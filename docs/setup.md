# Setup — from a fresh machine to a verified engine

Steps to get Max's engine running and **verified end-to-end** on a clean Windows box
(e.g. after a reinstall). Mirrors the "engine end-to-end verification" milestone.

## 1. Engine (Python)

```powershell
cd engine
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest -q      # expect 29 passed
```

## 2. Local models (Ollama)  ← Stage B, do after the OS reinstall

```powershell
winget install Ollama.Ollama
# new shell so PATH picks up ollama, then:
ollama pull qwen2.5-coder:3b      # ~1.9 GB — fast smoke-test model
# optional: the configured default used by /command
ollama pull qwen2.5-coder:14b     # ~9 GB — fits the 4070 Ti's 12 GB VRAM
```

Ollama serves on `http://127.0.0.1:11434` (already the engine's default).

## 3. Cloud path (`!` sigil) — optional, Stage C

Set an Anthropic key in the environment before launching the engine:

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."   # never commit this
```

Without a key the `!` cloud path is expected to fail cleanly; everything local still works.

## 3b. Desktop app toolchain (Tauri)

The widget app (`app/`) is Tauri v2 + React + TS + Vite. It needs Node, Rust, and the
MSVC C++ build tools (WebView2 ships with Windows 11):

```powershell
winget install OpenJS.NodeJS.LTS
winget install Rustlang.Rustup
winget install Microsoft.VisualStudio.2022.BuildTools --override "--quiet --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
# new shell, then:
cd app
npm install
npm run dev          # frontend only (browser preview, http://localhost:1420)
npm run tauri dev    # the real floating widget window (needs Rust + build tools)
```

## 4. Verify end-to-end

```powershell
./scripts/smoke.ps1 -Start
```

Expected once Ollama + a model are present: `/health` and `/parse` **PASS**,
`/v1/chat/completions` and `/command` **PASS** (real streamed tokens). Before
Stage B, the two inference checks report **SKIP** with a clean backend error —
that already confirms the HTTP + SSE plumbing and routing work.

## Status of this milestone

- [x] Stage A — HTTP/SSE plumbing verified (engine boots, `/health` + `/parse` pass, inference path SKIPs cleanly)
- [x] Stage B — real local inference ✅ (Ollama 0.24 + `qwen2.5-coder:3b` & `:14b`; smoke test all PASS, `/command` streams real code, delegate sessions run → done)
- [x] Stage C — cloud `!` path ✅ (`ANTHROPIC_API_KEY` in `engine/.env`; `!`/`/command` + cloud delegate sessions stream real Claude output)
