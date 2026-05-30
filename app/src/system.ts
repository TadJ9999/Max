// Live system meters from the Rust backend (CPU/RAM via sysinfo, GPU/VRAM via
// nvidia-smi). Returns null outside Tauri (e.g. the vite browser preview) so the
// widget keeps its placeholder values there.

import type { SysInfo } from "./components/TopBar";

type RawStats = {
  cpu: number;
  ram: number;
  gpu: number;
  vram: number;
  gpu_available: boolean;
};

function inTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export async function getSystemStats(): Promise<SysInfo | null> {
  if (!inTauri()) return null;
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    const s = await invoke<RawStats>("get_system_stats");
    return { cpu: s.cpu, gpu: s.gpu, vram: s.vram, ram: s.ram };
  } catch {
    return null;
  }
}
