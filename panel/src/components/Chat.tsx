import { useEffect, useRef, useState } from "react";
import { interruptNarration } from "../narration";
import { useStore } from "../store";
import { startListening, stopListening, voiceSupported } from "../voice";

function LiveCaption() {
  const current = useStore((s) => s.current);
  const status = useStore((s) => s.status);
  const activity = useStore((s) => s.activity);
  const listening = useStore((s) => s.listening);
  const interim = useStore((s) => s.interim);
  if (listening) return <div className="caption listening">🎙 {interim || "Listening…"}</div>;
  if (current)
    return (
      <div className="caption" aria-live="polite">
        {current.marker && <span className="marker">{current.marker}</span>}
        {current.text}
      </div>
    );
  if (status !== "idle")
    return (
      <div className="caption dim" aria-live="polite">
        <span className="dots" aria-hidden /> {activity || (status === "thinking" ? "Thinking…" : status === "acting" ? "Working in the application…" : "")}
      </div>
    );
  return <div className="caption dim">Hold <kbd>Space</kbd> to talk, or type below. <kbd>Esc</kbd> interrupts me.</div>;
}

export function Chat() {
  const transcript = useStore((s) => s.transcript);
  const status = useStore((s) => s.status);
  const send = useStore((s) => s.send);
  const addUser = useStore((s) => s.addUser);
  const clarification = useStore((s) => s.clarification);
  const dismissClarification = useStore((s) => s.dismissClarification);
  const voiceOn = useStore((s) => s.voiceOn);
  const setVoiceOn = useStore((s) => s.setVoiceOn);
  const listening = useStore((s) => s.listening);
  const [text, setText] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  // Show Wysp's sentences as they are spoken, not all at once when they arrive.
  const visible = transcript.filter((t) => !(t.kind === "wysp" && (t.state === "queued" || t.state === "skipped")));
  const hasCancelled = transcript.some((t) => t.kind === "wysp" && (t.state === "cancelled" || t.state === "skipped"));
  const busy = status !== "idle";

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [visible.length, clarification]);

  const submit = (value: string) => {
    const v = value.trim();
    if (!v) return;
    addUser(v, "typed");
    send({ type: "user.message", text: v, source: "typed" });
    dismissClarification();
    setText("");
  };

  return (
    <section className="chat" aria-label="Conversation">
      <LiveCaption />
      <div className="transcript" role="log" aria-live="off">
        {visible.map((t) => {
          if (t.kind === "user")
            return (
              <div key={t.id} className="msg user">
                {t.source === "voice" && <span aria-label="spoken">🎙 </span>}
                {t.text}
              </div>
            );
          if (t.kind === "wysp")
            return (
              <div key={t.id} className={`msg wysp ${t.state}`}>
                {t.segment.marker && <span className="marker">{t.segment.marker}</span>}
                {t.segment.text}
              </div>
            );
          if (t.kind === "evidence")
            return (
              <div key={t.id} className={`msg evidence ${t.ok ? "ok" : "bad"}`}>
                {t.ok ? "✓ Verified in the application" : "✕ Could not be verified"}: {t.title}
              </div>
            );
          return (
            <div key={t.id} className={`msg note ${t.tone}`}>
              {t.text}
            </div>
          );
        })}
        {clarification && (
          <div className="clarify">
            <div className="msg wysp">{clarification.question}</div>
            <div className="chips">
              {clarification.options.map((o) => (
                <button key={o} className="chip" onClick={() => submit(o)}>
                  {o}
                </button>
              ))}
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>
      <div className="controls">
        {busy && (
          <button className="secondary" onClick={interruptNarration} aria-label="Interrupt (Esc)">
            ⏹ Interrupt
          </button>
        )}
        {!busy && hasCancelled && (
          <button className="secondary" onClick={() => send({ type: "user.continue" })}>
            ▶ Continue
          </button>
        )}
        <button className="ghost" onClick={() => send({ type: "undo.last" })} title="Undo the last change Wysp made">
          ↩ Undo Wysp's last change
        </button>
        <label className="toggle">
          <input type="checkbox" checked={voiceOn} onChange={(e) => setVoiceOn(e.target.checked)} /> Voice
        </label>
      </div>
      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          submit(text);
        }}
      >
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Ask about your project…"
          aria-label="Message"
          autoComplete="off"
        />
        {voiceSupported && (
          <button
            type="button"
            className={`mic${listening ? " on" : ""}`}
            aria-label="Hold to talk"
            onPointerDown={startListening}
            onPointerUp={stopListening}
            onPointerLeave={() => listening && stopListening()}
          >
            🎙
          </button>
        )}
        <button type="submit" className="primary" disabled={!text.trim()}>
          Send
        </button>
      </form>
    </section>
  );
}
