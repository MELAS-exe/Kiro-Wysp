import { useEffect } from "react";
import { BoardView } from "./board/BoardView";
import { Chat } from "./components/Chat";
import { Corner } from "./components/Corner";
import { PermissionDialog } from "./components/PermissionDialog";
import { interruptNarration, startNarrationPlayer } from "./narration";
import { connect, useStore } from "./store";
import { startListening, stopListening, voiceSupported } from "./voice";

function isTyping(el: EventTarget | null): boolean {
  const t = (el as HTMLElement | null)?.tagName;
  return t === "INPUT" || t === "TEXTAREA" || t === "SELECT" || t === "BUTTON";
}

/** Minimal shell: one thing fills the panel, the conversation or the diagram. No header. */
export function App() {
  const connected = useStore((s) => s.connected);
  const view = useStore((s) => s.view);
  const hasBoard = useStore((s) => s.board.nodes.length > 0);

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

  return (
    <div className="app">
      <Corner />
      {!connected && (
        <div className="banner">
          Cannot reach the Wysp Core. Start it with <code>uv run wysp serve</code>.
        </div>
      )}
      <main>{view === "board" && hasBoard ? <BoardView /> : <Chat />}</main>
      <PermissionDialog />
    </div>
  );
}
