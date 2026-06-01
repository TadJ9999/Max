// Track-record bars — per-entity average score, colored green→red by skill.
// A compact horizontal bar list; the hardest/weakest domains sink to the bottom.

interface Props {
  rows: { entity: string; count: number; avgScore: number }[];
  limit?: number;
}

function scoreColor(s: number): string {
  if (s >= 70) return "#22c55e";
  if (s >= 50) return "#84cc16";
  if (s >= 35) return "#eab308";
  return "#ef4444";
}

export function TrackRecordChart({ rows, limit = 10 }: Props) {
  const data = [...rows].sort((a, b) => b.avgScore - a.avgScore).slice(0, limit);
  if (data.length === 0) {
    return <div className="ora-track__empty">No per-entity track record yet.</div>;
  }
  return (
    <div className="ora-track">
      {data.map((r) => (
        <div key={r.entity} className="ora-track__row" title={`${r.count} graded`}>
          <span className="ora-track__name">{r.entity}</span>
          <div className="ora-track__bar">
            <div
              className="ora-track__fill"
              style={{ width: `${Math.max(3, r.avgScore)}%`, background: scoreColor(r.avgScore) }}
            />
          </div>
          <span className="ora-track__val">{r.avgScore.toFixed(0)}</span>
          <span className="ora-track__n">·{r.count}</span>
        </div>
      ))}
    </div>
  );
}
