import { useEffect, useRef, useState } from "react";
import { interruptNarration } from "../narration";
import { useStore } from "../store";
import { ExploreCard } from "./ExploreCard";
import { startListening, stopListening, voiceSupported } from "../voice";

/** The conversation, ChatGPT style: your messages in bubbles on the right, Wysp's words as plain text. */
export function Chat() {
  const transcript = useStore((s) => s.transcript);
  const status = useStore((s) => s.status);
  const activity = useStore((s) => s.activity);
  const send = useStore((s) => s.send);
  const addUser = useStore((s) => s.addUser);
  const setView = useStore((s) => s.setView);
  const clarification = useStore((s) => s.clarification);
  const dismissClarification = useStore((s) => s.dismissClarification);
  const listening = useStore((s) => s.listening);
  const interim = useStore((s) => s.interim);
  const [text, setText] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  // Show Wysp's sentences as they are spoken, not all at once when they arrive.
  const visible = transcript.filter((t) => !(t.kind === "wysp" && (t.state === "queued" || t.state === "skipped")));
  const hasCancelled = transcript.some((t) => t.kind === "wysp" && (t.state === "cancelled" || t.state === "skipped"));
  const busy = status !== "idle";

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [visible.length, clarification, busy]);

  const submit = (value: string) => {
    const v = value.trim();
    if (!v) return;
    addUser(v, "typed");
    send({ type: "user.message", text: v, source: "typed" });
    dismissClarification();
    setText("");
    setView("chat");
  };

  return (
    <section className="chat" aria-label="Conversation">
      <div className="transcript" role="log" aria-live="off">
        {visible.length === 0 && !clarification && (
          <div className="hello">
            <img className="mascot" src="/wysp-mark.png" alt="" width={96} height={96} />
            <p>Ask about your project</p>
            <p className="muted small">
              Hold <kbd>Space</kbd> to talk. <kbd>Esc</kbd> interrupts.
            </p>
          </div>
        )}
        {visible.map((t) => {
          if (t.kind === "user")
            return (
              <div key={t.id} className="msg user">
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
                {t.ok ? "Verified in the application" : "Could not be verified"}: {t.title}
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
        {busy && (
          <div className="msg wait" aria-live="polite">
            <span className="dots" aria-hidden />
            {activity || (status === "thinking" ? "Thinking" : status === "acting" ? "Working in the application" : "")}
          </div>
        )}
        <div ref={endRef} />
      </div>
      <ExploreCard />
      {(busy || hasCancelled) && (
        <div className="quick">
          {busy ? (
            <button className="secondary" onClick={interruptNarration} aria-label="Interrupt (Esc)">
              Stop
            </button>
          ) : (
            <button className="secondary" onClick={() => send({ type: "user.continue" })}>
              Continue
            </button>
          )}
        </div>
      )}
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
          placeholder={listening ? interim || "Listening..." : "Ask about your project"}
          aria-label="Message"
          autoComplete="off"
        />
        {voiceSupported && (
          <button
            type="button"
            className={`icon${listening ? " on" : ""}`}
            aria-label="Hold to talk"
            title="Hold to talk"
            onPointerDown={startListening}
            onPointerUp={stopListening}
            onPointerLeave={() => listening && stopListening()}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
              <rect x="5.5" y="1.5" width="5" height="8" rx="2.5" fill="currentColor" />
              <path d="M3 7.5a5 5 0 0 0 10 0M8 12.5v2" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round" />
            </svg>
          </button>
        )}
        <button type="submit" className="icon primary" disabled={!text.trim()} aria-label="Send" title="Send">
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
            <path d="M8 13V3M3.5 7.5 8 3l4.5 4.5" stroke="currentColor" strokeWidth="1.8" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </form>
    </section>
  );
}
