# Max — Local-First AI Engine · Roadmap & Brainstorm

> Status: **living document** — Phases 0–18 core + all stretch items **built & working**.
> Includes: DSL + routing, Ollama/Claude streaming, delegate system, Tauri widget, OSINT map
> (with per-source toggles + GDELT tone signal), market tape (sparklines + drill-down),
> Apollo prediction engine, Polymarket intelligence (market news feed), Sentinel 3D space view,
> Aegis self-repair + Leo + Security Posture SAST/SCA (with auto-fix mode + Apollo fix memory),
> Voice I/O + Jarvis personality + user memory, Shadow Net Tor browser, LAN access (HTTPS/QR),
> token/cost Analytics dashboard, and a **Vision Pro / iOS frosted-glass UI** redesign
> (native Tauri window effects — mica/acrylic — carry the frost, not CSS backdrop-filter).
> **Phase 0**: local model benchmark engine + rich Model Manager UI + GitHub Actions CI.
> **268+ engine tests pass; tsc clean; GitHub Actions CI gates all pushes.**

A **local-first**, private AI engine for a powerful workstation, with an **explicit
opt-in cloud escape hatch**. One always-on **engine** (daemon) does the thinking;
thin **clients** (desktop chat app + VS Code extension) talk to it. Local by default,
cloud only when you ask for it — and clearly marked when it happens. A **delegate layer**
lets you fan work out: spin up multiple sessions on the fly, each running a different
model on a different task, in parallel.

## Decisions locked so far
- **Engine language:** Python + FastAPI ✅
- **v1 target:** Desktop **chat app first** (VS Code comes after) ✅
- **VS Code trigger:** **live as you type** (fire on closing delimiter) ✅
- **Routing:** model is **configurable per task**; **provider sigils** (`!`/`@`/`#`) pick the
  provider/model per-invocation; sigils + hotkeys set in the UI ✅
- **Not fully local:** `!` may call a cloud LLM (e.g. Claude). Cloud = opt-in + marked ✅
- **Delegate system:** run multiple sessions in parallel, each on a different model/task ✅
- **Delegate modes:** **Manual** + **Smart-Auto** (AI decides local vs cloud), toggle in settings ✅
- **Scheduling:** smart scheduler + UI to **manually push queued tasks to cloud** when local is backed up ✅
- **Session results:** **isolated** — each viewed separately in its own pane ✅
- **Desktop shell:** **Tauri** ✅
- **v1 scope:** chat + config + **full Smart-Auto delegation** (ambitious but the goal) ✅
- **Smart-Auto signal:** route by **task complexity** (small/simple → local, big/complex → cloud) ✅
- **Workspace access:** a **folder allowlist** set in the UI; anything inside listed paths is in-scope ✅
- VS Code integration is a **later phase** (after the chat app) ✅
- Hardware can be upgraded later if the project proves out ✅
- **Both local (Ollama) + cloud (Claude) wired from day one** (cloud gated by `allow_cloud`) ✅
- **Fix/refactor operator = `~`** (`!` is reserved as the cloud sigil) ✅
- **Beyond coding:** Max grows from coding assistant → **general personal assistant** (reports, music, voice, …) ✅
- **Two planes:** **control plane** (REST + WS/SSE — the client backbone, kept) vs **capability plane** (**MCP** for skills, added) ✅
- **Capabilities via MCP:** the engine is an **MCP host**; skills plug in behind an internal **capability registry** (MCP = default adapter, *not* hard-wired) ✅
- **Intent router:** generalize the delegate from "local vs cloud" → **skill domain + model + locality**; the sigil DSL stays the explicit/manual path ✅
- **Voice:** orchestration via capabilities, but **audio on a dedicated realtime WS channel** (not MCP) ✅
- **Home/LAN:** networked engine adds **bearer-token auth**; MCP skills run as local subprocess *or* networked service ✅
- **OSINT news map:** a glowing 2D world map with a **news heat choropleth** (GDELT + RSS, free/key-less) and a **live day/night terminator**, opened in a dedicated large window from below the chat bar; news egress lives in the engine ✅
- **Aegis (self-debug & fix):** Max watches its own logs/crashes, **asks before touching anything**, AI-diagnoses the root cause (cloud Claude default, local fallback), shows a **diff preview**, applies only on approval with **git-snapshot rollback** + test-verify, and records every action in an organized [`selfdiagnosefixes.md`](selfdiagnosefixes.md). **Two layers**: **Leo**, a bubbly, all-red boot-time **rescue terminal 🐩** that opens from `Max.cmd` when the engine won't start, plus the in-engine runtime layer. **Phase 16** extends Aegis with proactive SAST + SCA security scanning ✅
- *(Full layered design in [docs/architecture.md](docs/architecture.md).)*

---

## 0. Target hardware & the one constraint that matters

| Component | Spec | Implication |
|-----------|------|-------------|
| GPU | RTX 4070 Ti — **12 GB VRAM** | ⛳ **The bottleneck** for *local* models running fast. |
| CPU | i9-14900K (liquid cooled) | Strong CPU offload + great for embeddings/indexing. |
| RAM | 100 GB DDR5 | Run *huge* models (70B+) slowly via CPU/hybrid offload. |

**Design rule:** keep interactive *local* work inside 12 GB VRAM (two-model strategy below).
For heavier needs you now have two outs: (a) slow RAM/CPU offload, or (b) the `!` cloud sigil.
Upgrading the GPU later mainly raises the "runs fast locally" ceiling.

### Candidate local models (benchmark in Phase 0)
- **Inline completion / FIM (tiny, always resident):** Qwen2.5-Coder-1.5B/3B, StarCoder2-3B
- **Code generation (`.`):** Qwen2.5-Coder-14B (Q4 ~9–10 GB), DeepSeek-Coder-V2-Lite
- **Chat / general:** Qwen2.5-14B, Llama-3.1-8B, Mistral-Nemo-12B
- **Docstrings/README (`..`):** reuse code or chat model
- **Embeddings (RAG):** nomic-embed-text, bge-small
- **Cloud (`!`):** Claude (Anthropic API) — opt-in
- **Stretch local (slow, RAM/hybrid):** 32B–70B Q4 (~2–6 tok/s)

---

## 1. Architecture (proposed)

```
                 ┌──────────────────────────────────────────────┐
                 │               MAX ENGINE  (daemon)            │
                 │  • Local HTTP + WebSocket server              │
                 │  • OpenAI-compatible API  ◄── unlocks tools   │
                 │  • PROVIDER ROUTER  (sigil → provider/model)  │
                 │       default / @ Ollama / # Qwen / ! Claude  │
                 │  • Provider adapters: Ollama(local), Claude…  │
                 │  • Command Parser  (the  .  /  ..  DSL)       │
                 │  • DELEGATE / SESSION MGR (parallel tasks)    │
                 │       scheduler aware of 12 GB VRAM limit     │
                 │  • Per-task model config + hotkey registry    │
                 │  • Context Engine  (workspace RAG, memory)    │
                 │  • Privacy guard (mark/confirm cloud egress)  │
                 └───────────────┬──────────────────┬───────────┘
                                 │                  │
                   ┌─────────────┴───────┐  ┌───────┴──────────────┐
                   │   Desktop Chat App   │  │  VS Code Extension   │
                   │  (v1) chat + config  │  │  .  / ..  live-type  │
                   │  models, sigils, keys│  │  per-sigil routing   │
                   └──────────────────────┘  └──────────────────────┘
```

**One engine, many clients.** All logic (parsing, routing, prompts, RAG, privacy)
lives in the engine once. Clients stay thin; adding a CLI/Neovim client later is cheap.

**OpenAI-compatible endpoint** = the local side speaks a standard API, so existing tools
work against Max for free; the DSL + routing is the value-add on top.

**Provider adapter abstraction** = local (Ollama → later llama.cpp/vLLM) and cloud
(Claude → later others) sit behind one interface, so sigils just select an adapter+model.

