# Max — Aegis (self-debug & fix engine)

> How Max watches its own logs, explains what broke, and — with your explicit
> OK — fixes itself. The short version: **capture every error into a persistent
> store, let an AI diagnose the root cause and propose a patch, gate the fix
> behind a human approval + diff preview, then apply it with a git-snapshot
> rollback and test-verify — recording everything in `selfdiagnosefixes.md`.**

Aegis is the self-healing shield (codename in the `Apollo` family). It is a
**capability** on the engine, not a rewrite: it reuses the provider router,
delegate/sessions, SSE streaming, prompt templates, and the workspace allowlist
that already exist.

## Two layers (the engine isn't always up)

The hardest failure is a **cold start** — you launch Max and the engine never
comes up (bad venv, port in use, a syntax error in the engine, a missing key).
At that moment there is no engine to run `/aegis/diagnose` and no desktop window
to show it. So Aegis has two layers:

| Layer | When | Where it runs | Brain |
|-------|------|---------------|-------|
| **Leo — boot rescue** *(build first)* | launch **fails / any startup issue** | a standalone **terminal** Leo opens himself | cloud Claude → local Ollama → offline heuristics |
| **Runtime layer** | engine **is up**, something later breaks | the in-engine `aegis` module + desktop 🛡 window | router/delegate (cloud default, local fallback) |

> **Status: built (Phase 13).** Leo (`scripts/leo.ps1` + `Max.cmd` health gate) and
> the runtime layer (`engine/max_engine/aegis/` + Hub 🛡 tab) are live.

They are deliberately decoupled: **Leo must work with nothing else running**, so he
never calls the engine's endpoints. Both layers share the same contract — the
diagnosis prompt shape, secret redaction, the git-snapshot/allowlist/verify
discipline, and the single [`selfdiagnosefixes.md`](../selfdiagnosefixes.md) logbook.

## Leo — the boot-time rescue terminal 🐩

Leo is Max's little rescue dog: a **bubbly, upbeat** terminal companion who shows up
the moment a launch goes sideways and refuses to leave your side until Max is back on
its paws. He is friendly and chatty, but he is *all business about the fix* — and
**everything Leo prints is red**, so you always know you're in rescue mode.

**Trigger.** `Max.cmd` launches the app, which *owns* the engine (it starts uvicorn on
**port 8001** itself). A health gate polls `/health` for ~40s. If health never answers
— **or any other launch/startup problem occurs** — Leo opens a new terminal window and
takes over.

**What you see.** A red **`LEO · SELF-DIAGNOSE MODE`** banner with a tiny poodle, then
a live, **all-red** status stream (the `smoke.ps1` colored-status idiom, recolored red),
Leo cheering you through each step and **staying open until `/health` is back up**.

**What Leo does, each round:**
1. **Sniff around (health check)** — if the engine is already answering, Leo celebrates,
   offers to relaunch the app, and goes to his happy finale (below).
2. **Gather the signal** — environment checks (venv, `.env`, cloud key, port busy,
   Ollama reachable) + the **tail of the captured engine stderr**.
3. **Redact** secrets from that signal (mandatory) before any egress.
4. **Diagnose** — cloud Claude via the Anthropic API by default; fall back to a local
   Ollama `/api/generate` call; fall back again to **offline heuristics** (rule-matching
   common boot failures) so Leo is *useful even with no network and no models*. Output =
   root cause + a concrete fix + how to verify.
5. **Record** the proposal to `selfdiagnosefixes.md` (status `proposed`).
6. **Cheer you on (communicate)** — `[R]etry (relaunch Max) · [D]iagnose again ·
   [S]hell · [Q]uit`. On retry Leo relaunches the app (preserving the *app-owns-engine*
   model — never a competing uvicorn) and re-polls `/health`; the loop repeats until the
   engine is healthy.

**The happy finale.** The instant `/health` goes green, Leo announces **"My job is
done!"** and prints a **tiny smiling toy-poodle ASCII image**, then trots off (exits).
Candidate art (refine at build — small, curly, clearly smiling):

```
   Leo: My job is done!  ♥

        //\__/\\
       ( ^ ω ^ )   woof!
        > 🐾  <
       /  curly \
      (__/    \__)
```

**Voice.** Leo's lines are short, warm, and encouraging ("On it!", "Found something —
let's fix it together!", "Almost there, hang tight!"). The *content* (diagnosis, fix,
verification) stays precise and technical; only the framing is bubbly.

**Safety.** Leo is **suggest-by-default** — he shows the fix and lets you apply it by
hand, then retry. Unattended auto-apply stays a runtime-layer concern (engine-side
allowlist guard + git snapshot + verify) and is out of scope for Leo.

