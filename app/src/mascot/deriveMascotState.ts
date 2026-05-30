import type { MascotState } from "../components/Mascot";

/** Per-session state as reported by the engine's `GET /sessions`. */
export type SessionState = "queued" | "running" | "done" | "error";

export interface SessionLike {
  id: string;
  state: SessionState;
  /** True for cloud (`!`) tasks — they don't consume local VRAM. */
  cloud?: boolean;
}

export interface MascotSignal {
  state: MascotState;
  /** 0..1 VRAM pressure estimate; only meaningful when state === "busy". */
  vramLoad: number;
}

/**
 * Collapse the engine's session list (+ optional measured VRAM usage) into the
 * single mascot signal. This is the one place that decides "what is Max doing?"
 *
 * Priority, highest first:
 *   error    — any session errored
 *   done     — nothing active, but something finished very recently
 *   busy     — local work is running AND VRAM is under pressure / queue is deep
 *   thinking — something is running (or queued behind cloud work)
 *   idle     — nothing happening
 *
 * @param sessions       current sessions from the engine
 * @param vramUsedRatio  measured local VRAM usage 0..1 (e.g. from nvidia-smi);
 *                       optional — when omitted, queue depth is used as a proxy
 * @param recentlyDone   true if a session completed within the celebratory window
 */
export function deriveMascotState(
  sessions: SessionLike[],
  vramUsedRatio?: number,
  recentlyDone = false,
): MascotSignal {
  const hasError = sessions.some((s) => s.state === "error");
  if (hasError) return { state: "error", vramLoad: 0 };

  const localRunning = sessions.filter((s) => s.state === "running" && !s.cloud);
  const localQueued = sessions.filter((s) => s.state === "queued" && !s.cloud);
  const anyActive = sessions.some(
    (s) => s.state === "running" || s.state === "queued",
  );

  if (!anyActive) {
    return { state: recentlyDone ? "done" : "idle", vramLoad: 0 };
  }

  // VRAM pressure: prefer a real measurement; otherwise approximate from how
  // many heavy local tasks are stacked up (running + queued).
  const queueDepth = localRunning.length + localQueued.length;
  const vramLoad =
    typeof vramUsedRatio === "number"
      ? clamp01(vramUsedRatio)
      : clamp01(queueDepth / 4);

  const underPressure =
    (typeof vramUsedRatio === "number" ? vramUsedRatio >= 0.8 : queueDepth >= 2) ||
    localQueued.length > 0;

  if (localRunning.length > 0 && underPressure) {
    return { state: "busy", vramLoad: Math.max(vramLoad, 0.5) };
  }

  return { state: "thinking", vramLoad };
}

function clamp01(n: number): number {
  return Math.min(1, Math.max(0, Number.isFinite(n) ? n : 0));
}
