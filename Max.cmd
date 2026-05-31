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
set "APPDIR=%~dp0"

rem  Create logs dir for engine stderr capture (written by Tauri / Rust side)
if not exist "%~dp0logs" mkdir "%~dp0logs"

if not exist "%MAXEXE%" goto :build

:launch
echo [Max] Launching desktop app - the engine starts automatically...
start "" "%MAXEXE%"

rem  Health gate: poll /health for up to 40 seconds in background.
rem  If it never comes up, open Leo in a dedicated rescue terminal.
start "Max Health Gate" /min cmd /c ^
    powershell -NoProfile -NonInteractive -Command ^
    "$ok=$false; for($i=0;$i -lt 40;$i++){try{$r=Invoke-WebRequest -Uri 'http://localhost:8001/health' -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop;if($r.StatusCode -eq 200){$ok=$true;break}}catch{};Start-Sleep 1}; if(-not $ok){Start-Process powershell -ArgumentList '-NoExit','-File','\"%LEOSC%\"','-AppDir','\"%APPDIR%\"' -WindowStyle Normal}"

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
