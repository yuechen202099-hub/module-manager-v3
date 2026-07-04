# Delivery Archive Manifest Preview Plan

## Baseline

- Repository: `module-manager-v3`
- Platform branch: `pm-platform/production-3.0.77-sync`
- Production baseline branch: `production/V3/3.0.77`
- Baseline commit at work start: `6892205`

## Goal

Add a read-only delivery archive manifest preview after the delivery archive readiness summary.

Operators need to see what can enter the delivery package, what is still blocking the package, and which field/photo evidence rules define the package. This package does not create an archive, export files, write PostgreSQL, change production data, or publish a release.

## Product Rules

- Reuse the existing archive readiness classification so the manifest does not drift from review and evidence rules.
- `can_export` is true only when every work order is ready and there are no blockers.
- Required evidence must include always-required and conditional `required_when` fields/photos.
- The project board should show the preview as a compact inner section under archive readiness, without adding more operation buttons.

## Implementation Steps

1. Add a backend guard for `GET /projects/{project_id}/delivery/archive-manifest`.
2. Implement `build_platform_delivery_archive_manifest(project_id)` as a read-only summary.
3. Add frontend types, mapper, and fetch function.
4. Show the manifest preview on `/project-board`.
5. Add a frontend guard for visible manifest tokens and non-breaking fetch behavior.
6. Verify focused backend/frontend guards, build, browser smoke, diff checks, and sensitive paths.

## Data And Safety

- No database migration.
- No PostgreSQL write path.
- No OSS write path.
- No official production version bump.
- No tag.
- No deployment.
- No production data edit.

## Rollback

- Remove `build_platform_delivery_archive_manifest` and `/delivery/archive-manifest`.
- Remove frontend manifest types, mapper, fetch call, state, computed values, and project-board preview block.
- Remove `scripts/verify_platform_delivery_archive_manifest.py` and `scripts/verify_vue_delivery_archive_manifest.js`.
- Rebuild Vue static assets after reverting frontend files.
