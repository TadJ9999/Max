// A small labeled usage meter (CPU / GPU / VRAM / RAM).
// `emphasis` highlights VRAM, the 12 GB ceiling that decides when local queues.

type Props = {
  label: string;
  percent: number;
  emphasis?: boolean;
};

export function Meter({ label, percent, emphasis }: Props) {
  const pct = Math.max(0, Math.min(100, Math.round(percent)));
  return (
    <div className={`meter${emphasis ? " meter--emphasis" : ""}`} title={`${label} ${pct}%`}>
      <span className="meter__label">{label}</span>
      <div className="meter__track">
        <div
          className="meter__fill"
          style={{ width: `${pct}%` }}
          data-hot={pct >= 85 ? "true" : "false"}
        />
      </div>
      <span className="meter__pct">{pct}%</span>
    </div>
  );
}
