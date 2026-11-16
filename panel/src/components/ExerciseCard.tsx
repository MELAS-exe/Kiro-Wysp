import { useT } from "../i18n";
import { useStore } from "../store";

const RESULT: Record<string, { key: string; cls: string } | undefined> = {
  passed: { key: "exercise.passed", cls: "ok" },
  declared: { key: "exercise.declared", cls: "declared" },
  failed: { key: "exercise.failed", cls: "bad" },
};

/** The lesson in progress and the exercise Wysp is watching. Buttons only send what the user could type. */
export function ExerciseCard() {
  const t = useT();
  const lesson = useStore((s) => s.lesson);
  const ex = useStore((s) => s.exercise);
  const send = useStore((s) => s.send);
  const addUser = useStore((s) => s.addUser);
  if (!lesson && !(ex && ex.status === "active")) return null;
  const say = (text: string) => {
    addUser(text, "typed");
    send({ type: "user.message", text, source: "typed" });
  };
  const active = ex && ex.status === "active";
  const result = ex ? RESULT[ex.status] : undefined;
  return (
    <section className="lesson" aria-label={t("exercise.aria")}>
      {lesson && (
        <div className="lesson-head">
          <strong>{lesson.title}</strong>
          <span className="muted">
            {t("exercise.step", { step: lesson.step, total: lesson.total })}
          </span>
          <progress
            max={lesson.total}
            value={lesson.step}
            aria-label={t("exercise.progress")}
            aria-valuetext={t("exercise.step", {
              step: lesson.step,
              total: lesson.total,
            })}
          />
        </div>
      )}
      {!active && lesson && result && (
        <p className={`exercise-result ${result.cls}`} role="status">
          {t(result.key)}
        </p>
      )}
      {active && (
        <div className="exercise">
          <p>{ex.prompt}</p>
          <p className="muted small" role="status" aria-live="polite">
            {t("exercise.checks", {
              attempts: ex.attempts,
              max: ex.max_attempts,
              hints: ex.hints_used,
              hintsTotal: ex.hints_total,
            })}
          </p>
          <div className="row">
            <button
              className="ghost"
              onClick={() => say(t("exercise.hintSays"))}
              disabled={ex.hints_used >= ex.hints_total}
            >
              {t("exercise.hint")}
            </button>
            <button
              className="ghost"
              onClick={() => say(t("exercise.doneSays"))}
            >
              {t("exercise.done")}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
