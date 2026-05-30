// Floating-window behavior that only applies inside the Tauri shell:
// anchor the widget to the top-right of the active monitor.
//
// The global hotkey (Ctrl+Alt+M) and click-through-when-idle are handled in
// Rust (src-tauri/src/lib.rs) — both are more reliable from the backend.
//
// This is dynamically imported and guarded so the plain `vite dev` browser
// preview (no Tauri) is a no-op.

const MARGIN = 16;

function inTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export async function initFloatingWindow(): Promise<void> {
  if (!inTauri()) return;

  const { getCurrentWindow, currentMonitor, PhysicalPosition } = await import(
    "@tauri-apps/api/window"
  );

  const win = getCurrentWindow();
  const mon = await currentMonitor();
  if (!mon) return;

  const size = await win.outerSize();
  const x = mon.position.x + mon.size.width - size.width - MARGIN;
  const y = mon.position.y + MARGIN;
  await win.setPosition(new PhysicalPosition(Math.round(x), Math.round(y)));
}
