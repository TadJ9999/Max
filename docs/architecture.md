# Max — Architecture

> Companion to [../ROADMAP.md](../ROADMAP.md). Summarizes the design decisions made
> during planning.

## One engine, many clients

All intelligence lives in a single always-on **engine** (Python + FastAPI). Clients
(the Tauri desktop app now; a VS Code extension later) are thin and stateless — they
render UI and call the engine over HTTP/WebSocket. Adding a new client (CLI, Neovim,
LAN) is therefore cheap.

## From coding assistant to general assistant

Max starts as a coding assistant but is designed to grow into a **general personal
assistant** (write reports, play music, talk by voice, run errands, and more). The
architecture is layered so that expansion means **adding capabilities, not rewriting the
core**: the engine is the orchestrator, and new skills plug in underneath it.

## Interfaces: two planes

Two interfaces solve two different problems. Keeping them separate is the key decision.

```
  Clients (Tauri widget · VS Code · CLI · phone)
        │  REST + WebSocket/SSE        ── CONTROL PLANE
        ▼
  ┌─────────────────────────────────────────────┐
  │              MAX ENGINE (FastAPI)            │
  │  intent router · scheduler · sessions ·      │
  │  delegate · capability registry              │
  └─────────────────────────────────────────────┘
        │  MCP host (engine = MCP client)  ── CAPABILITY PLANE
        ▼
  MCP servers:  files · music · reports · web · calendar · TTS/STT · …
        ▲
        │  (optional, later) MCP server façade
  External agents (Claude Desktop, Cursor, …) → "ask Max" / use local models
```

- **Control plane — REST + WebSocket/SSE.** How clients *drive* Max: sessions, streaming
  output, live CPU/GPU/VRAM/RAM meters, settings, notifications, multi-client fan-out.
  This stays the backbone — a normal app API is the right shape for a long-running,
  multi-client, streaming UI. (MCP is the wrong shape here and we don't use it for this.)
- **Capability plane — MCP.** How Max *reaches out* to skills. The engine acts as an MCP
  **host/client** that loads MCP servers, each exposing tools/resources. This is where
  "play music / write a report / voice / calendar / web" lives.

## Capabilities via MCP

The engine consumes capabilities through **MCP** as the default adapter:

- **Standard + ecosystem.** MCP is the emerging tool-calling standard; many servers
  already exist (filesystem, web, GitHub, media, …), so we stop hand-building integrations.
- **Add a feature = add a server, zero core changes.** Skills are decoupled from the
  orchestrator; the model gets a uniform tool interface regardless of skill.
- **Don't hard-wire the core to MCP.** The engine talks to an internal **capability
  registry** (`Capability` interface). MCP is the default adapter behind it, but a native
  Python skill or a plain HTTP service can implement the same interface — so we're never
  locked into one mechanism.
- **Optional outward façade (later).** Expose Max *itself* as an MCP server so external
  agents (Claude Desktop, Cursor) can call into Max or use its local models. Low effort,
  high optionality — build only when wanted.

## Local-first, cloud opt-in

Models run locally via Ollama by default. The `!` sigil routes a single command to a
cloud provider (Claude), which is **opt-in, key-gated, and visibly marked**. Cloud can
be globally disabled. The workspace **folder allowlist** (set in the UI) defines what
Max may read/operate on.

## The DSL: provider sigils × operators

`[sigil][operator] body [operator]` — see [`engine/max_engine/dsl/parser.py`](../engine/max_engine/dsl/parser.py).

| Sigil | Provider | Locality |  | Operator | Action |
|-------|----------|----------|--|----------|--------|
| (none) | per-task default | local |  | `. … .` | generate code |
| `@` | Ollama | local |  | `.. … ..` | summarize / document |
| `#` | Qwen | local |  | `~ … ~` | fix / refactor |
| `!` | Claude | ☁ cloud |  | | |

(`!` is reserved as the cloud sigil, so fix/refactor uses `~`.)

The DSL is coding-centric today. As Max generalizes, the front of the pipeline becomes
an **intent router** (see below); the sigil DSL stays as the explicit/manual path, while
free-form requests get classified and routed automatically.

## Routing & delegate system

- **Intent routing (general).** The first stage classifies a request into a **skill
  domain** (code / music / report / question / …) and selects the capability + model. A
  tiny resident local model is well suited as the classifier (fits the hardware story).
- **Delegate modes:** Manual (you assign model+task) and Smart-Auto (engine picks). The
  delegate generalizes from "local vs cloud" to "**which skill domain + which model +
  local vs cloud**", primarily by task complexity.
- **Scheduling:** a VRAM-aware scheduler — cloud + tiny-local tasks fan out; heavy local
  models queue (12 GB VRAM ceiling). Users can manually push a queued task to cloud.
- **Sessions:** isolated; each result viewed in its own pane, all streaming concurrently.

## Voice & realtime

Voice = wake word + STT + TTS. The **orchestration** ("play music", "summarize this")
routes through the engine/capabilities like any other request, but the **audio
transport** wants a dedicated low-latency **streaming channel** (WebSocket) — *not* MCP
request/response. Voice is therefore a capability layered on top of a separate realtime
audio pipeline, kept distinct from the control plane.

## Running at home

The one-engine/many-clients model already supports a single always-on engine on the home
box with clients over the LAN. Two additions once it leaves localhost-only:

- **Auth:** a bearer token on the API (it is now networked).
- **Skill placement:** MCP capability servers run as local subprocesses (simplest) or as
  networked services, chosen per skill.

## Hardware shaping the design

12 GB VRAM (RTX 4070 Ti) is the interactive-speed ceiling, hence the two-model strategy
(tiny resident completer + heavy on-demand model) and the queue-heavy-local scheduler.
100 GB RAM enables slow large-model offload; the GPU can be upgraded later.
