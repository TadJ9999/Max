# Max pre-push hook — runs pytest + tsc before every git push.
# Blocks the push on failure and reports to Aegis if the engine is running.

param()

$ErrorActionPreference = "Stop"
$ROOT   = Split-Path $PSScriptRoot -Parent
$ENGINE = Join-Path $ROOT "engine"
$APP    = Join-Path $ROOT "app"
$AEGIS  = "http://127.0.0.1:8001/aegis/report"

function Report-To-Aegis {
    param([string]$Suite, [string]$Output)
    try {
        # NOTE: the /aegis/report endpoint only persists these fields:
        # source, severity, kind, message, traceback, context. Anything else
        # (e.g. a "detail" key) is silently dropped by Pydantic — which is why
        # the suite output must go into `traceback` to be captured/diagnosable.
        $body = @{
            source    = "pre-push-hook"
            severity  = "Medium"
            kind      = "PrePushCheckFailed"
            message   = "[$Suite] pre-push check FAILED"
            traceback = $Output
            context   = @{ suite = $Suite }
        } | ConvertTo-Json -Compress
        Invoke-RestMethod -Uri $AEGIS -Method POST `
            -ContentType "application/json" -Body $body `
            -TimeoutSec 3 | Out-Null
    } catch {}
}

Write-Host "==> [pre-push] Running engine tests..." -ForegroundColor Cyan

Push-Location $ENGINE
$pytestOut = python -m pytest tests/ -x -q 2>&1 | Out-String
$pytestOk  = ($LASTEXITCODE -eq 0)
Pop-Location

if (-not $pytestOk) {
    Write-Host $pytestOut
    Write-Host "FAIL: Engine tests failed. Push blocked." -ForegroundColor Red
    Report-To-Aegis -Suite "pytest" -Output $pytestOut
    exit 1
}
Write-Host "PASS: Engine tests passed." -ForegroundColor Green

Write-Host "==> [pre-push] Running TypeScript check..." -ForegroundColor Cyan

Push-Location $APP
$tscOut = npx tsc --noEmit 2>&1 | Out-String
$tscOk  = ($LASTEXITCODE -eq 0)
Pop-Location

if (-not $tscOk) {
    Write-Host $tscOut
    Write-Host "FAIL: TypeScript check failed. Push blocked." -ForegroundColor Red
    Report-To-Aegis -Suite "tsc" -Output $tscOut
    exit 1
}
Write-Host "PASS: TypeScript check passed." -ForegroundColor Green

Write-Host "==> [pre-push] All checks passed. Proceeding with push." -ForegroundColor Green
exit 0