**Files (when built):** a `scripts/` rescue console (PowerShell on Windows; a `.sh`
sibling once non-Windows lands), wired into [`Max.cmd`](../Max.cmd) behind a health
gate, with captured startup logs under `logs/`.

The rest of this document describes the **runtime layer** (in-engine Aegis).

## Goals & non-goals

- **Goal:** turn silent stdout crashes into a tracked, explainable, optionally
  self-repairing loop — without ever changing code behind your back.
- **Goal:** stay consistent with Max's ethos — *opt-in, marked, local-capable,
  allowlist-scoped, reversible*.
- **Non-goal (v1):** unattended autonomous repair. Full-auto (detect→fix→test→
  restart) is a flagged stretch, off by default.
- **Non-goal (v1):** auto-fixing Rust/Tauri. Its stderr is captured as a signal;
  whole-repo auto-fix (incl. Rust) is the stated target, frontend+engine ship first.

## Where it fits the two planes

Aegis lives on the **capability plane** (see [architecture.md](architecture.md)).
Its `/aegis/*` endpoints extend the **control plane** the clients already speak,
exactly like `/osint/*` and `/market/*` did. The diagnosis step is just another
delegate job routed through the provider router.

## Layers

```
                         ┌──────────────── MAX ENGINE ────────────────┐
  crash / exception ───► │ 1. OBSERVABILITY                           │
  log signal        ───► │    structured logger → ring buffer         │
  frontend onerror  ───► │    → SQLite event store (survives restart) │
  delegate ERROR    ───► │    + secret redaction                      │
                         │                    │                       │
                         │ 2. DIAGNOSIS       ▼                       │
                         │    collect issue + log context + source    │
                         │    (allowlist only) → diagnostic prompt    │
                         │    → router (cloud Claude default / local) │
                         │    → root cause · severity · files · diff  │
                         │                    │                       │
  you ◄── notify ────────│ 3. HUMAN GATE  ◄── approve / reject        │
                         │                    │ (approved)            │
                         │ 4. APPLY · VERIFY · ROLLBACK               │
                         │    git snapshot → patch (allowlist guard)  │
                         │    → verify (pytest / tsc+build)           │
                         │    → green: keep · fail/reject: git revert │
                         │                    │                       │
                         │ 5. LOGBOOK → selfdiagnosefixes.md          │
                         └────────────────────────────────────────────┘
   desktop: 🛡 Aegis window (below chat bar) · mascot "error" deep-links here
```

## 1. Observability (capture)

A new `engine/max_engine/aegis/` module owns capture. Today the engine only
`print()`s to stdout (`main.py`), the delegate stores a per-session error string
(`delegate/engine.py:127-129`), and the frontend has a lone `console.error`. Aegis
turns all of these into structured **events**.

**Event schema** (stored as JSON rows in SQLite so they survive a restart):

| Field | Meaning |
|-------|---------|
| `id` | stable id (used by diagnose/apply) |
| `ts` | UTC timestamp |
| `source` | `engine` · `delegate` · `provider` · `frontend` · `rust` |
| `severity` | `Critical` · `High` · `Medium` · `Low` |
| `kind` | exception type / error class |
| `message` | redacted human message |
| `traceback` | redacted stack (where available) |
| `context` | request path, session id, provider/model, route |
| `fingerprint` | hash of kind+site for **dedupe / loop protection** |
| `count`, `first_ts`, `last_ts` | rollup for repeated errors |

**Capture points:**
- **Engine** — a FastAPI exception handler (`@app.exception_handler(Exception)`)
  records unhandled errors before returning the existing structured error body.
- **Delegate** — tap the `except Exception` in `_run()` (`delegate/engine.py:127`)
  so failed sessions raise an event, not just set `session.output`.
- **Provider** — wrap provider errors (e.g. Anthropic `_api_error_message`).
- **Frontend** — a small client installs `window.onerror` + `unhandledrejection`
  handlers that `POST /aegis/report`.
- **Rust/Tauri** — the shell already logs engine start/stop and forwards engine
  stdout/stderr (`app/src-tauri/src/lib.rs`); pipe that stderr to `/aegis/report`
  as a `rust`/`engine` signal.

**Secret redaction** runs on every message/traceback before it is stored *or* sent
to the cloud — scrub `ANTHROPIC_API_KEY`, `FINNHUB_API_KEY`, bearer tokens, and
anything matching known key shapes. Redaction is mandatory and tested.

## 2. Diagnosis

