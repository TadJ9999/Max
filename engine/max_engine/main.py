"""Max engine — FastAPI entrypoint.

Run::

    uvicorn max_engine.main:app --reload

* ``/parse``                 — inspect how a DSL command would route (no inference)
* ``/v1/chat/completions``   — OpenAI-compatible streaming chat (pick a provider)
* ``/command``               — full path: parse a DSL command -> route -> stream
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import __version__
from .aegis import AegisCapture, AegisService, AegisStore
from .apollo import ApolloService, VectorStore
from .complete import fim_complete
from .config import load_config, save_overrides
from .delegate.engine import DelegateEngine
from .delegate.session import TERMINAL_STATES
from .dsl import ParseError, parse_command
from .market import MarketService, board_digest
from .osint import EventsService, NavalService, OsintService
from .polymarket import PolymarketService
from .polymarket.embedder import embed_markets
from .prompts import market_chat_messages, messages_for, polymarket_chat_messages, rag_messages
from .providers.base import Provider
from .providers.factory import build_provider
from .rag import RagService, RagStore, SessionMemory
from .router import model_for, resolve

# Load engine/.env (e.g. ANTHROPIC_API_KEY) if present, before providers read it.
# Explicit path so it works regardless of the launch directory; override=True so
# the file is authoritative over a stale/empty pre-existing env var.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

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
osint = OsintService(
    feeds=config.osint.feeds,
    query=config.osint.gdelt_query,
    timespan=config.osint.gdelt_timespan,
    max_records=config.osint.gdelt_max_records,
    ttl_seconds=config.osint.ttl_seconds,
)
naval = NavalService(
    twz_url=config.osint.naval_twz_url,
    ttl_seconds=config.osint.naval_ttl_seconds,
)
events = EventsService()
market = MarketService(
    symbols=config.market.watchlist,
    api_key=os.environ.get("FINNHUB_API_KEY"),
    ttl_seconds=config.market.ttl_seconds,
)
polymarket_svc = PolymarketService(
    watchlist=config.polymarket.watchlist,
    ttl_seconds=config.polymarket.ttl_seconds,
    embed_enabled=config.polymarket.embed_enabled,
    categories=config.polymarket.categories,
)
_polymarket_embedded_count: int = 0


def _make_store(path: str) -> VectorStore | None:
    """Best-effort: a VectorStore if sqlite-vec loads, else None (Apollo still
    runs, just without memory)."""
    try:
        store = VectorStore(path)
        store.stats()  # forces connect + extension load; surfaces failure now
        return store
    except Exception as e:  # pragma: no cover - environment-dependent
        print(f"[apollo] vector store unavailable ({e}); memory disabled")
        return None


_ollama_pc = next((p for p in config.providers if p.name == "ollama"), None)
_ollama_base = _ollama_pc.base_url if _ollama_pc else "http://127.0.0.1:11434"
rag = RagService(
    RagStore(config.rag.db_path),
    embed_model=config.rag.embed_model,
    base_url=_ollama_base,
    max_chars=config.rag.max_chars,
    overlap_lines=config.rag.overlap_lines,
)
rag_memory = SessionMemory()
apollo = ApolloService(
    osint=osint,
    market=market,
    store=_make_store(config.apollo.db_path),
    embed_model=config.apollo.embed_model,
    base_url=(_ollama_pc.base_url if _ollama_pc else "http://127.0.0.1:11434"),
    ttl_seconds=config.apollo.ttl_seconds,
    retrieve_k=config.apollo.retrieve_k,
)

_aegis_store = AegisStore(config.apollo.db_path)
_aegis_capture = AegisCapture(_aegis_store)
aegis_svc = AegisService(
    store=_aegis_store,
    config=config,
    repo_root=str(Path(__file__).resolve().parent.parent.parent),
)

# Register Aegis as the global FastAPI exception handler so unhandled errors
# are captured into the event store before the 500 response is returned.
app.add_exception_handler(Exception, _aegis_capture.fastapi_handler)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


# ---- Settings (UI-editable config) -------------------------------------


def _config_view() -> dict:
    """The UI-facing settings. Never exposes API key values — only whether they are set."""
    return {
        "allow_cloud": config.allow_cloud,
        "cloud_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "finnhub_key_set": bool(os.environ.get("FINNHUB_API_KEY")),
        "delegate": {
            "mode": config.delegate.mode,
            "max_parallel_local": config.delegate.max_parallel_local,
            "max_parallel_cloud": config.delegate.max_parallel_cloud,
        },
        "idle": {"keep_alive": config.idle.keep_alive},
        "workspace_allowlist": config.workspace_allowlist,
        "osint": {
            "gdelt_query": config.osint.gdelt_query,
            "gdelt_timespan": config.osint.gdelt_timespan,
            "gdelt_max_records": config.osint.gdelt_max_records,
            "ttl_seconds": config.osint.ttl_seconds,
            "naval_ttl_seconds": config.osint.naval_ttl_seconds,
            "feeds": config.osint.feeds,
        },
        "market": {
            "watchlist": config.market.watchlist,
            "ttl_seconds": config.market.ttl_seconds,
        },
        "polymarket": {
            "watchlist": config.polymarket.watchlist,
            "ttl_seconds": config.polymarket.ttl_seconds,
            "embed_enabled": config.polymarket.embed_enabled,
            "categories": config.polymarket.categories,
        },
        "apollo": {
            "embed_model": config.apollo.embed_model,
            "db_path": config.apollo.db_path,
            "ttl_seconds": config.apollo.ttl_seconds,
            "retrieve_k": config.apollo.retrieve_k,
        },
        "providers": [
            {"name": p.name, "kind": p.kind, "base_url": p.base_url}
            for p in config.providers
        ],
    }


@app.get("/config")
def get_config() -> dict:
    return _config_view()


class DelegatePatch(BaseModel):
    mode: str | None = None
    max_parallel_local: int | None = None
    max_parallel_cloud: int | None = None


class IdlePatch(BaseModel):
    keep_alive: str | None = None


class OsintPatch(BaseModel):
    gdelt_query: str | None = None
    gdelt_timespan: str | None = None
    gdelt_max_records: int | None = None
    ttl_seconds: int | None = None
    naval_ttl_seconds: int | None = None
    feeds: list[str] | None = None


class MarketPatch(BaseModel):
    watchlist: list[str] | None = None
    ttl_seconds: int | None = None


class ApolloPatch(BaseModel):
    embed_model: str | None = None
    ttl_seconds: int | None = None
    retrieve_k: int | None = None


class PolymarketPatch(BaseModel):
    watchlist: list[str] | None = None
    ttl_seconds: int | None = None
    embed_enabled: bool | None = None
    categories: list[str] | None = None


class ConfigPatch(BaseModel):
    allow_cloud: bool | None = None
    workspace_allowlist: list[str] | None = None
    delegate: DelegatePatch | None = None
    idle: IdlePatch | None = None
    osint: OsintPatch | None = None
    market: MarketPatch | None = None
    polymarket: PolymarketPatch | None = None
    apollo: ApolloPatch | None = None


@app.put("/config")
def update_config(patch: ConfigPatch) -> dict:
    """Apply UI settings to the live config and persist them."""
    if patch.allow_cloud is not None:
        config.allow_cloud = patch.allow_cloud
    if patch.workspace_allowlist is not None:
        config.workspace_allowlist = patch.workspace_allowlist
    if patch.delegate is not None:
        d = patch.delegate
        if d.mode is not None:
            if d.mode not in ("manual", "smart-auto"):
                raise HTTPException(status_code=400, detail="mode must be 'manual' or 'smart-auto'")
            config.delegate.mode = d.mode
        if d.max_parallel_local is not None:
            config.delegate.max_parallel_local = max(1, d.max_parallel_local)
        if d.max_parallel_cloud is not None:
            config.delegate.max_parallel_cloud = max(1, d.max_parallel_cloud)
    if patch.idle is not None and patch.idle.keep_alive is not None:
        config.idle.keep_alive = patch.idle.keep_alive
    if patch.osint is not None:
        o = patch.osint
        if o.gdelt_query is not None:
            config.osint.gdelt_query = o.gdelt_query
        if o.gdelt_timespan is not None:
            config.osint.gdelt_timespan = o.gdelt_timespan
        if o.gdelt_max_records is not None:
            config.osint.gdelt_max_records = max(10, o.gdelt_max_records)
        if o.ttl_seconds is not None:
            config.osint.ttl_seconds = max(60, o.ttl_seconds)
        if o.naval_ttl_seconds is not None:
            config.osint.naval_ttl_seconds = max(3600, o.naval_ttl_seconds)
        if o.feeds is not None:
            config.osint.feeds = o.feeds
    if patch.market is not None:
        m = patch.market
        if m.watchlist is not None:
            config.market.watchlist = m.watchlist
            market.set_watchlist(m.watchlist)
        if m.ttl_seconds is not None:
            config.market.ttl_seconds = max(5, m.ttl_seconds)
    if patch.polymarket is not None:
        pm = patch.polymarket
        if pm.watchlist is not None:
            config.polymarket.watchlist = pm.watchlist
            polymarket_svc.set_watchlist(pm.watchlist)
        if pm.ttl_seconds is not None:
            config.polymarket.ttl_seconds = max(30, pm.ttl_seconds)
        if pm.embed_enabled is not None:
            config.polymarket.embed_enabled = pm.embed_enabled
        if pm.categories is not None:
            config.polymarket.categories = pm.categories
    if patch.apollo is not None:
        a = patch.apollo
        if a.embed_model is not None:
            config.apollo.embed_model = a.embed_model
        if a.ttl_seconds is not None:
            config.apollo.ttl_seconds = max(3600, a.ttl_seconds)
        if a.retrieve_k is not None:
            config.apollo.retrieve_k = max(1, a.retrieve_k)
    save_overrides(config)
    return _config_view()


class KeyPatch(BaseModel):
    name: str   # e.g. "ANTHROPIC_API_KEY" or "FINNHUB_API_KEY"
    value: str  # new value — write-only; never returned


@app.post("/config/key")
def set_api_key(patch: KeyPatch) -> dict:
    """Write an API key to engine/.env and reload it into the running process.

    Accepted names: ANTHROPIC_API_KEY, FINNHUB_API_KEY. The value is stored in
    the .env file only — it is never echoed back to the caller."""
    allowed = {"ANTHROPIC_API_KEY", "FINNHUB_API_KEY"}
    if patch.name not in allowed:
        raise HTTPException(status_code=400, detail=f"Unknown key name '{patch.name}'")
    env_path = Path(__file__).resolve().parent.parent / ".env"
    lines: list[str] = env_path.read_text().splitlines() if env_path.exists() else []
    found = False
    new_lines: list[str] = []
    for line in lines:
        if line.startswith(f"{patch.name}="):
            new_lines.append(f"{patch.name}={patch.value}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{patch.name}={patch.value}")
    env_path.write_text("\n".join(new_lines) + "\n")
    os.environ[patch.name] = patch.value
    return _config_view()


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


def _sse_stream(
    provider: Provider,
    model: str,
    messages: list[dict],
    on_done: Callable[[str], None] | None = None,
) -> StreamingResponse:
    """Stream a provider response as OpenAI-compatible SSE chunks. If ``on_done``
    is given, it's called with the full assembled text after a clean finish (used
    to record a turn into session memory)."""

    async def event_stream() -> AsyncIterator[str]:
        parts: list[str] = []
        try:
            async for chunk in provider.chat(model, messages):
                parts.append(chunk.text)
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
            if on_done is not None:
                on_done("".join(parts))
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


class CompleteRequest(BaseModel):
    prefix: str
    suffix: str = ""
    model: str | None = None  # default: the configured fast "completion" model
    max_tokens: int = 96


@app.post("/complete")
async def complete(req: CompleteRequest) -> dict:
    """Fill-in-the-middle code completion (ghost text for the VS Code extension).
    Uses the fast local completion model unless ``model`` is given."""
    model = req.model or config.task_models.get("completion", "qwen2.5-coder:3b")
    text = await fim_complete(
        req.prefix,
        req.suffix,
        model=model,
        base_url=_ollama_base,
        max_tokens=req.max_tokens,
    )
    return {"completion": text, "model": model}


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


class CoordinateRequest(BaseModel):
    request: str
    planner: str | None = None  # provider override; default decided by delegate mode
    max_subtasks: int = 6


@app.post("/sessions/coordinate")
async def coordinate_sessions(req: CoordinateRequest):
    """Auto-delegate: a planner model splits one request into independent
    subtasks, each fanned out as a parallel session under the same scheduler."""
    try:
        return await delegate.coordinate(
            req.request, planner=req.planner, max_subtasks=req.max_subtasks
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


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


@app.get("/sessions/{session_id}/stream")
async def stream_session(session_id: str):
    """Live per-session output as SSE: replays output so far, then streams new
    chunks until the session reaches a terminal state. Lets the task cards show
    tokens as they're produced instead of only on the ~2s poll."""
    s = delegate.manager.get(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="no such session")

    async def event_stream() -> AsyncIterator[str]:
        q = s.subscribe()
        try:
            if s.output:  # catch-up for a mid-run (or finished) connect
                yield f"data: {json.dumps({'type': 'snapshot', 'text': s.output})}\n\n"
            if s.state in TERMINAL_STATES:
                yield f"data: {json.dumps({'type': 'done', 'state': s.state.value})}\n\n"
                return
            while True:
                ev = await q.get()
                yield f"data: {json.dumps(ev)}\n\n"
                if ev["type"] == "done":
                    return
        finally:
            s.unsubscribe(q)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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


