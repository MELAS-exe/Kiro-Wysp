---
inclusion: fileMatch
fileMatchPattern: ["apps/*/profile/**", "core/src/wysp_core/pedagogy/**", "core/src/wysp_core/verification/**", "core/src/wysp_core/orchestrator/**"]
---

# Pedagogy and Profiles

## Tutoring strategy (applies to prompts and lesson design)
1. Start from the user's real context (the observation), not from a generic lesson.
2. Explain in short segments of one or two sentences, each tied to something visible on the board or in the application.
3. Prefer **guide** (the user acts, Wysp watches and verifies) over **do** (Wysp acts after permission). Use **do** when the user asks for it, or when the action is a means rather than the learning goal.
4. After an explanation, offer a small contextual exercise and verify it in the application.
5. Adapt depth to mastery: below 0.4, explain basics and vocabulary; from 0.4 to 0.85, guided practice; above 0.85, a challenge or skip.
6. Ask a clarification question when the request is ambiguous rather than guessing.

## Profile files (`apps/<tutor>/profile/`)
- `profile.yaml`: `id`, `app`, `languages`, `primer` (short app description for the LLM), `skills` (id, title, prerequisites, optional BKT parameters).
- `concepts.yaml`: glossary entries with `id`, `term`, `short`, `detail`, `level`, `links` (official documentation), `related`.
- `lessons/L<NN>_<slug>.yaml`: `id`, `title`, `skills`, `prerequisites`, `board` (layout, focus), `steps` (`explain`, `show`, `guide`, `do`, `check`), `exercises`.
- Titles and prompts are localized maps: `{en: ..., fr: ...}`.

## Exercises
- An exercise has a `prompt`, `skills`, `bindings` (variables resolved from the context, for example `target: $focus.object`), `success` (predicates), ordered `hints` and `max_attempts`.
- Success criteria are **authored predicates** (JMESPath on the observation, combined with `all`, `any`, `not`). The LLM may phrase the prompt but never invents success criteria.
- An exercise is offered only if all its bindings resolve.

## Evidence and mastery
- Evidence types: `verified` (predicate true on a fresh observation after a user action), `answered` (quiz answer in the Panel), `declared` (the user says it is done but the application cannot verify it). Weights: 1.0, 0.6 and 0.3.
- Mastery uses a simplified Bayesian Knowledge Tracing per skill, bounded in [0, 1]. A skill is acquired at 0.85 or more.
- Actions performed by Wysp (`origin: wysp`) never produce evidence.
- The UI always says whether a success was verified in the application or only declared.
