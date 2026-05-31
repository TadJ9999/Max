# Max pre-push hook
# Runs engine pytest + frontend tsc before every git push.
# Blocks the push if either suite fails, and reports the failure to Aegis
# (if the local engine is reachable) so you can review it in the 🛡 tab.

param()

$ErrorActionPreference = "Stop"
$ROOT   = Split-Path $PSScriptRoot -Parent
$ENGINE = Join-Path $ROOT "engine"
$APP    = Join-Path $ROOT "app"
$AEGIS  = "http://127.0.0.1:8001/aegis/report"

function Report-To-Aegis {
    param([string]$Suite, [string]$Output)
    try {
        $body = @{
            source  = "pre-push-hook"
            message = "[$Suite] pre-push check FAILED"
            detail  = $Output
        } | ConvertTo-Json -Compress
        Invoke-RestMethod -Uri $AEGIS -Method POST `
            -ContentType "application/json" -Body $body `
            -TimeoutSec 3 | Out-Null
    } catch { <# engine may not be running — silently skip #> }
}

Write-Host "==> [pre-push] Running engine tests..." -ForegroundColor Cyan

Push-Location $ENGINE
$pytestOut = python -m pytest tests/ -x --timeout=30 -q 2>&1 | Out-String
$pytestOk  = $LASTEXITCODE -eq 0
Pop-Location

if (-not $pytestOk) {
    Write-Host $pytestOut
    Write-Host "✗  Engine tests FAILED — push blocked." -ForegroundColor Red
    Report-To-Aegis -Suite "pytest" -Output $pytestOut
    exit 1
}
Write-Host "✓  Engine tests passed." -ForegroundColor Green

Write-Host "==> [pre-push] Running TypeScript check..." -ForegroundColor Cyan

Push-Location $APP
$tscOut = npx tsc --noEmit 2>&1 | Out-String
$tscOk  = $LASTEXITCODE -eq 0
Pop-Location

if (-not $tscOk) {
    Write-Host $tscOut
    Write-Host "✗  TypeScript check FAILED — push blocked." -ForegroundColor Red
    Report-To-Aegis -Suite "tsc" -Output $tscOut
    exit 1
}
Write-Host "✓  TypeScript check passed." -ForegroundColor Green

Write-Host "==> [pre-push] All checks passed — proceeding with push." -ForegroundColor Green
exit 0
