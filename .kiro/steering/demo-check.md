---
inclusion: manual
---

# Demo check (run with `/demo-check` or `#demo-check`)

Use this checklist before recording the video or after a risky merge. Run what exists and report what is missing. Kiro IDE 1.x has no manual hooks, so this steering file plays that role.

1. `uv run pytest` and `npm test --workspaces --if-present` pass.
2. `uv run --no-project python scripts/kiro/hook.py boundaries` reports no violation.
3. The contract kit passes for `mock`, `blender-tutor` and `web-tutor`.
4. `uv run wysp serve` starts. The Panel opens at http://127.0.0.1:8765 and lists both adapters when they are connected.
5. Blender scenario: explain the pumpkin's modifier stack, interrupt, resume, add a Bevel to the candle with permission, see it verified, then complete the exercise "segments = 3" and see it verified.
6. Web scenario: explain the region filter, follow the guided report creation, see the report verified in the saved list.
7. Voice: push-to-talk and barge-in work, and captions match the speech.
8. Report the result as a table: step, status, notes.
