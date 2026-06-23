# 01 Agent Registry

## Registry Rules

Every Agent must declare before work:

```text
任务 ID�?Agent�?计划修改文件�?预计影响页面�?是否涉及版本号：
是否涉及数据库：
是否涉及生产发布�?```

Only the chief owner can assign a task, approve a write lock, change task status, approve database work, or approve release work.

## Standing Agents

| Agent | Thread ID | Responsibilities | Forbidden | Required deliverable |
| --- | --- | --- | --- | --- |
| Version Management Agent | `019ef55d-e075-7f93-8146-27a1fbab9f3f` | Maintain version ledger, check current and next version, own version owner conflict checks, inspect commit/tag/branch relationship, confirm release version strategy. | No business code edits, no release execution, no branch merge. | `ops-v3/tasks/<TASK_ID>/version-check.md` |
| Triage Agent | `019ef55e-156f-7d03-a0b1-3e8921a3c799` | Classify issue type, priority, task scope, and non-scope. | No code edits, no skipped reproduction or impact assessment. | `ops-v3/tasks/<TASK_ID>/triage.md` |
| Bug Location Agent | `019ef55e-51aa-7593-98cf-79b1faae2df9` | Reproduce and locate frontend/backend/API/database/cache/OSS/deploy/browser/data cause, then recommend minimum fix and next Agent. | No direct fix without chief owner approval, no scope expansion, no unrelated file edits. | `ops-v3/tasks/<TASK_ID>/bug-location.md` |
| Frontend UI Agent | `019ef55e-7cda-7883-89e3-19b801626f2f` | Vue UI, mini program UI, mobile experience, buttons, dialogs, layout, tables, scan/photo entry points. | No backend API edits, no DB edits, no whole-site restyle, no restoration of removed standalone exception/cache pages. | `ops-v3/tasks/<TASK_ID>/frontend-ui-report.md` |
| Backend API Agent | `019ef55e-a110-73d0-8306-178787403372` | FastAPI routes, contracts, permissions, request/response bodies, API tests, compatibility notes. | No DB schema changes, no production config edits, no temporary test API exposed as production capability. | `ops-v3/tasks/<TASK_ID>/backend-api-report.md` |
| Database Engineer Agent | `019ef55e-cee7-78c2-9c63-5bedf8e312e5` | PostgreSQL, Alembic, indexes, constraints, data repair scripts, backup and restore plans. | No Alembic without chief owner and release Agent double confirmation, no direct production cleanup, no data deletion, no assumed production index state. | `ops-v3/db-changes/<TASK_ID>-db-plan.md`; `ops-v3/db-changes/<TASK_ID>-dry-run.md`; `ops-v3/db-changes/<TASK_ID>-apply-report.md` |
| Algorithm Agent | `019ef55e-f431-77e1-ba43-300901aa05fa` | Meter matching, address clustering, KPI weights, efficiency model, anomaly rules, statistics definitions. | No UI edits, no DB schema edits, no unexplained black-box temporary rules. | `ops-v3/tasks/<TASK_ID>/algorithm-report.md` |
| QA Acceptance Agent | `019ef55f-1aa8-7160-b0ee-4f16e9f8b4a6` | Acceptance cases, browser/API/mobile/real phone validation boundaries, completion judgment. | No development fix, no desktop browser proof as real phone camera proof, no API 200 as business completion. | `ops-v3/acceptance/<TASK_ID>-qa-report.md` |
| Release Agent | `019ef55f-452a-7251-ae37-d380a7e3a179` | Release plan, backup, patch sync, restart, health checks, rollback, production verification report. | No backup no release, no dirty commit/tag release, no `.env` overwrite, no `data` overwrite, no uploads overwrite, no Alembic without approval, no full current replacement unless explicitly approved. | `ops-v3/releases/<VERSION>-release-plan.md`; `ops-v3/releases/<VERSION>-release-report.md` |
| Archive Agent | `019ef55f-71e1-7f11-a25f-fe5372b55e82` | Archive task results, update tasks/incidents/releases, ensure conclusions, validation, impact, rollback notes. | No unverified work marked complete, no hidden failures, no deleted incident history. | `ops-v3/tasks/<TASK_ID>/archive.md` |

## Current Write Locks

No active write locks.

## High Conflict Files

- `v2-web/package.json`
- `v2-api/pyproject.toml`
- `v2-api/app/main.py`
- `v2-api/app/services/ops_status.py`
- `v2-api/app/static/vue/**`
- `v2-web/src/views/ProjectBoardView.vue`
- `v2-web/src/views/TaskHallView.vue`
- `v2-web/src/views/ConstructionView.vue`
- `v2-web/src/views/ClaimTasksView.vue`
- `v2-api/app/services/state_repository.py`
- `v2-api/app/services/local_simulation.py`
- `v2-api/app/api/routes/local_test.py`

## Lock Release Rule

A lock is released only when the task is completed, cancelled, rolled back, or explicitly released by the chief owner in this registry.
