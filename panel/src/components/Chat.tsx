import { useEffect, useRef, useState } from "react";
import { useT } from "../i18n";
import { rich } from "../i18n/rich";
import { interruptNarration } from "../narration";
import { useStore } from "../store";
import { ExerciseCard } from "./ExerciseCard";
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
  const mode = useStore((s) => s.mode);
  const t = useT();
  const [text, setText] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  // Show Wysp's sentences as they are spoken, not all at once when they arrive.
  const all = transcript.filter((t) => !(t.kind === "wysp" && (t.state === "queued" || t.state === "skipped")));
  const visible = mode === "compact" ? all.slice(-2) : all; // compact: the last exchange only
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
    <section className="chat" aria-label={t("chat.conversation")}>
      <div className="transcript" role="log" aria-live="polite" aria-label={t("chat.history")} tabIndex={0}>
        {visible.length === 0 && !clarification && (
          <div className="hello">
            <img className="mascot" src="/wysp-mark.png" alt="" width={96} height={96} />
            <p>{t("chat.ask")}</p>
            <p className="muted small">
              {rich("chat.hintTalk", { space: <kbd>Space</kbd>, esc: <kbd>Esc</kbd> })}
            </p>
          </div>
        )}
        {visible.map((item) => {
          if (item.kind === "user")
            return (
              <div key={item.id} className="msg user">
                <span className="sr-only">{t("chat.you")}</span>
                {item.text}
              </div>
            );
          if (item.kind === "wysp")
            return (
              <div key={item.id} className={`msg wysp ${item.state}`}>
                {item.segment.marker && <span className="marker">{item.segment.marker}</span>}
                {item.segment.text}
              </div>
            );
          if (item.kind === "evidence")
            return (
              <div key={item.id} className={`msg evidence ${item.etype === "declared" ? "declared" : item.ok ? "ok" : "bad"}`}>
                {item.etype === "declared"
                  ? t("chat.evidence.declared")
                  : item.ok
                    ? t("chat.evidence.ok")
                    : t("chat.evidence.bad")}
                : {item.title}
              </div>
            );
          return (
            <div key={item.id} className={`msg note ${item.tone}`}>
              {item.text}
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
          <div className="msg wait">
            <span className="dots" aria-hidden />
            {activity || (status === "thinking" ? t("activity.thinking") : status === "acting" ? t("activity.acting") : "")}
          </div>
        )}
        <div ref={endRef} />
      </div>
      <ExploreCard />
      <ExerciseCard />
      {(busy || hasCancelled) && (
        <div className="quick">
          {busy ? (
            <button className="secondary" onClick={interruptNarration} aria-keyshortcuts="Escape" title={t("chat.stopTitle")}>
              {t("chat.stop")}
            </button>
          ) : (
            <button className="secondary" onClick={() => send({ type: "user.continue" })}>
              {t("chat.continue")}
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
          placeholder={listening ? interim || t("caption.listening") : t("chat.ask")}
          aria-label={t("chat.message")}
          autoComplete="off"
        />
        {voiceSupported && (
          <button
            type="button"
            className={`icon${listening ? " on" : ""}`}
            aria-label={t("chat.holdToTalk")}
            aria-pressed={listening}
            title={t("chat.holdToTalk")}
            onPointerDown={startListening}
            onPointerUp={stopListening}
            onPointerLeave={() => listening && stopListening()}
            onKeyDown={(e) => {
              if ((e.key === " " || e.key === "Enter") && !e.repeat) {
                e.preventDefault();
                startListening();
              }
            }}
            onKeyUp={(e) => {
              if (e.key === " " || e.key === "Enter") {
                e.preventDefault();
                stopListening();
              }
            }}
            onBlur={() => listening && stopListening()}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
              <rect x="5.5" y="1.5" width="5" height="8" rx="2.5" fill="currentColor" />
              <path d="M3 7.5a5 5 0 0 0 10 0M8 12.5v2" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round" />
            </svg>
          </button>
        )}
        <button type="submit" className="icon primary" disabled={!text.trim()} aria-label={t("chat.send")} title={t("chat.send")}>
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
            <path d="M8 13V3M3.5 7.5 8 3l4.5 4.5" stroke="currentColor" strokeWidth="1.8" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </form>
    </section>
  );
}
