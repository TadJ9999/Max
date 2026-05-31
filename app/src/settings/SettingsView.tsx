// Full settings view — one-stop configuration for every engine setting.
// Organised into collapsible sections. Changes are applied immediately via
// the /config PUT endpoint; API keys go through /config/key (write-only).

import { useEffect, useState } from "react";
import {
  getConfig,
  updateConfig,
  setApiKey,
  type ConfigPatch,
  type EngineConfigView,
} from "../config";
import "./Settings.css";

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

        {/* ── API Keys ─────────────────────────────────────────────── */}
        <Section title="API Keys" glyph="🔑">
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
            label="Finnhub (Market data)"
            envName="FINNHUB_API_KEY"
            isSet={cfg.finnhub_key_set}
            onSaved={setCfg}
          />
        </Section>

        {/* ── Cloud & AI Routing ───────────────────────────────────── */}
        <Section title="Cloud & AI Routing" glyph="☁">
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
            <span className="stg-row__label">Local model keep-alive</span>
            <input
              className="stg-inline"
              value={cfg.idle.keep_alive}
              onChange={(e) => void patch({ idle: { keep_alive: e.target.value } })}
              placeholder="10m"
            />
          </div>
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
          <FeedList
            feeds={cfg.osint.feeds}
            onChange={(feeds) => void patch({ osint: { feeds } })}
          />
        </Section>

        {/* ── Market ───────────────────────────────────────────────── */}
        <Section title="Market" glyph="$" defaultOpen={false}>
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
