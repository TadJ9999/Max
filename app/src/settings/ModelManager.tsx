// Rich model picker — local Ollama models + cloud model catalog.
// Shows: name, provider logo, cost/multiplier (cloud), VRAM/tokens-per-sec (local),
// context window, strengths, key/install status.
// Bottom section: task routing matrix (generate/chat/fix/summarize → model selector).

import { useCallback, useEffect, useState } from "react";
import { updateConfig } from "../config";
import {
  benchmarkModel,
  getModels,
  streamPullModel,
  type CloudModel,
  type LocalModel,
  type ModelsResponse,
} from "./models";

// ── Provider logos (inline SVG paths) ────────────────────────────────────────

function ProviderLogo({ provider }: { provider: string }) {
  switch (provider) {
    case "anthropic":
      return (
        <svg className="mm-logo" viewBox="0 0 24 24" fill="currentColor">
          <path d="M13.827 3.52h3.603L24 20h-3.603l-6.57-16.48zM6.394 3.52L0 20h3.603l1.498-3.858h7.197L10.8 20h3.604L8.012 3.52H6.394zm1.113 9.908 2.523-6.498 2.524 6.498H7.507z" />
        </svg>
      );
    case "openai":
      return (
        <svg className="mm-logo" viewBox="0 0 24 24" fill="currentColor">
          <path d="M22.282 9.821a5.985 5.985 0 0 0-.516-4.91 6.046 6.046 0 0 0-6.51-2.9A6.065 6.065 0 0 0 4.981 4.18a5.985 5.985 0 0 0-3.998 2.9 6.046 6.046 0 0 0 .743 7.097 5.98 5.98 0 0 0 .51 4.911 6.051 6.051 0 0 0 6.515 2.9A5.985 5.985 0 0 0 13.26 24a6.056 6.056 0 0 0 5.772-4.206 5.99 5.99 0 0 0 3.997-2.9 6.056 6.056 0 0 0-.747-7.073zM13.26 22.43a4.476 4.476 0 0 1-2.876-1.04l.141-.081 4.779-2.758a.795.795 0 0 0 .392-.681v-6.737l2.02 1.168a.071.071 0 0 1 .038.052v5.583a4.504 4.504 0 0 1-4.494 4.494zM3.6 18.304a4.47 4.47 0 0 1-.535-3.014l.142.085 4.783 2.759a.771.771 0 0 0 .78 0l5.843-3.369v2.332a.08.08 0 0 1-.033.062L9.74 19.95a4.5 4.5 0 0 1-6.14-1.646zM2.34 7.896a4.485 4.485 0 0 1 2.366-1.973V11.6a.766.766 0 0 0 .388.676l5.815 3.355-2.02 1.168a.076.076 0 0 1-.071 0l-4.83-2.786A4.504 4.504 0 0 1 2.34 7.872zm16.597 3.855-5.833-3.387L15.119 7.2a.076.076 0 0 1 .071 0l4.83 2.791a4.494 4.494 0 0 1-.676 8.105v-5.678a.79.79 0 0 0-.407-.667zm2.01-3.023-.141-.085-4.774-2.782a.776.776 0 0 0-.785 0L9.409 9.23V6.897a.066.066 0 0 1 .028-.061l4.83-2.787a4.5 4.5 0 0 1 6.68 4.66zm-12.64 4.135-2.02-1.164a.08.08 0 0 1-.038-.057V6.075a4.5 4.5 0 0 1 7.375-3.453l-.142.08L8.704 5.46a.795.795 0 0 0-.393.681zm1.097-2.365 2.602-1.5 2.607 1.5v2.999l-2.597 1.5-2.607-1.5Z" />
        </svg>
      );
    case "google":
      return (
        <svg className="mm-logo" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12.48 10.92v3.28h7.84c-.24 1.84-.853 3.187-1.787 4.133-1.147 1.147-2.933 2.4-6.053 2.4-4.827 0-8.6-3.893-8.6-8.72s3.773-8.72 8.6-8.72c2.6 0 4.507 1.027 5.907 2.347l2.307-2.307C18.747 1.44 16.133 0 12.48 0 5.867 0 .307 5.387.307 12s5.56 12 12.173 12c3.573 0 6.267-1.173 8.373-3.36 2.16-2.16 2.84-5.213 2.84-7.667 0-.76-.053-1.467-.173-2.053H12.48z" />
        </svg>
      );
    default:
      return (
        <svg className="mm-logo" viewBox="0 0 24 24" fill="currentColor">
          <circle cx="12" cy="12" r="10" opacity="0.3" />
          <text x="12" y="16" textAnchor="middle" fontSize="10" fill="currentColor">AI</text>
        </svg>
      );
  }
}

