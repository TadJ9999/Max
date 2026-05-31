<#
.SYNOPSIS
    Leo  - Max's boot-time rescue terminal. 🐩
    Runs when the engine fails to start. All output is RED.
    Leo animates left and right across the terminal and reacts to progress.
#>
param(
    [string]$LogFile = "",
    [string]$AppDir  = ""
)

# ============================================================
#  Setup
# ============================================================
$ESC       = [char]27
$RED       = "$ESC[91m"   # bright red
$YELLOW    = "$ESC[93m"
$GREEN     = "$ESC[92m"
$CYAN      = "$ESC[96m"
$BOLD      = "$ESC[1m"
$DIM       = "$ESC[2m"
$RESET     = "$ESC[0m"
$CLEARLINE = "$ESC[2K"
$HIDECUR   = "$ESC[?25l"
$SHOWCUR   = "$ESC[?25h"

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = "LEO · SELF-DIAGNOSE MODE 🐩"
# Use ANSI escape to hide cursor
Write-Host "$HIDECUR" -NoNewline

# Detect terminal width
$W = [Console]::WindowWidth
if ($W -lt 60) { $W = 80 }

$HEALTH_URL   = "http://localhost:8001/health"
$MAX_ATTEMPTS = 3
$STAGE_TOP    = 2   # Leo lives on rows 2-5

# ============================================================
#  Leo sprite library  - all frames are exactly 4 lines of $LEO_W chars
# ============================================================
$LEO_W = 14   # sprite column width (pad to this)

function Pad([string]$s) {
    if ($s.Length -ge $LEO_W) { return $s.Substring(0, $LEO_W) }
    return $s.PadRight($LEO_W)
}

# Running right  - 2 alternating stride frames
$RUN_R = @(
    @((Pad "  ,ε=ε     "), (Pad " (^ω^)->   "), (Pad "  /\\      "), (Pad " d    d    ")),
    @((Pad "  ,ε=ε     "), (Pad " (^ω^)->   "), (Pad "   //\\    "), (Pad "  b   b    "))
)
# Running left
$RUN_L = @(
    @((Pad "     ε=ε,  "), (Pad "  <-(^ω^)  "), (Pad "    /\\    "), (Pad "   d    d  ")),
    @((Pad "     ε=ε,  "), (Pad "  <-(^ω^)  "), (Pad "   //\\    "), (Pad "   b    b  "))
)
# Sniffing (env check)
$SNIFF = @(
    @((Pad "  ,ε=ε     "), (Pad " (ó_ò)~~>  "), (Pad "  /\\      "), (Pad " d    d    ")),
    @((Pad "  ,ε=ε     "), (Pad " (ó_ò)~>   "), (Pad "  /\\      "), (Pad " d    d    "))
)
# Thinking / diagnosing
$THINK = @(
    @((Pad "  ,ε=ε  ?  "), (Pad " (?_?)     "), (Pad "  /||     "), (Pad " d    d    ")),
    @((Pad "  ,ε=ε ??  "), (Pad " (?_?)     "), (Pad "  /||     "), (Pad " d    d    "))
)
# Alert  - found an issue!
$ALERT = @(
    @((Pad " !,ε=ε!    "), (Pad " (!ω!)!!   "), (Pad "  /\\      "), (Pad " d    d    ")),
    @((Pad "  ,ε=ε!!   "), (Pad " (!ω!) !   "), (Pad "  /\\      "), (Pad " d    d    "))
)
# Celebrate  - engine is back!
$CHEER = @(
    @((Pad "\\,ε=ε/     "), (Pad "\\(^ω^)/   "), (Pad "   ||     "), (Pad "  d  d     ")),
    @((Pad " ,ε=ε,     "), (Pad " (^ω^)^   "), (Pad "  /||     "), (Pad "  d  d     "))
)
# Sitting and waiting
$WAIT = @(
    @((Pad "  ,ε=ε     "), (Pad " (- ω -)   "), (Pad "  /||     "), (Pad "  ~~~~     ")),
    @((Pad "  ,ε=ε     "), (Pad " (- ω -)zzz"), (Pad "  /||     "), (Pad "  ~~~~     "))
)
# Sad (too many failures)
$SAD = @(
    @((Pad "  ,ε=ε     "), (Pad " (;_;)     "), (Pad "  /||     "), (Pad " d    d    ")),
    @((Pad "  ,ε=ε..   "), (Pad " (;_;)     "), (Pad "  /||     "), (Pad " d    d    "))
)

