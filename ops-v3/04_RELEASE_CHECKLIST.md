# 04 Release Checklist

## Default Release Method

Default release method is patch sync. Full production `current` replacement is forbidden unless the chief owner explicitly approves it for a specific release.

## Required Release Fields

Every release plan must state:

- version
- commit
- tag
- backup path
- whether Alembic will run
- whether `.env` is affected
- whether `data` is affected
- whether uploads are affected
- whether OSS is affected
- whether PostgreSQL is affected
- validation pages
- rollback method

## Prohibited Release Actions

- No backup, no release.
- No clean commit/tag, no release.
- Do not overwrite production `.env`.
- Do not overwrite production `data`.
- Do not overwrite uploads.
- Do not execute Alembic without chief owner, Database Engineer Agent, and Release Agent confirmation.
- Do not replace production `current` as a default operation.

## Minimum Production Validation

After release, validate:

- `/health`
- `/login`
- `/project-board`
- `/task-hall`
- `/construction`
- `/openapi.json` must return 404

If the change involves construction collection, scan, camera, album, or weak network behavior, real phone validation is required. Desktop browser validation is only an initial check.

## Version Consistency Gate

Before release, the Version Management Agent must confirm the paths listed in `ops-v3/03_VERSION_LEDGER.md` are consistent for the target version.

For target `V3.0.x`:

- backend/package values use `3.0.x`
- UI labels use `V3.0.x`
- tag uses `v3.0.x`
- release ID uses `REL-V3.0.x-YYYYMMDD`
