use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::Duration;

use tauri::Manager;

#[cfg(desktop)]
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// Default engine port when LAN mode is off.
const ENGINE_PORT: u16 = 8001;
/// LAN/HTTPS port used when LAN mode is on.
const LAN_PORT: u16 = 8443;

/// Tor SOCKS5 proxy port (must match DarkNetConfig.socks_port in Python config.py).
const TOR_SOCKS_PORT: u16 = 9050;

/// Holds the FastAPI engine child process when *we* started it, so we can kill it
/// on shutdown. `None` when the engine was already running (started externally) —
/// in that case we leave it alone.
struct EngineProcess(Mutex<Option<Child>>);

/// Holds the Tor daemon child process when the user starts it from the Shadow Net tab.
/// `None` when Tor is not running (user-initiated, unlike the engine which auto-starts).
struct TorProcess(Mutex<Option<Child>>);

/// True only when the engine port is open AND /health returns HTTP 200.
fn engine_healthy() -> bool {
    use std::io::{Read, Write};
    let addr = format!("127.0.0.1:{ENGINE_PORT}");
    let Ok(addr) = addr.parse() else { return false };
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_millis(3000)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(3000)));
    if stream
        .write_all(b"GET /health HTTP/1.0\r\nHost: localhost\r\n\r\n")
        .is_err()
    {
        return false;
    }
    let mut buf = [0u8; 256];
    let n = stream.read(&mut buf).unwrap_or(0);
    String::from_utf8_lossy(&buf[..n]).contains("200")
}

/// Kill whatever process is holding a specific port (best-effort).
fn kill_port_owner_on(port: u16) {
    #[cfg(windows)]
    {
        let pattern = format!(":{port}");
        let Ok(out) = std::process::Command::new("cmd")
            .args(["/C", &format!("netstat -ano | findstr {pattern}")])
            .creation_flags(CREATE_NO_WINDOW)
            .output()
        else {
            return;
        };
        let text = String::from_utf8_lossy(&out.stdout);
        let pids: Vec<String> = text
            .lines()
            .filter_map(|line| line.trim().split_whitespace().last().map(|s| s.to_owned()))
            .filter(|s| !s.is_empty() && s.chars().all(|c| c.is_ascii_digit()) && s != "0")
            .collect();
        let mut seen = std::collections::HashSet::new();
        for pid in pids {
            if seen.insert(pid.clone()) {
                let mut kill = std::process::Command::new("taskkill");
                kill.args(["/T", "/F", "/PID", &pid])
                    .creation_flags(CREATE_NO_WINDOW);
                let _ = kill.status();
                println!("[engine] killed zombie process (pid {pid}) on :{port}");
            }
        }
        std::thread::sleep(Duration::from_millis(400));
    }
    #[cfg(not(windows))]
    {
        let _ = std::process::Command::new("sh")
            .args(["-c", &format!("fuser -k {port}/tcp 2>/dev/null || true")])
            .status();
        std::thread::sleep(Duration::from_millis(400));
    }
}

/// Check if a specific port is open (any address on localhost).
fn port_open(port: u16) -> bool {
    let addr = format!("127.0.0.1:{port}");
    addr.parse()
        .ok()
        .and_then(|a| TcpStream::connect_timeout(&a, Duration::from_millis(300)).ok())
        .is_some()
}

/// Find the engine's venv Python by walking up from a starting dir looking for
/// `engine/.venv/Scripts/python.exe` (Windows) / `engine/.venv/bin/python`.
fn find_engine_python(start: &Path) -> Option<PathBuf> {
    #[cfg(windows)]
    let rel = Path::new("engine/.venv/Scripts/python.exe");
    #[cfg(not(windows))]
    let rel = Path::new("engine/.venv/bin/python");

    for dir in start.ancestors() {
        let candidate = dir.join(rel);
        if candidate.exists() {
            return Some(candidate);
        }
    }
    None
}

// ---- LAN helpers ---------------------------------------------------------

/// Walk ancestors of exe + cwd to find the existing .maxconfig.json.
fn find_maxconfig_path() -> Option<PathBuf> {
    let rel = Path::new("engine/.maxconfig.json");
    let roots = [
        std::env::current_exe().ok().and_then(|p| p.parent().map(Path::to_path_buf)),
        std::env::current_dir().ok(),
    ];
    for root in roots.into_iter().flatten() {
        for dir in root.ancestors() {
            let c = dir.join(rel);
            if c.exists() {
                return Some(c);
            }
        }
    }
    None
}

