"""Max engine — FastAPI entrypoint.

Run::

    uvicorn max_engine.main:app --reload

* ``/parse``                 — inspect how a DSL command would route (no inference)
* ``/v1/chat/completions``   — OpenAI-compatible streaming chat (pick a provider)
* ``/command``               — full path: parse a DSL command -> route -> stream
"""

from __future__ import annotations

import asyncio
import json
import os
import sys as _sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import datetime as _dt
import time as _time

from . import __version__
from .capabilities import CapabilityRegistry, classify_intent
from .skills import (
    CalendarCapability, CalendarService,
    FilesCapability, FilesService,
    ReportCapability, ReportService,
    SpotifyCapability, SpotifyService,
    WebSearchCapability,
)
from .skills.web_search import ddg_search, _search_stream
from .aegis import AegisCapture, AegisService, AegisStore, ScanService
from .analytics.store import UsageStore
from .darknet import TorService
from .darknet.client import make_tor_client as _make_tor_client
from .darknet.fetcher import fetch_url as tor_fetch_url
from .apollo import ApolloService, VectorStore
from .apollo.predictions import PredictionHistory
from .user import UserProfileStore
from .complete import fim_complete
from .config import load_config, save_overrides
from .delegate.engine import DelegateEngine
from .delegate.session import TERMINAL_STATES
from .dsl import ParseError, parse_command
from .market import MarketService, board_digest
from .osint import EventsService, NavalService, OsintService
from .polymarket import PolymarketService
from .polymarket.embedder import embed_markets
from .sentinel import SentinelService
from .prompts import (
    SYSTEM_PROMPTS,
    apply_persona,
    market_chat_messages,
    messages_for,
    polymarket_chat_messages,
    rag_messages,
    sentinel_chat_messages,
)
from .providers.base import Provider
from .providers.factory import build_provider
from .providers.vram import VramManager
from .rag import RagService, RagStore, SessionMemory
from .router import model_for, resolve
from .models import BenchmarkStore, CLOUD_MODELS, list_ollama_models, pull_ollama_model, run_benchmark, vram_mb

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
    gdelt_enabled=config.osint.gdelt_enabled,
    rss_enabled=config.osint.rss_enabled,
    tone_signal=config.osint.tone_signal,
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
sentinel_svc = SentinelService(
    nasa_key=os.environ.get("NASA_API_KEY") or "DEMO_KEY",
    tle_ttl=config.sentinel.tle_ttl,
    neo_ttl=config.sentinel.neo_ttl,
    sw_ttl=config.sentinel.sw_ttl,
    fireball_ttl=config.sentinel.fireball_ttl,
    launch_ttl=config.sentinel.launch_ttl,
    iss_ttl=config.sentinel.iss_ttl,
)


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
_vram_mgr = VramManager(base_url=_ollama_base)
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
_profile_store = UserProfileStore(config.apollo.db_path)
_prediction_history = PredictionHistory(config.apollo.db_path)
_usage_store = UsageStore(config.apollo.db_path)
_repo_root = str(Path(__file__).resolve().parent.parent.parent)
aegis_svc = AegisService(
    store=_aegis_store,
    config=config,
    repo_root=_repo_root,
)
scan_svc = ScanService(
    store=_aegis_store,
    config=config,
    repo_root=_repo_root,
)
dark_svc = TorService(
    socks_port=config.darknet.socks_port,
    control_port=config.darknet.control_port,
)
_benchmark_store = BenchmarkStore(config.apollo.db_path.replace(".apollo.db", ".apollo.db"))

# ── Phase 9 — Capability platform & skills ───────────────────────────────────

_report_svc = ReportService()
_files_svc = FilesService(config.workspace_allowlist)
_spotify_svc = SpotifyService(
    config.spotify,
    client_id=os.environ.get("SPOTIFY_CLIENT_ID", ""),
    client_secret=os.environ.get("SPOTIFY_CLIENT_SECRET", ""),
)
_calendar_svc = CalendarService(
    config.gcal,
    client_id=os.environ.get("GOOGLE_CALENDAR_CLIENT_ID", ""),
    client_secret=os.environ.get("GOOGLE_CALENDAR_CLIENT_SECRET", ""),
)


def _register_capabilities() -> None:
    """Register all skill capabilities into the global registry."""
    registry = CapabilityRegistry.get()
    _provider = build_provider("ollama", config)
    _model = config.task_models.get("chat", "qwen2.5-coder:14b")
    registry.register(WebSearchCapability(_provider, _model))
    registry.register(ReportCapability(_report_svc, _provider, _model))
    registry.register(FilesCapability(_files_svc, _provider, _model))
    registry.register(SpotifyCapability(_spotify_svc))
    registry.register(CalendarCapability(_calendar_svc))


_register_capabilities()

# ── Analytics: usage tracking ────────────────────────────────────────────────

_FEATURE_MAP: list[tuple[str, str]] = [
    ("/skills/",      "skills"),
    ("/capabilities/","skills"),
    ("/apollo/",      "apollo"),
    ("/osint/",       "osint"),
    ("/market/",      "market"),
    ("/polymarket/",  "polymarket"),
    ("/sentinel/",    "sentinel"),
    ("/voice/",       "voice"),
    ("/rag/",         "rag"),
    ("/sessions/",    "delegate"),
    ("/command",      "chat"),
    ("/chat",         "chat"),
    ("/v1/chat/",     "api"),
]


def _feature_from_path(path: str) -> str:
    for prefix, feat in _FEATURE_MAP:
        if path.startswith(prefix):
            return feat
    return "system"


def _on_usage(feature: str, provider: str, model: str, in_tok: int, out_tok: int) -> None:
    ts = int(_time.time())
    day = _dt.date.today().isoformat()
    cost = _usage_store.calc_cost(provider, model, in_tok, out_tok)
    _usage_store.record(ts, day, feature, provider, model, in_tok, out_tok, cost)


from .providers.anthropic import set_usage_callback as _set_ant_cb
from .providers.ollama import set_usage_callback as _set_oll_cb
_set_ant_cb(_on_usage)
_set_oll_cb(_on_usage)

# Register Aegis as the global FastAPI exception handler so unhandled errors
# are captured into the event store before the 500 response is returned.
app.add_exception_handler(Exception, _aegis_capture.fastapi_handler)


@app.on_event("startup")
async def _startup() -> None:
    """Startup tasks: security scan scheduler + config hot-reload watcher."""
    import asyncio

    async def _scan_scheduler() -> None:
        if config.aegis.scan_on_startup:
            await scan_svc.run_scan("scheduled")
        while True:
            await asyncio.sleep(config.aegis.scan_interval_hours * 3600)
            if config.aegis.scan_enabled:
                await scan_svc.run_scan("scheduled")

    async def _config_hot_reload() -> None:
        """Re-apply .maxconfig.json onto the live config whenever the file changes."""
        from .config import CONFIG_FILE, _apply_overrides
        last_mtime: float = 0.0
        while True:
            await asyncio.sleep(5)
            try:
                mtime = CONFIG_FILE.stat().st_mtime if CONFIG_FILE.exists() else 0.0
                if mtime and mtime != last_mtime:
                    last_mtime = mtime
                    import json as _json
                    _apply_overrides(config, _json.loads(CONFIG_FILE.read_text()))
            except Exception:
                pass

    async def _warmup_resident() -> None:
        """Ping the resident completer model so Ollama pre-loads it into VRAM."""
        if not config.idle.resident_model:
            return
        try:
            provider = build_provider("ollama", config, model=config.idle.resident_model)
            async for _ in provider.chat(  # type: ignore[attr-defined]
                config.idle.resident_model,
                [{"role": "user", "content": "hi"}],
                num_predict=1,
            ):
                break
        except Exception:
            pass

    asyncio.create_task(_scan_scheduler())
    asyncio.create_task(_config_hot_reload())
    asyncio.create_task(_warmup_resident())


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


def _check_network() -> None:
    """Raise 503 when force_offline is active — all outbound calls are blocked."""
    if config.force_offline:
        raise HTTPException(status_code=503, detail="force_offline: all network calls are blocked")


# ---- Settings (UI-editable config) -------------------------------------


