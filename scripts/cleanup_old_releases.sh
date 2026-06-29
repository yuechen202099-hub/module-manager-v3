#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${1:-/opt/module-manager-v2}"
KEEP_RELEASES="${2:-5}"
MODE="${3:-}"
DRY_RUN=0

if [ "$MODE" = "--dry-run" ]; then
  DRY_RUN=1
fi

if ! [[ "$KEEP_RELEASES" =~ ^[0-9]+$ ]] || [ "$KEEP_RELEASES" -lt 1 ]; then
  echo "KEEP_RELEASES must be a positive integer" >&2
  exit 2
fi

RELEASES_DIR="$APP_ROOT/releases"
if [ ! -d "$RELEASES_DIR" ]; then
  echo "Release directory does not exist: $RELEASES_DIR" >&2
  exit 2
fi

CURRENT_RELEASE=""
if [ -L "$APP_ROOT/current" ] || [ -e "$APP_ROOT/current" ]; then
  CURRENT_RELEASE="$(readlink -f "$APP_ROOT/current" || true)"
fi

RELEASES_DIR_REAL="$(readlink -f "$RELEASES_DIR")"
mapfile -d '' RELEASE_ENTRIES < <(
  find "$RELEASES_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%T@\t%p\0' | sort -z -nr
)

echo "APP_ROOT=$APP_ROOT"
echo "RELEASES_DIR=$RELEASES_DIR_REAL"
echo "KEEP_RELEASES=$KEEP_RELEASES"
echo "CURRENT_RELEASE=$CURRENT_RELEASE"
echo "DRY_RUN=$DRY_RUN"

kept=0
deleted=0
index=0
for entry in "${RELEASE_ENTRIES[@]}"; do
  release_path="${entry#*$'\t'}"
  release_real="$(readlink -f "$release_path")"
  index=$((index + 1))

  case "$release_real" in
    "$RELEASES_DIR_REAL"/*) ;;
    *)
      echo "Refusing to delete path outside releases directory: $release_real" >&2
      exit 3
      ;;
  esac

  if [ "$release_real" = "$CURRENT_RELEASE" ]; then
    echo "KEEP current $release_path"
    kept=$((kept + 1))
    continue
  fi

  if [ "$index" -le "$KEEP_RELEASES" ]; then
    echo "KEEP recent $release_path"
    kept=$((kept + 1))
    continue
  fi

  if [ "$DRY_RUN" -eq 1 ]; then
    echo "DRY_RUN_DELETE $release_path"
  else
    if [ "$release_real" = "$CURRENT_RELEASE" ]; then
      echo "Refusing to delete current release: $release_path" >&2
      exit 4
    fi
    echo "DELETE $release_path"
    rm -rf -- "$release_path"
  fi
  deleted=$((deleted + 1))
done

package_deleted=0
mapfile -d '' PACKAGE_ENTRIES < <(
  find "$RELEASES_DIR" -mindepth 1 -maxdepth 1 -type f -name 'module-manager-v2-server-*.zip' -printf '%T@\t%p\0' | sort -z -nr
)

for entry in "${PACKAGE_ENTRIES[@]}"; do
  package_path="${entry#*$'\t'}"
  package_real="$(readlink -f "$package_path")"
  case "$package_real" in
    "$RELEASES_DIR_REAL"/*) ;;
    *)
      echo "Refusing to delete package outside releases directory: $package_real" >&2
      exit 5
      ;;
  esac

  if [ "$DRY_RUN" -eq 1 ]; then
    echo "DRY_RUN_DELETE_PACKAGE $package_path"
  else
    echo "DELETE_PACKAGE $package_path"
    rm -f -- "$package_path"
  fi
  package_deleted=$((package_deleted + 1))
done

echo "RELEASE_RETENTION_SUMMARY kept=$kept deleted=$deleted package_deleted=$package_deleted total=$index dry_run=$DRY_RUN"
