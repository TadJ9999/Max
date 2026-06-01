// Code tab — full IDE: Monaco editor + file tree + AI edit planner + terminal.
//
// Layout:
//   [file tree + find-in-files 200px] | [toolbar / tabs / Monaco / statusbar / terminal] | [AI panel]

import { useEffect, useRef, useState } from "react";
import Editor, { loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor";
import { FileTree } from "./FileTree";
import { Terminal } from "./Terminal";
import {
  applyPlan,
  findInFiles,
  readFile,
  rollbackPlan,
  streamPlan,
  writeFile,
  type EditPlan,
  type SearchHit,
} from "./code";
import "./Code.css";

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
  // ── tabs ─────────────────────────────────────────────────────────────────
  const [tabs, setTabs] = useState<OpenTab[]>([]);
  const [activeIdx, setActiveIdx] = useState<number>(-1);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [treeRefreshKey, setTreeRefreshKey] = useState(0);

  // ── editor ref + cursor ──────────────────────────────────────────────────
  const editorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  const pendingRevealLine = useRef<number | null>(null);
  const [cursorPos, setCursorPos] = useState({ line: 1, col: 1 });
  const [minimapOn, setMinimapOn] = useState(false);

  // ── terminal ─────────────────────────────────────────────────────────────
  const [termOpen, setTermOpen] = useState(false);
  const [termHeight, setTermHeight] = useState(200);

  // ── find in files ─────────────────────────────────────────────────────────
  const [findOpen, setFindOpen] = useState(false);
  const [findQuery, setFindQuery] = useState("");
  const [findResults, setFindResults] = useState<SearchHit[]>([]);
  const [findLoading, setFindLoading] = useState(false);

  // ── AI plan ───────────────────────────────────────────────────────────────
  const [aiOpen, setAiOpen] = useState(false);
  const [aiRequest, setAiRequest] = useState("");
  const [aiStatus, setAiStatus] = useState<string | null>(null);
  const [plan, setPlan] = useState<EditPlan | null>(null);
  const [applying, setApplying] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);
  const [snapshotRef, setSnapshotRef] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const activeTab = tabs[activeIdx] ?? null;

  // ── file operations ───────────────────────────────────────────────────────

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

  const openFileAtLine = async (path: string, line: number) => {
    pendingRevealLine.current = line;
    await openFile(path);
  };

  const onEditorChange = (value: string | undefined) => {
    if (value === undefined || activeIdx < 0) return;
    setTabs((prev) =>
      prev.map((t, i) => (i === activeIdx ? { ...t, content: value, dirty: true } : t)),
    );
  };

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

  const closeTab = (idx: number) => {
    setTabs((prev) => {
      const next = prev.filter((_, i) => i !== idx);
      setActiveIdx((ai) => {
        if (next.length === 0) return -1;
        if (ai === idx) return Math.max(0, idx - 1);
        if (ai > idx) return ai - 1;
        return ai;
      });
      return next;
    });
  };

  // ── keyboard shortcuts ────────────────────────────────────────────────────

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const ctrl = e.ctrlKey || e.metaKey;
      if (ctrl && e.key === "s") { e.preventDefault(); void saveActive(); }
      if (ctrl && e.key === "`") { e.preventDefault(); setTermOpen((v) => !v); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // ── Monaco mount ──────────────────────────────────────────────────────────

  const handleEditorMount = (editor: monaco.editor.IStandaloneCodeEditor) => {
    editorRef.current = editor;
    editor.onDidChangeCursorPosition((e) => {
      setCursorPos({ line: e.position.lineNumber, col: e.position.column });
    });
    if (pendingRevealLine.current !== null) {
      const line = pendingRevealLine.current;
      pendingRevealLine.current = null;
      requestAnimationFrame(() => {
        editor.revealLine(line, monaco.editor.ScrollType.Smooth);
        editor.setPosition({ lineNumber: line, column: 1 });
      });
    }
  };

  // ── terminal resize ───────────────────────────────────────────────────────

  const handleTermResizeStart = (e: React.MouseEvent) => {
    e.preventDefault();
    const startY = e.clientY;
    const startH = termHeight;
    const onMove = (ev: MouseEvent) => {
      const delta = startY - ev.clientY;
      setTermHeight(Math.max(80, Math.min(600, startH + delta)));
    };
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  // ── find in files ─────────────────────────────────────────────────────────

  const runFind = async () => {
    if (!findQuery.trim()) return;
    setFindLoading(true);
    setFindResults([]);
    try {
      const hits = await findInFiles(findQuery);
      setFindResults(hits);
    } catch (e) {
      console.error("find in files:", e);
    } finally {
      setFindLoading(false);
    }
  };

  // ── AI plan ───────────────────────────────────────────────────────────────

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

  // ── render ────────────────────────────────────────────────────────────────

  return (
    <div className="code-view">
      {/* ── Left sidebar: file tree + find-in-files ── */}
      <aside className="code-view__tree">
        <div className="code-view__tree-head">
          <span>Files</span>
          <button
            className="ftree__add-btn"
            title="Find in files"
            onClick={() => setFindOpen((v) => !v)}
          >
            {findOpen ? "✕" : "⌕"}
          </button>
        </div>

        <FileTree
          selected={selectedPath}
          refreshKey={treeRefreshKey}
          onSelect={(p) => {
            setSelectedPath(p);
            void openFile(p);
          }}
          onRename={(oldPath, newPath) => {
            setTabs((prev) =>
              prev.map((t) =>
                t.path === oldPath
                  ? { ...t, path: newPath, name: newPath.split(/[\\/]/).pop() ?? t.name }
                  : t,
              ),
            );
            setTreeRefreshKey((k) => k + 1);
          }}
          onDelete={(path) => {
            const idx = tabs.findIndex((t) => t.path === path);
            if (idx >= 0) closeTab(idx);
            setTreeRefreshKey((k) => k + 1);
          }}
        />

        {/* Find in files panel */}
        {findOpen && (
          <div className="code-view__find">
            <div className="code-view__find-head">Find in Files</div>
            <input
              className="code-view__find-input"
              value={findQuery}
              onChange={(e) => setFindQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") void runFind(); }}
              placeholder="Search…"
              autoFocus
            />
            <div className="code-view__find-results">
              {findLoading && <div className="code-view__find-loading">Searching…</div>}
              {findResults.map((hit, i) => (
                <div
                  key={i}
                  className="code-view__find-hit"
                  onClick={() => void openFileAtLine(hit.file, hit.line)}
                  title={hit.file}
                >
                  <div className="code-view__find-hit-path">
                    {hit.file.split(/[/\\]/).pop()}:{hit.line}
                  </div>
                  <div className="code-view__find-hit-text">{hit.text.trim()}</div>
                </div>
              ))}
              {!findLoading && findResults.length === 0 && findQuery && (
                <div className="code-view__find-loading">No results</div>
              )}
            </div>
          </div>
        )}
      </aside>

      {/* ── Main editor area ── */}
      <div className="code-view__editor-wrap">
        {/* Always-visible toolbar */}
        <div className="code-view__toolbar">
          <button
            className={`code-view__toolbar-btn${activeTab?.dirty ? " is-dirty" : ""}`}
            onClick={() => void saveActive()}
            disabled={!activeTab?.dirty}
            title="Save (Ctrl+S)"
          >
            Save
          </button>
          <div className="code-view__toolbar-sep" />
          <button
            className={`code-view__toolbar-btn${termOpen ? " is-active" : ""}`}
            onClick={() => setTermOpen((v) => !v)}
            title="Toggle Terminal (Ctrl+`)"
          >
            Terminal
          </button>
          <button
            className={`code-view__toolbar-btn${minimapOn ? " is-active" : ""}`}
            onClick={() => setMinimapOn((v) => !v)}
            title="Toggle Minimap"
          >
            Minimap
          </button>
          <div className="code-view__toolbar-spacer" />
          <button
            className={`code-view__ai-btn${aiOpen ? " is-open" : ""}`}
            onClick={() => setAiOpen((v) => !v)}
            title="AI Edit Planner"
          >
            ✦ AI Plan
          </button>
        </div>

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
            onMount={handleEditorMount}
            theme="vs-dark"
            options={{
              fontSize: 13,
              fontFamily: "'Cascadia Code', 'JetBrains Mono', monospace",
              minimap: { enabled: minimapOn },
              wordWrap: "on",
              automaticLayout: true,
              scrollBeyondLastLine: false,
              padding: { top: 12 },
              renderWhitespace: "none",
              smoothScrolling: true,
              bracketPairColorization: { enabled: true },
              formatOnPaste: true,
              quickSuggestions: true,
              parameterHints: { enabled: true },
              suggestOnTriggerCharacters: true,
              scrollbar: { verticalScrollbarSize: 8, horizontalScrollbarSize: 8 },
            }}
          />
        ) : (
          <div className="code-view__empty">
            <div className="code-view__empty-msg">
              <span className="code-view__empty-glyph">⌨</span>
              <span>Open a file to start editing</span>
              <span className="code-view__empty-hint">Right-click the tree to create files · Ctrl+` for terminal · ✦ AI Plan for AI edits</span>
            </div>
          </div>
        )}

        {/* Status bar */}
        <div className="code-view__status">
          {activeTab ? (
            <>
              <span>Ln {cursorPos.line}, Col {cursorPos.col}</span>
              <span>{activeTab.language}</span>
              <span>Spaces: 2</span>
              <span>UTF-8</span>
            </>
          ) : (
            <span>No file open</span>
          )}
        </div>

        {/* Terminal panel (mounted once, hidden when closed) */}
        <div
          className="code-view__terminal-panel"
          style={{ height: termOpen ? termHeight : 0, display: termOpen ? "flex" : "none" }}
        >
          <div
            className="code-view__terminal-resize"
            onMouseDown={handleTermResizeStart}
          />
          <Terminal isOpen={termOpen} />
        </div>
      </div>

      {/* ── AI plan panel ── */}
      {aiOpen && (
        <aside className="code-view__ai">
          <div className="code-view__ai-head">
            <span>✦ AI Edit Planner</span>
            <button className="code-view__ai-close" onClick={() => setAiOpen(false)}>×</button>
          </div>

          {!plan ? (
            <div className="code-view__ai-form">
              <p className="code-view__ai-hint">
                Describe the change you want. All open tabs are included as context.
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