def _config_view() -> dict:
    """The UI-facing settings. Never exposes API key values — only whether they are set."""
    return {
        "allow_cloud": config.allow_cloud,
        "force_offline": config.force_offline,
        "cloud_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "openai_key_set": bool(os.environ.get("OPENAI_API_KEY")),
        "finnhub_key_set": bool(os.environ.get("FINNHUB_API_KEY")),
        "delegate": {
            "mode": config.delegate.mode,
            "max_parallel_local": config.delegate.max_parallel_local,
            "max_parallel_cloud": config.delegate.max_parallel_cloud,
        },
        "idle": {
            "keep_alive": config.idle.keep_alive,
            "resident_model": config.idle.resident_model,
            "resident_keep_alive": config.idle.resident_keep_alive,
            "vram_budget_mb": config.idle.vram_budget_mb,
        },
        "workspace_allowlist": config.workspace_allowlist,
        "osint": {
            "gdelt_query": config.osint.gdelt_query,
            "gdelt_timespan": config.osint.gdelt_timespan,
            "gdelt_max_records": config.osint.gdelt_max_records,
            "ttl_seconds": config.osint.ttl_seconds,
            "naval_ttl_seconds": config.osint.naval_ttl_seconds,
            "feeds": config.osint.feeds,
            "gdelt_enabled": config.osint.gdelt_enabled,
            "rss_enabled": config.osint.rss_enabled,
            "naval_enabled": config.osint.naval_enabled,
            "tone_signal": config.osint.tone_signal,
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
        "personality": {
            "persona": config.personality.persona,
            "user_name": config.personality.user_name,
            "custom_prefix": config.personality.custom_prefix,
        },
        "voice": {
            "stt_provider": config.voice.stt_provider,
            "whisper_model": config.voice.whisper_model,
            "tts_enabled": config.voice.tts_enabled,
            "tts_rate": config.voice.tts_rate,
            "tts_pitch": config.voice.tts_pitch,
            "tts_voice_name": config.voice.tts_voice_name,
        },
        "aegis": {
            "scan_enabled": config.aegis.scan_enabled,
            "scan_interval_hours": config.aegis.scan_interval_hours,
            "scan_on_startup": config.aegis.scan_on_startup,
            "scan_roots": config.aegis.scan_roots,
            "osv_enabled": config.aegis.osv_enabled,
            "osv_ttl_seconds": config.aegis.osv_ttl_seconds,
            "score_threshold": config.aegis.score_threshold,
            "autonomy": config.aegis.autonomy,
        },
        "task_models": config.task_models,
        "sigils": config.sigils,
        "provider_models": config.provider_models,
        "skills": {
            "intent_router_enabled": config.skills.intent_router_enabled,
            "intent_router_model": config.skills.intent_router_model,
        },
        "spotify": {
            "configured": bool(os.environ.get("SPOTIFY_CLIENT_ID") or config.spotify.client_id),
            "authenticated": bool(config.spotify.access_token),
            "client_id": (os.environ.get("SPOTIFY_CLIENT_ID") or config.spotify.client_id)[:8] + "..."
            if (os.environ.get("SPOTIFY_CLIENT_ID") or config.spotify.client_id) else "",
        },
        "gcal": {
            "configured": bool(
                (os.environ.get("GOOGLE_CALENDAR_CLIENT_ID") or config.gcal.client_id)
                and (os.environ.get("GOOGLE_CALENDAR_CLIENT_SECRET") or "")
            ),
            "authenticated": bool(config.gcal.access_token),
            "calendar_id": config.gcal.calendar_id,
        },
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
    resident_model: str | None = None
    resident_keep_alive: str | None = None
    vram_budget_mb: int | None = None


class OsintPatch(BaseModel):
    gdelt_query: str | None = None
    gdelt_timespan: str | None = None
    gdelt_max_records: int | None = None
    ttl_seconds: int | None = None
    naval_ttl_seconds: int | None = None
    feeds: list[str] | None = None
    gdelt_enabled: bool | None = None
    rss_enabled: bool | None = None
    naval_enabled: bool | None = None
    tone_signal: bool | None = None


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


class PersonalityPatch(BaseModel):
    persona: str | None = None
    user_name: str | None = None
    custom_prefix: str | None = None


class VoicePatch(BaseModel):
    stt_provider: str | None = None
    whisper_model: str | None = None
    tts_enabled: bool | None = None
    tts_rate: float | None = None
    tts_pitch: float | None = None
    tts_voice_name: str | None = None


class AegisPatch(BaseModel):
    scan_enabled: bool | None = None
    scan_interval_hours: int | None = None
    scan_on_startup: bool | None = None
    scan_roots: list[str] | None = None
    osv_enabled: bool | None = None
    osv_ttl_seconds: int | None = None
    score_threshold: int | None = None
    autonomy: str | None = None


class SkillsPatch(BaseModel):
    intent_router_enabled: bool | None = None
    intent_router_model: str | None = None


class SpotifyPatch(BaseModel):
    client_id: str | None = None


class GcalPatch(BaseModel):
    client_id: str | None = None
    calendar_id: str | None = None


class ConfigPatch(BaseModel):
    allow_cloud: bool | None = None
    force_offline: bool | None = None
    workspace_allowlist: list[str] | None = None
    delegate: DelegatePatch | None = None
    idle: IdlePatch | None = None
    osint: OsintPatch | None = None
    market: MarketPatch | None = None
    polymarket: PolymarketPatch | None = None
    apollo: ApolloPatch | None = None
    personality: PersonalityPatch | None = None
    voice: VoicePatch | None = None
    aegis: AegisPatch | None = None
    task_models: dict[str, str] | None = None
    sigils: dict[str, str] | None = None
    skills: SkillsPatch | None = None
    spotify: SpotifyPatch | None = None
    gcal: GcalPatch | None = None


@app.put("/config")
def update_config(patch: ConfigPatch) -> dict:
    """Apply UI settings to the live config and persist them."""
    if patch.allow_cloud is not None:
        config.allow_cloud = patch.allow_cloud
    if patch.force_offline is not None:
        config.force_offline = patch.force_offline
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
    if patch.idle is not None:
        idle = patch.idle
        if idle.keep_alive is not None:
            config.idle.keep_alive = idle.keep_alive
        if idle.resident_model is not None:
            config.idle.resident_model = idle.resident_model
        if idle.resident_keep_alive is not None:
            config.idle.resident_keep_alive = idle.resident_keep_alive
        if idle.vram_budget_mb is not None:
            config.idle.vram_budget_mb = max(1_000, idle.vram_budget_mb)
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
        if o.gdelt_enabled is not None:
            config.osint.gdelt_enabled = o.gdelt_enabled
            osint.gdelt_enabled = o.gdelt_enabled
        if o.rss_enabled is not None:
            config.osint.rss_enabled = o.rss_enabled
            osint.rss_enabled = o.rss_enabled
        if o.naval_enabled is not None:
            config.osint.naval_enabled = o.naval_enabled
        if o.tone_signal is not None:
            config.osint.tone_signal = o.tone_signal
            osint.tone_signal = o.tone_signal
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
    if patch.personality is not None:
        pers = patch.personality
        if pers.persona is not None:
            if pers.persona not in ("jarvis", "formal", "custom"):
                raise HTTPException(status_code=400, detail="persona must be 'jarvis', 'formal', or 'custom'")
            config.personality.persona = pers.persona
        if pers.user_name is not None:
            config.personality.user_name = pers.user_name
        if pers.custom_prefix is not None:
            config.personality.custom_prefix = pers.custom_prefix
    if patch.voice is not None:
        vo = patch.voice
        if vo.stt_provider is not None:
            if vo.stt_provider not in ("web", "whisper", "auto"):
                raise HTTPException(status_code=400, detail="stt_provider must be 'web', 'whisper', or 'auto'")
            config.voice.stt_provider = vo.stt_provider
        if vo.whisper_model is not None:
            config.voice.whisper_model = vo.whisper_model
        if vo.tts_enabled is not None:
            config.voice.tts_enabled = vo.tts_enabled
        if vo.tts_rate is not None:
            config.voice.tts_rate = max(0.5, min(2.0, vo.tts_rate))
        if vo.tts_pitch is not None:
            config.voice.tts_pitch = max(0.5, min(2.0, vo.tts_pitch))
        if vo.tts_voice_name is not None:
            config.voice.tts_voice_name = vo.tts_voice_name
    if patch.aegis is not None:
        ag = patch.aegis
        if ag.scan_enabled is not None:
            config.aegis.scan_enabled = ag.scan_enabled
        if ag.scan_interval_hours is not None:
            config.aegis.scan_interval_hours = max(1, ag.scan_interval_hours)
        if ag.scan_on_startup is not None:
            config.aegis.scan_on_startup = ag.scan_on_startup
        if ag.scan_roots is not None:
            config.aegis.scan_roots = ag.scan_roots
        if ag.osv_enabled is not None:
            config.aegis.osv_enabled = ag.osv_enabled
        if ag.osv_ttl_seconds is not None:
            config.aegis.osv_ttl_seconds = max(3600, ag.osv_ttl_seconds)
        if ag.score_threshold is not None:
            config.aegis.score_threshold = max(0, min(100, ag.score_threshold))
        if ag.autonomy is not None:
            if ag.autonomy not in ("suggest", "ask", "auto"):
                raise HTTPException(status_code=400, detail="autonomy must be 'suggest', 'ask', or 'auto'")
            config.aegis.autonomy = ag.autonomy
    if patch.task_models is not None:
        for task, model in patch.task_models.items():
            if task in config.task_models:
                config.task_models[task] = model
    if patch.sigils is not None:
        for sigil, provider in patch.sigils.items():
            config.sigils[sigil] = provider
    if patch.skills is not None:
        sk = patch.skills
        if sk.intent_router_enabled is not None:
            config.skills.intent_router_enabled = sk.intent_router_enabled
        if sk.intent_router_model is not None:
            config.skills.intent_router_model = sk.intent_router_model
    if patch.spotify is not None:
        sp = patch.spotify
        if sp.client_id is not None:
            config.spotify.client_id = sp.client_id
            _spotify_svc._client_id = sp.client_id
    if patch.gcal is not None:
        gc = patch.gcal
        if gc.client_id is not None:
            config.gcal.client_id = gc.client_id
            _calendar_svc._client_id = gc.client_id
        if gc.calendar_id is not None:
            config.gcal.calendar_id = gc.calendar_id
    save_overrides(config)
    return _config_view()


class KeyPatch(BaseModel):
    name: str   # e.g. "ANTHROPIC_API_KEY"
    value: str  # new value — write-only; never returned


@app.post("/config/key")
def set_api_key(patch: KeyPatch) -> dict:
    """Write an API key to engine/.env and reload it into the running process."""
    allowed = {
        "ANTHROPIC_API_KEY", "FINNHUB_API_KEY", "OPENAI_API_KEY",
        "GOOGLE_API_KEY", "NASA_API_KEY",
        "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET",
        "GOOGLE_CALENDAR_CLIENT_ID", "GOOGLE_CALENDAR_CLIENT_SECRET",
    }
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


# ---- Models (local Ollama + cloud catalog) ----------------------------------


@app.get("/models")
async def list_models() -> dict:
    """Return installed Ollama models + the cloud model catalog with benchmark data."""
    ollama_url = next(
        (p.base_url for p in config.providers if p.name == "ollama"),
        "http://127.0.0.1:11434",
    ) or "http://127.0.0.1:11434"
    try:
        raw = await list_ollama_models(base_url=ollama_url)
    except Exception:
        raw = []
    benchmarks = {r["model"]: r for r in _benchmark_store.all()}

    local: list[dict] = []
    for m in raw:
        tag = m.get("name", "")
        size_bytes = m.get("size", 0)
        size_gb = round(size_bytes / 1e9, 1)
        details = m.get("details", {})
        bench = benchmarks.get(tag)
        local.append({
            "id": tag,
            "display_name": tag,
            "provider": "ollama",
            "kind": "local",
            "size_gb": size_gb,
            "quant": details.get("quantization_level", ""),
            "family": details.get("family", ""),
            "parameter_size": details.get("parameter_size", ""),
            "vram_mb": vram_mb(tag),
            "ttft_ms": bench["ttft_ms"] if bench else None,
            "tokens_per_sec": bench["tokens_per_sec"] if bench else None,
            "bench_ran_at": bench["ran_at"] if bench else None,
        })

    # Annotate cloud models with key_set status
    cloud: list[dict] = []
    for cm in CLOUD_MODELS:
        env_key = cm.get("env_key", "")
        key_set = bool(os.environ.get(env_key)) if env_key else False
        cloud.append({**cm, "key_set": key_set})

    return {
        "local": local,
        "cloud": cloud,
        "task_models": config.task_models,
        "sigils": config.sigils,
    }


class BenchmarkRequest(BaseModel):
    model: str


@app.post("/models/benchmark")
async def benchmark_model(req: BenchmarkRequest) -> dict:
    """Run a live timed benchmark against a local Ollama model."""
    ollama_url = next(
        (p.base_url for p in config.providers if p.name == "ollama"),
        "http://127.0.0.1:11434",
    )
    try:
        result = await run_benchmark(req.model, base_url=ollama_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    _benchmark_store.upsert(
        model=result["model"],
        ttft_ms=result["ttft_ms"],
        tokens_per_sec=result["tokens_per_sec"],
        prompt_tokens=result.get("prompt_tokens", 0),
        total_tokens=result.get("total_tokens", 0),
    )
    return result


class PullRequest(BaseModel):
    model: str


@app.post("/models/pull")
async def pull_model(req: PullRequest) -> StreamingResponse:
    """Stream Ollama model pull progress as SSE."""
    ollama_url = next(
        (p.base_url for p in config.providers if p.name == "ollama"),
        "http://127.0.0.1:11434",
    )

    async def _gen():
        import json as _json
        async for status in pull_ollama_model(req.model, base_url=ollama_url):
            yield f"data: {_json.dumps({'status': status})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")


# ---- Parse / route ----------------------------------------------------------


class ParseRequest(BaseModel):
    text: str


@app.post("/parse")
def parse(req: ParseRequest) -> dict:
    """Parse a Max command and show how it would be routed (no inference yet)."""
    try:
        cmd = parse_command(req.text, sigils=config.sigils, custom_commands=config.custom_commands)
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
    feature: str = "system",
) -> StreamingResponse:
    """Stream a provider response as OpenAI-compatible SSE chunks. If ``on_done``
    is given, it's called with the full assembled text after a clean finish (used
    to record a turn into session memory)."""

    async def event_stream() -> AsyncIterator[str]:
        parts: list[str] = []
        try:
            async for chunk in provider.chat(model, messages, _feature=feature):
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
        return _sse_stream(provider, req.model, messages, feature="api")

    text = ""
    async for chunk in provider.chat(req.model, messages, _feature="api"):
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
        cmd = parse_command(req.text, sigils=config.sigils, custom_commands=config.custom_commands)
    except ParseError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    try:
        route = resolve(cmd, config)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    provider = build_provider(route.provider, config, model=route.model)
    messages = messages_for(cmd.action, cmd.body, prompt_override=cmd.prompt_override)
    return _sse_stream(provider, route.model, messages, feature="chat")


class CompleteRequest(BaseModel):
    prefix: str
    suffix: str = ""
    model: str | None = None  # default: the configured fast "completion" model
    max_tokens: int = 96


@app.post("/complete")
async def complete(req: CompleteRequest) -> dict:
    """Fill-in-the-middle code completion (ghost text for the VS Code extension).
    Uses the fast resident completion model unless ``model`` is given."""
    model = req.model or config.idle.resident_model or config.task_models.get("completion", "qwen2.5-coder:3b")
    is_resident = model == config.idle.resident_model
    ka = config.idle.resident_keep_alive if is_resident else config.idle.keep_alive
    text = await fim_complete(
        req.prefix,
        req.suffix,
        model=model,
        base_url=_ollama_base,
        max_tokens=req.max_tokens,
        keep_alive=ka,
    )
    return {"completion": text, "model": model}


class ChatTextRequest(BaseModel):
    text: str
    image_base64: str | None = None
    image_type: str = "image/jpeg"
    vision_provider: str = "claude"


@app.post("/chat")
async def chat(req: ChatTextRequest):
    """Plain conversational chat. When ``image_base64`` is set the request is
    routed to a vision-capable cloud provider (Claude or OpenAI)."""
    if req.image_base64:
        _check_network()
        vp = req.vision_provider if req.vision_provider in {"claude", "openai"} else "claude"
        if not config.allow_cloud:
            raise HTTPException(status_code=403, detail="vision requires cloud; allow_cloud is off")
        provider = build_provider(vp, config)
        if vp == "openai":
            content: list[dict] = [
                {"type": "text", "text": req.text},
                {"type": "image_url", "image_url": {"url": f"data:{req.image_type};base64,{req.image_base64}"}},
            ]
        else:
            content = [
                {"type": "text", "text": req.text},
                {"type": "image", "source": {"type": "base64", "media_type": req.image_type, "data": req.image_base64}},
            ]
        pm = config.provider_models.get(vp, {})
        model = pm.get("chat") or config.task_models.get("chat", "claude-sonnet-4-6")
        messages = [
            {"role": "system", "content": "You are Max, a helpful assistant that can analyse images."},
            {"role": "user", "content": content},
        ]
        return _sse_stream(provider, model, messages, feature="vision")
    provider = build_provider("ollama", config)
    model = config.task_models.get("chat", "qwen2.5-coder:14b")
    messages = messages_for("chat", req.text)
    return _sse_stream(provider, model, messages, feature="chat")


# ---- Custom commands config --------------------------------------------


class CustomCommandsRequest(BaseModel):
    commands: list[dict]


@app.get("/config/commands")
def get_commands():
    """Return the current list of user-defined custom commands."""
    return {"commands": [c.model_dump() for c in config.custom_commands]}


@app.put("/config/commands")
def put_commands(req: CustomCommandsRequest):
    """Replace the custom commands list and persist to .maxconfig.json."""
    from .config import _apply_overrides, save_overrides
    _apply_overrides(config, {"custom_commands": req.commands})
    save_overrides(config)
    return {"commands": [c.model_dump() for c in config.custom_commands]}


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

    return _sse_stream(provider, model, rag_messages(context, req.question, history), on_done, feature="rag")


@app.get("/rag/memory/{session_id}")
def rag_memory_get(session_id: str) -> dict:
    return {"session_id": session_id, "history": rag_memory.history(session_id)}


@app.post("/rag/memory/{session_id}/clear")
def rag_memory_clear(session_id: str) -> dict:
    rag_memory.clear(session_id)
    return {"session_id": session_id, "history": []}


# ---- OSINT: global news heat map ---------------------------------------


def _parse_domains(domains: str | None) -> set[str] | None:
    """Parse a comma-separated source-domain allowlist (the UI's per-source toggles)."""
    if not domains:
        return None
    items = {d.strip().lower() for d in domains.split(",") if d.strip()}
    return items or None


@app.get("/osint/heatmap")
async def osint_heatmap(domains: str | None = None) -> dict:
    """Per-country news intensity (0..1) from GDELT + RSS, cached for a TTL.

    Outbound egress to public news services; aggregated in the engine so the
    client stays thin. Returns empty ``countries`` if every source is unreachable.
    Pass ``domains`` (comma-separated allowlist) to restrict to specific sources.
    """
    _check_network()
    heatmap = await osint.get_heatmap(domains=_parse_domains(domains))
    return heatmap.to_dict()


@app.get("/osint/articles")
async def osint_articles(
    country: str | None = None, limit: int = 50, domains: str | None = None
) -> dict:
    """Ranked articles, newest first. Pass ``country`` (ISO-A3) to scope to one;
    omit it for the global top. ``domains`` is a comma-separated source allowlist."""
    _check_network()
    articles = await osint.get_articles(
        iso=country, limit=limit, domains=_parse_domains(domains)
    )
    return {
        "country": country.upper() if country else None,
        "articles": [a.to_dict() for a in articles],
    }


@app.get("/osint/domains")
async def osint_domains() -> dict:
    """Distinct source domains in the current article set + counts, for the UI's
    per-source toggle list."""
    _check_network()
    return {"domains": await osint.get_domains()}


@app.get("/osint/timeline")
async def osint_timeline(frames: int = 24, window_hours: float = 24.0) -> dict:
    """Heat replay: ``frames`` snapshots of per-country intensity over the last
    ``window_hours``, for the time-scrubber. Each frame is scored over articles
    up to that moment."""
    _check_network()
    return await osint.get_timeline(frames=frames, window_hours=window_hours)


@app.get("/osint/sources")
def osint_sources() -> dict:
    """Where the heat map's data comes from (for the UI's source panel)."""
    return osint.sources()


@app.get("/osint/events")
async def osint_events() -> dict:
    """Geospatial event markers (earthquakes ≥ M4.5, GDACS disaster alerts).
    Free, key-less sources; cached 5 min. Overlay-ready lat/lon + severity."""
    _check_network()
    return await events.get()


@app.get("/osint/naval")
async def osint_naval_endpoint() -> dict:
    """US carrier / big-deck amphib position *estimates* from public OSINT
    trackers (USNI + TWZ). Region-level and dated — not real-time GPS."""
    _check_network()
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
    messages = [
        {"role": "system", "content": apply_persona(system, config.personality, _profile_store.to_context_block())},
        *history,
    ]
    return _sse_stream(provider, model, messages, feature="osint")


# ---- Market: live US-stock board + AI "Ingest" -------------------------


def _ai_route() -> tuple[str, str]:
    """Pick (provider, model) for an AI analysis stream: cloud Claude when
    allowed, else the local default. Mirrors the resolve() cloud gate without the
    DSL. Used by Market and Apollo."""
    if config.allow_cloud and not config.force_offline:
        model = config.provider_models.get("claude", {}).get("chat", "claude-sonnet-4-6")
        return "claude", model
    return "ollama", config.task_models.get("chat", "qwen2.5-coder:14b")


def _stream_ai(action: str, payload: dict, feature: str = "system") -> StreamingResponse:
    """Route to cloud/local, build messages for ``action`` from a JSON payload,
    and stream the reply. The shared path behind Market analyze + Apollo reports."""
    provider_name, model = _ai_route()
    try:
        provider = build_provider(provider_name, config)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    msgs = messages_for(action, json.dumps(payload))
    msgs[0]["content"] = apply_persona(
        msgs[0]["content"], config.personality, _profile_store.to_context_block()
    )
    return _sse_stream(provider, model, msgs, feature=feature)


@app.get("/market/quotes")
async def market_quotes() -> dict:
    """Live quotes for the watchlist (Finnhub), cached for a short TTL. Returns an
    empty board if ``FINNHUB_API_KEY`` is unset or every fetch fails."""
    _check_network()
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
    return _stream_ai("market", payload, feature="market")


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
    messages[0]["content"] = apply_persona(messages[0]["content"], config.personality, _profile_store.to_context_block())
    return _sse_stream(provider, model, messages, feature="market")


@app.get("/market/candles/{symbol}")
async def market_candles(symbol: str, resolution: str = "D", days: int = 30) -> dict:
    """OHLCV candles for a symbol. Used for sparklines (resolution=D, days=30) and
    intraday charts (resolution=60, days=5). Returns [] when no key is set."""
    from .market.finnhub import fetch_candles
    api_key = os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        return {"symbol": symbol, "candles": []}
    import httpx as _httpx
    async with _httpx.AsyncClient(timeout=15.0) as client:
        candles = await fetch_candles(client, symbol, api_key, resolution=resolution, days=days)
    return {"symbol": symbol, "candles": candles}


# ---- Polymarket: prediction markets ------------------------------------


@app.get("/polymarket/board")
async def polymarket_board() -> dict:
    """Top active prediction markets by 24h volume, cached for a short TTL.

    No API key required — Polymarket's public APIs are open read access."""
    _check_network()
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


@app.get("/polymarket/news/{condition_id}")
async def polymarket_news(condition_id: str, limit: int = 10) -> dict:
    """Related news/events for a prediction market from the Gamma API events field."""
    from .polymarket.client import fetch_market_events
    import httpx as _httpx
    from .polymarket.client import _UA
    async with _httpx.AsyncClient(timeout=15.0, headers={"user-agent": _UA}) as client:
        events = await fetch_market_events(client, condition_id, limit=limit)
    return {"condition_id": condition_id, "events": events}


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
    return _stream_ai("polymarket", payload, feature="polymarket")


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
    messages[0]["content"] = apply_persona(messages[0]["content"], config.personality, _profile_store.to_context_block())
    return _sse_stream(provider, model, messages, feature="polymarket")


# ---- Local model lifecycle + VRAM management ---------------------------


@app.post("/engine/unload")
async def engine_unload() -> dict:
    """Free the local chat model from RAM/VRAM now (Ollama ``keep_alive=0``).
    It reloads automatically on the next local request. Idle models also unload
    on their own after ``config.idle.keep_alive`` (see settings)."""
    model = config.task_models.get("chat", "qwen2.5-coder:14b")
    provider = build_provider("ollama", config)
    unloaded = await provider.unload(model)  # type: ignore[attr-defined]
    return {"unloaded": unloaded, "model": model, "keep_alive": config.idle.keep_alive}


@app.get("/models/loaded")
async def models_loaded() -> dict:
    """Models currently resident in Ollama's RAM/VRAM (via /api/ps).

    Returns name, size_vram_mb, and whether it is the configured resident model."""
    loaded = await _vram_mgr.get_loaded()
    budget_mb = config.idle.vram_budget_mb
    used_mb = sum(m.size_vram for m in loaded) // (1024 * 1024)
    return {
        "models": [
            {
                "name": m.name,
                "size_vram_mb": m.size_vram // (1024 * 1024),
                "is_resident": m.name == config.idle.resident_model,
            }
            for m in loaded
        ],
        "used_mb": used_mb,
        "budget_mb": budget_mb,
        "resident_model": config.idle.resident_model,
    }


# ---- Egress audit log (privacy) ----------------------------------------

_EGRESS_LOG_PATH = Path(__file__).resolve().parent.parent / ".egress.log"


@app.get("/egress/log")
def egress_log(limit: int = 200) -> dict:
    """Recent outbound cloud-API calls from the egress audit log."""
    if not _EGRESS_LOG_PATH.exists():
        return {"entries": [], "total_lines": 0}
    lines = _EGRESS_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    tail = lines[-limit:] if len(lines) > limit else lines
    entries = []
    for line in reversed(tail):
        parts = {}
        for token in line.split():
            if "=" in token:
                k, _, v = token.partition("=")
                parts[k] = v
        if parts:
            entries.append({
                "ts": line.split()[0] if line else "",
                "provider": parts.get("provider", ""),
                "model": parts.get("model", ""),
                "action": parts.get("action", ""),
                "in_tokens": int(parts.get("in", 0)),
                "out_tokens": int(parts.get("out", 0)),
            })
    return {"entries": entries, "total_lines": len(lines)}


@app.delete("/egress/log")
def egress_log_clear() -> dict:
    """Truncate the egress audit log."""
    if _EGRESS_LOG_PATH.exists():
        _EGRESS_LOG_PATH.write_text("", encoding="utf-8")
    return {"cleared": True}


# ---- Analytics: token usage & cost ----------------------------------------

@app.get("/analytics/summary")
def analytics_summary(days: int = 30) -> dict:
    """Total token usage and cost summary for the given time window."""
    return _usage_store.summary(max(1, min(90, days)))


@app.get("/analytics/daily")
def analytics_daily(days: int = 30) -> dict:
    """Per-day per-feature token breakdown for the stacked bar chart."""
    d = max(1, min(90, days))
    return {"days": d, "series": _usage_store.daily(d)}


@app.get("/analytics/breakdown")
def analytics_breakdown(days: int = 30) -> dict:
    """Aggregated breakdown by feature × model × provider, sorted by cost."""
    d = max(1, min(90, days))
    return {"days": d, "rows": _usage_store.breakdown(d)}


@app.delete("/analytics/reset")
def analytics_reset() -> dict:
    """Clear all token usage history."""
    n = _usage_store.reset()
    return {"cleared": True, "rows_deleted": n}


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


@app.post("/aegis/auto-fix/{event_id}")
async def aegis_auto_fix(event_id: str) -> StreamingResponse:
    """Diagnose + auto-apply fix in one step (only runs when autonomy=auto).

    Streams SSE status events: diagnosing → applying → applied | failed.
    Requires ``config.aegis.autonomy == "auto"`` to proceed."""
    return StreamingResponse(
        aegis_svc.auto_diagnose_and_apply(event_id),
        media_type="text/event-stream",
    )


@app.get("/aegis/log")
def aegis_log(limit: int = 100) -> dict:
    """Structured history of all diagnosis + apply actions."""
    return {"log": aegis_svc.get_log(limit=limit)}


@app.get("/aegis/sources")
def aegis_sources() -> dict:
    """Current provider status, autonomy level, store path."""
    return aegis_svc.sources()


# ---- Aegis Security Posture (Phase 16) ---------------------------------


@app.post("/aegis/scan")
async def aegis_scan_start() -> dict:
    """Kick off a manual security scan (returns immediately with scan_id)."""
    import asyncio

    async def _run() -> None:
        await scan_svc.run_scan("manual")

    asyncio.create_task(_run())
    return {"scan_id": scan_svc.current_scan_id, "started": True}


@app.get("/aegis/scan/status")
def aegis_scan_status() -> dict:
    """Live progress of the current scan (or idle state)."""
    return {
        "running": scan_svc.is_running,
        "scan_id": scan_svc.current_scan_id,
        "files_scanned": scan_svc.files_scanned,
        "stage": scan_svc.stage,
    }


@app.get("/aegis/posture")
def aegis_posture() -> dict:
    """Current posture score, severity counts, scan history, at_risk flag."""
    p = scan_svc.posture()
    p["at_risk"] = p["score"] < config.aegis.score_threshold
    return p


@app.get("/aegis/findings")
def aegis_findings(
    category: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> dict:
    """List findings, optionally filtered by category (sast|sca) and status."""
    return {"findings": _aegis_store.list_findings(category=category, status=status or "open", limit=limit)}


@app.get("/aegis/scans")
def aegis_scans(limit: int = 20) -> dict:
    """Scan run history (for the score trend strip)."""
    return {"scans": _aegis_store.list_scans(limit=limit)}


class AegisFindingFixRequest(BaseModel):
    pass  # ID comes from the path


@app.post("/aegis/findings/{finding_id}/fix")
async def aegis_finding_fix(finding_id: str) -> StreamingResponse:
    """SSE — stream an AI fix (root cause + unified diff) for one finding."""
    finding = _aegis_store.get_finding(finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="finding not found")
    return StreamingResponse(
        scan_svc.fix_finding(finding_id), media_type="text/event-stream"
    )


class AegisFindingStatusRequest(BaseModel):
    status: str  # "open" | "ignored" | "fixed"


@app.post("/aegis/findings/{finding_id}/status")
def aegis_finding_status(finding_id: str, req: AegisFindingStatusRequest) -> dict:
    """Update a finding's status (open / ignored / fixed)."""
    finding = _aegis_store.get_finding(finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="finding not found")
    if req.status not in ("open", "ignored", "fixed"):
        raise HTTPException(status_code=422, detail="status must be open, ignored, or fixed")
    _aegis_store.set_finding_status(finding_id, req.status)
    return {"ok": True}


@app.get("/aegis/report")
def aegis_report_md() -> dict:
    """Markdown posture report (score, trend, grouped findings)."""
    return {"report": scan_svc.report_markdown()}


# ---- Sentinel: space situational awareness -----------------------------
#
# SGP4 propagation runs client-side (satellite.js Web Worker); the engine
# serves raw TLEs plus the NEO / space-weather / fireball / launch / ISS
# layers with per-feed TTL caching. All sources are free (NASA via env key).


@app.get("/sentinel/groups")
def sentinel_groups() -> dict:
    """Available CelesTrak satellite groups."""
    return {"groups": sentinel_svc.groups()}


@app.get("/sentinel/tle")
async def sentinel_tle(group: str = "stations"):
    """Raw TLEs for a group (parsed by the client's satellite.js worker)."""
    _check_network()
    return await sentinel_svc.get_tle(group)


@app.get("/sentinel/neo")
async def sentinel_neo():
    """Today's near-Earth objects (NASA NeoWs) + SBDB orbital elements."""
    _check_network()
    return await sentinel_svc.get_neo()


@app.get("/sentinel/space-weather")
async def sentinel_space_weather():
    """NOAA SWPC planetary Kp index + solar wind + storm scale."""
    _check_network()
    return await sentinel_svc.get_space_weather()


@app.get("/sentinel/fireballs")
async def sentinel_fireballs():
    """Recent atmospheric impact events (NASA CNEOS)."""
    _check_network()
    return await sentinel_svc.get_fireballs()


@app.get("/sentinel/launches")
async def sentinel_launches():
    """Upcoming rocket launches (TheSpaceDevs Launch Library 2)."""
    _check_network()
    return await sentinel_svc.get_launches()


@app.get("/sentinel/iss")
async def sentinel_iss():
    """Live ISS position + crew."""
    _check_network()
    return await sentinel_svc.get_iss()


@app.get("/sentinel/sources")
def sentinel_sources() -> dict:
    """Data sources + whether each needs a key."""
    return {"sources": sentinel_svc.sources()}


@app.post("/sentinel/analyze")
async def sentinel_analyze() -> StreamingResponse:
    """AI brief grounded in the live space snapshot (SSE)."""
    payload = await sentinel_svc.analyze_payload()
    return _stream_ai("sentinel", payload, feature="sentinel")


class SentinelChatRequest(BaseModel):
    messages: list[dict] = []


@app.post("/sentinel/chat")
async def sentinel_chat(req: SentinelChatRequest) -> StreamingResponse:
    """Conversational analyst grounded in the live space snapshot (SSE)."""
    payload = await sentinel_svc.chat_payload(req.messages)
    provider_name, model = _ai_route()
    try:
        provider = build_provider(provider_name, config)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    messages = sentinel_chat_messages(json.dumps(payload), req.messages)
    messages[0]["content"] = apply_persona(
        messages[0]["content"], config.personality, _profile_store.to_context_block()
    )
    return _sse_stream(provider, model, messages, feature="sentinel")


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
            async for chunk in provider.chat(model, messages_for(action, json.dumps(payload)), _feature="apollo"):
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


class SavePredictionRequest(BaseModel):
    text: str


@app.post("/apollo/prediction")
def apollo_save_prediction(req: SavePredictionRequest) -> dict:
    """Persist today's prediction text (1 per day, 30-day rolling window)."""
    _prediction_history.save(req.text)
    return {"saved": True}


_APOLLO_CHAT_SYSTEM = (
    "You are MAX's Apollo prediction engine, answering follow-up questions "
    "about global conflicts, markets, and forward-looking predictions. "
    "Use the provided recent prediction history as your primary context. "
    "Be analytical, specific, and cite prediction data when relevant. "
    "Keep answers focused and grounded in the available signals."
)


class ApolloChatMessage(BaseModel):
    role: str
    content: str


class ApolloChatRequest(BaseModel):
    messages: list[ApolloChatMessage]


@app.post("/apollo/chat")
async def apollo_chat(req: ApolloChatRequest) -> StreamingResponse:
    """Conversational Q&A grounded in recent Apollo predictions (SSE).

    The last 3 days of prediction history are injected into the system prompt
    so the AI can answer follow-up questions about its own forecasts."""
    prediction_ctx = _prediction_history.to_context_block()
    system = apply_persona(_APOLLO_CHAT_SYSTEM, config.personality, _profile_store.to_context_block())
    if prediction_ctx:
        system = system + "\n\n" + prediction_ctx
    history = [m.model_dump() for m in req.messages]
    provider_name, model = _ai_route()
    try:
        provider = build_provider(provider_name, config)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    messages = [{"role": "system", "content": system}, *history]
    return _sse_stream(provider, model, messages, feature="apollo")


# ---- User profile: persistent personal memory --------------------------


class ProfileItem(BaseModel):
    key: str
    value: str
    kind: str = "fact"
    source: str = "explicit"


@app.get("/user/profile")
def user_profile_get() -> dict:
    """Return all stored user-profile facts."""
    return {"items": _profile_store.get_all()}


@app.post("/user/profile")
def user_profile_upsert(item: ProfileItem) -> dict:
    """Create or update a user-profile fact."""
    return _profile_store.upsert(item.key, item.value, item.kind, item.source)


@app.delete("/user/profile/{key}")
def user_profile_delete(key: str) -> dict:
    deleted = _profile_store.delete(key)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Key '{key}' not found")
    return {"deleted": key}


# ---- Voice: speech-to-text transcription (Whisper) --------------------


class TranscribeRequest(BaseModel):
    audio_b64: str          # base64-encoded audio bytes
    mime: str = "audio/webm"  # e.g. "audio/webm", "audio/wav"


_whisper_model: object | None = None  # lazy-loaded on first use


def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        try:
            from faster_whisper import WhisperModel  # type: ignore[import-untyped]
            _whisper_model = WhisperModel(
                config.voice.whisper_model,
                device="cpu",
                compute_type="int8",
            )
        except ImportError as e:
            raise HTTPException(
                status_code=503,
                detail="faster-whisper is not installed. Run: pip install faster-whisper",
            ) from e
    return _whisper_model


@app.post("/voice/transcribe")
async def voice_transcribe(req: TranscribeRequest) -> dict:
    """Transcribe base64-encoded audio using a local Whisper model.

    The model is lazy-loaded on first call (~150 MB for tiny.en). Subsequent
    calls are fast. Use the /config voice.whisper_model setting to change the
    model size (tiny.en → small.en → medium)."""
    import base64
    import io
    import tempfile

    model = _get_whisper()
    audio_bytes = base64.b64decode(req.audio_b64)

    ext = ".webm" if "webm" in req.mime else ".wav"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        segments, _ = model.transcribe(tmp_path, beam_size=5)  # type: ignore[union-attr]
        text = " ".join(seg.text.strip() for seg in segments).strip()
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return {"text": text}


# ---- Shadow Net / Dark Web (Phase 15) ------------------------------------


@app.get("/dark/status")
async def dark_status() -> dict:
    """Circuit status: running, bootstrap %, exit IP, circuit age."""
    s = await dark_svc.status()
    return s.model_dump()


@app.post("/dark/new-circuit")
async def dark_new_circuit() -> dict:
    """Request a new Tor circuit (SIGNAL NEWNYM)."""
    await dark_svc.new_circuit()
    return {"ok": True}


@app.get("/dark/fetch")
async def dark_fetch_page(url: str, request: Request):
    """SSE stream: proxy-fetch *url* through Tor and return sanitised HTML.

    Events: ``{"type":"start"}`` → ``{"type":"html", ...FetchResult}``
            or ``{"type":"error","message":"..."}``
    """
    engine_base = f"{request.url.scheme}://{request.url.netloc}"

    async def _stream() -> AsyncIterator[str]:
        yield f"data: {json.dumps({'type': 'start', 'url': url})}\n\n"
        try:
            result = await tor_fetch_url(url, config.darknet.socks_port, engine_base=engine_base)
            yield f"data: {json.dumps({'type': 'html', **result.model_dump()})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@app.get("/dark/resource")
async def dark_resource(url: str):
    """Proxy an image/CSS/binary resource through Tor for the shadow browser iframe."""
    try:
        async with _make_tor_client(config.darknet.socks_port, timeout=20.0) as client:
            resp = await client.get(url)
        content_type = resp.headers.get("content-type", "application/octet-stream")
        return Response(content=resp.content, media_type=content_type)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"resource fetch failed: {exc}") from exc


@app.get("/dark/search")
async def dark_search(q: str) -> dict:
    """Search Ahmia for onion results, routed through Tor."""
    results = await dark_svc.search(q)
    return {"results": [r.model_dump() for r in results]}


# ---- LAN access ---------------------------------------------------------


@app.get("/lan/status")
def lan_status() -> dict:
    """Current LAN-sharing state. Consumed by the Settings panel to show URL/cert."""
    cert_ready = bool(
        config.lan.cert_path and Path(config.lan.cert_path).exists()
        and config.lan.key_path and Path(config.lan.key_path).exists()
    )
    return {
        "enabled": config.lan.lan_enabled,
        "port": config.lan.lan_port,
        "cert_path": config.lan.cert_path,
        "key_path": config.lan.key_path,
        "cert_ready": cert_ready,
    }



# ---- Code tab: file browser + AI edit planner ---------------------------

from .code import FileManager
from .code.planner import stream_plan as _stream_plan

_file_mgr: FileManager | None = None


def _get_file_mgr() -> FileManager:
    global _file_mgr
    if _file_mgr is None or set(str(r) for r in _file_mgr._roots) != set(config.workspace_allowlist):
        _file_mgr = FileManager(config.workspace_allowlist)
    return _file_mgr


@app.get("/code/files")
def code_list_files(path: str = ""):
    """List files/dirs in the workspace. Empty path returns root entries."""
    fm = _get_file_mgr()
    if not config.workspace_allowlist:
        raise HTTPException(status_code=400, detail="No workspace paths allow-listed in settings")
    try:
        if not path:
            entries = fm.list_root()
        else:
            entries = fm.list_dir(path)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return {"entries": [{"name": e.name, "path": e.path, "is_dir": e.is_dir} for e in entries]}


@app.get("/code/file")
def code_read_file(path: str):
    """Read a single file's content (text only, <= 500 KB)."""
    fm = _get_file_mgr()
    try:
        content = fm.read_file(path)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"file not found: {path}")
    except ValueError as e:
        raise HTTPException(status_code=413, detail=str(e)) from e
    return {"path": path, "content": content}


