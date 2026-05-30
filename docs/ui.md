# Max — Desktop UI Design (floating widget)

The Max client is **not** a normal window — it's a **floating, transparent desktop
widget** pinned to the **top-right** of the screen, sitting on top of everything like
an overlay. A living **vector mascot** anchors it; **task cards** for each active
session stack above it; system stats and settings sit along the top.

## Layout

```
        SYS INFO (%)                          (⚙ COG)
   ┌────────────────────────────────────────────────┐
   │                    TASK #1                       │
   │   model · provider · state · ☁/local · cancel   │
   └────────────────────────────────────────────────┘
                   ▲ small transparent gap
   ┌────────────────────────────────────────────────┐
   │                    TASK #2                       │
   │                                                  │
   └────────────────────────────────────────────────┘
                   ▲ small transparent gap
   ┌────────────────────────────────────────────────┐
   │                    TASK #3                       │
   │                                                  │
   └────────────────────────────────────────────────┘

                  ✦  X — VECTOR MASCOT — X  ✦
                  (reacts · thinks · animates)
```

## Elements

### Window / widget shell
- **Frameless, transparent background** — no title bar, no chrome; the desktop shows through.
- **Always-on-top**, **skip taskbar**, **top-right anchored**.
- **Global hotkey** toggles show/hide — **configurable, default `Ctrl+Alt+M`**.
- **Click-through when idle**: the widget ignores mouse events so it never blocks the
  desktop, and becomes interactive **only on hover** (Tauri `setIgnoreCursorEvents`).
- Optional: drag to reposition; remembers position.

### Top bar
- **Left — SYS INFO (%)**: live meters for **CPU · GPU · VRAM · RAM** usage. VRAM is the
  one that matters most (12 GB ceiling) — show it prominently so you can see when local
  is saturated and tasks will queue.
- **Right — ⚙ Cog**: opens settings (models, sigils, hotkeys, provider keys, cloud
  on/off, the workspace folder allowlist, delegate Manual/Smart-Auto toggle).

### Task cards (one per session)
- **Sleek, semi-transparent glass cards**, stacked vertically, newest on top.
- **Small transparent padding between cards** (the desktop shows through the gaps).
- Each card shows: task title / **TASK #**, **model · provider**, **state**
  (queued / running / done / error), a **☁ marker** when it's a cloud (`!`) task, a
  **progress / streaming** indicator, and quick actions: **cancel**, and **promote to
  cloud** while still queued.
- Cards map 1:1 to the engine's isolated sessions (`GET /sessions`).

### The mascot ("X")
- A **live vector-animated character** at the bottom that **reacts to engine state**:
  - **Idle** — calm breathing/looping.
  - **Thinking** — when sessions are running (animated, "working").
  - **Busy/queued** — more intense when the VRAM queue is deep.
  - **Done** — a brief celebratory beat.
  - **Error** — a concerned/glitch reaction.
- It's the emotional pulse of the app — you glance at X and know what Max is doing.

## Tech mapping (Tauri)

| Need | Approach |
|------|----------|
| Transparent, frameless, on-top, top-right | Tauri window: `transparent: true`, `decorations: false`, `alwaysOnTop: true`, `skipTaskbar: true`; position via the window API |
| Show/hide hotkey | `@tauri-apps/plugin-global-shortcut`; configurable, default `Ctrl+Alt+M` |
| Click-through when idle | Tauri `setIgnoreCursorEvents(true)`; toggle off on hover |
| Live mascot (reacts to state) | **SVG + CSS HUD** — *chosen*. Jarvis-style holographic rings, no deps, transparent; state-machine API mirrors Rive so real `.riv` art can drop in later |
| SYS INFO meters | Rust command using the `sysinfo` crate (CPU/RAM); GPU/VRAM via parsing `nvidia-smi` (RTX 4070 Ti) |
| Task cards + streaming | React frontend; subscribe to `/sessions` + per-session output stream (SSE/WebSocket) |
| Glass look | CSS `backdrop-filter: blur()`, low-alpha backgrounds, rounded corners, soft shadows |

## Decisions
- **Mascot:** built as a **"Jarvis"-style holographic HUD** in pure **SVG + CSS** (no Rive
  editor / `.riv` binary, no runtime dep, transparent background) — counter-rotating
  **multi-color (cyan + amber + white)** rings, traveling data arcs, a radar sweep, and a
  pulsing core with an "X" sigil, driven by engine state. The component API mirrors a Rive
  state-machine, so a commissioned `.riv` can drop in later with no other code changes.
  See [mascot.md](mascot.md).
- **UI glass:** **Apple dark-mode "vibrancy"** — near-black translucent cards with hairline
  white borders and strong backdrop blur (the desktop tints through the gaps).
- **Show/hide:** configurable global hotkey, default **`Ctrl+Alt+M`**.
- **Interaction:** click-through when idle, interactive on hover.

## Still open (later)
- Whether to upgrade the code mascot to commissioned Rive art (optional — current rig
  covers all five states).
- Card cap / scroll behavior when many sessions are active.
