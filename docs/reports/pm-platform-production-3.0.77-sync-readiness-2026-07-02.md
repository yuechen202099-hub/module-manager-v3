# PM Platform Production 3.0.77 Sync Readiness Report

Date: 2026-07-02

## Scope

This report records the safe path for bringing `pm-platform/project-drafts` forward to `production/V3/3.0.77`. It is a readiness and risk report only. No merge, rebase, tag, production release, database migration, OSS write, PostgreSQL write, or production deployment was performed.

## GitHub Trigger

GitHub Issue #1 asks the platform team to evaluate independent platform versioning and notes that the current production baseline is `V3.0.77`.

- Issue: `https://github.com/yuechen202099-hub/module-manager-v3/issues/1`
- Required PR/patch section: `平台版本号评估`
- Recommendation recorded in handoff docs: use `PM-V1.0.xx` as a platform progress version, always paired with the production baseline, and never as a replacement for production `V3.0.xx`.

## Production Drift

Fresh remote inspection found:

- Latest production branch: `origin/production/V3/3.0.77`
- Latest production commit: `4c05cc92a71e08a7eb5da6a25cef654271b4cfc5`
- Current platform branch: `pm-platform/project-drafts`
- Current platform HEAD: `8035f3247b5f2aaf579747fe4d71ae25fe2211e5`
- Merge base with latest production: `862659e0e6599367e7dbb164659b7ccd147c2574`

`scripts/verify_production_baseline.py` now fails as expected:

```text
[FAIL] Current ref HEAD does not contain production ref origin/production/V3/3.0.77 (4c05cc92a71e)
```

## Dirty Worktree Risk

Current worktree inspection:

```text
production_changed=145
dirty=192
overlap=43
```

Sensitive paths remain clean:

```text
.env
data
v2-api/data
v2-api/app/static/uploads
uploads
```

No pending changes were reported for those sensitive paths.

## Overlap Hotspots

Production `3.0.77` and platform WIP overlap on high-risk shared files:

- `v2-api/app/api/routes/projects.py`
- `v2-api/app/core/config.py`
- `v2-api/app/main.py`
- `v2-web/src/api/services.ts`
- `v2-web/src/api/types.ts`
- `v2-web/src/views/ProjectsView.vue`
- generated Vue static assets under `v2-api/app/static/vue/`

`git merge-tree` also reports `changed in both` for:

- `scripts/verify-client-release.py`
- `scripts/verify_release_sop.py`
- `v2-api/app/api/routes/local_test.py`
- `v2-api/app/api/routes/miniprogram.py`
- `v2-api/app/core/config.py`
- `v2-api/app/main.py`
- `v2-api/app/services/local_simulation.py`
- `v2-api/app/services/state_repository.py`
- `v2-api/tests/test_api.py`
- `v2-web/src/api/services.ts`
- `v2-web/src/views/ConstructionView.vue`

## Safe Sync Decision

Do not merge or rebase directly in the current dirty worktree.

Reason:

- The current workspace has substantial platform WIP.
- Latest production includes security hardening, auth, CORS, rate limiting, upload/photo proxy, release verifier, and generated asset changes.
- Shared files overlap with active platform work.
- Direct merge in this state risks losing or confusing platform changes and generated artifacts.

## Next Execution Sequence

1. Create a WIP snapshot or patch package for the current platform branch, excluding `.env`, real data, uploads, database dumps, secrets, build archives, and production artifacts.
2. Create an isolated sync workspace or clean branch based on `origin/production/V3/3.0.77`.
3. Re-apply platform changes in controlled packages.
4. Resolve production security hardening conflicts before platform UI conflicts.
5. Rebuild Vue static assets from source after conflict resolution.
6. Run:
   - `.\.venv\Scripts\python.exe scripts\verify_production_baseline.py`
   - focused platform backend tests,
   - platform guard scripts,
   - `pnpm --dir v2-web build`,
   - browser smoke for `/platform-projects`,
   - sensitive-path checks.
7. Refresh `平台版本号评估` with the concrete platform progress label, for example `PM-V1.0.03，基于生产 V3.0.77`.

## Rollback

Since this package does not merge or rebase:

- Rollback is simply reverting this report and related handoff documentation changes.
- No database rollback, OSS rollback, upload rollback, production release rollback, or tag cleanup is required.
