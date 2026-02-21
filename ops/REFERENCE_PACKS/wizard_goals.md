# Reference Pack — Wizard Goals

**Updated:** 2026-02-21 (America/New_York)

## Scope
Feature module: `features/wizard_goals.py`  
Feature gate: `VOZ_FEATURE_WIZARD_GOALS=1`  
Runtime gate: `VOZ_OWNER_GOALS_ENABLED=1`

Owner goal persistence + lifecycle APIs.

## Endpoints
- `POST /owner/goals`
- `GET /owner/goals?tenant_id=<tenant>`
- `POST /owner/goals/{goal_id}/approve`
- `POST /owner/goals/{goal_id}/pause`
- `POST /owner/goals/{goal_id}/resume`
- `PATCH /owner/goals/{goal_id}`

Auth:
- `Authorization: Bearer <VOZ_OWNER_API_KEY>`

## Lifecycle event types
- `wizard.goal_created`
- `wizard.goal_updated`
- `wizard.goal_approved`
- `wizard.goal_paused`
- `wizard.goal_resumed`
- scheduler enriches state via `scheduler.goal_executed`

## Rollback
- Runtime off: `VOZ_OWNER_GOALS_ENABLED=0`
- Feature off: `VOZ_FEATURE_WIZARD_GOALS=0`

