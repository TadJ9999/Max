<#
.SYNOPSIS
  End-to-end smoke test for the Max engine.

.DESCRIPTION
  Boots the engine (optional) and exercises the real HTTP/SSE surface:

    /health                 always
    /parse                  always (routing only, no inference)
    /v1/chat/completions    needs a running Ollama with -Model pulled
    /command                needs a running Ollama (default local model)

  Stage A checks (/health, /parse) need no model. The inference checks report
  SKIP (clean backend error) rather than FAIL when Ollama isn't reachable, so
  this script is useful both before and after the local models are installed.

.PARAMETER Start
  Launch the engine via uvicorn before testing and stop it afterward. Uses
  engine/.venv if present, else system `python`.

.EXAMPLE
  ./scripts/smoke.ps1 -Start
  ./scripts/smoke.ps1 -BaseUrl http://127.0.0.1:8000 -Model qwen2.5-coder:3b
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$Model = "qwen2.5-coder:3b",
    [string]$Provider = "ollama",
    [switch]$Start,
    [int]$StartTimeoutSec = 30
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$engineDir = Join-Path $repo "engine"

$results = [System.Collections.Generic.List[object]]::new()
function Add-Result($name, $status, $detail) {
    $results.Add([pscustomobject]@{ Check = $name; Status = $status; Detail = $detail })
}

# Read a streamed SSE response and pull out concatenated token text or an error.
function Invoke-Sse($url, $body) {
    $r = Invoke-WebRequest -Uri $url -Method Post -ContentType "application/json" `
        -Body $body -UseBasicParsing -TimeoutSec 60
    $text = ""
    $err = $null
    foreach ($line in ($r.Content -split "`n")) {
        $line = $line.Trim()
        if (-not $line.StartsWith("data:")) { continue }
        $data = $line.Substring(5).Trim()
        if ($data -eq "[DONE]" -or $data -eq "") { continue }
        try { $obj = $data | ConvertFrom-Json } catch { continue }
        if ($obj.error) { $err = $obj.error.message }
        elseif ($obj.choices) { $text += [string]$obj.choices[0].delta.content }
    }
    return @{ tokens = $text; error = $err }
}

$proc = $null
if ($Start) {
    $py = Join-Path $engineDir ".venv/Scripts/python.exe"
    if (-not (Test-Path $py)) { $py = "python" }
    Write-Host "Starting engine: $py -m uvicorn max_engine.main:app" -ForegroundColor Cyan
    $proc = Start-Process -FilePath $py `
        -ArgumentList @("-m", "uvicorn", "max_engine.main:app", "--host", "127.0.0.1", "--port", "8000") `
        -WorkingDirectory $engineDir -PassThru -WindowStyle Hidden
}

try {
    # --- /health (also our readiness gate) ---
    $healthy = $false
    $h = $null
    $deadline = (Get-Date).AddSeconds($StartTimeoutSec)
    do {
        try {
            $h = Invoke-RestMethod -Uri "$BaseUrl/health" -TimeoutSec 3
            if ($h.status -eq "ok") { $healthy = $true; break }
        } catch { Start-Sleep -Milliseconds 500 }
    } while ((Get-Date) -lt $deadline)

    if ($healthy) {
        Add-Result "/health" "PASS" "version $($h.version)"
    } else {
        Add-Result "/health" "FAIL" "engine not reachable at $BaseUrl"
        $results | Format-Table -AutoSize | Out-Host
        return
    }

    # --- /parse (cloud-sigil routing, no inference) ---
    try {
        $body = @{ text = "!. add a retry decorator ." } | ConvertTo-Json
        $p = Invoke-RestMethod -Uri "$BaseUrl/parse" -Method Post -ContentType "application/json" -Body $body
        if ($p.route.is_cloud -and $p.route.provider -eq "claude") {
            Add-Result "/parse" "PASS" "!. -> $($p.route.provider)/$($p.route.model) (cloud)"
        } else {
            Add-Result "/parse" "FAIL" "unexpected route: $($p.route | ConvertTo-Json -Compress)"
        }
    } catch { Add-Result "/parse" "FAIL" $_.Exception.Message }

    # --- /v1/chat/completions (real local inference; needs Ollama) ---
    try {
        $body = @{
            model    = $Model; provider = $Provider; stream = $true
            messages = @(@{ role = "user"; content = "Reply with the single word: pong" })
        } | ConvertTo-Json -Depth 5
        $res = Invoke-Sse "$BaseUrl/v1/chat/completions" $body
        if ($res.tokens) { Add-Result "/v1/chat/completions" "PASS" "streamed: '$($res.tokens.Trim())'" }
        elseif ($res.error) { Add-Result "/v1/chat/completions" "SKIP" "no backend: $($res.error)" }
        else { Add-Result "/v1/chat/completions" "WARN" "no tokens, no error" }
    } catch { Add-Result "/v1/chat/completions" "FAIL" $_.Exception.Message }

    # --- /command (full DSL path; needs Ollama for the default local model) ---
    try {
        $body = @{ text = ". print hello world in python ." } | ConvertTo-Json
        $res = Invoke-Sse "$BaseUrl/command" $body
        if ($res.tokens) { Add-Result "/command" "PASS" "streamed $($res.tokens.Length) chars" }
        elseif ($res.error) { Add-Result "/command" "SKIP" "no backend: $($res.error)" }
        else { Add-Result "/command" "WARN" "no tokens, no error" }
    } catch { Add-Result "/command" "FAIL" $_.Exception.Message }
}
finally {
    if ($proc) {
        Write-Host "Stopping engine (pid $($proc.Id))..." -ForegroundColor Cyan
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ""
$results | Format-Table -AutoSize | Out-Host

$failed = @($results | Where-Object { $_.Status -eq "FAIL" }).Count
if ($failed -gt 0) { exit 1 } else { exit 0 }
