# Project Template Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add downloadable Excel templates driven by each project's configured work item schema, using synthetic test data for platform simulation.

**Architecture:** Keep template rules in a focused platform service. Expose project-scoped download endpoints from the existing project router. Add a small frontend action group on the project page that calls the download endpoints.

**Tech Stack:** FastAPI, openpyxl, Vue 3, Element Plus, existing project schema catalog.

---

### Task 1: Backend Template Service

**Files:**
- Create: `v2-api/app/services/platform/templates.py`
- Modify: `v2-api/app/api/routes/projects.py`
- Test: `v2-api/tests/test_platform_overview.py`

- [ ] Write failing tests for `initial_work_orders`, `field_collection`, and `external_completed` template downloads.
- [ ] Implement a template service that builds workbooks from `work_item_schema`.
- [ ] Add `GET /projects/{project_id}/templates/{template_type}`.
- [ ] Verify tests pass without real business spreadsheets.

### Task 2: Frontend Template Download Entry

**Files:**
- Modify: `v2-web/src/api/services.ts`
- Modify: `v2-web/src/views/ProjectsView.vue`
- Modify: `scripts/verify_vue_work_item_schema_config.js`

- [ ] Write a verifier expectation for template download API calls and project page buttons.
- [ ] Add a frontend `downloadProjectTemplate(projectId, templateType, projectName)` service.
- [ ] Add three download buttons to draft/project rows.
- [ ] Verify the script and frontend build pass.

### Task 3: Synthetic Simulation Coverage

**Files:**
- Test: `v2-api/tests/test_platform_overview.py`
- Modify: `docs/superpowers/specs/2026-06-30-project-template-center-design.md` if rules need clarification.

- [ ] Use synthetic project schema data for meters, terminals, and station areas.
- [ ] Assert external completed templates mark platform-filled fields instead of requiring outside systems to provide them.
- [ ] Confirm no test depends on `C:\Users\Administrator\Desktop\总体数据.xlsx`.
