// API client for the Code tab (file browser + AI edit planner).

import { ENGINE_URL } from "../engine";

export interface FileEntry {
  name: string;
  path: string;
  is_dir: boolean;
}

export interface FilePatch {
  path: string;
  description: string;
  new_content: string;
}

export interface EditPlan {
  summary: string;
  patches: FilePatch[];
}

export async function listFiles(path: string = ""): Promise<FileEntry[]> {
  const url = path
    ? `${ENGINE_URL}/code/files?path=${encodeURIComponent(path)}`
    : `${ENGINE_URL}/code/files`;
  const r = await fetch(url);
  if (!r.ok) throw new Error(`list files failed: ${r.status}`);
  const data = (await r.json()) as { entries: FileEntry[] };
  return data.entries;
}

export async function readFile(path: string): Promise<string> {
  const r = await fetch(`${ENGINE_URL}/code/file?path=${encodeURIComponent(path)}`);
  if (!r.ok) throw new Error(`read file failed: ${r.status}`);
  const data = (await r.json()) as { content: string };
  return data.content;
}

export async function writeFile(path: string, content: string): Promise<void> {
  const r = await fetch(`${ENGINE_URL}/code/file`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ path, content }),
  });
  if (!r.ok) throw new Error(`write file failed: ${r.status}`);
}

export async function* streamPlan(
  request: string,
  filePaths: string[],
  signal?: AbortSignal,
): AsyncGenerator<{ status?: string; plan?: EditPlan; error?: string }> {
  const r = await fetch(`${ENGINE_URL}/code/plan`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ request, file_paths: filePaths }),
    signal,
  });
  if (!r.ok || !r.body) throw new Error(`plan request failed: ${r.status}`);

  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop() ?? "";
    for (const line of lines) {
      const t = line.trim();
      if (!t.startsWith("data:")) continue;
      const data = t.slice(5).trim();
      if (!data || data === "[DONE]") continue;
      const obj = JSON.parse(data) as { status?: string; plan?: EditPlan; error?: string };
      yield obj;
    }
  }
}

export async function applyPlan(
  patches: FilePatch[],
  takeSnapshot = true,
): Promise<{ written: string[]; errors: string[]; snapshot_ref: string | null }> {
  const r = await fetch(`${ENGINE_URL}/code/apply`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ patches, take_snapshot: takeSnapshot }),
  });
  if (!r.ok) throw new Error(`apply failed: ${r.status}`);
  return r.json() as Promise<{ written: string[]; errors: string[]; snapshot_ref: string | null }>;
}

export async function rollbackPlan(): Promise<{ ok: boolean }> {
  const r = await fetch(`${ENGINE_URL}/code/rollback`, { method: "POST" });
  if (!r.ok) throw new Error(`rollback failed: ${r.status}`);
  return r.json() as Promise<{ ok: boolean }>;
}

// ── File CRUD ──────────────────────────────────────────────────────────────

export async function createFile(path: string, content = ""): Promise<void> {
  const r = await fetch(`${ENGINE_URL}/code/file/new`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ path, content }),
  });
  if (!r.ok) {
    const detail = ((await r.json().catch(() => ({}))) as { detail?: unknown }).detail ?? r.status;
    throw new Error(String(detail));
  }
}

export async function createDir(path: string): Promise<void> {
  const r = await fetch(`${ENGINE_URL}/code/dir/new`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!r.ok) {
    const detail = ((await r.json().catch(() => ({}))) as { detail?: unknown }).detail ?? r.status;
    throw new Error(String(detail));
  }
}

export async function renameFile(
  path: string,
  newName: string,
): Promise<{ old_path: string; new_path: string }> {
  const r = await fetch(`${ENGINE_URL}/code/file/rename`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ path, new_name: newName }),
  });
  if (!r.ok) {
    const detail = ((await r.json().catch(() => ({}))) as { detail?: unknown }).detail ?? r.status;
    throw new Error(String(detail));
  }
  return r.json() as Promise<{ ok: boolean; old_path: string; new_path: string }>;
}

export async function deleteFile(path: string, recursive = false): Promise<void> {
  const url = `${ENGINE_URL}/code/file?path=${encodeURIComponent(path)}&recursive=${recursive}`;
  const r = await fetch(url, { method: "DELETE" });
  if (!r.ok) {
    const detail = ((await r.json().catch(() => ({}))) as { detail?: unknown }).detail ?? r.status;
    throw new Error(String(detail));
  }
}

// ── Find in Files ───────────────────────────────────────────────────────────

export interface SearchHit {
  file: string;
  line: number;
  text: string;
}

export async function findInFiles(query: string, maxResults = 50): Promise<SearchHit[]> {
  const r = await fetch(`${ENGINE_URL}/skills/files/search`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ query, max_results: maxResults }),
  });
  if (!r.ok) throw new Error(`findInFiles failed: ${r.status}`);
  const data = (await r.json()) as { hits: SearchHit[] };
  return data.hits;
}

// Custom commands config
export interface CustomCommand {
  name: string;
  description: string;
  trigger: string;
  prompt_template: string;
}

export async function getCustomCommands(): Promise<CustomCommand[]> {
  const r = await fetch(`${ENGINE_URL}/config/commands`);
  if (!r.ok) throw new Error("failed to fetch custom commands");
  const data = (await r.json()) as { commands: CustomCommand[] };
  return data.commands;
}

export async function saveCustomCommands(commands: CustomCommand[]): Promise<void> {
  const r = await fetch(`${ENGINE_URL}/config/commands`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ commands }),
  });
  if (!r.ok) throw new Error("failed to save custom commands");
}
