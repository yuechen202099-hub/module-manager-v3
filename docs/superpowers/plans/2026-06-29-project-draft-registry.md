# Project Draft Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let administrators create non-persistent platform project drafts with selected modules so the platform can start managing projects beyond the current replacement project.

**Architecture:** Extend the existing platform catalog with a draft-only in-memory registry and empty draft adapter. Keep `replacement-project` unchanged. Add a frontend creation dialog that posts to `/projects`, refreshes the list, and selects the created draft project.

**Tech Stack:** FastAPI, Pydantic, existing `app.services.platform` services, Vue 3, TypeScript, Pinia, Element Plus, pytest, existing Node verification scripts.

---

## File Structure

- Modify `v2-api/app/schemas/project.py`: extend `ProjectCreate` with `module_ids`.
- Modify `v2-api/app/services/platform/catalog.py`: add draft registry, validation, empty overview/section builders, and `create_project_draft()`.
- Modify `v2-api/app/api/routes/projects.py`: make `POST /projects` call catalog creation and map validation errors to HTTP 400.
- Modify `v2-api/tests/test_platform_overview.py`: add backend tests for draft creation, list inclusion, module sorting, disabled section 404, and invalid payloads.
- Modify `v2-web/src/api/types.ts`: add project draft create payload type and allow project `status` to include `draft`.
- Modify `v2-web/src/api/services.ts`: add `createProject()` and map `draft` project status.
- Modify `v2-web/src/stores/workspace.ts`: add `createProjectDraft()` action that creates, reloads, and selects the draft.
- Modify `v2-web/src/views/ProjectsView.vue`: replace placeholder "新建项目" message with an Element Plus dialog form.
- Modify `scripts/verify_vue_project_module_metadata.js`: require frontend draft creation wiring.
- Modify `v2-api/app/static/vue/`: refresh Vue production static assets after build.

## Task 1: Backend Draft Registry

**Files:**
- Modify: `v2-api/app/schemas/project.py`
- Modify: `v2-api/app/services/platform/catalog.py`
- Modify: `v2-api/app/api/routes/projects.py`
- Test: `v2-api/tests/test_platform_overview.py`

- [ ] **Step 1: Write failing backend tests**

Add imports in `v2-api/tests/test_platform_overview.py`:

```python
from app.services.platform.catalog import reset_project_drafts
```

Add an autouse fixture near existing tests:

```python
@pytest.fixture(autouse=True)
def clear_project_drafts():
    reset_project_drafts()
    yield
    reset_project_drafts()
```

Add draft behavior tests:

```python
def test_create_project_draft_registers_project_with_selected_modules():
    client = TestClient(app)
    response = client.post(
        "/projects",
        json={
            "name": "  线路巡检项目  ",
            "description": "用于巡检流程接入",
            "module_ids": ["review", "progress", "field", "progress"],
        },
    )

    assert response.status_code == 200
    draft = response.json()["data"]
    assert draft["id"] == "xian-lu-xun-jian-xiang-mu"
    assert draft["name"] == "线路巡检项目"
    assert draft["description"] == "用于巡检流程接入"
    assert draft["status"] == "draft"
    assert [module["id"] for module in draft["modules"]] == ["progress", "field", "review"]
    assert draft["stage"] == "准备中"
    assert draft["system_progress"] == 0
    assert draft["field"]["photo_rows_linked"] == 0
    assert draft["review"]["pending_groups"] == 0
    assert "delivery" not in draft

    list_response = client.get("/projects")
    assert list_response.status_code == 200
    assert "xian-lu-xun-jian-xiang-mu" in [item["id"] for item in list_response.json()["data"]["items"]]
```

```python
def test_project_draft_module_endpoints_follow_selected_modules():
    client = TestClient(app)
    create_response = client.post(
        "/projects",
        json={"name": "审阅专项", "module_ids": ["review"]},
    )
    project_id = create_response.json()["data"]["id"]

    modules_response = client.get(f"/projects/{project_id}/modules")
    assert modules_response.status_code == 200
    assert [module["id"] for module in modules_response.json()["data"]["items"]] == ["review"]

    review_response = client.get(f"/projects/{project_id}/modules/review")
    assert review_response.status_code == 200
    assert review_response.json()["data"]["reviewed_groups"] == 0

    progress_response = client.get(f"/projects/{project_id}/modules/progress")
    assert progress_response.status_code == 404
```