A new `aegis` **prompt template** in `prompts.py` (alongside the `market`/OSINT
analyst prompts) frames the model as a debugger. Given an event, Aegis gathers:
the event + rollup, surrounding log lines, and the **relevant source files** — but
only files inside `config.workspace_allowlist`.

Routing reuses the existing path: **cloud Claude by default** (best reasoning on
tricky bugs), **local model fallback** when `allow_cloud` is off or the cloud key
is missing. Because diagnosis sends code/logs off-machine, it is **egress** — gated
by `allow_cloud` and marked like the `!` sigil (see Privacy below).

The model must return a **structured result**:

- `root_cause` — plain-English explanation
- `severity` — Critical/High/Medium/Low
- `files` — affected paths (allowlist-scoped)
- `diff` — a **unified diff** ready to apply
- `verification` — which check should confirm the fix

Streaming uses the existing `_sse_stream` helper (as `/market/analyze` does), so the
desktop view shows the diagnosis token-by-token.

## 3. Human gate

Nothing is applied without an explicit approval. The autonomy level is config-driven
(`AegisConfig.autonomy`):

| Level | Behavior |
|-------|----------|
| `suggest` | diagnose + write the proposal to the logbook; never edits code |
| `ask` *(default)* | diagnose → **notify** → show diff → apply only on approval |
| `auto` *(stretch, flagged)* | detect→fix→test→restart, logged after the fact |

The desktop **mascot error state** (already wired in Phase 3) becomes the notifier:
it deep-links to the Aegis window with "Max found an issue →". (When the engine is
down entirely, **Leo** is the notifier instead — see above.)

## 4. Apply · verify · rollback

On approval, `POST /aegis/apply`:
1. **Snapshot** with git (the repo is already a git repo) so any change is revertible.
2. **Guard** — reject any hunk touching a path outside `workspace_allowlist`.
3. **Apply** the unified diff.
4. **Verify** with target-appropriate commands (configurable): `pytest` for the
   engine, `tsc && vite build` for the frontend.
5. **Keep on green**; on failure (or a later `POST /aegis/rollback`, or a rejection)
   **git-revert** to the snapshot.

This is the same *diff-preview-before-apply* trust model the VS Code phase calls for
(ROADMAP §4.5), applied to Max's own source.

## 5. Logbook — `selfdiagnosefixes.md`

Every diagnosis and fix appends an organized entry to the root
[`selfdiagnosefixes.md`](../selfdiagnosefixes.md). Status legend: `proposed` →
`applied` → `verified`, or `rolled-back`. Entry format:

```
## <UTC timestamp> — <short symptom>
- **Status:** proposed | applied | verified | rolled-back
- **Severity:** Critical | High | Medium | Low
- **Trigger:** <signal + where it was captured>
- **Root cause:** <AI diagnosis>
- **Files changed:** <allowlist-scoped paths>
- **Fix:** <one-line summary>   ·   **Provider:** ☁ claude | local
- **Verification:** <pytest / tsc+build result>
- **Diff:** <fenced unified diff or link>
- **Rollback:** <git ref / how to revert>
```

## Endpoint reference

| Endpoint | Purpose |
|----------|---------|
| `GET /aegis/events` | recent captured issues, ranked, newest-first |
| `POST /aegis/report` | client/Rust pushes an error signal |
| `POST /aegis/diagnose` | **SSE** — analyze an event → root cause + diff |
| `POST /aegis/apply` | apply an approved patch → verify → log |
| `POST /aegis/rollback` | revert the last applied fix |
| `GET /aegis/log` | structured history (the logbook) |
| `GET /aegis/sources` | status: provider, store path, autonomy, key-set |

## Safety, privacy & loop protection

- **Never silent.** `ask` is the default; applies require approval; every action is
  logged.
- **Allowlist-scoped.** Edits cannot escape `workspace_allowlist`.
- **Reversible.** Git snapshot before every apply; verify-before-keep.
- **Loop protection.** Events are deduped by `fingerprint`; a per-fingerprint
  **cooldown** + a cap on fixes-per-error stop a bad patch from triggering infinite
  re-diagnosis (and a fix that fails verification is auto-reverted, not retried blindly).
- **Privacy/egress.** Cloud diagnosis sends redacted code/logs off-machine — surfaced
  in settings/privacy guard and honoring the network kill-switch, exactly like the
  cloud `!` sigil, OSINT, and Market.

## Open questions / future

- **Full-auto mode** — what guardrails make unattended repair safe enough to enable?
- **Rust/Tauri auto-fix** — native build + panics are the hardest; what's the verify story?
- **Learn from history** — embed `selfdiagnosefixes.md` into Apollo memory so recurring
  bugs are recognized and prior fixes proposed first.
