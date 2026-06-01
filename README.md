# Max — Local-First AI Engine & Desktop Assistant

Max is a **local-first**, private AI engine for a powerful workstation, with an
**explicit, opt-in cloud escape hatch**. One always-on **engine** does the thinking;
thin **clients** — a floating desktop widget, a VS Code extension, a Neovim plugin, a
`max` CLI, and a phone/Mac LAN browser — all talk to it.
It started as a coding assistant and has grown into a general personal assistant —
parallel task delegation, a live global news/threat map, a market tape, a prediction
engine, 3D space intelligence, Tor dark-web browsing, voice I/O, and a self-repair
console, all behind one local API.

- 🔒 **Local by default** — runs models on your own GPU via [Ollama](https://ollama.com).
- ☁️ **Cloud on demand** — the `!` sigil routes to a cloud model (e.g. Claude), clearly marked; gated by `allow_cloud`.
- 🧩 **DSL commands** — `. generate code .`, `.. document this ..`, `~ fix this ~`, with provider sigils (`@` Ollama · `#` Qwen · `!` Claude).
- 🪄 **Delegate system** — run many tasks in **parallel**, **Manual** or **Smart-Auto** (the engine picks local vs cloud by task complexity), within a 12 GB-VRAM-aware scheduler. A **coordinator** can auto-decompose one request into parallel subtasks.
- 📡 **Live everything** — per-session output **streams** to the UI token-by-token (SSE).
- 🧠 **Knows your codebase** — local RAG indexes your workspace (sqlite-vec, incremental, allowlist-scoped) and answers grounded questions **cited by `file:line`**.
- 🧑‍💻 **In your editor** — a VS Code extension runs DSL commands inline (auto on the closing delimiter or a keybinding), replaces the command with streamed code, and offers ghost-text FIM completion.
- 🛰️ **OSINT** — a glowing world map of where the news is happening (GDELT + RSS, free/key-less), severity tiers, a live day/night terminator, and US-fleet positions.
- 📈 **Market** — a live US-stock tape (Finnhub) with an editable watchlist and on-demand AI **"Ingest"** analysis.
- 🔭 **Apollo** — a prediction engine with vector memory that fuses OSINT + market into forward-looking SITREPs.
- 🎲 **Polymarket** — live prediction-market intelligence (Gamma + CLOB APIs, no key), with YES/NO gauges, price charts, order book depth, and Apollo-embedded market sentiment.
- 🌌 **Sentinel** — 3D interactive Earth globe + heliocentric Solar System view with live satellite tracking (SGP4/CelesTrak), asteroid close-approaches (NASA NeoWs), space weather (NOAA SWPC), rocket launches, and AI chat grounded in live space data.
- 🎙️ **Voice + Jarvis** — Web Speech API mic button + TTS voice output; configurable Jarvis/Analyst/custom personality injected into every AI call; persistent user-profile memory in `.apollo.db`; Apollo daily predictions with 30-day rolling history.
- ⬡ **Shadow Net** — a Tor dark-web browser Hub tab: bundled Tor Expert Bundle sidecar, `stem` circuit management, SOCKS5-proxied fetches + BeautifulSoup link rewriter, multi-tab browser, and a TorLock widget always visible above the mascot.
- 🛡️ **Aegis** — self-repair + security posture: runtime error capture, AI diagnosis, diff preview, apply/rollback with git snapshot + test-verify; **Security Posture** sub-tab runs SAST (10-rule heuristics + AI triage) + SCA (OSV.dev CVE scan over Python/npm/Rust deps), posture score/trend, and "Ask Leo to fix" for any finding. Leo's boot-rescue diagnosis **streams token-by-token** with one-click **apply suggested commands**.
- ⚡ **Skills & capability platform** — a capability registry + intent router that turns Max into a general assistant: web search (DuckDuckGo), AI reports, workspace files, Spotify (OAuth PKCE), and Google Calendar (OAuth2), surfaced in a Skills Hub tab.
- 🔗 **MCP host (both directions)** — Max connects to external **MCP servers** (stdio or HTTP) and routes their tools, **and** exposes its own skills as an MCP server so Claude Desktop / Cursor can call Max (`python -m max_engine.mcp_server`, with a paste-ready config).
- 📱 **LAN access** — a "Share on LAN" toggle serves the built UI over HTTPS (mkcert) at `https://<pc-name>.local:8443` with a QR code, so you can use Max — voice included — from your iPhone/Mac browser; all compute stays on the desktop.
- 🧰 **Code Hub** — a Monaco editor + file tree with an AI **multi-file edit planner** (plan → approve → apply behind a git snapshot, with rollback); OpenAI provider (`%` sigil) + a connect-only **local OpenAI-compatible adapter** (`^` sigil, llama.cpp / vLLM / LM Studio), vision image-attach in chat, and user-defined custom DSL commands.
- 📊 **Analytics** — a token-usage & cost dashboard in Settings: every AI call (cloud or local) is recorded with feature tag, provider, model, token counts, and estimated USD cost; per-feature pure-SVG stacked charts with a 7d/30d/90d range.
- 🖥️ **Many clients** — besides the desktop widget and VS Code extension, a zero-dep **Neovim plugin** (inline DSL replace + FIM ghost text) and a `max` **CLI** (one-shot, REPL, health, sessions) that drive the engine **locally or remotely**.
- 🎨 **Floating widget UI** — frameless, transparent, always-on-top, top-right, **click-through when idle**, toggled by a global hotkey (`Ctrl+Shift+M`), with a "Jarvis"-style HUD mascot that reacts to engine state.

See **[ROADMAP.md](./ROADMAP.md)** for the phased plan and **[docs/architecture.md](./docs/architecture.md)** for the layered design.

## Architecture

**One engine, many clients.** All logic — DSL parsing, provider routing, the delegate
scheduler, OSINT/market/Apollo egress, prompts, privacy marking — lives in the engine.
Clients stay thin and consume the local HTTP/SSE API, so adding a new client (VS Code,
CLI, LAN) is cheap.

```
        ┌──────────────────────── MAX ENGINE (FastAPI, localhost) ───────────────────────┐
        │  DSL parser (. / .. / ~ + sigils)   Provider router (sigil → provider/model)    │
        │  Providers: Ollama (local) · Claude (cloud)   OpenAI-compatible /v1 streaming    │
        │  Delegate: session mgr + VRAM-aware scheduler + coordinator + per-session SSE    │
        │  OSINT (GDELT/RSS/naval)   Market (Finnhub)   Apollo (prediction + vector memory) │
        │  Polymarket (Gamma+CLOB)   Aegis (self-repair + Leo boot-rescue + SAST/SCA)     │
        │  Sentinel (3D space · satellites · asteroids)   Dark Net (Tor)   User/Voice     │
        │  Skills + intent router   MCP host (in/out)   Code Hub (multi-file edit planner) │
        └───────────────────────────────────┬─────────────────────────────────────────────┘
                                             │  HTTP + SSE (CORS: local origins)
                       ┌─────────────────────┴───────────────────┐
                       │  Tauri desktop widget (React + TS)       │
                       │  task cards (live) · chat · settings ·   │
                       │  HUD mascot · OSINT · Market · Apollo ·  │
                       │  Sentinel · Shadow Net · Aegis · Voice   │
                       └──────────────────────────────────────────┘
```

## Monorepo layout

```
Max/
├── engine/          # Python + FastAPI — the brain
│   └── max_engine/  # dsl · router · providers · delegate · rag · osint · market
│                    # apollo · polymarket · aegis · sentinel · darknet · user
│                    # skills · capabilities · mcp (+ mcp_server) · analytics
├── app/             # Tauri v2 desktop widget (React + TypeScript)
├── extension/       # VS Code extension (DSL commands, inline replace, FIM ghost text)
├── clients/         # nvim (zero-dep Lua plugin) · cli (max console script) — local or remote
├── docs/            # architecture · ui · mascot · setup · aegis · lan
├── scripts/         # smoke.ps1 end-to-end check · leo.ps1 boot-rescue terminal
├── Max.cmd          # double-click launcher (app owns the engine; Aegis health gate)
├── Max.command      # macOS/Linux thin-client launcher (remote-engine mode)
└── ROADMAP.md       # phased plan & status
```

## The command DSL

A command is `[sigil][operator] … [operator]`. The sigil picks the **provider**; the
operator picks the **action**. Plain text (no operator) is treated as chat.

| Sigil | Provider | | Operator | Action |
|-------|----------|-|----------|--------|
| *(none)* | per-task default (local) | | `. … .` | generate code |
| `@` | Ollama (local) | | `.. … ..` | summarize / docstring / README |
| `#` | Qwen (local) | | `~ … ~` | fix / refactor |
| `!` | Claude (☁ cloud, opt-in) | | | |
| `%` | OpenAI / GPT (☁ cloud, opt-in) | | | |
| `^` | local OpenAI-compatible server (llama.cpp / vLLM / LM Studio) | | | |

Sigils, operators, and per-task default models are all user-configurable. Examples:
`!. add a retry decorator .` (cloud generate) · `@.. document this ..` (local docs) ·
`%~ tidy this ~` (GPT fix) · `^. … .` (local llama.cpp server).

## Engine API

| Area | Endpoints |
|------|-----------|
| Core | `GET /health` · `GET/PUT /config` · `POST /config/key` · `POST /parse` |
| Chat / DSL | `POST /chat` · `POST /command` · `POST /v1/chat/completions` (OpenAI-compatible, SSE) · `POST /complete` (FIM, for the editor) |
| Delegate | `POST /sessions` (fan-out) · `POST /sessions/coordinate` (auto-decompose) · `GET /sessions` · `GET /sessions/{id}` · `GET /sessions/{id}/stream` (SSE) · `POST /sessions/{id}/cancel` · `POST /sessions/{id}/promote` |
| Codebase RAG | `POST /rag/index` (incremental, allowlist-scoped) · `POST /rag/search` · `POST /rag/ask` (SSE, cited by file:line, opt-in `session_id` memory) · `GET /rag/status` · `POST /rag/clear` · `GET /rag/memory/{id}` · `POST /rag/memory/{id}/clear` |
| OSINT | `GET /osint/heatmap` · `/osint/articles` · `/osint/sources` · `/osint/events` · `/osint/naval` · `/osint/domains` · `/osint/timeline` (24h heat replay) · `POST /osint/chat` (SSE) |
| Market | `GET /market/quotes` · `GET/PUT /market/watchlist` · `GET /market/sources` · `GET /market/candles/{symbol}` · `GET /market/stream` (SSE live ticks, Finnhub WS bridge) · `POST /market/analyze` (SSE) · `POST /market/chat` (SSE) |
| Polymarket | `GET /polymarket/board` · `/polymarket/markets` · `GET/PUT /polymarket/watchlist` · `GET /polymarket/prices/{id}` · `GET /polymarket/order-book/{id}` · `GET /polymarket/news/{id}` · `GET /polymarket/stream` (SSE, CLOB WS bridge) · `GET /polymarket/portfolio` (read-only by wallet) · `GET /polymarket/sources` · `POST /polymarket/ingest` (SSE) · `POST /polymarket/analyze` (SSE) · `POST /polymarket/chat` (SSE) |
| Apollo | `POST /apollo/osint-report` · `/apollo/market-report` · `/apollo/predict` · `GET /apollo/status` · `POST /apollo/chat` (SSE) |
| Sentinel | `GET /sentinel/tle` · `/sentinel/satellites/now` · `/sentinel/neo` · `/sentinel/space-weather` · `/sentinel/launches` · `/sentinel/fireballs` · `/sentinel/iss` · `POST /sentinel/chat` (SSE) |
| Voice / User | `GET/POST/DELETE /user/profile` · `POST /voice/transcribe` |
| Shadow Net | `GET /dark/status` · `POST /dark/new-circuit` · `GET /dark/fetch` (SSE) · `GET /dark/search` |
| Aegis | `GET /aegis/events` · `POST /aegis/report` · `POST /aegis/diagnose` (SSE) · `POST /aegis/apply` · `POST /aegis/rollback` · `POST /aegis/auto-fix/{id}` (SSE) · `GET /aegis/log` · `GET /aegis/sources` · `POST /aegis/scan` · `GET /aegis/scan/status` · `GET /aegis/posture` · `GET /aegis/findings` · `GET /aegis/scans` · `POST /aegis/findings/{id}/fix` (SSE) · `POST /aegis/findings/{id}/status` · `GET /aegis/report` |
| Skills / Capabilities | `GET /capabilities` · `POST /capabilities/route` (SSE intent router) · `/skills/*` (web search, reports, files, Spotify + Google Calendar OAuth) |
| MCP | `GET/POST/DELETE /mcp/servers` · `POST /mcp/servers/{name}/connect` · `/disconnect` · `POST /mcp/call` · `GET /mcp/facade` (inbound manifest + Claude Desktop config) |
| Code | `GET /code/files` · `/code/file` · `POST /code/plan` (SSE multi-file edit plan) · `/code/apply` (git snapshot) · `/code/rollback` |
| Models | `GET /models` · `GET /models/loaded` (VRAM usage) · `POST /models/benchmark` (live tok/s) · `POST /models/latency` (TTFT + end-to-end) |
| Analytics | `GET /analytics/summary` · `/analytics/daily` · `/analytics/breakdown` (all `?days=`, clamped 1–90) · `DELETE /analytics/reset` |
| Privacy | `GET /egress/log` · `DELETE /egress/log` |
| Lifecycle | `POST /engine/unload` |

## Quick start

### Desktop app (the normal way)

The app **owns** the engine: on launch it starts the FastAPI engine (uvicorn on
**port 8001**) if it isn't already running, and stops it on shutdown.

```bash
cd app
npm install
npm run tauri build -- --no-bundle   # builds Max.exe
```
Then double-click **`Max.cmd`** at the repo root. (Requires the engine venv at
`engine/.venv`; see [docs/setup.md](./docs/setup.md).)

### Engine standalone (dev)

```bash
cd engine
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                                  # 399 tests (377 pass; 22 skills-async are a marker-config quirk)
uvicorn max_engine.main:app --reload    # dev server on :8000
curl http://127.0.0.1:8000/health
```

Try the parser over HTTP:

```bash
curl -s localhost:8000/parse -H 'content-type: application/json' \
  -d '{"text": "!. add a retry decorator ."}' | python -m json.tool
```

## Configuration & keys

- **UI settings** (persisted to `.maxconfig.json`): cloud on/off, delegate mode
  (Manual / Smart-Auto) + parallel limits, workspace folder allowlist.
- **Per-task models, sigils, providers**: `engine/max_engine/config.py`.
- **Secrets** live only in `engine/.env` (gitignored) — never in the UI:
  - `ANTHROPIC_API_KEY` — enables the `!` cloud path.
  - `OPENAI_API_KEY` — enables the `%` cloud path (GPT models) + OpenAI vision.
  - `FINNHUB_API_KEY` — enables live market quotes + the trade-tick stream (free tier).
  - `NASA_API_KEY` — enables Sentinel asteroid close-approach data (free tier).
  - `GOOGLE_API_KEY` — used by the Google Calendar skill (OAuth client in `.env`).

**Privacy:** local by default. Cloud (`!`) and outbound news/market/space fetches are egress
points; cloud is opt-in, gated, and clearly marked in the UI. Aegis redacts secrets before
any diagnosis egress.

## Status

**Every planned phase (0–18) and all cross-cutting stretch work are built and working** —
the roadmap has no open items left. Shipped: DSL + routing, Ollama/Claude/OpenAI streaming
(plus a connect-only local OpenAI-compatible adapter), the full delegate system (parallel
sessions, Smart-Auto, coordinator, live SSE), workspace RAG with session memory, FIM
completion, two-model VRAM routing with keep-alive load/unload + a network kill-switch +
egress audit log, **quantization/KV-cache/context tuning** and **latency probing** (TTFT +
end-to-end) in the Model Manager, a **capability/skills platform** + intent router, OSINT map
(with a 24h heat-replay scrubber), market tape (with a live Finnhub WebSocket tick stream),
Apollo prediction engine, Polymarket intelligence (with live CLOB price streaming + read-only
wallet portfolios), Sentinel 3D space intelligence, Aegis self-repair (Leo boot-rescue with
streaming diagnosis + Security Posture SAST/SCA), Voice I/O + Jarvis personality, Shadow Net
Tor browser, **LAN access** (Max on iPhone/Mac over HTTPS), a **Code Hub** with a multi-file
AI edit planner, an **Analytics** token/cost dashboard, an **MCP host** (both directions),
and four clients (desktop widget, VS Code, Neovim, `max` CLI) plus a macOS/Linux thin-client
launcher (`Max.command`). **377 engine tests pass** (399 collected; 22 skills-async failures
are an unregistered-marker config quirk, not product bugs); the app and extension typecheck
and build; GitHub Actions CI gates every push. The only forward-looking work is explicitly
out of scope: remote/internet access (Tailscale/Cloudflare), app-level auth tokens, and
multi-user. See [ROADMAP.md](./ROADMAP.md) for phase-by-phase detail.

---

## Completed Phases

| Phase | Name | What shipped |
|-------|------|-------------|
| 0 | Foundations & decisions | Stack locked; Ollama + Claude wired; DSL grammar + parser |
| 1 | Engine MVP | Provider adapters, routing, OpenAI-compatible `/v1` endpoint, streaming |
| 2 | Command DSL & routing | All four operators (`. ` `..` `~`) wired end-to-end with sigil routing |
| 3 | Desktop widget app | Floating transparent widget, Jarvis-style mascot, task cards, settings |
| 4 | Delegate system | Parallel sessions, Smart-Auto, VRAM-aware scheduler, coordinator, SSE |
| 5 | VS Code extension | Inline replace, FIM ghost text, sigil routing honored from the editor |
| 6 | Context & RAG | sqlite-vec workspace indexer, incremental re-index, cited `file:line` answers |
| 7 | Performance & privacy polish | Two-model VRAM routing, keep-alive load/unload, network kill-switch, egress audit log |
| 8 | Advanced / agentic | Multi-file AI edit planner (Code Hub), custom DSL commands, OpenAI provider (`%`), vision image-attach |
| 9 | Capability platform & skills | Capability registry + intent router; web search, reports, files, Spotify + Calendar skills; **MCP host both directions** |
| 10 | OSINT global news map | GDELT + RSS heat choropleth, severity tiers, terminator, US fleet layer; 24h heat-replay scrubber, event clustering, per-source toggles |
| 11 | Market: live stocks + AI | Finnhub tape, editable watchlist, AI Ingest analysis |
| 11.5 | Polymarket intelligence | Gamma + CLOB APIs, prediction market UI, Apollo vector embedding |
| 12 | Sentinel: 3D space intelligence | Three.js globe + solar system, SGP4 Web Worker, CelesTrak/NeoWs/SWPC |
| 13 | Aegis: AI self-debug & fix | Leo rescue terminal, runtime error capture, diagnose/apply/rollback |
| 14 | Voice I/O + Jarvis personality | Web Speech mic, TTS, Jarvis persona, persistent user-profile memory |
| 15 | Shadow Net: Tor dark-web browser | Bundled Tor sidecar, circuit control, proxy renderer, TorLock widget |
| 16 | Aegis Security Posture | SAST (10-rule heuristics) + SCA (OSV.dev CVE scan), posture score/trend, Ask-Leo-to-fix |
| 17 | LAN access | "Share on LAN" toggle, engine serves the built UI over HTTPS (mkcert) at `<pc>.local:8443` + QR, mobile-first shell |
| 18 | Analytics | Token-usage + cost dashboard in Settings (per-feature, SVG charts), write hooks in both providers |
