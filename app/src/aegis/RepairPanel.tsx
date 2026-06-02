import { useCallback, useEffect, useRef, useState } from "react";
import {
  type RepairKind,
  type RepairPlan,
  applyRepair,
  revertRepair,
  streamRepairProposal,
} from "./aegis";
import { CopyButton } from "../components/CopyButton";

// ─── Diff rendering (shared) ─────────────────────────────────────────────────

export function DiffBlock({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <pre className="aegis__diff">
      {lines.map((line, i) => {
        let cls = "aegis__diff-line--ctx";
        if (line.startsWith("+++") || line.startsWith("---")) cls = "aegis__diff-line--hunk";
        else if (line.startsWith("@@")) cls = "aegis__diff-line--hunk";
        else if (line.startsWith("+")) cls = "aegis__diff-line--add";
        else if (line.startsWith("-")) cls = "aegis__diff-line--del";
        return <span key={i} className={`aegis__diff-line ${cls}`}>{line}{"\n"}</span>;
      })}
    </pre>
  );
}

// ─── Repair panel ────────────────────────────────────────────────────────────

type Phase = "idle" | "streaming" | "proposed" | "note" | "applying" | "applied" | "error";

export function RepairPanel({
  kind,
  id,
  onApplied,
}: {
  kind: RepairKind;
  id: string;
  onApplied?: () => void;
}) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [status, setStatus] = useState("");
  const [note, setNote] = useState("");
  const [plan, setPlan] = useState<RepairPlan | null>(null);
  const [applyMsg, setApplyMsg] = useState("");
  const [applyOk, setApplyOk] = useState(false);
  const [appliedFiles, setAppliedFiles] = useState<string[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  // Reset whenever the selected finding/event changes.
  useEffect(() => {
    abortRef.current?.abort();
    setPhase("idle");
    setStatus("");
    setNote("");
    setPlan(null);
    setApplyMsg("");
    setApplyOk(false);
    setAppliedFiles([]);
  }, [kind, id]);

  const askLeo = useCallback(async () => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setPhase("streaming");
    setStatus("Starting…");
    setNote("");
    setPlan(null);
    setApplyMsg("");
    try {
      for await (const evt of streamRepairProposal(kind, id, ctrl.signal)) {
        if (evt.type === "status") setStatus(evt.text);
        else if (evt.type === "note") {
          setNote(evt.text);
          setPhase("note");
        } else if (evt.type === "plan") {
          setPlan(evt.plan);
          setPhase("proposed");
        }
      }
      // Stream ended without a plan or note → treat as no-op.
      setPhase((p) => (p === "streaming" ? "idle" : p));
    } catch (e: unknown) {
      if ((e as Error)?.name !== "AbortError") {
        setNote(`Error: ${String(e)}`);
        setPhase("error");
      }
    }
  }, [kind, id]);

  const approve = useCallback(async () => {
    if (!plan) return;
    setPhase("applying");
    setApplyMsg("Writing files & verifying…");
    const result = await applyRepair({
      kind,
      id,
      patches: plan.patches.map((p) => ({ path: p.path, new_content: p.new_content })),
      log_id: plan.log_id,
    });
    if (result.ok) {
      setApplyOk(true);
      setAppliedFiles(result.files ?? []);
      setApplyMsg(`Applied & verified ✓  ${result.verification ? `— ${result.verification.slice(0, 200)}` : ""}`);
      setPhase("applied");
      onApplied?.();
    } else {
      setApplyOk(false);
      setApplyMsg(result.error ?? "Apply failed");
      setPhase("proposed"); // allow retry; changes were reverted
    }
  }, [plan, kind, id, onApplied]);

  const rollback = useCallback(async () => {
    if (appliedFiles.length === 0) {
      setApplyMsg("Nothing to roll back.");
      return;
    }
    setApplyMsg("Rolling back…");
    const r = await revertRepair(appliedFiles, plan?.log_id ?? undefined);
    setApplyMsg(r.ok ? "Rolled back ✓" : "Rollback failed");
    if (r.ok) {
      setApplyOk(false);
      onApplied?.();
    }
  }, [appliedFiles, plan, onApplied]);

  const reject = useCallback(() => {
    abortRef.current?.abort();
    setPhase("idle");
    setPlan(null);
    setNote("");
    setApplyMsg("");
  }, []);

  const allDiffs = plan ? plan.patches.map((p) => p.diff).join("\n") : "";

  return (
    <div className="aegis__repair">
      {/* Proposed plan review */}
      {phase === "proposed" || phase === "applying" || phase === "applied" ? (
        plan && (
          <div className="aegis__diag-area">
            {plan.summary && <div className="aegis__diag-text">{plan.summary}</div>}
            {plan.patches.map((p, i) => (
              <div key={i} className="aegis__repair-file">
                <div className="aegis__repair-file-head">
                  <span className="posture__file-path">{p.path.split(/[\\/]/).pop()}</span>
                  {p.description && (
                    <span style={{ color: "#5a7090", fontSize: 11 }}> — {p.description}</span>
                  )}
                </div>
                <DiffBlock text={p.diff} />
              </div>
            ))}
          </div>
        )
      ) : phase === "streaming" ? (
        <div className="aegis__diag-area">
          <span className="aegis__diag-text" style={{ color: "#8aaccc" }}>{status}</span>
          <span className="aegis__cursor" />
        </div>
      ) : (note || phase === "note" || phase === "error") ? (
        <div className="aegis__diag-area">
          <span className="aegis__diag-text" style={{ color: phase === "error" ? "#ff6b6b" : "#8aaccc" }}>
            {note}
          </span>
        </div>
      ) : (
        <div className="aegis__diag-area" style={{ color: "#3a5068", fontSize: 12 }}>
          Click <strong style={{ color: "#ff8c42" }}>🐩 Ask Leo to fix</strong> — Leo will rewrite
          the affected file(s) so you can review the diff, then apply it to the repo.
        </div>
      )}

      {/* Action bar */}
      <div className="aegis__actions">
        {(phase === "idle" || phase === "note" || phase === "error") && (
          <button className="aegis__btn aegis__btn--diagnose" onClick={askLeo}>
            🐩 Ask Leo to fix
          </button>
        )}

        {phase === "streaming" && (
          <button
            className="aegis__btn aegis__btn--reject"
            onClick={() => { abortRef.current?.abort(); setPhase("idle"); }}
          >
            ✕ Stop
          </button>
        )}

        {phase === "proposed" && plan && (
          <>
            <button className="aegis__btn aegis__btn--approve" onClick={approve}>
              ✓ Approve & Apply
            </button>
            <button className="aegis__btn aegis__btn--reject" onClick={reject}>
              Reject
            </button>
          </>
        )}

        {phase === "applying" && (
          <button className="aegis__btn aegis__btn--approve" disabled>
            <span className="aegis__spinner" /> Applying…
          </button>
        )}

        {phase === "applied" && applyOk && appliedFiles.length > 0 && (
          <button className="aegis__btn aegis__btn--reject" onClick={rollback}>
            ↩ Rollback
          </button>
        )}

        {allDiffs && (
          <CopyButton text={allDiffs} className="aegis__btn aegis__btn--dismiss" title="Copy diff" />
        )}

        {applyMsg && (
          <span className={`aegis__toast aegis__toast--${applyOk || applyMsg.startsWith("Rolled back") ? "ok" : "err"}`}>
            {applyMsg}
          </span>
        )}
      </div>
    </div>
  );
}
