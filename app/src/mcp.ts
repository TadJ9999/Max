// Client for the engine's MCP host + façade endpoints. Mirrors the other module
// clients: hit ENGINE_URL, return safe fallbacks on failure.

import { ENGINE_URL } from "./engine";

export type McpTool = { name: string; description?: string; inputSchema?: unknown };

export type McpServer = {
  name: string;
  transport: string;
  command: string[];
  url: string;
  enabled: boolean;
  connected: boolean;
  tools: McpTool[];
  serverInfo: Record<string, unknown>;
  error: string | null;
};

export type McpFacade = {
  tools: McpTool[];
  command: string[];
  claudeDesktopConfig: unknown;
};

export async function getMcpServers(): Promise<McpServer[]> {
  try {
    const r = await fetch(`${ENGINE_URL}/mcp/servers`);
    if (!r.ok) return [];
    return ((await r.json()).servers ?? []) as McpServer[];
  } catch {
    return [];
  }
}

export async function addMcpServer(server: {
  name: string;
  transport: string;
  command: string[];
  cwd?: string;
  url?: string;
}): Promise<McpServer[]> {
  const r = await fetch(`${ENGINE_URL}/mcp/servers`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ cwd: "", url: "", ...server }),
  });
  if (!r.ok) throw new Error(`add failed: HTTP ${r.status}`);
  return ((await r.json()).servers ?? []) as McpServer[];
}

export async function removeMcpServer(name: string): Promise<McpServer[]> {
  const r = await fetch(`${ENGINE_URL}/mcp/servers/${encodeURIComponent(name)}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`remove failed: HTTP ${r.status}`);
  return ((await r.json()).servers ?? []) as McpServer[];
}

export async function connectMcpServer(name: string): Promise<McpServer> {
  const r = await fetch(`${ENGINE_URL}/mcp/servers/${encodeURIComponent(name)}/connect`, { method: "POST" });
  if (!r.ok) {
    const detail = await r.json().then((j) => j.detail).catch(() => `HTTP ${r.status}`);
    throw new Error(String(detail));
  }
  return (await r.json()) as McpServer;
}

export async function disconnectMcpServer(name: string): Promise<void> {
  await fetch(`${ENGINE_URL}/mcp/servers/${encodeURIComponent(name)}/disconnect`, { method: "POST" });
}

export async function callMcpTool(
  server: string,
  tool: string,
  args: Record<string, unknown> = {},
): Promise<{ text: string; result: unknown }> {
  const r = await fetch(`${ENGINE_URL}/mcp/call`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ server, tool, arguments: args }),
  });
  if (!r.ok) {
    const detail = await r.json().then((j) => j.detail).catch(() => `HTTP ${r.status}`);
    throw new Error(String(detail));
  }
  return (await r.json()) as { text: string; result: unknown };
}

export async function getMcpFacade(): Promise<McpFacade | null> {
  try {
    const r = await fetch(`${ENGINE_URL}/mcp/facade`);
    if (!r.ok) return null;
    return (await r.json()) as McpFacade;
  } catch {
    return null;
  }
}
