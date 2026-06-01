// Code tab — Monaco editor + file tree + AI edit planner.
//
// Layout:
//   [file tree 200px] | [Monaco editor flex] | [AI panel 320px slide-in]
//
// Workflow:
//   1. Browse & open files in the tree → each opens as a tab in Monaco.
//   2. Edit freely; unsaved changes tracked per-tab (dirty flag).
//   3. Ctrl+S / Save button writes via PUT /code/file.
//   4. "AI Plan" panel: describe a change → engine streams a plan →
//      review per-file diffs → Apply or Discard.

import { useEffect, useRef, useState } from "react";
import Editor, { loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor";
import { FileTree } from "./FileTree";
import {
  applyPlan,
  readFile,
  rollbackPlan,
  streamPlan,
  writeFile,
  type EditPlan,
} from "./code";
import "./Code.css";

// Use locally bundled Monaco instead of CDN so it works offline / in Tauri.
loader.config({ monaco });

interface OpenTab {
  path: string;
  name: string;
  content: string;
  dirty: boolean;
  language: string;
}

function guessLang(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  const MAP: Record<string, string> = {
    ts: "typescript", tsx: "typescript", js: "javascript", jsx: "javascript",
    py: "python", rs: "rust", toml: "toml", json: "json", md: "markdown",
    css: "css", html: "html", yaml: "yaml", yml: "yaml", sh: "shell",
    ps1: "powershell", sql: "sql", xml: "xml",
  };
  return MAP[ext] ?? "plaintext";
}

export function CodeView() {
  const [tabs, setTabs] = useState<OpenTab[]>([]);
  const [activeIdx, setActiveIdx] = useState<number>(-1);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [aiOpen, setAiOpen] = useState(false);
  const [aiRequest, setAiRequest] = useState("");
  const [aiStatus, setAiStatus] = useState<string | null>(null);
  const [plan, setPlan] = useState<EditPlan | null>(null);
  const [applying, setApplying] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);
  const [snapshotRef, setSnapshotRef] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const activeTab = tabs[activeIdx] ?? null;

  // Open a file in a tab (or switch to existing tab).
  const openFile = async (path: string) => {
    const existing = tabs.findIndex((t) => t.path === path);
    if (existing >= 0) {
      setActiveIdx(existing);
      return;
    }
    try {
      const content = await readFile(path);
      const name = path.split(/[\\/]/).pop() ?? path;
      const tab: OpenTab = { path, name, content, dirty: false, language: guessLang(path) };
      setTabs((prev) => {
        const next = [...prev, tab];
        setActiveIdx(next.length - 1);
        return next;
      });
    } catch (e) {
      console.error("open file:", e);
    }
  };

  // Handle Monaco editor changes.
  const onEditorChange = (value: string | undefined) => {
    if (value === undefined || activeIdx < 0) return;
    setTabs((prev) =>
      prev.map((t, i) =>
        i === activeIdx ? { ...t, content: value, dirty: true } : t,
      ),
    );
  };

  // Save active tab.
  const saveActive = async () => {
    if (!activeTab || !activeTab.dirty) return;
    try {
      await writeFile(activeTab.path, activeTab.content);
      setTabs((prev) =>
        prev.map((t, i) => (i === activeIdx ? { ...t, dirty: false } : t)),
      );
    } catch (e) {
      alert(`Save failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  // Ctrl+S handler.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        void saveActive();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // Close a tab.
  const closeTab = (idx: number) => {
    setTabs((prev) => {
      const next = prev.filter((_, i) => i !== idx);
      setActiveIdx((ai) => {
        if (ai === idx) return Math.max(0, idx - 1);
        if (ai > idx) return ai - 1;
        return ai;
      });
      return next;
    });
  };

  // Run AI plan.
  const runPlan = async () => {
    if (!aiRequest.trim()) return;
    setPlan(null);
    setPlanError(null);
    setAiStatus("Connecting…");
    const ac = new AbortController();
    abortRef.current = ac;
    const filePaths = tabs.map((t) => t.path);
    try {
      for await (const msg of streamPlan(aiRequest, filePaths, ac.signal)) {
        if (msg.status) setAiStatus(msg.status);
        if (msg.error) { setPlanError(msg.error); setAiStatus(null); return; }
        if (msg.plan) { setPlan(msg.plan); setAiStatus(null); }
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError")
        setPlanError(e instanceof Error ? e.message : String(e));
      setAiStatus(null);
    }
  };

  const applyEditPlan = async () => {
    if (!plan) return;
    setApplying(true);
    try {
      const result = await applyPlan(plan.patches);
      setSnapshotRef(result.snapshot_ref);
      // Reload any open tabs that were changed.
      for (const patch of plan.patches) {
        const idx = tabs.findIndex((t) => t.path === patch.path);
        if (idx >= 0) {
          setTabs((prev) =>
            prev.map((t, i) =>
              i === idx ? { ...t, content: patch.new_content, dirty: false } : t,
            ),
          );
        }
      }
      setPlan(null);
      setAiRequest("");
      if (result.errors.length > 0)
        setPlanError(`Applied with errors: ${result.errors.join(", ")}`);
    } catch (e) {
      setPlanError(e instanceof Error ? e.message : String(e));
    } finally {
      setApplying(false);
    }
  };

  const rollback = async () => {
    try {
      await rollbackPlan();
      setSnapshotRef(null);
      setPlanError(null);
    } catch (e) {
      setPlanError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="code-view">
      {/* File tree sidebar */}
      <aside className="code-view__tree">
        <div className="code-view__tree-head">FILES</div>
        <FileTree
          selected={selectedPath}
          onSelect={(p) => {
            setSelectedPath(p);
            void openFile(p);
          }}
        />
      </aside>

      {/* Editor area */}
      <div className="code-view__editor-wrap">
        {/* Tab bar */}
        {tabs.length > 0 && (
          <div className="code-view__tabs">
            {tabs.map((t, i) => (
              <div
                key={t.path}
                className={`code-tab${i === activeIdx ? " is-active" : ""}`}
                onClick={() => setActiveIdx(i)}
                title={t.path}
              >
                <span className="code-tab__name">{t.name}{t.dirty ? " •" : ""}</span>
                <button
                  className="code-tab__close"
                  onClick={(e) => { e.stopPropagation(); closeTab(i); }}
                >
                  ×
                </button>
              </div>
            ))}
            <div className="code-view__tab-actions">
              {activeTab?.dirty && (
                <button className="code-view__save" onClick={() => void saveActive()} title="Save (Ctrl+S)">
                  Save
                </button>
              )}
              <button
                className={`code-view__ai-btn${aiOpen ? " is-open" : ""}`}
                onClick={() => setAiOpen((v) => !v)}
                title="AI Edit Planner"
              >
                ✦ AI Plan
              </button>
            </div>
          </div>
        )}

        {/* Monaco editor */}
        {activeTab ? (
          <Editor
            key={activeTab.path}
            className="code-view__monaco"
            language={activeTab.language}
            value={activeTab.content}
            onChange={onEditorChange}
            theme="vs-dark"
            options={{
              fontSize: 13,
              fontFamily: "'Cascadia Code', 'JetBrains Mono', monospace",
              minimap: { enabled: false },
              wordWrap: "on",
              scrollBeyondLastLine: false,
              padding: { top: 12 },
              renderWhitespace: "none",
              smoothScrolling: true,
            }}
          />
        ) : (
          <div className="code-view__empty">
            <div className="code-view__empty-msg">
              <span className="code-view__empty-glyph">⌨</span>
              <span>Open a file from the tree to start editing</span>
              <span className="code-view__empty-hint">Use ✦ AI Plan to make changes across multiple files</span>
            </div>
          </div>
        )}
      </div>

      {/* AI plan panel */}
      {aiOpen && (
        <aside className="code-view__ai">
          <div className="code-view__ai-head">
            <span>✦ AI Edit Planner</span>
            <button className="code-view__ai-close" onClick={() => setAiOpen(false)}>×</button>
          </div>

          {!plan ? (
            <div className="code-view__ai-form">
              <p className="code-view__ai-hint">
                Describe the change you want across your codebase. All open tabs are included as context.
              </p>
              <textarea
                className="code-view__ai-input"
                value={aiRequest}
                onChange={(e) => setAiRequest(e.target.value)}
                placeholder="e.g. Add error boundaries to all fetch calls in engine.ts"
                rows={5}
              />
              <button
                className="code-view__ai-run"
                onClick={() => void runPlan()}
                disabled={!aiRequest.trim() || !!aiStatus}
              >
                {aiStatus ?? "Generate Plan"}
              </button>
              {planError && <div className="code-view__ai-err">{planError}</div>}
            </div>
          ) : (
            <div className="code-view__plan">
              <div className="code-view__plan-summary">{plan.summary}</div>
              <div className="code-view__plan-files">
                {plan.patches.map((p) => (
                  <div key={p.path} className="code-view__patch">
                    <div className="code-view__patch-path">{p.path}</div>
                    <div className="code-view__patch-desc">{p.description}</div>
                  </div>
                ))}
              </div>
              <div className="code-view__plan-actions">
                <button
                  className="code-view__apply"
                  onClick={() => void applyEditPlan()}
                  disabled={applying}
                >
                  {applying ? "Applying…" : "Apply All"}
                </button>
                <button
                  className="code-view__discard"
                  onClick={() => { setPlan(null); setPlanError(null); }}
                >
                  Discard
                </button>
              </div>
              {planError && <div className="code-view__ai-err">{planError}</div>}
              {snapshotRef && (
                <div className="code-view__snapshot">
                  <span>Snapshot: <code>{snapshotRef}</code></span>
                  <button className="code-view__rollback" onClick={() => void rollback()}>
                    Rollback
                  </button>
                </div>
              )}
            </div>
          )}
        </aside>
      )}
    </div>
  );
}
