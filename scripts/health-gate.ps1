<#
.SYNOPSIS
    Max health gate. Polls the engine after launch; if it never comes up, opens
    Leo's boot-rescue console. LAN-aware: when "Share on LAN" is enabled the
    engine binds 0.0.0.0:<lan_port> over HTTPS (NOT 127.0.0.1:8001/http), so a
    plain HTTP check on 8001 would always fail and trip Leo even on a healthy
    engine. In that case we use a TCP port-open check (matching the Rust side,
    which can't do a raw HTTP health check against the self-signed TLS port).

.NOTES
    PURE ASCII, no fancy output — this runs minimized in the background.
#>
param(
    [string]$AppDir = "",
    [string]$LeoScript = "",
    [int]$TimeoutSeconds = 60
)

$ErrorActionPreference = "Continue"
if ($AppDir) { $AppDir = $AppDir.Trim().TrimEnd('\', '"', ' ') }
if (-not $AppDir -or -not (Test-Path $AppDir)) { $AppDir = Split-Path -Parent $PSScriptRoot }
if (-not $LeoScript) { $LeoScript = Join-Path $AppDir "scripts\leo.ps1" }

# ---- Resolve where the engine should be listening, from .maxconfig.json ----
$port = 8001
$tls  = $false
$cfg  = Join-Path $AppDir "engine\.maxconfig.json"
if (Test-Path $cfg) {
    try {
        $j = Get-Content $cfg -Raw | ConvertFrom-Json
        if ($j.lan -and $j.lan.lan_enabled) {
            if ($j.lan.lan_port) { $port = [int]$j.lan.lan_port }
            $cp = [string]$j.lan.cert_path
            $kp = [string]$j.lan.key_path
            if ($cp -and $kp -and (Test-Path $cp) -and (Test-Path $kp)) { $tls = $true }
        }
    } catch { }
}

# ---- Is the engine up? ----
# Use 127.0.0.1 (not 'localhost'): uvicorn binds IPv4; localhost prefers ::1 and
# wastes ~2s failing over, which can blow the per-attempt timeout.
function Test-Up {
    if ($tls) {
        # HTTPS / LAN mode: a successful TCP connect to the port is "up".
        try {
            $c = New-Object System.Net.Sockets.TcpClient
            $c.ConnectAsync("127.0.0.1", $port).Wait(2000) | Out-Null
            $ok = $c.Connected
            $c.Close()
            return $ok
        } catch { return $false }
    }
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/health" -TimeoutSec 3 `
            -UseBasicParsing -ErrorAction Stop
        return $r.StatusCode -eq 200
    } catch { return $false }
}

$ok = $false
for ($i = 0; $i -lt $TimeoutSeconds; $i++) {
    if (Test-Up) { $ok = $true; break }
    Start-Sleep -Seconds 1
}

if (-not $ok) {
    Start-Process powershell -ArgumentList @(
        "-NoExit", "-ExecutionPolicy", "Bypass", "-File", $LeoScript, "-AppDir", $AppDir
    ) -WindowStyle Normal
}
