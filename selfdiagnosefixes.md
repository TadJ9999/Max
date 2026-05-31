# Max — Self-Diagnose & Fix Log

> Append-only logbook written by **Aegis**, Max's self-debug & fix engine
> (see [docs/aegis.md](docs/aegis.md) and Phase 13 in [ROADMAP.md](ROADMAP.md)).
> Every issue Max detects, diagnoses, and (with your approval) fixes is recorded
> here — newest entries at the **top**. Nothing is applied to the codebase without
> an explicit OK and a diff preview; every applied fix has a git-snapshot rollback.

## Status legend

| Status | Meaning |
|--------|---------|
| `proposed` | Aegis diagnosed the issue and suggested a fix; **no code changed** |
| `applied` | the patch was approved and written to the working tree |
| `verified` | the applied patch passed its verification (tests / build) |
| `rolled-back` | the fix was reverted (verification failed, or you rejected it) |

## Severity legend

`Critical` · `High` · `Medium` · `Low` — set from the crash/log signal and confirmed
by the AI diagnosis.

---

## Entry template

> Copy this block for each new entry (Aegis fills it in automatically). Keep newest
> at the top, directly under this template.

```
## <UTC timestamp> — <short symptom>
- **Status:** proposed | applied | verified | rolled-back
- **Severity:** Critical | High | Medium | Low
- **Trigger:** <crash/log signal + where it was captured (engine / delegate / provider / frontend / rust)>
- **Root cause:** <AI diagnosis>
- **Files changed:** <allowlist-scoped paths, or "none (proposed)">
- **Fix:** <one-line summary>   ·   **Provider:** ☁ claude | local
- **Verification:** <pytest / tsc+build result, or "pending">
- **Diff:** <fenced unified diff or link to the patch>
- **Rollback:** <git ref / how to revert, or "n/a">
```

---

<!-- Aegis appends real entries below this line, newest first. None yet. -->
