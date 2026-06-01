// HindsightPanel — the inline "track record" strip shown under a freshly
// generated Apollo / Market / OSINT report. Two columns: predictions we called
// right, and ones that didn't pan out — each with the reason, grounded in real
// graded outcomes. Renders nothing until there's something relevant to show.

import { useEffect, useState } from "react";
import { getHindsight, outcomeLabel, type Hindsight, type HindsightItem } from "./oracle";
import { OwlLogo } from "./OwlLogo";

function Item({ it, kind }: { it: HindsightItem; kind: "right" | "missed" }) {
  return (
    <li className={`ora-hs__item ora-hs__item--${kind}`}>
      <div className="ora-hs__claim">
        {it.entity && <span className="ora-hs__entity">{it.entity}</span>}
        {it.claim}
      </div>
      <div className="ora-hs__meta">
        <span className="ora-hs__verdict">
          {outcomeLabel(it.outcome)}{it.score != null ? ` · ${it.score}/100` : ""}
        </span>
        {it.checkpoint && <span className="ora-hs__cp">@{it.checkpoint}</span>}
        {it.failureTag && <span className="ora-hs__tag">{it.failureTag}</span>}
      </div>
      {it.reason && <div className="ora-hs__reason">{it.reason}</div>}
    </li>
  );
}

export function HindsightPanel({
  feature,
  entity,
  query,
}: {
  feature: string;
  entity?: string;
  query?: string;
}) {
  const [hs, setHs] = useState<Hindsight | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!entity && !query) return;
    let alive = true;
    setLoading(true);
    void (async () => {
      const data = await getHindsight({ feature, entity, query, k: 5 });
      if (alive) {
        setHs(data);
        setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [feature, entity, query]);

  const empty = hs && hs.right.length === 0 && hs.missed.length === 0;
  if (loading && !hs) {
    return (
      <div className="ora-hs ora-hs--loading">
        <OwlLogo size={14} /> Checking our track record…
      </div>
    );
  }
  if (!hs || empty) return null;

  return (
    <div className="ora-hs">
      <header className="ora-hs__head">
        <OwlLogo size={15} glow />
        <span>Oracle hindsight — how our past calls on this actually played out</span>
      </header>
      <div className="ora-hs__cols">
        <div className="ora-hs__col">
          <div className="ora-hs__col-title ora-hs__col-title--right">✓ Called right</div>
          {hs.right.length ? (
            <ul className="ora-hs__list">
              {hs.right.map((it) => <Item key={`r${it.claimId}`} it={it} kind="right" />)}
            </ul>
          ) : (
            <div className="ora-hs__none">No prior wins on this yet.</div>
          )}
        </div>
        <div className="ora-hs__col">
          <div className="ora-hs__col-title ora-hs__col-title--missed">✗ Didn't pan out</div>
          {hs.missed.length ? (
            <ul className="ora-hs__list">
              {hs.missed.map((it) => <Item key={`m${it.claimId}`} it={it} kind="missed" />)}
            </ul>
          ) : (
            <div className="ora-hs__none">No prior misses on this yet.</div>
          )}
        </div>
      </div>
    </div>
  );
}
