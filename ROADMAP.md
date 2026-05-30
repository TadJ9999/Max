# Max — Local-First AI Engine · Roadmap & Brainstorm

> Status: **DRAFT / living document** — still brainstorming. Nothing is locked.

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
- VS Code integration is a **later phase** (after the chat app) ✅
- Hardware can be upgraded later if the project proves out ✅

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
| Desktop UI | Tauri (light) or Electron — decide in Phase 0 |
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

### Combined examples
| You type | Resolves to |
|----------|-------------|
| `. … .` | generate code · default code model (local) |
| `!. … .` | generate code · **Claude (cloud)** |
| `@.. code ..` | docstring · Ollama (local) |
| `#. … .` | generate code · Qwen (local) |

**Proposed extra operators (optional):** `? code ?` explain · `! code !` fix/refactor
(note: would need disambiguation from the `!` cloud sigil — TBD).

Parser rules:
- Parser + router live in the **engine** so every client behaves identically.
- Sigils, operators, and per-task default models are all **user-configurable**.
- Each operator maps to a dedicated, **user-editable prompt template**.
- Any cloud sigil triggers the **privacy guard** (visible marker / optional confirm).

---

## 3. Phases, milestones & checklist

### Phase 0 — Foundations & decisions  🎯 *stack locked, models benchmarked*
- [x] Engine language = Python/FastAPI
- [ ] Desktop UI shell decision (Tauri vs Electron)
- [ ] Monorepo structure (`/engine`, `/app`, `/extension`, `/docs`)
- [ ] Install + smoke-test Ollama; set up Anthropic API access for `!`
- [ ] **Benchmark local models on the 4070 Ti** (tokens/s, VRAM, quality) → shortlist
- [ ] Dev tooling: lint/format/test/CI; SessionStart hook for web sessions
- [ ] Lock the DSL grammar (sigils + operators + escaping)

### Phase 1 — Engine MVP (the brain)  🎯 *`curl` can chat with Max via any provider*
- [ ] Provider adapter interface
- [ ] Ollama (local) adapter + Anthropic/Claude (cloud) adapter
- [ ] OpenAI-compatible `/v1/chat/completions` with **streaming**
- [ ] Provider router (sigil → adapter+model) + per-task default model config
- [ ] Config system (models, sigils, params, API keys) — file-based, hot-reload
- [ ] **Privacy guard**: detect + mark cloud egress; secure API-key storage
- [ ] Health/status endpoint; run as background daemon

### Phase 2 — Command DSL & routing  🎯 *send `!.`/`@..`/`#.` strings → correct provider + behavior*
- [ ] DSL parser (sigils + `.`/`..`, escaping, nested code)
- [ ] Wire parser → router → adapter
- [ ] `.` → code generation (insertable code, not chatty prose)
- [ ] `..` → docstring / README generation
- [ ] Output post-processing (strip fences, match indentation/style)

### Phase 3 — Desktop chat app  🎯 **v1 — chat + configure everything from the app**
- [ ] Chat UI (streaming, markdown, code blocks, copy) with a **cloud indicator** when `!` used
- [ ] **Model manager**: list / download / switch / params (temp, ctx, quant)
- [ ] **Routing config**: map sigils → providers/models, set **per-task defaults**, assign **hotkeys**
- [ ] **Provider/key management** (add Claude key, toggle cloud on/off)
- [ ] Engine start/stop/restart + live VRAM/RAM meters
- [ ] Settings: **auto-delegate toggle (Manual / Smart-Auto)**, cloud on/off, privacy rules

### Phase 4 — Delegate system: parallel sessions & multi-model orchestration  🎯 *run many tasks at once, each on its own model*
- [ ] Session manager: spawn / track / cancel concurrent sessions, each bound to a provider+model
- [ ] **Mode toggle (settings): Manual** (you assign model+task) **and Smart-Auto** (AI decides local vs cloud)
- [ ] Smart-Auto router: choose local vs cloud per task from capability / queue depth / (later) privacy rules
- [ ] Task scheduler aware of the **12 GB VRAM limit** (cloud + small-local run in parallel; heavy local models queue)
- [ ] **Queue dashboard** with manual override: push a queued task to cloud when local is backed up
- [ ] Delegator/coordinator (optional): decompose one request into subtasks fanned out to workers
- [ ] **Isolated sessions** — each result in its own pane/view, all streaming concurrently

### Phase 5 — VS Code extension  🎯 *type `. … .` live → code appears; `!.` routes to cloud*
- [ ] **Live-as-you-type** detection (fire on closing delimiter) + debounce/cancel
- [ ] Sigil routing honored from the editor
- [ ] Stream results; **diff preview** before applying; insert/replace
- [ ] Engine status + active-model surface; cloud-egress indicator
- [ ] (Stretch) ghost-text **FIM autocomplete** as a separate fast channel

### Phase 6 — Context & RAG (Max knows your codebase)  🎯 *context-aware answers*
- [ ] Workspace indexer (walk, chunk, ignore rules)
- [ ] Embeddings + local vector store; incremental re-index
- [ ] Retrieval injected into prompts; per-project / session **memory**

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
- [ ] Voice input, vision models, tool-calling/agents

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
- Desktop shell: **Tauri** (light, Rust+web) or **Electron** (familiar, heavier)?
- For chat-app v1, do we wire **both** local (Ollama) and cloud (Claude) from day one, or local-only first then add `!`?
- Operator collision: `!` is the cloud sigil — keep `!` for fix/refactor, or pick a different operator (e.g. `~`)?
- Does v1 chat app need **codebase RAG**, or is plain chat + model config enough to start?
- Default per-task models — want me to propose a concrete default mapping after the Phase 0 benchmark?
