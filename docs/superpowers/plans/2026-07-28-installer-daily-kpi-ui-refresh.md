# Installer Daily KPI UI Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the existing installer daily-workload KPI dialog as the approved A “经营简报” layout with the A1 “通栏简报” secondary metric band, without changing KPI values or behavior.

**Architecture:** Keep `InstallerKpiDialog.vue` as the single UI owner and continue consuming the existing `totals`, `pagedRows`, drilldown handlers, and CSV helpers. Change only template hierarchy and scoped presentation styles, while strengthening the existing Python source contract so the approved hierarchy and table behavior cannot silently regress.

**Tech Stack:** Vue 3 `<script setup>`, TypeScript, Element Plus 2.9, scoped CSS, Python contract verification, Vite 6.

## Global Constraints

- Do not modify KPI formulas, installer attribution, API requests, database schema, or production data.
- Do not change `fetchInstallerWorkload`, `installerKpi.ts` filtering/pagination/CSV behavior, or parent component interfaces.
- Keep all existing detail columns, work-time drilldowns, segment addresses, exception drilldowns, raw-data navigation, and KPI CSV export.
- Use the approved A visual language: white/cool-gray surfaces, navy text, restrained business-blue accents, and no decorative gradients.
- Use the approved A1 secondary layer: one continuous three-column information band, not three independent cards.
- Do not add charts, rankings, filters, status badges, or invented timestamps.
- Do not deploy to production in this plan; production release requires separate explicit authorization after implementation verification.

## File Structure

- Modify `v2-web/src/components/InstallerKpiDialog.vue`
  - Owns the title treatment, two KPI hierarchy sections, main table shell, footer layout, and responsive behavior.
- Modify `scripts/verify_v3_2_1_installer_kpi_restore.py`
  - Adds source-level regression contracts for the approved UI hierarchy without duplicating KPI calculations.
- Reference `docs/superpowers/specs/2026-07-28-installer-daily-kpi-ui-refresh-design.md`
  - Approved visual and behavioral requirements.
- No new runtime source files, API fields, dependencies, or global styles.

---

### Task 1: Implement the approved two-level KPI hierarchy

**Files:**
- Modify: `scripts/verify_v3_2_1_installer_kpi_restore.py:102-134`
- Modify: `v2-web/src/components/InstallerKpiDialog.vue:51-60`
- Modify: `v2-web/src/components/InstallerKpiDialog.vue:179-194`
- Modify: `v2-web/src/components/InstallerKpiDialog.vue:327-357`

**Interfaces:**
- Consumes: `props.installer: string`, `props.scope: InstallerKpiScope`, and existing `totals` from `summarizeInstallerKpiRows`.
- Produces: `scopeLabel: ComputedRef<string>` plus `.workload-primary-summary` and `.workload-secondary-summary` DOM regions.
- Preserves: `v-model`, `open-data-center`, `loadWorkload`, `downloadCsv`, and every KPI value expression.

- [ ] **Step 1: Add a failing UI hierarchy contract**

Add these assertions at the end of `run_component_contract()`:

```python
    primary = re.search(
        r'<section class="workload-primary-summary"[\s\S]*?</section>',
        component,
    )
    secondary = re.search(
        r'<section class="workload-secondary-summary"[\s\S]*?</section>',
        component,
    )
    assert primary, "InstallerKpiDialog must expose the approved primary KPI region"
    assert secondary, "InstallerKpiDialog must expose the approved A1 secondary KPI band"
    assert primary.group(0).count('class="workload-primary-item') == 4
    assert secondary.group(0).count('class="workload-secondary-item') == 3
    for label in ["资料组", "照片", "已归档", "异常"]:
        assert label in primary.group(0), f"primary KPI region missing {label}"
    for label in ["总工时", "完成量", "加权完成"]:
        assert label in secondary.group(0), f"secondary KPI region missing {label}"
    assert 'class="installer-kpi-dialog-header"' in component
    assert "{{ scopeLabel }}" in component
```

- [ ] **Step 2: Run the contract and verify it fails**

Run:

```powershell
python scripts/verify_v3_2_1_installer_kpi_restore.py
```

Expected: FAIL with `InstallerKpiDialog must expose the approved primary KPI region`.

- [ ] **Step 3: Add a display-only scope label**

After the existing dialog-title computed values, add:

