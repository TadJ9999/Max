// Oracle — the 🦉 Learning Hub tab. Mission control for the self-grading track
// record: headline accuracy/calibration stats, a filterable claims table
// (graded + pending), and a click-through drawer with the grade flow chart,
// source report, and a manual-override control.

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getClaim, getClaims, getStats, gradeNow, overrideGrade, retrain,
  OUTCOME_COLOR, outcomeLabel, timeAgo,
  type Claim, type ClaimDetail, type OracleStats, type Outcome,
} from "./oracle";
import { OwlLogo } from "./OwlLogo";
import { CalibrationChart } from "./CalibrationChart";
import { TrackRecordChart } from "./TrackRecordChart";
import { GradeFlowChart } from "./GradeFlowChart";
import "./Oracle.css";

const FEATURES = ["", "apollo", "market", "osint"];
const STATUSES = ["", "pending", "graded"];
const OUTCOMES: Outcome[] = ["hit", "partial", "miss", "too-early"];
const TAGS = [
  "wrong-direction", "wrong-timing", "wrong-magnitude", "black-swan",
  "data-gap", "overconfidence", "partial-correct",
];

function StatCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="ora-stat">
      <div className="ora-stat__val">{value}</div>
      <div className="ora-stat__label">{label}</div>
      {hint && <div className="ora-stat__hint">{hint}</div>}
    </div>
  );
}

function StatusChip({ claim }: { claim: Claim }) {
  const g = claim.latestGrade;
  const outcome = g?.outcome ?? "pending";
  const color = OUTCOME_COLOR[outcome] ?? "#64748b";
  return (
    <span className="ora-statuschip" style={{ color, borderColor: color }}>
      {claim.status === "pending" && !g ? "Pending" : outcomeLabel(outcome)}
    </span>
  );
}

// ── Manual override form ──────────────────────────────────────────────────
function OverrideForm({ claim, onSaved }: { claim: ClaimDetail; onSaved: () => void }) {
  const last = claim.grades[claim.grades.length - 1];
  const [score, setScore] = useState(last?.score ?? 70);
  const [outcome, setOutcome] = useState<Outcome>(last?.outcome ?? "hit");
  const [tag, setTag] = useState<string>(last?.failureTag ?? "");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    await overrideGrade(claim.id, {
      score, outcome, failure_tag: outcome === "hit" ? null : (tag || null), reason,
    });
    setSaving(false);
    onSaved();
  };

  return (
    <div className="ora-override">
      <div className="ora-override__title">Override grade — your verdict trains the model harder</div>
      <div className="ora-override__row">
        <label>Outcome
          <select value={outcome} onChange={(e) => setOutcome(e.target.value as Outcome)}>
            {OUTCOMES.map((o) => <option key={o} value={o}>{outcomeLabel(o)}</option>)}
          </select>
        </label>
        <label>Score {score}
          <input type="range" min={0} max={100} value={score}
            onChange={(e) => setScore(Number(e.target.value))} />
        </label>
        {outcome !== "hit" && (
          <label>Failure
            <select value={tag} onChange={(e) => setTag(e.target.value)}>
              <option value="">—</option>
              {TAGS.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </label>
        )}
      </div>
      <input className="ora-override__reason" placeholder="Reason (optional)"
        value={reason} onChange={(e) => setReason(e.target.value)} />
      <button className="ora-btn ora-btn--primary" onClick={() => void save()} disabled={saving}>
        {saving ? "Saving…" : "Save verdict"}
      </button>
    </div>
  );
}

// ── Detail drawer ─────────────────────────────────────────────────────────
function ClaimDrawer({ id, onClose, onChanged }: {
  id: number; onClose: () => void; onChanged: () => void;
}) {
  const [detail, setDetail] = useState<ClaimDetail | null>(null);
  const load = useCallback(async () => setDetail(await getClaim(id)), [id]);
  useEffect(() => { void load(); }, [load]);

  return (
    <div className="ora-drawer">
      <div className="ora-drawer__backdrop" onClick={onClose} />
      <aside className="ora-drawer__panel">
        <header className="ora-drawer__head">
          <span>Prediction #{id}</span>
          <button className="ora-drawer__close" onClick={onClose}>×</button>
        </header>
        {!detail ? (
          <div className="ora-drawer__loading">Loading…</div>
        ) : (
          <div className="ora-drawer__body">
            <GradeFlowChart claim={detail} />
            <OverrideForm claim={detail} onSaved={() => { void load(); onChanged(); }} />
            {detail.report && (
              <details className="ora-source">
                <summary>Source report — {detail.report.title}</summary>
                <pre className="ora-source__body">{detail.report.body}</pre>
              </details>
            )}
          </div>
        )}
      </aside>
    </div>
  );
}