```python
@pytest.mark.parametrize(
    ("payload", "expected_detail"),
    [
        ({"name": "   ", "module_ids": ["progress"]}, "Project name is required"),
        ({"name": "空模块", "module_ids": []}, "At least one project module is required"),
        ({"name": "未知模块", "module_ids": ["unknown"]}, "Unknown project module"),
    ],
)
def test_create_project_draft_rejects_invalid_payload(payload, expected_detail):
    client = TestClient(app)
    response = client.post("/projects", json=payload)

    assert response.status_code == 400
    assert expected_detail in response.json()["detail"]
```

- [ ] **Step 2: Run backend tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_overview.py -q
```

Expected: fail because `reset_project_drafts`, `module_ids`, and real draft creation do not exist yet.

- [ ] **Step 3: Extend ProjectCreate schema**

Replace `v2-api/app/schemas/project.py` with:

```python
from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    module_ids: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Add catalog draft exceptions and dataclass**

In `v2-api/app/services/platform/catalog.py`, add:

```python
from datetime import datetime, timezone
import re
```

Add below `ProjectConfigurationError`:

```python
class ProjectValidationError(ValueError):
    """Raised when a project draft request is invalid."""
```

Extend `ProjectDefinition` with:

```python
    description: str = ""
    created_at: str = ""
    updated_at: str = ""
```

Create a module-level draft store:

```python
_DRAFT_PROJECTS: dict[str, ProjectDefinition] = {}
```

- [ ] **Step 5: Add slug and draft helpers**

Add helper code in `catalog.py`:

```python
_PINYIN_SLUGS = {
    "线路巡检项目": "xian-lu-xun-jian-xiang-mu",
    "审阅专项": "shen-yue-zhuan-xiang",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify_project_name(name: str) -> str:
    normalized = re.sub(r"\s+", " ", name.strip())
    if normalized in _PINYIN_SLUGS:
        return _PINYIN_SLUGS[normalized]
    ascii_slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    if ascii_slug:
        return ascii_slug
    return "draft-project"


def _unique_project_id(base_id: str) -> str:
    existing_ids = {project.id for project in _PROJECTS} | set(_DRAFT_PROJECTS)
    if base_id not in existing_ids:
        return base_id
    index = 2
    while f"{base_id}-{index}" in existing_ids:
        index += 1
    return f"{base_id}-{index}"
```

- [ ] **Step 6: Include draft projects in lookups**

Modify `get_project_definition()` so it checks `_PROJECT_BY_ID` first and `_DRAFT_PROJECTS` second:

```python
def get_project_definition(project_id: str) -> ProjectDefinition:
    if project_id in _PROJECT_BY_ID:
        return _PROJECT_BY_ID[project_id]
    if project_id in _DRAFT_PROJECTS:
        return _DRAFT_PROJECTS[project_id]
    raise ProjectNotFound(project_id)
```

Modify `list_project_definitions()`:

```python
def list_project_definitions() -> list[dict[str, str]]:
    return [project.as_dict() for project in _PROJECTS] + [
        project.as_dict() for project in _DRAFT_PROJECTS.values()
    ]
```

Modify `list_project_overviews()`:

```python
def list_project_overviews() -> list[dict[str, Any]]:
    project_ids = [project.id for project in _PROJECTS] + list(_DRAFT_PROJECTS)
    return [get_project_overview(project_id) for project_id in project_ids]
```

- [ ] **Step 7: Add empty draft overview and section builders**

Add to `catalog.py`:

```python
def _empty_sections() -> dict[str, dict[str, Any]]:
    return {
        "progress": {
            "stage": "准备中",
            "system_progress": 0,
            "management_progress": 0,
            "management_locked": False,
        },
        "delivery": {
            "status": "preparing",
            "total_items": 0,
            "completed_items": 0,
            "latest_record": "",
        },
        "field": {
            "photo_rows_linked": 0,
            "unconstructed_groups": 0,
            "exception_count": 0,
        },
        "review": {
            "reviewed_groups": 0,
            "review_rate": 0,
            "pending_groups": 0,
        },
        "risks": {
            "total": 0,
            "field_exceptions": 0,
            "unconstructed_groups": 0,
            "delivery_blockers": 0,
        },
        "tasks": {
            "total": 0,
            "uploaded": 0,
            "reviewing": 0,
            "archived": 0,
            "upload_rate": 0,
            "review_rate": 0,
        },
    }


def _build_draft_project_overview(definition: ProjectDefinition) -> dict[str, Any]:
    sections = _empty_sections()
    overview: dict[str, Any] = {
        "id": definition.id,
        "name": definition.name,
        "description": definition.description,
        "status": definition.status,
        "total_groups": 0,
        "completed_groups": 0,
        "exception_groups": 0,
        "updated_at": definition.updated_at or definition.created_at,
    }
    overview.update(sections["progress"])
    for section_id in ("delivery", "field", "review", "risks", "tasks"):
        overview[section_id] = sections[section_id]
    return _apply_project_definition(overview, definition)
```

