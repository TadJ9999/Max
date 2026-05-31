<#
.SYNOPSIS
    Leo - Max's boot-time rescue terminal.
    Runs when the engine fails to start. Diagnoses the problem and helps fix it.

.NOTES
    Bulletproof rendering rules (do not break these):
      * Source is PURE ASCII. No box-drawing, no emoji, no Greek letters, no
        smart quotes / em-dashes. This makes the on-disk encoding irrelevant,
        so Windows PowerShell 5.1 (which reads .ps1 as ANSI) renders it the
        same as PowerShell 7. Every past Leo bug was a UTF-8/ANSI mismatch.
      * Color comes from Write-Host -ForegroundColor, NOT raw ANSI escapes,
        so it works even when virtual-terminal processing is off.
      * Output is sequential (top to bottom). No absolute cursor positioning,
        so log text can never overlap the animation. The only in-place trick
        is a single-line spinner using a carriage return.
#>
param(
    [string]$LogFile = "",
    [string]$AppDir  = ""
)

$ErrorActionPreference = "Continue"

# ------------------------------------------------------------
#  Resolve AppDir robustly.
#  Max.cmd passes -AppDir "C:\dev\Max\" but the trailing \" gets
#  mangled by cmd/PowerShell quoting into 'C:\dev\Max\ ' (stray
#  backslash + space). Clean it up, and fall back to the repo root
#  derived from this script's own location (scripts\ -> root).
# ------------------------------------------------------------
if ($AppDir) { $AppDir = $AppDir.Trim().TrimEnd('\', '"', ' ') }
if (-not $AppDir -or -not (Test-Path $AppDir)) {
    $AppDir = Split-Path -Parent $PSScriptRoot
}

# Use 127.0.0.1, NOT 'localhost': on Windows 'localhost' resolves to ::1 (IPv6)
# first, but the engine (uvicorn) binds only 127.0.0.1 (IPv4). A localhost
# request wastes ~2s failing over IPv6 before falling back to IPv4 — which
# blows the 2s health timeout and makes Leo think a healthy engine is down.
$HEALTH_URL   = "http://127.0.0.1:8001/health"
$MAX_ATTEMPTS = 3

try { $Host.UI.RawUI.WindowTitle = "LEO - SELF-DIAGNOSE MODE" } catch { }

# ============================================================
#  Output helpers
# ============================================================
function Say([string]$msg, [string]$color = "Red") {
    Write-Host "  $msg" -ForegroundColor $color
}

function Rule() {
    Write-Host ("  " + ("-" * 58)) -ForegroundColor DarkRed
}

function Show-Poodle([string]$mood = "work") {
    $eyes  = "o.o"
    $mouth = "^"
    $tag   = "Leo is on it..."
    $color = "Red"
    switch ($mood) {
        "alert" { $eyes = "O.O"; $tag = "Found something - let's fix it!" }
        "happy" { $eyes = "^.^"; $mouth = "v"; $tag = "woof! engine is back up!"; $color = "Green" }
        "sad"   { $eyes = "T.T"; $mouth = "_"; $tag = "still down... I tried my best." }
        "wait"  { $eyes = "-.-"; $tag = "waiting on you..." }
    }
    Write-Host ""
    Write-Host "     ,_     ,_"        -ForegroundColor $color
    Write-Host "    ( $eyes )   $tag"  -ForegroundColor $color
    Write-Host "     > $mouth <"       -ForegroundColor $color
    Write-Host "    (__)_(__)"         -ForegroundColor $color
    Write-Host ""
}

# ============================================================
#  Health check
# ============================================================
function Test-Health {
    try {
        $r = Invoke-WebRequest -Uri $HEALTH_URL -TimeoutSec 2 -ErrorAction Stop -UseBasicParsing
        return $r.StatusCode -eq 200
    } catch {
        return $false
    }
}

# ============================================================
#  Animated wait (single line, carriage-return spinner).
#  Returns $true if -Poll is set and the engine came up.
# ============================================================
function Wait-Leo([int]$durationMs, [string]$msg = "working", [bool]$poll = $false) {
    $sw     = [System.Diagnostics.Stopwatch]::StartNew()
    $frames = @(">(o.o)   ", " >(o.o)  ", "  >(o.o) ", "   >(o.o)", "  >(o.o) ", " >(o.o)  ")
    $i      = 0
    $pollT  = 0
    while ($sw.ElapsedMilliseconds -lt $durationMs) {
        $f = $frames[$i % $frames.Count]
        Write-Host ("`r  [$f] $msg          ") -NoNewline -ForegroundColor Red
        $i++
        if ($poll) {
            $pollT++
            if ($pollT -ge 5) {            # poll roughly every 500ms
                $pollT = 0
                if (Test-Health) {
                    Write-Host ("`r" + (" " * 70) + "`r") -NoNewline
                    return $true
                }
            }
        }
        Start-Sleep -Milliseconds 100
    }
    Write-Host ("`r" + (" " * 70) + "`r") -NoNewline   # erase the spinner line
    return $false
}

# ============================================================
#  Environment sniff
# ============================================================
function Invoke-EnvSniff {
    $issues = [System.Collections.Generic.List[string]]::new()

    # 1. venv
    $venvPy = Join-Path $AppDir "engine\.venv\Scripts\python.exe"
    if (-not (Test-Path $venvPy)) {
        $issues.Add("MISSING venv: engine\.venv not found")
        Say "[x] venv missing" "Red"
    } else {
        Say "[ok] venv found" "Green"
    }

    # 2. .env file
    $envFile = Join-Path $AppDir "engine\.env"
    if (-not (Test-Path $envFile)) {
        $issues.Add("MISSING .env: engine\.env not found (copy from .env.example)")
        Say "[x] .env missing" "Red"
    } else {
        Say "[ok] .env found" "Green"
    }

    # 3. ANTHROPIC_API_KEY
    $hasKey = $false
    if ($env:ANTHROPIC_API_KEY) {
        $hasKey = $true
        Say "[ok] ANTHROPIC_API_KEY set (env)" "Green"
    } elseif (Test-Path $envFile) {
        $envContent = Get-Content $envFile -Raw
        if ($envContent -match "ANTHROPIC_API_KEY\s*=\s*\S+") {
            $hasKey = $true
            Say "[ok] ANTHROPIC_API_KEY found in .env" "Green"
        }
    }
    if (-not $hasKey) {
        $issues.Add("MISSING ANTHROPIC_API_KEY - cloud diagnosis unavailable")
        Say "[!] ANTHROPIC_API_KEY not set" "Yellow"
    }

    # 4. Port 8001 busy but not answering
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $tcp.ConnectAsync("127.0.0.1", 8001).Wait(500) | Out-Null
        if ($tcp.Connected) {
            Say "[!] Port 8001 is in use but /health did not respond" "Yellow"
            $issues.Add("Port 8001 occupied but engine not responding")
        }
        $tcp.Close()
    } catch { }

    # 5. Ollama (local fallback) — 127.0.0.1, not localhost (see HEALTH_URL note)
    try {
        $null = Invoke-WebRequest -Uri "http://127.0.0.1:11434" -TimeoutSec 1 -ErrorAction Stop -UseBasicParsing
        Say "[ok] Ollama reachable (local fallback available)" "Green"
    } catch {
        Say "[!] Ollama unreachable (local fallback offline)" "Yellow"
        $issues.Add("Ollama not running - local diagnosis fallback unavailable")
    }

    # 6. Engine stderr log
    $stderrSummary = ""
    if ($LogFile -and (Test-Path $LogFile)) {
        $lines = Get-Content $LogFile -Tail 30
        $stderrSummary = $lines -join "`n"
        Say "[ok] Engine stderr log found ($($lines.Count) lines)" "Green"
    } else {
        Say "[!] No engine stderr log" "Yellow"
    }

    return @{ issues = $issues; stderrSummary = $stderrSummary; hasKey = $hasKey }
}

# ============================================================
#  Safely grab the tail of a (possibly short) string
# ============================================================
function Get-Tail([string]$text, [int]$count) {
    if (-not $text) { return "" }
    if ($text.Length -le $count) { return $text }
    return $text.Substring($text.Length - $count)
}

# ============================================================
#  Diagnosis (cloud -> local -> offline heuristics)
# ============================================================
function Invoke-Diagnosis([System.Collections.Generic.List[string]]$issues, [string]$stderr) {
    # --- Offline heuristics (always available) ---
    $heuristic = ""
    $stderrLow = if ($stderr) { $stderr.ToLower() } else { "" }

    if ($stderrLow -match "address already in use|port.*8001|bind.*8001") {
        $heuristic = "Port 8001 is already in use.`nFix: kill the process holding port 8001.`n  netstat -ano | findstr :8001`n  taskkill /PID <pid> /F"
    } elseif ($stderrLow -match "modulenotfounderror|no module named") {
        $heuristic = "Python module missing.`nFix: activate the venv and reinstall:`n  engine\.venv\Scripts\pip install -e engine"
    } elseif ($stderrLow -match "syntaxerror") {
        $heuristic = "Python syntax error in the engine code.`nFix: check the traceback above for the offending file and line."
    } elseif ($stderrLow -match "permission denied|access is denied") {
        $heuristic = "Permission denied.`nFix: run Max.cmd as Administrator or check file permissions."
    } elseif ($issues -match "MISSING venv") {
        $heuristic = "Virtual environment not found.`nFix: run in the repo root:`n  cd engine; python -m venv .venv; .venv\Scripts\pip install -e ."
    } elseif ($issues -match "MISSING .env") {
        $heuristic = ".env file missing.`nFix: copy engine\.env.example to engine\.env and fill in your API keys."
    }

    # --- Try cloud Claude ---
    $cloudKey = $env:ANTHROPIC_API_KEY
    if (-not $cloudKey -and (Test-Path (Join-Path $AppDir "engine\.env"))) {
        $envContent = Get-Content (Join-Path $AppDir "engine\.env") -Raw
        if ($envContent -match "ANTHROPIC_API_KEY\s*=\s*(\S+)") {
            $cloudKey = $Matches[1]
        }
    }

    if ($cloudKey -and ($cloudKey.Length -gt 10)) {
        $diagnosis = Invoke-ClaudeDiagnosis -ApiKey $cloudKey -Issues $issues -Stderr $stderr
        if ($diagnosis) { return $diagnosis }
    }

    # --- Try local Ollama ---
    $localDiag = Invoke-OllamaDiagnosis -Issues $issues -Stderr $stderr
    if ($localDiag) { return $localDiag }

    # --- Offline fallback ---
    if ($heuristic) { return $heuristic }
    return "Could not reach any AI model for diagnosis.`nManual check:`n  1. Verify engine\.venv exists`n  2. Verify engine\.env has required keys`n  3. Check port 8001 is free`n  4. Run: cd engine; .venv\Scripts\python -m uvicorn max_engine.main:app --port 8001"
}

function Invoke-ClaudeDiagnosis([string]$ApiKey, [System.Collections.Generic.List[string]]$Issues, [string]$Stderr) {
    try {
        $issueStr  = if ($Issues.Count) { $Issues -join "`n" } else { "None detected" }
        $stderrStr = Get-Tail $Stderr 1500
        if (-not $stderrStr) { $stderrStr = "(no log)" }
        # Redact secrets before sending
        $stderrStr = $stderrStr -replace "sk-ant-[a-zA-Z0-9\-_]+", "[REDACTED]"
        $stderrStr = $stderrStr -replace "[A-Z_]{8,}=[^\s]{6,}", "[REDACTED]"

        $prompt = "You are Leo, Max's boot-rescue assistant. Max's Python engine (FastAPI on port 8001) failed to start.`n`nISSUES DETECTED:`n$issueStr`n`nENGINE STDERR (last 1500 chars):`n$stderrStr`n`nProvide: (1) root cause in 1-2 sentences, (2) the exact fix command(s) to run, (3) how to verify it worked. Be concise and direct. Plain text only, no markdown."

        $body = @{
            model      = "claude-haiku-4-5-20251001"
            max_tokens = 512
            messages   = @(@{ role = "user"; content = $prompt })
        } | ConvertTo-Json -Depth 5

        $resp = Invoke-RestMethod -Uri "https://api.anthropic.com/v1/messages" `
            -Method POST `
            -Headers @{
                "x-api-key"         = $ApiKey
                "anthropic-version" = "2023-06-01"
                "content-type"      = "application/json"
            } `
            -Body $body `
            -ErrorAction Stop

        return $resp.content[0].text
    } catch {
        return $null
    }
}

function Invoke-OllamaDiagnosis([System.Collections.Generic.List[string]]$Issues, [string]$Stderr) {
    try {
        $issueStr = if ($Issues.Count) { $Issues -join "`n" } else { "None detected" }
        $tail     = Get-Tail $Stderr 500
        $prompt   = "Max's Python engine failed to start. Issues: $issueStr. Stderr: $tail. Give a 2-line diagnosis and fix. Plain text only."

        $body = @{
            model  = "qwen2.5-coder:3b"
            prompt = $prompt
            stream = $false
        } | ConvertTo-Json

        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/generate" `
            -Method POST -Body $body -ErrorAction Stop -TimeoutSec 15
        return $resp.response
    } catch {
        return $null
    }
}

# ============================================================
#  Write to logbook
# ============================================================
function Write-Logbook([string]$status, [string]$rootCause, [string]$fix) {
    $logbook = Join-Path $AppDir "selfdiagnosefixes.md"
    $ts      = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mmZ")
    $entry   = "`n## $ts - Boot failure (Leo)`n- **Status:** $status`n- **Root cause:** $rootCause`n- **Fix:** $fix`n"
    try { Add-Content -Path $logbook -Value $entry -Encoding UTF8 } catch { }
}

# ============================================================
#  MAIN
# ============================================================
Clear-Host
Write-Host ""
Write-Host ("  == LEO - SELF-DIAGNOSE MODE " + ("=" * 30)) -ForegroundColor Red
Write-Host ""

# --- Fast check: already up? ---
Say "Checking if engine is already up..." "DarkRed"
if (Test-Health) {
    Show-Poodle "happy"
    Say "Engine is already running! My job here is done." "Green"
    Write-Host ""
    exit 0
}

Show-Poodle "work"
Say "LEO - Boot Rescue Console" "Red"
Say "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" "DarkRed"
Rule

$attempt       = 0
$lastDiagnosis = ""
$lastFix       = ""

while ($attempt -lt $MAX_ATTEMPTS) {
    $attempt++

    # ---- PHASE 1: give the engine a moment ----
    $up = Wait-Leo 4000 "Waiting for engine to start (attempt $attempt of $MAX_ATTEMPTS)" $true
    if ($up) { break }

    # ---- PHASE 2: env sniff ----
    Write-Host ""
    Say "[ Attempt $attempt ] Sniffing environment..." "Red"
    $sniff = Invoke-EnvSniff

    # ---- PHASE 3: diagnosis ----
    Write-Host ""
    $null = Wait-Leo 800 "Diagnosing root cause"
    $diagnosis = Invoke-Diagnosis $sniff.issues $sniff.stderrSummary

    # ---- show result ----
    Show-Poodle "alert"
    Say ">> DIAGNOSIS (attempt $attempt):" "Red"
    $diagLines = $diagnosis -split "`n"
    foreach ($dl in $diagLines) { Say "   $dl" "Red" }
    $lastDiagnosis = $diagLines[0]
    $lastFix       = ($diagLines | Select-Object -Skip 1) -join " "
    Write-Logbook "proposed" $lastDiagnosis $lastFix
    Rule

    # ---- MENU ----
    Say "[R] Retry (relaunch Max)   [D] Diagnose again   [S] Open shell   [Q] Quit" "Yellow"
    Write-Host "  > " -ForegroundColor Red -NoNewline
    $key = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown").Character.ToString().ToUpper()
    Write-Host $key -ForegroundColor Red

    if ($key -eq "Q") {
        Write-Host ""
        Say "Leo: Signing off. Good luck!" "Red"
        exit 0
    }
    elseif ($key -eq "S") {
        Say "Leo: Opening a shell for you. Type 'exit' to return." "Red"
        Start-Process powershell -Wait
    }
    elseif ($key -eq "D") {
        continue   # loop again for re-diagnosis
    }
    elseif ($key -eq "R") {
        $maxExe = Join-Path $AppDir "app\src-tauri\target\release\Max.exe"
        if (Test-Path $maxExe) {
            Say "Relaunching Max.exe..." "Red"
            Start-Process $maxExe
        } else {
            Say "[!] Max.exe not found - try running Max.cmd instead" "Yellow"
        }
        $up = Wait-Leo 30000 "Waiting for engine to come up" $true
        if ($up) { break }
        Say "Engine still not responding after 30s" "Red"
    }
}

# ============================================================
#  FINALE
# ============================================================
if (Test-Health) {
    Show-Poodle "happy"
    Say "Engine is healthy at $HEALTH_URL" "Green"
    Write-Host ""
    Write-Logbook "verified" $lastDiagnosis "Engine now healthy"
} else {
    Show-Poodle "sad"
    Say "The engine is still down. Check the diagnosis above and try manually." "Red"
    Write-Host ""
}