# ============================================================
#  State machine
# ============================================================
$global:LeoState  = "run_r"   # run_r | run_l | sniff | think | alert | cheer | wait | sad
$global:StatusMsg = "Checking if engine is already up..."
$global:LogLines  = [System.Collections.Generic.List[string]]::new()

# ============================================================
#  Draw helpers (ANSI cursor positioning)
# ============================================================
function Goto([int]$row, [int]$col) {
    Write-Host "$ESC[$($row+1);$($col+1)H" -NoNewline
}

function ClearRow([int]$row) {
    Goto $row 0
    Write-Host "$CLEARLINE" -NoNewline
}

function DrawHeader {
    ClearRow 0
    $title = " LEO · SELF-DIAGNOSE MODE "
    $bar   = "═" * [Math]::Max(0, $W - $title.Length - 4)
    Goto 0 0
    Write-Host "${RED}${BOLD}══${title}${bar}══${RESET}" -NoNewline
    ClearRow 1
}

function DrawStage([int]$x, [string[][]]$sprite, [int]$frame) {
    for ($line = 0; $line -lt 4; $line++) {
        ClearRow ($STAGE_TOP + $line)
        Goto ($STAGE_TOP + $line) $x
        Write-Host "${RED}$($sprite[$frame][$line])${RESET}" -NoNewline
    }
}

function DrawStatus([string]$msg) {
    ClearRow 6
    Goto 6 0
    Write-Host "${RED}${DIM}  $msg${RESET}" -NoNewline
    ClearRow 7
    Goto 7 0
    Write-Host "${RED}$('-' * ($W - 1))${RESET}" -NoNewline
}

function LogLine([string]$line) {
    $global:LogLines.Add($line)
    # Move cursor below separator (row 8+) and print
    $logRow = 8 + ($global:LogLines.Count - 1)
    Goto $logRow 0
    Write-Host "${RED}  $line${RESET}"
    # Restore cursor to safe position below log
    Goto ($logRow + 1) 0
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
#  Environment sniff
# ============================================================
function Invoke-EnvSniff {
    $global:LeoState  = "sniff"
    $global:StatusMsg = "Sniffing environment..."
    $issues = [System.Collections.Generic.List[string]]::new()

    # 1. venv
    $venvPy = Join-Path $AppDir "engine\.venv\Scripts\python.exe"
    if (-not (Test-Path $venvPy)) {
        $issues.Add("MISSING venv: engine\.venv not found")
        LogLine "✗ venv missing"
    } else {
        LogLine "OK venv found"
    }

    # 2. .env file
    $envFile = Join-Path $AppDir "engine\.env"
    if (-not (Test-Path $envFile)) {
        $issues.Add("MISSING .env: engine\.env not found (copy from .env.example)")
        LogLine "✗ .env missing"
    } else {
        LogLine "OK .env found"
    }

    # 3. ANTHROPIC_API_KEY
    $hasKey = $false
    if ($env:ANTHROPIC_API_KEY) {
        $hasKey = $true
        LogLine "OK ANTHROPIC_API_KEY set (env)"
    } elseif (Test-Path $envFile) {
        $envContent = Get-Content $envFile -Raw
        if ($envContent -match "ANTHROPIC_API_KEY\s*=\s*\S+") {
            $hasKey = $true
            LogLine "OK ANTHROPIC_API_KEY found in .env"
        }
    }
    if (-not $hasKey) {
        $issues.Add("MISSING ANTHROPIC_API_KEY  - cloud diagnosis unavailable")
        LogLine "⚠ ANTHROPIC_API_KEY not set"
    }

    # 4. Port 8001 busy
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $tcp.ConnectAsync("127.0.0.1", 8001).Wait(500) | Out-Null
        if ($tcp.Connected) {
            LogLine "⚠ Port 8001 is in use but /health didn't respond"
            $issues.Add("Port 8001 occupied but engine not responding")
        }
        $tcp.Close()
    } catch { }

    # 5. Ollama
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:11434" -TimeoutSec 1 -ErrorAction Stop -UseBasicParsing
        LogLine "OK Ollama reachable (local fallback available)"
    } catch {
        LogLine "⚠ Ollama unreachable (local fallback offline)"
        $issues.Add("Ollama not running  - local diagnosis fallback unavailable")
    }

    # 6. Engine stderr log
    $stderrSummary = ""
    if ($LogFile -and (Test-Path $LogFile)) {
        $lines = Get-Content $LogFile -Tail 30
        $stderrSummary = $lines -join "`n"
        LogLine "OK Engine stderr log found ($($lines.Count) lines)"
    } else {
        LogLine "⚠ No engine stderr log"
    }

    return @{ issues = $issues; stderrSummary = $stderrSummary; hasKey = $hasKey }
}

