# Import Draft Hierarchy Gap Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep conditional device-evidence gaps visible after template validation when the operator generates an import draft preview.

**Architecture:** Backend import draft creation already reruns template validation and stores the full validation report. Add a small denormalized hierarchy-gap summary to the draft result so the frontend can show the same business issue in the import preview card. The existing validation report and generic issue table remain unchanged.

**Tech Stack:** FastAPI service functions, openpyxl workbook fixtures, Vue 3 + TypeScript + Element Plus, source guard scripts.

---

### Task 1: Backend Guard

**Files:**
- Create: `scripts/verify_platform_import_draft_hierarchy_gap_summary.py`
- Modify: none

- [ ] **Step 1: Write the failing backend verifier**

The verifier creates a terminal replacement project, uploads an external-completed workbook whose accessory replacement confirmation is triggered, then asserts the import draft result includes `summary.hierarchy_gap_count` and `hierarchy_gap_items`.

- [ ] **Step 2: Run the verifier**

Run: `python scripts\verify_platform_import_draft_hierarchy_gap_summary.py`

Expected: FAIL because import draft summaries do not yet expose hierarchy gap counts.

### Task 2: Frontend Guard

**Files:**
- Create: `scripts/verify_vue_import_draft_hierarchy_gap_summary.js`
- Modify: none

- [ ] **Step 1: Write the failing frontend guard**

The guard checks `ProjectsView.vue` for:

```text
hierarchyGapCount
hierarchyGapItems
层级缺口
import-draft-hierarchy-gaps
```

- [ ] **Step 2: Run the guard**

Run: `node scripts\verify_vue_import_draft_hierarchy_gap_summary.js`

Expected: FAIL because the import draft preview card does not yet show hierarchy gaps.

### Task 3: Backend Implementation

**Files:**
- Modify: `v2-api/app/services/platform/templates.py`
- Test: `scripts/verify_platform_import_draft_hierarchy_gap_summary.py`

- [ ] **Step 1: Extract hierarchy gap items from validation**

Inside `create_project_template_import_draft`, filter validation items:

```python
hierarchy_gap_items = [
    {
        "row": item.get("row"),
        "field_key": item.get("field_key", ""),
        "field_label": item.get("field_label", ""),
        "message": item.get("message", ""),
        "value": item.get("value", ""),
    }
    for item in validation.get("items", [])
    if item.get("code") == "missing_conditional_field"
]
```

- [ ] **Step 2: Add summary fields**

Add to draft `result.summary`:

```python
"hierarchy_gap_count": len(hierarchy_gap_items),
```

and add to `result`:

```python
"hierarchy_gap_items": hierarchy_gap_items[:20],
```

- [ ] **Step 3: Run backend verifier**

Run: `python scripts\verify_platform_import_draft_hierarchy_gap_summary.py`

Expected: PASS.

### Task 4: Frontend Implementation

**Files:**
- Modify: `v2-web/src/views/ProjectsView.vue`
- Test: `scripts/verify_vue_import_draft_hierarchy_gap_summary.js`

- [ ] **Step 1: Extend import draft summary helper**

Return `hierarchyGapCount` and `hierarchyGapItems` from `importDraftSummary`.

- [ ] **Step 2: Render the import preview gap**

In the import draft summary card, show `层级缺口` count. If there are items, show a compact `import-draft-hierarchy-gaps` list.

- [ ] **Step 3: Run frontend guard and build**

Run:

```powershell
node scripts\verify_vue_import_draft_hierarchy_gap_summary.js
pnpm --dir v2-web build
```

Expected: guard and build pass.

### Task 5: Documentation And Safety

**Files:**
- Create: `docs/reports/pm-platform-import-draft-hierarchy-gap-summary-2026-07-03.md`
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

- [ ] **Step 1: Record report**

Include changed files, behavior, verification commands, migration note, rollback note, and data safety.

- [ ] **Step 2: Run safety checks**

Run:

```powershell
git diff --check
git status --short -- .env data uploads v2-api/data v2-api/app/static/uploads
```

Expected: no whitespace errors and no sensitive path changes.
