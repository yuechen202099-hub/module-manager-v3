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
set -euo pipefail
APP=/opt/module-manager-v2
PREVIOUS=/opt/module-manager-v2/releases/<previous-release>
RETIRED_UNITS=(
  module-manager-v2-photo-barcode-maintenance.service
  module-manager-v2-photo-barcode-maintenance-enqueue.service
  module-manager-v2-photo-barcode-maintenance.timer
)

validate_release_directory() {
  local target=$1
  if [ -z "$target" ] || [ ! -d "$target" ]; then
    echo "Release target is missing or is not a directory: $target" >&2
    return 1
  fi
  case "$target" in
    "$APP"/releases/v*) ;;
    *)
      echo "Release target is outside $APP/releases: $target" >&2
      return 1
      ;;
  esac
  if [ ! -f "$target/RELEASE_MANIFEST.md" ]; then
    echo "Release target has no RELEASE_MANIFEST.md: $target" >&2
    return 1
  fi
}

if ! PREVIOUS=$(readlink -f -- "$PREVIOUS"); then
  echo "Unable to resolve the requested rollback release" >&2
  exit 1
fi
validate_release_directory "$PREVIOUS"
PREVIOUS_NAME=$(basename "$PREVIOUS")
if [[ "$PREVIOUS_NAME" =~ ^v([0-9]+\.[0-9]+\.[0-9]+)- ]]; then
  PREVIOUS_VERSION=${BASH_REMATCH[1]}
else
  echo "Unable to derive the rollback semantic version from: $PREVIOUS" >&2
  exit 1
fi

assert_retired_unit() {
  local unit=$1
  local load_state
  local active_state
  local unit_file_state
  if ! LOAD_STATE=$(systemctl show "$unit" --property=LoadState --value); then
    echo "Unable to query retired unit load state: $unit" >&2
    return 1
  fi
  load_state=$LOAD_STATE
  if [ "$load_state" = "not-found" ]; then
    return 0
  fi
  if ! ACTIVE_STATE=$(systemctl show "$unit" --property=ActiveState --value); then
    echo "Unable to query retired unit active state: $unit" >&2
    return 1
  fi
  active_state=$ACTIVE_STATE
  case "$active_state" in
    inactive|failed) ;;
    *)
      echo "Retired background barcode unit is not inactive: $unit ($active_state)" >&2
      return 1
      ;;
  esac
  if ! UNIT_FILE_STATE=$(systemctl show "$unit" --property=UnitFileState --value); then
    echo "Unable to query retired unit file state: $unit" >&2
    return 1
  fi
  unit_file_state=$UNIT_FILE_STATE
  case "$unit_file_state" in
    disabled|static|indirect|masked) ;;
    *)
      echo "Retired background barcode unit is not disabled: $unit ($unit_file_state)" >&2
      return 1
      ;;
  esac
}

retire_unit() {
  local unit=$1
  local load_state
  if ! LOAD_STATE=$(systemctl show "$unit" --property=LoadState --value); then
    echo "Unable to query retired unit before disabling it: $unit" >&2
    return 1
  fi
  load_state=$LOAD_STATE
  if [ "$load_state" != "not-found" ]; then
    systemctl disable --now "$unit"
  fi
  assert_retired_unit "$unit"
}

wait_for_uvicorn() {
  "$APP/venv/bin/python" - <<'PY'
import socket
import time

deadline = time.monotonic() + 60
while time.monotonic() < deadline:
    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=1):
            raise SystemExit(0)
    except OSError:
        time.sleep(1)
raise SystemExit("Uvicorn did not listen on 127.0.0.1:8000 within 60 seconds")
PY
}

for UNIT in "${RETIRED_UNITS[@]}"; do
  retire_unit "$UNIT"
done
for UNIT in "${RETIRED_UNITS[@]}"; do
  assert_retired_unit "$UNIT"
done
rm -f \
  /etc/systemd/system/module-manager-v2-photo-barcode-maintenance.service \
  /etc/systemd/system/module-manager-v2-photo-barcode-maintenance-enqueue.service \
  /etc/systemd/system/module-manager-v2-photo-barcode-maintenance.timer
systemctl daemon-reload
for UNIT in "${RETIRED_UNITS[@]}"; do
  assert_retired_unit "$UNIT"
done
UNIT_BEFORE=$(mktemp)
UNIT_AFTER=$(mktemp)
trap 'rm -f "$UNIT_BEFORE" "$UNIT_AFTER"' EXIT
systemctl show module-manager-v2.service -p User -p Group -p WorkingDirectory -p ExecStart -p EnvironmentFiles > "$UNIT_BEFORE"
grep -Fx 'User=modulemgr' "$UNIT_BEFORE"
grep -Fx 'Group=modulemgr' "$UNIT_BEFORE"
grep -Fx 'WorkingDirectory=/opt/module-manager-v2/current/v2-api' "$UNIT_BEFORE"
grep -F 'ExecStart={ path=/opt/module-manager-v2/venv/bin/uvicorn ;' "$UNIT_BEFORE"
grep -F '/opt/module-manager-v2/.env' "$UNIT_BEFORE"
ln -sfn "$PREVIOUS" "$APP/current"
if ! RESTORED=$(readlink -f -- "$APP/current"); then
  echo "Unable to resolve current after rollback switch" >&2
  exit 1
fi
if [ "$RESTORED" = "$PREVIOUS" ]; then
  :
else
  echo "Rollback symlink verification failed: $RESTORED" >&2
  exit 1
fi
systemctl show module-manager-v2.service -p User -p Group -p WorkingDirectory -p ExecStart -p EnvironmentFiles > "$UNIT_AFTER"
diff -u "$UNIT_BEFORE" "$UNIT_AFTER"
systemctl restart module-manager-v2.service
systemctl is-active module-manager-v2.service
wait_for_uvicorn
"$APP/venv/bin/python" "$APP/current/scripts/production_health_check.py" \
  --base-url http://127.0.0.1 \
  --expected-version "$PREVIOUS_VERSION" \
  --env "$APP/.env"
```

Keep the retired background barcode worker and enqueue timer disabled after rollback. Construction live scanning, collector-inventory scanning, and review-region scanning remain part of the API; never run an Alembic downgrade during this rollback.

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