/// Return the path where .maxconfig.json lives (or should be created).
fn maxconfig_path() -> PathBuf {
    if let Some(p) = find_maxconfig_path() {
        return p;
    }
    // Derive from the engine .venv location
    let from_exe = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().and_then(find_engine_python));
    let py = from_exe
        .or_else(|| std::env::current_dir().ok().and_then(|d| find_engine_python(&d)));
    if let Some(py) = py {
        if let Some(engine_dir) = py.ancestors().nth(3) {
            return engine_dir.join(".maxconfig.json");
        }
    }
    std::env::current_dir()
        .unwrap_or_default()
        .join("engine/.maxconfig.json")
}

/// Read LAN settings from .maxconfig.json.
/// Returns (enabled, port, cert_path, key_path).
fn read_lan_from_config() -> (bool, u16, String, String) {
    let path = match find_maxconfig_path() {
        Some(p) => p,
        None => return (false, LAN_PORT, String::new(), String::new()),
    };
    let text = match std::fs::read_to_string(&path) {
        Ok(t) => t,
        Err(_) => return (false, LAN_PORT, String::new(), String::new()),
    };
    let data: serde_json::Value = match serde_json::from_str(&text) {
        Ok(v) => v,
        Err(_) => return (false, LAN_PORT, String::new(), String::new()),
    };
    let lan = match data.get("lan") {
        Some(v) => v,
        None => return (false, LAN_PORT, String::new(), String::new()),
    };
    let enabled = lan.get("lan_enabled").and_then(|v| v.as_bool()).unwrap_or(false);
    let port = lan.get("lan_port").and_then(|v| v.as_u64()).map(|n| n as u16).unwrap_or(LAN_PORT);
    let cert = lan.get("cert_path").and_then(|v| v.as_str()).unwrap_or("").to_string();
    let key = lan.get("key_path").and_then(|v| v.as_str()).unwrap_or("").to_string();
    (enabled, port, cert, key)
}

/// Write LAN fields into .maxconfig.json (merges into existing JSON).
fn update_maxconfig_lan_fields(
    cert_path: Option<&str>,
    key_path: Option<&str>,
    enabled: Option<bool>,
    port: Option<u16>,
) -> Result<(), String> {
    let cfg_path = maxconfig_path();
    let mut data: serde_json::Value = if cfg_path.exists() {
        let text = std::fs::read_to_string(&cfg_path).map_err(|e| e.to_string())?;
        serde_json::from_str(&text).unwrap_or_else(|_| serde_json::json!({}))
    } else {
        serde_json::json!({})
    };

    if data.get("lan").is_none() {
        data["lan"] = serde_json::json!({});
    }
    let lan = data["lan"].as_object_mut().ok_or("lan not an object")?;
    if let Some(c) = cert_path { lan.insert("cert_path".to_string(), serde_json::json!(c)); }
    if let Some(k) = key_path { lan.insert("key_path".to_string(), serde_json::json!(k)); }
    if let Some(e) = enabled { lan.insert("lan_enabled".to_string(), serde_json::json!(e)); }
    if let Some(p) = port { lan.insert("lan_port".to_string(), serde_json::json!(p)); }

    let pretty = serde_json::to_string_pretty(&data).map_err(|e| e.to_string())?;
    if let Some(parent) = cfg_path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    std::fs::write(&cfg_path, pretty).map_err(|e| e.to_string())
}

/// Find the mkcert binary: check PATH, then WinGet links dir.
fn find_mkcert() -> Option<PathBuf> {
    #[cfg(windows)]
    {
        // Try where.exe first
        if let Ok(out) = Command::new("where")
            .arg("mkcert")
            .creation_flags(CREATE_NO_WINDOW)
            .output()
        {
            if out.status.success() {
                let s = String::from_utf8_lossy(&out.stdout);
                let line = s.lines().next().unwrap_or("").trim();
                if !line.is_empty() {
                    return Some(PathBuf::from(line));
                }
            }
        }
        // WinGet links dir
        if let Ok(local) = std::env::var("LOCALAPPDATA") {
            let candidate = PathBuf::from(&local)
                .join("Microsoft/WinGet/Links/mkcert.exe");
            if candidate.exists() {
                return Some(candidate);
            }
        }
    }
    #[cfg(not(windows))]
    {
        if let Ok(out) = Command::new("which").arg("mkcert").output() {
            if out.status.success() {
                let s = String::from_utf8_lossy(&out.stdout);
                let line = s.trim();
                if !line.is_empty() {
                    return Some(PathBuf::from(line));
                }
            }
        }
    }
    None
}

