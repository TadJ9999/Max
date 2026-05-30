# Max — Local-First AI Engine

Max is a **local-first**, private AI engine for a powerful workstation, with an
**explicit, opt-in cloud escape hatch**. One always-on **engine** does the thinking;
thin **clients** (a desktop chat app and, later, a VS Code extension) talk to it.

- 🔒 **Local by default** — runs models on your own GPU via Ollama.
- ☁️ **Cloud on demand** — the `!` sigil routes to a cloud model (e.g. Claude), clearly marked.
- 🧩 **DSL commands** — `. generate code .` and `.. document this ..`, with provider sigils.
- 🪄 **Delegate system** — run many tasks in parallel, Manual or Smart-Auto (AI picks local vs cloud).
- ⚙️ **Everything configurable** — per-task models, sigils, hotkeys, prompt templates.

See **[ROADMAP.md](./ROADMAP.md)** for the full plan and **[docs/architecture.md](./docs/architecture.md)**.

## Monorepo layout

```
Max/
├── engine/     # Python + FastAPI — the brain (provider routing, DSL, delegate)
├── app/        # Tauri desktop chat app (v1 client)
├── docs/       # Architecture & design notes
└── ROADMAP.md  # Phased plan & checklist
```

## Quick start (engine)

```bash
cd engine
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn max_engine.main:app --reload
# health check:  curl http://127.0.0.1:8000/health
```

> Status: early scaffold. The DSL parser, provider router, Ollama/Claude adapters, and the
> delegate engine + `/sessions` API are implemented and tested (mock-tested; live Ollama and an
> Anthropic key are still needed for end-to-end verification). The desktop app is not yet scaffolded.
> See [ROADMAP.md](./ROADMAP.md) for phase-by-phase status.
