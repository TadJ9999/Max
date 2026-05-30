# Max — Local AI Engine · Roadmap & Brainstorm

> Status: **DRAFT / living document** — we are still brainstorming. Nothing here is locked.

A fully local, private AI engine for a single powerful workstation. One always-on
**engine** (daemon) does the thinking; thin **clients** (VS Code extension + desktop app)
talk to it. No cloud, no telemetry, no data leaving the machine.

---

## 0. Target hardware & the one constraint that matters

| Component | Spec | Implication |
|-----------|------|-------------|
| GPU | RTX 4070 Ti — **12 GB VRAM** | ⛳ **The bottleneck.** Decides which models run *fast* (fully on GPU). |
| CPU | i9-14900K (liquid cooled) | Strong CPU offload + great for embeddings/indexing. |
| RAM | 100 GB DDR5 | Lets you run *huge* models (70B+) slowly via CPU/hybrid offload. |

**Design rule:** keep interactive work inside 12 GB VRAM. Use RAM/CPU only for
"I can wait" heavy queries. This is why a **multi-model routing** strategy matters
(small fast model resident for completion, bigger model on-demand for chat/gen).

### Candidate models (starting points — benchmark in Phase 0)
- **Inline completion / FIM (fast, tiny, always resident):** Qwen2.5-Coder-1.5B/3B, StarCoder2-3B
- **Code generation (the `.` command):** Qwen2.5-Coder-14B (Q4, ~9–10 GB), DeepSeek-Coder-V2-Lite (16B MoE)
- **Chat / general (the app):** Qwen2.5-14B, Llama-3.1-8B, Mistral-Nemo-12B
- **Docstrings/README (the `..` command):** can reuse the code or chat model
- **Embeddings (for codebase RAG):** nomic-embed-text, bge-small
- **Stretch (slow, RAM/hybrid):** 32B–70B Q4 for occasional deep reasoning (~2–6 tok/s)

---

## 1. Architecture (proposed)

```
                 ┌─────────────────────────────────────────────┐
                 │              MAX ENGINE  (daemon)            │
                 │  • Local HTTP + WebSocket server             │
                 │  • OpenAI-compatible API  ◄── unlocks tools  │
                 │  • Model Manager  (load / unload / route)    │
                 │  • Command Parser  (the  .  /  ..  DSL)      │
                 │  • Context Engine  (workspace RAG, memory)   │
                 │  • Inference Adapter (Ollama → llama.cpp…)   │
                 │  • Config store + privacy/network kill-switch│
                 └───────────────┬──────────────────┬──────────┘
                                 │                  │
                   ┌─────────────┴───────┐  ┌───────┴──────────────┐
                   │  VS Code Extension  │  │   Desktop UI App     │
                   │  .  and  ..  commands│  │  chat + full config │
                   │  inline / ghost text │  │  model manager      │
                   └─────────────────────┘  └──────────────────────┘
```

**Key decision — one engine, many clients.** All logic (parsing, routing, prompts,
RAG) lives in the engine. VS Code and the app are thin. This avoids duplicating
behavior and means a 3rd client (CLI, Neovim, mobile-on-LAN) is cheap later.

**Key shortcut — expose an OpenAI-compatible endpoint.** If the engine speaks the
OpenAI API, a huge ecosystem (incl. existing VS Code AI extensions) works against
Max for free, and *your* custom DSL becomes the value-add on top.

### Stack options (to decide in Phase 0)
| Layer | Option A (pragmatic) | Option B (single-language) |
|-------|---------------------|----------------------------|
| Engine | **Python + FastAPI** (best ML ecosystem) | Node/TypeScript |
| Inference | **Ollama** to start, adapter to swap → llama.cpp / vLLM / LM Studio | same |
| Desktop UI | **Tauri** (light, Rust+web) or Electron | Electron |
| VS Code ext | TypeScript (required) | TypeScript |
| Vector store | sqlite-vec or LanceDB (embedded) | same |

---

## 2. The invocation DSL (your idea, formalized)

Your two core operators, plus room to grow:

| Syntax | Meaning | Example |
|--------|---------|---------|
| `. <instruction> .` | **Generate code** from a natural-language instruction | `. add a function here to do X and call Y .` |
| `.. <code> ..` | **Summarize / generate docstring or README** for the wrapped code | `.. def _rec_key(...): ... ..` |

**Proposed extensions (optional — your call):**
| Syntax | Meaning |
|--------|---------|
| `? <code/question> ?` | **Explain** this code / answer a question about it |
| `! <code> !` | **Fix / refactor** this code |
| `>` (trailing) | **Continue / complete** from cursor |

Parser notes:
- The parser lives in the **engine**, not the extension, so every client behaves identically.
- Each operator maps to a dedicated **prompt template** (user-editable later).
- Operators should be **configurable** (someone may want `///` instead of `.`).

