# Max — Local-First AI Engine · Roadmap & Brainstorm

> Status: **living document** — Phases 1–4 are **built & working** (DSL + routing,
> Ollama/Claude streaming, the full delegate system: parallel sessions, Smart-Auto,
> coordinator, live per-session SSE), plus the v1 Tauri widget, OSINT map, market tape,
> and Apollo. **104 engine tests pass; the app typechecks & builds.** Next: VS Code
> extension, codebase RAG, and the MCP capability platform. Checklists below are
> code-verified.

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
- **OSINT news map:** a glowing 2D world map with a **news heat choropleth** (GDELT + RSS, free/key-less) and a **live day/night terminator**, opened in a dedicated large window from below the chat bar; news egress lives in the engine (see [Phase 10](#phase-10--osint-global-news-map---a-glowing-world-map-of-where-the-news-is-happening-with-a-live-daynight-terminator)) ✅
- **Aegis (self-debug & fix):** Max watches its own logs/crashes, **asks before touching anything**, AI-diagnoses the root cause (cloud Claude default, local fallback), shows a **diff preview**, applies only on approval with **git-snapshot rollback** + test-verify, and records every action in an organized [`selfdiagnosefixes.md`](selfdiagnosefixes.md). **Two layers**: **Leo**, a bubbly, all-red boot-time **rescue terminal 🐩** that opens from `Max.cmd` when the engine won't start — looping until it's back up, then signing off with "My job is done!" + a smiling toy-poodle — plus the in-engine runtime layer (full design in [docs/aegis.md](docs/aegis.md); Phase 13) ✅
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

## 3. Phases, milestones & checklist

> Legend: `[x]` done · `[~]` partial (note explains what's left) · `[ ]` not started.

### Phase 0 — Foundations & decisions  🎯 *stack locked, models benchmarked*
- [x] Engine language = Python/FastAPI
- [x] Desktop UI shell decision — **Tauri** (locked)
- [x] Monorepo structure (`/engine`, `/app`, `/docs` exist; `/extension` lands in Phase 5)
- [x] Install + smoke-test Ollama ✅ (0.24; `qwen2.5-coder:3b`+`:14b`, smoke all PASS); Anthropic API access for `!` ✅ (key in `engine/.env`)
- [ ] **Benchmark local models on the 4070 Ti** (tokens/s, VRAM, quality) → shortlist
- [~] Dev tooling: lint/format/test done (**ruff + pytest, 29 passing**); **CI** + SessionStart hook pending
- [x] Lock the DSL grammar (sigils + operators + escaping) — parser implemented + tested

### Phase 1 — Engine MVP (the brain)  🎯 *`curl` can chat with Max via any provider*
- [x] Provider adapter interface
- [x] Ollama (local) adapter (streaming) — **verified end-to-end** against live Ollama (`/command` + `/v1/chat/completions` stream real tokens; sessions run → done)
- [x] Anthropic/Claude (cloud) adapter (streaming) — **verified end-to-end** (`!` + cloud sessions stream real Claude output; API errors surfaced)
- [x] OpenAI-compatible `/v1/chat/completions` with **streaming** (SSE); `provider` selectable
- [x] `/command` endpoint: full DSL → router → provider stream (sigil picks local/cloud)
- [x] Per-provider model overrides (cloud `!` → Claude model, local → coder model)
- [x] Provider router (sigil → adapter+model) + per-task default model config (`router.py`; per-task default *provider* still TODO)
- [~] Config system — defaults + **file-backed persistence for UI settings** (`/config` GET/PUT → `.maxconfig.json`: cloud, delegate mode, parallel limits, workspace allowlist); models/sigils/keys + hot-reload still pending
- [~] **Privacy guard** — cloud routes flagged (`is_cloud`) + `allow_cloud` gate + keys from env; **egress audit log + secure key store pending**
- [~] Health/status endpoint (`/health` ✅); **background daemon mode pending**

### Phase 3 — Desktop widget app  🎯 **v1 — floating widget + configure everything** ([UI design](docs/ui.md))
- [x] **Floating transparent widget** — frameless/transparent/always-on-top/skip-taskbar window, **top-right anchoring**, **global hotkey toggle** (`Ctrl+Shift+M`), and **click-through-when-idle** (Rust cursor-poll). ✅ *Confirmed on-screen (placement, hotkey, hover interactivity).*
- [x] **Live vector mascot** ("X") reacting to engine state (idle / thinking / busy / done / error) — built as a **"Jarvis"-style SVG + CSS HUD** (not Rive; same state API)
- [x] **Task cards** per session (model · provider · state · ☁ marker · cancel/promote) — **live**: polls the engine's `/sessions` (~2s), cancel/promote call the engine; mascot reacts to real session states. Falls back to placeholders when the engine is offline.
- [x] **SYS INFO** meters (CPU · GPU · **VRAM** · RAM) + **⚙ settings** cog — **live** values (Rust `sysinfo` for CPU/RAM, `nvidia-smi` for GPU/VRAM, polled ~1.5s); mascot reacts to real VRAM
- [x] Chat UI — plain chat (`/chat`) + DSL commands (`/command`), **markdown with code blocks + copy button**, cloud (`!`) indicator, SSE streaming, `/health` status dot
- [ ] **Model manager**: list / download / switch / params (temp, ctx, quant)
- [ ] **Routing config**: map sigils → providers/models, set **per-task defaults**, assign **hotkeys**
- [~] **Provider/key management** — cloud on/off ✅ + **key-set status** shown in settings; per-provider key *entry* stays in `engine/.env` by design (no secret-handling in the UI)
- [ ] Engine start/stop/restart + live VRAM/RAM meters
- [x] Settings: **auto-delegate toggle (Manual / Smart-Auto)** + cloud on/off + **parallel limits** — live via `/config`, persisted to `.maxconfig.json`
- [x] **Workspace folder allowlist** — add/remove paths in settings, persisted

### Phase 7 — Performance & privacy polish  🎯 *snappy, stable, provably local-by-default*
- [ ] **Two-model routing**: tiny resident completer + heavy on-demand gen/chat
- [ ] Keep-alive + smart load/unload to respect 12 GB VRAM
- [ ] Quantization / KV-cache / context-length tuning
- [ ] **Network kill-switch** (force fully-offline) + egress audit log
- [ ] Latency targets (completion < Xms, gen first-token < Yms)

### Phase 8 — Advanced / stretch  🎯 *agentic & multi-file*
- [ ] Multi-file / repo-wide edits with plan + approval
- [ ] User-defined custom commands & template library
- [ ] More providers (OpenAI, local llama.cpp/vLLM) + more clients (CLI, Neovim, LAN)
- [ ] Vision models  *(voice + tool-calling/agents → **Phase 9** capability platform)*

### Phase 9 — Capability platform & general assistant (beyond coding)  🎯 *add skills, not rewrite the core* ([architecture](docs/architecture.md))
*Turns Max from a coding assistant into a general personal assistant. Layered so each new ability is a plug-in, not a core change. Builds on the engine/delegate already in place — keeps 100% of current functionality.*
- [ ] **MCP host** in the engine — discover/load/manage MCP servers (stdio + networked) and expose their tools to models
- [ ] **Capability registry** — internal `Capability` interface; **MCP is the default adapter**, with native-Python / HTTP adapters possible (no lock-in)
- [ ] **Intent router** — classify free-form requests into a **skill domain** (code / music / report / Q&A / …) + pick capability + model; tiny resident local model as the classifier; the sigil DSL stays the explicit path
- [ ] **First skills** (prove the platform): **write reports**, **play music**, **web/search**, **files/calendar** — each an MCP server
- [ ] **Voice** — wake word + STT + TTS as a capability over a **dedicated low-latency WebSocket audio pipeline** (kept separate from the control plane)
- [ ] **Auth for home/LAN** — bearer-token on the API once it leaves localhost-only; per-skill placement (local subprocess vs networked)
- [ ] **Outward MCP façade (optional)** — expose Max *itself* as an MCP server so external agents (Claude Desktop, Cursor) can "ask Max" / use its local models

### Phase 10 — OSINT global news map  🎯 *a glowing world map of where the news is happening, with a live day/night terminator*
*A button below the chat bar opens a large dedicated window (the 360×640 widget is too small) with a 2D world map: glowing-blue country wireframe, a news-driven heat choropleth, and a real-time day/night terminator. All news egress lives in the engine (clients stay thin), consistent with the privacy-marked model; the map atlas is bundled locally so only news data touches the network.*

**Decisions locked:** 2D flat (equirectangular) map · dedicated large window (browser-preview falls back to an in-page overlay) · **GDELT + RSS** from day one (free, no key) · engine-side egress · bundled atlas.

- [x] **Engine OSINT module** (`engine/max_engine/osint/`): GDELT DOC 2.0 client + stdlib RSS/Atom fetcher + country gazetteer (name/demonym → ISO-A3) + importance scorer (volume × source-diversity × recency) + TTL-cached aggregator service
- [x] **Endpoints**: `GET /osint/heatmap` (per-country 0..1 intensity), `GET /osint/articles?country=&limit=` (ranked, newest-first), `GET /osint/sources`
- [x] **Config**: `OsintConfig` (GDELT query/timespan/max-records, feed list, cache TTL); no new Python deps (stdlib XML, existing httpx)
- [x] **Tests**: `tests/test_osint.py` — gazetteer, GDELT/RSS parsing, scoring, dedup, caching, endpoints (13 tests, network mocked) — full suite 50 passing, ruff clean
- [x] **Desktop map** (`app/src/osint/`): `WorldMap` (d3-geo equirectangular + `world-atlas` TopoJSON, glow wireframe, heat choropleth, hover/select), `terminator.ts` (subsolar point + night ring, refreshed each minute), `OsintView` (map + ranked countries + article panel), `OsintButton` (below chat bar)
- [x] **Dedicated window**: `#osint` hash route in `main.tsx`; Tauri `WebviewWindow` (1180×760, resizable) + `core:webview:allow-create-webview-window` capability; in-page overlay fallback outside Tauri
- [x] **Severity classification** — Critical / High / Medium / Low from headline *content* (word-boundary keyword tiers, `osint/severity.py`); country badge = **recency-weighted mean** so one outlier story can't flip a whole country; filter bar (top of view) gates map + hotspots + articles by tier
- [x] **Sleeker "threat-intercept" redesign** — dropped the rainbow heat ramp for a discrete dark-ops threat scale (cyan→amber→orange→rose) with per-tier glow; tactical graticule; severity-coded hotspot bars + article edges (shadowbroker-style aesthetic)
- [x] **Naval layer (US fleet positions)** — `osint/naval.py`: parses the latest USNI Fleet Tracker (read via its WordPress *feed*, which dodges Cloudflare) + TWZ Carrier Tracker, anchors on hull tokens (`CVN-73`) with name fallback, geocodes the nearest region phrase via a sea/port/AOR gazetteer (open-water beats homeport), and serves `GET /osint/naval`. Carrier (gold chevron) + amphib (steel diamond) markers with a `⚓ Fleet` toggle; positions flagged **estimated / region-level / dated** (no real-time GPS exists publicly). 6 naval tests. Groundwork for future track prediction.
- [x] **Verified end-to-end**: live GDELT+RSS (e.g. 360 signals / 61 countries), severity tiers (Zaporizhzhia/Iran/Israel → Critical/High), threat shading, moving terminator + subsolar marker, filter toggles, country click → filtered articles; `npm run build` + `tsc` clean
- [ ] **Surface egress in settings/privacy guard** (OSINT makes outbound calls to public news; mark it like the cloud `!` sigil) + optional network kill-switch integration (Phase 7)
- [ ] **Tauri external links** via the opener plugin (article links use `<a target=_blank>`; fine in the browser, route through `opener` inside the desktop shell)
- [ ] **Tuning & breadth**: GDELT theme-query tuning for "most important"; expand the gazetteer beyond the newsworthy core; per-source toggles in the UI; optional GDELT tone signal in the score
- [ ] *(stretch)* time-scrubber to replay the last 24h of heat; cluster/event detail on click

---

### Phase 11 — Market: live stocks + AI Ingest  🎯 *a live US-stock tape with an on-demand AI read*
*A `$` button below the chat bar (next to OSINT) opens a large dedicated window: a live US-stock board on the left and an AI analysis panel on the right. Quote egress lives in the engine. Mirrors the OSINT feature's shape.*

**Decisions locked:** **Finnhub** as the source (free `FINNHUB_API_KEY` in `engine/.env`, treated like the cloud key — never stored) · **user-editable** watchlist (curated megacap default, persisted) · AI analysis runs **only** on the top **"Ingest"** button (cloud Claude when `allow_cloud`, else local) · "live" = frontend polls every ~10s against a 10s engine TTL cache.

- [x] **Engine market module** (`engine/max_engine/market/`): Finnhub `/quote` + `/stock/profile2` client (per-symbol failures swallowed), `MarketService` with concurrent fetch + TTL cache + watchlist mutation, `Quote`/`MarketBoard` models
- [x] **Endpoints**: `GET /market/quotes` (live board), `GET`/`PUT /market/watchlist` (editable + persisted), `GET /market/sources` (provider + `key_set`), `POST /market/analyze` (SSE — the "Ingest" read, reuses `_sse_stream` + the `market` analyst prompt)
- [x] **Config**: `MarketConfig` (watchlist + cache TTL); watchlist round-trips through the persisted-override subset; no new Python deps (existing httpx)
- [x] **Tests**: `tests/test_market.py` — quote parsing, unknown-symbol/HTTP-error skip, board aggregation + caching, no-key empty board, watchlist round-trip/dedup, endpoints (network mocked)
- [x] **Desktop board** (`app/src/market/`): `MarketView` (polling stock rows, green-up/red-down, watchlist add/remove, streaming Ingest panel), `MarketButton` (`$` icon, next to OSINT), `market.ts` client; `#market` hash route + `market` Tauri window capability; in-page overlay fallback
- [ ] **Surface egress in settings/privacy guard** (Market makes outbound calls to Finnhub; mark it like OSINT / the cloud `!` sigil)
- [ ] *(stretch)* WebSocket trade stream for true real-time ticks; per-ticker AI drill-down; sparkline charts; intraday history

---

### Phase 12 — Sentinel: 3D Space Intelligence  🎯 *interactive 3D Earth globe + live solar system with asteroid tracking*
*A new Hub tab (◈ Sentinel) alongside Apollo/OSINT/Market/Settings. Two internal sub-views: Earth View (live satellite tracking on a 3D globe) and Solar System View (heliocentric planets + asteroid orbits). Mirrors the OSINT module pattern — thin React frontend, thick cached Python backend, SSE for AI chat. Adds Three.js as the first 3D library in the project.*

**Decisions locked:** **Three.js** for 3D rendering (both views) · **satellite.js Web Worker** for client-side SGP4 propagation off the main thread (5000+ satellites at 30fps) · **CelesTrak TLEs** (free, no key) as the satellite data source · **NASA NeoWs** (free NASA API key) for asteroid close approaches · **VSOP87 truncated coefficients** hardcoded in `solarUtils.ts` for planet positions (no external call) · same Hub tab/lazy-mount pattern as existing modules · extra data layers beyond the reference sites (NOAA SWPC, NASA CNEOS, RocketLaunch.live, open-notify.org ISS).

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

**Extra data layers beyond the reference sites:**
- NOAA space weather → aurora ring overlay on Earth globe (visible when Kp ≥ 5), space weather badge
- NASA CNEOS fireballs → cone markers on Earth surface
- RocketLaunch.live → launch pad markers + countdown sidebar panel
- ISS crew via open-notify.org → crew panel in Earth View info sidebar

- [ ] **Engine sentinel module** (`engine/max_engine/sentinel/`): `tle.py` (CelesTrak group fetcher + 3-line parser), `asteroids.py` (NeoWs close-approaches + JPL SBDB orbital elements), `space_weather.py` (NOAA SWPC JSON), `fireballs.py` (CNEOS), `launches.py` (RocketLaunch.live), `iss.py` (open-notify.org); `SentinelService` with per-feed TTL cache + async locks
- [ ] **New Python deps**: `sgp4>=2.22` (SGP4 propagation for backend `/sentinel/satellites/now`), `numpy>=1.26` (vectorized batch propagation)
- [ ] **Endpoints**: `GET /sentinel/tle`, `GET /sentinel/satellites/now`, `GET /sentinel/neo`, `GET /sentinel/space-weather`, `GET /sentinel/launches`, `GET /sentinel/fireballs`, `GET /sentinel/iss`, `POST /sentinel/chat` (SSE, same `_sse_stream` helper)
- [ ] **Config**: `SentinelConfig` in `config.py` (TLE groups, TTLs, `neo_days_ahead`, `fireball_days`); `NASA_API_KEY` from env
- [ ] **New npm deps**: `three ^0.167.0`, `@types/three`, `satellite.js ^5.0.0`, `@types/satellite.js`
- [ ] **Frontend** (`app/src/sentinel/`): `SentinelView.tsx` (Earth/Solar sub-tab toggle + AI chat slide-in), `EarthView.tsx` (Three.js globe), `SolarView.tsx` (Three.js heliocentric), `earthUtils.ts`, `solarUtils.ts` (VSOP87 constants + Kepler solver), `satelliteWorker.ts` (Web Worker), `useThreeScene.ts` (shared Three.js lifecycle hook), `sentinel.ts` (API client), `Sentinel.css`
- [ ] **Earth View**: Earth sphere + day/night textures (NASA Visible Earth, bundled), Fresnel atmosphere glow, `DirectionalLight` from `terminator.ts` subsolar point, satellite `Points` geometry (updated by worker ~100ms), selected satellite orbit `Line`, aurora `TorusGeometry` rings at ±65° (Kp-driven), fireball `ConeGeometry` markers, launch pad markers, `OrbitControls`
- [ ] **Solar System View**: Sun + `PointLight` at origin, planet orbit `RingGeometry`, planet spheres at VSOP87 positions (log-scale radii), main-belt asteroid `InstancedMesh` (1500 instances), NEA `Line` tracks, time scrubber `<input type="range" min={-365} max={365}>`, hazardous NEA red glow, `OrbitControls` default top-down
- [ ] **Hub integration**: add `"sentinel"` to `HubTab` union + `TABS[]` in `HubView.tsx`; lazy-mount view; add launcher button to `HubButtons.tsx`; sentinel tab accent in `Hub.css`; `#sentinel` hash route in `main.tsx`; `"sentinel"` in `capabilities/default.json`
- [ ] **AI chat** (`POST /sentinel/chat`): grounded in live snapshot (space weather, ISS crew, NEA close approaches, next launch); mascot `mascot:signal` on submit — mirrors OSINT chat exactly
- [ ] **Tests**: `tests/test_sentinel.py` — TLE parsing, SGP4 propagation, space weather parsing, asteroid model, endpoints (network mocked); add `sgp4`/`numpy` to test env

---

### Phase 13 — Aegis: AI self-debug & fix engine  🎯 *Max watches its own logs, explains what broke, and — with your OK — fixes itself* ([design](docs/aegis.md))
*Max becomes self-healing. An **observability** layer captures crashes/errors/log
signals into a persistent store; an **AI diagnosis** layer (cloud Claude by default,
local fallback) reads the signal + relevant source and proposes a root cause and a
concrete patch; a **human gate** asks before anything is touched; an **apply/verify/
rollback** layer commits the fix only if tests pass and reverts otherwise. Every action
is recorded in an organized [`selfdiagnosefixes.md`](selfdiagnosefixes.md). Mirrors the
OSINT/Market/Sentinel feature shape (engine module → endpoints → config → tests → desktop
view) and reuses the router/delegate, `_sse_stream`, prompt templates, and the
`workspace_allowlist` guard already in place.*

**Decisions locked:** **two layers** — **Leo**, a **boot-time rescue terminal (build
first)** that opens when the engine won't even start (or any launch issue), plus the
**in-engine runtime layer** · **diagnose → ask → apply** (never silent) with a mandatory
**diff preview + git-snapshot rollback** · fix scope = **engine (Python) + frontend
(TS/React) first**, **whole-repo incl Rust/Tauri the stated target** · brain = **cloud
Claude by default, local model fallback** (code/log egress marked like the `!` sigil,
gated by `allow_cloud`) · all edits constrained to the **workspace allowlist** · **loop
protection** (dedupe + cooldown) so a bad fix can't trigger infinite re-diagnosis ·
secrets redacted before any store or egress.

**Leo — boot-time rescue terminal 🐩 (build first):** *a bubbly, all-red rescue dog who works when nothing else is up.*
- [ ] **Launcher health gate** — `Max.cmd` launches the app (which owns the engine on
  port 8001), polls `/health` (~40s), and on launch failure (or any startup issue) opens
  Leo's terminal; preserves the app-owns-engine model
- [ ] **Leo rescue console** — red `LEO · SELF-DIAGNOSE MODE` banner, **all output red**,
  live status (reuses the `smoke.ps1` idiom, recolored), gathers env + stderr signal,
  **redacts secrets**, diagnoses (cloud Claude → local Ollama → offline heuristics),
  records to `selfdiagnosefixes.md`, and **loops with you (retry → relaunch app → `/health`)
  until the engine is back up**; suggest-by-default (no silent edits)
- [ ] **Happy finale** — on green `/health`, Leo prints **"My job is done!"** + a tiny
  smiling toy-poodle ASCII image, then exits; bubbly encouraging voice throughout
- [ ] **Polish**: stream the diagnosis token-by-token; richer offline heuristic rules;
  one-click "apply suggested commands"; cross-platform launcher (`.sh`) once non-Windows lands

**Runtime layer (engine up):**
- [ ] **Observability module** (`engine/max_engine/aegis/`): structured logger + ring
  buffer + SQLite event store (survives restart); FastAPI exception handler; taps on
  delegate `ERROR` sessions, provider errors, and startup failures; **secret redaction**
  before store/egress
- [ ] **Client error capture**: `POST /aegis/report` ← frontend `window.onerror` /
  `unhandledrejection`; Tauri/Rust engine-stderr forwarded as a signal
- [ ] **Endpoints** (mirror OSINT/Market/Sentinel): `GET /aegis/events`, `POST /aegis/report`,
  `POST /aegis/diagnose` (**SSE**, reuses `_sse_stream`), `POST /aegis/apply`,
  `POST /aegis/rollback`, `GET /aegis/log`, `GET /aegis/sources`
- [ ] **Config**: `AegisConfig` (enabled, autonomy level, auto-detect on/off, severity
  threshold to prompt, verify commands per target, retention) — round-trips through the
  persisted-override subset like `MarketConfig`/`SentinelConfig`
- [ ] **Diagnosis**: an `aegis` diagnostic prompt template in `prompts.py`; routes via the
  existing router/delegate (cloud Claude default, local fallback); structured output =
  root cause · severity · affected files · **unified diff**
- [ ] **Apply / verify / rollback**: git-snapshot patcher with **allowlist guard**; verify
  runner (`pytest` for engine, `tsc && vite build` for frontend); keep on green,
  **auto-revert** on failure or rejection
- [ ] **Logbook**: organized append-only [`selfdiagnosefixes.md`](selfdiagnosefixes.md)
  (status legend: proposed / applied / verified / rolled-back)
- [ ] **Hub integration** (`app/src/aegis/`): `AegisView` (issues list · diagnosis stream ·
  diff viewer · approve/apply/rollback · logbook tab); add `"aegis"` to `HubTab` + launcher
  button; `#aegis` hash route; the mascot **error** state deep-links here
- [ ] **Tests** (`engine/tests/test_aegis.py`): capture, event ranking, redaction, prompt
  build (mocked provider), patch parse/validate, allowlist guard, apply+rollback (temp git
  repo), logbook formatting
- [ ] **Surface egress in settings/privacy guard** (Aegis sends code/logs to the cloud when
  diagnosing; mark it like OSINT / Market / the `!` sigil) + network kill-switch integration
- [ ] *(stretch)* opt-in **full-auto mode** (detect→fix→test→restart, logged after the fact)
  behind a flag · Rust/Tauri auto-fix · learn from past fixes (embed `selfdiagnosefixes.md`
  into Apollo memory so recurring bugs are recognized)

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

### Phase 2 — Command DSL & routing ✅
*All four DSL operators wired end-to-end; post-processor ships in both engine and extension.*
- [x] DSL parser (sigils + `.`/`..`/`~`, escaping, nested code) — `dsl/parser.py`, tested
- [x] Wire parser → router → adapter — the `/command` endpoint
- [x] `.` → code generation; `..` → docstring/README; `~` → fix/refactor — system prompts in `prompts.py`
- [x] Output post-processing — `engine/max_engine/postprocess.py` (strip_fences + reindent, 14 tests); `extension/src/extension.ts` applies `postProcess(acc, baseIndent)` on every streaming chunk: opening fence never shows, closing fence stripped on arrival, all continuation lines aligned to the command's column
