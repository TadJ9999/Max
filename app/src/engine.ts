// Minimal client for the Max engine HTTP API.
// The engine runs locally (see ../../engine). Streaming endpoints return
// OpenAI-compatible SSE; we parse `data:` lines into text deltas.

import type { Session, SessionState } from "./types";

// The engine runs on 8001 by default. In LAN mode it switches to 8443 with HTTPS.
// initEngineBase() must be called before the first API call; the Tauri command
// engine_base() returns the right URL based on .maxconfig.json. In a browser
// served by the engine (mobile) we use relative URLs (same-origin).
export let ENGINE_URL = "http://127.0.0.1:8001";

export async function initEngineBase(): Promise<void> {
  if ("__TAURI_INTERNALS__" in window) {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      ENGINE_URL = await invoke<string>("engine_base");
    } catch {
      // keep default if Tauri invoke fails
    }
  } else {
    // Served from the engine directly (LAN mobile browser) — same-origin
    ENGINE_URL = "";
  }
}

export type Health = { status: string; version: string };

export async function getHealth(): Promise<Health | null> {
  try {
    const r = await fetch(`${ENGINE_URL}/health`, { method: "GET" });
    if (!r.ok) return null;
    return (await r.json()) as Health;
  } catch {
    return null;
  }
}

// Optional metadata surfaced from an SSE stream (currently the resolved model id,
// emitted by the engine on every chunk). `onMeta` fires once, on the first chunk
// that carries a model — useful for showing the invoked model's logo.
export type StreamMeta = { model?: string };