Modify `get_project_overview()`:

```python
    if definition.adapter == "draft":
        return _build_draft_project_overview(definition)
```

Modify `get_project_section()` so draft sections use `_empty_sections()` after `get_project_module_definition()` validates the module:

```python
    if get_project_definition(project_id).adapter == "draft":
        return _empty_sections()[section]
```

- [ ] **Step 8: Add draft creation API in catalog**

Add:

```python
def create_project_draft(*, name: str, description: str = "", module_ids: list[str]) -> dict[str, Any]:
    normalized_name = re.sub(r"\s+", " ", name.strip())
    if not normalized_name:
        raise ProjectValidationError("Project name is required")
    deduped_module_ids = list(dict.fromkeys(module_id.strip() for module_id in module_ids if module_id.strip()))
    if not deduped_module_ids:
        raise ProjectValidationError("At least one project module is required")
    unknown_modules = [module_id for module_id in deduped_module_ids if module_id not in _PROJECT_MODULE_BY_ID]
    if unknown_modules:
        raise ProjectValidationError(f"Unknown project module: {unknown_modules[0]}")
    now = _now_iso()
    project_id = _unique_project_id(_slugify_project_name(normalized_name))
    _DRAFT_PROJECTS[project_id] = ProjectDefinition(
        id=project_id,
        name=normalized_name,
        status="draft",
        adapter="draft",
        module_ids=tuple(deduped_module_ids),
        description=description.strip(),
        created_at=now,
        updated_at=now,
    )
    return get_project_overview(project_id)


def reset_project_drafts() -> None:
    _DRAFT_PROJECTS.clear()
```

- [ ] **Step 9: Wire POST /projects to catalog**

Modify `v2-api/app/api/routes/projects.py` imports:

```python
    ProjectValidationError,
    create_project_draft,
```

Replace `create_project()` body:

```python
@router.post("")
def create_project(payload: ProjectCreate, request: Request):
    try:
        project = create_project_draft(
            name=payload.name,
            description=payload.description or "",
            module_ids=payload.module_ids,
        )
    except ProjectValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(request, project)
```

- [ ] **Step 10: Run backend tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_overview.py -q
```

Expected: all platform overview tests pass.

- [ ] **Step 11: Commit backend draft registry**

Run:

```powershell
git add v2-api/app/schemas/project.py v2-api/app/services/platform/catalog.py v2-api/app/api/routes/projects.py v2-api/tests/test_platform_overview.py
git commit -m "feat: add project draft registry"
```

Expected: commit created with backend-only draft project registry.

## Task 2: Frontend API and Store Wiring

**Files:**
- Modify: `v2-web/src/api/types.ts`
- Modify: `v2-web/src/api/services.ts`
- Modify: `v2-web/src/stores/workspace.ts`
- Test: `scripts/verify_vue_project_module_metadata.js`

- [ ] **Step 1: Write failing frontend wiring verification**

In `scripts/verify_vue_project_module_metadata.js`, add reads for `v2-web/src/stores/workspace.ts`:

```js
const workspaceSource = fs.readFileSync(path.join(root, "v2-web", "src", "stores", "workspace.ts"), "utf8");
```

Append a check:

```js
  {
    ok:
      typesSource.includes("export type ProjectCreatePayload") &&
      typesSource.includes("status: 'active' | 'archived' | 'draft'") &&
      servicesSource.includes("export async function createProject") &&
      servicesSource.includes("api<BackendPlatformProject>('/projects'") &&
      servicesSource.includes("method: 'POST'") &&
      workspaceSource.includes("async createProjectDraft") &&
      workspaceSource.includes("services.createProject(payload)") &&
      workspaceSource.includes("this.selectProject(project.id)"),
    message: "Frontend must expose project draft creation through API services and workspace store.",
  },
```

- [ ] **Step 2: Run script and verify failure**

Run:

```powershell
node scripts\verify_vue_project_module_metadata.js
```

Expected: fail because frontend creation wiring does not exist.

- [ ] **Step 3: Add frontend create payload type**

In `v2-web/src/api/types.ts`, add after `ProjectModule`:

```ts
export type ProjectCreatePayload = {
  name: string
  description?: string
  moduleIds: string[]
}
```

Change project status:

```ts
  status: 'active' | 'archived' | 'draft'
