# WebUI MVP Spec (Based on Existing `vozlia-admin`)

**Date:** 2026-02-20  
**Source reviewed:** `apps/vozlia-admin` (Next.js 14 + panelized admin UI + API proxy routes)

## 1) Product target
Build a companion owner portal that is operationally safe and aligned with NG backend:
- owner auth and tenant-scoped views
- events/inbox/insights surfaces
- access-code operations
- business profile/templates and OCR review
- goal wizard + goals status + execution visibility

## 2) Proven patterns to reuse from existing portal
From `apps/vozlia-admin`:
- Next.js app shell with panelized components (`components/*`).
- Server-side API proxy routes (`pages/api/*`) that call control/backend services.
- Environment-driven backend routing:
  - `VOZLIA_CONTROL_BASE_URL`
  - `VOZLIA_ADMIN_KEY`
- Operational widgets already present (logs/status/debug panels).

Adopt these patterns for NG portal:
- Keep browser code thin; backend access via server proxy routes.
- Keep admin keys server-side only; do not expose raw backend keys in browser calls.
- Keep each UI section modular (panel/component isolation).

## 3) Architecture
- Repo: separate front-end repo (`vozlia-portal-ui` recommended).
- Framework: Next.js (App Router or Pages Router acceptable; prefer consistency with existing portal patterns).
- API integration model:
  - Browser -> Next API route -> NG backend endpoint.
  - API routes attach auth headers from server env.
- Tenant model:
  - all reads/writes must include tenant context and enforce tenant isolation in backend.

## 4) MVP pages
1. Owner Login
- MVP: owner key/session entry and persistence.
- Post-login health check call.

2. Dashboard
- high-level status tiles (events volume, leads, appt requests, notification state).

3. Access Codes
- show customer vs owner codes.
- copy/share UX.

4. Inbox
- leads + appointment requests tabs.
- actions: qualified/unqualified, handled.

5. Business Knowledge
- profile editor (hours/services/pricing/policies).
- template selector + preview.
- OCR upload/review/approve flow.

6. Goals
- wizard chat entry (goal -> questions -> approval).
- goals table (status, next run, last outcome).
- playbook detail read-only.

## 5) Backend contract expectations
Use backend routes defined in bundle plan. Validate each with:
- success response shape
- auth failure shape
- tenant isolation behavior
- idempotency where applicable

## 6) Non-negotiable safety constraints
- No heavy logic in voice/audio hot path.
- UI must not directly connect to backend DB.
- All sensitive keys stay server-side.
- New UI routes/panels behind feature toggles if backend endpoint not fully ready.

## 7) Testing contract (UI repo)
Required per bundle:
- `npm run lint`
- `npm run build`
- targeted component/page tests (if present)
- smoke checklist with screenshots/log snippets
- operator curl checks for backend-facing flows

## 8) Evidence contract
Each bundle completion must include:
- commands run
- pass/fail
- screenshots or short UI recordings for key flows
- matching backend evidence from `ops/logs/*` when feature touches voice/events

