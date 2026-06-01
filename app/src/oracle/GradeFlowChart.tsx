// GradeFlowChart — the "what we predicted → what happened → why" flow for a
// single graded claim. A top-down flow of nodes connected by arrows:
//
//   [ The Call ]  →  [ What we expected ]  →  [ 24h | 7d | 30d checkpoints ]
//        →  [ Verdict + reasoning + evidence ]
//
// Reads entirely from a ClaimDetail; renders a "pending" stub when ungraded.

import type { ClaimDetail, Grade } from "./oracle";
import { OUTCOME_COLOR, outcomeLabel } from "./oracle";

function Arrow() {
  return <div className="ora-flow__arrow" aria-hidden="true">▼</div>;
}

function ScoreRing({ score, color }: { score: number; color: string }) {
  const r = 15;
  const c = 2 * Math.PI * r;
  const off = c * (1 - Math.max(0, Math.min(100, score)) / 100);
  return (
    <svg width="38" height="38" className="ora-ring" viewBox="0 0 38 38">
      <circle cx="19" cy="19" r={r} className="ora-ring__track" />
      <circle
        cx="19" cy="19" r={r} className="ora-ring__val"
        stroke={color} strokeDasharray={c} strokeDashoffset={off}
        transform="rotate(-90 19 19)"
      />
      <text x="19" y="23" textAnchor="middle" className="ora-ring__txt">{score}</text>
    </svg>
  );
}

const SOURCE_LABEL: Record<string, string> = {
  objective: "price data",
  "llm-local": "AI judge",
  "llm-cloud": "AI judge (cloud)",
  user: "you",
};

function CheckpointNode({ grade }: { grade: Grade }) {
  const color = OUTCOME_COLOR[grade.outcome] ?? "#64748b";
  return (
    <div className="ora-cp" style={{ borderColor: color }}>
      <div className="ora-cp__head">
        <span className="ora-cp__when">{grade.checkpoint}</span>
        <span className="ora-cp__badge" style={{ color }}>{outcomeLabel(grade.outcome)}</span>
      </div>
      <ScoreRing score={grade.score} color={color} />
      <div className="ora-cp__src">{SOURCE_LABEL[grade.source] ?? grade.source}</div>
    </div>
  );
}

export function GradeFlowChart({ claim }: { claim: ClaimDetail }) {
  const grades = claim.grades ?? [];
  const terminal = grades[grades.length - 1] ?? null;
  const verdictColor = terminal ? OUTCOME_COLOR[terminal.outcome] ?? "#64748b" : "#64748b";
  const dir = claim.direction ?? "—";
  const evidence = terminal?.evidence ?? {};
  const pct = typeof evidence.changePct === "number" ? (evidence.changePct as number) : null;

  return (
    <div className="ora-flow">
      {/* 1 — the call */}
      <div className="ora-flow__node ora-flow__node--call">
        <div className="ora-flow__tag">THE CALL</div>
        <div className="ora-flow__claim">{claim.claim}</div>
        <div className="ora-flow__meta">
          {claim.entity && <span className="ora-chip">{claim.entity}</span>}
          <span className="ora-chip">{claim.feature}</span>
          {claim.confidence != null && (
            <span className="ora-chip">conf {(claim.confidence * 100).toFixed(0)}%</span>
          )}
        </div>
      </div>

      <Arrow />

      {/* 2 — what we expected */}
      <div className="ora-flow__node ora-flow__node--expect">
        <div className="ora-flow__tag">WHAT WE EXPECTED</div>
        <div className="ora-flow__expect">
          <span className={`ora-dir ora-dir--${dir}`}>{dir}</span>
          {claim.magnitude != null && <span> · target {claim.magnitude > 0 ? "+" : ""}{claim.magnitude}%</span>}
          {claim.horizonHours != null && <span> · within ~{Math.round(claim.horizonHours / 24) || 1}d</span>}
        </div>
      </div>

      <Arrow />

      {/* 3 — checkpoints */}
      {grades.length > 0 ? (
        <div className="ora-flow__cps">
          {grades.map((g) => <CheckpointNode key={g.id} grade={g} />)}
        </div>
      ) : (
        <div className="ora-flow__node ora-flow__node--pending">
          ⏳ Not yet graded — waiting for the first checkpoint to elapse.
        </div>
      )}

      {terminal && (
        <>
          <Arrow />
          {/* 4 — verdict + reasoning */}
          <div className="ora-flow__node ora-flow__node--verdict" style={{ borderColor: verdictColor }}>
            <div className="ora-flow__tag">
              {terminal.outcome === "miss" ? "WHY IT DIDN'T HAPPEN" : "WHY IT HAPPENED"}
            </div>
            <div className="ora-flow__verdict" style={{ color: verdictColor }}>
              {outcomeLabel(terminal.outcome)} · {terminal.score}/100
              {terminal.failureTag && <span className="ora-tag">{terminal.failureTag}</span>}
            </div>
            {terminal.reason && <p className="ora-flow__reason">{terminal.reason}</p>}
            {pct != null && (
              <div className="ora-flow__evidence">
                Price moved <b style={{ color: pct >= 0 ? "#22c55e" : "#ef4444" }}>
                  {pct >= 0 ? "+" : ""}{pct.toFixed(2)}%
                </b>
                {typeof evidence.entry === "number" && typeof evidence.exit === "number" && (
                  <> ({(evidence.entry as number).toFixed(2)} → {(evidence.exit as number).toFixed(2)})</>
                )}
              </div>
            )}
            {typeof evidence.text === "string" && evidence.text && (
              <details className="ora-flow__ev-text">
                <summary>Evidence the judge saw</summary>
                <pre>{evidence.text as string}</pre>
              </details>
            )}
          </div>
        </>
      )}
    </div>
  );
}
