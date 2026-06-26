# Subagent Review SOP

## Purpose

Make the review subagent a standard production gate instead of an informal second look.

## When Required

- Before every production deployment.
- Before merging a feature touching construction, review, KPI, dashboard, auth, upload, import/export, or database paths.
- After a P0 fix, before release.

## Reviewer Rules

- Reviewer is read-only by default.
- Reviewer must inspect the diff, tests, version markers, release package/static asset state, and production risk.
- Reviewer must classify issues as Critical, Important, or Minor.
- Critical and Important issues must be fixed or explicitly rejected with technical reasoning before deploy.

## Prompt Template

```text
You are a Senior Code Reviewer for the production maintenance line.
Review the current diff for production release risk. Do not edit files.

Context:
- Production branch:
- Target version:
- User requirement:
- Commands already run:
- Release package:
- Known risk areas:

Check:
- Requirement alignment
- Backward compatibility
- Data safety
- Test coverage
- Static asset state
- Version consistency
- Deployment readiness

Output:
### Strengths
### Issues
#### Critical
#### Important
#### Minor
### Assessment
Ready to merge? Yes | With fixes | No
```

## Review Record

Copy the reviewer assessment into the release record under `ops/releases/Vx.y.z.md`.
