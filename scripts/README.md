# scripts

Dev/ops helpers for Max.

## `smoke.ps1` — engine end-to-end smoke test

Boots the engine (optional) and exercises the real HTTP/SSE surface:
`/health`, `/parse`, `/v1/chat/completions`, `/command`.

```powershell
# boot the engine, run all checks, tear it down
./scripts/smoke.ps1 -Start

# against an already-running engine, with a specific local model
./scripts/smoke.ps1 -Model qwen2.5-coder:3b
```

`/health` and `/parse` need no model. The inference checks report **SKIP**
(clean backend error) when Ollama isn't running, and **PASS** once a local
model is pulled — so the script is useful before and after Stage B setup.
See [../docs/setup.md](../docs/setup.md) to install Ollama + pull a model.
