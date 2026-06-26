# Production Branch And Versioning SOP

## Current Baseline

- Production maintenance branch: `production/v3.0.35`
- Current production app version: `V3.0.37`
- Development environment `3.0.56` must not be mixed into this production line.

## Branch Rules

- Production fixes happen only on the production maintenance branch unless the user explicitly approves a different branch.
- Fetching from the production server is allowed for environment truth, but source-of-truth code changes must be committed to the production branch.
- Do not merge development branches into production without a scoped review and explicit user approval.

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
git tag v3.0.37 <commit>
git push origin v3.0.37
```

If tag creation is skipped, explain why in the release record.
