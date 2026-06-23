# 05 Production Runbook

## Production Safety Rules

- Do not overwrite production `.env`.
- Do not overwrite production `data`.
- Do not overwrite uploads.
- Do not modify OSS objects without an approved task and rollback plan.
- Do not modify PostgreSQL without a database plan, dry-run, backup, and approval.
- Do not run Alembic without chief owner and Release Agent confirmation.
- Do not mark work complete without validation evidence.

## Standard Release Outline

1. Confirm task status is `QA_PASSED` or explicitly approved for release.
2. Confirm version owner and target version in `ops-v3/03_VERSION_LEDGER.md`.
3. Confirm clean Git status, commit, and tag.
4. Create backup and record the backup path.
5. Use patch sync by default.
6. Restart only the required service units.
7. Run health and page validation.
8. Record release report and rollback method.
9. Archive task.

## Backup Record Must Include

- timestamp
- production host
- code backup path
- runtime data backup path if affected
- PostgreSQL dump path if affected
- uploads backup path if affected
- restore command or manual rollback steps

## Rollback Record Must Include

- previous commit/tag
- files changed by patch sync
- service restart steps
- database rollback steps if any
- validation pages after rollback

## Database Work

All database work must produce:

- risk assessment
- dry-run result
- apply report
- rollback plan

Production data repair must be dry-run before apply.
