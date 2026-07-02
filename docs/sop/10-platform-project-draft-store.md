# Platform Project Draft Store

This SOP covers the platform project draft registry used by the operations engineering platform.

## Scope

- Applies to draft projects created through `POST /projects`.
- Stores project metadata only: project id, name, status, selected module ids, description, and timestamps.
- Does not store production business records, uploaded photos, OSS objects, PostgreSQL rows, or release packages.

## Runtime File

- Environment override: `PLATFORM_PROJECT_DRAFTS_PATH`.
- Default path when unset: `data/platform-project-drafts.json`.
- The file is runtime data and must not be committed. `data/` is ignored by git.

## Migration

No database migration is required.

Before enabling this in production:

1. Confirm the app is running from the current production branch.
2. Decide the runtime path. Prefer an absolute path outside the code checkout when the server has persistent storage.
3. If an existing draft store file exists, copy it to a timestamped backup before deployment.
4. Set `PLATFORM_PROJECT_DRAFTS_PATH` only in the server environment or production `.env`; never commit it.
5. Start the service and verify:
   - `GET /projects` returns the existing production project.
   - Creating a draft project returns status `draft`.
   - The configured JSON file is updated.
   - Restarting the service keeps the draft project visible.

## Backup

Before production release or server maintenance, back up:

- production `.env`
- PostgreSQL dump
- `data/`
- `uploads/`
- configured `PLATFORM_PROJECT_DRAFTS_PATH` file, if it is outside `data/`

## Rollback

To roll back the draft registry change:

1. Stop the service.
2. Restore the previous application build or branch.
3. Move `platform-project-drafts.json` aside instead of deleting it.
4. Restore the backed-up draft store file only if the target build supports it.
5. Start the service and verify `GET /projects` still returns the production project.

Rollback does not require OSS changes, PostgreSQL changes, or uploaded-photo cleanup because this feature does not write to those systems.

## Risk Notes

- The JSON store is suitable for early platform draft metadata, not high-concurrency project lifecycle management.
- Before draft projects become core production records, move the registry to a transactional backend or add explicit file locking.
- Invalid module ids in the file are treated as project configuration errors and should be fixed by restoring the last valid backup.
