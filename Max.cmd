@echo off
rem ============================================================================
rem  Max launcher — double-click to start the desktop app.
rem  The app OWNS the engine: on launch it starts the FastAPI engine
rem  (uvicorn on port 8001) if it isn't already running, and stops it on
rem  shutdown. Close the app with the red shutdown button to free the port.
rem ============================================================================
setlocal
cd /d "%~dp0"

set "MAXEXE=%~dp0app\src-tauri\target\release\Max.exe"
if not exist "%MAXEXE%" goto :nobuild

echo [Max] Launching desktop app - the engine starts automatically...
start "" "%MAXEXE%"
goto :end

:nobuild
echo.
echo   [Max] Max.exe not built yet. From the app folder, run:
echo         npm run tauri build -- --no-bundle
echo   Then double-click Max.cmd again.
echo.
echo   [Max] Note: the engine venv must exist at engine\.venv for the app
echo         to start the engine automatically.
echo.
pause

:end
endlocal
