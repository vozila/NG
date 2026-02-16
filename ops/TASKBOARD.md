# Vozlia NG — TASKBOARD
**Date:** 2026-02-15 (America/New_York)

## DONE
- [x] Day 0 Milestone: NG skeleton + loader + registry + admin_quality + sample + scripts + gates green
- [x] TASK-0100 — Voice Flow A WS skeleton + waiting-audio hooks (Slice A+B)
- [x] TASK-0101 — Shared line access gate (out-of-band HTTP FSM)
- [x] TASK-0102 — WhatsApp inbound adapter stub

## NOW (Day 2 — after Day 1 merges)
- [ ] Voice Flow A Slice C: outbound audio buffering + pacing + backlog cap (separate ticket)
- [ ] Voice Flow A Slice D: barge-in cancel/clear semantics + aux-lane “thinking audio” (separate ticket)
- [ ] Unified engine router interface (shared across voice/whatsapp/webui)

## Guardrails
- No cross-feature imports.
- Every feature behind `VOZ_FEATURE_<NAME>` default OFF.
- Debug logs only when `VOZLIA_DEBUG=1`.
- Before merge: compileall + ruff + pytest + regression.

TASK-0200: Stabilize quality rails (scripts + admin_quality fix; core fix via CORE-CHANGE PR)

TASK-0201: Implement Flow A OpenAI Realtime bridge (flagged)

TASK-0202: Implement barge-in + pacing/backlog caps + deterministic tests (flagged)
