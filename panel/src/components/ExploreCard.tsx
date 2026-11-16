import { useT } from "../i18n";
import { useStore } from "../store";

/** Asks before Wysp studies the project, then shows how far it is. Nothing is read until the user says yes. */
export function ExploreCard() {
  const t = useT();
  const e = useStore((s) => s.explore);
  const send = useStore((s) => s.send);
  if (!e || e.phase === "none" || e.phase === "declined") return null;
  const start = () => send({ type: "explore.start" });
  const stop = () => send({ type: "explore.stop" });

  if (e.phase === "offer")
    return (
      <section
        className="explore"
        aria-label={t("explore.offerAria")}
      >
        <strong>{t("explore.offerTitle")}</strong>
        <p>{t("explore.offerBody")}</p>
        <div className="row">
          <button className="primary" onClick={start}>
            {t("explore.start")}
          </button>
          <button className="ghost" onClick={stop}>
            {t("explore.notNow")}
          </button>
        </div>
      </section>
    );

  if (e.phase === "mapping" || e.phase === "studying")
    return (
      <section className="explore" aria-label={t("explore.working")}>
        <div role="status">
          <strong>
            {e.phase === "mapping"
              ? t("explore.mapping")
              : t("explore.studying")}
          </strong>
          <p className="muted">
            {e.phase === "studying"
              ? t("explore.countsStudying", {
                  files: e.files,
                  symbols: e.symbols,
                  read: e.read,
                  briefs: e.briefs,
                })
              : t("explore.counts", { files: e.files, symbols: e.symbols })}
          </p>
        </div>
        <div className="row">
          <button className="ghost" onClick={stop}>
            {t("explore.stop")}
          </button>
        </div>
      </section>
    );

  // ready, stopped, failed: one quiet line with the way back in.
  return (
    <section className="explore quiet" aria-label={t("explore.quiet")}>
      <span className="muted">
        {e.note ||
          (e.phase === "failed" ? t("explore.failed") : t("explore.done"))}
      </span>
      <button className="ghost" onClick={start}>
        {e.phase === "ready" && e.briefs > 0
          ? t("explore.studyAgain")
          : t("explore.tryAgain")}
      </button>
    </section>
  );
}
