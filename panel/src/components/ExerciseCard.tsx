import { useStore } from "../store";

/** The lesson in progress and the exercise Wysp is watching. Buttons only send what the user could type. */
export function ExerciseCard() {
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
  return (
    <section className="lesson" aria-label="Lesson and exercise">
      {lesson && (
        <div className="lesson-head">
          <strong>{lesson.title}</strong>
          <span className="muted">
            Step {lesson.step} of {lesson.total}
          </span>
          <progress max={lesson.total} value={lesson.step} aria-label="Lesson progress" />
        </div>
      )}
      {active && (
        <div className="exercise">
          <p>{ex.prompt}</p>
          <p className="muted small" aria-live="polite">
            Wysp checks it in the application. Attempts {ex.attempts}/{ex.max_attempts} · hints {ex.hints_used}/{ex.hints_total}
          </p>
          <div className="row">
            <button className="ghost" onClick={() => say("Give me a hint.")} disabled={ex.hints_used >= ex.hints_total}>
              Hint
            </button>
            <button className="ghost" onClick={() => say("I think I am done, please check.")}>
              I'm done
            </button>
          </div>
        </div>
      )}
    </section>
  );
}