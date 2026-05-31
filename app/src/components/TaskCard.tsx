// One glass card per engine session. Shows model · provider · state, a ☁ marker
// for cloud (`!`) tasks, and quick actions (cancel; promote-to-cloud while queued).

import type { Session } from "../types";

type Props = {
  session: Session;
  onCancel: (id: string) => void;
  onPromote: (id: string) => void;
};

export function TaskCard({ session, onCancel, onPromote }: Props) {
  const { id, title, provider, model, state, isCloud, output } = session;
  const live = (output ?? "").trim();
  return (
    <article className={`card card--${state}`}>
      <div className="card__head">
        <span className="card__title">{title}</span>
        <span className={`badge badge--${state}`}>{state}</span>
      </div>
      <div className="card__meta">
        <span className="card__provider">
          {isCloud ? "☁ " : ""}
          {provider}
        </span>
        <span className="card__sep">·</span>
        <span className="card__model">{model}</span>
      </div>
      {live && (
        <pre className={`card__output${state === "running" ? " card__output--live" : ""}`}>
          {live}
        </pre>
      )}
      <div className="card__actions">
        {state === "queued" && (
          <button className="act act--promote" onClick={() => onPromote(id)} title="Promote to cloud">
            ☁ promote
          </button>
        )}
        {(state === "queued" || state === "running") && (
          <button className="act act--cancel" onClick={() => onCancel(id)} title="Cancel">
            cancel
          </button>
        )}
      </div>
    </article>
  );
}