/// Get the first non-loopback LAN IPv4 address from ipconfig/ip.
fn get_lan_ip() -> String {
    #[cfg(windows)]
    {
        let out = Command::new("ipconfig")
            .creation_flags(CREATE_NO_WINDOW)
            .output()
            .ok();
        if let Some(out) = out {
            let text = String::from_utf8_lossy(&out.stdout);
            for line in text.lines() {
                let line = line.trim();
                if (line.contains("IPv4") || line.contains("IPv4-Adresse")) && line.contains(':') {
                    if let Some(ip) = line.splitn(2, ':').nth(1) {
                        let ip = ip.trim();
                        if !ip.starts_with("127.") && !ip.starts_with("169.254")
                            && ip.chars().all(|c| c.is_ascii_digit() || c == '.')
                            && ip.contains('.')
                        {
                            return ip.to_string();
                        }
                    }
                }
            }
        }
    }
    #[cfg(not(windows))]
    {
        let out = Command::new("sh")
            .args(["-c", "ip -4 addr show scope global | grep -oP '(?<=inet )\\d+\\.\\d+\\.\\d+\\.\\d+'"])
            .output()
            .ok();
        if let Some(out) = out {
            let s = String::from_utf8_lossy(&out.stdout);
            if let Some(line) = s.lines().next() {
                let ip = line.trim();
                if !ip.is_empty() {
                    return ip.to_string();
                }
            }
        }
    }
    "127.0.0.1".to_string()
}

/// Run mkcert -CAROOT and return the directory path.
fn get_mkcert_caroot(mkcert: &Path) -> Option<String> {
    let mut cmd = Command::new(mkcert);
    cmd.arg("-CAROOT");
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);
    let out = cmd.output().ok()?;
    if out.status.success() {
        let s = String::from_utf8_lossy(&out.stdout).trim().to_string();
        if !s.is_empty() { Some(s) } else { None }
    } else {
        None
    }
}

/// Start the FastAPI engine. Reads LAN config from .maxconfig.json to decide
/// host/port/TLS. Returns the child handle when we spawned it, or `None` when
/// the engine was already running or we couldn't locate the venv.
fn spawn_engine() -> Option<Child> {
    let (lan_enabled, lan_port, cert_path, key_path) = read_lan_from_config();
    let use_tls = lan_enabled
        && !cert_path.is_empty()
        && !key_path.is_empty()
        && Path::new(&cert_path).exists()
        && Path::new(&key_path).exists();
    let (host, port) = if use_tls {
        ("0.0.0.0", lan_port)
    } else {
        ("127.0.0.1", ENGINE_PORT)
    };

    if port_open(port) {
        if use_tls {
            // For HTTPS mode port-open is sufficient — we can't do raw HTTP health check
            println!("[engine] already running on :{port} (TLS) — reusing");
            return None;
        } else if engine_healthy() {
            println!("[engine] already running and healthy on :{ENGINE_PORT} — reusing");
            return None;
        }
        println!("[engine] port :{port} occupied but unresponsive — killing zombie...");
        kill_port_owner_on(port);
    }

    // Search from the executable's dir and the current working dir (Max.cmd sets
    // cwd to the repo root), so it works both built and from a launcher.
    let from_exe = std::env::current_exe().ok().and_then(|p| {
        p.parent().and_then(find_engine_python)
    });
    let py = from_exe
        .or_else(|| std::env::current_dir().ok().and_then(|d| find_engine_python(&d)))?;
    let engine_dir = py.ancestors().nth(3)?.to_path_buf();

    let mut cmd = Command::new(&py);
    cmd.args(["-m", "uvicorn", "max_engine.main:app", "--host", host, "--port", &port.to_string()])
        .current_dir(&engine_dir);
    if use_tls {
        cmd.args(["--ssl-certfile", &cert_path, "--ssl-keyfile", &key_path]);
    }
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);

    match cmd.spawn() {
        Ok(child) => {
            println!("[engine] started ({}) on {host}:{port} from {}", child.id(), engine_dir.display());
            Some(child)
        }
        Err(e) => {
            eprintln!("[engine] failed to start: {e}");
            None
        }
    }
}

