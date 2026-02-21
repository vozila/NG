# Reference Pack — Playbooks Wizard

**Updated:** 2026-02-21 (America/New_York)

## Scope
Feature module: `features/playbooks.py`  
Feature gate: `VOZ_FEATURE_PLAYBOOKS=1`  
Runtime gate: `VOZ_OWNER_PLAYBOOKS_ENABLED=1`

Schema-validated chat wizard draft persistence.

## Endpoints
- `POST /owner/playbooks/wizard/draft`
- `GET /owner/playbooks/{playbook_id}?tenant_id=<tenant>`

Auth:
- `Authorization: Bearer <VOZ_OWNER_API_KEY>`

## Request contract
- `tenant_id`: required
- `goal_id`: required
- `messages`: list of `{role: user|assistant, text: string}`
- `schedule_hint_minutes`: optional bounded integer

## Persistence event type
- `wizard.playbook_drafted`

## Rollback
- Runtime off: `VOZ_OWNER_PLAYBOOKS_ENABLED=0`
- Feature off: `VOZ_FEATURE_PLAYBOOKS=0`

