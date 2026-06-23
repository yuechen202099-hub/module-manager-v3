# 00 Baseline

## Baseline Snapshot

- Ops task: OPS-INIT-001
- Baseline recorded at: 2026-06-24T00:45:58+08:00
- Current production version: V3.0.2
- New repository: https://github.com/yuechen202099-hub/module-manager-v3
- Legacy repository: https://github.com/yuechen202099-hub/module-manager-v2
- New default branch: main
- Legacy source branch: feature/v3.0.0-apple-ui-lab
- Baseline commit short: 78cee88
- Baseline commit full: 78cee884952ec0313e848cd1b0468956a846e16c
- Baseline commit subject: docs: record v3.0.2 production rematch

## Baseline Command Record

Required commands were executed against the legacy repository at:

`C:\Users\Administrator\Desktop\2025模块改造\模块更换项目管理器V2.0`

Observed results:

- `git status --short`: clean.
- `git checkout feature/v3.0.0-apple-ui-lab`: branch already checked out.
- `git log -1 --oneline`: `78cee88 docs: record v3.0.2 production rematch`.
- `git rev-parse HEAD`: `78cee884952ec0313e848cd1b0468956a846e16c`.
- `git fetch origin` and `git pull --ff-only origin feature/v3.0.0-apple-ui-lab`: local Git HTTPS connection to GitHub failed with connection reset / connect timeout.
- GitHub API verification for `origin/feature/v3.0.0-apple-ui-lab`: `78cee884952ec0313e848cd1b0468956a846e16c`.

The local HEAD and remote branch HEAD matched exactly before the new repository baseline was created.

## New Repository Creation

- Local new repository path: `C:\Users\Administrator\Desktop\2025模块改造\module-manager-v3`
- Creation method: local clone from the verified legacy working tree, preserving Git history.
- New remote: `origin https://github.com/yuechen202099-hub/module-manager-v3.git`
- Legacy remote retained as: `legacy-v2 https://github.com/yuechen202099-hub/module-manager-v2.git`
- New default branch: `main`
- Existing `v3.0.2` tag was not moved.

## Production Safety Baseline

OPS-INIT-001 did not modify business code and did not touch:

- production `.env`
- production `data`
- uploads
- OSS
- PostgreSQL
- Alembic migrations
- application version files
