# Parallel Development And GitHub Flow

## Current Rule

- Official production branch format: `production/V3/<version>`.
- Current production baseline: `production/V3/3.0.70`.
- Old branch `production/v3.0.35` is historical compatibility only.

## Roles

- Production maintainer: owns release safety, production version numbers, final merge, tag, package, and deployment.
- Miniprogram team: develops miniprogram frontend/client-side work and any scoped backend adjustments on `mp/<short-topic>` branches.
- Project management platform team: develops platform features on `pm-platform/<short-topic>` branches.

## Version Ownership

- Official version numbers are assigned only when code enters the production line.
- Small feature or BUG fix: `+0.01`.
- Major workflow change: `+0.1` after user confirmation.
- Documentation/SOP-only changes do not bump the application version.
- Candidate branches must not reserve production versions. Use branch names, PR titles, or notes to describe candidate scope.

## Handoff Contract

Every external team handoff must include:

- Base branch and commit SHA.
- Changed-file list.
- Feature or bug description in Chinese.
- API/schema/env changes, if any.
- Migration or data backfill notes, if any.
- Test commands and results.
- Known risks and rollback notes.

## Merge Order

1. Production maintainer confirms the latest live version and branch.
2. External team rebases or merges the latest `production/V3/<version>`.
3. External team opens PR into the current production branch, or provides a patch if PR is unavailable.
4. Production maintainer reviews diff, runs tests, assigns the next production version, and updates release notes.
5. Production maintainer tags and publishes the verified release.

## Protected Files And Data

Never include these in PRs or patches:

- `.env`, `.pem`, database dumps, secrets, tokens, or real account passwords.
- `data/`, `v2-api/data/`, `v2-api/app/static/uploads/`, real uploaded photos.
- `node_modules/`, `__pycache__/`, build archives, production backup archives.

## Prompt Files

Ready-to-send prompts for collaborator Codex agents are in `docs/team-handoff-prompts.md`.
