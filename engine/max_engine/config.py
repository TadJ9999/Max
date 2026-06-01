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


class CustomCommand(BaseModel):
    """A user-defined DSL command with a custom trigger character and prompt template.

    The trigger character is used as both the opening and closing delimiter, e.g.
    ``? explain this ?`` if trigger is ``?``. The prompt_template may include
    ``{body}`` which is replaced with the command body at call time.
    """

    name: str
    description: str = ""
    trigger: str  # single character, e.g. "?" or ">"
    prompt_template: str  # e.g. "Explain the following in plain English:\n\n{body}"


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
    # Two-model strategy: one tiny model stays resident in VRAM for FIM/completion,
    # heavy models load on demand and evict after keep_alive.
    resident_model: str = "qwen2.5-coder:3b"
    resident_keep_alive: str = "-1"  # never evict the resident completer
    # VRAM budget for auto-eviction before loading a heavy model (12 GB GPU, keep 1 GB headroom).
    vram_budget_mb: int = 11_000


class TuningConfig(BaseModel):
    """Ollama runtime tuning, passed as request ``options`` on every local chat
    call. A value of ``0`` (or ``-1`` for ``num_gpu``) means "leave it to
    Ollama's own default", so an untouched config changes nothing.

    Note: model **quantization** is fixed at pull time (it's part of the model
    tag, e.g. ``:q4_0``), and **KV-cache** quantization is a server-level env var
    (``OLLAMA_KV_CACHE_TYPE=q8_0``), not a per-request option — both are
    documented in the Performance settings rather than set here."""

    num_ctx: int = 0      # context window in tokens (0 = model default)
    num_gpu: int = -1     # layers offloaded to the GPU (-1 = auto-detect)
    num_batch: int = 0    # prompt batch size (0 = default)
    num_thread: int = 0   # CPU threads (0 = default)

    def to_options(self) -> dict:
        """The subset of knobs the user actually set, as Ollama option names."""
        opts: dict = {}
        if self.num_ctx > 0:
            opts["num_ctx"] = self.num_ctx
        if self.num_gpu >= 0:
            opts["num_gpu"] = self.num_gpu
        if self.num_batch > 0:
            opts["num_batch"] = self.num_batch
        if self.num_thread > 0:
            opts["num_thread"] = self.num_thread
        return opts


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
    # Per-source toggles
    gdelt_enabled: bool = True
    rss_enabled: bool = True
    naval_enabled: bool = True
    tone_signal: bool = False  # amplify heat by negative GDELT tone (opt-in)


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


class SkillsConfig(BaseModel):
    """Phase 9 — Capability platform & skills."""

    intent_router_enabled: bool = True
    intent_router_model: str = ""  # empty = use resident model


class MCPServerConfig(BaseModel):
    """One external MCP server Max can connect to as a host/client."""

    name: str
    transport: str = "stdio"  # "stdio" | "http"
    command: list[str] = Field(default_factory=list)  # stdio: argv
    cwd: str = ""  # stdio: working dir (optional)
    url: str = ""  # http: server URL
    enabled: bool = True


class MCPConfig(BaseModel):
    """Phase 9 (stretch) — MCP host: external servers Max connects to."""

    servers: list[MCPServerConfig] = Field(default_factory=list)


class SpotifyConfig(BaseModel):
    """Spotify OAuth PKCE. client_id/secret from env; tokens persisted here."""

    client_id: str = ""
    redirect_uri: str = "http://127.0.0.1:8001/skills/spotify/callback"
    access_token: str = ""
    refresh_token: str = ""
    token_expiry: float = 0.0


