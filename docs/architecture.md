# Max — Architecture

> Companion to [../ROADMAP.md](../ROADMAP.md). Summarizes the design decisions made
> during planning.

## One engine, many clients

All intelligence lives in a single always-on **engine** (Python + FastAPI). Clients
(the Tauri desktop app now; a VS Code extension later) are thin and stateless — they
render UI and call the engine over HTTP/WebSocket. Adding a new client (CLI, Neovim,
LAN) is therefore cheap.

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
| `#` | Qwen | local |  | | |
| `!` | Claude | ☁ cloud |  | | |

## Delegate system

- **Modes:** Manual (you assign model+task) and Smart-Auto (engine picks local vs cloud,
  primarily by **task complexity**). Toggle in settings.
- **Scheduling:** a VRAM-aware scheduler — cloud + tiny-local tasks fan out; heavy local
  models queue (12 GB VRAM ceiling). Users can manually push a queued task to cloud.
- **Sessions:** isolated; each result viewed in its own pane, all streaming concurrently.

## Hardware shaping the design

12 GB VRAM (RTX 4070 Ti) is the interactive-speed ceiling, hence the two-model strategy
(tiny resident completer + heavy on-demand model) and the queue-heavy-local scheduler.
100 GB RAM enables slow large-model offload; the GPU can be upgraded later.