```

- [ ] **Step 4: Add createProject service**

In `v2-web/src/api/services.ts`, import `ProjectCreatePayload`.

Update `mapProject()` status mapping:

```ts
const status = raw.status === 'draft' ? 'draft' : raw.status === 'archived' ? 'archived' : 'active'
```

Use `status` in the returned object.

Add near `fetchProjectsWithModules()`:

```ts
export async function createProject(payload: ProjectCreatePayload): Promise<Project> {
  const data = await api<BackendPlatformProject>('/projects', {
    method: 'POST',
    body: JSON.stringify({
      name: payload.name,
      description: payload.description || '',
      module_ids: payload.moduleIds,
    }),
  })
  const project = mapProject(data)
  const sections = await fetchProjectModuleSections(project.id, project.modules)
  return {
    ...project,
    ...sections.progress,
    delivery: sections.delivery,
    field: sections.field,
    review: sections.review,
    risks: sections.risks,
    tasks: sections.tasks,
  }
}
```

- [ ] **Step 5: Add workspace store action**

In `v2-web/src/stores/workspace.ts`, import `ProjectCreatePayload`.

Add action:

```ts
    async createProjectDraft(payload: ProjectCreatePayload) {
      const project = await services.createProject(payload)
      await this.loadProjects()
      this.selectProject(project.id)
      return project
    },
```

- [ ] **Step 6: Run frontend wiring verification**

Run:

```powershell
node scripts\verify_vue_project_module_metadata.js
```

Expected: pass.

- [ ] **Step 7: Commit frontend API/store wiring**

Run:

```powershell
git add scripts/verify_vue_project_module_metadata.js v2-web/src/api/types.ts v2-web/src/api/services.ts v2-web/src/stores/workspace.ts
git commit -m "feat: wire project draft creation API"
```

Expected: commit created.

## Task 3: Project Creation Dialog

**Files:**
- Modify: `v2-web/src/views/ProjectsView.vue`
- Modify: `scripts/verify_vue_project_module_metadata.js`

- [ ] **Step 1: Extend frontend verification for dialog**

Append to `scripts/verify_vue_project_module_metadata.js` checks:

```js
  {
    ok:
      projectsViewSource.includes("createDialogVisible") &&
      projectsViewSource.includes("createForm") &&
      projectsViewSource.includes("ElDialog") &&
      projectsViewSource.includes("ElCheckboxGroup") &&
      projectsViewSource.includes("workspace.createProjectDraft") &&
      !projectsViewSource.includes("项目创建接口待接入"),
    message: "Projects view must provide a project draft creation dialog.",
  },
```

- [ ] **Step 2: Run script and verify failure**

Run:

```powershell
node scripts\verify_vue_project_module_metadata.js
```

Expected: fail because dialog does not exist.

- [ ] **Step 3: Add dialog state and defaults**

In `ProjectsView.vue`, update imports:

```ts
import { computed, reactive, ref } from 'vue'
```

Add script state:

```ts
const createDialogVisible = ref(false)
const creatingProject = ref(false)
const createForm = reactive({
  name: '',
  description: '',
  moduleIds: ['progress', 'delivery', 'field', 'review'],
})

const moduleOptions = computed(() => {
  const knownModules = workspace.projects.flatMap((project) => project.modules)
  const modules = knownModules.length ? knownModules : fallbackModules
  const uniqueModules = new Map(modules.map((module) => [module.id, module]))
  return Array.from(uniqueModules.values()).sort((left, right) => left.priority - right.priority)
})
```

Add helpers:

```ts
function openCreateDialog() {
  createDialogVisible.value = true
}

function resetCreateForm() {
  createForm.name = ''
  createForm.description = ''
  createForm.moduleIds = ['progress', 'delivery', 'field', 'review']
}

