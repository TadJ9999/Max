# Install Max git hooks.
# Run once after cloning: scripts\install-hooks.ps1

$ROOT      = Split-Path $PSScriptRoot -Parent
$HOOKS_DIR = Join-Path $ROOT ".git\hooks"
$HOOK_FILE = Join-Path $HOOKS_DIR "pre-push"

if (-not (Test-Path $HOOKS_DIR)) {
    Write-Host "Not a git repository (no .git/hooks). Aborting." -ForegroundColor Red
    exit 1
}

$content = @"
#!/bin/sh
# Auto-installed by scripts/install-hooks.ps1
powershell.exe -ExecutionPolicy Bypass -NoProfile -File "$(Join-Path $ROOT 'scripts\pre-push.ps1')"
"@

Set-Content -Path $HOOK_FILE -Value $content -Encoding UTF8
Write-Host ("Installed pre-push hook at " + $HOOK_FILE) -ForegroundColor Green
Write-Host "Pushes will now be gated by pytest + tsc. Failures appear in Aegis."
