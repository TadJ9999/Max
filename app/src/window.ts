// Floating-window behaviors that only apply inside the Tauri shell:
//   - anchor the widget to the top-right of the active monitor
//   - global hotkey (Ctrl+Alt+M) to toggle show/hide
// Click-through-when-idle is handled in Rust (src-tauri/src/lib.rs), since
// whole-window cursor-ignore can't be detected back from the webview.
//
// Everything is dynamically imported and guarded so the plain `vite dev`
// browser preview (no Tauri) is a no-op.

const TOGGLE_ACCELERATOR = "CommandOrControl+Alt+M";
const MARGIN = 16;

function inTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export async function initFloatingWindow(): Promise<void> {
  if (!inTauri()) return;

  const { getCurrentWindow, currentMonitor, PhysicalPosition } = await import(
    "@tauri-apps/api/window"
  );
  const { register, isRegistered } = await import("@tauri-apps/plugin-global-shortcut");

  const win = getCurrentWindow();

  const anchorTopRight = async () => {
    const mon = await currentMonitor();
    if (!mon) return;
    const size = await win.outerSize();
    const x = mon.position.x + mon.size.width - size.width - MARGIN;
    const y = mon.position.y + MARGIN;
    await win.setPosition(new PhysicalPosition(Math.round(x), Math.round(y)));
  };

  await anchorTopRight();

  try {
    if (!(await isRegistered(TOGGLE_ACCELERATOR))) {
      await register(TOGGLE_ACCELERATOR, async (event) => {
        // v2 fires for both press and release — act on press only.
        if (event && "state" in event && event.state !== "Pressed") return;
        if (await win.isVisible()) {
          await win.hide();
        } else {
          await win.show();
          await win.setFocus();
          await anchorTopRight();
        }
      });
    }
  } catch (err) {
    // Non-fatal: another instance may already hold the shortcut.
    console.warn("global shortcut registration failed:", err);
  }
}
