# 03 Version Ledger

## Current Version

- Current production version: V3.0.2
- Semantic value: `3.0.2`
- UI display value: `V3.0.2`
- Git tag format: `v3.0.2`
- Release ID format: `REL-V3.0.2-YYYYMMDD`
- Current owner: none
- OPS-INIT-001 version action: no application version bump

## Baseline

- Repository: https://github.com/yuechen202099-hub/module-manager-v3
- Branch: main
- Baseline commit: `78cee884952ec0313e848cd1b0468956a846e16c`
- Existing production tag: `v3.0.2`
- `v3.0.2` tag must not be moved.

## Version Increment Rules

- Small bug, small UI fix, copy change, compatibility fix: `+0.0.1`.
- Major workflow, architecture, database structure, or main page experience change: `+0.1.0`.
- Documentation-only ops initialization: no application version bump, but requires Git commit.

## Single Owner Rule

Only one task can own the next version at a time. The Version Management Agent records the owner before implementation begins.

| Version | Owner task | Owner Agent | Status | Notes |
| --- | --- | --- | --- | --- |
| V3.0.2 | baseline | chief owner | active production baseline | New `module-manager-v3` repository created from this baseline. |

## Strong Version Consistency Paths

Every version update must check and align all current-version values in these paths:

- `v2-api/pyproject.toml`
- `v2-api/app/main.py`
- `v2-api/app/services/ops_status.py`
- `v2-api/tests/test_api.py`
- `v2-web/package.json`
- `v2-web/index.html`
- `v2-web/src/components/AppLayout.vue`
- `v2-web/src/layouts/AppLayout.vue`
- `v2-web/src/views/LoginView.vue`
- `v2-api/app/static/vue/index.html`
- `v2-api/app/static/vue/assets/index-*.js`
- `v2-api/app/static/vue/assets/LoginView-*.js`

## Version String Policy

- Python/package semantic version: `3.0.x`.
- UI visible version: `V3.0.x`.
- Git tag: `v3.0.x`.
- Release ID: `REL-V3.0.x-YYYYMMDD`.
- Historical changelog entries may retain old values, but current runtime declarations, current release checklist, visible UI, tests, and static built assets must match.

## Required Version Check Command

Before a version-bearing release, run:

```powershell
rg -n "V3\\.[0-9]+\\.[0-9]+|v3\\.[0-9]+\\.[0-9]+|3\\.[0-9]+\\.[0-9]+" v2-api v2-web ops-v3 README.md PROJECT_KNOWLEDGE.md BUG_HISTORY.md FIX_NOTES.md docs
```

The Version Management Agent must classify every hit as either current-version path, historical record, or release note.
