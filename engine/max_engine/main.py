"""Max engine — FastAPI entrypoint.

Run::

    uvicorn max_engine.main:app --reload

* ``/parse``                 — inspect how a DSL command would route (no inference)
* ``/v1/chat/completions``   — OpenAI-compatible streaming chat (pick a provider)
* ``/command``               — full path: parse a DSL command -> route -> stream
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import __version__
from .config import load_config
from .delegate.engine import DelegateEngine
from .dsl import ParseError, parse_command
from .prompts import messages_for
from .providers.base import Provider
from .providers.factory import build_provider
from .router import resolve

app = FastAPI(title="Max Engine", version=__version__)

# The engine binds to localhost and is consumed by local clients (the Tauri
# widget's webview, browser previews, VS Code). Allow any local origin so those
# clients can call it; tighten if the engine is ever exposed on the network.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

config = load_config()
delegate = DelegateEngine(config)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


class ParseRequest(BaseModel):
    text: str


@app.post("/parse")
def parse(req: ParseRequest) -> dict:
    """Parse a Max command and show how it would be routed (no inference yet)."""
    try:
        cmd = parse_command(req.text, sigils=config.sigils)
    except ParseError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    route = resolve(cmd, config)
    return {
        "command": {"action": cmd.action, "body": cmd.body, "sigil": cmd.sigil},
        "route": {
            "provider": route.provider,
            "model": route.model,
            "is_cloud": route.is_cloud,
        },
    }


def _sse_stream(provider: Provider, model: str, messages: list[dict]) -> StreamingResponse:
    """Stream a provider response as OpenAI-compatible SSE chunks."""

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for chunk in provider.chat(model, messages):
                delta = {"content": chunk.text} if chunk.text else {}
                payload = {
                    "object": "chat.completion.chunk",
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": delta,
                            "finish_reason": "stop" if chunk.done else None,
                        }
                    ],
                }
                yield f"data: {json.dumps(payload)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:  # surface backend errors to the client
            err = {"error": {"message": str(e), "type": type(e).__name__}}
            yield f"data: {json.dumps(err)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    stream: bool = True
    provider: str = "ollama"  # which adapter to use; default local


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    """OpenAI-compatible chat completion. Set ``provider`` to pick local/cloud.

    Note: local needs a running Ollama with the model pulled; cloud needs an API key.
    """
    try:
        provider = build_provider(req.provider, config)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    messages = [m.model_dump() for m in req.messages]

    if req.stream:
        return _sse_stream(provider, req.model, messages)

    text = ""
    async for chunk in provider.chat(req.model, messages):
        text += chunk.text
    return {
        "object": "chat.completion",
        "model": req.model,
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
        ],
    }


class CommandRequest(BaseModel):
    text: str


@app.post("/command")
async def command(req: CommandRequest):
    """Full DSL path: parse ``text``, resolve the route, stream from that provider.

    The ``!`` sigil routes to the cloud (blocked if ``allow_cloud`` is off).
    """
    try:
        cmd = parse_command(req.text, sigils=config.sigils)
    except ParseError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    try:
        route = resolve(cmd, config)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    provider = build_provider(route.provider, config)
    messages = messages_for(cmd.action, cmd.body)
    return _sse_stream(provider, route.model, messages)


class ChatTextRequest(BaseModel):
    text: str


@app.post("/chat")
async def chat(req: ChatTextRequest):
    """Plain conversational chat (no DSL operators required). Routes to the
    default local provider with the configured chat model and streams the reply.
    Use the ``/command`` endpoint for DSL commands (``.``/``..``/``~`` + sigils)."""
    provider = build_provider("ollama", config)
    model = config.task_models.get("chat", "qwen2.5-coder:14b")
    messages = messages_for("chat", req.text)
    return _sse_stream(provider, model, messages)


# ---- Delegate system: parallel sessions --------------------------------


class TaskSpec(BaseModel):
    task: str
    action: str = "generate"
    provider: str | None = None  # None => decided by delegate mode (Manual/Smart-Auto)
    complexity: float = 0.5  # Smart-Auto hint (0..1); higher => more likely cloud


class SubmitRequest(BaseModel):
    tasks: list[TaskSpec]


@app.post("/sessions")
async def create_sessions(req: SubmitRequest):
    """Fan out one or more tasks as isolated parallel sessions, then schedule them."""
    created = []
    for spec in req.tasks:
        try:
            s = delegate.submit(
                spec.task,
                action=spec.action,
                provider=spec.provider,
                complexity=spec.complexity,
            )
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e
        created.append(s)
    await delegate.kick()
    return {"sessions": [s.to_dict() for s in created]}


@app.get("/sessions")
def list_sessions():
    """List all sessions (isolated — each output viewed separately)."""
    return {"sessions": [s.to_dict() for s in delegate.manager.list()]}


@app.get("/sessions/{session_id}")
def get_session(session_id: str):
    s = delegate.manager.get(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="no such session")
    return s.to_dict()


@app.post("/sessions/{session_id}/cancel")
def cancel_session(session_id: str):
    if delegate.manager.get(session_id) is None:
        raise HTTPException(status_code=404, detail="no such session")
    delegate.cancel(session_id)
    return delegate.manager.get(session_id).to_dict()


@app.post("/sessions/{session_id}/promote")
async def promote_session(session_id: str):
    """Manual override: push a still-queued session to the cloud, then reschedule."""
    try:
        s = delegate.promote_to_cloud(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="no such session") from e
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    await delegate.kick()
    return s.to_dict()
