"""Max engine — FastAPI entrypoint.

Run::

    uvicorn max_engine.main:app --reload

Endpoints here are an early skeleton. ``/parse`` already exercises the real DSL
parser + router so the command grammar can be tested end-to-end before the
provider adapters exist.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import __version__
from .config import load_config
from .dsl import ParseError, parse_command
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


# TODO(Phase 1): /v1/chat/completions (OpenAI-compatible, streaming)
# TODO(Phase 4): /sessions  (delegate: spawn / list / cancel)