/// Kill the engine we started (best-effort) so shutting the app frees the port.
/// On Windows the venv `python.exe` is a launcher stub that spawns the real
/// interpreter as a child, so we must kill the whole tree — `Child::kill()` would
/// only reap the stub and orphan the process that actually holds the port.
fn shutdown_engine(app: &tauri::AppHandle) {
    if let Some(state) = app.try_state::<EngineProcess>() {
        if let Ok(mut guard) = state.0.lock() {
            if let Some(mut child) = guard.take() {
                let pid = child.id();
                #[cfg(windows)]
                {
                    let mut kill = Command::new("taskkill");
                    kill.args(["/T", "/F", "/PID", &pid.to_string()]);
                    kill.creation_flags(CREATE_NO_WINDOW);
                    let _ = kill.status();
                }
                #[cfg(not(windows))]
                {
                    let _ = child.kill();
                }
                let _ = child.wait();
                println!("[engine] stopped (pid {pid} tree)");
            }
        }
    }
}

// ---- Tor daemon management -----------------------------------------------

/// True if Tor's SOCKS5 proxy port is open (daemon is up and accepting).
fn tor_port_open() -> bool {
    let addr = format!("127.0.0.1:{TOR_SOCKS_PORT}");
    addr.parse()
        .ok()
        .and_then(|a| TcpStream::connect_timeout(&a, Duration::from_millis(300)).ok())
        .is_some()
}

/// Locate the bundled Tor binary. In a bundled install it sits under
/// `resource_dir()/tor/...`; in a `--no-bundle` / dev build resources are NOT
/// copied next to the exe, so we also walk up from the exe and cwd looking for
/// the source-tree `resources/tor/<platform>/tor[.exe]` (same strategy as
/// `find_engine_python`).
fn find_tor_binary(app: &tauri::AppHandle) -> Option<PathBuf> {
    #[cfg(windows)]
    let rel = Path::new("tor/windows/tor.exe");
    #[cfg(not(windows))]
    let rel = Path::new("tor/linux/tor");

    // 1) Bundled location: directly under the resource dir.
    if let Ok(res_dir) = app.path().resource_dir() {
        for c in [res_dir.join(rel), res_dir.join("tor/tor.exe")] {
            if c.exists() {
                return Some(c);
            }
        }
    }

    // 2) Source tree: walk ancestors of the exe and cwd for `resources/tor/...`.
    #[cfg(windows)]
    let src_rel = Path::new("resources/tor/windows/tor.exe");
    #[cfg(not(windows))]
    let src_rel = Path::new("resources/tor/linux/tor");

    let roots = [
        std::env::current_exe().ok().and_then(|p| p.parent().map(Path::to_path_buf)),
        std::env::current_dir().ok(),
    ];
    for root in roots.into_iter().flatten() {
        for dir in root.ancestors() {
            let c = dir.join(src_rel);
            if c.exists() {
                return Some(c);
            }
        }
    }
    None
}

/// Kill the Tor process we own on app exit.
fn shutdown_tor(app: &tauri::AppHandle) {
    if let Some(state) = app.try_state::<TorProcess>() {
        if let Ok(mut guard) = state.0.lock() {
            if let Some(mut child) = guard.take() {
                let pid = child.id();
                #[cfg(windows)]
                {
                    let mut kill = Command::new("taskkill");
                    kill.args(["/T", "/F", "/PID", &pid.to_string()]);
                    kill.creation_flags(CREATE_NO_WINDOW);
                    let _ = kill.status();
                }
                #[cfg(not(windows))]
                {
                    let _ = child.kill();
                }
                let _ = child.wait();
                println!("[tor] stopped (pid {pid} tree)");
            }
        }
    }
}

/// Start the Tor daemon. User-initiated from the Shadow Net tab — unlike the
/// engine, Tor does NOT start automatically on launch.
#[tauri::command]
fn start_tor(app: tauri::AppHandle, state: tauri::State<'_, TorProcess>) -> Result<(), String> {
    if tor_port_open() {
        println!("[tor] already running on :{TOR_SOCKS_PORT}");
        return Ok(());
    }

    let tor_bin = find_tor_binary(&app)
        .ok_or_else(|| "Tor binary not found in app resources. Place tor.exe in resources/tor/windows/.".to_string())?;

    // Data directory in the OS app-data folder so it persists between launches.
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| e.to_string())?
        .join("tor");
    std::fs::create_dir_all(&data_dir).map_err(|e| e.to_string())?;

    let data_dir_str = data_dir.to_string_lossy().into_owned();

    // Run from the binary's own directory so Windows finds the bundled DLLs
    // (libcrypto, libssl, libevent, etc.) that ship alongside tor.exe.
    let tor_dir = tor_bin.parent().unwrap_or(tor_bin.as_path());

    let mut cmd = Command::new(&tor_bin);
    cmd.args([
        "--SocksPort",
        &TOR_SOCKS_PORT.to_string(),
        "--ControlPort",
        "9051",
        "--DataDirectory",
        &data_dir_str,
        "--Log",
        "notice stdout",
    ])
    .current_dir(tor_dir);
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);

    let child = cmd.spawn().map_err(|e| format!("Failed to start Tor: {e}"))?;
    let pid = child.id();
    *state.0.lock().unwrap() = Some(child);
    println!("[tor] started (pid {pid}) — data dir: {data_dir_str}");
    Ok(())
}

