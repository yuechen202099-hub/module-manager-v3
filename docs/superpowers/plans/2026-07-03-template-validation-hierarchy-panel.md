# Template Validation Hierarchy Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make external-completed template validation warnings about conditional device evidence visible as a dedicated hierarchy gap panel before the generic issue table.

**Architecture:** The backend already emits non-blocking validation items with code `missing_conditional_field`. The frontend project import validation dialog will compute those items, show them in an operator-focused panel, and keep the existing full issue table unchanged.

**Tech Stack:** Vue 3, TypeScript, Element Plus, existing source guard scripts, existing platform template validation contract.

---

### Task 1: Frontend Guard

**Files:**
- Create: `scripts/verify_vue_template_validation_hierarchy_panel.js`
- Modify: none

- [ ] **Step 1: Write the failing guard**

```js
const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const source = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ProjectsView.vue'), 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const requiredTokens = [
  ['const hierarchyValidationItems', 'projects view must compute hierarchy validation items'],
  ["item.code === 'missing_conditional_field'", 'hierarchy panel must use backend conditional evidence code'],
  ['function validationIssueRowLabel', 'projects view must format validation row labels'],
  ['层级证据缺口', 'validation dialog must expose hierarchy gap heading'],
  ['条件采集缺失', 'validation dialog must explain conditional evidence gaps'],
  ['validation-hierarchy-panel', 'validation dialog must style the hierarchy gap panel'],
  ['validation-hierarchy-list', 'validation dialog must style hierarchy gap rows'],
]

for (const [token, message] of requiredTokens) {
  if (!source.includes(token)) fail(message)
}

console.log('[OK] Vue template validation hierarchy panel is visible.')
```

- [ ] **Step 2: Run guard to verify it fails**

Run: `node scripts\verify_vue_template_validation_hierarchy_panel.js`

Expected: FAIL because the panel is not implemented yet.

### Task 2: Validation Dialog Panel

**Files:**
- Modify: `v2-web/src/views/ProjectsView.vue`
- Test: `scripts/verify_vue_template_validation_hierarchy_panel.js`

- [ ] **Step 1: Add computed hierarchy item list**

Add a computed value near existing validation state:

```ts
const hierarchyValidationItems = computed(() =>
  (templateValidationReport.value?.items || []).filter((item) => item.code === 'missing_conditional_field'),
)
```

- [ ] **Step 2: Add row label helper**

Add a helper near other validation helper functions:

```ts
function validationIssueRowLabel(item: ProjectTemplateValidationItem) {
  return item.row ? `第 ${item.row} 行` : '整表'
}
```

- [ ] **Step 3: Render the hierarchy panel**

Render the panel before the generic issue table:

```vue
<div v-if="hierarchyValidationItems.length" class="validation-hierarchy-panel" aria-label="层级证据缺口">
  <div class="validation-hierarchy-heading">
    <strong>层级证据缺口</strong>
    <span>条件采集缺失</span>
  </div>
  <div class="validation-hierarchy-list">
    <article v-for="item in hierarchyValidationItems" :key="`${item.row || 'sheet'}-${item.field_key}-${item.message}`">
      <ElTag type="warning" effect="light" size="small">{{ validationIssueRowLabel(item) }}</ElTag>
      <div>
        <strong>{{ item.field_label || item.field_key }}</strong>
        <span>{{ item.message }}</span>
      </div>
      <small v-if="item.value">当前值：{{ item.value }}</small>
    </article>
  </div>
</div>
```

- [ ] **Step 4: Add styles**

Add scoped CSS for the panel using existing Element Plus colors and an 8px radius.

- [ ] **Step 5: Run guard and frontend build**

Run:

```powershell
node scripts\verify_vue_template_validation_hierarchy_panel.js
pnpm --dir v2-web build
```

Expected: guard passes and frontend build exits 0.

### Task 3: Documentation And Safety Evidence

**Files:**
- Create: `docs/reports/pm-platform-template-validation-hierarchy-panel-2026-07-03.md`
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

- [ ] **Step 1: Record package report**

Document changed files, behavior, tests, migration note, rollback note, and data safety.

- [ ] **Step 2: Update team memory**

Add this package to the latest artifact list and current execution history.

- [ ] **Step 3: Run safety checks**

Run:

```powershell
git diff --check
git status --short -- .env data uploads v2-api/data v2-api/app/static/uploads
```

Expected: no whitespace errors and no sensitive path changes.
