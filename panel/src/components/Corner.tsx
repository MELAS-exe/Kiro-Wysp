import { useEffect, useRef, useState } from "react";
import type { LogLevel } from "../protocol";
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
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
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
  return (
    <div className="corner" ref={ref}>
      <span className={`dot ${state}`} role="img" aria-label={connected ? `Wysp is ${status}` : "Wysp Core is not reachable"} title={connected ? status : "Reconnecting to the Wysp Core"} />
      {hasBoard && (
        <button className="seg" onClick={() => setView(showingBoard ? "chat" : "board")} aria-label={showingBoard ? "Show the conversation" : "Show the diagram"}>
          {showingBoard ? "Chat" : "Diagram"}
        </button>
      )}
      <button className="menu-btn" onClick={() => setOpen(!open)} aria-label="Menu" aria-expanded={open} aria-haspopup="true">
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
          <circle cx="3" cy="8" r="1.4" fill="currentColor" />
          <circle cx="8" cy="8" r="1.4" fill="currentColor" />
          <circle cx="13" cy="8" r="1.4" fill="currentColor" />
        </svg>
      </button>
      {open && (
        <div className="menu" role="menu">
          <label className="row">
            <span className="muted">Looking at</span>
            {adapters.length > 0 ? (
              <select
                value={active}
                onChange={(e) => send({ type: "adapter.activate", adapter_id: e.target.value })}
                aria-label="Application the tutor is looking at"
              >
                {!active && <option value="">choose</option>}
                {adapters.map((a) => (
                  <option key={a.adapter_id} value={a.adapter_id}>
                    {a.app.name} {a.app.version}
                  </option>
                ))}
              </select>
            ) : (
              <span className="muted">no application connected</span>
            )}
          </label>
          {session?.logging && (
            <label className="row" title={session.logPath ? `Session log: ${session.logPath}` : "Session telemetry"}>
              <span className="muted">Logs</span>
              <select
                value={session.logging}
                onChange={(e) => send({ type: "settings.update", logging: e.target.value as LogLevel })}
                aria-label="Session logging level"
              >
                <option value="off">off</option>
                <option value="basic">basic (no content)</option>
                <option value="full">full (with conversation)</option>
              </select>
            </label>
          )}
          <label className="row">
            <span className="muted">Voice</span>
            <input type="checkbox" checked={voiceOn} onChange={(e) => setVoiceOn(e.target.checked)} />
          </label>
          {explore && ["declined", "stopped", "failed"].includes(explore.phase) && (
            <button className="ghost wide" onClick={() => send({ type: "explore.start" })} title="Map the code and study the main files">
              Explore this project
            </button>
          )}
          <button className="ghost wide" onClick={() => send({ type: "undo.last" })} title="Undo the last change Wysp made">
            Undo Wysp's last change
          </button>
          {session && <div className="muted small foot">Model: {session.model ?? session.llm}</div>}
        </div>
      )}
    </div>
  );
}