function OllamaLogo() {
  return (
    <svg className="mm-logo" viewBox="0 0 24 24" fill="currentColor">
      <circle cx="12" cy="8" r="5" opacity="0.9" />
      <path d="M5 20c0-3.866 3.134-7 7-7s7 3.134 7 7" strokeWidth="2" stroke="currentColor" fill="none" strokeLinecap="round" />
    </svg>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt$(n: number) {
  return n < 1 ? `$${(n * 100).toFixed(0)}¢` : `$${n.toFixed(2)}`;
}

function fmtMb(mb: number) {
  return mb >= 1000 ? `${(mb / 1024).toFixed(1)} GB` : `${mb} MB`;
}

const TASK_LABELS: Record<string, string> = {
  generate: "Generate code",
  summarize: "Summarize / docs",
  fix: "Fix / refactor",
  chat: "Chat",
  completion: "Inline completion",
};

// ── Cloud model card ──────────────────────────────────────────────────────────

function CloudCard({
  model,
  isActive,
  onSelect,
}: {
  model: CloudModel;
  isActive: boolean;
  onSelect: () => void;
}) {
  const unavailable = model.status === "coming_soon";
  const needsKey = model.status === "available" && !model.key_set;

  return (
    <div
      className={`mm-card mm-card--cloud mm-card--${model.provider}${isActive ? " mm-card--active" : ""}${unavailable ? " mm-card--dim" : ""}`}
      onClick={unavailable ? undefined : onSelect}
      role={unavailable ? undefined : "button"}
      tabIndex={unavailable ? undefined : 0}
      onKeyDown={(e) => e.key === "Enter" && !unavailable && onSelect()}
    >
      <div className="mm-card__top">
        <ProviderLogo provider={model.provider} />
        <div className="mm-card__titles">
          <span className="mm-card__name">{model.display_name}</span>
          <span className="mm-card__sub">{model.provider_label}</span>
        </div>
        {isActive && <span className="mm-card__active-dot" title="Selected" />}
      </div>

      <div className="mm-card__metrics">
        <div className="mm-card__metric">
          <span className="mm-card__metric-label">Cost ×</span>
          <span className="mm-card__metric-val mm-card__metric-val--mult">
            {model.cost_multiplier}×
          </span>
        </div>
        <div className="mm-card__metric">
          <span className="mm-card__metric-label">Input /1M</span>
          <span className="mm-card__metric-val">{fmt$(model.input_cost_per_1m)}</span>
        </div>
        <div className="mm-card__metric">
          <span className="mm-card__metric-label">Output /1M</span>
          <span className="mm-card__metric-val">{fmt$(model.output_cost_per_1m)}</span>
        </div>
        <div className="mm-card__metric">
          <span className="mm-card__metric-label">Context</span>
          <span className="mm-card__metric-val">{model.context_k}K</span>
        </div>
      </div>

      <div className="mm-card__strengths">
        {model.strengths.slice(0, 3).map((s) => (
          <span key={s} className="mm-tag">{s}</span>
        ))}
      </div>

      {unavailable && (
        <div className="mm-card__badge mm-card__badge--soon">Coming soon</div>
      )}
      {needsKey && (
        <div className="mm-card__badge mm-card__badge--key">API key required</div>
      )}
    </div>
  );
}

// ── Local model card ──────────────────────────────────────────────────────────

function LocalCard({
  model,
  isActive,
  benchmarking,
  onSelect,
  onBenchmark,
}: {
  model: LocalModel;
  isActive: boolean;
  benchmarking: boolean;
  onSelect: () => void;
  onBenchmark: () => void;
}) {
  const hasBench = model.tokens_per_sec !== null;

  return (
    <div
      className={`mm-card mm-card--local${isActive ? " mm-card--active" : ""}`}
      onClick={onSelect}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && onSelect()}
    >
      <div className="mm-card__top">
        <OllamaLogo />
        <div className="mm-card__titles">
          <span className="mm-card__name" title={model.id}>{model.display_name}</span>
          <span className="mm-card__sub">
            {model.parameter_size && <span>{model.parameter_size} · </span>}
            {model.quant && <span className="mm-quant">{model.quant}</span>}
          </span>
        </div>
        {isActive && <span className="mm-card__active-dot" title="Selected" />}
      </div>

      <div className="mm-card__metrics">
        <div className="mm-card__metric">
          <span className="mm-card__metric-label">Cost ×</span>
          <span className="mm-card__metric-val mm-card__metric-val--free">FREE</span>
        </div>
        {model.vram_mb !== null && (
          <div className="mm-card__metric">
            <span className="mm-card__metric-label">VRAM</span>
            <span className="mm-card__metric-val">~{fmtMb(model.vram_mb)}</span>
          </div>
        )}
        <div className="mm-card__metric">
          <span className="mm-card__metric-label">Size</span>
          <span className="mm-card__metric-val">{model.size_gb} GB</span>
        </div>
        {hasBench ? (
          <div className="mm-card__metric">
            <span className="mm-card__metric-label">tok/s</span>
            <span className="mm-card__metric-val mm-card__metric-val--speed">
              {model.tokens_per_sec!.toFixed(0)}
            </span>
          </div>
        ) : (
          <div className="mm-card__metric">
            <span className="mm-card__metric-label">tok/s</span>
            <span className="mm-card__metric-val mm-card__metric-val--dim">—</span>
          </div>
        )}
        {hasBench && model.ttft_ms !== null && (
          <div className="mm-card__metric">
            <span className="mm-card__metric-label">TTFT</span>
            <span className="mm-card__metric-val">{model.ttft_ms!.toFixed(0)}ms</span>
          </div>
        )}
      </div>

      <button
        className={`mm-bench-btn${benchmarking ? " mm-bench-btn--running" : ""}`}
        onClick={(e) => { e.stopPropagation(); onBenchmark(); }}
        disabled={benchmarking}
        title="Run live benchmark (fires a timed prompt)"
      >
        {benchmarking ? "⏱ Running…" : hasBench ? "↺ Re-benchmark" : "⏱ Benchmark"}
      </button>
    </div>
  );
}

// ── Download card (suggest-to-install) ───────────────────────────────────────

const SUGGESTED_MODELS = [
  "qwen2.5-coder:14b",
  "qwen2.5-coder:3b",
  "llama3.1:8b",
  "nomic-embed-text",
];

function SuggestedCard({
  tag,
  installedIds,
  pulling,
  pullStatus,
  onPull,
}: {
  tag: string;
  installedIds: Set<string>;
  pulling: string | null;
  pullStatus: string;
  onPull: (tag: string) => void;
}) {
  const installed = installedIds.has(tag);
  const active = pulling === tag;
  return (
    <div className={`mm-card mm-card--suggest${installed ? " mm-card--installed" : ""}`}>
      <div className="mm-card__top">
        <OllamaLogo />
        <div className="mm-card__titles">
          <span className="mm-card__name">{tag}</span>
          <span className="mm-card__sub">Recommended local model</span>
        </div>
      </div>
      {active && <p className="mm-pull-status">{pullStatus || "Connecting…"}</p>}
      <button
        className="mm-pull-btn"
        onClick={() => onPull(tag)}
        disabled={installed || active}
      >
        {installed ? "✓ Installed" : active ? "Pulling…" : "↓ Install"}
      </button>
    </div>
  );
}

// ── Task routing matrix ───────────────────────────────────────────────────────

function RoutingMatrix({
  taskModels,
  allModelIds,
  onChange,
}: {
  taskModels: Record<string, string>;
  allModelIds: string[];
  onChange: (task: string, model: string) => void;
}) {
  return (
    <div className="mm-routing">
      <p className="mm-routing__hint">
        Map each task to its default model. The sigil (e.g. <code>!</code>) overrides this per-invocation.
      </p>
      <table className="mm-routing__table">
        <thead>
          <tr>
            <th>Task</th>
            <th>Default model</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(taskModels).map(([task, model]) => (
            <tr key={task}>
              <td className="mm-routing__task">{TASK_LABELS[task] ?? task}</td>
              <td>
                <select
                  className="mm-routing__sel"
                  value={model}
                  onChange={(e) => onChange(task, e.target.value)}
                >
                  <optgroup label="Local (Ollama)">
                    {allModelIds
                      .filter((id) => !id.startsWith("claude-") && !id.startsWith("gpt-") && !id.startsWith("gemini-") && !id.startsWith("o1") && !id.startsWith("o3"))
                      .map((id) => (
                        <option key={id} value={id}>{id}</option>
                      ))}
                  </optgroup>
                  <optgroup label="Cloud (Claude)">
                    {["claude-haiku-4-5-20251001", "claude-sonnet-4-6", "claude-opus-4-8"].map((id) => (
                      <option key={id} value={id}>{id}</option>
                    ))}
                  </optgroup>
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

type Tab = "local" | "cloud" | "routing";

export function ModelManager() {
  const [data, setData] = useState<ModelsResponse | null>(null);
  const [tab, setTab] = useState<Tab>("local");
  const [selectedModel, setSelectedModel] = useState<string | null>(null);
  const [benchmarking, setBenchmarking] = useState<string | null>(null);
  const [pulling, setPulling] = useState<string | null>(null);
  const [pullStatus, setPullStatus] = useState("");
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    const d = await getModels();
    setData(d);
    return d;
  }, []);

  // Initial load with retry: poll every 3s until the engine responds.
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      const d = await getModels();
      if (!alive) return;
      setData(d);
      if (!d) window.setTimeout(poll, 3000);
    };
    void poll();
    return () => { alive = false; };
  }, []);

  const handleBenchmark = async (modelId: string) => {
    setBenchmarking(modelId);
    await benchmarkModel(modelId);
    await load();
    setBenchmarking(null);
  };

  const handlePull = async (tag: string) => {
    setPulling(tag);
    setPullStatus("");
    try {
      for await (const status of streamPullModel(tag)) {
        setPullStatus(status);
      }
    } catch (e) {
      setPullStatus(String(e));
    }
    await load();
    setPulling(null);
    setPullStatus("");
  };

  const handleRoutingChange = async (task: string, model: string) => {
    if (!data) return;
    const next = { ...data.task_models, [task]: model };
    setData({ ...data, task_models: next });
    await updateConfig({ task_models: next });
    setSaved(true);
    window.setTimeout(() => setSaved(false), 1200);
  };

  if (!data) {
    return (
      <div className="mm-offline">
        <span className="mm-offline__glyph">⚙</span>
        Engine offline — start Max engine to manage models.
      </div>
    );
  }

  const installedIds = new Set(data.local.map((m) => m.id));
  const allModelIds = data.local.map((m) => m.id);
  const activeModel = selectedModel ?? data.task_models["chat"] ?? "";

  const suggestedNotInstalled = SUGGESTED_MODELS.filter((t) => !installedIds.has(t));

  return (
    <div className="mm">
      <div className="mm__header">
        <span className="mm__title">Models</span>
        {saved && <span className="mm__saved">Saved ✓</span>}
        <button className="mm__refresh" onClick={() => void load()} title="Refresh model list">↺</button>
      </div>

      {/* Tabs */}
      <div className="mm__tabs">
        {(["local", "cloud", "routing"] as Tab[]).map((t) => (
          <button
            key={t}
            className={`mm__tab${tab === t ? " mm__tab--on" : ""}`}
            onClick={() => setTab(t)}
          >
            {t === "local" ? `Local (${data.local.length})` : t === "cloud" ? "Cloud" : "Task Routing"}
          </button>
        ))}
      </div>

      {/* Local tab */}
      {tab === "local" && (
        <div className="mm__panel">
          {data.local.length === 0 ? (
            <p className="mm-hint">No Ollama models installed. Use the suggestions below or run <code>ollama pull &lt;model&gt;</code>.</p>
          ) : (
            <div className="mm-grid">
              {data.local.map((m) => (
                <LocalCard
                  key={m.id}
                  model={m}
                  isActive={activeModel === m.id}
                  benchmarking={benchmarking === m.id}
                  onSelect={() => setSelectedModel(m.id)}
                  onBenchmark={() => void handleBenchmark(m.id)}
                />
              ))}
            </div>
          )}

          {suggestedNotInstalled.length > 0 && (
            <>
              <p className="mm-section-label">Suggested models</p>
              <div className="mm-grid">
                {suggestedNotInstalled.map((tag) => (
                  <SuggestedCard
                    key={tag}
                    tag={tag}
                    installedIds={installedIds}
                    pulling={pulling}
                    pullStatus={pullStatus}
                    onPull={(t) => void handlePull(t)}
                  />
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {/* Cloud tab */}
      {tab === "cloud" && (
        <div className="mm__panel">
          <p className="mm-hint">
            Cloud models are opt-in (<code>!</code> sigil or allow_cloud). Set your API key in <strong>API Keys</strong> to unlock them.
          </p>

          {/* Group by provider */}
          {(["anthropic", "openai", "google"] as const).map((prov) => {
            const models = data.cloud.filter((m) => m.provider === prov);
            if (models.length === 0) return null;
            return (
              <div key={prov} className="mm-provider-group">
                <div className="mm-provider-label">
                  <ProviderLogo provider={prov} />
                  <span>{models[0].provider_label}</span>
                </div>
                <div className="mm-grid">
                  {models.map((m) => (
                    <CloudCard
                      key={m.id}
                      model={m}
                      isActive={activeModel === m.id}
                      onSelect={() => setSelectedModel(m.id)}
                    />
                  ))}
                </div>
              </div>
            );
          })}

          {/* Cost multiplier legend */}
          <div className="mm-legend">
            <span className="mm-legend__title">Cost multiplier</span>
            <span className="mm-legend__item">1× = Claude Haiku ($0.80/1M input)</span>
            <span className="mm-legend__item">5× = ~$4/1M · 25× = ~$20/1M</span>
          </div>
        </div>
      )}

      {/* Routing tab */}
      {tab === "routing" && (
        <div className="mm__panel">
          <RoutingMatrix
            taskModels={data.task_models}
            allModelIds={allModelIds}
            onChange={(task, model) => void handleRoutingChange(task, model)}
          />
        </div>
      )}
    </div>
  );
}
