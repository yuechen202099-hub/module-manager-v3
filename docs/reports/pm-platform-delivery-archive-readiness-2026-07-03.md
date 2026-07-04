# PM Platform Delivery Archive Readiness Report

## Summary

Added a read-only delivery archive readiness summary for platform projects.

The backend now classifies work orders as ready for archive, pending review, returned rework, evidence gap, not ready, or exception. The project board shows the resulting counts and blocker summary before any archive write path exists.

This package keeps the device hierarchy contract intact: module replacement remains an accessory-device replacement under one task object, while terminal replacement confirms accessory devices before conditional accessory fields and photos are required.

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
- `scripts/verify_platform_delivery_archive_readiness.py`
- `scripts/verify_vue_delivery_archive_readiness.js`
- `docs/superpowers/plans/2026-07-03-delivery-archive-readiness.md`
- `docs/reports/pm-platform-delivery-archive-readiness-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Generated Vue static assets under `v2-api/app/static/vue/`

## Verification

- `python scripts\verify_platform_delivery_archive_readiness.py`
- `python scripts\verify_platform_work_order_dashboard_summary.py`
- `python scripts\verify_platform_review_required_evidence.py`
- `node scripts\verify_vue_delivery_archive_readiness.js`
- `node scripts\verify_vue_device_hierarchy_config.js`
- `node scripts\verify_vue_field_graph_smart_drop.js`
- `python scripts\verify_platform_device_relation_roles.py`
- `python scripts\verify_platform_project_readiness.py`
- `node scripts\verify_vue_construction_hierarchy_collection.js`
- `node scripts\verify_vue_review_hierarchy_sections.js`
- `node scripts\verify_vue_project_board_field_hierarchy_map.js`
- `pnpm --dir v2-web build`
- Browser smoke on `http://127.0.0.1:52146/project-board?project_id=draft-project`

Browser smoke confirmed:

- `交付归档就绪`
- `归档前处理清单`
- `可归档`
- `待审阅`
- `证据缺口`
- `换模块是在任务对象下更换附属设备`
- `换终端要确认附属设备是否更换`

## Risk

Low to medium. The backend endpoint is read-only, but it adds a new project-board dependency on platform work-order status and required-evidence validation. The frontend now shows archive readiness independently from legacy task KPI totals.

## Rollback

Remove the read-only backend builder and route, remove the frontend API and project-board panel, remove the two verification scripts, then rebuild Vue static assets. No data migration rollback is required.