### Stack
| Layer | Choice |
|-------|--------|
| Engine | **Python + FastAPI** ✅ |
| Local inference | **Ollama** first; adapter to swap → llama.cpp / vLLM |
| Cloud inference | **Anthropic (Claude)** adapter; pattern reusable for others |
| Desktop UI | **Tauri** ✅ (locked) |
| VS Code ext | TypeScript |
| Vector store | sqlite-vec or LanceDB (embedded) |

---

## 2. The DSL — provider sigils × operators

**Command = `[sigil][operator] … [operator]`**

### Provider sigils (configurable in UI; these are defaults)
| Sigil | Provider | Locality |
|-------|----------|----------|
| *(none)* | per-task default model | local |
| `@` | Ollama | local |
| `#` | Qwen | local |
| `!` | Claude | ☁ **cloud (opt-in, marked)** |

### Operators
| Operator | Meaning | Example |
|----------|---------|---------|
| `. <instruction> .` | **Generate code** | `. add a function to do X and call Y .` |
| `.. <code> ..` | **Summarize / docstring / README** | `.. def _rec_key(...): ... ..` |
| `~ <code> ~` | **Fix / refactor** | `~ tidy this messy block ~` |

### Combined examples
| You type | Resolves to |
|----------|-------------|
| `. … .` | generate code · default code model (local) |
| `!. … .` | generate code · **Claude (cloud)** |
| `@.. code ..` | docstring · Ollama (local) |
| `#. … .` | generate code · Qwen (local) |

**Decided:** `~ code ~` = fix/refactor (since `!` is reserved as the cloud sigil).
**Proposed (optional):** `? code ?` = explain.

Parser rules:
- Parser + router live in the **engine** so every client behaves identically.
- Sigils, operators, and per-task default models are all **user-configurable**.
- Each operator maps to a dedicated, **user-editable prompt template**.
- Any cloud sigil triggers the **privacy guard** (visible marker / optional confirm).

---

## 3. Upcoming phases