class WriteFileRequest(BaseModel):
    path: str
    content: str


@app.put("/code/file")
def code_write_file(req: WriteFileRequest):
    """Write (overwrite) a file within the workspace allowlist."""
    fm = _get_file_mgr()
    try:
        fm.write_file(req.path, req.content)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return {"ok": True, "path": req.path}


class PlanRequest(BaseModel):
    request: str
    file_paths: list[str] = []  # specific files to include; empty = let AI decide from context
    provider: str = "claude"    # vision-capable model; defaults to Claude


@app.post("/code/plan")
async def code_plan(req: PlanRequest):
    """Stream a multi-file AI edit plan for the given natural-language request."""
    _check_network()
    if not config.allow_cloud:
        raise HTTPException(status_code=403, detail="code planning uses a cloud provider; allow_cloud is off")
    fm = _get_file_mgr()
    prov_name = req.provider if req.provider in {"claude", "openai"} else "claude"
    try:
        provider = build_provider(prov_name, config)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    pm = config.provider_models.get(prov_name, {})
    model = pm.get("generate") or config.task_models.get("generate", "claude-sonnet-4-6")

    file_contexts: list[dict] = []
    for fp in req.file_paths:
        try:
            text = fm.read_file(fp)
            file_contexts.append({"path": fp, "content": text})
        except Exception:
            pass  # skip unreadable files silently

    async def _gen():
        async for chunk in _stream_plan(req.request, file_contexts, provider, model):
            yield chunk

    return StreamingResponse(_gen(), media_type="text/event-stream")


