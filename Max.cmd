@echo off
rem ============================================================================
rem  Max launcher — double-click to start the desktop app.
rem  The app now OWNS the engine: on launch it starts the FastAPI engine
rem  (uvicorn on :8001) if it isn't already running, and stops it on shutdown.
rem  Close the app with the red shutdown button — it frees the engine + port.
rem ============================================================================
setlocal
cd /d "%~dp0"

set "MAXEXE=%~dp0app\src-tauri\target\release\Max.exe"
if exist "%MAXEXE%" (
  echo [Max] Launching desktop app (engine starts automatically)...
  start "" "%MAXEXE%"
) else (
  echo.
  echo   [Max] Max.exe not built yet. Build it once with:
  echo         cd app  ^&^&  npm run tauri build -- --no-bundle
  echo   Then double-click Max.cmd again.
  echo.
  echo   [Max] Tip: the engine venv must exist at engine\.venv for the app to
  echo         start it. Create it with:  cd engine ^&^&  python -m venv .venv  ^&^&
  echo         .venv\Scripts\pip install -e .
  echo.
  pause
)
endlocal
