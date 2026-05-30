// The settings panel (opened by the ⚙ cog). Reads/writes the engine's
// /config: cloud on/off (+ key-set status), delegate mode, parallel limits,
// and the workspace folder allowlist. Each change is sent immediately and the
// panel re-syncs to the engine's response.

import { useEffect, useState } from "react";
import { getConfig, updateConfig, type ConfigPatch, type EngineConfigView } from "../config";

export function SettingsPanel() {
  const [cfg, setCfg] = useState<EngineConfigView | null>(null);
  const [path, setPath] = useState("");

  useEffect(() => {
    void (async () => setCfg(await getConfig()))();
  }, []);

  const patch = async (p: ConfigPatch) => {
    const next = await updateConfig(p);
    if (next) setCfg(next);
  };

  if (!cfg) {
    return (
      <div className="panel">
        <div className="panel__title">Settings</div>
        <p className="panel__hint">Engine offline — start it to edit settings.</p>
      </div>
    );
  }

  const addPath = () => {
    const p = path.trim();
    if (!p || cfg.workspace_allowlist.includes(p)) return;
    void patch({ workspace_allowlist: [...cfg.workspace_allowlist, p] });
    setPath("");
  };

  return (
    <div className="panel set">
      <div className="panel__title">Settings</div>

      <div className="set__row">
        <span className="set__label">
          Cloud (<code>!</code>)
        </span>
        <div className="set__ctl">
          <span className={`set__key ${cfg.cloud_key_set ? "ok" : "no"}`}>
            {cfg.cloud_key_set ? "key set ✓" : "no key"}
          </span>
          <button
            className={`toggle ${cfg.allow_cloud ? "toggle--on" : ""}`}
            onClick={() => patch({ allow_cloud: !cfg.allow_cloud })}
            title="Allow cloud (!) requests"
          >
            {cfg.allow_cloud ? "on" : "off"}
          </button>
        </div>
      </div>

      <div className="set__row">
        <span className="set__label">Delegate</span>
        <div className="set__seg">
          {(["manual", "smart-auto"] as const).map((mode) => (
            <button
              key={mode}
              className={`seg ${cfg.delegate.mode === mode ? "seg--on" : ""}`}
              onClick={() => patch({ delegate: { mode } })}
            >
              {mode === "smart-auto" ? "Smart-Auto" : "Manual"}
            </button>
          ))}
        </div>
      </div>

      <div className="set__row">
        <span className="set__label">Parallel local</span>
        <input
          className="set__num"
          type="number"
          min={1}
          value={cfg.delegate.max_parallel_local}
          onChange={(e) => patch({ delegate: { max_parallel_local: Number(e.target.value) } })}
        />
      </div>

      <div className="set__row">
        <span className="set__label">Parallel cloud</span>
        <input
          className="set__num"
          type="number"
          min={1}
          value={cfg.delegate.max_parallel_cloud}
          onChange={(e) => patch({ delegate: { max_parallel_cloud: Number(e.target.value) } })}
        />
      </div>

      <div className="set__block">
        <span className="set__label">Workspace allowlist</span>
        <ul className="set__list">
          {cfg.workspace_allowlist.length === 0 && <li className="set__empty">none yet</li>}
          {cfg.workspace_allowlist.map((p) => (
            <li key={p} className="set__item">
              <span className="set__path">{p}</span>
              <button
                className="set__rm"
                title="Remove"
                onClick={() =>
                  patch({ workspace_allowlist: cfg.workspace_allowlist.filter((x) => x !== p) })
                }
              >
                ×
              </button>
            </li>
          ))}
        </ul>
        <div className="set__add">
          <input
            className="set__input"
            placeholder="C:/path/to/folder"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addPath();
              }
            }}
          />
          <button className="set__addbtn" onClick={addPath}>
            add
          </button>
        </div>
      </div>
    </div>
  );
}