class ApplyPlanRequest(BaseModel):
    patches: list[dict]  # [{path, new_content}]
    take_snapshot: bool = True


_last_snapshot_ref: str | None = None


@app.post("/code/apply")
def code_apply(req: ApplyPlanRequest):
    """Apply a list of file patches (after optional git snapshot)."""
    global _last_snapshot_ref
    fm = _get_file_mgr()
    paths = [p["path"] for p in req.patches if "path" in p]

    snapshot_ref: str | None = None
    if req.take_snapshot:
        snapshot_ref = fm.git_snapshot(paths)
        _last_snapshot_ref = snapshot_ref

    written: list[str] = []
    errors: list[str] = []
    for patch in req.patches:
        path = patch.get("path", "")
        new_content = patch.get("new_content", "")
        if not path or new_content is None:
            continue
        try:
            fm.write_file(path, new_content)
            written.append(path)
        except Exception as e:
            errors.append(f"{path}: {e}")

    return {
        "written": written,
        "errors": errors,
        "snapshot_ref": snapshot_ref,
    }


@app.post("/code/rollback")
def code_rollback():
    """Rollback the last applied plan using the stored git stash ref."""
    global _last_snapshot_ref
    if not _last_snapshot_ref:
        raise HTTPException(status_code=404, detail="no snapshot available to rollback")
    fm = _get_file_mgr()
    ok = fm.git_rollback(_last_snapshot_ref)
    ref = _last_snapshot_ref
    if ok:
        _last_snapshot_ref = None
    return {"ok": ok, "stash_ref": ref}

