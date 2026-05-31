# Max — Mascot "X"

The live vector mascot from [ui.md](ui.md), implemented as a **"Jarvis"-style holographic
HUD** in pure **SVG + CSS** (no Rive editor, no `.riv` binary, no runtime dependency, fully
transparent background). Several counter-rotating rings of tick marks and traveling dashed
arcs, a rotating radar sweep, a circular audio waveform, drifting particles, and a pulsing
reactor core — in the **J.A.R.V.I.S palette (cyan + magenta + violet)** that reacts to engine
state. The rings/sweep are SVG/CSS; the waveform + particles are a transparent canvas layer.
The component's
interface deliberately mirrors a Rive state-machine, so a commissioned `.riv` rig can
replace it later behind the identical API.

## Files
- [`app/src/components/Mascot.tsx`](../app/src/components/Mascot.tsx) — the component.
- [`app/src/components/Mascot.css`](../app/src/components/Mascot.css) — animations / palette.
- [`app/src/mascot/deriveMascotState.ts`](../app/src/mascot/deriveMascotState.ts) — maps
  the engine's `GET /sessions` into the single mascot signal.
- [`app/src/App.tsx`](../app/src/App.tsx) — the widget; derives the signal and renders `<Mascot>`.

## The contract
```ts
type MascotState = "idle" | "thinking" | "busy" | "done" | "error";
<Mascot state={state} vramLoad={0..1} size={180} />
```

| State    | Look                                                          |
|----------|---------------------------------------------------------------|
| idle     | slow rotation, dim glow                                        |
| thinking | faster rotation, brighter cyan glow                           |
| busy     | spin speed + glow scale with `vramLoad` (deeper queue = faster)|
| done     | green retint + bloom, then auto-relaxes to idle (~1.3s)        |
| error    | red retint, fastest/agitated spin                             |

Reduced-motion users get a calm static pose (`prefers-reduced-motion`).

## Wiring to the engine
```tsx
const { state, vramLoad } = deriveMascotState(sessions, vramUsedRatio, recentlyDone);
<Mascot state={state} vramLoad={vramLoad} />
```
`deriveMascotState` is the single place that answers "what is Max doing?": any errored
session → `error`; nothing active → `idle`/`done`; local work under VRAM pressure →
`busy`; otherwise `thinking`. Pass a measured VRAM ratio (from `nvidia-smi`) when you
have it; otherwise it estimates pressure from local queue depth.

## Swapping in real Rive later (optional)
If you ever commission Rive art: add `@rive-app/react-canvas`, build a state machine
with one number input `state` (0–4) plus a number input `vramLoad` (0–1), and replace
`Mascot.tsx`'s SVG with the Rive canvas while keeping the same props. Nothing else
in the app changes.