# ---- Codebase RAG -------------------------------------------------------


def _within_allowlist(roots: list[str]) -> list[str]:
    """Restrict requested roots to paths inside the workspace allowlist (privacy:
    Max only ever indexes folders the user has explicitly opted in)."""
    allow = [os.path.abspath(p) for p in config.workspace_allowlist]
    if not allow:
        return []
    out = []
    for r in roots:
        ra = os.path.abspath(r)
        if any(ra == a or ra.startswith(a + os.sep) for a in allow):
            out.append(ra)
    return out


class RagIndexRequest(BaseModel):
    roots: list[str] | None = None  # default: the whole workspace allowlist


@app.post("/rag/index")
async def rag_index(req: RagIndexRequest):
    """(Re)index the workspace allowlist (incremental). Pass ``roots`` to scope to
    a subset — anything outside the allowlist is ignored."""
    requested = req.roots if req.roots is not None else config.workspace_allowlist
    return await rag.index(_within_allowlist(requested))


class RagSearchRequest(BaseModel):
    query: str
    k: int | None = None


@app.post("/rag/search")
async def rag_search(req: RagSearchRequest):
    return {"hits": await rag.search(req.query, k=req.k or config.rag.retrieve_k)}


@app.get("/rag/status")
def rag_status() -> dict:
    return {**rag.status(), "allowlist": config.workspace_allowlist}


