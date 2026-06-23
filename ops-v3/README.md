# V3 Production Ops System

This directory is the current source of truth for Module Manager V3 production operations.

## Baseline

- Repository: https://github.com/yuechen202099-hub/module-manager-v3
- Legacy source repository: https://github.com/yuechen202099-hub/module-manager-v2
- Baseline product version: V3.0.2
- Baseline branch: main
- Baseline source branch: feature/v3.0.0-apple-ui-lab
- First ops task: OPS-INIT-001

## Authority

Rules in `ops-v3/` supersede old development-stage coordination notes. The old files below are historical references only:

- `docs/V2_CHANGE_WORKLOG.md`
- `BUG_HISTORY.md`
- `FIX_NOTES.md`
- `docs/AGENT_COORDINATION.md`

Business facts and production safety rules remain active:

- Do not overwrite production `.env`.
- Do not overwrite production `data`.
- Do not overwrite uploads.
- Do not change OSS production data without an approved task.
- Do not execute Alembic without database and release double confirmation.
- Do not publish without backup.
- Do not mark work complete without validation.

## Required Flow

All work follows this path:

User issue -> chief owner registers TASK_ID -> triage agent -> chief owner decides type, priority, and version strategy -> assigned agent -> QA acceptance -> version check -> release handoff or release -> archive -> user report.

## Current Directories

- `agent-prompts/`: startup prompts for each standing Agent thread.
- `tasks/`: task records and handoffs.
- `incidents/`: production incident records.
- `releases/`: release plans and reports.
- `db-changes/`: database risk, dry-run, apply, and rollback records.
- `acceptance/`: QA acceptance reports.
