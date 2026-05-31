# Max — Self-Diagnose & Fix Log

> Append-only logbook written by **Aegis**, Max's self-debug & fix engine
> (see [docs/aegis.md](docs/aegis.md) and Phase 13 in [ROADMAP.md](ROADMAP.md)).
> Every issue Max detects, diagnoses, and (with your approval) fixes is recorded
> here — newest entries at the **top**. Nothing is applied to the codebase without
> an explicit OK and a diff preview; every applied fix has a git-snapshot rollback.

## Status legend

| Status | Meaning |
|--------|---------|
| `proposed` | Aegis diagnosed the issue and suggested a fix; **no code changed** |
| `applied` | the patch was approved and written to the working tree |
| `verified` | the applied patch passed its verification (tests / build) |
| `rolled-back` | the fix was reverted (verification failed, or you rejected it) |

## Severity legend

`Critical` · `High` · `Medium` · `Low` — set from the crash/log signal and confirmed
by the AI diagnosis.

---

## Entry template

> Copy this block for each new entry (Aegis fills it in automatically). Keep newest
> at the top, directly under this template.

```
## <UTC timestamp> — <short symptom>
- **Status:** proposed | applied | verified | rolled-back
- **Severity:** Critical | High | Medium | Low
- **Trigger:** <crash/log signal + where it was captured (engine / delegate / provider / frontend / rust)>
- **Root cause:** <AI diagnosis>
- **Files changed:** <allowlist-scoped paths, or "none (proposed)">
- **Fix:** <one-line summary>   ·   **Provider:** ☁ claude | local
- **Verification:** <pytest / tsc+build result, or "pending">
- **Diff:** <fenced unified diff or link to the patch>
- **Rollback:** <git ref / how to revert, or "n/a">
```

---

<!-- Aegis appends real entries below this line, newest first. None yet. -->

## 2026-05-31T20:16Z - Boot failure (Leo)
- **Status:** proposed
- **Root cause:** ROOT CAUSE:
- **Fix:** Port 8001 is held by a stale process or another service. FastAPI failed to bind because the port wasn't available. Ollama is also down, removing your fallback diagnosis path.  FIX COMMANDS: lsof -i :8001 Kill the process shown (note its PID, then: kill -9 <PID>) Then restart Max's engine: cd /path/to/max && python -m uvicorn main:app --port 8001 --host 0.0.0.0  Or if you want the nuclear option: sudo fuser -k 8001/tcp Then restart the engine as above.  VERIFICATION: curl http://localhost:8001/health Should return HTTP 200 with a response body. ps aux | grep uvicorn Should show the FastAPI process running.


## 2026-05-31T20:17Z - Boot failure (Leo)
- **Status:** proposed
- **Root cause:** ROOT CAUSE:
- **Fix:** Port 8001 is held by a zombie process or previous FastAPI instance that didn't shut down cleanly. Ollama dependency is also down, which may have caused the initial crash.  FIX COMMANDS: lsof -i :8001 | grep LISTEN | awk '{print $2}' | xargs kill -9 systemctl start ollama cd /path/to/max && python -m uvicorn main:app --host 0.0.0.0 --port 8001  VERIFICATION: curl -s http://localhost:8001/health && echo "Engine responsive" || echo "Still down" Check Ollama: curl -s http://localhost:11434/api/tags | grep models  Run these in order and report any errors from the kill or curl commands.


## 2026-05-31T20:17Z - Boot failure (Leo)
- **Status:** proposed
- **Root cause:** ROOT CAUSE:
- **Fix:** Port 8001 is held by a stale process or hung FastAPI instance. Ollama is also down, preventing the diagnosis fallback service from running.  FIX COMMANDS: lsof -ti:8001 | xargs kill -9 sudo systemctl restart ollama sleep 2 python -m uvicorn main:app --host 0.0.0.0 --port 8001  VERIFICATION: curl http://localhost:8001/health curl http://localhost:11434/api/tags  Both should return 200 with valid responses. If curl fails, check that FastAPI started without errors in the terminal where you ran the python command.