```ts
const scopeLabel = computed(() => {
  const anchorDate = props.scope.anchorDate.trim()
  if (props.scope.mode === 'day') return anchorDate ? `按日 · ${anchorDate}` : '按日'
  if (props.scope.mode === 'week') return anchorDate ? `按周 · ${anchorDate} 起` : '按周'
  if (props.scope.mode === 'month') return anchorDate ? `按月 · ${anchorDate.slice(0, 7)}` : '按月'
  return '全部周期'
})
```

This value is presentation-only and must not alter `filterInstallerKpiRows`.

- [ ] **Step 4: Replace the seven equal summary cards with the approved hierarchy**

Replace the main dialog opening and `.workload-summary` block with:

```vue
<el-dialog
  v-model="visible"
  class="installer-kpi-dialog"
  width="min(1180px, calc(100vw - 32px))"
  append-to-body
>
  <template #header>
    <div class="installer-kpi-dialog-header">
      <div>
        <h2>{{ installer }} · 每日工作量</h2>
        <span>{{ scopeLabel }}</span>
      </div>
    </div>
  </template>

  <el-alert v-if="loadError" type="error" :closable="false" :title="loadError" show-icon>
    <template #default>
      <el-button link type="primary" @click="loadWorkload">重试</el-button>
    </template>
  </el-alert>

  <section class="workload-primary-summary" aria-label="核心产出指标">
    <article class="workload-primary-item"><span>资料组</span><strong>{{ totals.groupCount }}</strong></article>
    <article class="workload-primary-item"><span>照片</span><strong>{{ totals.photoCount }}</strong></article>
    <article class="workload-primary-item"><span>已归档</span><strong>{{ totals.archivedCount }}</strong></article>
    <article class="workload-primary-item workload-primary-item-danger">
      <span>异常</span><strong>{{ totals.exceptionCount }}</strong>
    </article>
  </section>

  <section class="workload-secondary-summary" aria-label="工时与完成效率">
    <article class="workload-secondary-item workload-total-duration">
      <span>总工时</span><strong>{{ formatInstallerKpiDuration(totals.workDurationMinutes) }}</strong>
    </article>
    <article class="workload-secondary-item">
      <span>完成量</span><strong>{{ totals.completionCount }}</strong>
    </article>
    <article class="workload-secondary-item">
      <span>加权完成</span><strong>{{ formatInstallerKpiDecimal(totals.weightedCompletion) }}</strong>
    </article>
  </section>
```

Do not change the nested work-time, segment-address, or exception dialogs.

- [ ] **Step 5: Add the complete hierarchy styles**

Replace the `.workload-summary` shared rules with:

```css
.installer-kpi-dialog-header {
  display: flex;
  align-items: center;
  min-width: 0;
}

.installer-kpi-dialog-header h2 {
  margin: 0;
  color: #14243a;
  font-size: 18px;
  font-weight: 750;
  line-height: 1.35;
}

.installer-kpi-dialog-header span {
  display: block;
  margin-top: 3px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-weight: 600;
}

.workload-primary-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 10px;
}

.workload-primary-item {
  position: relative;
  display: grid;
  gap: 5px;
  min-width: 0;
  padding: 13px 14px 13px 17px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #f7f9fc;
}

.workload-primary-item::before {
  position: absolute;
  top: 12px;
  bottom: 12px;
  left: 0;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--el-color-primary);
  content: '';
}

.workload-primary-item span,
.workload-secondary-item span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-weight: 650;
}

.workload-primary-item strong {
  color: #14243a;
  font-size: 24px;
  font-weight: 800;
  line-height: 1.15;
}

.workload-primary-item-danger strong {
  color: var(--el-color-danger);
}

.workload-secondary-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-bottom: 12px;
  border-top: 1px solid #dce7ef;
  border-bottom: 1px solid #dce7ef;
  background: #f7fbfe;
}

.workload-secondary-item {
  display: grid;
  gap: 5px;
  min-width: 0;
  padding: 13px 20px;
  border-right: 1px solid #dbe5ed;
}

.workload-secondary-item:last-child {
  border-right: 0;
}

.workload-secondary-item strong {
  color: #14243a;
  font-size: 20px;
  font-weight: 780;
  line-height: 1.2;
}

.workload-total-duration {
  position: relative;
  padding-left: 22px;
}

.workload-total-duration::before {
  position: absolute;
  top: 13px;
  bottom: 13px;
  left: 0;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--el-color-primary);
  content: '';
}

.workload-total-duration strong {
  color: var(--el-color-primary);
}
```

