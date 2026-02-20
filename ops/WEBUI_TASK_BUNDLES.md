# WebUI Task Bundles (Separate Repo Flow)

**Date:** 2026-02-20  
**Applies to:** `vozlia-portal-ui` repo (not NG backend repo)

## Bundle W1 — Access + owner baseline

### Agent UI-A
- Owner login/session shell.
- API proxy base + auth header injection.
- Health/status panel.

### Agent UI-B
- Access code page (owner/customer code display + copy UX).
- `/owner/events` basic timeline view.

### Agent UI-C
- Build shared UI primitives (panel, table, empty/loading/error states).
- Add test harness + smoke checklist page.

Proof gate:
- `npm run lint`
- `npm run build`
- login + access-codes + events smoke walkthrough

## Bundle W2 — Business knowledge management

### Agent UI-A
- Business profile editor UI.

### Agent UI-B
- Template selection + preview UI.

### Agent UI-C
- OCR upload + review/approve UI.

Proof gate:
- profile/template/ocr flows complete end-to-end with backend responses captured
- screenshot evidence + request/response samples

## Bundle W3 — Inbox + notifications ops

### Agent UI-A
- Leads/appt request inbox pages.

### Agent UI-B
- Inbox action controls (qualified/unqualified/handled).

### Agent UI-C
- Notification settings page (channels/quiet hours if supported).

Proof gate:
- action changes reflected in summary/insights
- idempotent behavior confirmed with repeated actions

## Bundle W4 — Goals wizard + goals ops

### Agent UI-A
- Goal wizard chat UI.

### Agent UI-B
- Goals list/status page.

### Agent UI-C
- Playbook detail read-only + execution history view.

Proof gate:
- create goal, approve, run scheduler tick, confirm outcome view updates

## Cross-repo integration checklist (every UI bundle)
1. Verify backend endpoints exist and match schema.
2. Run operator curls for touched endpoints (from `ops/BUNDLE_PROOF_GATES.md`).
3. Confirm backend logs/events for touched flows when relevant.
4. If UI agent cannot verify runtime behavior directly, provide exact operator commands and expected outputs.

