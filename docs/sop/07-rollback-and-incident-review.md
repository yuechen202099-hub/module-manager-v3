# Rollback And Incident Review SOP

## Rollback Triggers

Rollback immediately if any of these occur after release:

- `/health` fails.
- Login fails for administrator.
- Construction page cannot load.
- Review or admin core page is unavailable.
- New release causes data mismatch or unsafe writes.
- Dependency installation partially failed.

## Rollback Steps

```bash
APP=/opt/module-manager-v2
PREVIOUS=/opt/module-manager-v2/releases/<previous-release>
ln -sfn "$PREVIOUS" "$APP/current"
systemctl restart module-manager-v2.service
systemctl is-active module-manager-v2.service
curl -fsS http://127.0.0.1/health
```

If data changed after deployment, do not restore database/uploads automatically. Stop and confirm the restore plan with the user.

## P0 Incident Flow

1. Classify as P0 if production施工, login, upload, review, dashboard, or data correctness is blocked.
2. Freeze unrelated changes.
3. Preserve evidence: time, version, commit, package hash, screenshots, logs, database state.
4. Choose containment: rollback, disable risky entry, or hotfix.
5. Back up before any data repair.
6. Patch only the root cause.
7. Run targeted and regression tests.
8. Request subagent review.
9. Deploy and verify.
10. Write incident record within 24 hours.

## Incident Record Location

Use:

```text
ops/incidents/P0-yyyyMMdd-short-title.md
```
