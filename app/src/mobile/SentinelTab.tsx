import { useState, useEffect } from "react";
import { ENGINE_URL } from "../engine";
import type { SpaceWeather, Launch, ISS } from "../sentinel/sentinel";

async function getSentinel<T>(path: string): Promise<T | null> {
  try {
    const r = await fetch(`${ENGINE_URL}${path}`);
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch { return null; }
}

const KP_LABEL = ["Quiet", "Quiet", "Quiet", "Quiet", "Quiet", "Active", "Storm G1", "Storm G2", "Storm G3", "Storm G4+"] as const;

export function SentinelTab() {
  const [sw, setSw] = useState<SpaceWeather | null>(null);
  const [launches, setLaunches] = useState<Launch[]>([]);
  const [iss, setIss] = useState<ISS | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    const [swData, launchData, issData] = await Promise.all([
      getSentinel<SpaceWeather>("/sentinel/space-weather"),
      getSentinel<{ launches: Launch[] }>("/sentinel/launches"),
      getSentinel<ISS>("/sentinel/iss"),
    ]);
    setSw(swData);
    setLaunches(launchData?.launches ?? []);
    setIss(issData);
    setLoading(false);
  };

  useEffect(() => {
    void load();
    const id = setInterval(() => void getSentinel<ISS>("/sentinel/iss").then(setIss), 10_000);
    return () => clearInterval(id);
  }, []);

  if (loading) return <div className="mob-loading">Loading space data…</div>;

  const kp = sw?.kp ?? null;
  const kpLabel = kp !== null ? (KP_LABEL[Math.round(Math.min(kp, 9))] ?? "Unknown") : "—";
  const kpColor = kp === null ? "#7f95a3" : kp >= 6 ? "#f43f5e" : kp >= 5 ? "#f97316" : "#22d3ee";

  return (
    <div className="mob-scroll">
      <div className="mob-section-head">
        <span className="mob-section-title">Space Intelligence</span>
        <button className="mob-btn" onClick={() => void load()}>↻</button>
      </div>

      {/* Space weather */}
      <div className="mob-card">
        <div className="mob-card__title">Space Weather</div>
        <div className="mob-sent-row">
          <span className="mob-sent-label">Kp index</span>
          <span className="mob-sent-val" style={{ color: kpColor }}>
            {kp !== null ? kp.toFixed(1) : "—"} · {kpLabel}
          </span>
        </div>
        {sw?.wind_speed !== null && sw?.wind_speed !== undefined && (
          <div className="mob-sent-row">
            <span className="mob-sent-label">Solar wind</span>
            <span className="mob-sent-val">{sw.wind_speed.toFixed(0)} km/s</span>
          </div>
        )}
        {sw?.storm && sw.storm !== "G0" && (
          <div className="mob-sent-row">
            <span className="mob-sent-label">Storm level</span>
            <span className="mob-sent-val" style={{ color: "#f43f5e" }}>{sw.storm}</span>
          </div>
        )}
      </div>

      {/* ISS */}
      {iss && (
        <div className="mob-card">
          <div className="mob-card__title">ISS — Live</div>
          {iss.lat !== null && iss.lon !== null && (
            <div className="mob-sent-row">
              <span className="mob-sent-label">Position</span>
              <span className="mob-sent-val">
                {iss.lat.toFixed(2)}° {iss.lat >= 0 ? "N" : "S"},{" "}
                {iss.lon.toFixed(2)}° {iss.lon >= 0 ? "E" : "W"}
              </span>
            </div>
          )}
          {iss.altitude_km !== null && (
            <div className="mob-sent-row">
              <span className="mob-sent-label">Altitude</span>
              <span className="mob-sent-val">{iss.altitude_km.toFixed(0)} km</span>
            </div>
          )}
          {iss.velocity_kms !== null && (
            <div className="mob-sent-row">
              <span className="mob-sent-label">Speed</span>
              <span className="mob-sent-val">{iss.velocity_kms.toFixed(2)} km/s</span>
            </div>
          )}
          {iss.crew.length > 0 && (
            <div className="mob-sent-row mob-sent-row--col">
              <span className="mob-sent-label">Crew ({iss.crew.length})</span>
              <span className="mob-sent-val mob-sent-val--crew">{iss.crew.join(" · ")}</span>
            </div>
          )}
        </div>
      )}

      {/* Upcoming launches */}
      {launches.length > 0 && (
        <>
          <div className="mob-section-head" style={{ marginTop: 12 }}>
            <span className="mob-section-title">Upcoming Launches</span>
          </div>
          {launches.slice(0, 5).map((l) => (
            <div key={l.id} className="mob-card mob-launch">
              <div className="mob-launch__name">{l.name}</div>
              <div className="mob-launch__meta">
                {l.provider} · {l.vehicle}
              </div>
              <div className="mob-launch__meta">{l.location}</div>
              <div className="mob-launch__net">{new Date(l.net).toLocaleString()}</div>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
