# OPS-INIT-001 Triage

## Classification

- Type: Release operation / documentation initialization
- Priority: P1
- Production impact: governance and repository baseline only
- User-facing runtime impact: none
- Database impact: none
- Release impact: no production release
- Version impact: no application version bump

## Decision

Create a V3.0.2-based repository and initialize V3 production operations documents before any future business changes.

## Do

- Record the verified baseline commit.
- Create the new GitHub repository and `main` branch.
- Register Agent roles, boundaries, locks, deliverables, task statuses, release safety, archive rules, and version consistency gates.

## Do Not

- Do not change application code.
- Do not rename `v2-api`, `v2-web`, or `v2-miniprogram` in this task.
- Do not alter production version values.
- Do not publish to production.
