import { useState, useEffect } from "react";
import { getHeatmap, type CountryStat, type Article } from "../osint/osint";
import { ENGINE_URL } from "../engine";

const SEV_COLOR = ["#22d3ee", "#f59e0b", "#f97316", "#f43f5e"] as const;
const SEV_LABEL = ["Low", "Medium", "High", "Critical"] as const;

async function fetchArticles(limit = 20): Promise<Article[]> {
  try {
    const r = await fetch(`${ENGINE_URL}/osint/articles?limit=${limit}`);
    if (!r.ok) return [];
    return (await r.json()) as Article[];
  } catch { return []; }
}

export function OsintTab() {
  const [countries, setCountries] = useState<CountryStat[]>([]);
  const [articles, setArticles] = useState<Article[]>([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    const [hm, arts] = await Promise.all([getHeatmap(), fetchArticles(20)]);
    if (hm) {
      const sorted = [...hm.countries].sort((a, b) => b.severity - a.severity || b.intensity - a.intensity);
      setCountries(sorted.slice(0, 12));
    }
    setArticles(arts);
    setLoading(false);
  };

  useEffect(() => { void load(); }, []);

  if (loading) return <div className="mob-loading">Loading intel…</div>;

  return (
    <div className="mob-scroll">
      <div className="mob-section-head">
        <span className="mob-section-title">Hotspots</span>
        <button className="mob-btn" onClick={() => void load()}>↻</button>
      </div>

      {countries.map((c) => (
        <div key={c.iso} className="mob-card mob-hotspot">
          <span className="mob-hotspot__dot" style={{ color: SEV_COLOR[c.severity] }}>■</span>
          <span className="mob-hotspot__name">{c.name}</span>
          <span className="mob-hotspot__count">{c.articleCount} art.</span>
          <span className="mob-hotspot__sev" style={{ color: SEV_COLOR[c.severity] }}>
            {SEV_LABEL[c.severity]}
          </span>
        </div>
      ))}

      {articles.length > 0 && (
        <>
          <div className="mob-section-head" style={{ marginTop: 12 }}>
            <span className="mob-section-title">Latest</span>
          </div>
          {articles.map((a, i) => (
            <a
              key={i}
              className="mob-card mob-article"
              href={a.url}
              target="_blank"
              rel="noopener noreferrer"
            >
              <div className="mob-article__title">{a.title}</div>
              <div className="mob-article__meta">
                <span style={{ color: SEV_COLOR[a.severity] }}>{a.severityLabel}</span>
                {a.country && <> · {a.country}</>}
                {" · "}{a.domain}
              </div>
            </a>
          ))}
        </>
      )}
    </div>
  );
}