@app.post("/rag/clear")
def rag_clear() -> dict:
    rag.store.clear()
    return rag.status()


class RagAskRequest(BaseModel):
    question: str
    k: int | None = None
    provider: str = "ollama"
    session_id: str | None = None  # opt-in conversational memory across turns


@app.post("/rag/ask")
async def rag_ask(req: RagAskRequest):
    """Retrieve workspace context for the question, then stream a grounded answer
    (cited by file:line). Falls back gracefully when nothing is indexed.

    With a ``session_id``, prior turns are fed to the model and the last user
    turns widen retrieval (so a terse follow-up still pulls the right code); the
    new Q&A is appended to that session's memory on completion."""
    sid = req.session_id
    history = rag_memory.history(sid) if sid else []

    # Widen the retrieval query with recent user turns for follow-up continuity.
    retrieval_query = req.question
    if sid:
        recent = rag_memory.recent_user_text(sid)
        if recent:
            retrieval_query = f"{recent}\n{req.question}"
    context = await rag.context_for(retrieval_query, k=req.k or config.rag.retrieve_k)

    try:
        provider = build_provider(req.provider, config)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    model = model_for(req.provider, "chat", config)

    on_done = None
    if sid:

        def on_done(answer: str) -> None:
            rag_memory.append(sid, "user", req.question)
            rag_memory.append(sid, "assistant", answer)

    return _sse_stream(provider, model, rag_messages(context, req.question, history), on_done)


