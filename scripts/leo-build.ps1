<#
.SYNOPSIS
    Leo - Max's BUILD console. Wraps the web-UI / desktop-app build in Leo's
    terminal aesthetic: ASCII poodle + an animated spinner while the build runs,
    with the verbose npm/tsc/vite/cargo output tucked into a log. On success a
    happy poodle; on failure a sad poodle + the error tail (so you can still fix it).

.NOTES
    Same bulletproof rendering rules as leo.ps1:
      * PURE ASCII source (no box-drawing, emoji, Greek, smart quotes/dashes) so
        Windows PowerShell 5.1 (ANSI) renders identically to PowerShell 7.
      * Color via Write-Host -ForegroundColor, never raw ANSI escapes.
      * Sequential output; the only in-place trick is a carriage-return spinner.
#>
param(
    [ValidateSet("refresh", "full")]
    [string]$Mode = "refresh",
    [string]$AppDir = ""
)

$ErrorActionPreference = "Continue"

if ($AppDir) { $AppDir = $AppDir.Trim().TrimEnd('\', '"', ' ') }
if (-not $AppDir -or -not (Test-Path $AppDir)) { $AppDir = Split-Path -Parent $PSScriptRoot }

$webDir = Join-Path $AppDir "app"
$logDir = Join-Path $AppDir "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$outLog = Join-Path $logDir "build.out.log"
$errLog = Join-Path $logDir "build.err.log"

try { $Host.UI.RawUI.WindowTitle = "LEO - BUILD MODE" } catch { }

function Say([string]$m, [string]$c = "Red") { Write-Host "  $m" -ForegroundColor $c }
function Rule() { Write-Host ("  " + ("-" * 58)) -ForegroundColor DarkRed }

function Show-Poodle([string]$mood = "work") {
    $eyes = "o.o"; $mouth = "^"; $tag = "Leo is building..."; $color = "Red"
    switch ($mood) {
        "happy" { $eyes = "^.^"; $mouth = "v"; $tag = "woof! build is done!"; $color = "Green" }
        "sad"   { $eyes = "T.T"; $mouth = "_"; $tag = "build hit a snag - see below."; $color = "Yellow" }
    }
    Write-Host ""
    Write-Host "     ,_     ,_"        -ForegroundColor $color
    Write-Host "    ( $eyes )   $tag"  -ForegroundColor $color
    Write-Host "     > $mouth <"       -ForegroundColor $color
    Write-Host "    (__)_(__)"         -ForegroundColor $color
    Write-Host ""
}

if ($Mode -eq "full") {
    $label = "Building Max (first run - compiling the desktop app)"
    $cmd   = "npm run tauri build -- --no-bundle"
} else {
    $label = "Refreshing the web UI (mobile + desktop)"
    $cmd   = "npm run build"
}

Clear-Host
Write-Host ""
Write-Host ("  == LEO - BUILD MODE " + ("=" * 37)) -ForegroundColor Red
Write-Host ""
Show-Poodle "work"
Say $label "Red"
Say "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" "DarkRed"
Rule

# Launch the build, redirecting the noisy output into log files so the console
# stays clean for Leo's spinner.
Set-Content -Path $outLog -Value "" -Encoding UTF8
Set-Content -Path $errLog -Value "" -Encoding UTF8
$proc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $cmd `
    -WorkingDirectory $webDir -RedirectStandardOutput $outLog -RedirectStandardError $errLog `
    -PassThru -NoNewWindow
# Cache the OS handle NOW — without this, Start-Process -PassThru drops the handle
# and $proc.ExitCode comes back $null after the process exits (a known quirk).
$null = $proc.Handle

# Animated single-line spinner (carriage-return) while the build runs.
$frames = @(">(o.o)   ", " >(o.o)  ", "  >(o.o) ", "   >(o.o)", "  >(o.o) ", " >(o.o)  ")
$i = 0
$sw = [System.Diagnostics.Stopwatch]::StartNew()
while (-not $proc.HasExited) {
    $f    = $frames[$i % $frames.Count]
    $secs = [int]$sw.Elapsed.TotalSeconds
    Write-Host ("`r  [$f] working... ${secs}s          ") -NoNewline -ForegroundColor Red
    $i++
    Start-Sleep -Milliseconds 120
}
Write-Host ("`r" + (" " * 72) + "`r") -NoNewline   # erase the spinner line
$proc.WaitForExit()
$code = $proc.ExitCode
$took = [int]$sw.Elapsed.TotalSeconds

if ($code -eq 0) {
    Show-Poodle "happy"
    Say "[ok] $label - done in ${took}s" "Green"
    Write-Host ""
    exit 0
}

Show-Poodle "sad"
Say "[x] Build failed (exit $code) after ${took}s. Last lines:" "Red"
Rule
$tail = @()
if (Test-Path $errLog) { $tail += (Get-Content $errLog -Tail 25 | Where-Object { $_ -ne "" }) }
if ((-not $tail) -and (Test-Path $outLog)) { $tail += (Get-Content $outLog -Tail 25) }
foreach ($l in $tail) { Say "  $l" "DarkRed" }
Rule
Say "Full log: $outLog" "Yellow"
Write-Host ""
exit 1