# ── Code CRUD ────────────────────────────────────────────────────────────────

class CreateFileRequest(BaseModel):
    path: str
    content: str = ""

class CreateDirRequest(BaseModel):
    path: str

class RenameEntryRequest(BaseModel):
    path: str
    new_name: str


@app.post("/code/file/new")
def code_create_file(req: CreateFileRequest):
    fm = _get_file_mgr()
    try:
        fm.create_file(req.path, req.content)
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    except FileExistsError as e:
        raise HTTPException(409, str(e)) from e
    return {"ok": True, "path": req.path}


@app.post("/code/dir/new")
def code_create_dir(req: CreateDirRequest):
    fm = _get_file_mgr()
    try:
        fm.create_dir(req.path)
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    except FileExistsError as e:
        raise HTTPException(409, str(e)) from e
    return {"ok": True, "path": req.path}


@app.post("/code/file/rename")
def code_rename_entry(req: RenameEntryRequest):
    fm = _get_file_mgr()
    try:
        new_path = fm.rename_entry(req.path, req.new_name)
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    except (FileNotFoundError, IsADirectoryError) as e:
        raise HTTPException(404, str(e)) from e
    except FileExistsError as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"ok": True, "old_path": req.path, "new_path": new_path}


@app.delete("/code/file")
def code_delete_entry(path: str, recursive: bool = False):
    fm = _get_file_mgr()
    try:
        fm.delete_entry(path, recursive=recursive)
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except IsADirectoryError as e:
        raise HTTPException(409, str(e)) from e
    return {"ok": True, "path": path}


