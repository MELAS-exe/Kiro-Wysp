import { useT } from "../i18n";
import { useStore } from "../store";

/** What Wysp is saying or doing right now: the spoken sentence, the voice input, or its activity. Renders nothing when idle. */
export function LiveCaption() {
  return (
    <div role="status" aria-atomic="true" className="caption-region">
      <CaptionBody />
    </div>
  );
}

function CaptionBody() {
  const current = useStore((s) => s.current);
  const status = useStore((s) => s.status);
  const activity = useStore((s) => s.activity);
  const listening = useStore((s) => s.listening);
  const interim = useStore((s) => s.interim);
  const t = useT();
  if (listening)
    return (
      <div className="caption listening">
        {interim || t("caption.listening")}
      </div>
    );
  if (current)
    return (
      <div className="caption">
        {current.marker && <span className="marker">{current.marker}</span>}
        {current.text}
      </div>
    );
  if (status !== "idle")
    return (
      <div className="caption dim">
        <span className="dots" aria-hidden />
        {activity || (status === "thinking" ? t("activity.thinking") : status === "acting" ? t("activity.acting") : "")}
      </div>
    );
  return <div className="caption" />;
}
