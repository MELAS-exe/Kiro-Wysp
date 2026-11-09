# Requirements Document: Pedagogy and Verification

Lead: Person A. Profile authors: Person B (content of both profiles), with technical review by Person C.

## Introduction

The pedagogy engine makes Wysp a tutor rather than an assistant: it reads a profile (skills, concepts, lessons, exercises), tracks what the learner masters, chooses the next step, offers contextual exercises and verifies them in the real application. Verification distinguishes a success observed in the application from a simple statement by the user. The engine is generic: all application knowledge comes from the profile files and the adapter.

## Glossary

- **Profile**: YAML files under `apps/<tutor>/profile/` (profile, concepts, lessons).
- **Skill**: a unit of competence with prerequisites, tracked by the learner model.
- **Lesson**: an ordered list of steps (`explain`, `show`, `guide`, `do`, `check`) for some skills.
- **Exercise**: a task with bindings, success predicates, hints and an attempt limit.
- **Binding**: a variable resolved from the current context (for example `$focus.object`).
- **Evidence**: a record of a verification: type (`verified`, `answered`, `declared`), predicate outcomes, observation id, time.
- **Mastery**: probability in [0, 1] that the learner masters a skill.

## Requirements

### Requirement 1: Profile loading and validation

**User Story:** As a tutor author, I want my profile checked when I save it, so that broken lessons never reach a learner.

#### Acceptance Criteria

1. THE Core SHALL load a profile from `profile.yaml`, `concepts.yaml` and `lessons/*.yaml` and validate it against the profile JSON Schema.
2. THE validator SHALL reject a profile whose lessons or exercises reference unknown skills, concepts or action ids declared in the tutor's contract fixture, or whose skill prerequisites contain a cycle.
3. WHEN the user runs `wysp validate-profile <path>`, THE CLI SHALL print each error with file, line and a fix suggestion, and exit with a non-zero status if there is any error.
4. THE validator SHALL reject success predicates that use placeholders outside the allowed positions of the predicate language.

### Requirement 2: Lessons

**User Story:** As a learner, I want short lessons that start from my own work, so that I learn on my real project.

#### Acceptance Criteria

1. WHEN a lesson starts, THE engine SHALL check its prerequisites and bindings, then run its steps in order.
2. WHEN a step is `explain` or `show`, THE engine SHALL give the orchestrator the step goal, the related concepts and the board instructions, and the orchestrator SHALL phrase the narration.
3. WHEN a step is `guide`, THE engine SHALL publish the UI path steps and wait for a verified user change before moving on.
4. WHEN a step is `do`, THE engine SHALL create a proposal through the permission gate and continue only after the action is verified.
5. WHEN a step is `check`, THE engine SHALL start the step's exercise.
6. THE learner SHALL be able to skip a step, repeat a step or stop the lesson at any time.

### Requirement 3: Exercises

**User Story:** As a learner, I want small exercises on my own scene or page, with hints, so that I practise right away.

#### Acceptance Criteria

1. THE engine SHALL offer an exercise only if all its bindings resolve on the current observation and its success predicates are not already true.
2. WHEN an exercise is active and the adapter reports a user-origin state change, THE engine SHALL evaluate the success predicates on a fresh observation.
3. WHEN all success predicates are true after a user-origin change, THE engine SHALL record `verified` evidence and mark the exercise as passed.
4. WHEN the learner asks for a hint, THE engine SHALL reveal the next hint in order, and SHALL record the number of hints used.
5. IF the learner reaches `max_attempts` failed checks, THEN THE engine SHALL offer the solution as a guided or `do` action.
6. WHERE the application cannot verify an exercise, THE engine SHALL accept the learner's statement as `declared` evidence and SHALL label it as not verified.

### Requirement 4: Verification and evidence

**User Story:** As a learner, I want to know whether my success was really checked in the application.

#### Acceptance Criteria

1. THE verification service SHALL evaluate predicates on an observation captured after the triggering change, and record evidence with predicate, actual value, expected value, observation id, state version and timestamp.
2. WHERE the adapter declares `verify.native`, THE service MAY call `adapter.verify` and SHALL record the adapter's evidence with its source.
3. THE engine SHALL never record evidence for a change whose origin is `wysp`.
4. THE Panel messages for evidence SHALL include the evidence type so that the UI can show "verified in the application" or "declared".

### Requirement 5: Learner model

**User Story:** As a learner, I want the tutor to adapt to what I already know.

#### Acceptance Criteria

1. THE learner model SHALL keep a mastery value in [0, 1] for each skill of the profile, initialised from the profile's prior (default 0.2) or from a short self-assessment.
2. WHEN evidence is recorded, THE learner model SHALL update the mastery of the exercise's skills with a simplified Bayesian Knowledge Tracing update weighted by evidence type (verified 1.0, answered 0.6, declared 0.3).
3. THE engine SHALL treat a skill as acquired when its mastery is at least 0.85.
4. THE learner model SHALL be persisted per profile in `~/.wysp/learners/<profile_id>.json`.

### Requirement 6: Recommendation and adaptation

**User Story:** As a learner, I want the tutor to suggest what to learn next.

#### Acceptance Criteria

1. WHEN the learner asks what to do next or finishes a lesson, THE engine SHALL recommend the lesson whose prerequisites are acquired and whose skills have the lowest mastery.
2. THE engine SHALL give the orchestrator a depth hint per skill: `basics` below 0.4, `practice` from 0.4 to 0.85, `challenge` above 0.85.
