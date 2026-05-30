use tauri::Manager;

#[cfg(desktop)]
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

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

            // Only manage interactivity while the window is actually shown.
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
