// File tree sidebar — lazy-loads children, supports right-click CRUD.

import { useEffect, useRef, useState } from "react";
import {
  createDir,
  createFile,
  deleteFile,
  listFiles,
  renameFile,
  type FileEntry,
} from "./code";

// ── Context menu ─────────────────────────────────────────────────────────────

interface CtxPos { x: number; y: number }

interface CtxMenuProps {
  pos: CtxPos;
  isDir: boolean;
  onClose: () => void;
  onNewFile: () => void;
  onNewFolder: () => void;
  onRename: () => void;
  onDelete: () => void;
}

function ContextMenu({ pos, isDir, onClose, onNewFile, onNewFolder, onRename, onDelete }: CtxMenuProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const dismiss = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", dismiss);
    return () => document.removeEventListener("mousedown", dismiss);
  }, [onClose]);

  return (
    <div
      ref={ref}
      className="ftree__ctx-menu"
      style={{ left: pos.x, top: pos.y }}
    >
      {isDir && (
        <>
          <button className="ftree__ctx-item" onClick={() => { onClose(); onNewFile(); }}>
            New File
          </button>
          <button className="ftree__ctx-item" onClick={() => { onClose(); onNewFolder(); }}>
            New Folder
          </button>
          <div className="ftree__ctx-sep" />
        </>
      )}
      <button className="ftree__ctx-item" onClick={() => { onClose(); onRename(); }}>
        Rename
      </button>
      <button className="ftree__ctx-item is-danger" onClick={() => { onClose(); onDelete(); }}>
        Delete{isDir ? " Folder" : ""}
      </button>
    </div>
  );
}

// ── Tree node ─────────────────────────────────────────────────────────────────

interface NodeProps {
  entry: FileEntry;
  depth: number;
  selected: string | null;
  onSelect: (path: string) => void;
  onRenameTab: (oldPath: string, newPath: string) => void;
  onDeleteTab: (path: string) => void;
}

