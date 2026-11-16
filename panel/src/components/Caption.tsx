import { useStore } from "../store";

/** What Wysp is saying or doing right now: the spoken sentence, the voice input, or its activity. Renders nothing when idle. */
export function LiveCaption() {
  const current = useStore((s) => s.current);
  const status = useStore((s) => s.status);
  const activity = useStore((s) => s.activity);
  const listening = useStore((s) => s.listening);
  const interim = useStore((s) => s.interim);
  if (listening)
    return (
      <div className="caption listening" aria-live="polite">
        {interim || "Listening..."}
      </div>
    );
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
        <span className="dots" aria-hidden />
        {activity || (status === "thinking" ? "Thinking" : status === "acting" ? "Working in the application" : "")}
      </div>
    );
  return null;
}
