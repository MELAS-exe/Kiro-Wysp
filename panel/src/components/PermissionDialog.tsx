import { useEffect, useRef, useState } from "react";
import { useT } from "../i18n";
import { rich } from "../i18n/rich";
import { useStore } from "../store";

const RISKS = ["read_only", "ui_state", "reversible", "irreversible"];

/** A text change arrives as `preview.diff` (lines starting with "+", "-" or " "): show it as a diff. Anything else is shown as JSON. */
function PreviewBlock({ preview }: { preview: unknown }) {
  const t = useT();
  const p = preview as { diff?: unknown; file?: unknown; lines?: unknown } | null;
  if (p && typeof p === "object" && typeof p.diff === "string") {
    return (
      <div>
        {typeof p.file === "string" && (
          <p className="muted small mono">
            {p.file}
            {typeof p.lines === "string" ? t("perm.lines", { lines: p.lines }) : ""}
          </p>
        )}
        <pre className="preview diff" aria-label={t("perm.diff")} tabIndex={0}>
          {p.diff.split("\n").map((line, i) => (
            <span key={i} className={line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : undefined}>
              {line + "\n"}
            </span>
          ))}
        </pre>
      </div>
    );
  }
  return <pre className="preview" tabIndex={0} aria-label={t("perm.preview")}>{JSON.stringify(preview, null, 2)}</pre>;
}

export function PermissionDialog() {
  const t = useT();
  const perm = useStore((s) => s.permission);
  const send = useStore((s) => s.send);
  const dismiss = useStore((s) => s.dismissPermission);
  const denyRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const [left, setLeft] = useState(0);

  useEffect(() => {
    if (!perm) return;
    setLeft(perm.timeout_s);
    const t = setInterval(() => setLeft((v) => Math.max(0, v - 1)), 1000);
    const before = document.activeElement as HTMLElement | null;
    denyRef.current?.focus(); // safe default: Enter never approves
    return () => {
      clearInterval(t);
      before?.focus?.(); // give the focus back to what had it
    };
  }, [perm]);

  if (!perm) return null;
  const answer = (decision: "approve" | "deny" | "grant_lesson") => {
    send({ type: "permission.respond", request_id: perm.request_id, decision, via: "click" });
    dismiss();
  };
  // Focus stays inside the dialog (Tab wraps), and Esc denies: the safe answer.
  const keys = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      answer("deny");
      return;
    }
    if (e.key !== "Tab") return;
    const items = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>("button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex=\"-1\"])") ?? []);
    const first = items[0];
    const last = items[items.length - 1];
    if (!first || !last) return;
    const cur = document.activeElement;
    if (e.shiftKey && (cur === first || !dialogRef.current?.contains(cur))) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && (cur === last || !dialogRef.current?.contains(cur))) {
      e.preventDefault();
      first.focus();
    }
  };
  const irreversible = perm.risk === "irreversible";
  return (
    <div className="scrim">
      <div className="dialog" ref={dialogRef} role="alertdialog" aria-modal="true" aria-labelledby="perm-title" aria-describedby="perm-desc" onKeyDown={keys}>
        <div className={`risk ${perm.risk}`}>
          <span className="sr-only">{t("perm.risk")}</span>
          {RISKS.includes(perm.risk) ? t(`perm.risk.${perm.risk}`) : perm.risk}
        </div>
        <div className="dialog-body">
          <h2 id="perm-title">{perm.title}</h2>
          {perm.target && <p className="target">{rich("perm.on", { target: <strong>{perm.target}</strong> })}</p>}
          <p id="perm-desc">{perm.rationale || t("perm.rationale")}</p>
          {perm.preview != null && <PreviewBlock preview={perm.preview} />}
          <p className="muted small">
            {perm.reversible ? t("perm.undoable") : t("perm.notUndoable")}{" "}
            {!perm.voice_allowed && t("perm.needsClick")}
          </p>
        </div>
        <div className="actions">
          <button ref={denyRef} onClick={() => answer("deny")} className="secondary">
            {t("perm.deny")}
          </button>
          <button onClick={() => answer("approve")} className={irreversible ? "danger" : "primary"}>
            {irreversible ? t("perm.approveApply") : t("perm.approve")}
          </button>
          {perm.can_grant && (
            <button onClick={() => answer("grant_lesson")} className="ghost" title={t("perm.grantTitle")}>
              {t("perm.grant")}
            </button>
          )}
        </div>
        <div className="muted small" role="timer" aria-live="off">{t("perm.timeout", { seconds: left })}</div>
      </div>
    </div>
  );
}