> Legend: `[x]` done · `[~]` partial (note explains what's left) · `[ ]` not started.

### Phase 7 — Performance & privacy polish  ✅ *snappy, stable, provably local-by-default*
- [x] **Two-model routing**: `idle.resident_model` (default: qwen2.5-coder:3b) always pinned in VRAM via `keep_alive=-1`; heavy models load on demand with `idle.keep_alive` (default 10m); `/complete` (FIM) routes to resident model automatically; `router.py` short-circuits completion to resident when no explicit sigil
- [x] Keep-alive + smart load/unload — `VramManager` (`providers/vram.py`) polls Ollama `/api/ps`; `GET /models/loaded` exposes loaded models + VRAM usage; `evict_to_fit()` evicts largest-first while protecting resident model; factory passes correct keep_alive per model
- [x] **Network kill-switch** (`force_offline: bool`) blocks ALL outbound calls (OSINT, Market, Polymarket, Sentinel, cloud AI) via `_check_network()` guard in `main.py`; toggle in Settings "Cloud & AI Routing"; red banner when active; `_ai_route()` falls back to local when kill-switch is on
- [x] **Egress audit log viewer** — `GET /egress/log` + `DELETE /egress/log` endpoints parse `.egress.log`; full table UI in Settings "Egress Audit Log" section with refresh + clear buttons, newest-first, token counts
- [x] Resident model warm-up on engine startup (async ping to pre-load into VRAM)
- [ ] Quantization / KV-cache / context-length tuning (Ollama config options — deferred)
- [ ] Latency targets (completion < Xms, gen first-token < Yms — measurement tooling deferred)

### Phase 8 — Advanced / stretch  🎯 *agentic & multi-file*
- [x] **Multi-file / repo-wide edits with plan + approval** — Code Hub tab: `POST /code/plan` streams a multi-file `EditPlan`, `POST /code/apply` writes patches behind a git snapshot, `POST /code/rollback` reverts; frontend `app/src/code/` (CodeView + FileTree + Terminal)
- [x] **User-defined custom commands & template library** — `custom:<name>` triggers (any single delimiter char) in `dsl/parser.py`; add/edit/remove UI in Settings (`CustomCommandsSection`), persisted via config
- [~] **More providers + more clients** — OpenAI provider built (`%` sigil, `providers/openai_provider.py`, cost catalog) + LAN browser client (Phase 17) + **OpenAI-compatible local adapter** (`^` sigil, `providers/openai_compat.py`): one `local`-kind provider for any local server speaking `/v1/chat/completions` (llama.cpp `llama-server`, vLLM, LM Studio); connect-only (no spawning), no API key, no egress, usage recorded at $0 like Ollama; configurable `base_url` (default `:8080`) round-tripped through `/config`; Model Manager "Local server" card (reachability dot + served models from `GET /v1/models`) + Task Routing optgroup; 6 tests. **Still open:** CLI client, Neovim client
- [x] Vision models — image attach in chat bar, routes to Claude or OpenAI vision

### Phase 9 — Capability platform & general assistant (beyond coding)  ✅ *add skills, not rewrite the core* ([architecture](docs/architecture.md))
*Turns Max from a coding assistant into a general personal assistant. Layered so each new ability is a plug-in, not a core change. Builds on the engine/delegate already in place — keeps 100% of current functionality.*
- [x] **Capability registry** — `Capability` ABC + `CapabilityRegistry` singleton; native-Python adapter (no lock-in); `GET /capabilities` list endpoint; skills auto-registered on startup
- [x] **Intent router** — `POST /capabilities/route` classifies free-form requests using the resident local model into domain (web_search / report / spotify / calendar / files / code / chat); prefix normalisation ("web" → "web_search"); DSL sigils stay the explicit manual path
- [x] **First skills**: **Web Search** (DuckDuckGo lite + AI synthesis, no key), **Reports** (AI Markdown reports saved to `engine/reports/`), **Files** (read/search/write within workspace allowlist), **Spotify** (OAuth PKCE, playback + track search), **Google Calendar** (OAuth2 PKCE, list/create/delete events)
- [x] **⚡ Skills Hub tab** — sidebar nav across all 5 skills; streaming panels; in-app OAuth connect/disconnect; connection-dot status indicators
- [x] **Settings section** — intent router toggle, Spotify + Google Calendar connect/disconnect, credential env hints
- [x] **49 new tests** green (web search, reports, files, Spotify, Calendar, registry + router); total **349 passing, tsc clean**
- [x] **Voice** — already complete in Phase 14 (Web Speech API + Whisper); Phase 9 WebSocket re-architecture not needed
- [x] **Auth for home/LAN** — home-network firewall rule (Phase 17) is sufficient; bearer tokens deferred
- [x] *(stretch)* **MCP host — both directions** (`engine/max_engine/mcp/`): **outbound** — `MCPManager` connects Max to external MCP servers over **stdio** (`MCPStdioClient`) or **HTTP** (`MCPHttpClient`), runs `initialize`→`tools/list`, and routes `tools/call`; managed via `GET/POST/DELETE /mcp/servers`, `/mcp/servers/{name}/connect|disconnect`, `POST /mcp/call`; server list persisted in `.maxconfig.json` (`MCPConfig`). **Inbound façade** — `MaxFacade` exposes Max's skills as MCP tools (`max_ask` routes through the intent router, `max_market_board`, `max_osint_hotspots`); `python -m max_engine.mcp_server` is a stdio entrypoint Claude Desktop/Cursor launch (cross-platform stdin via executor — `connect_read_pipe` is unsupported on Windows); `GET /mcp/facade` returns the manifest + a paste-ready `claude_desktop_config.json`. Settings **🔗 MCP** section (add/connect/probe servers + façade config). No new deps (stdlib + httpx). **18 tests** (stdio framing, manager, HTTP client, façade dispatch, endpoints).

### Phase 17 — LAN Access: Max on your iPhone & Mac over WiFi  📱 *open Max in a phone/Mac browser on the same network — all compute stays on this PC* — ✅

*Today Max only runs as the desktop widget. This phase lets you open Max from your iPhone and Mac in a browser over the same WiFi, while the engine, Ollama, Tor, and cloud-API keys stay on this desktop. The frontend already talks to the engine purely over HTTP `fetch` (no Tauri IPC for backend calls), so a plain browser can drive the whole engine — the work is exposing it safely and giving phones a touch-first UI. A **"Share on LAN" toggle** in Settings flips the engine from safe localhost to `0.0.0.0:8443` over HTTPS, serves a dedicated **mobile web UI**, and shows the `https://<pc-name>.local:8443` URL plus a scannable QR code. The desktop widget keeps working unchanged. First step toward a later "accessible from anywhere" phase (Tailscale/Cloudflare) — explicitly out of scope here. Full plan: `C:\Users\tadjo\.claude\plans\lets-plan-a-new-enumerated-parnas.md`.*

**The load-bearing gotcha:** iOS Safari treats a LAN IP/host over plain HTTP as an *insecure context*, which **silently disables the mic / Web Speech / clipboard** (`localhost` is exempt, `192.168.x.x` and `*.local` are not). Voice on mobile is required → **HTTPS via a locally-trusted cert is mandatory**, not optional polish.

**Decisions locked:** mic on mobile required → **HTTPS mandatory** · **engine serves the built frontend** (single origin → no CORS) · desktop Tauri app **stays open** (LAN is an in-app toggle, no standalone launcher) · **no app token** — rely on home LAN + a subnet-scoped Windows firewall rule (`profile=private`, `remoteip=LocalSubnet`) · HTTPS via **mkcert** + install/trust root CA on the iPhone (pure LAN, no internet/accounts) · reach the PC at **`<computer-name>.local`** via mDNS (cert SANs also cover LAN IP + `localhost` + `127.0.0.1`) · **uvicorn built-in TLS** (`--ssl-keyfile/--ssl-certfile`, no Caddy) on port **8443** · connect UX = **toggle + URL + QR** in Settings · **dedicated mobile build** (separate Vite entry, built alongside desktop) · cert setup is **app-assisted** (run mkcert, generate cert w/ SANs, reveal/AirDrop root CA + short trust doc) · LAN state **remembered** across launches · phone feature priority **Chat+Voice · Market/Polymarket · OSINT/Sentinel** (Aegis/Shadow Net deferred).

- [x] **17.A — Engine serve + dynamic base + HTTP LAN bind**: `main.py` mounts the Vite `dist/` as `StaticFiles` (single origin) with a UA-based mobile redirect (`/` → `/m`); narrow CORS `allow_origins=["*"]` → LAN `allow_origin_regex`; new `EngineConfig` fields (`lan_enabled`, `lan_host`, `lan_port`, `tls_cert`, `tls_key`) round-tripping through `.maxconfig.json`; make `app/src/engine.ts` base URL dynamic (same-origin in a served browser, absolute via a new `engine_base()` Tauri command in the webview); parametrize Rust `spawn_engine()` to bind `0.0.0.0` (HTTP first, to validate).
- [x] **17.B — Mobile-first shell**: `src/mobile/` — `MobileApp.tsx` with bottom-tab nav (Chat+Voice · Markets · Intel · Space); `ChatTab.tsx` (streaming chat + Web Speech API mic + TTS); `MarketsTab.tsx` (live quotes + AI read); `OsintTab.tsx` (severity hotspots + articles); `SentinelTab.tsx` (ISS live + space weather + launches); `Mobile.css` dark touch-first styles. Served at engine `/m` (FastAPI `FileResponse(index.html)`) — `main.tsx` detects `pathname === "/m"` and renders `MobileApp` instead of the desktop shell; same bundle, zero separate build step.
- [x] **17.C — HTTPS: certs + TLS + firewall**: `setup_cert()` / `reveal_root_ca()` Tauri commands run mkcert (`-install`, then SANs `<pc>.local <lan-ip> localhost 127.0.0.1`); Rust spawns uvicorn with `--ssl-keyfile/--ssl-certfile` on `:8443` when LAN-enabled; health/port checks speak HTTPS to `127.0.0.1:8443` (keep `127.0.0.1`, never `localhost`); add/remove the subnet-scoped firewall rule (elevated/UAC) on toggle; `docs/lan.md` with the iPhone "enable full trust" steps. **`find_mkcert()` hardened** (`lib.rs`) — resolves the binary across `where`/PATH, WinGet Links shim, Chocolatey, Scoop, `go install`, plus a bounded recursive scan of `WinGet/Packages` for the versioned `mkcert*.exe`, so cert setup works even when the GUI inherited a stale pre-install PATH.
- [x] **17.D — Settings "Share on LAN"**: section in `settings/SettingsView.tsx` with the toggle (`set_lan_mode`), live `lan_status` (`{enabled, url, pc_name, lan_ip, cert_ready}`), copyable `https://<pc-name>.local:8443` URL, **QR code**, cert-helper buttons + trust steps, firewall/Private-network hint; LAN state remembered across launches.

> **Future phase (out of scope here):** remote/internet access (Tailscale `*.ts.net` or Cloudflare Tunnel), app-level auth tokens, and multi-user — noted only as the upgrade path that this single-origin HTTPS app extends into cleanly.

---

## 4. Notes & recommendations
1. **Cloud is opt-in and visible.** `!` sends code off-machine — needs a key, a marker, and
   (configurable) a confirm. A global kill-switch forces fully-offline mode.
2. **Provider adapter pattern** keeps local/cloud symmetric — adding OpenAI/Gemini later is trivial.
3. **Two-model strategy** is how we live within 12 GB VRAM until a GPU upgrade.
4. **OpenAI-compatible API** for the local side = free ecosystem compatibility.
5. **Diff-preview-before-apply** in VS Code for trust/safety.
6. **Everything configurable** (sigils, operators, per-task models, hotkeys, templates) — your core ask.

## 5. Open questions (next round)
*(Resolved: Tauri shell, `~` fix operator, and both local+cloud from day one — now under "Decisions locked".)*
- Does v1 chat app need **codebase RAG**, or is plain chat + model config enough to start?
- Default per-task models — propose a concrete default mapping after the Phase 0 benchmark?
- **Engine end-to-end verification** (next milestone): which local model(s) to pull first for the smoke test, and do we test the `!` cloud path now or after a key is set up?

---

## ✅ Completed Phases

### Phase 0 — Foundations & decisions  🎯 *stack locked, models benchmarked*
- [x] Engine language = Python/FastAPI
- [x] Desktop UI shell decision — **Tauri** (locked)
- [x] Monorepo structure (`/engine`, `/app`, `/docs` exist; `/extension` lands in Phase 5)
- [x] Install + smoke-test Ollama ✅ (0.24; `qwen2.5-coder:3b`+`:14b`, smoke all PASS); Anthropic API access for `!` ✅ (key in `engine/.env`)
- [x] **Benchmark local models on the 4070 Ti** (tokens/s, VRAM, quality) → live timed benchmark via `/models/benchmark`; results stored in `.apollo.db`; shown in Model Manager
- [x] Dev tooling: lint/format/test done (**ruff + pytest, 268 passing**); **GitHub Actions CI** (`.github/workflows/ci.yml` — pytest + tsc gates every push); **pre-push hook** (`scripts/pre-push.ps1`) blocks push + reports failures to Aegis; SessionStart hook: engine health + provider ping on startup
- [x] Lock the DSL grammar (sigils + operators + escaping) — parser implemented + tested

### Phase 1 — Engine MVP (the brain)  🎯 *`curl` can chat with Max via any provider*
- [x] Provider adapter interface
- [x] Ollama (local) adapter (streaming) — **verified end-to-end** against live Ollama (`/command` + `/v1/chat/completions` stream real tokens; sessions run → done)
- [x] Anthropic/Claude (cloud) adapter (streaming) — **verified end-to-end** (`!` + cloud sessions stream real Claude output; API errors surfaced)
- [x] OpenAI-compatible `/v1/chat/completions` with **streaming** (SSE); `provider` selectable
- [x] `/command` endpoint: full DSL → router → provider stream (sigil picks local/cloud)
- [x] Per-provider model overrides (cloud `!` → Claude model, local → coder model)
- [x] Provider router (sigil → adapter+model) + per-task default model config (`router.py`)
- [x] Config system — defaults + file-backed persistence (`/config` GET/PUT → `.maxconfig.json`); **hot-reload**: background watcher reloads file on mtime change; `task_models` + `sigils` round-trip through config; expanded `ConfigPatch` with `aegis.autonomy`
- [x] **Privacy guard** — cloud routes flagged (`is_cloud`) + `allow_cloud` gate + keys from env; **egress audit log** (`engine/.egress.log` — one line per Anthropic call with model/action/token counts)
- [x] Health/status endpoint (`/health` ✅); background daemon mode: uvicorn process managed by Rust launcher

### Phase 2 — Command DSL & routing ✅
*All four DSL operators wired end-to-end; post-processor ships in both engine and extension.*
- [x] DSL parser (sigils + `.`/`..`/`~`, escaping, nested code) — `dsl/parser.py`, tested
- [x] Wire parser → router → adapter — the `/command` endpoint
- [x] `.` → code generation; `..` → docstring/README; `~` → fix/refactor — system prompts in `prompts.py`
- [x] Output post-processing — `engine/max_engine/postprocess.py` (strip_fences + reindent, 14 tests); `extension/src/extension.ts` applies `postProcess(acc, baseIndent)` on every streaming chunk: opening fence never shows, closing fence stripped on arrival, all continuation lines aligned to the command's column

### Phase 3 — Desktop widget app  🎯 **v1 — floating widget + configure everything** ([UI design](docs/ui.md))
- [x] **Floating transparent widget** — frameless/transparent/always-on-top/skip-taskbar window, **top-right anchoring**, **global hotkey toggle** (`Ctrl+Shift+M`), and **click-through-when-idle** (Rust cursor-poll). ✅
- [x] **Live vector mascot** ("X") reacting to engine state (idle / thinking / busy / done / error) — built as a **"Jarvis"-style SVG + CSS HUD** (not Rive; same state API)
- [x] **Task cards** per session (model · provider · state · ☁ marker · cancel/promote) — **live**: polls the engine's `/sessions` (~2s), cancel/promote call the engine; mascot reacts to real session states.
- [x] **SYS INFO** meters (CPU · GPU · **VRAM** · RAM) + **⚙ settings** cog — **live** values (Rust `sysinfo` for CPU/RAM, `nvidia-smi` for GPU/VRAM, polled ~1.5s)
- [x] Chat UI — plain chat (`/chat`) + DSL commands (`/command`), **markdown with code blocks + copy button**, cloud (`!`) indicator, SSE streaming, `/health` status dot
- [x] **Model manager**: rich card-based UI (`app/src/settings/ModelManager.tsx`) — Local tab (installed Ollama models: size, quant, VRAM estimate, benchmark tokens/s + TTFT, ↓ install suggested models), Cloud tab (Claude / GPT / Gemini cards: cost/1M, cost multiplier, context window, strengths, key status), Task Routing tab (per-task model selector)
- [x] **Routing config**: `PUT /config { task_models, sigils }` updates live routing + persists; Task Routing matrix in Model Manager maps generate/chat/fix/summarize/completion → model
- [x] **Provider/key management** — cloud on/off ✅ + key-set status shown + expanded to `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `NASA_API_KEY`; per-provider key entry in `engine/.env` by design
- [x] Settings: **auto-delegate toggle (Manual / Smart-Auto)** + cloud on/off + **parallel limits** — live via `/config`, persisted to `.maxconfig.json`
- [x] **Workspace folder allowlist** — add/remove paths in settings, persisted

### Phase 4 — Delegate system: parallel sessions & multi-model orchestration ✅
*Engine side built + tested (29 tests); dashboard/streaming UI wired in the Tauri app.*
- [x] Session manager: spawn / track / cancel concurrent sessions, each bound to a provider+model
- [x] **Mode (config): Manual** (you assign model+task) **and Smart-Auto** (engine decides local vs cloud)
- [x] Smart-Auto router: choose local vs cloud per task by **task complexity** (+ local queue depth)
- [x] Task scheduler aware of the **12 GB VRAM limit** (cloud + small-local run in parallel; heavy local models queue)
- [x] Manual override (backend): `promote` a queued session to cloud when local is backed up
- [x] **Isolated sessions** — each tracked + retrieved separately (`/sessions` API)
- [x] **Queue dashboard** (UI) — live task cards poll `/sessions`; cancel/promote wired; **cards now render live output** (per-session SSE: `snapshot` then `chunk` deltas, blinking caret while running)
- [x] Streaming each session's output concurrently to the client — **SSE** `GET /sessions/{id}/stream`; engine fan-out via per-session subscribers
- [x] **Delegator/coordinator**: `POST /sessions/coordinate` — planner decomposes request into parallel subtasks (defensive JSON parse + single-task fallback)

### Phase 5 — VS Code extension ✅
*Built in `extension/` (TypeScript, esbuild; typecheck + build clean). Run with F5.*
- [x] **Trigger (configurable)** — `auto` fires on closing delimiter (debounced); `manual` uses `ctrl/cmd+enter`
- [x] **Sigil routing honored from the editor** — raw command sent to `/command`; engine parses `@`/`#`/`!` and routes
- [x] Stream results; **inline replace** — command span replaced with streamed output as it arrives (single undo)
- [x] Engine status + active-model surface; **cloud (☁) indicator** while a `!` command runs
- [x] Ghost-text **FIM autocomplete** — `InlineCompletionItemProvider` → engine `POST /complete` (Ollama FIM), debounced/cancellable, toggleable

### Phase 6 — Context & RAG (Max knows your codebase) ✅
*Engine side built + tested (`engine/max_engine/rag/`, 17 tests). Scoped to workspace allowlist for privacy.*
- [x] Workspace indexer — file walk with noise-dir pruning + text/size filters; line-aligned overlapping chunker
- [x] Embeddings + local vector store (sqlite-vec); **incremental re-index** keyed on per-file content hash
- [x] Retrieval injected into prompts — `POST /rag/ask` streams grounded answers **cited by `file:line`**
- [x] **UI**: 🧠 toggle routes questions to `/rag/ask`; ⟳ index button shows live `files / chunks` counts; ✕ clears session memory
- [x] **Session memory** — `SessionMemory` carries prior turns per `session_id`; fed to model + used to widen retrieval so terse follow-ups still pull the right code

---

### Phase 10 — OSINT global news map  ✅ *a glowing world map of where the news is happening, with a live day/night terminator*
*A button below the chat bar opens a large dedicated window with a 2D world map: glowing-blue country wireframe, a news-driven heat choropleth, and a real-time day/night terminator. All news egress lives in the engine; the map atlas is bundled locally so only news data touches the network.*

**Decisions locked:** 2D flat (equirectangular) map · dedicated large window · **GDELT + RSS** from day one (free, no key) · engine-side egress · bundled atlas.

- [x] **Engine OSINT module** (`engine/max_engine/osint/`): GDELT DOC 2.0 client + stdlib RSS/Atom fetcher + country gazetteer (name/demonym → ISO-A3) + importance scorer (volume × source-diversity × recency) + TTL-cached aggregator service
- [x] **Endpoints**: `GET /osint/heatmap` (per-country 0..1 intensity), `GET /osint/articles?country=&limit=` (ranked, newest-first), `GET /osint/sources`, `GET /osint/events`, `GET /osint/naval`, `POST /osint/chat` (SSE)
- [x] **Config**: `OsintConfig` (GDELT query/timespan/max-records, feed list, cache TTL); no new Python deps (stdlib XML, existing httpx)
- [x] **Tests**: `tests/test_osint.py` — gazetteer, GDELT/RSS parsing, scoring, dedup, caching, endpoints (13 tests, network mocked)
- [x] **Desktop map** (`app/src/osint/`): `WorldMap` (d3-geo equirectangular + `world-atlas` TopoJSON, glow wireframe, heat choropleth, hover/select), `terminator.ts` (subsolar point + night ring, refreshed each minute), `OsintView` (map + ranked countries + article panel), `OsintButton` (below chat bar)
- [x] **Dedicated window**: `#osint` hash route in `main.tsx`; Tauri `WebviewWindow` (1180×760, resizable) + `core:webview:allow-create-webview-window` capability; in-page overlay fallback outside Tauri
- [x] **Severity classification** — Critical / High / Medium / Low from headline *content* (word-boundary keyword tiers, `osint/severity.py`); country badge = **recency-weighted mean** so one outlier story can't flip a whole country; filter bar gates map + hotspots + articles by tier
- [x] **Sleeker "threat-intercept" redesign** — dropped the rainbow heat ramp for a discrete dark-ops threat scale (cyan→amber→orange→rose) with per-tier glow; tactical graticule; severity-coded hotspot bars + article edges (shadowbroker-style aesthetic)
- [x] **Naval layer (US fleet positions)** — `osint/naval.py`: parses the latest USNI Fleet Tracker + TWZ Carrier Tracker; anchors on hull tokens (`CVN-73`) with name fallback, geocodes the nearest region phrase via a sea/port/AOR gazetteer; `GET /osint/naval`. Carrier (gold chevron) + amphib (steel diamond) markers with a `⚓ Fleet` toggle; 6 naval tests
- [x] **Verified end-to-end**: live GDELT+RSS (e.g. 360 signals / 61 countries), severity tiers, threat shading, moving terminator + subsolar marker, filter toggles, country click → filtered articles; `npm run build` + `tsc` clean
- [x] **Surface egress in settings/privacy guard** — amber egress warning added to OSINT settings section ✅
- [x] **Tauri external links** via the opener plugin — article links now use `@tauri-apps/plugin-opener`; falls back to `window.open` in browser ✅
- [x] *(stretch)* **Per-source toggles** (GDELT / RSS / Naval) in OSINT settings + `OsintConfig`; **GDELT tone signal** (opt-in amplifier: negative tone → more heat) wired through Article model → score.py `use_tone=True` → settings toggle
- [x] *(stretch)* **time-scrubber** to replay the last 24h of heat (`GET /osint/timeline` — cumulative per-frame `score_countries`; play/pause + range scrubber, map+hotspots reflect the selected frame); **cluster/event detail on click** (proximity clustering in `WorldMap`, zoom-aware threshold; click opens a detail card listing the clustered events with source links); **per-source domain toggles** in the UI (`GET /osint/domains` + `domains=` allowlist on `/osint/heatmap` + `/osint/articles`; ⌗ Sources popover re-filters heat+articles live)

---

### Phase 11 — Market: live stocks + AI Ingest  ✅ *a live US-stock tape with an on-demand AI read*
*A `$` button opens a large dedicated window: a live US-stock board on the left and an AI analysis panel on the right. Quote egress lives in the engine.*

**Decisions locked:** **Finnhub** as the source (free `FINNHUB_API_KEY` in `engine/.env`) · **user-editable** watchlist (curated megacap default, persisted) · AI analysis runs **only** on the top **"Ingest"** button · "live" = frontend polls every ~10s against a 10s engine TTL cache.

- [x] **Engine market module** (`engine/max_engine/market/`): Finnhub `/quote` + `/stock/profile2` client (per-symbol failures swallowed), `MarketService` with concurrent fetch + TTL cache + watchlist mutation, `Quote`/`MarketBoard` models
- [x] **Endpoints**: `GET /market/quotes` (live board), `GET`/`PUT /market/watchlist` (editable + persisted), `GET /market/sources` (provider + `key_set`), `POST /market/analyze` (SSE), `POST /market/chat` (SSE)
- [x] **Config**: `MarketConfig` (watchlist + cache TTL); watchlist round-trips through the persisted-override subset; no new Python deps (existing httpx)
- [x] **Tests**: `tests/test_market.py` — quote parsing, unknown-symbol/HTTP-error skip, board aggregation + caching, no-key empty board, watchlist round-trip/dedup, endpoints (network mocked)
- [x] **Desktop board** (`app/src/market/`): `MarketView` (polling stock rows, green-up/red-down, watchlist add/remove, streaming Ingest panel), `MarketButton` (`$` icon, next to OSINT), `market.ts` client; `#market` hash route + `market` Tauri window capability; in-page overlay fallback
- [x] **Surface egress in settings/privacy guard** — amber egress warning added to Market settings section ✅
- [x] *(stretch)* **Sparkline charts** (`Sparkline` SVG component, 30-day closing prices, lazy-loaded per ticker); **per-ticker drill-down modal** (price, day stats, full 30-day chart); **intraday history** via `GET /market/candles/{symbol}` (Finnhub `/stock/candle` endpoint)
- [x] *(stretch)* **WebSocket trade stream** for true real-time ticks — `market/stream.py` `TradeStream` holds one upstream Finnhub WS, fans out to browsers via SSE (`GET /market/stream`), auto-reconnects + live watchlist re-subscribe; frontend overlays live ticks on the polled board with a green ● LIVE indicator + per-tick price flash. **Per-ticker intraday drill-down with resolution selector** — drill-down modal gains 1D/1W/1M/3M/1Y buttons (5-min → weekly via `/market/candles` resolution+days)

---

### Phase 11.5 — Polymarket: Prediction Markets Intelligence  ✅ *full Polymarket data view with local AI embedding*
*A new Hub tab (Ψ Poly). Full Polymarket data view: active prediction markets, YES/NO probability gauges, price history chart, order book depth, category filtering, and a user watchlist. Market data is locally embedded into Apollo's sqlite-vec store.*

**Decisions locked:** **Gamma API** (`gamma-api.polymarket.com`) for market listings/metadata · **CLOB API** (`clob.polymarket.com`) for order book and price history · **no API key required** (public read access) · **Apollo bridge** — markets embedded with `source="polymarket"` into the shared sqlite-vec store (24h TTL, same embed model).

- [x] **Engine polymarket module** (`engine/max_engine/polymarket/`): Gamma + CLOB `httpx` clients, `PolymarketService` with TTL cache (120s board / 1h history) + async lock + watchlist mutation, `Market`/`Outcome`/`PricePoint`/`OrderBook`/`PolymarketBoard` models, Apollo bridge `embedder.py`
- [x] **Config**: `PolymarketConfig` (watchlist, ttl_seconds, embed_enabled, categories) in `config.py`; round-trips through `_apply_overrides` + `save_overrides`; persisted in `.maxconfig.json`
- [x] **Endpoints**: `GET /polymarket/board`, `GET /polymarket/markets?category=`, `GET/PUT /polymarket/watchlist`, `GET /polymarket/prices/{condition_id}?interval=`, `GET /polymarket/order-book/{token_id}`, `GET /polymarket/sources`, `POST /polymarket/ingest` (SSE embed), `POST /polymarket/analyze` (SSE AI brief), `POST /polymarket/chat` (SSE conversational)
- [x] **Prompts**: `"polymarket"` analyst prompt + `"polymarket_chat"` conversational prompt in `prompts.py`; `polymarket_chat_messages()` helper
- [x] **Tests** (`tests/test_polymarket.py`): 24 tests passing, full suite 164 tests green at time of build
- [x] **Desktop board** (`app/src/polymarket/`): `PolymarketView` (category tabs All/Politics/Crypto/Sports/Economics/Entertainment/Science/World/★ Watchlist, three-column layout: market list · detail · AI panel), `PriceChart` (SVG probability chart, interval selector 1D/1W/1M/Max), `OrderBookPanel` (bid/ask depth ladder), `polymarket.ts` client, `Polymarket.css` (dark theme, gold accent, probability gauges green/amber/red)
- [x] **Hub integration**: `"polymarket"` tab added to `HubTab` union + TABS array (glyph Ψ, label "Poly", gold accent in `Hub.css`); lazy-mount `<PolymarketView />`; Ψ launcher button in `HubButtons.tsx`; `#polymarket` hash route in `main.tsx`
- [x] **Surface egress in settings/privacy guard** — amber egress warning + new Polymarket settings section added ✅
- [x] *(stretch)* **Per-market news feed** from Gamma `events` field (`GET /polymarket/news/{condition_id}` + `MarketNewsFeed` component in detail column)
- [x] *(stretch)* **Real-time price streaming** via Polymarket CLOB WebSocket — `polymarket/stream.py` relays the public CLOB *market* channel to the browser as SSE (`GET /polymarket/stream?token_ids=`); selected-market detail panel live-updates the YES price + order book with a ● LIVE badge, reconnects on drop. **Read-only portfolio tracking** by wallet address — `fetch_positions` via the public Data API + `GET /polymarket/portfolio?address=`; 💼 Portfolio view with positions table + aggregate P&L, address remembered in localStorage

---

### Phase 12 — Sentinel: 3D Space Intelligence  ✅ *interactive 3D Earth globe + live solar system with asteroid tracking*
*A new Hub tab (🛰 Sentinel). Two internal sub-views: Earth View (live satellite tracking on a 3D globe) and Solar System View (heliocentric planets + asteroid orbits). Mirrors the OSINT module pattern — thin React frontend, thick cached Python backend, SSE for AI chat.*

**Decisions locked:** **Three.js** for 3D rendering (both views) · **satellite.js Web Worker** for client-side SGP4 propagation off the main thread (5000+ satellites at 30fps) · **CelesTrak TLEs** (free, no key) as the satellite data source · **NASA NeoWs** (free NASA API key) for asteroid close approaches · **VSOP87 truncated coefficients** hardcoded in `solarUtils.ts` for planet positions (no external call) · same Hub tab/lazy-mount pattern as existing modules.

**Data sources (all free):**
| Source | Data | Key? |
|---|---|---|
| CelesTrak | TLE data for ISS, Starlink, GPS, Galileo, weather sats | None |
| NASA NeoWs | Near-Earth asteroid close approaches + orbital elements | Free NASA key |
| JPL SBDB | Asteroid orbital elements for 3D rendering | None |
| NOAA SWPC | Solar wind speed, Kp index, CME alerts, X-ray flux | None |
| NASA CNEOS | Fireball/meteor events (last 30 days) plotted on Earth | None |
| RocketLaunch.live | Next 5 rocket launches with pad lat/lon | Free tier, no key |
| open-notify.org | ISS crew roster + live ISS position (5s poll) | None |

- [x] **Engine sentinel module** (`engine/max_engine/sentinel/`): `tle.py` (CelesTrak group fetcher + 3-line parser), `asteroids.py` (NeoWs close-approaches + JPL SBDB orbital elements), `space_weather.py` (NOAA SWPC JSON), `fireballs.py` (CNEOS), `launches.py` (RocketLaunch.live), `iss.py` (open-notify.org); `SentinelService` with per-feed TTL cache + async locks
- [x] **New Python deps**: `sgp4>=2.22` (SGP4 propagation for backend `/sentinel/satellites/now`), `numpy>=1.26` (vectorized batch propagation)
- [x] **Endpoints**: `GET /sentinel/tle`, `GET /sentinel/satellites/now`, `GET /sentinel/neo`, `GET /sentinel/space-weather`, `GET /sentinel/launches`, `GET /sentinel/fireballs`, `GET /sentinel/iss`, `POST /sentinel/chat` (SSE, same `_sse_stream` helper)
- [x] **Config**: `SentinelConfig` in `config.py` (TLE groups, TTLs, `neo_days_ahead`, `fireball_days`); `NASA_API_KEY` from env
- [x] **New npm deps**: `three ^0.167.0`, `@types/three`, `satellite.js ^5.0.0`, `@types/satellite.js`
- [x] **Frontend** (`app/src/sentinel/`): `SentinelView.tsx` (Earth/Solar sub-tab toggle + AI chat slide-in), `EarthView.tsx` (Three.js globe), `SolarView.tsx` (Three.js heliocentric), `earthUtils.ts`, `solarUtils.ts` (VSOP87 constants + Kepler solver), `satelliteWorker.ts` (Web Worker), `useThreeScene.ts` (shared Three.js lifecycle hook), `sentinel.ts` (API client), `Sentinel.css`
- [x] **Earth View**: neon-hologram Earth sphere + day/night textures, Fresnel atmosphere glow, `DirectionalLight` from subsolar point, satellite `Points` geometry (SGP4 Web Worker ~100ms), selected satellite orbit `Line`, aurora `TorusGeometry` rings at ±65° (Kp-driven), fireball `ConeGeometry` markers, launch pad markers, `OrbitControls`
- [x] **Solar System View**: Sun + `PointLight` at origin, planet orbit `RingGeometry`, planet spheres at VSOP87 positions (log-scale radii), main-belt asteroid `InstancedMesh`, NEA `Line` tracks, time scrubber, hazardous NEA red glow, `OrbitControls` default top-down
- [x] **Hub integration**: `"sentinel"` Hub tab (🛰 Sentinel) + launcher button in `HubButtons.tsx`; `#sentinel` hash route in `main.tsx`
- [x] **AI chat** (`POST /sentinel/chat`): grounded in live snapshot (space weather, ISS crew, NEA close approaches, next launch); mascot `mascot:signal` on submit
- [x] **Tests**: `tests/test_sentinel.py` — TLE parsing, SGP4 propagation, space weather parsing, asteroid model, endpoints (network mocked); `sgp4`/`numpy` in test env

---

### Phase 13 — Aegis: AI self-debug & fix engine  ✅ *Max watches its own logs, explains what broke, and — with your OK — fixes itself* ([design](docs/aegis.md))

**Decisions locked:** **two layers** — **Leo**, a **boot-time rescue terminal (build first)** that opens when the engine won't even start, plus the **in-engine runtime layer** · **diagnose → ask → apply** (never silent) with a mandatory **diff preview + git-snapshot rollback** · brain = **cloud Claude by default, local model fallback** · all edits constrained to the **workspace allowlist** · **loop protection** (dedupe + cooldown).

**Leo — boot-time rescue terminal 🐩 (build first):** *a bubbly, all-red rescue dog who works when nothing else is up.*
- [x] **Launcher health gate** — `Max.cmd` launches the app (which owns the engine on port 8001), polls `/health` (~40s), and on launch failure opens Leo's terminal
- [x] **Leo rescue console** — red `LEO · SELF-DIAGNOSE MODE` banner, **all output red**, animated sprite + live status, gathers env + stderr signal, **redacts secrets**, diagnoses (cloud Claude → local Ollama → offline heuristics), records to `selfdiagnosefixes.md`, and **loops until the engine is back up**
- [x] **Happy finale** — on green `/health`, Leo prints **"My job is done!"** + a tiny smiling toy-poodle ASCII image, then exits; bubbly encouraging voice throughout
- [x] **Polish**: fixed PowerShell 5.1 encoding bug (em-dash/box-chars with 0x94 byte read as curly-quote by Windows-1252, breaking string parsing); added `-ExecutionPolicy Bypass` to launcher ✅
- [~] *(stretch)* **Stream diagnosis token-by-token** — `Invoke-ClaudeDiagnosisStream` / `Invoke-OllamaDiagnosisStream` in `scripts/leo.ps1` read the SSE/JSONL body via `HttpClient` (ResponseHeadersRead) and print tokens live in red as they arrive; **one-click "apply suggested commands"** — `Get-FixCommands` extracts runnable commands from the diagnosis, `[A] Apply fix` shows + confirms + runs them then re-checks `/health`. **Still open:** cross-platform launcher (`.sh`) once non-Windows lands

**Runtime layer (engine up):**
- [x] **Observability module** (`engine/max_engine/aegis/`): structured logger + ring buffer + SQLite event store (survives restart); FastAPI exception handler; taps on delegate `ERROR` sessions, provider errors, and startup failures; **secret redaction** before store/egress
- [x] **Client error capture**: `POST /aegis/report` ← frontend `window.onerror` / `unhandledrejection`; Tauri/Rust engine-stderr forwarded as a signal
- [x] **Endpoints**: `GET /aegis/events`, `POST /aegis/report`, `POST /aegis/diagnose` (**SSE**, reuses `_sse_stream`), `POST /aegis/apply`, `POST /aegis/rollback`, `GET /aegis/log`, `GET /aegis/sources`
- [x] **Config**: `AegisConfig` (autonomy level, severity threshold, retention) in `config.py`; round-trips through the persisted-override subset
- [x] **Diagnosis**: `aegis` diagnostic prompt template in `prompts.py`; routes via the existing router/delegate (cloud Claude default, local fallback); structured output = root cause · severity · affected files · **unified diff**
- [x] **Apply / verify / rollback**: git-snapshot patcher with **allowlist guard**; verify runner (`pytest` for engine, `tsc && vite build` for frontend); keep on green, **auto-revert** on failure or rejection
- [x] **Logbook**: organized append-only [`selfdiagnosefixes.md`](selfdiagnosefixes.md) (status legend: proposed / applied / verified / rolled-back)
- [x] **Hub integration** (`app/src/aegis/`): `AegisView` (issues list · diagnosis stream · diff viewer · approve/apply/rollback); `"aegis"` Hub tab (🛡 Aegis) + launcher button; `#aegis` hash route; mascot **error** state deep-links here
- [x] **Tests** (`engine/tests/test_aegis_*.py`): capture, event ranking, redaction, store operations — 21 tests passing
- [x] **Surface egress in settings/privacy guard** — amber egress warning + Aegis section in Settings; notes secrets are redacted before egress ✅
- [x] *(stretch)* **Opt-in auto mode** (`autonomy=auto` config): `POST /aegis/auto-fix/{event_id}` streams diagnose→extract diff→apply→verify in one shot; **Apollo fix memory**: every `apply()` embeds the fix record into Apollo vector store (`source="aegis_fix"`) so recurring bugs are recognized; autonomy selector (suggest/ask/auto) in both Settings and AegisView; **Auto-Fix button** shown in AegisView when `autonomy=auto`
- [~] *(stretch)* **Rust/Tauri auto-fix path** — `aegis_auto_fix(event_id)` Tauri command (`lib.rs`) POSTs `/aegis/auto-fix/{id}` over raw TCP and returns the collected SSE body; `AegisView` drives the desktop Auto-Fix through this native path (`autoFixNative` in `aegis.ts`), falling back to the in-webview SSE stream in the browser/LAN client. Streaming token-by-token Leo diagnosis: done (see Leo). **Still open:** cross-platform launcher (`.sh`)

---

### Phase 14 — Voice I/O, Jarvis Personality & User Memory  ✅ *Max becomes a personal AI companion*

*Transforms Max from a data terminal into a persistent personal assistant. Three tightly coupled pillars: configurable personality, persistent user-profile memory, and full voice I/O. All local-first — voice STT/TTS uses the Web Speech API with an optional local Whisper fallback; user memory is stored in `.apollo.db` with no TTL.*

**Decisions locked:** Jarvis persona by default (casual/witty/direct, like Jarvis to Tony Stark) with formal-analyst and custom-text alternatives · user name set once in Settings, used in every AI call · `user_profile` SQLite table in `.apollo.db` (no TTL, persists forever) · explicit "remember that…" shortcut · Web Speech API as primary STT (zero new deps, works in Tauri WebView2) · faster-whisper as local STT alternative (lazy-loaded, `tiny.en` default) · `window.speechSynthesis` TTS reads first 3 sentences aloud · Apollo predictions stored 1/day with 30-day rolling window.

- [x] **Jarvis personality**: `PersonalityConfig` (persona/user_name/custom_prefix) in `config.py`; `persona_prefix()` + `apply_persona()` in `prompts.py`; injected as first system message in ALL AI calls (OSINT chat, Market chat, Polymarket chat, Apollo, Aegis) ✅
- [x] **Persistent user memory**: `user_profile` SQLite table in `.apollo.db`; `UserProfileStore` (`engine/max_engine/user/profile.py`); `GET/POST/DELETE /user/profile`; `to_context_block()` injected into every AI system prompt; Settings "Your AI → What Max knows about you" table ✅
- [x] **Web Speech API mic button**: `useSpeech.ts` hook + type declarations (`speech.d.ts`); `MicButton.tsx` component (pulsing red while recording); placed in OSINT chat input; interrupts TTS before recording ✅
- [x] **TTS voice output**: `useTTS.ts` hook (`window.speechSynthesis`); reads first 3 sentences of each AI response; toggle on/off + rate/pitch sliders in Settings ✅
- [x] **Local Whisper STT**: `faster-whisper>=1.0` added to `pyproject.toml`; `POST /voice/transcribe` endpoint (lazy-loads model on first call, `tiny.en` default); `MicButton` Whisper provider path via `MediaRecorder` ✅
- [x] **Apollo chat**: inline chat thread below Predictions box; prediction text auto-seeded as first assistant message; `POST /apollo/chat` endpoint grounded in `PredictionHistory`; `PredictionHistory` stores 1 prediction/day, 30-day rolling TTL ✅
- [x] **Settings "Your AI" section**: user name, tone selector (Jarvis/Analyst/Custom), custom textarea, TTS toggle + rate/pitch, STT provider selector, Whisper model field ✅
- [x] **Leo fixes**: `-ExecutionPolicy Bypass` added to launcher; em-dash/box-drawing character encoding bug fixed (UTF-8 0x94 byte reads as curly-quote in Windows-1252, breaking string parsing) ✅
- [x] **ChatBar poodle**: placeholder text removed; custom chocolate-brown SVG toy poodle (`PoodleSprite.tsx`) trots left-to-right with a gentle bounce, loops while input is empty/unfocused ✅
- [x] **Privacy egress**: amber egress warning banners added to OSINT, Market, Polymarket, and Aegis settings sections; Tauri `plugin-opener` wired for OSINT article links ✅

---

### Phase 15 — Shadow Net: Tor Dark Web Browser  ✅ *Anonymous browsing with live Tor visualization*

*Adds a Shadow Net Hub tab backed by a bundled Tor daemon, giving anonymous access to both .onion and clearnet sites via onion routing. A persistent TorLock widget above the mascot shows circuit state globally — green when connected, red when dark. Requests and responses animate as vertical streaks between mascot core and lock.*

**Decisions locked:** Tor only (no separate VPN — Tor provides stronger anonymity + dark web access in one) · Tor Expert Bundle (BSD 3-Clause) bundled as Tauri sidecar binary in `resources/tor/` · `stem` Python library for circuit control (new-identity, bootstrap polling) · `socksio` + httpx SOCKS5 client (`proxy=socks5://127.0.0.1:9050`) for all dark web fetches · `beautifulsoup4` for HTML proxy-renderer link rewriting · proxy-renderer browser (engine fetches + rewrites HTML, iframe srcdoc) rather than full WebView proxy · TorLock always visible above mascot when Tor is active, regardless of active Hub tab · lock click opens inline popover (not modal) with exit IP + disconnect + new identity · disconnect from lock widget returns Shadow Net tab to connect screen.

- [x] **Phase A — Tor lifecycle**: Tor Expert Bundle in `resources/tor/windows/`; Rust `TorProcess(Mutex<Option<Child>>)` state + `start_tor()`, `stop_tor()`, `tor_running()` Tauri commands in `lib.rs`; data dir in OS app-data; killed on app exit
- [x] **Phase B — Backend**: `engine/max_engine/darknet/` module (`service.py`, `fetcher.py`, `client.py`, `models.py`); `TorService` with `stem` circuit control + httpx SOCKS5 client; BeautifulSoup4 link rewriter; `GET /dark/status`, `POST /dark/new-circuit`, `GET /dark/fetch` (SSE), `GET /dark/search` endpoints; `DarkNetConfig` in `config.py`; `socksio`, `stem`, `beautifulsoup4` deps; 13 tests
- [x] **Phase C — TorLock widget**: `TorLock.tsx` SVG padlock with `off`/`connecting`/`connected`/`error` states; green glow (connected), red (off), amber pulse + spin arc (connecting); inline popover (exit IP, circuit age, new-identity, disconnect); positioned above mascot in `App.tsx` via `.widget__mascot-wrap`; polls `/dark/status` every 5s
- [x] **Phase D — Shadow Net tab**: `ShadowNetView.tsx`; connect screen with Tor onion SVG logo + bootstrap progress bar; browser pane with address bar, back/forward history stack (`useReducer`), Ahmia + DDG onion quick-search, proxy-rendered HTML in sandboxed iframe; multi-tab browser; added to HubView + HubButtons (`⬡` glyph) + `#shadow` hash route
- [x] **Phase E — Streak animations**: `mascot:tor-request` event → upward green streak from core (750ms); `mascot:tor-response` → downward streak (600ms); `torStreaks` state + `tor-streak--up/down` CSS keyframes in `Mascot.tsx`/`Mascot.css`; BroadcastChannel + Tauri events wired in `App.tsx`
- [x] **Phase F — Polish**: circuit info bar (exit IP, circuit age), "New Identity" in status bar, Ahmia/DDG quick search, home page quick links, `.onion` error states; Tor features bar; iframe base URL fix for image/CSS rendering

---

### Phase 16 — Aegis Security Posture: Full Codebase Vulnerability Scanner  ✅ *Max audits its own code + dependencies and helps Leo fix what it finds*

*Extends Aegis from reactive (catch runtime errors) to proactive (find vulnerabilities before they bite). A new **Security Posture** sub-tab inside the 🛡 Aegis tab runs two scanners: **SAST** (regex/heuristic rules over the codebase, AI-triaged) and **SCA** (parse dependency manifests/lockfiles and query OSV.dev for known CVEs/GHSAs). Adds zero new runtime deps. Full plan: `C:\Users\tadjo\.claude\plans\new-feature-plan-inside-enchanted-hamming.md`.*

**Decisions locked:** SAST = heuristic rules + AI triage (no new deps) · SCA = **OSV.dev** batch API (free, no key, covers PyPI/npm/crates.io; returns CVE/GHSA + CVSS + fixed version) via existing `httpx`, TTL-cached, offline-safe · in-engine async-interval scheduler + manual trigger (no OS cron) · sub-tab toggle inside Aegis (`Runtime Errors` | `Security Posture`) · posture score 0–100 (`100 − 15·crit − 7·high − 3·med − 1·low`) + severity counts + scan-history trend strip · findings dedup by fingerprint, status open/fixed/ignored, auto-`fixed` on reconcile when no longer seen · "Ask Leo to fix" reuses diagnose/apply/rollback; SCA fixes = manifest version-bump diffs · **ecosystem-aware verify** (Python→pytest, npm→npm ci+tsc, rust→cargo check; missing toolchain → "applied, needs manual verify") · configurable **score-threshold gate** → "at risk" banner · one-click **Markdown posture report** export · new `aegis_scans` + `aegis_findings` tables in `.apollo.db`; reuses `rag/chunker` file-walker, `aegis/redact`, and the provider router.

- [x] **SAST scanner** (`aegis/scanner.py`): 10-rule heuristic registry (secrets, eval/exec, shell=True, SQL injection, pickle/yaml, XSS sinks, TLS verify=False, weak hashing, debug=True, permissive CORS) + AI triage; snippets redacted via `aegis/redact.py`; file walk via `rag/chunker.gather_files`.
- [x] **SCA scanner** (`aegis/deps.py` + `aegis/osv.py`): parse `engine/pyproject.toml` / `app/package-lock.json` / `app/src-tauri/Cargo.lock`; OSV.dev `querybatch` → CVE findings with fixed versions + CVSS→severity; injectable httpx; offline-safe.
- [x] **Store + scan service**: `aegis_scans` / `aegis_findings` tables in `store.py`; `scan_service.py` `run_scan` (SAST+SCA independent), dedup/reconcile, posture score; in-engine scheduler + `scan_on_startup` (FastAPI startup hook).
- [x] **Endpoints** (`main.py`): `POST /aegis/scan`, `GET /aegis/scan/status`, `GET /aegis/posture`, `GET /aegis/findings`, `GET /aegis/scans`, `POST /aegis/findings/{id}/fix` (SSE), `POST /aegis/findings/{id}/status`, `GET /aegis/report`.
- [x] **Ask-Leo-to-fix + ecosystem-aware apply**: `fix_finding` SSE (SAST = code diff, SCA = version bump); `_verify_for(changed_paths)` dispatches pytest / tsc / cargo check by changed file type.
- [x] **Security Posture UI** (`app/src/aegis/SecurityPostureView.tsx`): circular score gauge, at-risk banner, history strip, SAST/SCA finding list + detail, fix/approve/ignore/reopen, report export; `Runtime Errors | Security Posture` sub-tab toggle in `AegisView.tsx`; styles in `Aegis.css`.
- [x] **Config + Settings**: `AegisConfig` scan/OSV/threshold fields in `config.py` exposed via `/config`; scan controls in `settings/SettingsView.tsx`; `aegis_security` prompt in `prompts.py`.
- [x] **Tests**: `test_aegis_scanner.py`, `test_aegis_deps_osv.py` (mocked httpx), `test_aegis_scan_store.py` — 69 new tests, 268 total green.

---

### Phase 18 — Analytics: Token Usage & Cost Dashboard  📊 *see exactly how many tokens and dollars every AI feature spends*

*Adds a persistent `token_usage` table in `.apollo.db`, write hooks in both the Anthropic and Ollama providers, and a rich **Analytics** collapsible section inside the Settings tab. Every completed AI call (cloud or local) is recorded with its feature tag, provider, model, token counts, and estimated USD cost. No new runtime dependencies — chart is pure SVG.*

**Decisions locked:** SQLite `token_usage` table in shared `.apollo.db` · feature tag inferred from HTTP path at the engine layer (no client changes) · cost calculated at write-time from `CLOUD_MODELS` catalog prices · local Ollama calls included with $0.00 cost · pure SVG stacked bar chart (no chart deps) · 7d / 30d / 90d time-range selector · 90d view auto-bins into weekly groups.

- [x] **`UsageStore`** (`engine/max_engine/analytics/store.py`): `token_usage` table with indexes on `day` and `feature`; `record()`, `summary()`, `daily()`, `breakdown()`, `reset()` methods; `calc_cost()` helper using `CLOUD_MODELS` catalog.
- [x] **Provider hooks** (`providers/anthropic.py`, `providers/ollama.py`): `_usage_callback` module-level hook + `set_usage_callback()` / `clear_usage_callback()`; Anthropic fires callback on `chat_done` with actual token counts from API events; Ollama captures `eval_count` / `prompt_eval_count` from the final `done:true` streaming line; `_feature` kwarg stripped before payload construction.
- [x] **Wiring** (`main.py`): `UsageStore` instantiated at startup; `_on_usage` callback registered for both providers; `_feature_from_path()` helper maps URL paths to feature strings (apollo/osint/market/polymarket/sentinel/voice/rag/chat/delegate/api); `_sse_stream()` + `_stream_ai()` + `_apollo_run()` + direct `provider.chat()` call sites updated with `feature=` / `_feature=` args.
- [x] **API endpoints** (`main.py`): `GET /analytics/summary?days=`, `GET /analytics/daily?days=`, `GET /analytics/breakdown?days=`, `DELETE /analytics/reset` — all clamped to [1, 90] days.
- [x] **Analytics UI** (`app/src/settings/SettingsView.tsx`): `AnalyticsSection` with time-range segmented control, 4 stat cards (Total Tokens · Total Cost · Top Feature · Requests), pure-SVG `StackedBarChart` with hover tooltips + feature legend, reused egress-log table for breakdown, reset button with confirm dialog; inserted as collapsible `Section` between Egress Audit Log and Providers.
- [x] **Styles** (`app/src/settings/Settings.css`): `--ana-*` color palette (9 feature colors) + `.ana-stat`, `.ana-chart-wrap`, `.ana-tooltip`, `.ana-legend`, `.ana-feature-dot`, `.ana-controls` classes.
