@echo off
rem ============================================================================
rem  Max launcher — double-click to build (if needed) and start the desktop app.
rem  The app OWNS the engine: on launch it starts the FastAPI engine
rem  (uvicorn on port 8001) if it isn't already running, and stops it on
rem  shutdown. Close the app with the red shutdown button to free the port.
rem ============================================================================
setlocal
cd /d "%~dp0"

set "MAXEXE=%~dp0app\src-tauri\target\release\Max.exe"
if not exist "%MAXEXE%" goto :build

echo [Max] Launching desktop app - the engine starts automatically...
start "" "%MAXEXE%"
goto :end

:build
echo.
echo   [Max] Max.exe not found — building now (this may take a few minutes)...
echo.
cd /d "%~dp0app"
call npm run tauri build -- --no-bundle
if errorlevel 1 (
    echo.
    echo   [Max] Build failed. Check the output above for errors.
    echo.
    pause
    goto :end
)
cd /d "%~dp0"
echo.
echo   [Max] Build complete. Launching...
start "" "%MAXEXE%"

:end
endlocal