class GoogleCalendarConfig(BaseModel):
    """Google Calendar OAuth2. client_id/secret from env; tokens persisted here."""

    client_id: str = ""
    redirect_uri: str = "http://127.0.0.1:8001/skills/calendar/callback"
    access_token: str = ""
    refresh_token: str = ""
    token_expiry: float = 0.0
    calendar_id: str = "primary"


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
        default_factory=lambda: {
            "@": "ollama", "#": "qwen", "!": "claude", "%": "openai", "^": "local",
        }
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
            },
            "openai": {
                "generate": "gpt-4o",
                "summarize": "gpt-4o-mini",
                "fix": "gpt-4o",
                "chat": "gpt-4o",
            },
        }
    )
    providers: list[ProviderConfig] = Field(
        default_factory=lambda: [
            ProviderConfig(name="ollama", kind="local", base_url="http://127.0.0.1:11434"),
            ProviderConfig(name="qwen", kind="local", base_url="http://127.0.0.1:11434"),
            # OpenAI-compatible local server (llama.cpp / vLLM / LM Studio) — ^ sigil.
            ProviderConfig(name="local", kind="local", base_url="http://127.0.0.1:8080"),
            ProviderConfig(name="claude", kind="cloud"),
            ProviderConfig(name="openai", kind="cloud"),
        ]
    )
    custom_commands: list[CustomCommand] = Field(default_factory=list)
    allow_cloud: bool = True
    force_offline: bool = False  # kill-switch: block ALL outbound network calls
    workspace_allowlist: list[str] = Field(default_factory=list)
    delegate: DelegateConfig = Field(default_factory=DelegateConfig)
    idle: IdleConfig = Field(default_factory=IdleConfig)
    tuning: TuningConfig = Field(default_factory=TuningConfig)
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
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    spotify: SpotifyConfig = Field(default_factory=SpotifyConfig)
    gcal: GoogleCalendarConfig = Field(default_factory=GoogleCalendarConfig)