// POST a JSON body to an SSE endpoint and yield text deltas as they arrive.
// Throws if the engine reports an error event in the stream.
async function* streamSSE(
  path: string,
  body: unknown,
  signal?: AbortSignal,
  onMeta?: (m: StreamMeta) => void,
): AsyncGenerator<string> {
  const r = await fetch(`${ENGINE_URL}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!r.ok || !r.body) {
    throw new Error(`engine returned HTTP ${r.status}`);
  }

  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let metaSent = false;

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
      if (data === "" || data === "[DONE]") continue;

      const obj = JSON.parse(data);
      if (obj.error) throw new Error(obj.error.message ?? "engine error");
      if (!metaSent && onMeta && typeof obj.model === "string" && obj.model) {
        metaSent = true;
        onMeta({ model: obj.model });
      }
      const delta: string | undefined = obj.choices?.[0]?.delta?.content;
      if (delta) yield delta;
    }
  }
}

// A DSL command starts with an operator (`.`/`..`/`~`), optionally after a
// provider sigil (`@`/`q`/`#`/`!`/`%`). Anything else is treated as plain chat.
export function isDslCommand(text: string): boolean {
  let s = text.trim();
  if (!s) return false;
  if ("@#!%q".includes(s[0])) s = s.slice(1);
  return s.startsWith(".") || s.startsWith("~");
}

// Stream a full DSL command via /command.
export function streamCommand(
  text: string, signal?: AbortSignal, onMeta?: (m: StreamMeta) => void,
): AsyncGenerator<string> {
  return streamSSE("/command", { text }, signal, onMeta);
}

// Stream a plain conversational reply via /chat (no DSL operators needed).
export function streamChat(
  text: string, signal?: AbortSignal, onMeta?: (m: StreamMeta) => void,
): AsyncGenerator<string> {
  return streamSSE("/chat", { text }, signal, onMeta);
}

// Stream a vision (image + text) reply. Encodes the image to base64 and routes
// to a cloud vision provider (Claude by default).
export function streamChatVision(
  text: string,
  imageBase64: string,
  imageType: string,
  signal?: AbortSignal,
): AsyncGenerator<string> {
  return streamSSE("/chat", { text, image_base64: imageBase64, image_type: imageType }, signal);
}

// DSL check also matches OpenAI (%) and custom triggers.
export function isDslCommandExtended(text: string): boolean {
  let s = text.trim();
  if (!s) return false;
  if ("@#!%q".includes(s[0])) s = s.slice(1);
  return s.startsWith(".") || s.startsWith("~");
}

// ---- Codebase RAG -------------------------------------------------------

export type RagStatus = { files: number; chunks: number; allowlist?: string[] };
export type RagIndexResult = RagStatus & {
  indexed: number;
  skipped: number;
  removed: number;
};

// Stream a workspace-grounded answer (cited by file:line) via /rag/ask.
// Passing a stable sessionId gives the conversation memory across turns.
export function streamAsk(
  question: string,
  sessionId?: string,
  signal?: AbortSignal,
): AsyncGenerator<string> {
  return streamSSE("/rag/ask", { question, session_id: sessionId }, signal);
}

export async function clearRagMemory(sessionId: string): Promise<void> {
  try {
    await fetch(`${ENGINE_URL}/rag/memory/${sessionId}/clear`, { method: "POST" });
  } catch {
    /* offline — nothing to clear */
  }
}

export async function getRagStatus(): Promise<RagStatus | null> {
  try {
    const r = await fetch(`${ENGINE_URL}/rag/status`, { method: "GET" });
    if (!r.ok) return null;
    return (await r.json()) as RagStatus;
  } catch {
    return null;
  }
}

// (Re)index the workspace allowlist; returns the run summary (or null if offline).
export async function indexWorkspace(): Promise<RagIndexResult | null> {
  try {
    const r = await fetch(`${ENGINE_URL}/rag/index`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{}",
    });
    if (!r.ok) return null;
    return (await r.json()) as RagIndexResult;
  } catch {
    return null;
  }
}

// ---- Sessions (delegate) ------------------------------------------------

type RawSession = {
  id: string;
  task: string;
  provider: string;
  model: string;
  is_cloud: boolean;
  state: string;
  output: string;
};

// Engine has a "cancelled" state the widget renders as "done".
const STATE_MAP: Record<string, SessionState> = {
  queued: "queued",
  running: "running",
  done: "done",
  error: "error",
  cancelled: "done",
};

function titleFor(task: string, i: number): string {
  const t = task.trim();
  if (!t) return `TASK #${i + 1}`;
  return t.length > 28 ? `${t.slice(0, 27)}…` : t;
}

// Fetch the engine's sessions, mapped to the widget's Session shape.
// Returns null when the engine is unreachable (caller keeps prior state).
export async function getSessions(): Promise<Session[] | null> {
  try {
    const r = await fetch(`${ENGINE_URL}/sessions`, { method: "GET" });
    if (!r.ok) return null;
    const data = (await r.json()) as { sessions: RawSession[] };
    return data.sessions.map((s, i) => ({
      id: s.id,
      title: titleFor(s.task, i),
      provider: s.provider,
      model: s.model,
      state: STATE_MAP[s.state] ?? "queued",
      isCloud: s.is_cloud,
      output: s.output ?? "",
    }));
  } catch {
    return null;
  }
}

// Live per-session output via GET /sessions/{id}/stream (SSE).
// The engine sends a `snapshot` (output so far) on connect, then `chunk` deltas,
// then a final `done`. We map those to set / append / finish so cards show tokens
// as they're produced instead of waiting on the ~2s poll.
export type SessionStreamHandlers = {
  onSnapshot?: (text: string) => void;
  onDelta?: (text: string) => void;
  onDone?: (state: string) => void;
};

export async function streamSession(
  id: string,
  handlers: SessionStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let r: Response;
  try {
    r = await fetch(`${ENGINE_URL}/sessions/${id}/stream`, { signal });
  } catch {
    return; // offline / mock session — polling still drives the card
  }
  if (!r.ok || !r.body) return;

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
      if (!data) continue;

      const obj = JSON.parse(data) as { type: string; text?: string; state?: string };
      if (obj.type === "snapshot") handlers.onSnapshot?.(obj.text ?? "");
      else if (obj.type === "chunk") handlers.onDelta?.(obj.text ?? "");
      else if (obj.type === "done") {
        handlers.onDone?.(obj.state ?? "done");
        return;
      }
    }
  }
}

export async function cancelSession(id: string): Promise<void> {
  try {
    await fetch(`${ENGINE_URL}/sessions/${id}/cancel`, { method: "POST" });
  } catch {
    /* offline / mock session — local optimistic update stands */
  }
}

export async function promoteSession(id: string): Promise<void> {
  try {
    await fetch(`${ENGINE_URL}/sessions/${id}/promote`, { method: "POST" });
  } catch {
    /* offline / mock session — local optimistic update stands */
  }
}