@app.get("/code/git/status")
def code_git_status():
    """Working-tree git status for the workspace, for file-tree badges."""
    if not config.workspace_allowlist:
        return {"files": []}
    fm = _get_file_mgr()
    try:
        return {"files": fm.git_status()}
    except Exception as e:  # never block the editor on a git hiccup
        return {"files": [], "error": str(e)}


@app.websocket("/code/ws/terminal")
async def code_terminal(ws: WebSocket):
    """Spawn a shell and pipe I/O bidirectionally over the WebSocket."""
    await ws.accept()

    cwd = config.workspace_allowlist[0] if config.workspace_allowlist else None
    if _sys.platform == "win32":
        cmd = ["powershell.exe", "-NoLogo", "-NoExit", "-Command", "-"]
    else:
        cmd = ["/bin/bash", "--login"]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
        )
    except Exception as exc:
        await ws.send_text(f"\r\n[terminal error: {exc}]\r\n")
        await ws.close()
        return

    async def _pump_output() -> None:
        assert proc.stdout is not None
        try:
            while True:
                chunk = await proc.stdout.read(1024)
                if not chunk:
                    break
                await ws.send_text(chunk.decode("utf-8", errors="replace"))
        except Exception:
            pass
        finally:
            try:
                await ws.close()
            except Exception:
                pass

    read_task = asyncio.create_task(_pump_output())

    try:
        while True:
            try:
                data = await ws.receive_text()
            except WebSocketDisconnect:
                break
            if proc.stdin and not proc.stdin.is_closing():
                proc.stdin.write(data.encode("utf-8"))
                await proc.stdin.drain()
    finally:
        read_task.cancel()
        try:
            proc.terminate()
        except Exception:
            pass


