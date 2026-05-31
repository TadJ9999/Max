# Max — Local-First AI Engine & Desktop Assistant

Max is a **local-first**, private AI engine for a powerful workstation, with an
**explicit, opt-in cloud escape hatch**. One always-on **engine** does the thinking;
thin **clients** (a floating desktop widget today, a VS Code extension later) talk to it.
It started as a coding assistant and is growing into a general personal assistant —
parallel task delegation, a live global news/threat map, a market tape, and a
prediction engine, all behind one local API.

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
        │  OSINT (GDELT/RSS/naval)   Market (Finnhub)   Apollo (prediction + vector memory)│
        └───────────────────────────────────┬─────────────────────────────────────────────┘
                                             │  HTTP + SSE (CORS: local origins)
                       ┌─────────────────────┴───────────────────┐
                       │  Tauri desktop widget (React + TS)       │
                       │  task cards (live) · chat · settings ·   │
                       │  HUD mascot · OSINT map · market · Apollo│
                       └──────────────────────────────────────────┘
```

## Monorepo layout

```
Max/
├── engine/          # Python + FastAPI — the brain
│   └── max_engine/  # dsl · router · providers · delegate · osint · market · apollo
├── app/             # Tauri v2 desktop widget (React + TypeScript)
├── extension/       # VS Code extension (DSL commands, inline replace, FIM ghost text)
├── docs/            # architecture · ui · mascot · setup
├── scripts/         # smoke.ps1 end-to-end check
├── Max.cmd          # double-click launcher (app owns the engine)
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

Examples: `!. add a retry decorator .` (cloud generate) · `@.. document this ..` (local docs).

## Engine API

| Area | Endpoints |
|------|-----------|
| Core | `GET /health` · `GET/PUT /config` · `POST /parse` |
| Chat / DSL | `POST /chat` · `POST /command` · `POST /v1/chat/completions` (OpenAI-compatible, SSE) · `POST /complete` (FIM, for the editor) |
| Delegate | `POST /sessions` (fan-out) · `POST /sessions/coordinate` (auto-decompose) · `GET /sessions` · `GET /sessions/{id}` · `GET /sessions/{id}/stream` (SSE) · `POST /sessions/{id}/cancel` · `POST /sessions/{id}/promote` |
| Codebase RAG | `POST /rag/index` (incremental, allowlist-scoped) · `POST /rag/search` · `POST /rag/ask` (SSE, cited by file:line, opt-in `session_id` memory) · `GET /rag/status` · `POST /rag/clear` · `GET /rag/memory/{id}` · `POST /rag/memory/{id}/clear` |
| OSINT | `GET /osint/heatmap` · `/osint/articles` · `/osint/sources` · `/osint/events` · `/osint/naval` |
| Market | `GET /market/quotes` · `GET/PUT /market/watchlist` · `GET /market/sources` · `POST /market/analyze` (SSE) · `POST /market/chat` (SSE) |
| Apollo | `POST /apollo/osint-report` · `/apollo/market-report` · `/apollo/predict` · `GET /apollo/status` |
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
pytest                                  # full suite (104 tests)
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
  - `FINNHUB_API_KEY` — enables live market quotes (free tier).

**Privacy:** local by default. Cloud (`!`) and outbound news/market fetches are egress
points; cloud is opt-in, gated, and clearly marked in the UI.

## Status

The engine core, the v1 desktop widget, **codebase RAG**, and the **VS Code extension**
are built and working: DSL + routing, Ollama/Claude streaming, the full delegate system
(parallel sessions, Smart-Auto, coordinator, live SSE), workspace RAG with session memory,
FIM completion, OSINT map, market tape, and Apollo. **126 engine tests pass**; the app and
extension typecheck and build. See [ROADMAP.md](./ROADMAP.md) for phase-by-phase detail
(next up: the MCP capability platform, and performance/privacy polish).
