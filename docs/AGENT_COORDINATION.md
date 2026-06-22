# Agent Coordination

Last updated: 2026-06-22

This file is the shared coordination board for parallel maintenance threads.

## Active Version Claims

| Version | Owner | Scope | Status | Notes |
| --- | --- | --- | --- | --- |
| V2.4.12 | BUG fix thread + project engineer deploy thread | Construction mobile scanner patch | Released | Committed as `5f6d0aa`, tagged `v2.4.12`, deployed by project engineer. Backup: `/opt/module-manager-v2/backups/runtime/20260621_224811_before_v2.4.12`; release: `/opt/module-manager-v2/releases/v2.4.12-20260621_224816`; service active; `/health`, `/login`, `/project-board`, `/construction` OK; `/openapi.json` 404. Real phone scan QA still pending. |
| V2.4.13 | Project engineer thread `019edff4-0c40-7920-8872-3c20eacb4430` | ClaimTasks task-claiming page patch | Folded into V2.4.14 | ClaimTasks fix is included in the V2.4.14 combined patch to avoid deploying a mixed version/build artifact. |
| V2.4.14 | Project engineer thread + BUG fix thread | ClaimTasks cleanup plus construction mobile capture/cache patch | Released | Committed as `d18c516`, tagged `v2.4.14`, deployed by patch sync. Backup: `/opt/module-manager-v2/backups/runtime/20260621_234534_before_v2.4.14_patch`. Production `.env`, `data`, uploads preserved; no Alembic migration. Service active; `/health`, `/login`, `/project-board`, `/claim-tasks`, `/construction`, and `https://www.sgcc.online/login` OK. |
| V2.4.15 | BUG fix thread `019eea7e-146b-71c0-b7d1-85599dd0f97a` | Review exception payload, review thumbnails, installer date KPI hotfixes | Folded into V2.5.0 | User explicitly approved folding the V2.4.15 hotfix into the V2.5.0 feature release instead of publishing it separately. |
| V2.5.0 | Project engineer thread | Combined release: V2.4.15 review/thumbnail/KPI fixes plus unmatched address task cards, project-outside-construction trace/export, meter-replacement matching, exception group task cards, constructor assignment workflow for unmatched/exception tasks | Released | Committed as `eeb0fa9`, tagged `v2.5.0`, deployed by patch sync. Backup: `/opt/module-manager-v2/backups/runtime/20260622_014459_before_v2.5.0_patch`. Production `.env`, `data`, uploads preserved; no Alembic migration. Service active; `/health`, `/login`, `/project-board`, `/task-hall`, `/construction`, `/openapi.json` 404, and `https://www.sgcc.online/login` OK from server. |
| V2.5.1 | Project engineer thread | Review and construction permanent field-task cards plus UI label centering | Released | Committed and tagged as `v2.5.1`, deployed by patch sync. Backup: `/opt/module-manager-v2/backups/runtime/20260622_075536_before_v2.5.1_patch`. Production `.env`, `data`, uploads preserved; no Alembic migration. Service active; `/health`, `/login`, `/project-board`, `/task-hall`, `/construction`, `/claim-tasks`, `/openapi.json` 404, and `https://www.sgcc.online/login` OK. |
| V2.5.2 | BUG fix thread + project engineer deploy thread | Construction mobile permanent task cards click-through hotfix | Released | Code committed as `8ac42ba`, tagged `v2.5.2`, deployed by project engineer patch sync. Backup: `/opt/module-manager-v2/backups/runtime/20260622_085116_before_v2.5.2_patch`. Production `.env`, `data`, uploads preserved; no Alembic migration. Service active; `/health`, `/login`, `/project-board`, `/construction`, `/task-hall`, `/claim-tasks`, `/openapi.json` 404, and `https://www.sgcc.online/login` OK. |
| V2.5.3 | Project engineer thread | Project board installer KPI daily exception drilldown | Released via V2.5.4 | Daily exception counts open abnormal group details for the selected installer/date. Included in the V2.5.4 production patch because V2.5.4 was deployed from HEAD. |
| V2.5.4 | BUG fix thread + project engineer deploy thread | Construction upload installer should use user display name | Released | Code committed as `f532eb1`, tagged `v2.5.4`, deployed by project engineer patch sync. Backup: `/opt/module-manager-v2/backups/runtime/20260622_105337_before_v2.5.4_patch`. Production `.env`, `data`, uploads preserved; no Alembic migration. Service active; `/health`, `/login`, `/project-board`, `/construction`, `/openapi.json` 404, and `https://www.sgcc.online/login` OK. |
| V2.5.5 | BUG fix thread + project engineer deploy thread | Backfill historical construction-upload installer names | Released | Code committed as `f0b0edb`, tagged `v2.5.5`, deployed by project engineer patch sync. Backup: `/opt/module-manager-v2/backups/runtime/20260622_114149_before_v2.5.5_patch`. Production `.env`, `data`, uploads preserved; no Alembic migration. Dry-run matched only constructor `xa` -> `樊哲浩`; apply updated PostgreSQL `211` rows and JSON compatibility state `54` rows. Service active; `/health`, `/login`, `/project-board`, `/construction`, and `https://www.sgcc.online/login` OK. |

## Rules

1. Before editing files, every agent must read:
   - `PROJECT_KNOWLEDGE.md`
   - `BUG_HISTORY.md`
   - `FIX_NOTES.md`
   - `docs/AGENT_COORDINATION.md`
2. Before editing files, every agent must run `git status --short` and inspect active dirty files.
3. If another agent has changed a file, do not edit that file unless the user explicitly reassigns ownership.
4. Version numbers are exclusive locks.
   - One active version can have only one owner.
   - A second agent must reserve the next version instead of reusing the same one.
5. Small fixes increment `+0.0.1`; large workflow or UI changes increment `+0.1.0`.
6. A claim must include:
   - version
   - owner/thread role
   - files or page scope
   - status: `Active`, `Paused`, `Ready for review`, `Released`, or `Abandoned`
7. The owner must update `FIX_NOTES.md`, `BUG_HISTORY.md`, and `docs/V2_CHANGE_WORKLOG.md` before commit.
8. The owner must run the relevant gates before commit:
   - frontend typecheck/build for Vue changes
   - backend tests for API/service changes
   - browser QA for rendered page changes
9. The owner who commits a version also tags it.
10. Deployment must only happen from a clean committed version and must keep the production backup/release process.
10a. Small frontend/backend patches should be deployed as patch syncs by default: backup first, then copy only changed source/build files to production. Do not create a full replacement release unless the user explicitly requests a full release or the change is architectural.
11. If an agent needs coordination with another active thread, the agent must proactively send a message to that thread when its thread ID is available.
12. If the other thread ID is not available, the agent must record the coordination request in this file and pause instead of taking over the version or files.

## Conflict Handling

- If two agents need the same files, the first active version claim keeps ownership.
- The second agent pauses and records the requested follow-up under the next version.
- If urgent production work must interrupt an active claim, the user must explicitly reassign ownership.
- Direct thread messaging is preferred over implicit assumptions. The coordination file is the fallback channel when direct messaging is not possible.