/// Stop the Tor daemon. Called when the user disconnects from Shadow Net.
#[tauri::command]
fn stop_tor(state: tauri::State<'_, TorProcess>) -> Result<(), String> {
    let mut guard = state.0.lock().unwrap();
    if let Some(mut child) = guard.take() {
        let pid = child.id();
        #[cfg(windows)]
        {
            let mut kill = Command::new("taskkill");
            kill.args(["/T", "/F", "/PID", &pid.to_string()]);
            kill.creation_flags(CREATE_NO_WINDOW);
            let _ = kill.status();
        }
        #[cfg(not(windows))]
        {
            let _ = child.kill();
        }
        let _ = child.wait();
        println!("[tor] stopped (pid {pid})");
    }
    Ok(())
}

/// Returns true if the Tor SOCKS5 port is currently accepting connections.
#[tauri::command]
fn tor_running() -> bool {
    tor_port_open()
}

// ---- LAN commands --------------------------------------------------------

/// Return the base URL the Tauri WebView should use to reach the engine.
/// Reads .maxconfig.json at call time so it reflects the current LAN state.
#[tauri::command]
fn engine_base() -> String {
    let (enabled, port, cert_path, key_path) = read_lan_from_config();
    if enabled
        && !cert_path.is_empty()
        && !key_path.is_empty()
        && Path::new(&cert_path).exists()
        && Path::new(&key_path).exists()
    {
        format!("https://127.0.0.1:{port}")
    } else {
        format!("http://127.0.0.1:{ENGINE_PORT}")
    }
}

/// Trigger the engine's autonomous Aegis fix for an event via the local HTTP API
/// (raw TCP — the same minimal client as the health check). Returns the raw SSE
/// body so the caller can parse the final status. Only effective when the engine's
/// `aegis.autonomy` is `auto`; otherwise the engine streams an error event. This is
/// the desktop/Rust path into the auto-fix pipeline, complementing the in-webview
/// fetch stream used by the browser/LAN client.
#[tauri::command]
fn aegis_auto_fix(event_id: String) -> Result<String, String> {
    use std::io::{Read, Write};
    // Constrain the id to a path-safe token — it is interpolated into the URL.
    if event_id.is_empty()
        || !event_id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
    {
        return Err("invalid event id".into());
    }
    let addr = format!("127.0.0.1:{ENGINE_PORT}");
    let parsed = addr.parse().map_err(|_| "bad engine address".to_string())?;
    let mut stream = TcpStream::connect_timeout(&parsed, Duration::from_millis(3000))
        .map_err(|e| format!("connect failed: {e}"))?;
    let _ = stream.set_read_timeout(Some(Duration::from_secs(180)));
    let req = format!(
        "POST /aegis/auto-fix/{event_id} HTTP/1.0\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\n\r\n"
    );
    stream
        .write_all(req.as_bytes())
        .map_err(|e| format!("write failed: {e}"))?;
    let mut body = String::new();
    stream
        .read_to_string(&mut body)
        .map_err(|e| format!("read failed: {e}"))?;
    Ok(body)
}

#[derive(serde::Serialize)]
struct LanStatus {
    enabled: bool,
    port: u16,
    cert_ready: bool,
    cert_path: String,
    key_path: String,
    url: String,
    lan_url: String,
    pc_name: String,
    lan_ip: String,
    root_ca_path: String,
}

