@echo off
rem ============================================================================
rem  Max launcher — double-click to build (if needed) and start the desktop app.
rem  The app OWNS the engine: on launch it starts the FastAPI engine
rem  (uvicorn on port 8001) if it isn't already running, and stops it on
rem  shutdown. Close the app with the red shutdown button to free the port.
rem
rem  AEGIS health gate: after launching, polls /health for 40s. If the engine
rem  never answers, Leo opens in a rescue terminal to diagnose and fix it.
rem ============================================================================
setlocal
cd /d "%~dp0"

set "MAXEXE=%~dp0app\src-tauri\target\release\Max.exe"
set "LEOSC=%~dp0scripts\leo.ps1"
rem  %~dp0 always ends with a backslash; a trailing \" gets mis-parsed as an
rem  escaped quote when passed to PowerShell, so strip it to a clean path.
set "APPDIR=%~dp0"
if "%APPDIR:~-1%"=="\" set "APPDIR=%APPDIR:~0,-1%"

rem  Create logs dir for engine stderr capture (written by Tauri / Rust side)
if not exist "%~dp0logs" mkdir "%~dp0logs"

if not exist "%MAXEXE%" goto :build

:launch
rem  Always refresh the web UI (app\dist) before launching so the engine — and
rem  any LAN phone hitting https://<pc>.local:8443/ — serves the CURRENT code.
rem  Mobile and desktop are the same bundle (main.tsx renders MobileApp on /m),
rem  so one `npm run build` covers both. This is just tsc + vite (no Rust
rem  recompile), and frontendDist=../dist means the desktop app picks it up too.
rem  If the rebuild fails we keep the existing dist and still launch.
rem  Leo build console: animated poodle + spinner; verbose output → logs\,
rem  errors surfaced only on failure (see scripts\leo-build.ps1).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\leo-build.ps1" -Mode refresh -AppDir "%APPDIR%"
if errorlevel 1 (
    echo.
    echo   [Max] Web UI rebuild failed - launching with the existing dist.
    echo         Fix the build errors above so mobile/LAN serves current code.
    echo.
)
cd /d "%~dp0"

rem  Kill any stale Max.exe (crash survivor) so single-instance doesn't block.
taskkill /F /IM Max.exe >nul 2>&1
echo [Max] Launching desktop app - the engine starts automatically...
start "" "%MAXEXE%"

rem  Health gate: poll the engine for up to 60s in the background; open Leo only
rem  if it never comes up. LAN-aware — when "Share on LAN" is on the engine binds
rem  HTTPS on 8443 (not http/8001), so health-gate.ps1 reads .maxconfig.json and
rem  port-checks the right place. (Hardcoding 8001/http tripped Leo on every LAN
rem  launch even though the engine was healthy.)
start "Max Health Gate" /min powershell -NoProfile -ExecutionPolicy Bypass ^
    -File "%~dp0scripts\health-gate.ps1" -AppDir "%APPDIR%" -LeoScript "%LEOSC%"

goto :end

:build
rem  First run: full desktop build, fronted by the Leo build console.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\leo-build.ps1" -Mode full -AppDir "%APPDIR%"
if errorlevel 1 (
    echo.
    echo   [Max] Build failed. See the Leo error tail above ^(full log: logs\build.out.log^).
    echo.
    pause
    goto :end
)
cd /d "%~dp0"
goto :launch

:end
endlocal
