# Construction Rework Gap Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show returned platform work orders on the construction side with a structured rework checklist, so field workers know exactly which fields or photos need to be collected again. The checklist must preserve replacement hierarchy: module replacement happens as accessory-device replacement under one task object, while terminal replacement records the main-device replacement and confirms whether accessory devices are also replaced.

**Architecture:** Backend construction work-order payloads will expose `rework_evidence_gap_groups` only for returned platform work orders. The groups reuse existing review hierarchy gap data and current required field/photo checks. The Vue construction page will map the groups and render them in both the platform work-order preview and active collection form.

**Tech Stack:** FastAPI service helpers in `v2-api/app/services/platform/templates.py`, Vue 3 + TypeScript API mapping in `v2-web/src/api`, and construction UI in `v2-web/src/views/ConstructionView.vue`.

---

### Task 1: Backend Guard

**Files:**
- Create: `scripts/verify_platform_construction_rework_gap_panel.py`
- Modify later: `v2-api/app/services/platform/templates.py`

- [x] **Step 1: Write the failing verifier**

Create a terminal replacement project. Import an external-completed row where `通讯模块是否更换=更换` but old/new module and evidence photo are blank. Execute the work-order task, return the review work order with a blank reason, then fetch `/projects/{project_id}/construction/work-orders`.

Assert the returned construction work order exposes:

```python
item["review_status"] == "returned"
item["rework_evidence_gap_groups"]
"导入层级缺口"
"旧通讯模块号"
"新通讯模块号"
"新旧模块照片"
```

- [x] **Step 2: Run red**

Run:

```powershell
& "C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\verify_platform_construction_rework_gap_panel.py
```

Expected red result: construction payload does not yet expose `rework_evidence_gap_groups`.

### Task 2: Frontend Guard

**Files:**
- Create: `scripts/verify_vue_construction_rework_gap_panel.js`
- Modify later: `v2-web/src/api/types.ts`
- Modify later: `v2-web/src/api/services.ts`
- Modify later: `v2-web/src/views/ConstructionView.vue`

- [x] **Step 1: Write the failing guard**

The guard requires:

```text
PlatformReworkEvidenceGapGroup
reworkEvidenceGapGroups
rework_evidence_gap_groups
platformReworkEvidenceGapGroups
退回补采清单
platform-rework-gap-panel
```

- [x] **Step 2: Run red**

Run:

```powershell
& "C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" scripts\verify_vue_construction_rework_gap_panel.js
```

Expected red result: construction UI has no structured rework gap panel.

### Task 3: Backend Implementation

**Files:**
- Modify: `v2-api/app/services/platform/templates.py`

- [x] Add `_platform_rework_evidence_gap_groups(work_order, construction_fields, photo_slots)`.
- [x] Return an empty list when review status is not `returned`.
- [x] Include `导入层级缺口` from `review_hierarchy_gap_items`.
- [x] Include current missing active required fields/photos when present.
- [x] Add `rework_evidence_gap_groups` to `_construction_work_order_payload`.

### Task 4: Frontend Implementation

**Files:**
- Modify: `v2-web/src/api/types.ts`
- Modify: `v2-web/src/api/services.ts`
- Modify: `v2-web/src/views/ConstructionView.vue`

- [x] Add `PlatformReworkEvidenceGapGroup` and `reworkEvidenceGapGroups`.
- [x] Map backend `rework_evidence_gap_groups`.
- [x] Add a computed `platformReworkEvidenceGapGroups`.
- [x] Render a `退回补采清单` panel in the active platform collection form.
- [x] Show the first gap group in the platform work-order preview card so workers can pick the right returned order quickly.

### Task 5: Verification and Records

**Files:**
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Create: `docs/reports/pm-platform-construction-rework-gap-panel-2026-07-03.md`

- [x] Run the new backend/frontend guards.
- [x] Re-run review return reason and construction submit gap guards.
- [x] Build Vue and browser-smoke `/construction`.
- [x] Run `git diff --check` and sensitive-path scan.
- [x] Record behavior, risk, and rollback notes.
