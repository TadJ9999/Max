use std::sync::Mutex;

use tauri::Manager;

#[cfg(desktop)]
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

/// Live system meters shown in the widget's top bar. Percentages are 0..100.
#[derive(serde::Serialize)]
struct SystemStats {
    cpu: f32,
    ram: f32,
    gpu: f32,
    vram: f32,
    /// False when no NVIDIA GPU / `nvidia-smi` is available (gpu/vram are 0).
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

    let (gpu, vram, gpu_available) = query_nvidia().unwrap_or((0.0, 0.0, false));
    SystemStats {
        cpu,
        ram,
        gpu,
        vram,
        gpu_available,
    }
}

/// Returns (gpu_util%, vram_used%, true) by parsing `nvidia-smi`, or None if it
/// isn't present / fails. Runs without flashing a console window on Windows.
fn query_nvidia() -> Option<(f32, f32, bool)> {
    let mut cmd = std::process::Command::new("nvidia-smi");
    cmd.args([
        "--query-gpu=utilization.gpu,memory.used,memory.total",
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
    if parts.len() < 3 {
        return None;
    }
    let gpu: f32 = parts[0].parse().ok()?;
    let used: f32 = parts[1].parse().ok()?;
    let total: f32 = parts[2].parse().ok()?;
    let vram = if total > 0.0 { used / total * 100.0 } else { 0.0 };
    Some((gpu, vram, true))
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
        .plugin(tauri_plugin_opener::init())
        .manage(Mutex::new(sysinfo::System::new_all()))
        .invoke_handler(tauri::generate_handler![get_system_stats])
        .setup(|app| {
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
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