/// Full LAN status used by the Settings panel.
#[tauri::command]
fn get_lan_status() -> LanStatus {
    let (enabled, port, cert_path, key_path) = read_lan_from_config();
    let cert_ready = !cert_path.is_empty()
        && Path::new(&cert_path).exists()
        && !key_path.is_empty()
        && Path::new(&key_path).exists();
    let pc_name = std::env::var("COMPUTERNAME")
        .unwrap_or_else(|_| hostname_fallback());
    let lan_ip = get_lan_ip();
    let url = format!("https://{pc_name}.local:{port}");
    let lan_url = format!("https://{lan_ip}:{port}");
    let root_ca_path = find_mkcert()
        .and_then(|m| get_mkcert_caroot(&m))
        .unwrap_or_default();
    LanStatus { enabled, port, cert_ready, cert_path, key_path, url, lan_url, pc_name, lan_ip, root_ca_path }
}

fn hostname_fallback() -> String {
    #[cfg(windows)]
    {
        Command::new("hostname")
            .creation_flags(CREATE_NO_WINDOW)
            .output()
            .ok()
            .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| "DESKTOP".to_string())
    }
    #[cfg(not(windows))]
    {
        Command::new("hostname")
            .output()
            .ok()
            .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| "localhost".to_string())
    }
}

/// Install mkcert (via winget if needed), generate a cert trusted for this PC's
/// LAN hostname, IP, localhost, and 127.0.0.1. Saves cert paths to .maxconfig.json.
#[tauri::command]
fn setup_cert() -> Result<String, String> {
    // 1. Find or install mkcert
    let mkcert = if let Some(p) = find_mkcert() {
        p
    } else {
        // Try winget (Windows 11 has it by default)
        let _ = Command::new("winget")
            .args(["install", "FiloSottile.mkcert",
                   "--silent", "--accept-package-agreements", "--accept-source-agreements"])
            .creation_flags(CREATE_NO_WINDOW)
            .status();
        // Pause a moment for the install to settle
        std::thread::sleep(Duration::from_millis(2000));
        find_mkcert().ok_or_else(|| {
            "mkcert not found after winget install.\n\
             Please download mkcert.exe from https://github.com/FiloSottile/mkcert/releases, \
             place it on PATH, then click 'Setup Certs' again.".to_string()
        })?
    };

    // 2. Install root CA into system trust store (needs UAC on Windows).
    //    Use PowerShell Start-Process -Verb RunAs so the user sees a UAC prompt.
    #[cfg(windows)]
    {
        let mkcert_str = mkcert.to_string_lossy().to_string();
        let ps_cmd = format!("Start-Process '{}' -ArgumentList '-install' -Verb RunAs -Wait", mkcert_str);
        let status = Command::new("powershell")
            .args(["-NoProfile", "-NonInteractive", "-Command", &ps_cmd])
            .creation_flags(CREATE_NO_WINDOW)
            .status()
            .map_err(|e| format!("PowerShell elevation failed: {e}"))?;
        if !status.success() {
            return Err("mkcert -install was cancelled or failed. UAC elevation required.".to_string());
        }
    }
    #[cfg(not(windows))]
    {
        let status = Command::new(&mkcert)
            .arg("-install")
            .status()
            .map_err(|e| format!("mkcert -install failed: {e}"))?;
        if !status.success() {
            return Err("mkcert -install failed — may need sudo.".to_string());
        }
    }

    // 3. Determine output directory (engine/ dir, next to .maxconfig.json)
    let engine_dir = maxconfig_path()
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_default().join("engine"));

    let cert_file = engine_dir.join("lan-cert.pem");
    let key_file = engine_dir.join("lan-key.pem");

    // 4. Get LAN identifiers for the cert SANs
    let pc_name = std::env::var("COMPUTERNAME").unwrap_or_else(|_| hostname_fallback());
    let lan_ip = get_lan_ip();
    let mdns_name = format!("{pc_name}.local");

    // 5. Generate cert
    let mut cmd = Command::new(&mkcert);
    cmd.args([
        "-key-file", key_file.to_str().unwrap_or("lan-key.pem"),
        "-cert-file", cert_file.to_str().unwrap_or("lan-cert.pem"),
        &mdns_name,
        &lan_ip,
        "localhost",
        "127.0.0.1",
    ]);
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);

    let out = cmd.output().map_err(|e| format!("mkcert cert generation failed: {e}"))?;
    if !out.status.success() {
        let stderr = String::from_utf8_lossy(&out.stderr);
        return Err(format!("mkcert failed: {stderr}"));
    }

    // 6. Save cert paths into .maxconfig.json
    update_maxconfig_lan_fields(
        Some(cert_file.to_str().unwrap_or("")),
        Some(key_file.to_str().unwrap_or("")),
        None,
        None,
    )?;

    Ok(format!(
        "Certificate ready!\n\
         Trusted names: {mdns_name}, {lan_ip}, localhost, 127.0.0.1\n\
         Cert: {}\n\
         Key: {}",
        cert_file.display(),
        key_file.display()
    ))
}

