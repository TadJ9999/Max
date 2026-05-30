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
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import __version__
from .config import load_config
from .dsl import ParseError, parse_command
from .prompts import messages_for
from .providers.base import Provider
from .providers.factory import build_provider
from .router import resolve

app = FastAPI(title="Max Engine", version=__version__)
config = load_config()


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
            {"index": 0, "message": {"role": "assistant", "content": text},
             "finish_reason": "stop"}
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


# TODO(Phase 4): /sessions  (delegate: spawn / list / cancel)
