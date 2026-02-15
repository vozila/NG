# Vozlia NG — TASKBOARD
**Date:** 2026-02-15 (America/New_York)

## DONE
- [x] Day 0 Milestone: NG skeleton + loader + registry + admin_quality + sample + scripts + gates green

## NOW (Day 1 — start after Day 0 green)
- [ ] TASK-0100 — Voice Flow A WS skeleton + waiting-audio hooks (Slice A+B)
  - Spec: `.agents/tasks/TASK-0100.md`
  - Owner: Codex Agent (Voice)
- [ ] TASK-0101 — Shared line access gate (state machine, out-of-band HTTP)
  - Spec: `.agents/tasks/TASK-0101.md`
  - Owner: Codex Agent (Access)
- [ ] TASK-0102 — WhatsApp inbound adapter (minimal) -> unified engine stub
  - Spec: `.agents/tasks/TASK-0102.md`
  - Owner: Codex Agent (WhatsApp)

## Guardrails
- No cross-feature imports.
- Every feature behind `VOZ_FEATURE_<NAME>` default OFF.
- Debug logs only when `VOZLIA_DEBUG=1`.
- Before merge: compileall + ruff + pytest + regression.