Keep `.work-time-stats` as the existing independent three-column drilldown summary.

- [ ] **Step 6: Run the focused contract**

Run:

```powershell
python scripts/verify_v3_2_1_installer_kpi_restore.py
```

Expected: `[OK] V3.2.1 installer KPI restore checks passed`.

- [ ] **Step 7: Commit the hierarchy change**

```powershell
git add -- scripts/verify_v3_2_1_installer_kpi_restore.py v2-web/src/components/InstallerKpiDialog.vue
git commit -m "feat: redesign installer KPI summary hierarchy"
```

---

### Task 2: Improve table scanning, footer hierarchy, and responsive behavior

**Files:**
- Modify: `scripts/verify_v3_2_1_installer_kpi_restore.py:102-150`
- Modify: `v2-web/src/components/InstallerKpiDialog.vue:196-248`
- Modify: `v2-web/src/components/InstallerKpiDialog.vue:359-450`

**Interfaces:**
- Consumes: existing `pagedRows`, `openWorkTime`, `openExceptions`, `openDataCenter`, and `downloadCsv`.
- Produces: `.installer-kpi-table-shell`, `.installer-kpi-main-table`, and `.installer-kpi-footer`.
- Preserves: all 15 daily table columns, pagination, disabled states, and button behavior.

- [ ] **Step 1: Add a failing table and footer contract**

Append to `run_component_contract()`:

```python
    assert 'class="installer-kpi-table-shell"' in component
    assert 'class="installer-kpi-main-table"' in component
    assert re.search(
        r'<el-table-column\s+fixed="left"\s+prop="date"\s+label="日期"',
        component,
    ), "InstallerKpiDialog must keep the date visible while the table scrolls"
    assert 'class="installer-kpi-footer"' in component
    assert component.count("<el-table-column") >= 25, (
        "main and drilldown tables must retain every existing field"
    )
```

- [ ] **Step 2: Run the contract and verify it fails**

Run:

```powershell
python scripts/verify_v3_2_1_installer_kpi_restore.py
```

Expected: FAIL with `assert 'class="installer-kpi-table-shell"' in component`.

- [ ] **Step 3: Wrap and identify the main table without changing its data**

Change the table opening and date column to:

```vue
<div class="installer-kpi-table-shell">
  <el-table
    v-loading="loading"
    class="installer-kpi-main-table"
    :data="pagedRows.items"
    height="390"
    size="small"
  >
    <el-table-column fixed="left" prop="date" label="日期" width="104" />
```

Close `.installer-kpi-table-shell` immediately after the existing main `</el-table>`. Keep all remaining columns in their current order and keep every current width/min-width unless browser verification proves a specific visible defect.

- [ ] **Step 4: Add a deliberate footer container**

Replace the main footer slot contents with:

```vue
<template #footer>
  <div class="installer-kpi-footer">
    <el-button @click="visible = false">关闭</el-button>
    <div class="installer-kpi-footer-actions">
      <el-button plain :disabled="!installer" @click="openDataCenter">查看原始资料</el-button>
      <el-button type="primary" :disabled="!workloadRows.length" @click="downloadCsv">导出 KPI CSV</el-button>
    </div>
  </div>
</template>
```

- [ ] **Step 5: Add table, footer, and responsive styles**

Add:

```css
.installer-kpi-table-shell {
  overflow: hidden;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}

.installer-kpi-main-table {
  width: 100%;
}

:deep(.installer-kpi-main-table .el-table__header-wrapper th.el-table__cell) {
  color: #596a80;
  background: #f6f8fb;
  font-weight: 700;
}

:deep(.installer-kpi-main-table .el-table__row:hover > td.el-table__cell) {
  background: #f7fbfe;
}

.installer-kpi-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}

.installer-kpi-footer-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}
```

Replace the current summary media queries with:

```css
@media (max-width: 960px) {
  .workload-primary-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .work-time-chart {
    grid-template-columns: repeat(6, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .workload-primary-summary,
  .workload-secondary-summary,
  .work-time-stats {
    grid-template-columns: 1fr;
  }

  .workload-secondary-item {
    border-right: 0;
    border-bottom: 1px solid #dbe5ed;
  }

  .workload-secondary-item:last-child {
    border-bottom: 0;
  }

  .installer-kpi-footer {
    align-items: stretch;
    flex-direction: column-reverse;
  }

  .installer-kpi-footer-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .work-time-chart {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .screen-time-head {
    display: grid;
  }

  .screen-time-legend {
    text-align: left;
  }
}
```

- [ ] **Step 6: Run focused and static verification**

Run:

```powershell
python scripts/verify_v3_2_1_installer_kpi_restore.py
git diff --check
```

Expected:

- verifier prints `[OK] V3.2.1 installer KPI restore checks passed`;
- `git diff --check` prints no errors.

- [ ] **Step 7: Commit table and responsive polish**

```powershell
git add -- scripts/verify_v3_2_1_installer_kpi_restore.py v2-web/src/components/InstallerKpiDialog.vue
git commit -m "feat: polish installer KPI table layout"
```

---

### Task 3: Run functional, build, and visual fidelity verification

**Files:**
- Verify: `v2-web/src/components/InstallerKpiDialog.vue`
- Verify: `v2-web/src/utils/installerKpi.ts`
- Verify: `scripts/verify_v3_2_1_installer_kpi_restore.py`
- Reference: `.superpowers/brainstorm/2010-1785242964/content/visual-style.html`
- Reference: `.superpowers/brainstorm/2010-1785242964/content/second-tier-style.html`

**Interfaces:**
- Consumes: the completed UI implementation and existing read-only KPI endpoint shape.
- Produces: passing checks plus desktop and narrow-width screenshots suitable for direct comparison with A + A1.
- Preserves: no production deployment or external state mutation.

- [ ] **Step 1: Run all focused verification**

Run:

```powershell
python scripts/verify_v3_2_1_installer_kpi_restore.py
python scripts/verify_v3_2_0_dashboard_drilldown.py
python scripts/verify_v3_2_0_data_center_ui.py
python scripts/verify_v3_2_0_single_export_entry.py
```

Expected: every script exits `0` and prints its success marker.

- [ ] **Step 2: Run TypeScript and production-build checks**

Run:

```powershell
npm run type-check
npm run build
```

Working directory: `v2-web`

Expected:

- `vue-tsc --noEmit` exits `0`;
- Vite production build exits `0`;
- no new TypeScript, Vue template, or CSS build warnings attributable to this change.

- [ ] **Step 3: Start the local UI for isolated browser QA**

Run:

```powershell
npm run dev -- --host 127.0.0.1 --port 5173
```

Working directory: `v2-web`

Use the Browser/IAB control skill with request interception. Seed:

```js
localStorage.setItem(
  'v2-web-token',
  'eyJhbGciOiJub25lIn0.eyJleHAiOjQxMDQ2MDQ4MDB9.'
)
localStorage.setItem(
  'v2-web-user',
  JSON.stringify({ username: 'visual-admin', name: '视觉验收', role: 'admin', roles: ['admin'] })
)
```

Intercept these read requests:

```text
/api/local-test/summary
/api/local-test/tasks/status
/api/local-test/tasks?summary=true
/local-test/events
/api/local-test/installers/樊哲浩/daily-workload
```

Return a summary with one installer:

```json
{
  "summary": {
    "groups": 22358,
    "scanned_groups": 3561,
    "approved_groups": 1962,
    "installer_distribution": [
      {"installer": "樊哲浩", "group_count": 857, "share": 1}
    ]
  },
  "paths": {}
}
```

Generate the workload fixture with this exact data:

