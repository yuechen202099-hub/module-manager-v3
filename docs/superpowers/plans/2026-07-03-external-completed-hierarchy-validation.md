# External Completed Hierarchy Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Warn users during system-external completed template validation when a replacement confirmation triggers required child evidence but the uploaded row lacks the follow-up fields.

**Architecture:** Keep template validation non-blocking for external completed imports. `validate_project_template_workbook()` will inspect `required_when` relationships after ordinary format/header checks and add warning items when a confirmation value matches but the conditional child field is missing or blank.

**Tech Stack:** FastAPI service-level Python, openpyxl workbook fixtures, Node source guards, existing template validation UI.

---

### Task 1: Add Red Verification

**Files:**
- Create: `scripts/verify_platform_external_completed_hierarchy_validation.py`
- Create: `scripts/verify_platform_external_completed_hierarchy_validation_guard.js`

- [x] **Step 1: Write failing Python verification**

Create a temporary project with terminal replacement hierarchy:

- primary `terminal_no`
- aggregate `area_no`
- confirmation field `comm_replace_confirm`
- conditional children `old_comm_module`, `new_comm_module`, and `comm_photo`

Upload an `external_completed` workbook row where `comm_replace_confirm` is `replace` but the conditional children are blank.

Expected after implementation:

- validation status is `warning`
- report contains `missing_conditional_field`
- report names the missing conditional child labels
- a second workbook where confirmation is `keep` does not raise conditional warnings

- [x] **Step 2: Write source guard**

Require backend helper tokens:

- `_validate_conditional_template_fields`
- `_required_when_matches`
- `missing_conditional_field`
- `template_type == "external_completed"`

- [x] **Step 3: Verify red**

Run:

```powershell
python scripts\verify_platform_external_completed_hierarchy_validation.py
node scripts\verify_platform_external_completed_hierarchy_validation_guard.js
```

Expected: Python verification fails before implementation; source guard fails until helpers are wired.

Result before implementation:

- Python verification: `[FAIL] missing conditional evidence should warn but not block`
- Source guard: `[FAIL] template validation must define conditional hierarchy helper`

### Task 2: Implement Conditional Validation

**Files:**
- Modify: `v2-api/app/services/platform/templates.py`

- [x] **Step 1: Add condition matcher**

Add `_required_when_matches(value, required_when)` supporting string and list `equals`.

- [x] **Step 2: Add conditional validation helper**

Add `_validate_conditional_template_fields(...)` that:

- runs only for `external_completed`
- finds fields with `required_when`
- checks the controlling field value in the same row
- appends a warning with code `missing_conditional_field` when the triggered child is missing or blank

- [x] **Step 3: Call helper from workbook validation**

Call the helper once per data row after required/recommended field checks.

### Task 3: Verify And Document

**Files:**
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Modify: `docs/superpowers/plans/2026-07-03-external-completed-hierarchy-validation.md`
- Create: `docs/reports/pm-platform-external-completed-hierarchy-validation-2026-07-03.md`

- [x] **Step 1: Run verification**

Run:

```powershell
python scripts\verify_platform_external_completed_hierarchy_validation.py
node scripts\verify_platform_external_completed_hierarchy_validation_guard.js
python scripts\verify_platform_line_loss_template_contract.py
python scripts\verify_platform_review_required_evidence.py
pnpm --dir v2-web build
```

Result: all commands passed. The frontend build retained the existing VueUse annotation and large chunk warnings.

- [x] **Step 2: Safety checks**

Run:

```powershell
git diff --check
git status --short -- .env data uploads v2-api/data v2-api/app/static/uploads
```

Result: both commands passed with no output.

- [x] **Step 3: Record results**

Update this plan, report, and team memory.
