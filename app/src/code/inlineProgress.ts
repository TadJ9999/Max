// Inline-runner progress estimator. The stream carries no token total, so % is
// derived hybrid: streamed characters against a rolling "typical length" (EWMA,
// persisted across sessions), eased and capped at ~95% so it never stalls early;
// the caller snaps to 100% on [DONE]. target() is monotonic non-decreasing.

const KEY = "max.inline.expectedLen";
const DEFAULT_EXPECTED = 700;
const CEILING = 95;

function readExpected(): number {
  try {
    const v = Number(localStorage.getItem(KEY));
    return Number.isFinite(v) && v > 100 ? v : DEFAULT_EXPECTED;
  } catch {
    return DEFAULT_EXPECTED;
  }
}

export interface ProgressEstimator {
  begin(): void;
  update(chars: number): void;
  /** Current target % in [0, 95], monotonic. */
  target(): number;
  /** Record the final length to refine future estimates. */
  finish(finalChars: number): void;
}

export function createProgressEstimator(): ProgressEstimator {
  let chars = 0;
  let start = 0;
  let last = 0;
  let expected = DEFAULT_EXPECTED;

  return {
    begin() {
      chars = 0;
      start = performance.now();
      last = 0;
      expected = readExpected();
    },
    update(n: number) {
      chars = Math.max(0, n);
    },
    target() {
      const elapsed = performance.now() - start;
      const charPct = expected > 0 ? (chars / expected) * 100 : 0;
      // Time creep so the bar always advances even if the model is quiet.
      const timeCeil = CEILING * (1 - Math.exp(-elapsed / 8000));
      // Let real output lead, but blend in the time creep so it never freezes.
      const blended = Math.max(charPct * 0.85, timeCeil * 0.55 + Math.min(charPct, CEILING) * 0.45);
      const t = Math.min(CEILING, blended);
      last = Math.max(last, t); // never regress
      return last;
    },
    finish(finalChars: number) {
      const next = 0.7 * expected + 0.3 * Math.max(80, finalChars);
      try {
        localStorage.setItem(KEY, String(Math.round(next)));
      } catch {
        /* storage unavailable — keep the in-memory default */
      }
    },
  };
}