# ── Phase 9: Capabilities & Skills ──────────────────────────────────────────


@app.get("/capabilities")
def list_capabilities() -> dict:
    """List all registered skill capabilities and their connection status."""
    return {"capabilities": CapabilityRegistry.get().list_capabilities()}


class RouteRequest(BaseModel):
    message: str
    provider: str | None = None  # override AI provider for synthesis


@app.post("/capabilities/route")
async def capabilities_route(req: RouteRequest):
    """Classify the message → pick a skill → stream the response (SSE).
    Falls back to a plain chat reply when no skill matches."""
    prov_name, model = _ai_route()
    try:
        provider = build_provider(req.provider or prov_name, config)
    except KeyError:
        provider = build_provider("ollama", config)
        model = config.task_models.get("chat", "qwen2.5-coder:14b")

    # Use resident model for fast classification
    classifier_model = (
        config.skills.intent_router_model or config.idle.resident_model
        or config.task_models.get("chat", "qwen2.5-coder:14b")
    )
    try:
        classifier_provider = build_provider("ollama", config)
    except KeyError:
        classifier_provider = provider

    domain = await classify_intent(req.message, classifier_provider, classifier_model)

    async def _gen():
        # Emit the routing decision so the UI can display it
        yield f"data: {json.dumps({'object': 'route', 'domain': domain})}\n\n"

        if domain == "web_search":
            _check_network()
            async for chunk in _search_stream(req.message, provider, model):
                yield f"data: {json.dumps({'object': 'chat.completion.chunk', 'choices': [{'delta': {'content': chunk}}]})}\n\n"

        elif domain == "report":
            async for chunk in _report_svc.generate_stream(req.message, req.message, provider, model):
                yield f"data: {json.dumps({'object': 'chat.completion.chunk', 'choices': [{'delta': {'content': chunk}}]})}\n\n"

        elif domain == "spotify":
            status = await _spotify_svc.get_status(lambda: save_overrides(config))
            context = json.dumps(status)
            from .prompts import skill_messages
            msgs = skill_messages(context, req.message, [])
            async for chunk in provider.chat(model, msgs, _feature="skills"):
                if not chunk.done:
                    yield f"data: {json.dumps({'object': 'chat.completion.chunk', 'choices': [{'delta': {'content': chunk.text}}]})}\n\n"

        elif domain == "calendar":
            try:
                events = await _calendar_svc.list_events(lambda: save_overrides(config))
                context = json.dumps(events[:10])
            except Exception:
                context = "[]"
            from .prompts import skill_messages
            msgs = skill_messages(context, req.message, [])
            async for chunk in provider.chat(model, msgs, _feature="skills"):
                if not chunk.done:
                    yield f"data: {json.dumps({'object': 'chat.completion.chunk', 'choices': [{'delta': {'content': chunk.text}}]})}\n\n"

        elif domain == "files":
            from .prompts import skill_messages
            msgs = skill_messages("", req.message, [])
            async for chunk in provider.chat(model, msgs, _feature="skills"):
                if not chunk.done:
                    yield f"data: {json.dumps({'object': 'chat.completion.chunk', 'choices': [{'delta': {'content': chunk.text}}]})}\n\n"

        else:
            # code / chat — plain response
            from .prompts import apply_persona
            msgs = [
                {"role": "system", "content": apply_persona(
                    SYSTEM_PROMPTS["chat"], config.personality, _profile_store.to_context_block()
                )},
                {"role": "user", "content": req.message},
            ]
            async for chunk in provider.chat(model, msgs, _feature="skills"):
                if not chunk.done:
                    yield f"data: {json.dumps({'object': 'chat.completion.chunk', 'choices': [{'delta': {'content': chunk.text}}]})}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")


# -- Web Search ---------------------------------------------------------------

class SearchRequest(BaseModel):
    query: str
    max_results: int = 6
    provider: str | None = None


@app.get("/skills/search/raw")
async def skills_search_raw(q: str, max_results: int = 6) -> dict:
    """DuckDuckGo search results without AI synthesis."""
    _check_network()
    try:
        results = await ddg_search(q, max_results=max_results)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Search error: {e}") from e
    return {"query": q, "results": [r.to_dict() for r in results]}


@app.post("/skills/search")
async def skills_search(req: SearchRequest):
    """DDG search + AI synthesis streamed as SSE."""
    _check_network()
    prov_name, model = _ai_route()
    try:
        provider = build_provider(req.provider or prov_name, config)
    except KeyError:
        provider = build_provider("ollama", config)
        model = config.task_models.get("chat", "qwen2.5-coder:14b")

    async def _gen():
        async for chunk in _search_stream(req.query, provider, model):
            payload = {"object": "chat.completion.chunk", "choices": [{"delta": {"content": chunk}}]}
            yield f"data: {json.dumps(payload)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")


# -- Reports ------------------------------------------------------------------

class ReportGenerateRequest(BaseModel):
    title: str
    instructions: str
    provider: str | None = None


@app.post("/skills/report/generate")
async def skills_report_generate(req: ReportGenerateRequest):
    """Generate a structured markdown report (SSE)."""
    prov_name, model = _ai_route()
    try:
        provider = build_provider(req.provider or prov_name, config)
    except KeyError:
        provider = build_provider("ollama", config)
        model = config.task_models.get("chat", "qwen2.5-coder:14b")

    async def _gen():
        async for chunk in _report_svc.generate_stream(req.title, req.instructions, provider, model):
            payload = {"object": "chat.completion.chunk", "choices": [{"delta": {"content": chunk}}]}
            yield f"data: {json.dumps(payload)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")


@app.get("/skills/report/list")
def skills_report_list() -> dict:
    return {"reports": _report_svc.list_reports()}


@app.get("/skills/report/{report_id}")
def skills_report_get(report_id: str) -> dict:
    r = _report_svc.get_report(report_id)
    if r is None:
        raise HTTPException(status_code=404, detail="report not found")
    return r


@app.delete("/skills/report/{report_id}")
def skills_report_delete(report_id: str) -> dict:
    if not _report_svc.delete_report(report_id):
        raise HTTPException(status_code=404, detail="report not found")
    return {"ok": True}


# -- Files --------------------------------------------------------------------

class FilesReadRequest(BaseModel):
    path: str


class FilesSearchRequest(BaseModel):
    query: str
    path: str | None = None
    max_results: int = 50
    case_sensitive: bool = False


class FilesWriteRequest(BaseModel):
    path: str
    content: str
    preview: bool = False  # when True, returns diff info without writing


@app.get("/skills/files/list")
def skills_files_list(path: str | None = None) -> dict:
    if not config.workspace_allowlist:
        raise HTTPException(status_code=400, detail="No workspace paths allow-listed in settings")
    target = path or config.workspace_allowlist[0]
    try:
        entries = _files_svc.list_dir(target)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"path": target, "entries": entries}