@app.get("/rag/memory/{session_id}")
def rag_memory_get(session_id: str) -> dict:
    return {"session_id": session_id, "history": rag_memory.history(session_id)}


@app.post("/rag/memory/{session_id}/clear")
def rag_memory_clear(session_id: str) -> dict:
    rag_memory.clear(session_id)
    return {"session_id": session_id, "history": []}


# ---- OSINT: global news heat map ---------------------------------------


@app.get("/osint/heatmap")
async def osint_heatmap() -> dict:
    """Per-country news intensity (0..1) from GDELT + RSS, cached for a TTL.

    Outbound egress to public news services; aggregated in the engine so the
    client stays thin. Returns empty ``countries`` if every source is unreachable.
    """
    heatmap = await osint.get_heatmap()
    return heatmap.to_dict()


@app.get("/osint/articles")
async def osint_articles(country: str | None = None, limit: int = 50) -> dict:
    """Ranked articles, newest first. Pass ``country`` (ISO-A3) to scope to one;
    omit it for the global top."""
    articles = await osint.get_articles(iso=country, limit=limit)
    return {
        "country": country.upper() if country else None,
        "articles": [a.to_dict() for a in articles],
    }


@app.get("/osint/sources")
def osint_sources() -> dict:
    """Where the heat map's data comes from (for the UI's source panel)."""
    return osint.sources()


