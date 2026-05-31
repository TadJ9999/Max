@echo off
rem ============================================================================
rem  Kill-Max.cmd — emergency force-kill for when Max is stuck / port deadlocked.
rem  Double-click this to wipe all Max processes and free port 8001.
rem ============================================================================
echo [Kill-Max] Stopping all Max processes...

rem  Kill the desktop app
taskkill /F /IM Max.exe >nul 2>&1

rem  Kill the Python engine (uvicorn) by port 8001
powershell -NoProfile -NonInteractive -Command ^
    "$pids = (netstat -ano | Select-String ':\b8001\b') | ForEach-Object { ($_ -replace '.*\s+(\d+)\s*$','$1').Trim() } | Where-Object { $_ -match '^\d+$' } | Sort-Object -Unique; foreach ($p in $pids) { taskkill /F /T /PID $p 2>$null | Out-Null; Write-Host \"  Killed PID $p\" }"

rem  Belt-and-suspenders: kill any python process that might be the engine
taskkill /F /FI "IMAGENAME eq python.exe" /FI "WINDOWTITLE eq *uvicorn*" >nul 2>&1

rem  Confirm
timeout /t 1 /nobreak >nul
powershell -NoProfile -NonInteractive -Command ^
    "$busy = netstat -ano | Select-String ':\b8001\b'; if ($busy) { Write-Host '[Kill-Max] WARNING: port 8001 still in use:'; $busy } else { Write-Host '[Kill-Max] Done. Port 8001 is free. You can now launch Max.cmd.' }"

echo.
pause