```js
const durationLabel = (minutes) => {
  const hours = Math.floor(minutes / 60)
  const remainder = minutes % 60
  return hours ? `${hours}小时${remainder}分钟` : `${remainder}分钟`
}

const fixtureRows = [
  ['2026-07-24', '11:19', '12:50', 91, 27, 105, 18, 0, 30.1],
  ['2026-07-22', '11:14', '14:08', 189, 70, 280, 40, 2, 84.8],
  ['2026-07-13', '10:51', '13:39', 183, 77, 306, 45, 1, 74.7],
  ['2026-07-07', '10:15', '12:52', 172, 73, 295, 44, 1, 78.1],
  ['2026-07-06', '09:58', '14:41', 289, 105, 420, 60, 3, 111.8],
  ['2026-07-03', '14:57', '16:39', 117, 38, 152, 24, 0, 52.6],
  ['2026-06-25', '10:17', '14:32', 195, 103, 408, 62, 2, 105.0],
  ['2026-06-24', '10:16', '12:17', 136, 63, 252, 42, 1, 65.0],
  ['2026-06-23', '09:40', '16:05', 399, 140, 554, 78, 2, 110.0],
  ['2026-06-18', '09:20', '11:20', 120, 80, 320, 50, 1, 29.0],
  ['2026-06-17', '13:10', '15:32', 142, 81, 324, 56, 2, 30.2],
].map(([date, startTime, endTime, minutes, groups, photos, archived, exceptions, weighted]) => ({
  date,
  start_time: startTime,
  end_time: endTime,
  work_duration_minutes: minutes,
  work_duration_label: durationLabel(minutes),
  efficiency_duration_minutes: minutes,
  efficiency_duration_label: durationLabel(minutes),
  completion_count: groups,
  group_count: groups,
  photo_count: photos,
  archived_count: archived,
  exception_count: exceptions,
  unreviewed_count: groups - archived,
  completion_per_effective_hour: groups / (minutes / 60),
  weighted_completion: weighted,
  weighted_completion_per_effective_hour: weighted / (minutes / 60),
  fused_work_duration_minutes: minutes,
  fused_work_duration_label: durationLabel(minutes),
  fused_weighted_completion_per_effective_hour: weighted / (minutes / 60),
  final_online_coefficient: 1,
  dense_bonus_minutes_v2: 0,
  timepoint_count: 1,
  two_hour_segments: [],
  exception_groups: [],
}))

const workloadResponse = {
  installer: '樊哲浩',
  items: fixtureRows,
}
```

The fixture totals are exactly 857 groups, 3,416 photos, 519 archived, 15 exceptions, 33 hours 53 minutes, and 771.3 weighted completion. Keep all traffic local and do not send credentials or writes.

- [ ] **Step 4: Capture and inspect the accepted desktop view**

At `1440×900`:

1. Open `/project-board`.
2. Click the `樊哲浩` installer row.
3. Capture the full KPI dialog to `C:\Users\Administrator\AppData\Local\Temp\installer-kpi-a-a1-1440.png`.
4. Inspect both the implementation screenshot and the accepted companion screens with `view_image`.

Record a fidelity ledger covering:

```text
1. Title and scope hierarchy
2. Four primary KPI blocks
3. A1 continuous secondary band
4. Table header/date column/active-hour emphasis
5. Footer button hierarchy
6. Dialog/table clipping and scrolling
```

Fix every material mismatch before continuing.

- [ ] **Step 5: Capture and inspect desktop-height and narrow-width behavior**

Repeat at:

- `1366×768`, screenshot `C:\Users\Administrator\AppData\Local\Temp\installer-kpi-a-a1-1366.png`;
- `1024×768`, screenshot `C:\Users\Administrator\AppData\Local\Temp\installer-kpi-a-a1-1024.png`.

Expected:

- 1366×768 shows the hierarchy and several table rows without footer overlap;
- 1024×768 keeps content inside the dialog and uses internal horizontal table scrolling;
- no primary metric, A1 cell, close control, or footer action is clipped.

- [ ] **Step 6: Re-run verification after visual fixes**

Run:

```powershell
python scripts/verify_v3_2_1_installer_kpi_restore.py
npm run type-check
npm run build
git diff --check
```

Working directory for npm commands: `v2-web`

Expected: all commands exit `0`.

- [ ] **Step 7: Commit any visual QA corrections**

If visual QA required source changes:

```powershell
git add -- scripts/verify_v3_2_1_installer_kpi_restore.py v2-web/src/components/InstallerKpiDialog.vue
git commit -m "fix: refine installer KPI visual fidelity"
```

If no source changes remain after the Task 2 commit, do not create an empty commit.

- [ ] **Step 8: Confirm the implementation boundary**

Run:

```powershell
git status --short
git log -4 --oneline
```

Expected:

- working tree is clean;
- only the approved design/plan and KPI UI implementation commits are new;
- no production deployment, version bump, package build, SSH action, or production data write has occurred.
