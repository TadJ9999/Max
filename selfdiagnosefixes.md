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


## 2026-05-31T20:34Z - Boot failure (Leo)
- **Status:** proposed
- **Root cause:** ROOT CAUSE:
- **Fix:** Port 8001 is held by a stale process from a previous failed startup. The engine cannot bind to the port, and Ollama is down so local diagnosis cannot run.  FIX COMMANDS: lsof -ti:8001 | xargs kill -9 sleep 2 cd /path/to/max && python -m uvicorn main:app --host 0.0.0.0 --port 8001  (Replace /path/to/max with your actual project directory)  VERIFICATION: curl http://localhost:8001/health Expected: HTTP 200 response with health status, not connection refused.


## 2026-05-31T20:34Z - Boot failure (Leo)
- **Status:** proposed
- **Root cause:** ROOT CAUSE:
- **Fix:** Port 8001 is held by a stale process or another service. FastAPI cannot bind to the port, so the engine fails silently. Ollama being down means local diagnosis cannot help.  FIX COMMANDS: lsof -i :8001 Kill the process using port 8001 with: kill -9 <PID> Then restart the engine: cd /path/to/max && python -m uvicorn main:app --port 8001 --host 0.0.0.0  VERIFICATION: curl -s http://localhost:8001/health Should return HTTP 200 with a valid response. If you get connection refused, the port is still blocked or FastAPI didn't start.


## 2026-05-31T20:35Z - Boot failure (Leo)
- **Status:** proposed
- **Root cause:** ROOT CAUSE:
- **Fix:** Port 8001 is held by a stale process or crashed FastAPI instance. Without Ollama running, the engine cannot start its local diagnosis fallback, compounding the startup failure.  FIX COMMANDS: lsof -i :8001 | grep LISTEN | awk '{print $2}' | xargs kill -9 sleep 2 cd /path/to/max && python -m uvicorn main:app --host 0.0.0.0 --port 8001  (Replace /path/to/max with your actual FastAPI project directory)  VERIFICATION: curl -s http://localhost:8001/health | grep -q "ok" && echo "ENGINE UP" || echo "FAILED"  If curl fails, check logs: tail -f /path/to/max/engine.log


## 2026-06-02T12:17Z - Boot failure (Leo)
- **Status:** proposed
- **Root cause:** ROOT CAUSE:
- **Fix:** FastAPI engine on port 8001 failed to start with no stderr output, indicating either a missing dependency, port conflict, or incomplete startup before logs were captured.  FIX COMMANDS: lsof -i :8001 pip install fastapi uvicorn python -m uvicorn main:app --host 0.0.0.0 --port 8001  VERIFICATION: curl http://localhost:8001/docs Check response is HTTP 200 and Swagger UI loads.


## 2026-06-02T12:19Z - Boot failure (Leo)
- **Status:** proposed
- **Root cause:** ROOT CAUSE:
- **Fix:** The FastAPI engine on port 8001 failed to start, likely due to a missing or misconfigured startup process, dependency issue, or port already in use. Without stderr logs, the process may have exited silently before logging errors.  FIX COMMANDS: lsof -i :8001 | grep LISTEN kill -9 $(lsof -t -i :8001) 2>/dev/null || true cd /path/to/max && python -m pip install -r requirements.txt cd /path/to/max && python -m uvicorn main:app --host 0.0.0.0 --port 8001  VERIFICATION: curl http://localhost:8001/docs If the Swagger UI loads, the engine is running. Also check: ps aux | grep uvicorn to confirm the process is active.


## 2026-06-02T12:33Z - Boot failure (Leo)
- **Status:** proposed
- **Root cause:** ROOT CAUSE:
- **Fix:** FastAPI engine on port 8001 failed to start with no stderr output, suggesting either a port binding issue, missing dependencies, or the process never launched. The absence of logs indicates the startup failed before logging initialized.  FIX COMMANDS: lsof -i :8001 pkill -f "port 8001" cd /path/to/max && pip install -r requirements.txt python -m uvicorn main:app --host 0.0.0.0 --port 8001  VERIFICATION: curl http://localhost:8001/docs Check that the Swagger UI loads and shows available endpoints.