@app.post("/skills/files/read")
def skills_files_read(req: FilesReadRequest) -> dict:
    try:
        content = _files_svc.read_file(req.path)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"path": req.path, "content": content}


@app.post("/skills/files/search")
def skills_files_search(req: FilesSearchRequest) -> dict:
    try:
        hits = _files_svc.search_content(
            req.query,
            path=req.path,
            max_results=req.max_results,
            case_sensitive=req.case_sensitive,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return {"query": req.query, "hits": hits}


@app.post("/skills/files/write")
def skills_files_write(req: FilesWriteRequest) -> dict:
    try:
        if req.preview:
            return _files_svc.write_preview(req.path, req.content)
        return _files_svc.write_file(req.path, req.content)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


# -- Spotify ------------------------------------------------------------------

@app.get("/skills/spotify/auth")
def skills_spotify_auth() -> dict:
    """Start the Spotify OAuth PKCE flow. Returns {url, configured}."""
    if not _spotify_svc._is_configured:
        raise HTTPException(
            status_code=400,
            detail="Spotify not configured — set SPOTIFY_CLIENT_ID in engine/.env",
        )
    url = _spotify_svc.start_auth()
    return {"url": url, "configured": True}


_OAUTH_SUCCESS_HTML = """<!DOCTYPE html><html><body style="font-family:sans-serif;text-align:center;padding:3rem;background:#0a0a0a;color:#ccc">
<h2 style="color:#1DB954">&#9654; Connected to Spotify</h2>
<p>You can close this tab and return to Max.</p>
<script>window.close();</script></body></html>"""

_OAUTH_ERROR_HTML = """<!DOCTYPE html><html><body style="font-family:sans-serif;text-align:center;padding:3rem;background:#0a0a0a;color:#ccc">
<h2 style="color:#e74c3c">&#10060; Spotify auth failed</h2>
<p>Please try again from Max settings.</p></body></html>"""


@app.get("/skills/spotify/callback")
async def skills_spotify_callback(code: str | None = None, error: str | None = None):
    """Spotify OAuth callback — exchanges code for tokens and closes the browser tab."""
    from fastapi.responses import HTMLResponse
    if error or not code:
        return HTMLResponse(_OAUTH_ERROR_HTML)
    ok = await _spotify_svc.handle_callback(code, lambda: save_overrides(config))
    if not ok:
        return HTMLResponse(_OAUTH_ERROR_HTML)
    return HTMLResponse(_OAUTH_SUCCESS_HTML)


@app.get("/skills/spotify/status")
async def skills_spotify_status() -> dict:
    """Auth status + currently-playing track (if authenticated)."""
    return await _spotify_svc.get_status(lambda: save_overrides(config))


class SpotifyControlRequest(BaseModel):
    action: str  # play | pause | next | prev


@app.post("/skills/spotify/control")
async def skills_spotify_control(req: SpotifyControlRequest) -> dict:
    if not _spotify_svc._is_authenticated:
        raise HTTPException(status_code=401, detail="Spotify not authenticated")
    return await _spotify_svc.control(req.action, lambda: save_overrides(config))


class SpotifyPlayRequest(BaseModel):
    uri: str  # spotify:track:... or spotify:playlist:...


@app.post("/skills/spotify/play")
async def skills_spotify_play(req: SpotifyPlayRequest) -> dict:
    if not _spotify_svc._is_authenticated:
        raise HTTPException(status_code=401, detail="Spotify not authenticated")
    return await _spotify_svc.play_uri(req.uri, lambda: save_overrides(config))


class SpotifySearchRequest(BaseModel):
    query: str
    types: str = "track"
    limit: int = 10


@app.post("/skills/spotify/search")
async def skills_spotify_search(req: SpotifySearchRequest) -> dict:
    if not _spotify_svc._is_authenticated:
        raise HTTPException(status_code=401, detail="Spotify not authenticated")
    results = await _spotify_svc.search(req.query, req.types, req.limit, lambda: save_overrides(config))
    return {"results": results}


@app.post("/skills/spotify/disconnect")
def skills_spotify_disconnect() -> dict:
    config.spotify.access_token = ""
    config.spotify.refresh_token = ""
    config.spotify.token_expiry = 0.0
    _spotify_svc._cfg.access_token = ""
    _spotify_svc._cfg.refresh_token = ""
    _spotify_svc._cfg.token_expiry = 0.0
    save_overrides(config)
    return {"ok": True}


# -- Google Calendar ----------------------------------------------------------

@app.get("/skills/calendar/auth")
def skills_calendar_auth() -> dict:
    """Start the Google Calendar OAuth2 PKCE flow. Returns {url, configured}."""
    if not _calendar_svc._is_configured:
        raise HTTPException(
            status_code=400,
            detail="Google Calendar not configured — set GOOGLE_CALENDAR_CLIENT_ID and GOOGLE_CALENDAR_CLIENT_SECRET in engine/.env",
        )
    url = _calendar_svc.start_auth()
    return {"url": url, "configured": True}


_GCAL_SUCCESS_HTML = """<!DOCTYPE html><html><body style="font-family:sans-serif;text-align:center;padding:3rem;background:#0a0a0a;color:#ccc">
<h2 style="color:#4285F4">&#128197; Connected to Google Calendar</h2>
<p>You can close this tab and return to Max.</p>
<script>window.close();</script></body></html>"""

_GCAL_ERROR_HTML = """<!DOCTYPE html><html><body style="font-family:sans-serif;text-align:center;padding:3rem;background:#0a0a0a;color:#ccc">
<h2 style="color:#e74c3c">&#10060; Google Calendar auth failed</h2>
<p>Please try again from Max settings.</p></body></html>"""


@app.get("/skills/calendar/callback")
async def skills_calendar_callback(code: str | None = None, error: str | None = None):
    """Google OAuth2 callback — exchanges code for tokens."""
    from fastapi.responses import HTMLResponse
    if error or not code:
        return HTMLResponse(_GCAL_ERROR_HTML)
    ok = await _calendar_svc.handle_callback(code, lambda: save_overrides(config))
    if not ok:
        return HTMLResponse(_GCAL_ERROR_HTML)
    return HTMLResponse(_GCAL_SUCCESS_HTML)


@app.get("/skills/calendar/status")
def skills_calendar_status() -> dict:
    return _calendar_svc.get_status()


@app.get("/skills/calendar/events")
async def skills_calendar_events(max_results: int = 15, days_ahead: int = 14) -> dict:
    if not _calendar_svc._is_authenticated:
        raise HTTPException(status_code=401, detail="Google Calendar not authenticated")
    events = await _calendar_svc.list_events(
        lambda: save_overrides(config),
        max_results=max_results,
        days_ahead=days_ahead,
    )
    return {"events": events}


class CalendarEventRequest(BaseModel):
    summary: str
    start_dt: str   # ISO 8601, e.g. "2026-06-01T10:00:00Z"
    end_dt: str
    description: str = ""
    location: str = ""


@app.post("/skills/calendar/event")
async def skills_calendar_create_event(req: CalendarEventRequest) -> dict:
    if not _calendar_svc._is_authenticated:
        raise HTTPException(status_code=401, detail="Google Calendar not authenticated")
    try:
        event = await _calendar_svc.create_event(
            req.summary, req.start_dt, req.end_dt,
            req.description, req.location,
            lambda: save_overrides(config),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return event


@app.delete("/skills/calendar/event/{event_id}")
async def skills_calendar_delete_event(event_id: str) -> dict:
    if not _calendar_svc._is_authenticated:
        raise HTTPException(status_code=401, detail="Google Calendar not authenticated")
    ok = await _calendar_svc.delete_event(event_id, lambda: save_overrides(config))
    if not ok:
        raise HTTPException(status_code=404, detail="event not found or could not be deleted")
    return {"ok": True}


@app.post("/skills/calendar/disconnect")
def skills_calendar_disconnect() -> dict:
    config.gcal.access_token = ""
    config.gcal.refresh_token = ""
    config.gcal.token_expiry = 0.0
    _calendar_svc._cfg.access_token = ""
    _calendar_svc._cfg.refresh_token = ""
    _calendar_svc._cfg.token_expiry = 0.0
    save_overrides(config)
    return {"ok": True}


# ---- Static files (LAN mobile access) -----------------------------------

_dist_path = Path(__file__).resolve().parent.parent.parent / "app" / "dist"


@app.get("/m")
def mobile_index() -> FileResponse:
    """Serve the mobile-first shell. The path /m tells main.tsx to render MobileApp."""
    html = _dist_path / "index.html"
    if html.exists():
        return FileResponse(str(html), media_type="text/html")
    raise HTTPException(status_code=404, detail="UI not built — run npm run build in app/")


# Serve the built Vite dist/ so mobile browsers hitting https://<pc>.local:8443/
# get the full Max UI. API routes above take priority; this is the catch-all.
# Only mounted when the dist/ directory exists (i.e. after `npm run build`).
if _dist_path.exists():
    app.mount("/", StaticFiles(directory=str(_dist_path), html=True), name="static")