---

## 3. Phases, milestones & checklist

### Phase 0 — Foundations & decisions  🎯 *Milestone: stack locked, models benchmarked*
- [ ] Decide engine language (Python/FastAPI vs Node) and UI shell (Tauri vs Electron)
- [ ] Set up monorepo structure (`/engine`, `/extension`, `/app`, `/docs`)
- [ ] Install + smoke-test inference backend (Ollama)
- [ ] **Benchmark models on the 4070 Ti**: tokens/s, VRAM use, quality — pick the shortlist
- [ ] Dev tooling: linting, formatting, tests, CI; SessionStart hook for web sessions
- [ ] Lock the DSL grammar (operators + escaping rules)

### Phase 1 — Engine MVP (the brain)  🎯 *Milestone: `curl` can chat with Max locally*
- [ ] Inference adapter interface + Ollama implementation
- [ ] OpenAI-compatible `/v1/chat/completions` endpoint (with **streaming**)
- [ ] Config system (models, params, paths) — file-based, hot-reloadable
- [ ] Structured logging + health/status endpoint
- [ ] Run engine as a background daemon/service

### Phase 2 — Command DSL & code intelligence  🎯 *Milestone: send a raw `.`/`..` string → correct routed behavior*
- [ ] DSL parser (`.`, `..`, escaping, nested code)
- [ ] Prompt template per operator
- [ ] `.` → code generation (returns insertable code, not chatty prose)
- [ ] `..` → docstring / README generation
- [ ] Output post-processing (strip fences, match indentation/style)

### Phase 3 — VS Code extension  🎯 *Milestone: type `. add a function … .` in the editor → code appears*
- [ ] Detect DSL in the active document (on save / on hotkey / on inline trigger)
- [ ] Stream results; show **diff preview** before applying
- [ ] Insert at cursor / replace selection
- [ ] Connect to engine; surface engine status; pick active model
- [ ] (Stretch) ghost-text **FIM autocomplete** as a separate fast channel

### Phase 4 — Desktop UI app  🎯 *Milestone: chat + configure everything from the app*
- [ ] Chat interface (streaming, markdown, code blocks, copy)
- [ ] **Model manager**: list / download / switch / set params (temp, ctx, quant)
- [ ] Settings: DSL operators, prompt templates, routing rules, privacy
- [ ] Engine start/stop/restart + live status & VRAM/RAM usage meters

### Phase 5 — Context & RAG (Max knows your codebase)  🎯 *Milestone: ask about your code → context-aware answer*
- [ ] Workspace indexer (file walk, chunking, ignore rules)
- [ ] Embeddings + local vector store; incremental re-index on change
- [ ] Retrieval injected into prompts for `.`, `?`, and chat
- [ ] Per-project / session **memory**

### Phase 6 — Performance & privacy polish  🎯 *Milestone: snappy completion, stable, provably local*
- [ ] **Model routing**: small resident model for completion, big on-demand for gen/chat
- [ ] Keep-alive + smart load/unload to respect 12 GB VRAM
- [ ] Quantization / KV-cache / context-length tuning
- [ ] **Network kill-switch** + "fully offline" verification (no egress)
- [ ] Latency budget targets (e.g. completion < Xms, gen first-token < Yms)

### Phase 7 — Advanced / stretch  🎯 *Milestone: agentic & multi-file*
- [ ] Multi-file / repo-wide edits with plan + approval
- [ ] User-defined custom commands & template library
- [ ] Additional clients (CLI, Neovim, LAN access from phone)
- [ ] Voice input, image/vision models, tool-calling/agents

---

## 4. My added ideas / recommendations (review these)
1. **OpenAI-compatible API first** — biggest leverage; instant tool compatibility.
2. **Two-model strategy** for the VRAM limit — fast resident completer + heavy on-demand.
3. **FIM autocomplete** as ghost text, *separate* from the explicit `.`/`..` commands.
4. **Diff-preview-before-apply** in VS Code — trust + safety for generated code.
5. **Privacy as a feature** — airplane-mode toggle, zero telemetry, "verify offline" button.
6. **User-editable prompt templates & configurable operators** — power-user appeal.
7. **Build-vs-buy:** Continue.dev + Ollama already covers ~60% of this. Decide where Max
   is genuinely custom (the DSL, the engine, the UX) vs. where we stand on shoulders.

---

## 5. Open questions (need your input)
- Engine language: **Python** (ML ecosystem) or **TypeScript** (one language everywhere)?
- VS Code trigger: on **save**, on **hotkey**, or **live as you type**?
- Build the engine from scratch, or wrap **Ollama + Continue.dev** and focus effort on the DSL/UX?
- Is the desktop app a **must-have for v1**, or can VS Code + a config file ship first?
- How important is **codebase-wide RAG** for v1 vs. just acting on the current file/selection?