/// Open the mkcert root CA directory in Explorer so the user can find rootCA.pem
/// to AirDrop to their iPhone for trust installation.
#[tauri::command]
fn reveal_root_ca() -> Result<(), String> {
    let mkcert = find_mkcert()
        .ok_or_else(|| "mkcert not found — run cert setup first.".to_string())?;
    let ca_dir = get_mkcert_caroot(&mkcert)
        .ok_or_else(|| "Could not determine mkcert CA root.".to_string())?;

    #[cfg(windows)]
    {
        Command::new("explorer")
            .arg(&ca_dir)
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .map_err(|e| format!("Could not open Explorer: {e}"))?;
    }
    #[cfg(not(windows))]
    {
        Command::new("xdg-open")
            .arg(&ca_dir)
            .spawn()
            .map_err(|e| format!("Could not open file manager: {e}"))?;
    }
    Ok(())
}

/// Toggle LAN mode and restart the engine with the new config.
/// `enabled=true` starts the engine on 0.0.0.0:8443 with HTTPS.
/// `enabled=false` returns to 127.0.0.1:8001 HTTP.
#[tauri::command]
fn restart_engine_for_lan(
    enabled: bool,
    engine_state: tauri::State<'_, EngineProcess>,
) -> Result<(), String> {
    // 1. Persist the toggle
    update_maxconfig_lan_fields(None, None, Some(enabled), None)?;

    // 2. Kill the current engine by PID
    {
        let mut guard = engine_state.0.lock().map_err(|e| e.to_string())?;
        if let Some(mut child) = guard.take() {
            let pid = child.id();
            #[cfg(windows)]
            {
                let mut kill = Command::new("taskkill");
                kill.args(["/T", "/F", "/PID", &pid.to_string()])
                    .creation_flags(CREATE_NO_WINDOW);
                let _ = kill.status();
            }
            #[cfg(not(windows))]
            { let _ = child.kill(); }
            let _ = child.wait();
            println!("[engine] stopped for LAN restart (pid {pid})");
        }
    }

    // 3. Brief pause so the port is freed before respawn
    std::thread::sleep(Duration::from_millis(600));

    // 4. Respawn with updated config
    let child = spawn_engine();
    {
        let mut guard = engine_state.0.lock().map_err(|e| e.to_string())?;
        *guard = child;
    }
    Ok(())
}

// --------------------------------------------------------------------------

/// Live system meters shown in the widget's top bar. Percentages are 0..100.
#[derive(serde::Serialize)]
struct SystemStats {
    cpu: f32,
    ram: f32,
    gpu: f32,
    vram: f32,
    /// GPU temperature in °C (0 when unavailable).
    gpu_temp: f32,
    /// False when no NVIDIA GPU / `nvidia-smi` is available (gpu/vram/temp are 0).
    gpu_available: bool,
}

/// CPU + RAM via `sysinfo`; GPU + VRAM via `nvidia-smi` (the 4070 Ti). Polled by
/// the frontend every ~1.5s. VRAM is the meter that matters most (12 GB ceiling).
#[tauri::command]
fn get_system_stats(sys: tauri::State<'_, Mutex<sysinfo::System>>) -> SystemStats {
    let (cpu, ram) = {
        let mut s = sys.lock().unwrap();
        s.refresh_cpu_usage();
        s.refresh_memory();
        let total = s.total_memory();
        let ram = if total > 0 {
            s.used_memory() as f32 / total as f32 * 100.0
        } else {
            0.0
        };
        (s.global_cpu_usage(), ram)
    };

    let (gpu, vram, gpu_temp, gpu_available) = query_nvidia().unwrap_or((0.0, 0.0, 0.0, false));
    SystemStats {
        cpu,
        ram,
        gpu,
        vram,
        gpu_temp,
        gpu_available,
    }
}

