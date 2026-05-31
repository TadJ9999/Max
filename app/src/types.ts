// Shared UI types. Sessions map 1:1 to the engine's isolated sessions
// (GET /sessions). The widget polls real data every ~2s; mock values in App.tsx
// serve as the initial placeholder state when the engine is offline.
//
// Mascot derivation lives in ./mascot/deriveMascotState (single source of truth
// for "what is Max doing?"). SessionState is re-exported from there to avoid
// duplicating the union.

import type { SessionState } from "./mascot/deriveMascotState";

export type { SessionState };

export type Session = {
  id: string;
  title: string;
  provider: string;
  model: string;
  state: SessionState;
  isCloud: boolean;
  output?: string; // live-streamed output (SSE /sessions/{id}/stream)
};
