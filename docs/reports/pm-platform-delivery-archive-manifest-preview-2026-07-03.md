# PM Platform Delivery Archive Manifest Preview Report

## Summary

Added a read-only delivery archive manifest preview.

The new endpoint summarizes which work orders can enter the delivery package, which work orders are still blocking the package, and which required field/photo evidence rules define the package. The project board now shows this preview inside the archive readiness panel.

This is not a formal archive write, export package, production release, PostgreSQL migration, or deployment.

## Baseline

- Production baseline branch: `production/V3/3.0.77`
- Platform branch: `pm-platform/production-3.0.77-sync`
- Baseline commit: `6892205`

## Modified Files

- `v2-api/app/services/platform/templates.py`
- `v2-api/app/api/routes/projects.py`
- `v2-web/src/api/types.ts`
- `v2-web/src/api/services.ts`
- `v2-web/src/views/ProjectBoardView.vue`
- `scripts/verify_platform_delivery_archive_manifest.py`
- `scripts/verify_vue_delivery_archive_manifest.js`
- `docs/superpowers/plans/2026-07-03-delivery-archive-manifest-preview.md`
- `docs/reports/pm-platform-delivery-archive-manifest-preview-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Generated Vue static assets under `v2-api/app/static/vue/`

## Verification

- `python scripts\verify_platform_delivery_archive_manifest.py`
- `python scripts\verify_platform_delivery_archive_readiness.py`
- `node scripts\verify_vue_delivery_archive_manifest.js`
- `node scripts\verify_vue_delivery_archive_readiness.js`
- `pnpm --dir v2-web build`
- Browser smoke on `http://127.0.0.1:52147/project-board?project_id=draft-project`

Browser smoke confirmed:

- `交付归档就绪`
- `交付包预览`
- `可纳入交付包`
- `阻塞清单`
- `必备证据`
- `换模块是在任务对象下更换附属设备`
- `换终端要确认附属设备是否更换`

## Risk

Low. The endpoint and UI are read-only. The main risk is interpretation: `can_export` intentionally means every work order is ready and no blockers remain, not that a partial set can be exported.

## Rollback

Remove the backend manifest builder and route, remove frontend manifest API/state/UI, remove the two verification scripts, and rebuild Vue static assets. No data rollback is required.