/// Returns (gpu_util%, vram_used%, gpu_temp_c, true) by parsing `nvidia-smi`, or
/// None if it isn't present / fails. No console flash on Windows.
fn query_nvidia() -> Option<(f32, f32, f32, bool)> {
    let mut cmd = std::process::Command::new("nvidia-smi");
    cmd.args([
        "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
        "--format=csv,noheader,nounits",
    ]);
    #[cfg(windows)]
    cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW

    let out = cmd.output().ok()?;
    if !out.status.success() {
        return None;
    }
    let text = String::from_utf8_lossy(&out.stdout);
    let line = text.lines().next()?;
    let parts: Vec<&str> = line.split(',').map(str::trim).collect();
    if parts.len() < 4 {
        return None;
    }
    let gpu: f32 = parts[0].parse().ok()?;
    let used: f32 = parts[1].parse().ok()?;
    let total: f32 = parts[2].parse().ok()?;
    let temp: f32 = parts[3].parse().ok()?;
    let vram = if total > 0.0 { used / total * 100.0 } else { 0.0 };
    Some((gpu, vram, temp, true))
}

/// Click-through-when-idle: Tauri's `set_ignore_cursor_events` is whole-window,
/// so once the window ignores the cursor the webview can't see hover to switch
/// back. We instead poll the global cursor position against the window bounds
/// from the backend and toggle interactivity: interactive while the cursor is
/// over the widget, click-through (passes to the desktop) otherwise.
fn spawn_click_through_guard(app: &tauri::AppHandle) {
    let Some(window) = app.get_webview_window("main") else {
        return;
    };
    let handle = app.clone();

    std::thread::spawn(move || {
        let mut ignoring = false;
        loop {
            std::thread::sleep(std::time::Duration::from_millis(120));

            if !window.is_visible().unwrap_or(false) {
                continue;
            }

            let (Ok(cursor), Ok(pos), Ok(size)) = (
                handle.cursor_position(),
                window.outer_position(),
                window.outer_size(),
            ) else {
                continue;
            };

            let inside = cursor.x >= pos.x as f64
                && cursor.x <= pos.x as f64 + size.width as f64
                && cursor.y >= pos.y as f64
                && cursor.y <= pos.y as f64 + size.height as f64;

            let want_ignore = !inside;
            if want_ignore != ignoring {
                let _ = window.set_ignore_cursor_events(want_ignore);
                ignoring = want_ignore;
            }
        }
    });
}

/// Quit the whole app (the widget's red shutdown button). Exits the process so
/// every window — main, OSINT, Market — closes together.
#[tauri::command]
fn quit_app(app: tauri::AppHandle) {
    app.exit(0);
}

/// Toggle the widget's visibility (bound to the global hotkey).
#[cfg(desktop)]
fn toggle_main(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        if window.is_visible().unwrap_or(false) {
            let _ = window.hide();
        } else {
            let _ = window.show();
            let _ = window.set_focus();
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // Single-instance MUST be the first plugin. A second launch focuses the
        // existing widget instead of stacking another (invisible) one + engine.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_opener::init())
        .manage(Mutex::new(sysinfo::System::new_all()))
        .manage(TorProcess(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![
            get_system_stats,
            quit_app,
            start_tor,
            stop_tor,
            tor_running,
            engine_base,
            aegis_auto_fix,
            get_lan_status,
            setup_cert,
            reveal_root_ca,
            restart_engine_for_lan,
        ])
        .setup(|app| {
            // Own the engine lifecycle: start it on launch (if not already up) and
            // hold the handle so we can stop it on shutdown.
            app.manage(EngineProcess(Mutex::new(spawn_engine())));

            #[cfg(desktop)]
            {
                // Global hotkey: Ctrl+Shift+M toggles show/hide. Registered in the
                // backend (more reliable than from the webview). Ctrl+Alt is avoided
                // because Windows treats it as AltGr, which makes such global
                // hotkeys unreliable to register.
                let toggle = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyM);
                app.handle().plugin(
                    tauri_plugin_global_shortcut::Builder::new()
                        .with_handler(move |app, shortcut, event| {
                            if shortcut == &toggle && event.state() == ShortcutState::Pressed {
                                toggle_main(app);
                            }
                        })
                        .build(),
                )?;
                // Clear any stale registration (e.g. left by a force-killed dev
                // instance) and register fresh. Non-fatal: a hotkey conflict must
                // not crash the app.
                let gs = app.global_shortcut();
                let _ = gs.unregister_all();
                match gs.register(toggle) {
                    Ok(()) => println!("global toggle hotkey (Ctrl+Shift+M) registered"),
                    Err(e) => eprintln!("global toggle hotkey registration failed: {e}"),
                }

                spawn_click_through_guard(app.handle());
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            // On final exit, stop the engine and Tor so ports are freed.
            if let tauri::RunEvent::Exit = event {
                shutdown_engine(app_handle);
                shutdown_tor(app_handle);
            }
        });
}
