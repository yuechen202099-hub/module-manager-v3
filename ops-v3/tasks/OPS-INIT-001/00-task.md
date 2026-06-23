# OPS-INIT-001 Task

- Task ID: OPS-INIT-001
- Title: Establish V3 production ops Agent system and V3.0.2 repository baseline
- Status: ARCHIVED
- Priority: P1
- Type: Release operation / documentation initialization
- Owner: chief owner
- Created at: 2026-06-24T00:45:58+08:00
- Baseline version: V3.0.2

## Scope

- Create new public GitHub repository `yuechen202099-hub/module-manager-v3`.
- Preserve Git history from `feature/v3.0.0-apple-ui-lab`.
- Use `main` as the new default branch.
- Initialize `ops-v3/` as the current production operations source of truth.
- Create 10 standing Agent threads and register them.
- Add version consistency rules for all current-version paths.

## Non-Scope

- No business code changes.
- No application version bump.
- No production release.
- No production `.env`, `data`, uploads, OSS, PostgreSQL, or Alembic changes.
