import { useStore } from "../store";

/** Asks before Wysp studies the project, then shows how far it is. Nothing is read until the user says yes. */
export function ExploreCard() {
  const e = useStore((s) => s.explore);
  const send = useStore((s) => s.send);
  if (!e || e.phase === "none" || e.phase === "declined") return null;
  const start = () => send({ type: "explore.start" });
  const stop = () => send({ type: "explore.stop" });

  if (e.phase === "offer")
    return (
      <section className="explore" aria-label="Explore this project">
        <strong>Explore this project?</strong>
        <p>
          I can map the code (folders, classes, what depends on what), then read the main files and take notes, so what I tell you comes from
          the code. Nothing is read until you say yes.
        </p>
        <div className="row">
          <button className="primary" onClick={start}>
            Start
          </button>
          <button className="ghost" onClick={stop}>
            Not now
          </button>
        </div>
      </section>
    );

  if (e.phase === "mapping" || e.phase === "studying")
    return (
      <section className="explore" aria-label="Exploring the project" aria-live="polite">
        <strong>{e.phase === "mapping" ? "Mapping the code" : "Reading the main files"}</strong>
        <p className="muted">
          {e.files} files, {e.symbols} symbols mapped
          {e.phase === "studying" ? ` · ${e.read} files read · ${e.briefs} notes` : ""}
        </p>
        <div className="row">
          <button className="ghost" onClick={stop}>
            Stop
          </button>
        </div>
      </section>
    );

  // ready, stopped, failed: one quiet line with the way back in.
  return (
    <section className="explore quiet" aria-label="Project exploration">
      <span className="muted">{e.note || (e.phase === "failed" ? "Exploration failed." : "Project explored.")}</span>
      <button className="ghost" onClick={start}>
        {e.phase === "ready" && e.briefs > 0 ? "Study again" : "Try again"}
      </button>
    </section>
  );
}
