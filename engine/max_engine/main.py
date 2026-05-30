"""Max engine — FastAPI entrypoint.

Run::

    uvicorn max_engine.main:app --reload

Endpoints here are an early skeleton. ``/parse`` already exercises the real DSL
parser + router so the command grammar can be tested end-to-end before the
provider adapters exist.
"""

from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import __version__
from .config import load_config
from .dsl import ParseError, parse_command
from .providers.ollama import OllamaProvider
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
        "command": {
            "action": cmd.action,
            "body": cmd.body,
            "sigil": cmd.sigil,
        },
        "route": {
            "provider": route.provider,
            "model": route.model,
            "is_cloud": route.is_cloud,
        },
    }


def _ollama() -> OllamaProvider:
    """Build an Ollama provider from config."""
    p = next((p for p in config.providers if p.name == "ollama"), None)
    base_url = (p.base_url if p and p.base_url else "http://127.0.0.1:11434")
    return OllamaProvider(base_url=base_url)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    stream: bool = True


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    """OpenAI-compatible chat completion, backed by local Ollama.

    Note: requires a running Ollama server with the requested model pulled.
    """
    provider = _ollama()
    messages = [m.model_dump() for m in req.messages]

    if req.stream:
        async def event_stream():
            try:
                async for chunk in provider.chat(req.model, messages):
                    delta = {"content": chunk.text} if chunk.text else {}
                    payload = {
                        "object": "chat.completion.chunk",
                        "model": req.model,
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


# TODO(Phase 4): /sessions  (delegate: spawn / list / cancel)