def _apply_overrides(cfg: EngineConfig, data: dict) -> None:
    """Apply the UI-editable subset of settings onto a config in place."""
    if "allow_cloud" in data:
        cfg.allow_cloud = bool(data["allow_cloud"])
    if "force_offline" in data:
        cfg.force_offline = bool(data["force_offline"])
    if "workspace_allowlist" in data:
        cfg.workspace_allowlist = list(data["workspace_allowlist"])
    if "task_models" in data and isinstance(data["task_models"], dict):
        for k, v in data["task_models"].items():
            if isinstance(v, str) and k in cfg.task_models:
                cfg.task_models[k] = v
    if "sigils" in data and isinstance(data["sigils"], dict):
        for k, v in data["sigils"].items():
            if isinstance(v, str):
                cfg.sigils[k] = v
    # Provider endpoint overrides (only base_url is UI-editable; matched by name).
    if isinstance(data.get("providers"), list):
        by_name = {p.name: p for p in cfg.providers}
        for item in data["providers"]:
            if isinstance(item, dict):
                p = by_name.get(item.get("name"))
                if p is not None and isinstance(item.get("base_url"), str) and item["base_url"]:
                    p.base_url = item["base_url"]
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
    if "resident_model" in idle:
        cfg.idle.resident_model = str(idle["resident_model"])
    if "resident_keep_alive" in idle:
        cfg.idle.resident_keep_alive = str(idle["resident_keep_alive"])
    if "vram_budget_mb" in idle:
        cfg.idle.vram_budget_mb = max(1_000, int(idle["vram_budget_mb"]))
    tn = data.get("tuning") or {}
    if "num_ctx" in tn:
        cfg.tuning.num_ctx = max(0, int(tn["num_ctx"]))
    if "num_gpu" in tn:
        cfg.tuning.num_gpu = max(-1, int(tn["num_gpu"]))
    if "num_batch" in tn:
        cfg.tuning.num_batch = max(0, int(tn["num_batch"]))
    if "num_thread" in tn:
        cfg.tuning.num_thread = max(0, int(tn["num_thread"]))
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
    if "gdelt_enabled" in os_:
        cfg.osint.gdelt_enabled = bool(os_["gdelt_enabled"])
    if "rss_enabled" in os_:
        cfg.osint.rss_enabled = bool(os_["rss_enabled"])
    if "naval_enabled" in os_:
        cfg.osint.naval_enabled = bool(os_["naval_enabled"])
    if "tone_signal" in os_:
        cfg.osint.tone_signal = bool(os_["tone_signal"])
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
    sk = data.get("skills") or {}
    if "intent_router_enabled" in sk:
        cfg.skills.intent_router_enabled = bool(sk["intent_router_enabled"])
    if "intent_router_model" in sk:
        cfg.skills.intent_router_model = str(sk["intent_router_model"])
    mcp = data.get("mcp") or {}
    if isinstance(mcp.get("servers"), list):
        servers: list[MCPServerConfig] = []
        for s in mcp["servers"]:
            if isinstance(s, dict) and s.get("name"):
                servers.append(MCPServerConfig(
                    name=str(s["name"]),
                    transport=str(s.get("transport", "stdio")),
                    command=[str(x) for x in (s.get("command") or [])],
                    cwd=str(s.get("cwd", "")),
                    url=str(s.get("url", "")),
                    enabled=bool(s.get("enabled", True)),
                ))
        cfg.mcp.servers = servers
    sp = data.get("spotify") or {}
    if "client_id" in sp:
        cfg.spotify.client_id = str(sp["client_id"])
    if "access_token" in sp:
        cfg.spotify.access_token = str(sp["access_token"])
    if "refresh_token" in sp:
        cfg.spotify.refresh_token = str(sp["refresh_token"])
    if "token_expiry" in sp:
        cfg.spotify.token_expiry = float(sp["token_expiry"])
    gc = data.get("gcal") or {}
    if "client_id" in gc:
        cfg.gcal.client_id = str(gc["client_id"])
    if "access_token" in gc:
        cfg.gcal.access_token = str(gc["access_token"])
    if "refresh_token" in gc:
        cfg.gcal.refresh_token = str(gc["refresh_token"])
    if "token_expiry" in gc:
        cfg.gcal.token_expiry = float(gc["token_expiry"])
    if "calendar_id" in gc:
        cfg.gcal.calendar_id = str(gc["calendar_id"])
    cmds = data.get("custom_commands")
    if isinstance(cmds, list):
        parsed: list[CustomCommand] = []
        for c in cmds:
            if isinstance(c, dict) and c.get("name") and c.get("trigger") and c.get("prompt_template"):
                parsed.append(CustomCommand(
                    name=str(c["name"]),
                    description=str(c.get("description", "")),
                    trigger=str(c["trigger"])[:1],
                    prompt_template=str(c["prompt_template"]),
                ))
        cfg.custom_commands = parsed


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
        "force_offline": cfg.force_offline,
        "workspace_allowlist": cfg.workspace_allowlist,
        "task_models": cfg.task_models,
        "sigils": cfg.sigils,
        "providers": [{"name": p.name, "base_url": p.base_url} for p in cfg.providers],
        "delegate": {
            "mode": cfg.delegate.mode,
            "max_parallel_local": cfg.delegate.max_parallel_local,
            "max_parallel_cloud": cfg.delegate.max_parallel_cloud,
        },
        "idle": {
            "keep_alive": cfg.idle.keep_alive,
            "resident_model": cfg.idle.resident_model,
            "resident_keep_alive": cfg.idle.resident_keep_alive,
            "vram_budget_mb": cfg.idle.vram_budget_mb,
        },
        "tuning": {
            "num_ctx": cfg.tuning.num_ctx,
            "num_gpu": cfg.tuning.num_gpu,
            "num_batch": cfg.tuning.num_batch,
            "num_thread": cfg.tuning.num_thread,
        },
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
            "gdelt_enabled": cfg.osint.gdelt_enabled,
            "rss_enabled": cfg.osint.rss_enabled,
            "naval_enabled": cfg.osint.naval_enabled,
            "tone_signal": cfg.osint.tone_signal,
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
        "skills": {
            "intent_router_enabled": cfg.skills.intent_router_enabled,
            "intent_router_model": cfg.skills.intent_router_model,
        },
        "spotify": {
            "client_id": cfg.spotify.client_id,
            "access_token": cfg.spotify.access_token,
            "refresh_token": cfg.spotify.refresh_token,
            "token_expiry": cfg.spotify.token_expiry,
        },
        "gcal": {
            "client_id": cfg.gcal.client_id,
            "access_token": cfg.gcal.access_token,
            "refresh_token": cfg.gcal.refresh_token,
            "token_expiry": cfg.gcal.token_expiry,
            "calendar_id": cfg.gcal.calendar_id,
        },
        "custom_commands": [
            {
                "name": c.name,
                "description": c.description,
                "trigger": c.trigger,
                "prompt_template": c.prompt_template,
            }
            for c in cfg.custom_commands
        ],
        "mcp": {
            "servers": [
                {
                    "name": s.name,
                    "transport": s.transport,
                    "command": s.command,
                    "cwd": s.cwd,
                    "url": s.url,
                    "enabled": s.enabled,
                }
                for s in cfg.mcp.servers
            ],
        },
    }
    CONFIG_FILE.write_text(json.dumps(data, indent=2))