async function submitCreateProject() {
  const name = createForm.name.trim()
  if (!name) {
    ElMessage.warning('请填写项目名称')
    return
  }
  if (!createForm.moduleIds.length) {
    ElMessage.warning('请至少选择一个模块')
    return
  }
  creatingProject.value = true
  try {
    const project = await workspace.createProjectDraft({
      name,
      description: createForm.description.trim(),
      moduleIds: createForm.moduleIds,
    })
    createDialogVisible.value = false
    resetCreateForm()
    ElMessage.success(`已创建项目草稿：${project.name}`)
  } finally {
    creatingProject.value = false
  }
}
```

- [ ] **Step 4: Replace button behavior**

Change:

```vue
<ElButton type="primary" :icon="Plus" @click="ElMessage.info('项目创建接口待接入')">新建项目</ElButton>
```

To:

```vue
<ElButton type="primary" :icon="Plus" @click="openCreateDialog">新建项目</ElButton>
```

- [ ] **Step 5: Add dialog template**

Add after the `section`:

```vue
<ElDialog v-model="createDialogVisible" title="新建项目草稿" width="520px" @closed="resetCreateForm">
  <ElForm label-position="top">
    <ElFormItem label="项目名称" required>
      <ElInput v-model="createForm.name" maxlength="40" show-word-limit placeholder="例如：线路巡检项目" />
    </ElFormItem>
    <ElFormItem label="项目说明">
      <ElInput
        v-model="createForm.description"
        type="textarea"
        :rows="3"
        maxlength="160"
        show-word-limit
        placeholder="说明这个项目的现场范围、交付目标或接入计划"
      />
    </ElFormItem>
    <ElFormItem label="启用模块" required>
      <ElCheckboxGroup v-model="createForm.moduleIds" class="module-checkboxes">
        <ElCheckbox v-for="module in moduleOptions" :key="module.id" :label="module.id">
          {{ module.name }}
        </ElCheckbox>
      </ElCheckboxGroup>
    </ElFormItem>
  </ElForm>
  <template #footer>
    <ElButton @click="createDialogVisible = false">取消</ElButton>
    <ElButton type="primary" :loading="creatingProject" @click="submitCreateProject">创建草稿</ElButton>
  </template>
</ElDialog>
```

- [ ] **Step 6: Add compact dialog styles**

Add to style:

```css
.module-checkboxes {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px 12px;
}
```

- [ ] **Step 7: Run frontend verification**

Run:

```powershell
node scripts\verify_vue_project_module_metadata.js
node scripts\verify_vue_project_module_paths.js
```

Expected: both pass.

- [ ] **Step 8: Commit project creation dialog**

Run:

```powershell
git add scripts/verify_vue_project_module_metadata.js v2-web/src/views/ProjectsView.vue
git commit -m "feat: add project draft creation dialog"
```

Expected: commit created.

## Task 4: Build, Static Assets, and Final Verification

**Files:**
- Modify: `v2-api/app/static/vue/`

- [ ] **Step 1: Run production baseline and backend tests**

Run:

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_production_baseline.py
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_overview.py -q
```

Expected: baseline OK and backend tests pass.

- [ ] **Step 2: Run frontend scripts before build**

Run:

```powershell
node scripts\verify_vue_project_module_metadata.js
node scripts\verify_vue_project_module_paths.js
```

Expected: both pass.

- [ ] **Step 3: Build Vue static assets**

Run:

```powershell
$env:PATH = 'C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin;C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin;' + $env:PATH
cd v2-web
pnpm build
```

Expected: build passes, with only known chunk size or VueUse annotation warnings.

- [ ] **Step 4: Re-run Vue scripts after build**

Run from repo root:

```powershell
node scripts\verify_vue_project_module_metadata.js
node scripts\verify_vue_project_module_paths.js
```

Expected: both pass against source and built assets.

- [ ] **Step 5: Run release gates**

Run:

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_release_sop.py
.\.venv\Scripts\python.exe .\scripts\verify_vue_migration_gate.py --strict-native
```

Expected: both pass.

- [ ] **Step 6: Check staged risk before commit**

Run:

```powershell
git diff --check
git status -sb
git ls-files --others --exclude-standard | Select-String -Pattern '(^|/|\\)(data|uploads|node_modules|__pycache__)(/|\\|$)|(^|/|\\)\.env($|\.)|\.pem$|\.xlsx$|\.zip$|\.db$|dump|\.log$'
```

Expected: no whitespace errors, no forbidden data/upload/env/secret artifacts.

- [ ] **Step 7: Commit static assets**

Run:

```powershell
git add v2-api/app/static/vue
git commit -m "build: refresh vue assets for project drafts"
```

Expected: commit contains only Vue static asset hash updates.

- [ ] **Step 8: Request code review**

Ask a code review subagent to review the full branch range covering the three implementation commits and the static asset commit. The reviewer should check API behavior, draft-only data boundary, frontend UX, and production risk.

- [ ] **Step 9: Final status**

Run:

```powershell
git status -sb
git log -5 --oneline
```

Expected: clean working tree on `feat/operations-platform-phase-one`.

## Self-Review

- Spec coverage: backend draft registry, frontend create dialog, module selection, empty draft state, validation, release gates, and production boundaries are each represented by tasks.
- Placeholder scan: no placeholder markers or vague "handle errors" steps remain; validation and error strings are specified.
- Type consistency: backend request uses `module_ids`; frontend payload uses `moduleIds` and maps to `module_ids`; project status includes `draft`; module ids match existing registry ids.
