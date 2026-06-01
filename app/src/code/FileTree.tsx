// File tree sidebar — lazy-loads children, supports right-click CRUD, a header
// toolbar (new file/folder, refresh, collapse-all), and git-status badges.

import { useEffect, useRef, useState } from "react";
import {
  createDir,
  createFile,
  deleteFile,
  gitBadge,
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

// ── Git badge ──────────────────────────────────────────────────────────────

function GitBadge({ code }: { code: string }) {
  const b = gitBadge(code);
  if (!b) return null;
  return (
    <span className={`ftree__git ftree__git--${b.kind}`} title={`git: ${b.kind}`}>
      {b.letter}
    </span>
  );
}

// ── Tree node ─────────────────────────────────────────────────────────────────

interface NodeProps {
  entry: FileEntry;
  depth: number;
  selected: string | null;
  gitStatus: Map<string, string>;
  onSelect: (path: string) => void;
  onRenameTab: (oldPath: string, newPath: string) => void;
  onDeleteTab: (path: string) => void;
}

function TreeNode({ entry, depth, selected, gitStatus, onSelect, onRenameTab, onDeleteTab }: NodeProps) {
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
  const code = gitStatus.get(entry.path);

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
          className={`ftree__row${isSelected ? " is-selected" : ""}${code ? " is-changed" : ""}`}
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
          {!entry.is_dir && code && <GitBadge code={code} />}
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
              gitStatus={gitStatus}
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
  gitStatus?: Map<string, string>;
  onSelect: (path: string) => void;
  onRename?: (oldPath: string, newPath: string) => void;
  onDelete?: (path: string) => void;
  onRefresh?: () => void;
  onOpenFolder?: () => void;
  refreshKey?: number;
}

export function FileTree({
  selected,
  gitStatus,
  onSelect,
  onRename,
  onDelete,
  onRefresh,
  onOpenFolder,
  refreshKey,
}: FileTreeProps) {
  const [roots, setRoots] = useState<FileEntry[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0); // bumped to remount nodes (collapse-all)
  const [rootCreate, setRootCreate] = useState<"file" | "dir" | null>(null);
  const [rootCreateName, setRootCreateName] = useState("");
  const status = gitStatus ?? new Map<string, string>();

  const load = () => {
    setErr(null);
    listFiles()
      .then(setRoots)
      .catch((e: unknown) =>
        setErr(e instanceof Error ? e.message : "failed to load files"),
      );
  };

  useEffect(load, [refreshKey]);

  const refresh = () => {
    load();
    setNonce((n) => n + 1);
    onRefresh?.();
  };

  const collapseAll = () => setNonce((n) => n + 1);

  const confirmRootCreate = async () => {
    const name = rootCreateName.trim();
    const base = roots[0]?.path;
    if (!name || !base) { setRootCreate(null); return; }
    try {
      const full = `${base}/${name}`;
      if (rootCreate === "file") { await createFile(full); onSelect(full); }
      else await createDir(full);
      refresh();
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    } finally {
      setRootCreate(null);
      setRootCreateName("");
    }
  };

  const hasRoots = roots.length > 0 && !err;

  return (
    <div className="ftree-wrap">
      {/* Toolbar */}
      <div className="ftree__toolbar">
        <button
          className="ftree__tool"
          title="New File"
          disabled={!hasRoots}
          onClick={() => { setRootCreate("file"); setRootCreateName(""); }}
        >
          ⊕
        </button>
        <button
          className="ftree__tool"
          title="New Folder"
          disabled={!hasRoots}
          onClick={() => { setRootCreate("dir"); setRootCreateName(""); }}
        >
          ⊞
        </button>
        <button className="ftree__tool" title="Refresh" onClick={refresh}>
          ⟳
        </button>
        <button
          className="ftree__tool"
          title="Collapse All"
          disabled={!hasRoots}
          onClick={collapseAll}
        >
          ⇥
        </button>
        <button className="ftree__tool" title="Open Folder…" onClick={() => onOpenFolder?.()}>
          📂
        </button>
      </div>

      {err ? (
        <div className="ftree__err">
          {err.includes("allow-listed") || err.includes("No workspace") ? (
            <>
              <div>No workspace folder open.</div>
              <button className="ftree__open-btn" onClick={() => onOpenFolder?.()}>
                📂 Open Folder
              </button>
            </>
          ) : (
            err
          )}
        </div>
      ) : roots.length === 0 ? (
        <div className="ftree__empty">
          <div>No workspace folder open.</div>
          <button className="ftree__open-btn" onClick={() => onOpenFolder?.()}>
            📂 Open Folder
          </button>
        </div>
      ) : (
        <div className="ftree" key={nonce}>
          {rootCreate && (
            <div style={{ paddingLeft: 12 }}>
              <input
                className="ftree__rename-input"
                value={rootCreateName}
                autoFocus
                placeholder={rootCreate === "file" ? "filename.ts" : "folder-name"}
                onChange={(e) => setRootCreateName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void confirmRootCreate();
                  if (e.key === "Escape") setRootCreate(null);
                }}
                onBlur={() => setRootCreate(null)}
              />
            </div>
          )}
          {roots.map((r) => (
            <TreeNode
              key={r.path}
              entry={r}
              depth={0}
              selected={selected}
              gitStatus={status}
              onSelect={onSelect}
              onRenameTab={onRename ?? (() => {})}
              onDeleteTab={onDelete ?? (() => {})}
            />
          ))}
        </div>
      )}
    </div>
  );
}
