// One AI-proposed patch in the plan review: path, description, +/- stats, and
// an expandable unified diff against the file's current on-disk content.

import { useEffect, useState } from "react";
import { readFile, type FilePatch } from "./code";
import { diffLines, diffStats, type DiffRow } from "./diff";

export function PatchDiff({ patch }: { patch: FilePatch }) {
  const [rows, setRows] = useState<DiffRow[] | null>(null);
  const [open, setOpen] = useState(false);
  const [isNew, setIsNew] = useState(false);

  useEffect(() => {
    let alive = true;
    void (async () => {
      let current = "";
      try {
        current = await readFile(patch.path);
      } catch {
        if (alive) setIsNew(true); // file doesn't exist yet → new file
      }
      const d = diffLines(current, patch.new_content);
      if (alive) setRows(d);
    })();
    return () => { alive = false; };
  }, [patch.path, patch.new_content]);

  const stats = rows ? diffStats(rows) : { added: 0, removed: 0 };

  return (
    <div className="code-view__patch">
      <div className="code-view__patch-head" onClick={() => setOpen((v) => !v)}>
        <span className="code-view__patch-caret">{open ? "▾" : "▸"}</span>
        <span className="code-view__patch-path">{patch.path}</span>
        {isNew && <span className="code-view__patch-new">new</span>}
        <span className="code-view__patch-stats">
          <span className="code-view__stat-add">+{stats.added}</span>
          <span className="code-view__stat-del">−{stats.removed}</span>
        </span>
      </div>
      <div className="code-view__patch-desc">{patch.description}</div>
      {open && (
        <pre className="code-view__diff">
          {rows === null ? (
            <span className="code-view__diff-loading">Loading diff…</span>
          ) : (
            rows.map((r, i) => (
              <div key={i} className={`code-view__diff-row code-view__diff-row--${r.type}`}>
                <span className="code-view__diff-gutter">
                  {r.type === "add" ? "+" : r.type === "del" ? "−" : " "}
                </span>
                <span className="code-view__diff-text">{r.text || " "}</span>
              </div>
            ))
          )}
        </pre>
      )}
    </div>
  );
}
