# Design Document: Pedagogy and Verification

## Overview

`core/src/wysp_core/pedagogy/` loads profiles, runs lessons and exercises, and keeps the learner model. `core/src/wysp_core/verification/` evaluates predicates (the contract's predicate language) on fresh observations and produces evidence. Both modules are application-agnostic and are driven by profile data, the event bus and the orchestrator.

## Architecture

```
profile YAML ──▶ ProfileLoader ──▶ Profile (skills DAG, concepts, lessons)
                                        │
EventBus (user-origin changes) ──▶ LessonRunner ──▶ ExerciseEngine ──▶ VerificationService ──▶ Evidence
                                        │                  ▲                     │
Orchestrator ◀── step goals, depth ─────┘                  └── fresh observe ────┘
                                                                                 ▼
                                                                  LearnerModel (BKT) ──▶ ~/.wysp/learners/
```

## Profile format

```yaml
# apps/blender-tutor/profile/profile.yaml
id: blender-tutor
app: Blender
languages: [en, fr]
primer: >
  Blender is a 3D creation suite. Objects live in a scene; a mesh object can have a stack of
  modifiers evaluated from top to bottom; materials define surface appearance.
board:
  props: {object: [type, modifiers_count, material], modifier: [type, show_viewport, levels, width, segments]}
skills:
  - {id: scene_navigation, title: {en: "Read the scene", fr: "Lire la scène"}, prior: 0.3}
  - {id: modifier_stack, title: {en: "Understand the modifier stack"}, prerequisites: [scene_navigation]}
  - {id: bevel_modifier, title: {en: "Use a Bevel modifier"}, prerequisites: [modifier_stack]}
```

```yaml
# apps/blender-tutor/profile/lessons/L02_bevel.yaml
id: blender.modifiers.bevel
title: {en: "Soften edges with a Bevel", fr: "Adoucir les arêtes avec un Biseau"}
skills: [bevel_modifier]
prerequisites: [modifier_stack]
bindings: {target: "$focus.object"}
board: {layout: stack, focus: "${bindings.target}"}
steps:
  - {type: explain, goal: "Why hard edges look fake and what a bevel does", concepts: [bevel, edge]}
  - {type: show, goal: "Show the modifier stack of the target", refs: ["${bindings.target}"], include_children: true}
  - {type: guide, action: add_modifier, params: {target: "${bindings.target}", type: BEVEL}}
  - {type: check, exercise: bevel_segments}
exercises:
  - id: bevel_segments
    prompt: {en: "Give the bevel 3 segments so the edge looks round."}
    skills: [bevel_modifier]
    bindings: {target: "$focus.object"}
    success:
      all:
        - {path: "entities[?kind=='modifier' && parent=='${bindings.target}' && props.type=='BEVEL'] | length(@)", op: gte, value: 1}
        - {path: "entities[?kind=='modifier' && parent=='${bindings.target}' && props.type=='BEVEL'].props.segments | [0]", op: eq, value: 3}
    hints:
      - {en: "Look at the Modifier Properties tab (the blue wrench)."}
      - {en: "Find the Segments field in the Bevel panel."}
    max_attempts: 3
```

Bindings: `$focus.<kind>` (first focused entity of that kind, else its nearest ancestor of that kind), `$ref:<ref>` (literal ref), `$context.<fact>`. Resolution happens on the latest observation.

## Components and Interfaces

- `ProfileLoader.load(path) -> Profile` and `validate(profile, fixture) -> list[ProfileError(file, line, message, hint)]` (line numbers kept with a ruamel/PyYAML mark map). Checks: schema, unknown skills, concepts and actions (from `contract.fixture.yaml` `expect.actions`), DAG cycles, placeholder positions, duplicate ids, missing translations for declared languages (warning).
- `LessonRunner`: state machine `idle → running(step i) → waiting_user | waiting_gate | waiting_exercise → done | stopped`. Controls: `start(lesson_id)`, `skip()`, `repeat()`, `stop()`. Publishes `lesson.update` through the UI protocol.
- `ExerciseEngine`: `offer(exercise_id) -> Offer | Refusal(reason)`; on start, records `start_state_version` and evaluates success once (must be false). Subscribes to user-origin `event.state_changed`; on each event (debounced 300 ms) runs verification. Tracks attempts (a failed check after a user change counts as an attempt only if a predicate that was true becomes false or the learner says "done"), hints used, outcome.
- `VerificationService.verify(predicates, scope_hint) -> VerificationResult(ok, outcomes[], observation_id, state_version)`: always calls `adapter.observe` (never uses a cached observation), at `full` level with `root` set to the common ancestor of predicate refs when possible.
- `LearnerModel`: `mastery(skill)`, `update(skills, evidence)`, `depth_hint(skill)`, persisted JSON with history (last 50 evidence ids per skill).
- `Recommender.next(profile, learner) -> lesson_id | None`.

## Data Models

```python
class Evidence(BaseModel):
    id: str
    type: Literal["verified", "answered", "declared"]
    source: Literal["core", "adapter", "learner"]
    exercise_id: str | None
    skills: list[str]
    outcomes: list[PredicateOutcome]
    observation_id: str | None
    state_version: int | None
    created_at: datetime
    hints_used: int = 0
```

### Mastery update (simplified BKT)

With slip `s = 0.1`, guess `g = 0.2`, transit `t = 0.15` (overridable per skill), prior mastery `p`, outcome `correct` and weight `w` (verified 1.0, answered 0.6, declared 0.3):

```
posterior = p(1-s) / (p(1-s) + (1-p)g)           if correct
          = p s / (p s + (1-p)(1-g))              otherwise
bkt       = posterior + (1 - posterior) t
p_new     = clamp(p + w (bkt - p), 0, 1)
```

Hints reduce the effective weight: `w × (1 − 0.15 × hints_used)`, minimum 0.4 × w.

## Correctness Properties

**PED-P1: Mastery is bounded.** *For any* sequence of evidence, every mastery value stays in [0, 1]. **Validates: Requirement 5.1**

**PED-P2: Correct verified evidence never lowers mastery.** *For any* prior and hint count, a correct `verified` update gives `p_new ≥ p`. **Validates: Requirement 5.2**

**PED-P3: Evidence strength is ordered.** *For any* prior, a correct update with `verified` evidence gives at least the mastery obtained with `answered`, which gives at least the mastery obtained with `declared`. **Validates: Requirement 5.2**

**PED-P4: Wysp actions never count.** *For any* event sequence, events with `origin: wysp` never produce evidence and never change mastery. **Validates: Requirement 4.3**

**PED-P5: No stale success.** *For any* exercise, a pass is recorded only after a user-origin state change that happened after the exercise started, and exercises already satisfied at start are refused. **Validates: Requirements 3.1, 3.2, 3.3**

**PED-P6: Offers need resolved bindings.** *For any* observation, an exercise is offered only if every binding resolves to an entity of that observation. **Validates: Requirement 3.1**

**PED-P7: Profile validity.** *For any* generated profile with unknown references or prerequisite cycles, validation reports at least one error; valid generated profiles report none. **Validates: Requirement 1.2**

**PED-P8: Hints in order.** *For any* sequence of hint requests, the revealed hints are a prefix of the exercise's hint list. **Validates: Requirement 3.4**

**PED-P9: Recommendation respects prerequisites.** *For any* profile and learner state, a recommended lesson never has a non-acquired prerequisite. **Validates: Requirement 6.1**

## Error Handling

- Unresolvable bindings: the engine refuses the offer with a reason the orchestrator can explain ("select an object first").
- Verification observation fails (timeout): the attempt is not counted, and the learner is told the check could not run.
- Corrupted learner file: back it up as `.bak`, start from priors, warn once.

## Testing Strategy

- Hypothesis for PED-P1 to P3, P7 to P9 (pure functions and generated profiles).
- Scenario tests with the mock adapter (`simulate_user`) for PED-P4 to P6 and the lesson runner.
- Both real profiles are validated in CI with `wysp validate-profile`.
