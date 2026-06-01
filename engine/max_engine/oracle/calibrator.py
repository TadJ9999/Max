"""The trained calibrator — what Oracle *learns* from its graded track record.

Three things are fit from the labelled grades:

  1. **Confidence calibration** — isotonic map from stated confidence → empirical
     hit-fraction, so a "90% confident" call that historically lands 60% gets
     pulled down.
  2. **Signal/source reliability** — a logistic regression over one-hot features
     (feature, entity_kind, direction, horizon bucket) → P(hit); its coefficients
     read out as "what makes a call reliable".
  3. **Per-domain difficulty** — per-entity hit-rate priors, shrunk toward the
     global mean so a 1-sample entity doesn't dominate.

numpy + scikit-learn are imported lazily. If they're absent (or there isn't
enough data yet) the calibrator stays dormant — ``ready`` is False and the rest
of Oracle still works on raw stats. User-verified grades are weighted higher.
"""

from __future__ import annotations

import json
import time
from pathlib import Path


def sklearn_available() -> bool:
    try:
        import numpy  # noqa: F401
        import sklearn  # noqa: F401
        return True
    except Exception:
        return False


def _horizon_bucket(hours: int | None) -> str:
    h = hours or 0
    if h <= 48:
        return "h-short"
    if h <= 240:
        return "h-mid"
    return "h-long"


