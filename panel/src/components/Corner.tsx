import { useEffect, useRef, useState } from "react";
import type { LogLevel } from "../protocol";
import { useT } from "../i18n";
import { LAYOUT_MODES, parseMode } from "../layoutMode";
import { useStore } from "../store";

/** The only chrome left: a status dot, the Chat/Diagram switch (when there is a diagram) and a menu for the rest. */
export function Corner() {
  const connected = useStore((s) => s.connected);
  const status = useStore((s) => s.status);
  const session = useStore((s) => s.session);
  const adapters = useStore((s) => s.adapters);
  const send = useStore((s) => s.send);
  const view = useStore((s) => s.view);
  const setView = useStore((s) => s.setView);
  const hasBoard = useStore((s) => s.board.nodes.length > 0);
  const voiceOn = useStore((s) => s.voiceOn);
  const setVoiceOn = useStore((s) => s.setVoiceOn);
  const explore = useStore((s) => s.explore);
  const mode = useStore((s) => s.mode);
  const setMode = useStore((s) => s.setMode);
  const t = useT();
  const btnRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      btnRef.current?.focus();
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  const active = session?.active_adapter ?? "";
  const state = connected ? status : "offline";
  const showingBoard = view === "board" && hasBoard;
  // Arrow keys move between the two tabs (roving tabindex), as in the ARIA tabs pattern.
  const tabKeys = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const next = showingBoard ? "chat" : "board";
    setView(next);
    document.getElementById(`tab-${next}`)?.focus();
  };
  return (
    <div className="corner" ref={ref}>
      <span className={`dot ${state}`} role="img" aria-label={connected ? t("corner.dot.on", { status: t(`status.${status}`) }) : t("corner.dot.off")} title={connected ? t(`status.${status}`) : t("corner.dot.reconnecting")} />
      {hasBoard && (
        <div className="tabs" role="tablist" aria-label={t("corner.view")} onKeyDown={tabKeys}>
          {(["chat", "board"] as const).map((v) => (
            <button
              key={v}
              id={`tab-${v}`}
              role="tab"
              aria-selected={(v === "board") === showingBoard}
              tabIndex={(v === "board") === showingBoard ? 0 : -1}
              onClick={() => setView(v)}
            >
              {v === "chat" ? t("corner.tab.chat") : t("corner.tab.board")}
            </button>
          ))}
        </div>
      )}
      <button ref={btnRef} className="menu-btn" onClick={() => setOpen(!open)} aria-label={t("corner.menu")} aria-expanded={open} aria-controls="wysp-menu">
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
          <circle cx="3" cy="8" r="1.4" fill="currentColor" />
          <circle cx="8" cy="8" r="1.4" fill="currentColor" />
          <circle cx="13" cy="8" r="1.4" fill="currentColor" />
        </svg>
      </button>
      {open && (
        <div className="menu" id="wysp-menu" role="group" aria-label={t("corner.settings")}>
          <label className="row">
            <span className="muted">{t("corner.layout")}</span>
            <select value={mode} onChange={(e) => setMode(parseMode(e.target.value) ?? "side")} aria-label={t("corner.layoutAria")}>
              {LAYOUT_MODES.map((m) => (
                <option key={m} value={m}>
                  {t(`mode.${m}`)}
                </option>
              ))}
            </select>
          </label>
          <label className="row">
            <span className="muted">{t("corner.lookingAt")}</span>
            {adapters.length > 0 ? (
              <select
                value={active}
                onChange={(e) => send({ type: "adapter.activate", adapter_id: e.target.value })}
                aria-label={t("corner.lookingAtAria")}
              >
                {!active && <option value="">{t("corner.choose")}</option>}
                {adapters.map((a) => (
                  <option key={a.adapter_id} value={a.adapter_id}>
                    {a.app.name} {a.app.version}
                  </option>
                ))}
              </select>
            ) : (
              <span className="muted">{t("corner.noApp")}</span>
            )}
          </label>
          {session?.logging && (
            <label className="row" title={session.logPath ? t("corner.logsPath", { path: session.logPath }) : t("corner.logsTitle")}>
              <span className="muted">{t("corner.logs")}</span>
              <select
                value={session.logging}
                onChange={(e) => send({ type: "settings.update", logging: e.target.value as LogLevel })}
                aria-label={t("corner.logsAria")}
              >
                <option value="off">{t("corner.log.off")}</option>
                <option value="basic">{t("corner.log.basic")}</option>
                <option value="full">{t("corner.log.full")}</option>
              </select>
            </label>
          )}
          <label className="row">
            <span className="muted" aria-hidden="true">{t("corner.voice")}</span>
            <input type="checkbox" checked={voiceOn} onChange={(e) => setVoiceOn(e.target.checked)} aria-label={t("corner.voiceAria")} />
          </label>
          {explore && ["declined", "stopped", "failed"].includes(explore.phase) && (
            <button className="ghost wide" onClick={() => send({ type: "explore.start" })} title={t("corner.exploreTitle")}>
              {t("corner.explore")}
            </button>
          )}
          <button className="ghost wide" onClick={() => send({ type: "undo.last" })} title={t("corner.undoTitle")}>
            {t("corner.undo")}
          </button>
          {session && <div className="muted small foot">{t("corner.model", { model: session.model ?? session.llm })}</div>}
        </div>
      )}
    </div>
  );
}
