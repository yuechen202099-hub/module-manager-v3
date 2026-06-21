# Agent Coordination

Last updated: 2026-06-21

This file is the shared coordination board for parallel maintenance threads.

## Active Version Claims

| Version | Owner | Scope | Status | Notes |
| --- | --- | --- | --- | --- |
| V2.4.12 | BUG fix thread + project engineer deploy thread | Construction mobile scanner patch | Released | Committed as `5f6d0aa`, tagged `v2.4.12`, deployed by project engineer. Backup: `/opt/module-manager-v2/backups/runtime/20260621_224811_before_v2.4.12`; release: `/opt/module-manager-v2/releases/v2.4.12-20260621_224816`; service active; `/health`, `/login`, `/project-board`, `/construction` OK; `/openapi.json` 404. Real phone scan QA still pending. |
| V2.4.13 | Project engineer thread `019edff4-0c40-7920-8872-3c20eacb4430` | ClaimTasks task-claiming page patch | Active | Scope: remove open/close construction buttons, reviewer only sees task cards with unreviewed work, admin sees all task cards, add admin construction assignment entry, improve card hierarchy. BUG fix thread must not edit ClaimTasks-related files. |

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
11. If an agent needs coordination with another active thread, the agent must proactively send a message to that thread when its thread ID is available.
12. If the other thread ID is not available, the agent must record the coordination request in this file and pause instead of taking over the version or files.

## Conflict Handling

- If two agents need the same files, the first active version claim keeps ownership.
- The second agent pauses and records the requested follow-up under the next version.
- If urgent production work must interrupt an active claim, the user must explicitly reassign ownership.
- Direct thread messaging is preferred over implicit assumptions. The coordination file is the fallback channel when direct messaging is not possible.
