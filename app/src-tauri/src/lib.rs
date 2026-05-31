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

/// The engine port the app + UI agree on (see app/src/engine.ts ENGINE_URL).
const ENGINE_PORT: u16 = 8001;

/// Holds the FastAPI engine child process when *we* started it, so we can kill it
/// on shutdown. `None` when the engine was already running (started externally) —
/// in that case we leave it alone.
struct EngineProcess(Mutex<Option<Child>>);

/// True if something is already listening on the engine port.
fn engine_running() -> bool {
    let addr = format!("127.0.0.1:{ENGINE_PORT}");
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

/// Start the FastAPI engine if it isn't already up. Returns the child handle when
/// we spawned it (so we own its lifecycle), or `None` if it was already running
/// or we couldn't locate the venv.
fn spawn_engine() -> Option<Child> {
    if engine_running() {
        println!("[engine] already running on :{ENGINE_PORT} — reusing");
        return None;
    }

    // Search from the executable's dir and the current working dir (Max.cmd sets
    // cwd to the repo root), so it works both built and from a launcher.
    let from_exe = std::env::current_exe().ok().and_then(|p| {
        p.parent().and_then(find_engine_python)
    });
    let py = from_exe
        .or_else(|| std::env::current_dir().ok().and_then(|d| find_engine_python(&d)))?;
    // engine dir = the folder that contains `.venv` (python is .../engine/.venv/Scripts/python.exe)
    let engine_dir = py.ancestors().nth(3)?.to_path_buf();

    let mut cmd = Command::new(&py);
    cmd.args([
        "-m",
        "uvicorn",
        "max_engine.main:app",
        "--port",
        &ENGINE_PORT.to_string(),
    ])
    .current_dir(&engine_dir);
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);

    match cmd.spawn() {
        Ok(child) => {
            println!("[engine] started ({}) from {}", child.id(), engine_dir.display());
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
        .invoke_handler(tauri::generate_handler![get_system_stats, quit_app])
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
            // On final exit, stop the engine we started so the port is freed.
            if let tauri::RunEvent::Exit = event {
                shutdown_engine(app_handle);
            }
        });
}
