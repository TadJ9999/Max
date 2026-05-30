// Shared UI types. Sessions map 1:1 to the engine's isolated sessions
// (GET /sessions); for now the widget renders mock data until that polling
// is wired (see ROADMAP Phase 3/4).
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
};