export function OracleView({ onClose }: { onClose?: () => void } = {}) {
  const [stats, setStats] = useState<OracleStats | null>(null);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [status, setStatus] = useState("");
  const [feature, setFeature] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    const [s, c] = await Promise.all([
      getStats(),
      getClaims({ status: status || undefined, feature: feature || undefined, limit: 300 }),
    ]);
    setStats(s);
    setClaims(c);
  }, [status, feature]);

  useEffect(() => { void loadAll(); }, [loadAll]);

  const flash = (m: string) => { setToast(m); window.setTimeout(() => setToast(null), 3500); };

  const onGradeNow = async () => {
    setBusy(true);
    const r = await gradeNow();
    setBusy(false);
    flash(r ? `Graded ${r.graded} checkpoint${r.graded === 1 ? "" : "s"}.` : "Grading failed.");
    void loadAll();
  };

  const onRetrain = async () => {
    setBusy(true);
    const m = await retrain();
    setBusy(false);
    flash(
      m?.ready ? `Calibrator retrained on ${m.samples} graded claims.`
        : `Need ${m?.minSamples ?? 30} graded claims to calibrate (have ${m?.samples ?? 0}).`,
    );
    void loadAll();
  };

  const model = stats?.model;
  const modelStatus = useMemo(() => {
    if (!model) return "—";
    if (model.ready) return "Trained";
    return `${model.samples ?? 0}/${model.minSamples ?? 30}`;
  }, [model]);

  return (
    <div className="ora">
      <header className="ora__bar">
        <div className="ora__title">
          <OwlLogo size={22} glow />
          Oracle
          <span className="ora__subtitle">self-grading prediction track record</span>
        </div>
        <div className="ora__actions">
          <button className="ora-btn" onClick={() => void onGradeNow()} disabled={busy}>
            Grade now
          </button>
          <button className="ora-btn" onClick={() => void onRetrain()} disabled={busy}>
            Retrain model
          </button>
          {onClose && <button className="ora-btn ora-btn--close" onClick={onClose}>×</button>}
        </div>
      </header>

      {toast && <div className="ora__toast">{toast}</div>}

      {/* headline stats */}
      <div className="ora__stats">
        <StatCard label="Accuracy"
          value={stats?.accuracy != null ? `${(stats.accuracy * 100).toFixed(0)}%` : "—"}
          hint={`${stats?.resolvedGrades ?? 0} graded`} />
        <StatCard label="Brier"
          value={stats?.avgBrier != null ? stats.avgBrier.toFixed(3) : "—"}
          hint="lower = sharper" />
        <StatCard label="Avg score"
          value={stats?.avgScore != null ? stats.avgScore.toFixed(0) : "—"} hint="/ 100" />
        <StatCard label="Pending" value={String(stats?.pending ?? 0)} hint="awaiting outcome" />
        <StatCard label="Calibrator" value={modelStatus}
          hint={model?.trainedAt ? timeAgo(model.trainedAt) : "cold start"} />
      </div>

      {/* charts + failure modes */}
      <div className="ora__panels">
        <section className="ora-card">
          <h3 className="ora-card__h">Calibration</h3>
          <CalibrationChart curve={stats?.calibrationCurve ?? []} fit={model?.calibrationFit} />
          <p className="ora-card__note">Stated confidence vs. how often it actually came true.</p>
        </section>
        <section className="ora-card">
          <h3 className="ora-card__h">Per-entity track record</h3>
          <TrackRecordChart rows={stats?.perEntity ?? []} />
        </section>
        <section className="ora-card">
          <h3 className="ora-card__h">Top failure modes</h3>
          <div className="ora-fails">
            {Object.entries(stats?.failureModes ?? {}).sort((a, b) => b[1] - a[1]).map(([tag, n]) => (
              <div key={tag} className="ora-fail">
                <span className="ora-fail__tag">{tag}</span>
                <span className="ora-fail__n">{n}</span>
              </div>
            ))}
            {Object.keys(stats?.failureModes ?? {}).length === 0 && (
              <div className="ora-fails__empty">No misses recorded yet.</div>
            )}
          </div>
        </section>
      </div>

      {/* claims table */}
      <div className="ora__table-head">
        <h3 className="ora-card__h">Predictions</h3>
        <div className="ora__filters">
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            {STATUSES.map((s) => <option key={s} value={s}>{s ? s : "all status"}</option>)}
          </select>
          <select value={feature} onChange={(e) => setFeature(e.target.value)}>
            {FEATURES.map((f) => <option key={f} value={f}>{f ? f : "all features"}</option>)}
          </select>
        </div>
      </div>
      <div className="ora-table">
        <div className="ora-table__head">
          <span>Status</span><span>Prediction</span><span>Entity</span>
          <span>Conf</span><span>Score</span><span>Age</span>
        </div>
        <div className="ora-table__body">
          {claims.length === 0 && (
            <div className="ora-table__empty">
              No predictions captured yet. Run an Apollo or Market report — Oracle extracts and
              tracks its claims automatically.
            </div>
          )}
          {claims.map((c) => (
            <button key={c.id} className="ora-table__row" onClick={() => setSelected(c.id)}>
              <span><StatusChip claim={c} /></span>
              <span className="ora-table__claim">{c.claim}</span>
              <span className="ora-table__entity">{c.entity ?? "—"}</span>
              <span>{c.confidence != null ? `${(c.confidence * 100).toFixed(0)}%` : "—"}</span>
              <span style={{ color: c.latestGrade ? OUTCOME_COLOR[c.latestGrade.outcome] : "#64748b" }}>
                {c.latestGrade ? c.latestGrade.score : "—"}
              </span>
              <span className="ora-table__age">{timeAgo(c.createdAt)}</span>
            </button>
          ))}
        </div>
      </div>

      {selected != null && (
        <ClaimDrawer id={selected} onClose={() => setSelected(null)} onChanged={() => void loadAll()} />
      )}
    </div>
  );
}
