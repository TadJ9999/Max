// Full settings view — one-stop configuration for every engine setting.
// Organised into collapsible sections. Changes are applied immediately via
// the /config PUT endpoint; API keys go through /config/key (write-only).

import { useCallback, useEffect, useState } from "react";
import {
  getConfig,
  updateConfig,
  setApiKey,
  getUserProfile,
  upsertProfileItem,
  deleteProfileItem,
  type ConfigPatch,
  type EngineConfigView,
  type ProfileItem,
} from "../config";
import { ModelManager } from "./ModelManager";
import { ENGINE_URL } from "../engine";
import "./Settings.css";
import "./ModelManager.css";

// ── tiny helpers ─────────────────────────────────────────────────────────────

function Toggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      className={`stg-toggle${on ? " stg-toggle--on" : ""}`}
      onClick={() => onChange(!on)}
      aria-pressed={on}
    >
      <span className="stg-toggle__knob" />
    </button>
  );
}

function NumField({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  value: number;
  min?: number;
  max?: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="stg-num">
      <span className="stg-num__label">{label}</span>
      <input
        className="stg-num__input"
        type="number"
        value={value}
        min={min}
        max={max}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  );
}

function TextField({
  label,
  value,
  onChange,
  placeholder,
  mono,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  mono?: boolean;
}) {
  return (
    <label className="stg-text">
      <span className="stg-text__label">{label}</span>
      <input
        className={`stg-text__input${mono ? " stg-text__input--mono" : ""}`}
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

function Section({
  title,
  glyph,
  children,
  defaultOpen = true,
}: {
  title: string;
  glyph: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={`stg-section${open ? " is-open" : ""}`}>
      <button className="stg-section__head" onClick={() => setOpen((v) => !v)}>
        <span className="stg-section__glyph">{glyph}</span>
        <span className="stg-section__title">{title}</span>
        <span className="stg-section__chevron">{open ? "▲" : "▼"}</span>
      </button>
      {open && <div className="stg-section__body">{children}</div>}
    </div>
  );
}

function ApiKeyField({
  label,
  envName,
  isSet,
  onSaved,
}: {
  label: string;
  envName: string;
  isSet: boolean;
  onSaved: (cfg: EngineConfigView) => void;
}) {
  const [val, setVal] = useState("");
  const [saving, setSaving] = useState(false);
  const [ok, setOk] = useState(false);

  const save = async () => {
    if (!val.trim()) return;
    setSaving(true);
    const next = await setApiKey(envName, val.trim());
    if (next) {
      onSaved(next);
      setOk(true);
      setVal("");
      window.setTimeout(() => setOk(false), 2000);
    }
    setSaving(false);
  };

  return (
    <div className="stg-key">
      <div className="stg-key__head">
        <span className="stg-key__label">{label}</span>
        <span className={`stg-key__badge${isSet ? " is-set" : ""}`}>
          {isSet ? "● set" : "○ not set"}
        </span>
        {ok && <span className="stg-key__ok">✓ saved</span>}
      </div>
      <div className="stg-key__row">
        <input
          className="stg-key__input"
          type="password"
          placeholder={isSet ? "Paste new key to replace…" : `Paste ${envName}…`}
          value={val}
          onChange={(e) => setVal(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void save()}
          autoComplete="off"
        />
        <button
          className="stg-key__save"
          onClick={() => void save()}
          disabled={saving || !val.trim()}
        >
          {saving ? "…" : "save"}
        </button>
      </div>
    </div>
  );
}

function FeedList({
  feeds,
  onChange,
}: {
  feeds: string[];
  onChange: (feeds: string[]) => void;
}) {
  const [newFeed, setNewFeed] = useState("");
  const add = () => {
    const f = newFeed.trim();
    if (!f || feeds.includes(f)) return;
    onChange([...feeds, f]);
    setNewFeed("");
  };
  return (
    <div className="stg-list">
      <span className="stg-list__label">RSS Feeds</span>
      <ul className="stg-list__items">
        {feeds.map((f) => (
          <li key={f} className="stg-list__item">
            <span className="stg-list__val">{f}</span>
            <button className="stg-list__rm" onClick={() => onChange(feeds.filter((x) => x !== f))}>×</button>
          </li>
        ))}
      </ul>
      <div className="stg-list__add">
        <input
          className="stg-list__input"
          placeholder="https://example.com/rss"
          value={newFeed}
          onChange={(e) => setNewFeed(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()}
        />
        <button className="stg-list__addbtn" onClick={add}>add</button>
      </div>
    </div>
  );
}

function PathList({
  paths,
  onChange,
}: {
  paths: string[];
  onChange: (paths: string[]) => void;
}) {
  const [newPath, setNewPath] = useState("");
  const add = () => {
    const p = newPath.trim();
    if (!p || paths.includes(p)) return;
    onChange([...paths, p]);
    setNewPath("");
  };
  return (
    <div className="stg-list">
      <ul className="stg-list__items">
        {paths.length === 0 && <li className="stg-list__empty">none yet</li>}
        {paths.map((p) => (
          <li key={p} className="stg-list__item">
            <span className="stg-list__val">{p}</span>
            <button className="stg-list__rm" onClick={() => onChange(paths.filter((x) => x !== p))}>×</button>
          </li>
        ))}
      </ul>
      <div className="stg-list__add">
        <input
          className="stg-list__input"
          placeholder="C:/path/to/folder"
          value={newPath}
          onChange={(e) => setNewPath(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()}
        />
        <button className="stg-list__addbtn" onClick={add}>add</button>
      </div>
    </div>
  );
}

// ── Egress hint ───────────────────────────────────────────────────────────────

function EgressHint({ sources }: { sources: string }) {
  return (
    <p className="stg-hint stg-egress">
      <span className="stg-egress__icon">↑</span>
      <span>
        <strong>Outbound:</strong> calls {sources}. Data leaves your machine while this module is active.
      </span>
    </p>
  );
}

// ── Egress log viewer ─────────────────────────────────────────────────────────

type EgressEntry = {
  ts: string;
  provider: string;
  model: string;
  action: string;
  in_tokens: number;
  out_tokens: number;
};

function EgressLogSection() {
  const [entries, setEntries] = useState<EgressEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const { ENGINE_URL } = await import("../engine");
      const r = await fetch(`${ENGINE_URL}/egress/log?limit=50`);
      if (!r.ok) return;
      const d = await r.json() as { entries: EgressEntry[]; total_lines: number };
      setEntries(d.entries);
      setTotal(d.total_lines);
    } catch { /* offline */ }
  }, []);

  const clear = async () => {
    setBusy(true);
    try {
      const { ENGINE_URL } = await import("../engine");
      await fetch(`${ENGINE_URL}/egress/log`, { method: "DELETE" });
      setEntries([]);
      setTotal(0);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => { void load(); }, [load]);

  return (
    <div className="stg-egress-log">
      <div className="stg-egress-log__header">
        <span className="stg-hint">{total} total entries (showing last 50)</span>
        <div className="stg-egress-log__btns">
          <button className="stg-btn stg-btn--sm" onClick={() => void load()}>↻ refresh</button>
          <button className="stg-btn stg-btn--sm stg-btn--danger" onClick={() => void clear()} disabled={busy}>
            clear log
          </button>
        </div>
      </div>
      {entries.length === 0 ? (
        <p className="stg-hint">No egress entries recorded.</p>
      ) : (
        <table className="stg-egress-log__table">
          <thead>
            <tr>
              <th>Time</th><th>Provider</th><th>Model</th><th>Action</th><th>In</th><th>Out</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e, i) => (
              <tr key={i} className={e.action.endsWith("_done") ? "stg-egress-log__done" : ""}>
                <td className="stg-egress-log__ts">{e.ts.replace("T", " ").replace("Z", "")}</td>
                <td>{e.provider}</td>
                <td className="stg-egress-log__model">{e.model}</td>
                <td>{e.action}</td>
                <td className="stg-egress-log__tok">{e.in_tokens}</td>
                <td className="stg-egress-log__tok">{e.out_tokens}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ── Analytics section ─────────────────────────────────────────────────────────

type AnalyticsSummary = {
  days: number;
  total_in_tokens: number;
  total_out_tokens: number;
  total_tokens: number;
  total_cost_usd: number;
  requests: number;
  top_feature: string;
  top_model: string;
};

type DailyPoint = {
  day: string;
  total_tokens: number;
  total_cost_usd: number;
  by_feature: Record<string, number>;
};

type BreakdownRow = {
  feature: string;
  model: string;
  provider: string;
  in_tokens: number;
  out_tokens: number;
  total_tokens: number;
  cost_usd: number;
  requests: number;
};

const FEATURE_ORDER = [
  "apollo", "osint", "market", "polymarket", "sentinel", "voice", "rag", "chat", "delegate", "api", "system",
];

const FEATURE_COLOR: Record<string, string> = {
  apollo:     "var(--ana-apollo)",
  osint:      "var(--ana-osint)",
  market:     "var(--ana-market)",
  polymarket: "var(--ana-polymarket)",
  sentinel:   "var(--ana-sentinel)",
  voice:      "var(--ana-voice)",
  rag:        "var(--ana-rag)",
  chat:       "var(--ana-chat)",
  delegate:   "var(--ana-delegate)",
  api:        "var(--ana-api)",
  system:     "var(--stg-muted)",
};

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "k";
  return String(n);
}

function fmtCost(usd: number): string {
  if (usd === 0) return "$0.00";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

// ── Pure SVG stacked bar chart ───────────────────────────────────────────────

type TooltipState = { x: number; y: number; day: string; feature: string; tokens: number } | null;

function StackedBarChart({ series, days }: { series: DailyPoint[]; days: number }) {
  const [tip, setTip] = useState<TooltipState>(null);

  // For 90d, bin into weekly groups
  const bins: DailyPoint[] = (() => {
    if (days <= 30 || series.length <= 30) return series;
    const result: DailyPoint[] = [];
    for (let i = 0; i < series.length; i += 7) {
      const week = series.slice(i, i + 7);
      const merged: DailyPoint = {
        day: week[0].day,
        total_tokens: week.reduce((s, d) => s + d.total_tokens, 0),
        total_cost_usd: week.reduce((s, d) => s + d.total_cost_usd, 0),
        by_feature: {},
      };
      for (const d of week) {
        for (const [feat, tok] of Object.entries(d.by_feature)) {
          merged.by_feature[feat] = (merged.by_feature[feat] || 0) + tok;
        }
      }
      result.push(merged);
    }
    return result;
  })();

  if (bins.length === 0) return null;

  const W = 700, H = 96, LABEL_H = 16, BAR_H = H - LABEL_H;
  const maxTok = Math.max(...bins.map((b) => b.total_tokens), 1);
  const barW = Math.max(4, Math.floor((W - 8) / bins.length) - 2);
  const gap = Math.floor((W - 8) / bins.length);

  const features = FEATURE_ORDER.filter((f) => bins.some((b) => b.by_feature[f]));

  return (
    <div className="ana-chart-wrap" onMouseLeave={() => setTip(null)}>
      <svg className="ana-chart" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        {bins.map((b, bi) => {
          const x = 4 + bi * gap;
          let stackY = BAR_H;
          return (
            <g key={bi}>
              {features.map((feat) => {
                const tok = b.by_feature[feat] || 0;
                if (!tok) return null;
                const barPx = Math.max(2, Math.round((tok / maxTok) * BAR_H));
                stackY -= barPx;
                const color = FEATURE_COLOR[feat] || "var(--stg-muted)";
                return (
                  <rect
                    key={feat}
                    x={x}
                    y={stackY}
                    width={barW}
                    height={barPx}
                    fill={color}
                    opacity={0.85}
                    rx={1}
                    onMouseEnter={(e) => {
                      const rect = (e.currentTarget as SVGRectElement).closest(".ana-chart-wrap")?.getBoundingClientRect();
                      const svgRect = (e.currentTarget as SVGRectElement).getBoundingClientRect();
                      if (rect) {
                        setTip({
                          x: svgRect.left - rect.left + barW / 2,
                          y: svgRect.top - rect.top - 4,
                          day: b.day,
                          feature: feat,
                          tokens: tok,
                        });
                      }
                    }}
                  />
                );
              })}
              {bi % 7 === 0 && (
                <text
                  x={x + barW / 2}
                  y={H - 2}
                  textAnchor="middle"
                  fontSize={9}
                  fill="var(--stg-muted)"
                >
                  {b.day.slice(5)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      {tip && (
        <div
          className="ana-tooltip"
          style={{ left: tip.x, top: tip.y, transform: "translate(-50%, -100%)" }}
        >
          {tip.day} · {tip.feature} · {fmtNum(tip.tokens)} tokens
        </div>
      )}
      <div className="ana-legend">
        {features.map((f) => (
          <span key={f} className="ana-legend__item">
            <span className="ana-legend__dot" style={{ background: FEATURE_COLOR[f] }} />
            {f}
          </span>
        ))}
      </div>
    </div>
  );
}

// ── AnalyticsSection ─────────────────────────────────────────────────────────

function AnalyticsSection() {
  const [range, setRange] = useState<7 | 30 | 90>(30);
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [daily, setDaily] = useState<DailyPoint[]>([]);
  const [rows, setRows] = useState<BreakdownRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [clearing, setClearing] = useState(false);

  const load = useCallback(async (d: number) => {
    setBusy(true);
    try {
      const { ENGINE_URL } = await import("../engine");
      const [sum, day, brk] = await Promise.all([
        fetch(`${ENGINE_URL}/analytics/summary?days=${d}`).then((r) => r.ok ? r.json() as Promise<AnalyticsSummary> : null),
        fetch(`${ENGINE_URL}/analytics/daily?days=${d}`).then((r) => r.ok ? r.json() as Promise<{ series: DailyPoint[] }> : null),
        fetch(`${ENGINE_URL}/analytics/breakdown?days=${d}`).then((r) => r.ok ? r.json() as Promise<{ rows: BreakdownRow[] }> : null),
      ]);
      if (sum) setSummary(sum);
      if (day) setDaily(day.series);
      if (brk) setRows(brk.rows);
    } catch { /* offline */ }
    finally { setBusy(false); }
  }, []);

  useEffect(() => { void load(range); }, [load, range]);

  const reset = async () => {
    if (!confirm("Clear all token usage history? This cannot be undone.")) return;
    setClearing(true);
    try {
      const { ENGINE_URL } = await import("../engine");
      await fetch(`${ENGINE_URL}/analytics/reset`, { method: "DELETE" });
      setSummary(null);
      setDaily([]);
      setRows([]);
    } finally { setClearing(false); }
  };

  return (
    <div className="stg-row-group" style={{ flexDirection: "column", gap: 12 }}>
      {/* controls row */}
      <div className="ana-controls">
        <div className="stg-seg">
          {([7, 30, 90] as const).map((d) => (
            <button
              key={d}
              className={`stg-seg__btn${range === d ? " stg-seg__btn--on" : ""}`}
              onClick={() => setRange(d)}
            >
              {d}d
            </button>
          ))}
        </div>
        <button
          className="stg-btn stg-btn--sm"
          onClick={() => void load(range)}
          disabled={busy}
        >
          ↻ refresh
        </button>
      </div>

      {/* stat cards */}
      <div className="ana-stats">
        <div className="ana-stat">
          <div className="ana-stat__label">Total Tokens</div>
          <div className="ana-stat__value">{summary ? fmtNum(summary.total_tokens) : "—"}</div>
        </div>
        <div className="ana-stat">
          <div className="ana-stat__label">Total Cost</div>
          <div className="ana-stat__value">{summary ? fmtCost(summary.total_cost_usd) : "—"}</div>
        </div>
        <div className="ana-stat">
          <div className="ana-stat__label">Top Feature</div>
          <div className="ana-stat__value" style={{ fontSize: 13 }}>
            {summary?.top_feature ? (
              <>
                <span className="ana-feature-dot" style={{ background: FEATURE_COLOR[summary.top_feature] }} />
                {summary.top_feature}
              </>
            ) : "—"}
          </div>
        </div>
        <div className="ana-stat">
          <div className="ana-stat__label">Requests</div>
          <div className="ana-stat__value">{summary ? fmtNum(summary.requests) : "—"}</div>
        </div>
      </div>

      {/* bar chart */}
      {daily.length > 0 ? (
        <StackedBarChart series={daily} days={range} />
      ) : (
        <p className="stg-hint">Usage data accumulates as you use AI features.</p>
      )}

      {/* breakdown table */}
      {rows.length > 0 && (
        <table className="stg-egress-log__table">
          <thead>
            <tr>
              <th>Feature</th>
              <th>Provider</th>
              <th>Model</th>
              <th style={{ textAlign: "right" }}>In</th>
              <th style={{ textAlign: "right" }}>Out</th>
              <th style={{ textAlign: "right" }}>Cost</th>
              <th style={{ textAlign: "right" }}>Reqs</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td>
                  <span className="ana-feature-dot" style={{ background: FEATURE_COLOR[r.feature] }} />
                  {r.feature}
                </td>
                <td>{r.provider}</td>
                <td className="stg-egress-log__model">{r.model}</td>
                <td className="stg-egress-log__tok">{fmtNum(r.in_tokens)}</td>
                <td className="stg-egress-log__tok">{fmtNum(r.out_tokens)}</td>
                <td className="stg-egress-log__tok">{fmtCost(r.cost_usd)}</td>
                <td className="stg-egress-log__tok">{r.requests}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* reset */}
      <div>
        <button
          className="stg-btn stg-btn--sm stg-btn--danger"
          onClick={() => void reset()}
          disabled={clearing}
        >
          clear history
        </button>
      </div>
    </div>
  );
}

// ── User Profile section ──────────────────────────────────────────────────────

const KIND_OPTIONS = ["fact", "preference", "interest", "style"] as const;

function ProfileSection() {
  const [items, setItems] = useState<ProfileItem[]>([]);
  const [newKey, setNewKey] = useState("");
  const [newVal, setNewVal] = useState("");
  const [newKind, setNewKind] = useState<string>("fact");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setItems(await getUserProfile());
  }, []);

  useEffect(() => { void load(); }, [load]);

  const save = async () => {
    if (!newKey.trim() || !newVal.trim()) return;
    setSaving(true);
    await upsertProfileItem(newKey.trim(), newVal.trim(), newKind);
    setNewKey("");
    setNewVal("");
    await load();
    setSaving(false);
  };

  const remove = async (key: string) => {
    await deleteProfileItem(key);
    await load();
  };

  return (
    <div className="stg-profile">
      {items.length === 0 ? (
        <p className="stg-hint">Nothing stored yet — add facts below.</p>
      ) : (
        <table className="stg-profile__table">
          <thead>
            <tr>
              <th>key</th>
              <th>value</th>
              <th>kind</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.map((it) => (
              <tr key={it.key}>
                <td className="stg-profile__key">{it.key}</td>
                <td className="stg-profile__val">{it.value}</td>
                <td>
                  <span className="stg-badge">{it.kind}</span>
                </td>
                <td>
                  <button className="stg-list__rm" onClick={() => void remove(it.key)}>×</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="stg-profile__add">
        <input
          className="stg-list__input"
          placeholder="key (e.g. interests)"
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void save()}
        />
        <input
          className="stg-list__input"
          placeholder="value"
          value={newVal}
          onChange={(e) => setNewVal(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void save()}
        />
        <select
          className="stg-select"
          value={newKind}
          onChange={(e) => setNewKind(e.target.value)}
        >
          {KIND_OPTIONS.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
        <button
          className="stg-list__addbtn"
          onClick={() => void save()}
          disabled={saving || !newKey.trim() || !newVal.trim()}
        >
          {saving ? "…" : "add"}
        </button>
      </div>
    </div>
  );
}

// ── LAN section ──────────────────────────────────────────────────────────────

type LanStatus = {
  enabled: boolean;
  port: number;
  cert_ready: boolean;
  cert_path: string;
  key_path: string;
  url: string;
  lan_url: string;
  pc_name: string;
  lan_ip: string;
  root_ca_path: string;
};

const IS_TAURI = "__TAURI_INTERNALS__" in window;

async function tauriInvoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<T>(cmd, args ?? {});
}

function LanSection() {
  const [status, setStatus] = useState<LanStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [QRCodeSVG, setQRCodeSVG] = useState<React.ComponentType<any> | null>(null);

  useEffect(() => {
    void import("qrcode.react").then((m) => setQRCodeSVG(() => m.QRCodeSVG));
  }, []);

  const load = useCallback(async () => {
    try {
      const s = await tauriInvoke<LanStatus>("get_lan_status");
      setStatus(s);
    } catch { /* Tauri not available */ }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const flash = (text: string, ok: boolean) => {
    setMsg({ text, ok });
    window.setTimeout(() => setMsg(null), 6000);
  };

  const runSetupCert = async () => {
    setBusy(true);
    try {
      const result = await tauriInvoke<string>("setup_cert");
      flash(result, true);
      await load();
    } catch (e) { flash(String(e), false); }
    setBusy(false);
  };

  const toggleLan = async (next: boolean) => {
    if (next && !status?.cert_ready) {
      flash("Set up certificates first before enabling LAN sharing.", false);
      return;
    }
    setBusy(true);
    try {
      await tauriInvoke("restart_engine_for_lan", { enabled: next });
      const { initEngineBase, getHealth } = await import("../engine");
      await initEngineBase();
      for (let i = 0; i < 20; i++) {
        await new Promise((r) => setTimeout(r, 800));
        if (await getHealth()) break;
      }
      flash(next ? "LAN sharing enabled — scan the QR code on your phone." : "LAN sharing disabled.", true);
      await load();
    } catch (e) { flash(String(e), false); }
    setBusy(false);
  };

  const revealRootCa = async () => {
    try { await tauriInvoke("reveal_root_ca"); }
    catch (e) { flash(String(e), false); }
  };

  if (!IS_TAURI || status === null) return null;

  return (
    <Section title="Share on LAN" glyph="📱" defaultOpen={false}>
      <p className="stg-hint">
        Open Max from your iPhone or Mac on the same WiFi.
        All compute stays on this PC. HTTPS is required so the mic works on mobile.
      </p>

      {!status.cert_ready && (
        <div className="stg-lan-setup">
          <p className="stg-hint stg-hint--warn">
            Step 1: Install a locally-trusted certificate (requires admin/UAC).
          </p>
          <button className="stg-lan-btn" onClick={() => void runSetupCert()} disabled={busy}>
            {busy ? "Installing…" : "Install mkcert & generate cert"}
          </button>
          <p className="stg-hint">
            mkcert is fetched via winget. A UAC prompt will appear to trust the root CA.
          </p>
        </div>
      )}

      {status.cert_ready && (
        <div className="stg-row">
          <span className="stg-row__label">
            LAN sharing
            <span className={`stg-badge${status.enabled ? " stg-badge--ok" : ""}`}>
              {status.enabled ? "active" : "off"}
            </span>
          </span>
          <Toggle on={status.enabled} onChange={(v) => void toggleLan(v)} />
        </div>
      )}

      {status.enabled && status.cert_ready && (
        <div className="stg-lan-active">
          <div className="stg-lan-url-row">
            <span className="stg-lan-url">{status.url}/m</span>
            <button className="stg-lan-copy" onClick={() => void navigator.clipboard.writeText(`${status.url}/m`)}>
              copy
            </button>
          </div>
          {QRCodeSVG && (
            <div className="stg-lan-qr">
              <QRCodeSVG value={`${status.url}/m`} size={140} bgColor="#03080d" fgColor="#22d3ee" />
            </div>
          )}
          <p className="stg-hint">
            Scan for mobile UI · Desktop at <code>{status.url}/</code>
          </p>
        </div>
      )}

      {status.cert_ready && (
        <div className="stg-lan-cert">
          <p className="stg-hint stg-hint--section">Certificate</p>
          <p className="stg-hint">
            Trusted: <code>{status.pc_name}.local</code> · <code>{status.lan_ip}</code> ·{" "}
            <code>localhost</code> · <code>127.0.0.1</code>
          </p>
          <button className="stg-lan-btn stg-lan-btn--sm" onClick={() => void runSetupCert()} disabled={busy}>
            {busy ? "Running…" : "Regenerate cert"}
          </button>
        </div>
      )}

      {status.cert_ready && (
        <div className="stg-lan-trust">
          <p className="stg-hint stg-hint--section">One-time iPhone setup</p>
          <ol className="stg-lan-steps">
            <li>
              <button className="stg-lan-link" onClick={() => void revealRootCa()}>
                Show rootCA.pem in Explorer
              </button>{" "}
              → AirDrop to iPhone
            </li>
            <li>iPhone: <strong>Settings → General → VPN & Device Management</strong></li>
            <li>Tap mkcert profile → <strong>Install</strong></li>
            <li><strong>Settings → About → Certificate Trust Settings</strong> → enable full trust</li>
          </ol>
          {status.root_ca_path && (
            <p className="stg-hint">CA path: <code className="stg-lan-path">{status.root_ca_path}</code></p>
          )}
        </div>
      )}

      {msg && (
        <p className={`stg-lan-msg${msg.ok ? " stg-lan-msg--ok" : " stg-lan-msg--err"}`}>
          {msg.text}
        </p>
      )}
    </Section>
  );
}

// ── Custom Commands section ───────────────────────────────────────────────────

interface CustomCmd {
  name: string;
  description: string;
  trigger: string;
  prompt_template: string;
}

function CustomCommandsSection() {
  const [commands, setCommands] = useState<CustomCmd[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editIdx, setEditIdx] = useState<number | null>(null);
  const [draft, setDraft] = useState<CustomCmd>({ name: "", description: "", trigger: "", prompt_template: "" });

  useEffect(() => {
    fetch(`${ENGINE_URL}/config/commands`)
      .then((r) => r.json() as Promise<{ commands: CustomCmd[] }>)
      .then((d) => { setCommands(d.commands); setLoaded(true); })
      .catch(() => setLoaded(true));
  }, []);

  const save = async (cmds: CustomCmd[]) => {
    setSaving(true);
    try {
      await fetch(`${ENGINE_URL}/config/commands`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ commands: cmds }),
      });
      setCommands(cmds);
    } finally {
      setSaving(false);
    }
  };

  const startNew = () => {
    setDraft({ name: "", description: "", trigger: "?", prompt_template: "{body}" });
    setEditIdx(-1);
  };

  const commitDraft = () => {
    if (!draft.name.trim() || !draft.trigger.trim() || !draft.prompt_template.trim()) return;
    const updated = editIdx === -1
      ? [...commands, draft]
      : commands.map((c, i) => (i === editIdx ? draft : c));
    void save(updated);
    setEditIdx(null);
  };

  const remove = (idx: number) => {
    void save(commands.filter((_, i) => i !== idx));
  };

  if (!loaded) return null;

  return (
    <Section title="Custom Commands" glyph="⌘" defaultOpen={false}>
      <p className="stg-hint">
        Define your own DSL commands. Use a single trigger character (e.g. <code>?</code>), then type{" "}
        <code>? your text ?</code> in the chat bar. Use <code>{"{{body}}"}</code> in the template.
      </p>
      {commands.map((cmd, i) => (
        <div key={i} className="stg-row">
          <span className="stg-row__label">
            <code>{cmd.trigger} … {cmd.trigger}</code> → <strong>{cmd.name}</strong>
            {cmd.description && <span className="stg-row__muted"> — {cmd.description}</span>}
          </span>
          <div style={{ display: "flex", gap: 6 }}>
            <button className="stg-btn stg-btn--sm" onClick={() => { setDraft(cmd); setEditIdx(i); }}>Edit</button>
            <button className="stg-btn stg-btn--sm stg-btn--danger" onClick={() => remove(i)}>✕</button>
          </div>
        </div>
      ))}
      {editIdx !== null ? (
        <div className="stg-cmd-editor">
          <div className="stg-row">
            <span className="stg-row__label">Name</span>
            <input className="stg-text__input" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="explain" />
          </div>
          <div className="stg-row">
            <span className="stg-row__label">Trigger char</span>
            <input className="stg-text__input" maxLength={1} style={{ width: 48 }} value={draft.trigger} onChange={(e) => setDraft({ ...draft, trigger: e.target.value.slice(-1) })} placeholder="?" />
          </div>
          <div className="stg-row">
            <span className="stg-row__label">Description</span>
            <input className="stg-text__input" value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} placeholder="Explain in plain English" />
          </div>
          <div className="stg-row" style={{ flexDirection: "column", alignItems: "flex-start", gap: 6 }}>
            <span className="stg-row__label">Prompt template <span className="stg-row__muted">(use {"{body}"})</span></span>
            <textarea
              className="stg-text__input"
              style={{ width: "100%", minHeight: 72, resize: "vertical", fontFamily: "monospace", fontSize: 12 }}
              value={draft.prompt_template}
              onChange={(e) => setDraft({ ...draft, prompt_template: e.target.value })}
              placeholder={"Explain the following in plain English:\n\n{body}"}
            />
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="stg-btn" onClick={commitDraft} disabled={saving}>
              {saving ? "Saving…" : "Save command"}
            </button>
            <button className="stg-btn stg-btn--ghost" onClick={() => setEditIdx(null)}>Cancel</button>
          </div>
        </div>
      ) : (
        <button className="stg-btn" onClick={startNew}>+ New command</button>
      )}
    </Section>
  );
}

// ── Main view ─────────────────────────────────────────────────────────────────

export function SettingsView() {
  const [cfg, setCfg] = useState<EngineConfigView | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    void (async () => setCfg(await getConfig()))();
  }, []);

  const patch = async (p: ConfigPatch) => {
    const next = await updateConfig(p);
    if (next) {
      setCfg(next);
      setSaved(true);
      window.setTimeout(() => setSaved(false), 1200);
    }
  };

  if (!cfg) {
    return (
      <div className="stg">
        <div className="stg__offline">
          <span className="stg__offline-glyph">⚙</span>
          Engine offline — start Max engine to edit settings.
        </div>
      </div>
    );
  }

  return (
    <div className="stg">
      <header className="stg__header">
        <span className="stg__glyph">⚙</span>
        <span className="stg__title">Settings</span>
        {saved && <span className="stg__saved">Saved ✓</span>}
      </header>

      <div className="stg__body">

        {/* ── Your AI ──────────────────────────────────────────────── */}
        <Section title="Your AI" glyph="◈" defaultOpen={false}>
          <TextField
            label="What should Max call you?"
            value={cfg.personality.user_name}
            onChange={(v) => void patch({ personality: { user_name: v } })}
            placeholder="e.g. Tony"
          />
          <div className="stg-row">
            <span className="stg-row__label">Tone</span>
            <div className="stg-seg">
              {(["jarvis", "formal", "custom"] as const).map((m) => (
                <button
                  key={m}
                  className={`stg-seg__btn${cfg.personality.persona === m ? " is-on" : ""}`}
                  onClick={() => void patch({ personality: { persona: m } })}
                >
                  {m === "jarvis" ? "Jarvis" : m === "formal" ? "Analyst" : "Custom"}
                </button>
              ))}
            </div>
          </div>
          {cfg.personality.persona === "custom" && (
            <label className="stg-text">
              <span className="stg-text__label">Custom personality prefix</span>
              <textarea
                className="stg-text__input stg-text__input--area"
                value={cfg.personality.custom_prefix}
                placeholder="You are MAX — describe your preferred tone here…"
                rows={4}
                onChange={(e) => void patch({ personality: { custom_prefix: e.target.value } })}
              />
            </label>
          )}
          <p className="stg-hint">
            Jarvis mode: casual, witty, direct — like Jarvis to Tony Stark.
            Analyst mode: formal briefing style (current default).
          </p>

          <div className="stg-row">
            <span className="stg-row__label">Voice output (TTS)</span>
            <Toggle
              on={cfg.voice.tts_enabled}
              onChange={(v) => void patch({ voice: { tts_enabled: v } })}
            />
          </div>
          <div className="stg-row">
            <span className="stg-row__label">Speech input (STT)</span>
            <div className="stg-seg">
              {(["web", "whisper", "auto"] as const).map((p) => (
                <button
                  key={p}
                  className={`stg-seg__btn${cfg.voice.stt_provider === p ? " is-on" : ""}`}
                  onClick={() => void patch({ voice: { stt_provider: p } })}
                >
                  {p === "web" ? "Web API" : p === "whisper" ? "Whisper" : "Auto"}
                </button>
              ))}
            </div>
          </div>
          <div className="stg-row-group">
            <label className="stg-num">
              <span className="stg-num__label">TTS rate</span>
              <input
                className="stg-num__input"
                type="number"
                min={0.5}
                max={2.0}
                step={0.1}
                value={cfg.voice.tts_rate}
                onChange={(e) => void patch({ voice: { tts_rate: Number(e.target.value) } })}
              />
            </label>
            <label className="stg-num">
              <span className="stg-num__label">TTS pitch</span>
              <input
                className="stg-num__input"
                type="number"
                min={0.5}
                max={2.0}
                step={0.1}
                value={cfg.voice.tts_pitch}
                onChange={(e) => void patch({ voice: { tts_pitch: Number(e.target.value) } })}
              />
            </label>
          </div>
          {cfg.voice.stt_provider !== "web" && (
            <TextField
              label="Whisper model"
              value={cfg.voice.whisper_model}
              onChange={(v) => void patch({ voice: { whisper_model: v } })}
              placeholder="tiny.en"
              mono
            />
          )}

          <p className="stg-hint stg-hint--section">What Max knows about you</p>
          <ProfileSection />
        </Section>

        {/* ── Models ───────────────────────────────────────────────── */}
        <Section title="Models" glyph="◈" defaultOpen={false}>
          <ModelManager />
        </Section>

        {/* ── API Keys ─────────────────────────────────────────────── */}
        <Section title="API Keys" glyph="🔑" defaultOpen={false}>
          <p className="stg-hint">
            Keys are written to <code>engine/.env</code> and never echoed back.
          </p>
          <ApiKeyField
            label="Anthropic (Claude)"
            envName="ANTHROPIC_API_KEY"
            isSet={cfg.cloud_key_set}
            onSaved={setCfg}
          />
          <ApiKeyField
            label="OpenAI (GPT-4o, % sigil)"
            envName="OPENAI_API_KEY"
            isSet={cfg.openai_key_set ?? false}
            onSaved={setCfg}
          />
          <ApiKeyField
            label="Finnhub (Market data)"
            envName="FINNHUB_API_KEY"
            isSet={cfg.finnhub_key_set}
            onSaved={setCfg}
          />
        </Section>

        {/* ── Cloud & AI Routing ───────────────────────────────────── */}
        <Section title="Cloud & AI Routing" glyph="☁" defaultOpen={false}>
          {cfg.force_offline && (
            <div className="stg-offline-banner">
              ✦ Network kill-switch active — all outbound calls are blocked
            </div>
          )}

          <div className="stg-row">
            <span className="stg-row__label">
              <strong>Network kill-switch</strong>
              <span className="stg-hint stg-hint--inline">blocks ALL outbound calls (OSINT, Market, Cloud AI, Sentinel…)</span>
            </span>
            <Toggle on={cfg.force_offline} onChange={(v) => void patch({ force_offline: v })} />
          </div>

          <div className="stg-row">
            <span className="stg-row__label">
              Allow cloud (Claude)
              <span className={`stg-badge${cfg.cloud_key_set ? " stg-badge--ok" : " stg-badge--no"}`}>
                {cfg.cloud_key_set ? "key set" : "no key"}
              </span>
            </span>
            <Toggle on={cfg.allow_cloud} onChange={(v) => void patch({ allow_cloud: v })} />
          </div>

          <div className="stg-row">
            <span className="stg-row__label">Delegate mode</span>
            <div className="stg-seg">
              {(["manual", "smart-auto"] as const).map((m) => (
                <button
                  key={m}
                  className={`stg-seg__btn${cfg.delegate.mode === m ? " is-on" : ""}`}
                  onClick={() => void patch({ delegate: { mode: m } })}
                >
                  {m === "smart-auto" ? "Smart-Auto" : "Manual"}
                </button>
              ))}
            </div>
          </div>

          <div className="stg-row-group">
            <NumField
              label="Parallel local"
              value={cfg.delegate.max_parallel_local}
              min={1}
              max={8}
              onChange={(v) => void patch({ delegate: { max_parallel_local: v } })}
            />
            <NumField
              label="Parallel cloud"
              value={cfg.delegate.max_parallel_cloud}
              min={1}
              max={32}
              onChange={(v) => void patch({ delegate: { max_parallel_cloud: v } })}
            />
          </div>

          <div className="stg-row">
            <span className="stg-row__label">Heavy model keep-alive</span>
            <input
              className="stg-inline"
              value={cfg.idle.keep_alive}
              onChange={(e) => void patch({ idle: { keep_alive: e.target.value } })}
              placeholder="10m"
            />
          </div>

          <div className="stg-row">
            <span className="stg-row__label">
              Resident completer model
              <span className="stg-hint stg-hint--inline">tiny model kept in VRAM permanently for FIM/completion</span>
            </span>
            <input
              className="stg-inline"
              value={cfg.idle?.resident_model ?? ""}
              onChange={(e) => void patch({ idle: { resident_model: e.target.value } })}
              placeholder="qwen2.5-coder:3b"
            />
          </div>

          <div className="stg-row">
            <span className="stg-row__label">Resident keep-alive</span>
            <input
              className="stg-inline"
              value={cfg.idle?.resident_keep_alive ?? "-1"}
              onChange={(e) => void patch({ idle: { resident_keep_alive: e.target.value } })}
              placeholder="-1"
            />
          </div>

          <NumField
            label="VRAM budget (MB)"
            value={cfg.idle?.vram_budget_mb ?? 11000}
            min={1000}
            max={24000}
            onChange={(v) => void patch({ idle: { vram_budget_mb: v } })}
          />
        </Section>

        {/* ── Egress audit log ─────────────────────────────────────── */}
        <Section title="Egress Audit Log" glyph="↑" defaultOpen={false}>
          <p className="stg-hint">Every outbound cloud-API call logged for privacy auditing. Local Ollama calls are never logged.</p>
          <EgressLogSection />
        </Section>

        {/* ── Analytics ────────────────────────────────────────────── */}
        <Section title="Analytics" glyph="◈" defaultOpen={false}>
          <p className="stg-hint">Token usage and estimated cost by feature, model, and day. Data accumulates automatically.</p>
          <AnalyticsSection />
        </Section>

        {/* ── Providers ────────────────────────────────────────────── */}
        <Section title="Providers" glyph="🔌" defaultOpen={false}>
          <p className="stg-hint">Base URLs for local providers. Restart engine after changes.</p>
          {cfg.providers.map((p) => (
            <div key={p.name} className="stg-row">
              <span className="stg-row__label">
                <code>{p.name}</code>
                <span className={`stg-badge stg-badge--${p.kind}`}>{p.kind}</span>
              </span>
              {p.base_url ? (
                <span className="stg-row__mono">{p.base_url}</span>
              ) : (
                <span className="stg-row__muted">cloud (no URL)</span>
              )}
            </div>
          ))}
        </Section>

        {/* ── OSINT ────────────────────────────────────────────────── */}
        <Section title="OSINT" glyph="◉" defaultOpen={false}>
          <EgressHint sources="GDELT, public RSS feeds, USNI/TWZ fleet tracker" />
          <TextField
            label="GDELT query"
            value={cfg.osint.gdelt_query}
            onChange={(v) => void patch({ osint: { gdelt_query: v } })}
            placeholder="conflict OR military OR attack"
          />
          <div className="stg-row">
            <span className="stg-row__label">GDELT timespan</span>
            <div className="stg-seg">
              {["1h", "6h", "12h", "24h"].map((t) => (
                <button
                  key={t}
                  className={`stg-seg__btn${cfg.osint.gdelt_timespan === t ? " is-on" : ""}`}
                  onClick={() => void patch({ osint: { gdelt_timespan: t } })}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>
          <div className="stg-row-group">
            <NumField
              label="Max GDELT records"
              value={cfg.osint.gdelt_max_records}
              min={10}
              max={1000}
              onChange={(v) => void patch({ osint: { gdelt_max_records: v } })}
            />
            <NumField
              label="News cache TTL (s)"
              value={cfg.osint.ttl_seconds}
              min={60}
              onChange={(v) => void patch({ osint: { ttl_seconds: v } })}
            />
            <NumField
              label="Naval cache TTL (s)"
              value={cfg.osint.naval_ttl_seconds}
              min={3600}
              onChange={(v) => void patch({ osint: { naval_ttl_seconds: v } })}
            />
          </div>
          <p className="stg-hint stg-hint--section">Data sources</p>
          <div className="stg-row">
            <span className="stg-row__label">GDELT news</span>
            <Toggle
              on={cfg.osint.gdelt_enabled ?? true}
              onChange={(v) => void patch({ osint: { gdelt_enabled: v } })}
            />
          </div>
          <div className="stg-row">
            <span className="stg-row__label">RSS feeds</span>
            <Toggle
              on={cfg.osint.rss_enabled ?? true}
              onChange={(v) => void patch({ osint: { rss_enabled: v } })}
            />
          </div>
          <div className="stg-row">
            <span className="stg-row__label">Naval tracker</span>
            <Toggle
              on={cfg.osint.naval_enabled ?? true}
              onChange={(v) => void patch({ osint: { naval_enabled: v } })}
            />
          </div>
          <div className="stg-row">
            <span className="stg-row__label">
              GDELT tone signal
              <span className="stg-badge">opt-in</span>
            </span>
            <Toggle
              on={cfg.osint.tone_signal ?? false}
              onChange={(v) => void patch({ osint: { tone_signal: v } })}
            />
          </div>
          <p className="stg-hint">Tone signal amplifies heat for countries with strongly negative coverage.</p>
          <FeedList
            feeds={cfg.osint.feeds}
            onChange={(feeds) => void patch({ osint: { feeds } })}
          />
        </Section>

        {/* ── Market ───────────────────────────────────────────────── */}
        <Section title="Market" glyph="$" defaultOpen={false}>
          <EgressHint sources="Finnhub (quotes + market news)" />
          <div className="stg-row">
            <span className="stg-row__label">
              Finnhub API key
              <span className={`stg-badge${cfg.finnhub_key_set ? " stg-badge--ok" : " stg-badge--no"}`}>
                {cfg.finnhub_key_set ? "set" : "not set"}
              </span>
            </span>
          </div>
          <NumField
            label="Quote cache TTL (s)"
            value={cfg.market.ttl_seconds}
            min={5}
            max={120}
            onChange={(v) => void patch({ market: { ttl_seconds: v } })}
          />
          <p className="stg-hint">Manage the watchlist directly in the Market tab.</p>
        </Section>

        {/* ── Apollo ───────────────────────────────────────────────── */}
        <Section title="Apollo" glyph="▲" defaultOpen={false}>
          <TextField
            label="Embed model"
            value={cfg.apollo.embed_model}
            onChange={(v) => void patch({ apollo: { embed_model: v } })}
            placeholder="nomic-embed-text"
            mono
          />
          <div className="stg-row-group">
            <NumField
              label="Memory TTL (s)"
              value={cfg.apollo.ttl_seconds}
              min={3600}
              onChange={(v) => void patch({ apollo: { ttl_seconds: v } })}
            />
            <NumField
              label="Retrieve k"
              value={cfg.apollo.retrieve_k}
              min={1}
              max={20}
              onChange={(v) => void patch({ apollo: { retrieve_k: v } })}
            />
          </div>
          <div className="stg-row">
            <span className="stg-row__label">DB path</span>
            <span className="stg-row__mono stg-row__mono--dim">{cfg.apollo.db_path}</span>
          </div>
        </Section>

        {/* ── Polymarket ───────────────────────────────────────────── */}
        <Section title="Polymarket" glyph="Ψ" defaultOpen={false}>
          <EgressHint sources="Polymarket Gamma + CLOB APIs (public, no key required)" />
          <div className="stg-row">
            <span className="stg-row__label">Apollo embedding</span>
            <Toggle
              on={cfg.polymarket.embed_enabled}
              onChange={(v) => void patch({ polymarket: { embed_enabled: v } })}
            />
          </div>
          <NumField
            label="Board cache TTL (s)"
            value={cfg.polymarket.ttl_seconds}
            min={30}
            max={600}
            onChange={(v) => void patch({ polymarket: { ttl_seconds: v } })}
          />
          <p className="stg-hint">Manage the watchlist and categories in the Poly tab.</p>
        </Section>

        {/* ── Aegis ────────────────────────────────────────────────── */}
        <Section title="Aegis" glyph="🛡" defaultOpen={false}>
          <EgressHint sources="Cloud Claude (when allow_cloud is on) — sends code snippets and log excerpts for AI diagnosis and security fixes" />
          <p className="stg-hint">
            Aegis only calls the cloud when diagnosing or fixing, and <code>allow_cloud</code> is enabled.
            All secrets are redacted before any data leaves the machine.
          </p>
          <div className="stg-row">
            <span className="stg-row__label">
              Autonomy mode
              <span className="stg-badge">{cfg.aegis?.autonomy ?? "ask"}</span>
            </span>
            <div className="stg-seg">
              {(["suggest", "ask", "auto"] as const).map((m) => (
                <button
                  key={m}
                  className={`stg-seg__btn${(cfg.aegis?.autonomy ?? "ask") === m ? " is-on" : ""}`}
                  onClick={() => void patch({ aegis: { autonomy: m } })}
                >
                  {m === "suggest" ? "Suggest" : m === "ask" ? "Ask (safe)" : "Auto"}
                </button>
              ))}
            </div>
          </div>
          <p className="stg-hint">
            <strong>Auto</strong> = diagnose + apply without confirmation. Use with caution — Aegis will modify your files automatically.
          </p>

          <label className="stg-row">
            <span className="stg-row__label">Security scan enabled</span>
            <Toggle
              on={cfg.aegis?.scan_enabled ?? true}
              onChange={(v) => void patch({ aegis: { scan_enabled: v } })}
            />
          </label>
          <label className="stg-row">
            <span className="stg-row__label">Scan on startup</span>
            <Toggle
              on={cfg.aegis?.scan_on_startup ?? false}
              onChange={(v) => void patch({ aegis: { scan_on_startup: v } })}
            />
          </label>
          <NumField
            label="Scan interval (hours)"
            value={cfg.aegis?.scan_interval_hours ?? 24}
            min={1}
            max={168}
            onChange={(v) => void patch({ aegis: { scan_interval_hours: v } })}
          />
          <NumField
            label="Score threshold (below = at risk)"
            value={cfg.aegis?.score_threshold ?? 70}
            min={0}
            max={100}
            onChange={(v) => void patch({ aegis: { score_threshold: v } })}
          />
          <label className="stg-row">
            <span className="stg-row__label">OSV.dev dependency scan</span>
            <Toggle
              on={cfg.aegis?.osv_enabled ?? true}
              onChange={(v) => void patch({ aegis: { osv_enabled: v } })}
            />
          </label>
        </Section>

        {/* ── Share on LAN ─────────────────────────────────────────── */}
        <LanSection />

        {/* ── Custom Commands ──────────────────────────────────────── */}
        <CustomCommandsSection />

        {/* ── Workspace Allowlist ───────────────────────────────────── */}
        <Section title="Workspace Allowlist" glyph="📁" defaultOpen={false}>
          <p className="stg-hint">
            Folders the engine may read/write for task execution.
          </p>
          <PathList
            paths={cfg.workspace_allowlist}
            onChange={(p) => void patch({ workspace_allowlist: p })}
          />
        </Section>

      </div>
    </div>
  );
}
