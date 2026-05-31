// Top bar: SYS INFO meters (left) + settings cog (right).
// Meter values are mock until a Rust `sysinfo`/nvidia-smi command is wired
// (ROADMAP Phase 3). VRAM is emphasized — it's the 12 GB bottleneck.

import { Meter } from "./Meter";

export type SysInfo = {
  cpu: number;
  gpu: number;
  vram: number;
  ram: number;
  /** GPU temperature in °C (0 when unavailable). Drives the mascot's heat. */
  gpuTemp: number;
};

type Props = {
  sys: SysInfo;
  onSettings: () => void;
  onShutdown: () => void;
};

export function TopBar({ sys, onSettings, onShutdown }: Props) {
  return (
    <header className="topbar">
      <div className="topbar__meters">
        <Meter label="CPU" percent={sys.cpu} />
        <Meter label="GPU" percent={sys.gpu} />
        <Meter label="VRAM" percent={sys.vram} emphasis />
        <Meter label="RAM" percent={sys.ram} />
      </div>
      <div className="topbar__actions">
        <button className="cog" onClick={onSettings} title="Settings" aria-label="Settings">
          ⚙
        </button>
        <button
          className="power"
          onClick={onShutdown}
          title="Shut down Max"
          aria-label="Shut down Max"
        >
          ⏻
        </button>
      </div>
    </header>
  );
}
