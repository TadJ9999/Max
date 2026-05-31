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
rem  Kill any stale Max.exe (crash survivor) so single-instance doesn't block.
taskkill /F /IM Max.exe >nul 2>&1
echo [Max] Launching desktop app - the engine starts automatically...
start "" "%MAXEXE%"

rem  Health gate: poll /health for up to 60 seconds in background.
rem  If it never comes up, open Leo in a dedicated rescue terminal.
rem  NOTE: use 127.0.0.1 (not 'localhost'). On Windows 'localhost' resolves to
rem  ::1 (IPv6) first, but uvicorn binds only 127.0.0.1 (IPv4) — so a localhost
rem  request wastes ~2s failing over IPv6 before falling back, blowing the 2s
rem  timeout and tripping Leo on every launch even when the engine is healthy.
start "Max Health Gate" /min cmd /c ^
    powershell -NoProfile -NonInteractive -Command ^
    "$ok=$false; for($i=0;$i -lt 60;$i++){try{$r=Invoke-WebRequest -Uri 'http://127.0.0.1:8001/health' -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop;if($r.StatusCode -eq 200){$ok=$true;break}}catch{};Start-Sleep 1}; if(-not $ok){Start-Process powershell -ArgumentList '-NoExit','-ExecutionPolicy','Bypass','-File','\"%LEOSC%\"','-AppDir','\"%APPDIR%\"' -WindowStyle Normal}"

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
goto :launch

:end
endlocal
