# Vozlia NG — CHATLOG (append-only, summarized)

Purpose:
- Capture *nuanced* decisions and lessons learned from engineering chats that are easy to lose
  between sessions.
- This is intentionally higher-signal than raw checkpoints: include the “why”, the tradeoffs,
  and the anti-regression rules.

How to use:
- Append a short entry after any meaningful design decision, bug fix, or reliability lesson.
- Prefer bullets. Keep each entry 10–30 lines.
- If an entry affects code, also update:
  - `ops/DECISIONS.md` (for stable invariants)
  - `ops/JOURNAL.md` (for merge-quality evidence and what changed)

---

## 2026-02-15 — NG rebuild direction locked
- Rebuild as a monorepo NG (modular monolith) with one-file feature modules in `features/`.
- Core stays stable; features self-register via `core/feature_loader.py`.
- Quality rails: regression/security/capacity “agents” as runnable modules + CI.
- Flow A hot path discipline is non-negotiable (no heavy planning inside streaming loop).
- Feature flags required for every new execution path; default OFF.

## 2026-02-17 — Thinking chime: separate aux audio lane (first-class state)
Problem:
- Prior attempts to “inject” a thinking chime into the same outbound buffer as assistant speech
  caused regressions due to cancel/clear semantics, barge-in timing, and shared buffering.

Core fix:
- Treat “thinking audio” as a first-class state and play it from an independent aux lane.
- Maintain 2 outbound buffers:
  - main = assistant speech audio
  - aux  = thinking/comfort tone audio
- Sender loop rule:
  1) Always prefer main if it has frames
  2) If main is empty and THINKING is active, send aux frames
  3) If user speech starts while THINKING, stop thinking audio immediately and clear only aux

Determinism:
- Start THINKING only after a trigger threshold (default 800ms).
- Stop immediately when the waiting operation ends.
- Unit-test the state machine without Twilio/OpenAI by validating:
  - threshold behavior
  - aux clearing on speech_started
  - main-lane priority

Operational note:
- Default `VOICE_WAIT_CHIME_ENABLED=0` until parity tests prove it doesn’t destabilize barge-in.

