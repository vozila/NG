# Vozlia NG — Agent Roster

**Rule:** One task/branch per agent. Agents read specs from `.agents/tasks/`.

## Active assignments
- Agent A: TASK-0401 (`features/voice_flow_a.py`, `tests/test_voice_flow_a.py`)
- Agent B: TASK-0402 (`scripts/capture_render_logs.sh`, `scripts/analyze_bargein_latency.py`, `scripts/extract_call_window.py`, `ops/REFERENCE_PACKS/voice_flow_a.md`)
- Agent C: TASK-0403 (`AGENTS.md`, `ops/*` memory spine docs, `.agents/tasks/*` status sync)

## Bundle command
- To launch a full 3-agent bundle with canonical instruction files:
  - `bash scripts/agent_bundle_workflow.sh execute B001`
- Available bundles: `B001`, `B002`, `B003`, `B004`
- Agent instruction files:
  - `.agents/tasks/BUNDLE-B00X-AGENT-A.md`
  - `.agents/tasks/BUNDLE-B00X-AGENT-B.md`
  - `.agents/tasks/BUNDLE-B00X-AGENT-C.md`

## Roles
- Core Maintainer: core/* and feature loader changes
- Feature Agents: features/* only (one-file rule)
