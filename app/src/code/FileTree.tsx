// File tree sidebar for the Code tab. Lazy-loads directory children on expand.

import { useEffect, useState } from "react";
import { listFiles, type FileEntry } from "./code";

interface NodeProps {
  entry: FileEntry;
  depth: number;
  selected: string | null;
  onSelect: (path: string) => void;
}

function TreeNode({ entry, depth, selected, onSelect }: NodeProps) {
  const [open, setOpen] = useState(false);
  const [children, setChildren] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(false);

  const toggle = async () => {
    if (!entry.is_dir) {
      onSelect(entry.path);
      return;
    }
    if (!open && children.length === 0) {
      setLoading(true);
      try {
        const kids = await listFiles(entry.path);
        setChildren(kids);
      } catch {
        /* ignore */
      } finally {
        setLoading(false);
      }
    }
    setOpen((v) => !v);
  };

  const isSelected = !entry.is_dir && entry.path === selected;

  return (
    <div className="ftree__node" style={{ paddingLeft: depth * 12 }}>
      <button
        className={`ftree__row${isSelected ? " is-selected" : ""}`}
        onClick={() => void toggle()}
        title={entry.path}
      >
        <span className="ftree__icon" aria-hidden="true">
          {entry.is_dir ? (open ? "▾" : "▸") : "·"}
        </span>
        <span className="ftree__name">{entry.name}</span>
        {loading && <span className="ftree__spin">…</span>}
      </button>
      {open && children.map((c) => (
        <TreeNode
          key={c.path}
          entry={c}
          depth={depth + 1}
          selected={selected}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}

interface FileTreeProps {
  selected: string | null;
  onSelect: (path: string) => void;
}

export function FileTree({ selected, onSelect }: FileTreeProps) {
  const [roots, setRoots] = useState<FileEntry[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    listFiles()
      .then(setRoots)
      .catch((e: unknown) =>
        setErr(e instanceof Error ? e.message : "failed to load files"),
      );
  }, []);

  if (err) {
    return (
      <div className="ftree__err">
        {err.includes("allow-listed") ? (
          <>No workspace paths set.<br />Add one in Settings → Workspace.</>
        ) : (
          err
        )}
      </div>
    );
  }

  if (roots.length === 0) {
    return <div className="ftree__empty">No workspace paths allow-listed.</div>;
  }

  return (
    <div className="ftree">
      {roots.map((r) => (
        <TreeNode key={r.path} entry={r} depth={0} selected={selected} onSelect={onSelect} />
      ))}
    </div>
  );
}
