# PM Platform Template Preview Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the project field graph preview use the same backend rules as downloadable Excel templates and template validation.

**Architecture:** Backend template service remains the source of truth. A lightweight preview API exposes template headers, field rows, platform fill rules, and site-required fields; the frontend requests it while editing draft project schemas and keeps local preview only as fallback.

**Tech Stack:** FastAPI, pytest, Vue 3, TypeScript, Element Plus, Node guard scripts.

---

### Task 1: Backend Preview Contract

**Files:**
- Modify: `v2-api/tests/test_platform_overview.py`
- Modify: `v2-api/app/services/platform/templates.py`
- Modify: `v2-api/app/api/routes/projects.py`

- [x] **Step 1: Write the failing test**

Add `test_project_template_preview_uses_download_template_rules_for_draft_schema` to require:

- `POST /projects/{project_id}/templates/preview`
- request body with `work_item_schema`
- response `templates[].headers`
- response `templates[].field_rows`
- response platform fill rules for external-completed templates
- response `site_required_fields`

- [x] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_overview.py::test_project_template_preview_uses_download_template_rules_for_draft_schema -q
```

Expected before implementation: FAIL with `405 Method Not Allowed`.

- [x] **Step 3: Implement backend preview service and route**

Add `build_project_template_preview()` in `v2-api/app/services/platform/templates.py` and route `POST /projects/{project_id}/templates/preview` in `v2-api/app/api/routes/projects.py`.

- [x] **Step 4: Run test to verify it passes**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_overview.py::test_project_template_preview_uses_download_template_rules_for_draft_schema -q
```

Expected after implementation: PASS.

### Task 2: Frontend Preview Integration

**Files:**
- Modify: `v2-web/src/api/types.ts`
- Modify: `v2-web/src/api/services.ts`
- Modify: `v2-web/src/components/project-fields/FieldGraphDesigner.vue`
- Modify: `v2-web/src/views/ProjectsView.vue`
- Modify: `scripts/verify_vue_project_field_graph_designer.js`

- [x] **Step 1: Add frontend API types and service**

Add `ProjectTemplateFieldPreview`, field-row types, and `previewProjectTemplateFields(projectId, workItemSchema)`.

- [x] **Step 2: Wire schema dialog to backend preview**

When the field schema dialog opens or the draft schema changes, call the backend preview API and pass the result into `FieldGraphDesigner`.

- [x] **Step 3: Keep local fallback**

If the preview API fails, keep the existing local computed preview so operators can continue editing.

- [x] **Step 4: Verify frontend guard and build**

Run:

```powershell
node scripts\verify_vue_project_field_graph_designer.js
pnpm --dir v2-web build
```

Expected: both commands pass.

### Task 3: Handoff Notes

**Files:**
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Modify: this plan

- [x] **Step 1: Record team operating model update**

Record backend agent decomposition, the current template-preview package, and next execution order.

- [x] **Step 2: Final verification and risk report**

Run focused backend, frontend, production-baseline, and sensitive-path checks. Summarize changed files, risk, rollback, and next task.