class OracleCalibrator:
    """Trains on graded claims and corrects new predictions. Persists to a pickle
    plus a JSON metrics sidecar the dashboard reads."""

    def __init__(self, model_path: str, *, min_samples: int = 30) -> None:
        self._path = Path(model_path)
        self._meta_path = self._path.with_suffix(".meta.json")
        self.min_samples = min_samples
        self._model = None  # dict of fitted pieces
        self._load()

    # ---- persistence ----------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            import joblib  # bundled with scikit-learn
            self._model = joblib.load(self._path)
        except Exception:
            self._model = None

    @property
    def ready(self) -> bool:
        return self._model is not None

    def metrics(self) -> dict:
        """Last-train metrics for the dashboard (or a not-ready stub)."""
        if self._meta_path.exists():
            try:
                return json.loads(self._meta_path.read_text())
            except (ValueError, OSError):
                pass
        return {"ready": False, "trainedAt": None, "samples": 0}

    # ---- training -------------------------------------------------------

    def train(self, rows: list[dict]) -> dict:
        """Fit on ``OracleStore.grades_for_training()`` rows. Returns a metrics
        dict (also persisted). No-op (returns progress) below the sample gate or
        when scikit-learn is unavailable."""
        n = len(rows)
        if not sklearn_available():
            meta = {"ready": False, "reason": "scikit-learn not installed",
                    "samples": n, "minSamples": self.min_samples, "trainedAt": None}
            self._write_meta(meta)
            return meta
        if n < self.min_samples:
            meta = {"ready": False, "reason": "cold-start", "samples": n,
                    "minSamples": self.min_samples, "trainedAt": None}
            self._write_meta(meta)
            return meta

        import numpy as np
        from sklearn.isotonic import IsotonicRegression
        from sklearn.linear_model import LogisticRegression

        conf = np.array([float(r["confidence"] or 0.0) for r in rows])
        hit = np.array([1.0 if r["outcome"] == "hit" else (0.5 if r["outcome"] == "partial" else 0.0)
                        for r in rows])
        weights = np.array([3.0 if r["userVerified"] else 1.0 for r in rows])

        # 1) Confidence calibration (isotonic, monotonic non-decreasing).
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        try:
            iso.fit(conf, hit, sample_weight=weights)
            iso_pts = [
                {"x": round(float(x), 3), "y": round(float(iso.predict([x])[0]), 3)}
                for x in [i / 10 for i in range(11)]
            ]
        except Exception:
            iso = None
            iso_pts = []

        # 2) Signal/source reliability (logistic over one-hot categoricals).
        feats = sorted({r["feature"] or "?" for r in rows})
        kinds = sorted({r["entityKind"] or "?" for r in rows})
        dirs = sorted({r["direction"] or "?" for r in rows})
        buckets = ["h-short", "h-mid", "h-long"]
        columns = (
            [f"feature={f}" for f in feats]
            + [f"kind={k}" for k in kinds]
            + [f"dir={d}" for d in dirs]
            + [f"hz={b}" for b in buckets]
        )

        def vec(r: dict) -> list[float]:
            row = []
            row += [1.0 if (r["feature"] or "?") == f else 0.0 for f in feats]
            row += [1.0 if (r["entityKind"] or "?") == k else 0.0 for k in kinds]
            row += [1.0 if (r["direction"] or "?") == d else 0.0 for d in dirs]
            hb = _horizon_bucket(r["horizonHours"])
            row += [1.0 if hb == b else 0.0 for b in buckets]
            return row

        X = np.array([vec(r) for r in rows])
        y_hit = np.array([1 if r["outcome"] == "hit" else 0 for r in rows])
        coefs: dict[str, float] = {}
        reliability_ok = len(set(y_hit.tolist())) > 1  # need both classes
        if reliability_ok:
            try:
                lr = LogisticRegression(max_iter=500, C=1.0)
                lr.fit(X, y_hit, sample_weight=weights)
                coefs = {c: round(float(w), 3) for c, w in zip(columns, lr.coef_[0])}
            except Exception:
                reliability_ok = False

        # 3) Per-domain difficulty (shrunk per-entity hit-fraction).
        global_mean = float(hit.mean())
        ent: dict[str, list[float]] = {}
        for r in rows:
            if r["entity"]:
                ent.setdefault(r["entity"], []).append(
                    1.0 if r["outcome"] == "hit" else (0.5 if r["outcome"] == "partial" else 0.0)
                )
        K = 5.0  # shrinkage strength toward the global mean
        difficulty = {
            e: round((sum(v) + K * global_mean) / (len(v) + K), 3)
            for e, v in ent.items()
        }

        self._model = {
            "iso_x": [p["x"] for p in iso_pts],
            "iso_y": [p["y"] for p in iso_pts],
            "columns": columns,
            "coefs": coefs,
            "difficulty": difficulty,
            "global_mean": round(global_mean, 3),
        }
        self._save()

        brier_vals = [float(r["brier"]) for r in rows if r["brier"] is not None]
        meta = {
            "ready": True,
            "trainedAt": int(time.time()),
            "samples": n,
            "minSamples": self.min_samples,
            "globalHitMean": round(global_mean, 3),
            "brier": round(sum(brier_vals) / len(brier_vals), 4) if brier_vals else None,
            "calibrationFit": iso_pts,
            "reliability": dict(sorted(coefs.items(), key=lambda kv: -abs(kv[1]))[:12]),
            "hardestEntities": sorted(
                ({"entity": e, "skill": s} for e, s in difficulty.items()),
                key=lambda d: d["skill"],
            )[:8],
        }
        self._write_meta(meta)
        return meta

    def _save(self) -> None:
        try:
            import joblib
            joblib.dump(self._model, self._path)
        except Exception:
            pass

    def _write_meta(self, meta: dict) -> None:
        try:
            self._meta_path.write_text(json.dumps(meta, indent=2))
        except OSError:
            pass

    # ---- inference ------------------------------------------------------

    def correct(self, claim: dict) -> dict:
        """Correct a fresh claim's stated confidence using the trained pieces.
        Returns calibrated confidence + reliability + domain difficulty + a note.
        Identity passthrough when not ready."""
        conf = float(claim.get("confidence") or 0.0)
        if not self.ready:
            return {"ready": False, "calibratedConfidence": round(conf, 3)}
        m = self._model or {}
        # Interpolate the isotonic calibration map.
        xs, ys = m.get("iso_x") or [], m.get("iso_y") or []
        cal = conf
        if xs and ys:
            if conf <= xs[0]:
                cal = ys[0]
            elif conf >= xs[-1]:
                cal = ys[-1]
            else:
                for i in range(1, len(xs)):
                    if conf <= xs[i]:
                        t = (conf - xs[i - 1]) / max(1e-6, xs[i] - xs[i - 1])
                        cal = ys[i - 1] + t * (ys[i] - ys[i - 1])
                        break
        entity = (claim.get("entity") or "").upper() or None
        difficulty = (m.get("difficulty") or {}).get(entity)
        note = ""
        if cal < conf - 0.1:
            note = "Historically overconfident on calls like this — trimmed."
        elif cal > conf + 0.1:
            note = "Historically under-credited here — nudged up."
        return {
            "ready": True,
            "statedConfidence": round(conf, 3),
            "calibratedConfidence": round(float(cal), 3),
            "domainSkill": difficulty,
            "globalMean": m.get("global_mean"),
            "note": note,
        }
