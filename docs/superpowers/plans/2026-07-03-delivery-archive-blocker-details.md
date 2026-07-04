# Delivery Archive Blocker Details Plan

## Baseline

- Repository: `module-manager-v3`
- Platform branch: `pm-platform/production-3.0.77-sync`
- Production baseline branch: `production/V3/3.0.77`
- Baseline commit at work start: `6892205`

## Goal

Make the delivery archive manifest preview actionable by listing the work orders that block the delivery package, with the reason, work object, aggregate value, and handling detail.

## Product Rules

- Keep the feature read-only.
- Do not create archives, exports, database records, tags, releases, or production writes.
- Reuse the existing archive manifest sections as the blocker source of truth.
- Exclude approved archive rows from the blocker list.
- Keep the blocker list compact inside the project board archive readiness panel.
- Preserve the device hierarchy context already shown on the project board, including main device replacement and accessory replacement confirmation.

## Implementation Steps

1. Add a frontend guard that fails until the project board shows blocker work-order details.
2. Add `platformArchiveManifestBlockerRows` to flatten blocker sections.
3. Add a section-reason label helper for operator-readable blocker reasons.
4. Render a compact blocker detail list under the manifest summary.
5. Verify the guard, related manifest guards, Vue build, browser smoke, formatting, and sensitive-path checks.

## Data And Safety

- No backend write path.
- No database migration.
- No PostgreSQL or OSS operation.
- No production data edit.
- No official version bump.
- No deployment.

## Rollback

- Remove the blocker detail computed value, reason-label helper, template block, and CSS from `ProjectBoardView.vue`.
- Remove `scripts/verify_vue_delivery_archive_manifest_blocker_details.js`.
- Rebuild Vue static assets.
