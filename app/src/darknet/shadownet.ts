import { ENGINE_URL } from "../engine";

export interface TorStatus {
  running: boolean;
  bootstrapped: number;
  circuit_established: boolean;
  exit_ip: string | null;
  circuit_age_seconds: number;
  socks_port: number;
}

export interface FetchResult {
  url: string;
  title: string | null;
  html: string;
  status_code: number;
  is_onion: boolean;
  fetch_time_ms: number;
}

export interface SearchResult {
  title: string;
  url: string;
  description: string | null;
  is_onion: boolean;
}

export async function getTorStatus(): Promise<TorStatus | null> {
  try {
    const r = await fetch(`${ENGINE_URL}/dark/status`);
    if (!r.ok) return null;
    return (await r.json()) as TorStatus;
  } catch {
    return null;
  }
}

export async function newCircuit(): Promise<void> {
  await fetch(`${ENGINE_URL}/dark/new-circuit`, { method: "POST" });
}

export async function searchDark(query: string): Promise<SearchResult[]> {
  try {
    const r = await fetch(`${ENGINE_URL}/dark/search?q=${encodeURIComponent(query)}`);
    if (!r.ok) return [];
    const data = (await r.json()) as { results: SearchResult[] };
    return data.results ?? [];
  } catch {
    return [];
  }
}

/** Stream-fetch a URL through Tor. Calls onStart immediately, then onHtml or onError. */
export function streamFetchUrl(
  url: string,
  callbacks: {
    onStart: () => void;
    onHtml: (result: FetchResult) => void;
    onError: (msg: string) => void;
  },
  signal?: AbortSignal,
): void {
  const src = new EventSource(`${ENGINE_URL}/dark/fetch?url=${encodeURIComponent(url)}`);

  const cleanup = () => src.close();

  if (signal) {
    signal.addEventListener("abort", cleanup);
  }

  src.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data) as { type: string; [k: string]: unknown };
      if (data.type === "start") {
        callbacks.onStart();
      } else if (data.type === "html") {
        callbacks.onHtml(data as unknown as FetchResult);
        cleanup();
      } else if (data.type === "error") {
        callbacks.onError((data.message as string) ?? "Unknown error");
        cleanup();
      }
    } catch {
      callbacks.onError("Invalid response from engine");
      cleanup();
    }
  };

  src.onerror = () => {
    callbacks.onError("Connection to engine lost");
    cleanup();
  };
}