# ============================================================
#  Diagnosis (cloud -> local -> offline heuristics)
# ============================================================
function Invoke-Diagnosis([System.Collections.Generic.List[string]]$issues, [string]$stderr) {
    $global:LeoState  = "think"
    $global:StatusMsg = "Diagnosing..."

    # --- Offline heuristics (always available) ---
    $heuristic = ""
    $stderrLow = $stderr.ToLower()

    if ($stderrLow -match "address already in use|port.*8001|bind.*8001") {
        $heuristic = "Port 8001 is already in use.`nFix: kill the process holding port 8001.`n  netstat -ano | findstr :8001`n  taskkill /PID <pid> /F"
    } elseif ($stderrLow -match "modulenotfounderror|no module named") {
        $heuristic = "Python module missing.`nFix: activate the venv and reinstall:`n  engine\.venv\Scripts\pip install -e engine"
    } elseif ($stderrLow -match "syntaxerror") {
        $heuristic = "Python syntax error in the engine code.`nFix: check the traceback above for the offending file and line."
    } elseif ($stderrLow -match "permission denied|access is denied") {
        $heuristic = "Permission denied.`nFix: run Max.cmd as Administrator or check file permissions."
    } elseif ($issues -match "MISSING venv") {
        $heuristic = "Virtual environment not found.`nFix: run in the repo root:`n  cd engine && python -m venv .venv && .venv\Scripts\pip install -e ."
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
        $global:StatusMsg = "Asking Claude for help..."
        $diagnosis = Invoke-ClaudeDiagnosis -ApiKey $cloudKey -Issues $issues -Stderr $stderr
        if ($diagnosis) { return $diagnosis }
    }

    # --- Try local Ollama ---
    $global:StatusMsg = "Asking local model..."
    $localDiag = Invoke-OllamaDiagnosis -Issues $issues -Stderr $stderr
    if ($localDiag) { return $localDiag }

    # --- Offline fallback ---
    if ($heuristic) { return $heuristic }
    return "Could not connect to any AI model for diagnosis.`nManual check:`n  1. Verify engine\.venv exists`n  2. Verify engine\.env has required keys`n  3. Check port 8001 is free`n  4. Run: cd engine && .venv\Scripts\python -m uvicorn max_engine.main:app --port 8001"
}