## 2026-06-02T14:13Z - Boot failure (Leo)
- **Status:** proposed
- **Root cause:** ROOT CAUSE:
- **Fix:** The FastAPI engine on port 8001 failed to start with no stderr output, indicating either a missing dependency, import error, or the process exited before logging. The engine likely crashed during initialization before error messages could be written.  FIX COMMANDS: pip install fastapi uvicorn cd /path/to/max && python -m uvicorn main:app --host 0.0.0.0 --port 8001  VERIFICATION: curl http://localhost:8001/docs If the FastAPI interactive docs page loads, the engine is running successfully.


## 2026-06-02T14:13Z - Boot failure (Leo)
- **Status:** proposed
- **Root cause:** ROOT CAUSE:
- **Fix:** FastAPI engine on port 8001 failed to start with no stderr output. This typically indicates either the process exited silently before logging, a port binding issue, or missing dependencies.  FIX COMMANDS: lsof -i :8001 pip install -r requirements.txt python -m uvicorn main:app --host 0.0.0.0 --port 8001 --reload  VERIFICATION: curl http://localhost:8001/docs Check that the FastAPI Swagger UI loads and returns a 200 status code.


## 2026-06-02T14:13Z - Boot failure (Leo)
- **Status:** proposed
- **Root cause:** ROOT CAUSE:
- **Fix:** The FastAPI engine on port 8001 failed to start, but no error logs are available. The process likely crashed silently or failed during initialization before logging could occur.  FIX COMMANDS: python -m pip install fastapi uvicorn --upgrade cd /path/to/max && python -m uvicorn main:app --host 0.0.0.0 --port 8001 --reload  VERIFICATION: curl http://localhost:8001/docs If the Swagger UI loads and returns HTTP 200, the engine is running.  Note: Replace /path/to/max with the actual project directory path. If the engine still fails, run with --log-level debug to capture initialization errors.


## 2026-06-02T14:53Z - Boot failure (Leo)
- **Status:** proposed
- **Root cause:** ROOT CAUSE:
- **Fix:** The FastAPI engine on port 8001 failed to start with no error logs captured, indicating either a startup timeout, silent crash, or port binding issue.  FIX COMMANDS: lsof -i :8001 pkill -f "FastAPI.*8001" || true cd /path/to/max && python -m uvicorn main:app --host 0.0.0.0 --port 8001 --reload  VERIFICATION: curl http://localhost:8001/docs Check for 200 response and FastAPI Swagger UI loads successfully.


## 2026-06-02T14:54Z - Boot failure (Leo)
- **Status:** proposed
- **Root cause:** ROOT CAUSE:
- **Fix:** FastAPI engine on port 8001 failed to start with no error logs, indicating either a port binding issue, missing dependencies, or the process didn't initialize. The absence of stderr suggests the application may have exited before logging began.  FIX COMMANDS: lsof -i :8001 | grep -v COMMAND | awk '{print $2}' | xargs kill -9 2>/dev/null || true cd /path/to/max && pip install -r requirements.txt python -m uvicorn main:app --host 0.0.0.0 --port 8001  VERIFICATION: curl -s http://localhost:8001/docs && echo "Engine running successfully" || echo "Engine failed"


## 2026-06-02T14:54Z - Boot failure (Leo)
- **Status:** proposed
- **Root cause:** ROOT CAUSE:
- **Fix:** The FastAPI engine on port 8001 failed to start with no stderr output logged. This typically indicates either a port binding failure (port already in use), missing dependencies, or the process crashed before generating logs.  FIX COMMANDS: lsof -i :8001 | grep LISTEN && kill -9 $(lsof -t -i :8001) || true cd /path/to/max && pip install -r requirements.txt python -m uvicorn main:app --host 0.0.0.0 --port 8001  VERIFICATION: curl -s http://localhost:8001/docs && echo "FastAPI engine running" ps aux | grep "uvicorn" | grep -v grep

