"""Engine configuration.

Mirrors the roadmap: per-task default models, sigil->provider map, providers,
cloud toggle, and the workspace folder allowlist. File-backed loading is a TODO
(Phase 1); for now these are the in-memory defaults.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from .market.finnhub import DEFAULT_WATCHLIST as MARKET_DEFAULT_WATCHLIST
from .osint.gdelt import DEFAULT_QUERY as OSINT_DEFAULT_QUERY
from .osint.naval import DEFAULT_TWZ_URL as OSINT_DEFAULT_TWZ_URL
from .osint.rss import DEFAULT_FEEDS as OSINT_DEFAULT_FEEDS

# UI-editable settings persist here (gitignored), next to engine/.env.
CONFIG_FILE = Path(__file__).resolve().parent.parent / ".maxconfig.json"


class ProviderConfig(BaseModel):
    name: str
    kind: str  # "local" | "cloud"
    base_url: str | None = None  # e.g. Ollama endpoint
    # API keys are loaded from the environment / secret store, never hard-coded.


class DelegateConfig(BaseModel):
    mode: str = "smart-auto"  # "manual" | "smart-auto"
    max_parallel_local: int = 1  # heavy local models queue past this (12 GB VRAM)
    max_parallel_cloud: int = 8


class IdleConfig(BaseModel):
    """Local model lifecycle. Ollama keeps a model resident in RAM/VRAM for this
    window after the last request, then unloads it to free memory; the next
    request transparently reloads it. ``"0"`` unloads immediately after each call;
    ``"-1"`` keeps it loaded forever. Accepts Ollama duration strings (e.g. ``"10m"``)."""

    keep_alive: str = "10m"


class OsintConfig(BaseModel):
    """Global news heat map (GDELT + RSS). Egress is outbound to public news."""

    gdelt_query: str = OSINT_DEFAULT_QUERY
    gdelt_timespan: str = "24h"
    gdelt_max_records: int = 250
    feeds: list[str] = Field(default_factory=lambda: list(OSINT_DEFAULT_FEEDS))
    ttl_seconds: int = 600  # cache window (GDELT refreshes ~every 15 min)
    # Naval layer: US carrier/amphib positions from public OSINT trackers.
    naval_twz_url: str = OSINT_DEFAULT_TWZ_URL
    naval_ttl_seconds: int = 21_600  # trackers update ~weekly


class MarketConfig(BaseModel):
    """Live US-stock board (Finnhub). The API key is read from the environment
    (``FINNHUB_API_KEY``), never stored here. The watchlist is user-editable."""

    watchlist: list[str] = Field(default_factory=lambda: list(MARKET_DEFAULT_WATCHLIST))
    ttl_seconds: int = 10  # cache window; the UI polls ~every 10s


class PolymarketConfig(BaseModel):
    """Prediction market board (Polymarket Gamma + CLOB APIs). No key required."""

    watchlist: list[str] = Field(default_factory=list)  # pinned condition IDs
    ttl_seconds: int = 120
    embed_enabled: bool = True
    categories: list[str] = Field(default_factory=list)  # empty = all categories


class AegisConfig(BaseModel):
    """Self-repair engine. Events captured to .apollo.db; diagnosis via provider router."""

    autonomy: str = "ask"            # suggest | ask | auto
    cooldown_seconds: int = 300      # per-fingerprint re-diagnose cooldown
    max_fixes_per_error: int = 3     # loop-protection cap
    # ---- Phase 16: Security Posture ----
    scan_enabled: bool = True
    scan_interval_hours: int = 24
    scan_on_startup: bool = False
    scan_roots: list[str] = Field(default_factory=list)  # empty → repo root
    osv_enabled: bool = True
    osv_ttl_seconds: int = 21_600                         # cache OSV results ~6h
    score_threshold: int = 70                             # below → "at risk" banner


class SentinelConfig(BaseModel):
    """Space situational awareness. SGP4 propagation runs client-side; this just
    serves raw TLEs + NEO/space-weather/fireball/launch/ISS layers with TTL caches.
    The NASA key is read from the environment (``NASA_API_KEY``), never stored here."""

    tle_groups: list[str] = Field(
        default_factory=lambda: ["stations", "starlink", "gps", "galileo", "weather"]
    )
    tle_ttl: int = 7200       # TLEs update ~daily
    neo_ttl: int = 3600
    sw_ttl: int = 600         # space weather refreshes often
    fireball_ttl: int = 21600
    launch_ttl: int = 3600
    iss_ttl: int = 5          # live position


class PersonalityConfig(BaseModel):
    """How Max addresses and speaks to the user."""

    persona: str = "jarvis"      # "jarvis" | "formal" | "custom"
    user_name: str = ""          # the human's preferred name, e.g. "Tony"
    custom_prefix: str = ""      # used verbatim when persona="custom"


class LanConfig(BaseModel):
    """Share Max on the local network. When enabled, the engine binds 0.0.0.0
    over HTTPS so phones/Macs on the same WiFi can open Max in a browser.
    Mic on mobile requires HTTPS — mkcert generates a locally-trusted cert."""

    lan_enabled: bool = False
    lan_port: int = 8443
    cert_path: str = ""   # absolute path to TLS certificate PEM
    key_path: str = ""    # absolute path to TLS private key PEM


class DarkNetConfig(BaseModel):
    """Tor-based dark web browser. Tor process managed by Tauri; Python side
    reads its ports to proxy requests and stream circuit status."""

    socks_port: int = 9050
    control_port: int = 9051


class VoiceConfig(BaseModel):
    """Voice I/O settings. STT provider is configurable; TTS uses the Web Speech API."""

    stt_provider: str = "web"    # "web" | "whisper" | "auto"
    whisper_model: str = "tiny.en"
    tts_enabled: bool = True
    tts_rate: float = 1.0        # speech rate multiplier (0.5–2.0)
    tts_pitch: float = 1.0       # pitch multiplier (0.5–2.0)
    tts_voice_name: str = ""     # empty = system default voice


class ApolloConfig(BaseModel):
    """Apollo prediction engine. Local sqlite-vec memory + Ollama embeddings.
    Everything stays on the machine; memory auto-expires after ``ttl_seconds``."""

    db_path: str = str(Path(__file__).resolve().parent.parent / ".apollo.db")
    embed_model: str = "nomic-embed-text"
    ttl_seconds: int = 86_400  # 24h auto-purge
    retrieve_k: int = 6


class RagConfig(BaseModel):
    """Codebase RAG. Local sqlite-vec index of the workspace allowlist + Ollama
    embeddings. Indexing only ever touches allowlisted paths; nothing leaves the
    machine."""

    db_path: str = str(Path(__file__).resolve().parent.parent / ".maxrag.db")
    embed_model: str = "nomic-embed-text"
    max_chars: int = 1200  # chunk size target
    overlap_lines: int = 8  # context continuity between chunks
    retrieve_k: int = 6


class EngineConfig(BaseModel):
    # sigil -> provider name
    sigils: dict[str, str] = Field(
        default_factory=lambda: {"@": "ollama", "#": "qwen", "!": "claude"}
    )
    # task -> default model
    task_models: dict[str, str] = Field(
        default_factory=lambda: {
            "generate": "qwen2.5-coder:14b",
            "summarize": "qwen2.5-coder:14b",
            "fix": "qwen2.5-coder:14b",
            "chat": "qwen2.5-coder:14b",
            "completion": "qwen2.5-coder:3b",
        }
    )
    # Optional per-provider model overrides: provider -> {action: model}.
    # Falls back to task_models when a provider/action isn't listed here.
    provider_models: dict[str, dict[str, str]] = Field(
        default_factory=lambda: {
            "claude": {
                "generate": "claude-sonnet-4-6",
                "summarize": "claude-haiku-4-5-20251001",
                "fix": "claude-sonnet-4-6",
                "chat": "claude-sonnet-4-6",
            }
        }
    )
    providers: list[ProviderConfig] = Field(
        default_factory=lambda: [
            ProviderConfig(name="ollama", kind="local", base_url="http://127.0.0.1:11434"),
            ProviderConfig(name="qwen", kind="local", base_url="http://127.0.0.1:11434"),
            ProviderConfig(name="claude", kind="cloud"),
        ]
    )
    allow_cloud: bool = True
    workspace_allowlist: list[str] = Field(default_factory=list)
    delegate: DelegateConfig = Field(default_factory=DelegateConfig)
    idle: IdleConfig = Field(default_factory=IdleConfig)
    osint: OsintConfig = Field(default_factory=OsintConfig)
    market: MarketConfig = Field(default_factory=MarketConfig)
    polymarket: PolymarketConfig = Field(default_factory=PolymarketConfig)
    apollo: ApolloConfig = Field(default_factory=ApolloConfig)
    rag: RagConfig = Field(default_factory=RagConfig)
    aegis: AegisConfig = Field(default_factory=AegisConfig)
    sentinel: SentinelConfig = Field(default_factory=SentinelConfig)
    personality: PersonalityConfig = Field(default_factory=PersonalityConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    darknet: DarkNetConfig = Field(default_factory=DarkNetConfig)
    lan: LanConfig = Field(default_factory=LanConfig)


def _apply_overrides(cfg: EngineConfig, data: dict) -> None:
    """Apply the UI-editable subset of settings onto a config in place."""
    if "allow_cloud" in data:
        cfg.allow_cloud = bool(data["allow_cloud"])
    if "workspace_allowlist" in data:
        cfg.workspace_allowlist = list(data["workspace_allowlist"])
    d = data.get("delegate") or {}
    if "mode" in d:
        cfg.delegate.mode = d["mode"]
    if "max_parallel_local" in d:
        cfg.delegate.max_parallel_local = max(1, int(d["max_parallel_local"]))
    if "max_parallel_cloud" in d:
        cfg.delegate.max_parallel_cloud = max(1, int(d["max_parallel_cloud"]))
    idle = data.get("idle") or {}
    if "keep_alive" in idle:
        cfg.idle.keep_alive = str(idle["keep_alive"])
    mk = data.get("market") or {}
    if "watchlist" in mk:
        cfg.market.watchlist = [str(s) for s in mk["watchlist"]]
    if "ttl_seconds" in mk:
        cfg.market.ttl_seconds = max(5, int(mk["ttl_seconds"]))
    os_ = data.get("osint") or {}
    if "gdelt_query" in os_:
        cfg.osint.gdelt_query = str(os_["gdelt_query"])
    if "gdelt_timespan" in os_:
        cfg.osint.gdelt_timespan = str(os_["gdelt_timespan"])
    if "gdelt_max_records" in os_:
        cfg.osint.gdelt_max_records = max(10, int(os_["gdelt_max_records"]))
    if "ttl_seconds" in os_:
        cfg.osint.ttl_seconds = max(60, int(os_["ttl_seconds"]))
    if "naval_ttl_seconds" in os_:
        cfg.osint.naval_ttl_seconds = max(3600, int(os_["naval_ttl_seconds"]))
    if "feeds" in os_:
        cfg.osint.feeds = [str(f) for f in os_["feeds"]]
    pm = data.get("polymarket") or {}
    if "watchlist" in pm:
        cfg.polymarket.watchlist = [str(s) for s in pm["watchlist"]]
    if "ttl_seconds" in pm:
        cfg.polymarket.ttl_seconds = max(30, int(pm["ttl_seconds"]))
    if "embed_enabled" in pm:
        cfg.polymarket.embed_enabled = bool(pm["embed_enabled"])
    if "categories" in pm:
        cfg.polymarket.categories = [str(c) for c in pm["categories"]]
    ap = data.get("apollo") or {}
    if "embed_model" in ap:
        cfg.apollo.embed_model = str(ap["embed_model"])
    if "ttl_seconds" in ap:
        cfg.apollo.ttl_seconds = max(3600, int(ap["ttl_seconds"]))
    if "retrieve_k" in ap:
        cfg.apollo.retrieve_k = max(1, int(ap["retrieve_k"]))
    pers = data.get("personality") or {}
    if "persona" in pers:
        cfg.personality.persona = str(pers["persona"])
    if "user_name" in pers:
        cfg.personality.user_name = str(pers["user_name"])
    if "custom_prefix" in pers:
        cfg.personality.custom_prefix = str(pers["custom_prefix"])
    vo = data.get("voice") or {}
    if "stt_provider" in vo:
        cfg.voice.stt_provider = str(vo["stt_provider"])
    if "whisper_model" in vo:
        cfg.voice.whisper_model = str(vo["whisper_model"])
    if "tts_enabled" in vo:
        cfg.voice.tts_enabled = bool(vo["tts_enabled"])
    if "tts_rate" in vo:
        cfg.voice.tts_rate = max(0.5, min(2.0, float(vo["tts_rate"])))
    if "tts_pitch" in vo:
        cfg.voice.tts_pitch = max(0.5, min(2.0, float(vo["tts_pitch"])))
    if "tts_voice_name" in vo:
        cfg.voice.tts_voice_name = str(vo["tts_voice_name"])
    la = data.get("lan") or {}
    if "lan_enabled" in la:
        cfg.lan.lan_enabled = bool(la["lan_enabled"])
    if "lan_port" in la:
        cfg.lan.lan_port = max(1024, int(la["lan_port"]))
    if "cert_path" in la:
        cfg.lan.cert_path = str(la["cert_path"])
    if "key_path" in la:
        cfg.lan.key_path = str(la["key_path"])
    ag = data.get("aegis") or {}
    if "scan_enabled" in ag:
        cfg.aegis.scan_enabled = bool(ag["scan_enabled"])
    if "scan_interval_hours" in ag:
        cfg.aegis.scan_interval_hours = max(1, int(ag["scan_interval_hours"]))
    if "scan_on_startup" in ag:
        cfg.aegis.scan_on_startup = bool(ag["scan_on_startup"])
    if "scan_roots" in ag:
        cfg.aegis.scan_roots = [str(r) for r in ag["scan_roots"]]
    if "osv_enabled" in ag:
        cfg.aegis.osv_enabled = bool(ag["osv_enabled"])
    if "osv_ttl_seconds" in ag:
        cfg.aegis.osv_ttl_seconds = max(3600, int(ag["osv_ttl_seconds"]))
    if "score_threshold" in ag:
        cfg.aegis.score_threshold = max(0, min(100, int(ag["score_threshold"])))


def load_config() -> EngineConfig:
    """Defaults, with any persisted UI overrides from CONFIG_FILE applied."""
    cfg = EngineConfig()
    if CONFIG_FILE.exists():
        try:
            _apply_overrides(cfg, json.loads(CONFIG_FILE.read_text()))
        except (ValueError, OSError):
            pass  # corrupt/unreadable file -> fall back to defaults
    return cfg


def save_overrides(cfg: EngineConfig) -> None:
    """Persist the UI-editable subset of settings to CONFIG_FILE."""
    data = {
        "allow_cloud": cfg.allow_cloud,
        "workspace_allowlist": cfg.workspace_allowlist,
        "delegate": {
            "mode": cfg.delegate.mode,
            "max_parallel_local": cfg.delegate.max_parallel_local,
            "max_parallel_cloud": cfg.delegate.max_parallel_cloud,
        },
        "idle": {"keep_alive": cfg.idle.keep_alive},
        "market": {
            "watchlist": cfg.market.watchlist,
            "ttl_seconds": cfg.market.ttl_seconds,
        },
        "osint": {
            "gdelt_query": cfg.osint.gdelt_query,
            "gdelt_timespan": cfg.osint.gdelt_timespan,
            "gdelt_max_records": cfg.osint.gdelt_max_records,
            "ttl_seconds": cfg.osint.ttl_seconds,
            "naval_ttl_seconds": cfg.osint.naval_ttl_seconds,
            "feeds": cfg.osint.feeds,
        },
        "polymarket": {
            "watchlist": cfg.polymarket.watchlist,
            "ttl_seconds": cfg.polymarket.ttl_seconds,
            "embed_enabled": cfg.polymarket.embed_enabled,
            "categories": cfg.polymarket.categories,
        },
        "apollo": {
            "embed_model": cfg.apollo.embed_model,
            "ttl_seconds": cfg.apollo.ttl_seconds,
            "retrieve_k": cfg.apollo.retrieve_k,
        },
        "personality": {
            "persona": cfg.personality.persona,
            "user_name": cfg.personality.user_name,
            "custom_prefix": cfg.personality.custom_prefix,
        },
        "voice": {
            "stt_provider": cfg.voice.stt_provider,
            "whisper_model": cfg.voice.whisper_model,
            "tts_enabled": cfg.voice.tts_enabled,
            "tts_rate": cfg.voice.tts_rate,
            "tts_pitch": cfg.voice.tts_pitch,
            "tts_voice_name": cfg.voice.tts_voice_name,
        },
        "lan": {
            "lan_enabled": cfg.lan.lan_enabled,
            "lan_port": cfg.lan.lan_port,
            "cert_path": cfg.lan.cert_path,
            "key_path": cfg.lan.key_path,
        },
        "aegis": {
            "scan_enabled": cfg.aegis.scan_enabled,
            "scan_interval_hours": cfg.aegis.scan_interval_hours,
            "scan_on_startup": cfg.aegis.scan_on_startup,
            "scan_roots": cfg.aegis.scan_roots,
            "osv_enabled": cfg.aegis.osv_enabled,
            "osv_ttl_seconds": cfg.aegis.osv_ttl_seconds,
            "score_threshold": cfg.aegis.score_threshold,
        },
    }
    CONFIG_FILE.write_text(json.dumps(data, indent=2))
