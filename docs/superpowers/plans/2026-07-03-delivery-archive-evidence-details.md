# Delivery Archive Evidence Details Plan

## Baseline

- Repository: `module-manager-v3`
- Platform branch: `pm-platform/production-3.0.77-sync`
- Production baseline branch: `production/V3/3.0.77`
- Baseline commit at work start: `6892205`

## Goal

Make the delivery archive manifest preview more actionable by showing the required field and photo evidence details, not only the total evidence count.

## Product Rules

- Keep the feature read-only.
- Do not create archives, exports, database records, tags, releases, or production writes.
- Show required field evidence and required photo evidence separately.
- Preserve conditional requirements from `requiredWhen`, so operators can see which evidence is always required and which is triggered by accessory replacement confirmation.
- Keep the UI compact inside the project board archive readiness panel.

## Implementation Steps

1. Add a frontend guard that fails until the project board shows evidence detail groups.
2. Add `platformArchiveManifestEvidenceGroups` and a condition-label helper.
3. Render `必备字段` and `必备照片` groups under `交付包预览`.
4. Add compact styling for evidence chips.
5. Verify the guard, Vue build, browser smoke, formatting, and sensitive-path checks.

## Data And Safety

- No backend write path.
- No database migration.
- No PostgreSQL or OSS operation.
- No production data edit.
- No official version bump.
- No deployment.

## Rollback

- Remove the project-board evidence detail computed values, helper, template block, and CSS.
- Remove `scripts/verify_vue_delivery_archive_manifest_evidence_details.js`.
- Rebuild Vue static assets.
