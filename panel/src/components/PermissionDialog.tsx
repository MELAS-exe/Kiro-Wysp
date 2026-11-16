import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";

const RISK_LABEL: Record<string, string> = {
  read_only: "reads only",
  ui_state: "changes the view only",
  reversible: "reversible change",
  irreversible: "cannot be undone",
};

/** A text change arrives as `preview.diff` (lines starting with "+", "-" or " "): show it as a diff. Anything else is shown as JSON. */
function PreviewBlock({ preview }: { preview: unknown }) {
  const p = preview as { diff?: unknown; file?: unknown; lines?: unknown } | null;
  if (p && typeof p === "object" && typeof p.diff === "string") {
    return (
      <div>
        {typeof p.file === "string" && (
          <p className="muted small mono">
            {p.file}
            {typeof p.lines === "string" ? `, lines ${p.lines}` : ""}
          </p>
        )}
        <pre className="preview diff" aria-label="Change preview">
          {p.diff.split("\n").map((line, i) => (
            <span key={i} className={line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : undefined}>
              {line + "\n"}
            </span>
          ))}
        </pre>
      </div>
    );
  }
  return <pre className="preview">{JSON.stringify(preview, null, 2)}</pre>;
}

export function PermissionDialog() {
  const perm = useStore((s) => s.permission);
  const send = useStore((s) => s.send);
  const dismiss = useStore((s) => s.dismissPermission);
  const denyRef = useRef<HTMLButtonElement>(null);
  const [left, setLeft] = useState(0);

  useEffect(() => {
    if (!perm) return;
    setLeft(perm.timeout_s);
    const t = setInterval(() => setLeft((v) => Math.max(0, v - 1)), 1000);
    denyRef.current?.focus(); // safe default: Enter never approves
    return () => clearInterval(t);
  }, [perm]);

  if (!perm) return null;
  const answer = (decision: "approve" | "deny" | "grant_lesson") => {
    send({ type: "permission.respond", request_id: perm.request_id, decision, via: "click" });
    dismiss();
  };
  const irreversible = perm.risk === "irreversible";
  return (
    <div className="scrim">
      <div className="dialog" role="alertdialog" aria-labelledby="perm-title" aria-describedby="perm-desc">
        <div className={`risk ${perm.risk}`}>{RISK_LABEL[perm.risk] ?? perm.risk}</div>
        <div className="dialog-body">
          <h2 id="perm-title">{perm.title}</h2>
          {perm.target && <p className="target">on <strong>{perm.target}</strong></p>}
          <p id="perm-desc">{perm.rationale || "Wysp would like to make this change in your application."}</p>
          {perm.preview != null && <PreviewBlock preview={perm.preview} />}
          <p className="muted small">
            {perm.reversible ? "You can undo this afterwards." : "Wysp cannot undo this."}{" "}
            {!perm.voice_allowed && "It needs a click: it cannot be approved by voice."}
          </p>
        </div>
        <div className="actions">
          <button ref={denyRef} onClick={() => answer("deny")} className="secondary">
            Deny
          </button>
          <button onClick={() => answer("approve")} className={irreversible ? "danger" : "primary"}>
            {irreversible ? "Approve and apply" : "Approve"}
          </button>
          {perm.can_grant && (
            <button onClick={() => answer("grant_lesson")} className="ghost" title="Do not ask again for this action during the session">
              Always allow this session
            </button>
          )}
        </div>
        <div className="muted small">Denied automatically in {left}s if you do not answer.</div>
      </div>
    </div>
  );
}