function TreeNode({ entry, depth, selected, onSelect, onRenameTab, onDeleteTab }: NodeProps) {
  const [open, setOpen] = useState(false);
  const [children, setChildren] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [ctxPos, setCtxPos] = useState<CtxPos | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [renameVal, setRenameVal] = useState(entry.name);
  const [creatingChild, setCreatingChild] = useState<"file" | "dir" | null>(null);
  const [newChildName, setNewChildName] = useState("");

  const refreshChildren = async () => {
    try {
      const kids = await listFiles(entry.path);
      setChildren(kids);
    } catch { /* ignore */ }
  };

  const toggle = async () => {
    if (!entry.is_dir) {
      onSelect(entry.path);
      return;
    }
    if (!open && children.length === 0) {
      setLoading(true);
      try {
        await refreshChildren();
      } finally {
        setLoading(false);
      }
    }
    setOpen((v) => !v);
  };

  const startCreate = (kind: "file" | "dir") => {
    if (!open) {
      // expand first, then show input
      void toggle().then(() => {
        setCreatingChild(kind);
        setNewChildName("");
      });
    } else {
      setCreatingChild(kind);
      setNewChildName("");
    }
  };

  const confirmCreate = async () => {
    const name = newChildName.trim();
    if (!name) { setCreatingChild(null); return; }
    const fullPath = `${entry.path}/${name}`;
    try {
      if (creatingChild === "file") await createFile(fullPath);
      else await createDir(fullPath);
      await refreshChildren();
      if (!open) setOpen(true);
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    } finally {
      setCreatingChild(null);
      setNewChildName("");
    }
  };

  const confirmRename = async () => {
    const name = renameVal.trim();
    if (!name || name === entry.name) { setRenaming(false); return; }
    try {
      const result = await renameFile(entry.path, name);
      onRenameTab(entry.path, result.new_path);
      entry.name = name;
      entry.path = result.new_path;
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
      setRenameVal(entry.name);
    } finally {
      setRenaming(false);
    }
  };

  const confirmDelete = async () => {
    const msg = entry.is_dir
      ? `Delete folder "${entry.name}" and all its contents?`
      : `Delete "${entry.name}"?`;
    if (!window.confirm(msg)) return;
    try {
      await deleteFile(entry.path, entry.is_dir);
      onDeleteTab(entry.path);
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    }
  };

  const isSelected = !entry.is_dir && entry.path === selected;

  return (
    <div className="ftree__node" style={{ paddingLeft: depth * 12 }}>
      {/* Row */}
      {renaming ? (
        <input
          className="ftree__rename-input"
          value={renameVal}
          autoFocus
          onChange={(e) => setRenameVal(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void confirmRename();
            if (e.key === "Escape") { setRenameVal(entry.name); setRenaming(false); }
          }}
          onBlur={() => { setRenameVal(entry.name); setRenaming(false); }}
          onClick={(e) => e.stopPropagation()}
        />
      ) : (
        <button
          className={`ftree__row${isSelected ? " is-selected" : ""}`}
          onClick={() => void toggle()}
          onContextMenu={(e) => {
            e.preventDefault();
            setCtxPos({ x: e.clientX, y: e.clientY });
          }}
          title={entry.path}
        >
          <span className="ftree__icon" aria-hidden="true">
            {entry.is_dir ? (open ? "▾" : "▸") : "·"}
          </span>
          <span className="ftree__name">{entry.name}</span>
          {loading && <span className="ftree__spin">…</span>}
        </button>
      )}

      {/* Context menu */}
      {ctxPos && (
        <ContextMenu
          pos={ctxPos}
          isDir={entry.is_dir}
          onClose={() => setCtxPos(null)}
          onNewFile={() => startCreate("file")}
          onNewFolder={() => startCreate("dir")}
          onRename={() => { setRenameVal(entry.name); setRenaming(true); }}
          onDelete={() => void confirmDelete()}
        />
      )}

      {/* Children + inline new-entry input */}
      {open && (
        <>
          {creatingChild && (
            <div style={{ paddingLeft: 12 }}>
              <input
                className="ftree__rename-input"
                value={newChildName}
                autoFocus
                placeholder={creatingChild === "file" ? "filename.ts" : "folder-name"}
                onChange={(e) => setNewChildName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void confirmCreate();
                  if (e.key === "Escape") setCreatingChild(null);
                }}
                onBlur={() => setCreatingChild(null)}
              />
            </div>
          )}
          {children.map((c) => (
            <TreeNode
              key={c.path}
              entry={c}
              depth={depth + 1}
              selected={selected}
              onSelect={onSelect}
              onRenameTab={onRenameTab}
              onDeleteTab={onDeleteTab}
            />
          ))}
        </>
      )}
    </div>
  );
}

// ── FileTree (root) ───────────────────────────────────────────────────────────

interface FileTreeProps {
  selected: string | null;
  onSelect: (path: string) => void;
  onRename?: (oldPath: string, newPath: string) => void;
  onDelete?: (path: string) => void;
  refreshKey?: number;
}

export function FileTree({ selected, onSelect, onRename, onDelete, refreshKey }: FileTreeProps) {
  const [roots, setRoots] = useState<FileEntry[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const load = () => {
    listFiles()
      .then(setRoots)
      .catch((e: unknown) =>
        setErr(e instanceof Error ? e.message : "failed to load files"),
      );
  };

  useEffect(load, [refreshKey]);

  if (err) {
    return (
      <div className="ftree__err">
        {err.includes("allow-listed") || err.includes("No workspace") ? (
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
        <TreeNode
          key={r.path}
          entry={r}
          depth={0}
          selected={selected}
          onSelect={onSelect}
          onRenameTab={onRename ?? (() => {})}
          onDeleteTab={onDelete ?? (() => {})}
        />
      ))}
    </div>
  );
}