@app.get("/osint/events")
async def osint_events() -> dict:
    """Geospatial event markers (earthquakes ≥ M4.5, GDACS disaster alerts).
    Free, key-less sources; cached 5 min. Overlay-ready lat/lon + severity."""
    return await events.get()


@app.get("/osint/naval")
async def osint_naval_endpoint() -> dict:
    """US carrier / big-deck amphib position *estimates* from public OSINT
    trackers (USNI + TWZ). Region-level and dated — not real-time GPS."""
    return await naval.get()


class OsintChatRequest(BaseModel):
    messages: list[ChatMessage]
    country: str | None = None  # ISO-A3 to focus context; None = global


@app.post("/osint/chat")
async def osint_chat(req: OsintChatRequest):
    """AI chat grounded in indexed OSINT articles + broader reasoning.

    The system prompt includes the most recent headlines so the model can
    cite them, then instructs it to cross-reference with its own knowledge
    to verify and extend the analysis. Cloud Claude when allowed, else local."""
    articles = await osint.get_articles(iso=req.country, limit=20)
    article_lines = "\n".join(
        f"• [Sev {a.severity}] {a.title} ({a.domain}): {a.summary or '(no summary)'}"
        for a in articles[:15]
    )
    country_ctx = f"Focused on: {req.country.upper()}" if req.country else "Global view — all regions"
    system = (
        "You are an elite OSINT intelligence analyst embedded in the Max platform. "
        f"{country_ctx}.\n\n"
        "INDEXED INTELLIGENCE (last 24 h, ranked by severity):\n"
        f"{article_lines}\n\n"
        "GUIDELINES:\n"
        "- Lead with the indexed data, but cross-reference with your broader knowledge "
        "to verify, add context, and surface patterns the data alone doesn't show.\n"
        "- Clearly flag when you go beyond indexed sources: prefix such sentences with "
        "'[Broader knowledge]'.\n"
        "- If asked to verify a specific claim, state your confidence (High / Medium / Low) "
        "and why.\n"
        "- Be concise and structured; use bullet points for multi-part answers.\n"
        "- Never fabricate specific numbers, dates, or names — say 'unverified' if uncertain."
    )
    history = [m.model_dump() for m in req.messages]
    provider_name, model = _ai_route()
    provider = build_provider(provider_name, config)
    messages = [{"role": "system", "content": system}, *history]
    return _sse_stream(provider, model, messages)


# ---- Market: live US-stock board + AI "Ingest" -------------------------


def _ai_route() -> tuple[str, str]:
    """Pick (provider, model) for an AI analysis stream: cloud Claude when
    allowed, else the local default. Mirrors the resolve() cloud gate without the
    DSL. Used by Market and Apollo."""
    if config.allow_cloud:
        model = config.provider_models.get("claude", {}).get("chat", "claude-sonnet-4-6")
        return "claude", model
    return "ollama", config.task_models.get("chat", "qwen2.5-coder:14b")


def _stream_ai(action: str, payload: dict) -> StreamingResponse:
    """Route to cloud/local, build messages for ``action`` from a JSON payload,
    and stream the reply. The shared path behind Market analyze + Apollo reports."""
    provider_name, model = _ai_route()
    try:
        provider = build_provider(provider_name, config)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _sse_stream(provider, model, messages_for(action, json.dumps(payload)))


@app.get("/market/quotes")
async def market_quotes() -> dict:
    """Live quotes for the watchlist (Finnhub), cached for a short TTL. Returns an
    empty board if ``FINNHUB_API_KEY`` is unset or every fetch fails."""
    board = await market.get_board()
    return board.to_dict()


@app.get("/market/watchlist")
def market_watchlist() -> dict:
    return {"watchlist": market.get_watchlist()}


class WatchlistPatch(BaseModel):
    symbols: list[str]


