import { useEffect } from "react";
import { BoardView } from "./board/BoardView";
import { Chat } from "./components/Chat";
import { PermissionDialog } from "./components/PermissionDialog";
import { interruptNarration, startNarrationPlayer } from "./narration";
import type { LogLevel } from "./protocol";
import { connect, useStore } from "./store";
import { startListening, stopListening, voiceSupported } from "./voice";

function isTyping(el: EventTarget | null): boolean {
  const t = (el as HTMLElement | null)?.tagName;
  return t === "INPUT" || t === "TEXTAREA" || t === "SELECT" || t === "BUTTON";
}

export function App() {
  const connected = useStore((s) => s.connected);
  const session = useStore((s) => s.session);
  const adapters = useStore((s) => s.adapters);
  const status = useStore((s) => s.status);
  const send = useStore((s) => s.send);
  const mode = useStore((s) => s.mode);
  const setMode = useStore((s) => s.setMode);

  useEffect(() => {
    const stopCore = connect();
    const stopPlayer = startNarrationPlayer();
    const down = (e: KeyboardEvent) => {
      if (e.key === "Escape") interruptNarration();
      if (e.code === "Space" && !e.repeat && voiceSupported && !isTyping(e.target)) {
        e.preventDefault();
        startListening();
      }
    };
    const up = (e: KeyboardEvent) => {
      if (e.code === "Space" && !isTyping(e.target)) stopListening();
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      stopCore();
      stopPlayer();
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, []);

  const active = session?.active_adapter ?? "";
  return (
    <div className={`app ${mode}`}>
      <header className="top">
        <div className="brand">
          <span className={`orb small ${status}`} aria-hidden />
          <strong>Wysp</strong>
          <span className={`pill ${connected ? "ok" : "bad"}`}>{connected ? status : "reconnecting…"}</span>
        </div>
        <div className="spacer" />
        {adapters.length > 0 ? (
          <label className="adapter">
            <span className="muted">Looking at</span>
            <select
              value={active}
              onChange={(e) => send({ type: "adapter.activate", adapter_id: e.target.value })}
              aria-label="Application the tutor is looking at"
            >
              {!active && <option value="">choose…</option>}
              {adapters.map((a) => (
                <option key={a.adapter_id} value={a.adapter_id}>
                  {a.app.name} {a.app.version} · {a.integration_level}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <span className="muted">No application connected</span>
        )}
        {session && (
          <span className="muted small" title="language model">
            LLM: {session.model ?? session.llm}
          </span>
        )}
        {session?.logging && (
          <label className="small" title={session.logPath ? `Session log: ${session.logPath}` : "Session telemetry"}>
            <span className="muted">Logs</span>{" "}
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
        <button className="ghost" onClick={() => setMode(mode === "side" ? "full" : "side")} aria-label="Toggle layout">
          {mode === "side" ? "⤢ Full" : "⤡ Side"}
        </button>
      </header>
      {!connected && <div className="banner">Cannot reach the Wysp Core. Start it with <code>uv run wysp serve</code>.</div>}
      <main>
        <BoardView />
        <Chat />
      </main>
      <PermissionDialog />
    </div>
  );
}
