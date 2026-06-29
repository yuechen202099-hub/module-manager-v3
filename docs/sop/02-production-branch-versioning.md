# Production Branch And Versioning SOP

## Current Baseline

- Production maintenance branch: `production/V3/3.0.71`
- Current production app version: `V3.0.71`
- Development environment `3.0.56` must not be mixed into this production line.

## Branch Rules

- Production fixes happen only on the production maintenance branch unless the user explicitly approves a different branch.
- Production branch names use `production/V3/<version>`, for example `production/V3/3.0.71`.
- The legacy branch `production/v3.0.35` is kept only for historical compatibility and must not be used as the base for new production work.
- Fetching from the production server is allowed for environment truth, but source-of-truth code changes must be committed to the production branch.
- Do not merge development branches into production without a scoped review and explicit user approval.

## Parallel Team Rules

- The production maintainer owns the official production version number.
- Miniprogram work starts from the latest production branch and uses `mp/<short-topic>` branches.
- Project management platform work starts from the latest production branch and uses `pm-platform/<short-topic>` branches.
- External teams should deliver changes through PRs into the current production branch. If PR is not possible, they must provide a patch, changed-file list, migration notes, and verification evidence.
- Candidate branches must not change official production version files unless the production maintainer assigns the release version.
- When multiple branches are ready at the same time, the production maintainer merges them one by one and increments versions in merge order.

## Version Rules

| Change Type | Version Action |
| --- | --- |
| Documentation/SOP only | No app version bump |
| Bug fix or small feature | `+0.01` |
| Major workflow change | `+0.1` after user confirmation |
| Database migration or architecture change | Ask user before version decision |

## Version Consistency Gate

Before release, verify the same version appears in:

- `v2-web/package.json`
- `v2-web/src/constants/releaseNotes.ts`
- `v2-web/index.html`
- `v2-web/src/components/AppLayout.vue`
- `v2-api/app/main.py`
- `v2-api/app/services/ops_status.py`
- `v2-api/pyproject.toml`
- release package name
- release record under `ops/releases/`

## Tag Rule

After a production release is verified, create or update a git tag for the released version when the repository policy allows it:

```powershell
git tag v<version> <commit>
git push origin v<version>
```

If tag creation is skipped, explain why in the release record.