@app.put("/market/watchlist")
def market_set_watchlist(patch: WatchlistPatch) -> dict:
    """Replace the watchlist and persist it (user-editable, survives restarts)."""
    symbols = market.set_watchlist(patch.symbols)
    config.market.watchlist = symbols
    save_overrides(config)
    return {"watchlist": symbols}


@app.get("/market/sources")
def market_sources() -> dict:
    """Where the board's data comes from + whether the API key is set (for the UI)."""
    return market.sources()


@app.post("/market/analyze")
async def market_analyze():
    """The "Ingest" action: snapshot the live board (quotes + computed breadth +
    recent market news) and stream a structured AI read of it.

    Routes to cloud Claude when ``allow_cloud`` is on, else the local model.
    Informational only — not financial advice (see the ``market`` prompt)."""
    board = await market.get_board()
    news = await market.get_news(count=8)
    payload = {"board": board.to_dict(), "stats": board_digest(board), "news": news}
    return _stream_ai("market", payload)


class MarketChatRequest(BaseModel):
    messages: list[ChatMessage]


@app.post("/market/chat")
async def market_chat_endpoint(req: MarketChatRequest):
    """Conversational Q&A about the live board, through the same AI pipeline as
    Ingest (cloud Claude when ``allow_cloud`` is on, else the local model). The
    current board snapshot is folded into the system prompt. Informational only."""
    board = await market.get_board()
    snapshot = json.dumps(board.to_dict())
    provider_name, model = _ai_route()
    try:
        provider = build_provider(provider_name, config)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    history = [msg.model_dump() for msg in req.messages]
    messages = market_chat_messages(snapshot, history)
    return _sse_stream(provider, model, messages)


# ---- Polymarket: prediction markets ------------------------------------


@app.get("/polymarket/board")
async def polymarket_board() -> dict:
    """Top active prediction markets by 24h volume, cached for a short TTL.

    No API key required — Polymarket's public APIs are open read access."""
    board = await polymarket_svc.get_board()
    return board.to_dict()


