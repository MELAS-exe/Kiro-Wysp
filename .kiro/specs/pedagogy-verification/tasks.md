# Implementation Plan: Pedagogy and Verification

Owners: A = Core & Contract, B = Experience, C = Adapters. Gates: J0 Wed 11 Nov, J1 Thu 19 Nov, J2 Fri 27 Nov, J3 Tue 1 Dec.
Depends on adapter-contract task 3 (predicates) and core-orchestrator tasks 3 and 7.

- [x] 1. Implement profile loading, the profile schema and `wysp validate-profile`
  - Pydantic models for profile, concepts, lessons and exercises; JSON Schema exported to `schemas/profile.schema.json`
  - Loader with line numbers, validator (references, DAG, placeholder positions, translations), CLI command with readable errors and exit status
  - A minimal valid profile for the mock adapter in `contract-tests/wysp_mock/profile/`
  - _Owner: A_ · _Gate: Mon 16 Nov (B writes both profiles from Fri 20 Nov)_
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 1.1 Write property test for profile validation
  - **Property PED-P7: Profile validity**
  - **Validates: Requirement 1.2**

- [x] 2. Implement the verification service and evidence
  - `verification/service.py` (fresh observe, scope hint, predicate evaluation), `Evidence` model, optional `adapter.verify` use, evidence publication to the Panel
  - _Owner: A_ · _Gate: J1_
  - _Requirements: 4.1, 4.2, 4.4_

- [x] 3. Implement the learner model
  - BKT update of design.md with hint weighting, depth hints, persistence with backup on corruption
  - _Owner: A_ · _Gate: J2_
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 6.2_

- [x] 3.1 Write property tests for the learner model
  - **Property PED-P1: Mastery is bounded**
  - **Property PED-P2: Correct verified evidence never lowers mastery**
  - **Property PED-P3: Evidence strength is ordered**
  - **Validates: Requirements 5.1, 5.2**

- [x] 4. Implement the exercise engine
  - Binding resolution, offer and refusal reasons, start-state check, user-origin subscription with debounce, attempts, hints, solution offer after `max_attempts`, declared evidence path
  - _Owner: A_ · _Gate: J2_
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.3_

- [x] 4.1 Write property tests for exercises
  - **Property PED-P4: Wysp actions never count**
  - **Property PED-P5: No stale success**
  - **Property PED-P6: Offers need resolved bindings**
  - **Property PED-P8: Hints in order**
  - **Validates: Requirements 3.1–3.4, 4.3**

- [x] 5. Implement the lesson runner
  - Step state machine (`explain`, `show`, `guide`, `do`, `check`), skip, repeat, stop, `lesson.update` messages, integration with the orchestrator (step goals) and the gate (`do` steps, lesson grants)
  - _Owner: A_ · _Gate: J2_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

- [x] 6. Implement recommendations and adaptation hints
  - Recommender and depth hints exposed to the context builder
  - _Owner: A_ · _Gate: J2_
  - _Requirements: 6.1, 6.2_

- [x] 6.1 Write property test for recommendations
  - **Property PED-P9: Recommendation respects prerequisites**
  - **Validates: Requirement 6.1**

- [x] 7. Write lesson scenario tests with the mock adapter
  - A full lesson (explain, show, guide verified by `simulate_user`, check with one failed attempt then a pass), plus the declared-evidence path
  - _Owner: A_ · _Gate: J2_
  - _Requirements: 2.1–2.5, 3.2–3.6_

- [x] 8. Validate both real profiles in CI
  - CI step running `wysp validate-profile` on `apps/blender-tutor/profile` and `apps/web-tutor/profile`
  - _Owner: A_ · _Gate: J2_
  - _Requirements: 1.3_

- [ ] 9. Checkpoint: pedagogy ready for the demo
  - Ask the user if questions arise