function Invoke-ClaudeDiagnosis([string]$ApiKey, [System.Collections.Generic.List[string]]$Issues, [string]$Stderr) {
    try {
        $issueStr  = if ($Issues.Count) { $Issues -join "`n" } else { "None detected" }
        $stderrStr = if ($Stderr) { $Stderr[-1500..-1] -join "" } else { "(no log)" }
        # Redact key from stderr before sending
        $stderrStr = $stderrStr -replace "sk-ant-[a-zA-Z0-9\-_]+", "[REDACTED]"
        $stderrStr = $stderrStr -replace "[A-Z_]{8,}=[^\s]{6,}", "[REDACTED]"

        $prompt = "You are Leo, Max's boot-rescue assistant. Max's Python engine (FastAPI on port 8001) failed to start.`n`nISSUES DETECTED:`n$issueStr`n`nENGINE STDERR (last 1500 chars):`n$stderrStr`n`nProvide: (1) root cause in 1-2 sentences, (2) the exact fix command(s) to run, (3) how to verify it worked. Be concise and direct."

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
        $prompt   = "Max's Python engine failed to start. Issues: $issueStr. Stderr: $($Stderr[-500..-1] -join ''). Give a 2-line diagnosis and fix."

        $body = @{
            model  = "qwen2.5-coder:3b"
            prompt = $prompt
            stream = $false
        } | ConvertTo-Json

        $resp = Invoke-RestMethod -Uri "http://localhost:11434/api/generate" `
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
    $entry   = "`n## $ts  - Boot failure (Leo)`n- **Status:** $status`n- **Root cause:** $rootCause`n- **Fix:** $fix`n"
    try { Add-Content -Path $logbook -Value $entry -Encoding UTF8 } catch { }
}

# ============================================================
#  Animation loop  - runs Leo during a timed wait
# ============================================================
function Run-Animation([int]$durationMs, [bool]$poll = $false) {
    $sw     = [System.Diagnostics.Stopwatch]::StartNew()
    $leoX   = 0
    $dir    = 1
    $frame  = 0
    $maxX   = $W - $LEO_W - 4
    if ($maxX -lt 0) { $maxX = 0 }
    $pollT  = 0

    while ($sw.ElapsedMilliseconds -lt $durationMs) {
        # Pick sprite based on current state
        $sprite = switch ($global:LeoState) {
            "sniff"  { $SNIFF[$frame % 2] }
            "think"  { $THINK[$frame % 2] }
            "alert"  { $ALERT[$frame % 2] }
            "cheer"  { $CHEER[$frame % 2] }
            "wait"   { $WAIT[$frame % 2]  }
            "sad"    { $SAD[$frame % 2]   }
            "run_l"  { $RUN_L[$frame % 2] }
            default  { $RUN_R[$frame % 2] }
        }

        DrawStage $leoX $sprite $frame
        DrawStatus $global:StatusMsg

        # Move Leo (only when running)
        if ($global:LeoState -in @("run_r","run_l","sniff")) {
            $leoX += $dir * 3
            if ($leoX -ge $maxX) { $leoX = $maxX; $dir = -1; $global:LeoState = "run_l" }
            if ($leoX -le 0)     { $leoX = 0;     $dir = 1;  $global:LeoState = "run_r" }
        }

        $frame++

        # Optional health poll every 3 seconds
        if ($poll) {
            $pollT++
            if ($pollT -ge 30) {
                $pollT = 0
                if (Test-Health) { return $true }
            }
        }

        Start-Sleep -Milliseconds 100
    }
    return $false
}

# ============================================================
#  MAIN
# ============================================================
Clear-Host
DrawHeader

# --- Fast check: already up? ---
$global:StatusMsg = "Checking if engine is already up..."
if (Test-Health) {
    $global:LeoState = "cheer"
    DrawStage (($W / 2) - 7) $CHEER[0] 0
    DrawStatus "Engine is already up! Nothing to do."
    Start-Sleep -Milliseconds 1500
    Write-Host ""
    Goto 9 0
    Write-Host "${GREEN}${BOLD}  Leo: Engine is already running! My job here is done. ♥${RESET}"
    Write-Host ""
    Write-Host "${GREEN}        //\\__/\\\\     ${RESET}"
    Write-Host "${GREEN}       ( ^ ω ^ )  woof!${RESET}"
    Write-Host "${GREEN}        >  🐾  <        ${RESET}"
    Write-Host ""
    Write-Host "$SHOWCUR"
    exit 0
}

# --- Initial run animation + log header ---
LogLine "LEO v1 · Boot Rescue Console"
LogLine "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') UTC"
LogLine "---------------------------------"

$attempt = 0
$diagnosed = $false
$lastDiagnosis = ""
$lastFix = ""

while ($attempt -lt $MAX_ATTEMPTS) {
    $attempt++

    # ---- PHASE 1: wait a moment with Leo running ----
    $global:LeoState  = "run_r"
    $global:StatusMsg = "Waiting for engine to start (attempt $attempt of $MAX_ATTEMPTS)..."
    $up = Run-Animation 4000 $true
    if ($up) { break }

    # ---- PHASE 2: env sniff ----
    LogLine ""
    LogLine "[ Attempt $attempt ] Sniffing environment..."
    $global:LeoState = "sniff"
    $sniff = Invoke-EnvSniff
    Run-Animation 1000

    # ---- PHASE 3: diagnosis ----
    $global:LeoState  = "think"
    $global:StatusMsg = "Diagnosing root cause..."
    Run-Animation 500
    $diagnosis = Invoke-Diagnosis $sniff.issues $sniff.stderrSummary
    $diagnosed = $true

    # ---- show alert ----
    $global:LeoState  = "alert"
    $global:StatusMsg = "Found something  - let's fix it!"
    Run-Animation 1200

    # ---- print diagnosis ----
    LogLine ""
    LogLine "◆ DIAGNOSIS (attempt $attempt):"
    $diagnosis -split "`n" | ForEach-Object { LogLine "  $_" }
    $lastDiagnosis = ($diagnosis -split "`n")[0]
    $lastFix       = ($diagnosis -split "`n" | Select-Object -Skip 1) -join " "

    # Write to logbook
    Write-Logbook "proposed" $lastDiagnosis $lastFix

    # ---- MENU ----
    $global:LeoState  = "wait"
    $global:StatusMsg = "[R] Retry (relaunch Max)   [D] Diagnose again   [S] Open shell   [Q] Quit"
    DrawStage (($W / 2) - 7) $WAIT[0] 0
    DrawStatus $global:StatusMsg

    Write-Host "$SHOWCUR" -NoNewline
    Goto 22 0
    Write-Host "${RED}${BOLD}  > ${RESET}" -NoNewline
    $key = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown").Character.ToString().ToUpper()
    Write-Host "$HIDECUR" -NoNewline

    if ($key -eq "Q") {
        Goto 23 0
        Write-Host "${RED}  Leo: Signing off. Good luck! ♥${RESET}"
        Write-Host "$SHOWCUR"
        exit 0
    }
    elseif ($key -eq "S") {
        Write-Host "$SHOWCUR"
        Write-Host "${RED}  Leo: Opening a shell for you. Type 'exit' to return.${RESET}"
        Start-Process powershell -Wait
        Write-Host "$HIDECUR"
    }
    elseif ($key -eq "D") {
        # Loop again for re-diagnosis
        continue
    }
    elseif ($key -eq "R") {
        # Relaunch Max.exe
        $maxExe = Join-Path $AppDir "app\src-tauri\target\release\Max.exe"
        if (Test-Path $maxExe) {
            LogLine "Relaunching Max.exe..."
            Start-Process $maxExe
        } else {
            LogLine "⚠ Max.exe not found  - try running Max.cmd instead"
        }

        # Poll health for up to 30 seconds
        $global:LeoState  = "run_r"
        $global:StatusMsg = "Waiting for engine to come up..."
        LogLine "Polling /health..."
        $up = Run-Animation 30000 $true
        if ($up) { break }
        LogLine "Engine still not responding after 30s"
    }
}

# ============================================================
#  FINALE
# ============================================================
if (Test-Health) {
    $global:LeoState = "cheer"
    DrawStage (($W / 2) - 7) $CHEER[0] 0
    Run-Animation 1500

    Write-Host ""
    Goto ([Math]::Max(9, $global:LogLines.Count + 10)) 0
    Write-Host ""
    Write-Host "${GREEN}${BOLD}  Leo: My job is done! ♥${RESET}"
    Write-Host ""
    Write-Host "${GREEN}        //\\__/\\\\      ${RESET}"
    Write-Host "${GREEN}       ( ^ ω ^ )  woof! ${RESET}"
    Write-Host "${GREEN}        >  🐾  <         ${RESET}"
    Write-Host "${GREEN}       /  curly  \\       ${RESET}"
    Write-Host "${GREEN}      (__/    \\__)        ${RESET}"
    Write-Host ""
    Write-Host "${GREEN}  Engine is healthy at $HEALTH_URL${RESET}"
    Write-Host ""
    Write-Logbook "verified" $lastDiagnosis "Engine now healthy"
} else {
    $global:LeoState = "sad"
    DrawStage (($W / 2) - 7) $SAD[0] 0
    Run-Animation 1000

    Write-Host ""
    Goto ([Math]::Max(9, $global:LogLines.Count + 10)) 0
    Write-Host "${RED}${BOLD}  Leo: I tried my best... the engine is still down. 😢${RESET}"
    Write-Host "${RED}  Please check the diagnostics above and try manually.${RESET}"
    Write-Host ""
}

Write-Host "$SHOWCUR"
