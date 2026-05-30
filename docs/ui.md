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
- **Global hotkey** toggles show/hide (e.g. `Ctrl+Alt+M`, user-configurable).
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
| Show/hide hotkey | `@tauri-apps/plugin-global-shortcut` |
| Live mascot (reacts to state) | **Rive** (state-machine vector animation, driven by engine status inputs) — ideal for "reacts/thinks". Lottie is the simpler fallback |
| SYS INFO meters | Rust command using the `sysinfo` crate (CPU/RAM); GPU/VRAM via parsing `nvidia-smi` (RTX 4070 Ti) |
| Task cards + streaming | React frontend; subscribe to `/sessions` + per-session output stream (SSE/WebSocket) |
| Glass look | CSS `backdrop-filter: blur()`, low-alpha backgrounds, rounded corners, soft shadows |

## Open UI questions
- Mascot art style + source — commission a Rive piece, or start with a placeholder rig?
- Default hotkey for show/hide?
- Click-through when idle (so the widget never blocks clicks), and only interactive on hover?
- Card cap / scroll when many sessions are active?