@app.get("/polymarket/markets")
async def polymarket_markets(
    category: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Fetch prediction markets, optionally filtered by category."""
    markets = await polymarket_svc.get_markets(
        category=category, limit=min(limit, 100), offset=offset
    )
    return {"category": category, "count": len(markets), "markets": [m.to_dict() for m in markets]}


@app.get("/polymarket/watchlist")
async def polymarket_get_watchlist() -> dict:
    markets = await polymarket_svc.get_watchlist_markets()
    return {
        "watchlist": polymarket_svc.get_watchlist(),
        "count": len(markets),
        "markets": [m.to_dict() for m in markets],
    }


class PolymarketWatchlistPatch(BaseModel):
    condition_ids: list[str]


@app.put("/polymarket/watchlist")
def polymarket_set_watchlist(patch: PolymarketWatchlistPatch) -> dict:
    """Replace the prediction-market watchlist and persist it."""
    ids = polymarket_svc.set_watchlist(patch.condition_ids)
    config.polymarket.watchlist = ids
    save_overrides(config)
    return {"watchlist": ids}


@app.get("/polymarket/prices/{condition_id}")
async def polymarket_prices(condition_id: str, interval: str = "1w") -> dict:
    """Price (probability) history for a market's YES outcome."""
    if interval not in ("1d", "1w", "1m", "max"):
        interval = "1w"
    points = await polymarket_svc.get_price_history(condition_id, interval=interval)
    return {
        "conditionId": condition_id,
        "interval": interval,
        "history": [{"t": p.t, "p": round(p.p, 4)} for p in points],
    }


@app.get("/polymarket/order-book/{token_id}")
async def polymarket_order_book(token_id: str) -> dict:
    """Order book (bid/ask depth) for one outcome token from the CLOB API."""
    book = await polymarket_svc.get_order_book(token_id)
    if book is None:
        return {"tokenId": token_id, "bids": [], "asks": []}
    return {"tokenId": token_id, **book.to_dict()}


@app.get("/polymarket/sources")
def polymarket_sources() -> dict:
    """Data sources, API status, and embed stats."""
    return polymarket_svc.sources(embedded_count=_polymarket_embedded_count)


@app.post("/polymarket/ingest")
async def polymarket_ingest() -> StreamingResponse:
    """Re-fetch the top markets and embed them into Apollo's vector store (SSE).

    Streams status events so the UI can show progress. Embedding is best-effort:
    if Ollama is unavailable the markets are still refreshed, just not embedded."""
    global _polymarket_embedded_count

    async def gen():
        try:
            yield _ev({"object": "polymarket.status", "stage": "Fetching markets from Polymarket…"})
            await polymarket_svc.refresh(force=True)
            board = await polymarket_svc.get_board()
            yield _ev({"object": "polymarket.status", "stage": f"Fetched {len(board.markets)} markets"})

            store = apollo._store  # reuse Apollo's vector store
            if store is not None and config.polymarket.embed_enabled:
                yield _ev({"object": "polymarket.status", "stage": "Embedding → Apollo vector memory…"})
                n = await embed_markets(
                    board.markets,
                    store,
                    embed_model=config.apollo.embed_model,
                    base_url=_ollama_base,
                    ttl_seconds=config.apollo.ttl_seconds,
                )
                _polymarket_embedded_count = n
                yield _ev({"object": "polymarket.status", "stage": f"Embedded {n} markets into memory"})
            else:
                yield _ev({"object": "polymarket.status", "stage": "Embedding skipped (store unavailable or disabled)"})

            yield "data: [DONE]\n\n"
        except Exception as e:
            yield _ev({"error": {"message": str(e), "type": type(e).__name__}})

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/polymarket/analyze")
async def polymarket_analyze() -> StreamingResponse:
    """AI brief on the current prediction-market board (SSE).

    Routes to cloud Claude when ``allow_cloud`` is on, else local. Informational
    only — not financial advice."""
    board = await polymarket_svc.get_board()
    payload = {"markets": [m.to_dict() for m in board.markets[:30]]}
    return _stream_ai("polymarket", payload)


class PolymarketChatRequest(BaseModel):
    messages: list[ChatMessage]


@app.post("/polymarket/chat")
async def polymarket_chat(req: PolymarketChatRequest) -> StreamingResponse:
    """Conversational Q&A about the live prediction-market board (SSE).

    The current board snapshot is folded into the system prompt. Informational only."""
    board = await polymarket_svc.get_board()
    snapshot = json.dumps({"markets": [m.to_dict() for m in board.markets[:30]]})
    provider_name, model = _ai_route()
    try:
        provider = build_provider(provider_name, config)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    history = [msg.model_dump() for msg in req.messages]
    messages = polymarket_chat_messages(snapshot, history)
    return _sse_stream(provider, model, messages)


# ---- Local model lifecycle ---------------------------------------------


@app.post("/engine/unload")
async def engine_unload() -> dict:
    """Free the local chat model from RAM/VRAM now (Ollama ``keep_alive=0``).
    It reloads automatically on the next local request. Idle models also unload
    on their own after ``config.idle.keep_alive`` (see settings)."""
    model = config.task_models.get("chat", "qwen2.5-coder:14b")
    provider = build_provider("ollama", config)
    unloaded = await provider.unload(model)  # type: ignore[attr-defined]
    return {"unloaded": unloaded, "model": model, "keep_alive": config.idle.keep_alive}


# ---- Aegis: self-repair console ----------------------------------------


@app.get("/aegis/events")
def aegis_events(limit: int = 50) -> dict:
    """Recent captured error events, newest-first."""
    return {"events": aegis_svc.get_events(limit=limit)}


class AegisReportRequest(BaseModel):
    source: str = "frontend"
    severity: str = "Medium"
    kind: str = "ClientError"
    message: str
    traceback: str | None = None
    context: dict | None = None


@app.post("/aegis/report")
def aegis_report(req: AegisReportRequest) -> dict:
    """Accept an error event from the frontend or Rust layer."""
    eid = _aegis_capture.ingest_report(req.model_dump())
    return {"event_id": eid}


class AegisDiagnoseRequest(BaseModel):
    event_id: str


@app.post("/aegis/diagnose")
async def aegis_diagnose(req: AegisDiagnoseRequest) -> StreamingResponse:
    """SSE — AI diagnosis of a captured event → root cause + unified diff."""
    event = aegis_svc.store.get_event(req.event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")
    return StreamingResponse(aegis_svc.diagnose(req.event_id), media_type="text/event-stream")


class AegisApplyRequest(BaseModel):
    event_id: str
    diff: str
    log_id: str | None = None


@app.post("/aegis/apply")
def aegis_apply(req: AegisApplyRequest) -> dict:
    """Apply an approved patch: snapshot → validate → apply → verify → keep or rollback."""
    try:
        return aegis_svc.apply(req.event_id, req.diff, req.log_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


class AegisRollbackRequest(BaseModel):
    snapshot_ref: str
    log_id: str | None = None


@app.post("/aegis/rollback")
def aegis_rollback(req: AegisRollbackRequest) -> dict:
    """Revert the last applied fix via git stash pop."""
    return aegis_svc.rollback(req.snapshot_ref, req.log_id)


@app.get("/aegis/log")
def aegis_log(limit: int = 100) -> dict:
    """Structured history of all diagnosis + apply actions."""
    return {"log": aegis_svc.get_log(limit=limit)}


@app.get("/aegis/sources")
def aegis_sources() -> dict:
    """Current provider status, autonomy level, store path."""
    return aegis_svc.sources()


# ---- Apollo: prediction engine -----------------------------------------
#
# Apollo's SSE carries two kinds of events besides the model deltas:
#   {"object":"apollo.status","stage":..., "db":0|1|-1}  — live call trace; `db`
#       is +1 for a vector-memory WRITE, -1 for a READ, 0 otherwise (drives the
#       UI call-log + the mascot's "learning" pulse).
# Model text uses the same chat.completion.chunk shape as everywhere else.


def _ev(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _status_ev(stage: str, db: int = 0) -> str:
    return _ev({"object": "apollo.status", "stage": stage, "db": db})


def _delta_ev(text: str, model: str) -> str:
    return _ev(
        {
            "object": "chat.completion.chunk",
            "model": model,
            "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
        }
    )


async def _apollo_run(kind: str):
    """Generator for an Apollo report/prediction: emit a real call trace as each
    stage runs (aggregate → embed/store or retrieve → generate), then stream the
    model. ``kind`` is 'osint' | 'market' | 'predict'."""

    async def gen():
        try:
            yield _status_ev("Contacting engine…")
            if kind == "osint":
                yield _status_ev("Pulling GDELT + RSS feeds…")
                payload = await apollo.osint_payload()
                yield _status_ev("Scoring severity · ranking hotspots…")
                yield _status_ev("Embedding criticals → vector memory", db=1)
                n = await apollo.ingest_osint(payload)
                yield _status_ev(f"Wrote {n} memories · purged >24h", db=1)
                action = "apollo_osint"
            elif kind == "market":
                yield _status_ev("Fetching quotes · breadth · market news…")
                payload = await apollo.market_payload()
                yield _status_ev("Embedding market snapshot → vector memory", db=1)
                n = await apollo.ingest_market(payload)
                yield _status_ev(f"Wrote {n} memories · purged >24h", db=1)
                action = "apollo_market"
            else:  # predict
                yield _status_ev("Assembling OSINT + market signals…")
                payload = await apollo.combined_payload()
                yield _status_ev("Recalling related memory (vector search)…", db=-1)
                memory = await apollo.retrieve_for_prediction(payload)
                yield _status_ev(f"Recalled {len(memory)} prior signals", db=-1)
                payload["memory"] = memory
                action = "apollo_predict"

            provider_name, model = _ai_route()
            yield _status_ev(f"Generating via {provider_name} · {model}…")
            provider = build_provider(provider_name, config)
            async for chunk in provider.chat(model, messages_for(action, json.dumps(payload))):
                if chunk.text:
                    yield _delta_ev(chunk.text, model)
            yield "data: [DONE]\n\n"
        except Exception as e:  # surface backend errors to the client
            yield _ev({"error": {"message": str(e), "type": type(e).__name__}})

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/apollo/osint-report")
async def apollo_osint_report():
    """Stream an AI situational report over the highest-severity world news,
    embedding the criticals into 24h vector memory as it goes."""
    return await _apollo_run("osint")


@app.post("/apollo/market-report")
async def apollo_market_report():
    """Stream an AI market report (quotes + breadth + news), embedding the
    snapshot into vector memory."""
    return await _apollo_run("market")


@app.post("/apollo/predict")
async def apollo_predict():
    """Stream forward-looking predictions on global conflicts + markets, grounded
    in the current brief, the live market, and recalled vector memory."""
    return await _apollo_run("predict")


@app.get("/apollo/status")
def apollo_status() -> dict:
    """Vector-memory stats (counts by kind, oldest/newest) for the UI."""
    return apollo.memory_stats()
