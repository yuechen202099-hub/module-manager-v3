# V3.0.83 终端优先施工实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为终端任务增加管理员维护的“优先施工”标识、服务端派生的“可施工/可领取审阅”状态、Excel 两阶段批量导入和任务领取页四类筛选，并在施工上传达到 100% 时原子清除优先标识。

**Architecture:** PostgreSQL `tasks` 表保存唯一的人工优先标识和修改人/时间，JSON 后端保留等价字段；任务 payload 统一从上传/审阅统计派生可施工与可领取审阅，前端不重复计算。单条修改、批量确认和最后一组上传都在任务行锁内重新检查完成量并写审计；Excel 解析放进独立纯服务，路由只负责权限、文件限制和两阶段调用。

**Tech Stack:** Python 3.14、FastAPI、SQLAlchemy/PostgreSQL、Alembic、openpyxl、pytest、Vue 3、TypeScript、Element Plus、Node 源码契约验证、Vite、PowerShell 发布脚本。

## Global Constraints

- 生产基线必须是 `origin/production/V3/3.0.82` 的 `f4b703d`；本功能与图片框选识别同版发布为 `V3.0.83`。
- 唯一人工优先级是“优先施工”，不增加高/中/低等级。
- 优先标识绑定终端任务，不绑定领取人、施工员或指派记录；领取、释放和改派不能清除未完成终端的标识。
- `construction_available = total_groups > 0 and uploaded_count < total_groups`。
- `review_available = uploaded_count > 0 and unreviewed_count > 0`。
- `effective_construction_priority = construction_priority and construction_available`。
- 1%-99% 上传且仍有未审资料时，同一任务可以同时属于“可施工”和“可领取审阅”。
- 100% 上传后“可施工”和“优先施工”必须同时消失；最后一组上传事务永久清除数据库优先值。
- 回退至未施工不得恢复已清除的旧优先值。
- 零资料组任务不属于“可施工”或“可领取审阅”，也不能设置优先施工。
- 只有管理员能单条设置/取消、下载模板、预览和确认导入；审阅员只能在权限范围内查看服务端状态标签。
- Excel 固定列为 `终端号 | 优先施工`，优先施工只接受“是”或“否”，长终端号按字符串处理。
- 导入预览和错误明细每页 20 条；服务端仍返回完整逐行结果，前端分页渲染。
- 批量预览与确认都重新解析同一文件；冲突或格式错误存在时禁止确认。
- 单条、批量和自动清除都必须按当前团队隔离、锁定任务、写审计并使任务状态版本失效。
- 自动上传继续关闭，不修改施工缓存上传策略，不创建 `00000000` 或其他占位任务。

---

### Task 1: 任务字段与数据库迁移

**Files:**
- Create: `v2-api/alembic/versions/0005_add_construction_priority.py`
- Modify: `v2-api/app/models.py`
- Modify: `v2-api/tests/test_postgres_migration.py`

**Interfaces:**
- Produces: `Task.construction_priority: bool`、`Task.construction_priority_updated_by: str | None`、`Task.construction_priority_updated_at: datetime | None`。
- Migration revision: `20260721_0005`，down revision: `20260622_0004`。

- [ ] **Step 1: 写迁移字段和旧任务默认值失败测试**

在 `v2-api/tests/test_postgres_migration.py` 增加：

```python
def test_construction_priority_migration_has_safe_defaults_and_backfill() -> None:
    migration = (ROOT / "alembic" / "versions" / "0005_add_construction_priority.py").read_text(encoding="utf-8")
    assert 'revision = "20260721_0005"' in migration
    assert 'down_revision = "20260622_0004"' in migration
    assert '"construction_priority"' in migration
    assert "server_default=sa.false()" in migration
    assert '"construction_priority_updated_by"' in migration
    assert '"construction_priority_updated_at"' in migration
    assert "UPDATE tasks SET construction_priority = FALSE" in migration
```

- [ ] **Step 2: 运行测试确认 RED**

```powershell
Set-Location v2-api
..\.venv\Scripts\python.exe -m pytest tests\test_postgres_migration.py -q
```

Expected: 因 `0005_add_construction_priority.py` 尚不存在而失败。

- [ ] **Step 3: 增加模型字段和可逆迁移**

模型字段使用：

```python
construction_priority: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
construction_priority_updated_by: Mapped[str | None] = mapped_column(String(64))
construction_priority_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

迁移先新增带 `false` 默认值的三列，再执行 `UPDATE tasks SET construction_priority = FALSE`，最后保留数据库默认值供非 ORM 写入安全使用。`downgrade()` 按更新时间、修改人、优先值的反序删除三列。

- [ ] **Step 4: 运行迁移测试和模型导入确认 GREEN**

```powershell
Set-Location v2-api
..\.venv\Scripts\python.exe -m pytest tests\test_postgres_migration.py -q
..\.venv\Scripts\python.exe -c "from app.models import Task; print(Task.__table__.c.construction_priority.name)"
```

Expected: 测试通过并输出 `construction_priority`。

- [ ] **Step 5: 提交迁移**

```powershell
git add v2-api/alembic/versions/0005_add_construction_priority.py v2-api/app/models.py v2-api/tests/test_postgres_migration.py
git commit -m "feat: add terminal construction priority fields"
```

---

### Task 2: 服务端派生状态与 JSON/PostgreSQL payload

**Files:**
- Modify: `v2-api/tests/test_state_repository.py`
- Modify: `v2-api/tests/test_local_simulation.py`
- Modify: `v2-api/app/services/local_simulation.py`
- Modify: `v2-api/app/services/state_repository.py`

**Interfaces:**
- Produces: `construction_task_availability(stats: Mapping[str, Any]) -> tuple[bool, bool]`。
- Produces snake_case payload: `construction_priority`、`construction_available`、`review_available`，同时出现在 `/local-test/tasks` 与 `/local-test/construction/tasks`。
- JSON task defaults: `construction_priority=False`、`construction_priority_updated_by=""`、`construction_priority_updated_at=""`。

- [ ] **Step 1: 写 0%、部分上传、100%、全审和零资料组矩阵失败测试**

在 `test_state_repository.py` 增加：

```python
@pytest.mark.parametrize(
    ("stats", "expected"),
    [
        ({"total_groups": 4, "uploaded_count": 0, "unreviewed_count": 4}, (True, False)),
        ({"total_groups": 4, "uploaded_count": 2, "unreviewed_count": 2}, (True, True)),
        ({"total_groups": 4, "uploaded_count": 4, "unreviewed_count": 2}, (False, True)),
        ({"total_groups": 4, "uploaded_count": 2, "unreviewed_count": 0}, (True, False)),
        ({"total_groups": 0, "uploaded_count": 0, "unreviewed_count": 0}, (False, False)),
    ],
)
def test_construction_task_availability_matrix(stats, expected) -> None:
    assert state_repository.construction_task_availability(stats) == expected
```

再为 `_task_payload` 和 `_construction_task_payload` 断言：数据库值为 true 且 100% 完成时响应中的 `construction_priority` 必须防御性返回 false；部分完成时两个列表都返回 true。为 `task_status()` 增加断言，单独切换优先值会改变 status version。

- [ ] **Step 2: 运行矩阵测试确认 RED**

```powershell
Set-Location v2-api
..\.venv\Scripts\python.exe -m pytest tests\test_state_repository.py -k "construction_task_availability or construction_priority_payload" -q
```

Expected: 新 helper 和 payload 字段不存在。

- [ ] **Step 3: 实现唯一派生规则并接入两个后端**

在 `state_repository.py` 增加：

```python
def construction_task_availability(stats: Mapping[str, Any]) -> tuple[bool, bool]:
    total = max(0, int(stats.get("total_groups") or 0))
    uploaded = max(0, int(stats.get("uploaded_count") or 0))
    unreviewed = max(0, int(stats.get("unreviewed_count") or 0))
    return total > 0 and uploaded < total, uploaded > 0 and unreviewed > 0
```

`_task_payload` 使用 helper，并把有效优先状态写为 `bool(task.construction_priority and construction_available)`，同时返回修改人/时间；`_construction_task_payload` 继续复用 `_task_payload`，不能另写一套公式。PostgreSQL `task_status()` 查询和 JSON 状态摘要必须把有效优先布尔值纳入版本 hash 输入，使单条/批量修改立即改变 status version。`local_simulation.ensure_construction_task_fields` 和任务刷新函数设置同名 JSON 字段，使用同一公式，不允许前端根据百分比自行推算。

- [ ] **Step 4: 运行 JSON/PostgreSQL payload 回归确认 GREEN**

```powershell
Set-Location v2-api
..\.venv\Scripts\python.exe -m pytest tests\test_state_repository.py tests\test_local_simulation.py -k "construction_priority or construction_available or review_available" -q
```

Expected: 矩阵、历史脏值防御和 JSON 等价字段全部通过。

- [ ] **Step 5: 提交派生状态**

```powershell
git add v2-api/tests/test_state_repository.py v2-api/tests/test_local_simulation.py v2-api/app/services/local_simulation.py v2-api/app/services/state_repository.py
git commit -m "feat: derive construction and review availability"
```

---

### Task 3: 单条优先修改与最后上传原子清除

**Files:**
- Modify: `v2-api/tests/test_state_repository.py`
- Modify: `v2-api/tests/test_api.py`
- Modify: `v2-api/app/services/local_simulation.py`
- Modify: `v2-api/app/services/state_repository.py`
- Modify: `v2-api/app/api/routes/local_test.py`

**Interfaces:**
- Produces repository method: `set_construction_task_priority(task_id: int, *, actor: str, priority: bool) -> dict[str, Any]`。
- Produces route: `PATCH /local-test/construction/tasks/{task_id}/priority`，body `{ "priority": true }`。
- Extends: `upload_construction_group_batch` 在持有 Task 行锁的同一事务内清除最终完成任务的优先值。

- [ ] **Step 1: 写权限、幂等、锁和最终上传失败测试**

在 `test_api.py` 增加管理员/审阅员/施工员矩阵；在 `test_state_repository.py` 增加：

```python
def test_last_construction_upload_clears_priority_in_same_transaction(postgres_repo, seeded_priority_task) -> None:
    task_id, final_group_id = seeded_priority_task
    result = postgres_repo.upload_construction_group_batch(
        final_group_id,
        actor="installer-a",
        client_batch_id="priority-final-upload",
        collector="collector-1",
        module_asset_no="module-1",
        photos=complete_upload_photos(),
    )

    assert result["task"]["construction_available"] is False
    assert result["task"]["construction_priority"] is False
    assert load_task(task_id).construction_priority is False
    assert latest_audit().action == "construction_priority_auto_cleared"
```

另测：重复设置同值不写第二条审计；已完成或零资料组设置 true 返回业务错误；取消 false 幂等成功；领取、释放、改派后未完成任务仍保持 true；回退未施工后不恢复 false。

- [ ] **Step 2: 运行聚焦测试确认 RED**

```powershell
Set-Location v2-api
..\.venv\Scripts\python.exe -m pytest tests\test_state_repository.py tests\test_api.py -k "construction_priority" -q
```

Expected: repository 方法、路由和自动清除审计尚不存在。

- [ ] **Step 3: 实现行锁修改、审计和路由**

PostgreSQL 方法调用 `_task_by_legacy_id(session, task_id, lock=True)`，在锁内重新计算 `_task_stats`；设置 true 时要求 `construction_available`，设置 false 始终允许且幂等。实际变化时写修改人/UTC 时间并用 `_stage_transactional_audit` 记录 action `construction_priority_updated`、任务 ID、终端、修改前后值。JSON 后端用相同校验、字段和 audit event。

路由请求模型必须 `extra="forbid"` 且 `priority: bool`，路由依赖 `require_admin`，actor 只取认证请求，不接受 body 伪造；404 不泄露其他团队同名任务。

- [ ] **Step 4: 在最后上传事务内清除并写系统审计**

在 PostgreSQL `upload_construction_group_batch` 已经取得关联 Task `FOR UPDATE` 后，新增照片并 flush，再用 `_task_stats(session, task)` 计算最新 `total_groups/uploaded_count`。当任务从可施工变成 100% 且 `task.construction_priority` 为 true 时，同一事务设置 false、更新修改人为触发上传的 actor/时间，写 action `construction_priority_auto_cleared`，payload 包含 `uploaded_count` 和 `total_groups`。JSON 后端在 `refresh_task_summary` 后执行等价清除。任何上传异常回滚时，照片和优先值都必须一起回滚。

- [ ] **Step 5: 运行事务、API 和并发回归确认 GREEN**

```powershell
Set-Location v2-api
..\.venv\Scripts\python.exe -m pytest tests\test_state_repository.py tests\test_api.py -k "construction_priority or construction_task_open_claim_and_upload_batch" -q
..\.venv\Scripts\python.exe -m pytest tests\test_round3_postgres_concurrency.py tests\test_round4_postgres_assign_validation.py -q
```

Expected: 全部通过，最后上传与并发单条修改最终都得到完成任务非优先状态。

- [ ] **Step 6: 提交单条修改和自动清除**

```powershell
git add v2-api/tests/test_state_repository.py v2-api/tests/test_api.py v2-api/app/services/local_simulation.py v2-api/app/services/state_repository.py v2-api/app/api/routes/local_test.py
git commit -m "feat: manage and clear construction priority"
```

---

### Task 4: Excel 模板、预览与确认导入

**Files:**
- Create: `v2-api/app/services/construction_priority_import.py`
- Create: `v2-api/tests/test_construction_priority_import.py`
- Modify: `v2-api/tests/test_api.py`
- Modify: `v2-api/app/services/state_repository.py`
- Modify: `v2-api/app/api/routes/local_test.py`

**Interfaces:**
- Produces: `build_priority_template() -> bytes`。
- Produces: `parse_priority_workbook(content: bytes) -> list[PriorityImportRow]`，其中 row 包含 `row_number`、`terminal`、`priority` 和 `status`。
- Produces repository method: `import_construction_priorities(rows, *, actor: str, confirm: bool) -> dict[str, Any]`。
- Produces routes: `GET /local-test/construction/priority-template` 与 `POST /local-test/construction/priority-import?confirm=false|true`。

- [ ] **Step 1: 写模板、去重、冲突和安全限制失败测试**

创建 `test_construction_priority_import.py`，至少覆盖：

```python
def test_priority_template_uses_exact_chinese_headers_and_text_validation() -> None:
    workbook = load_workbook(BytesIO(build_priority_template()), data_only=False)
    sheet = workbook.active
    assert [sheet.cell(1, 1).value, sheet.cell(1, 2).value] == ["终端号", "优先施工"]
    assert sheet["A2"].number_format == "@"
    assert any("是,否" in str(rule.formula1) for rule in sheet.data_validations.dataValidation)


def test_priority_parser_merges_same_values_and_blocks_conflicts() -> None:
    rows = parse_priority_workbook(workbook_bytes([
        ("350000000001", "是"),
        ("350000000001", "是"),
        ("350000000002", "是"),
        ("350000000002", "否"),
    ]))
    assert [row.status for row in rows] == ["valid", "duplicate", "conflict", "conflict"]
```

另测错误表头、空终端、非“是/否”、公式单元格、损坏文件、非 `.xlsx`、超过 2 MiB 和超过 5000 个数据行。

- [ ] **Step 2: 运行解析测试确认 RED**

```powershell
Set-Location v2-api
..\.venv\Scripts\python.exe -m pytest tests\test_construction_priority_import.py -q
```

Expected: 服务模块不存在。

- [ ] **Step 3: 实现无公式执行的纯解析服务**

使用 `openpyxl.load_workbook(BytesIO(content), read_only=False, data_only=False, keep_links=False)`；只读取第一张表和前两列，任意 `cell.data_type == "f"` 记为格式错误。终端号用 `str(value).strip()`，不转 float、不补零、不截断；相同值重复只保留首行有效，出现“是/否”冲突时该终端所有行标记 conflict。模板 A 列设文本格式、B 列加“是,否”下拉。

- [ ] **Step 4: 实现团队内预览/确认事务和审计**

repository 用当前团队一次查询 terminal 映射，分类返回 `valid`、`duplicate`、`conflict`、`unknown`、`completed`、`unchanged`、`malformed` 的 count 和逐行 items。`confirm=false` 不写数据库；`confirm=true` 重新解析后锁定所有有效 Task 行，重新计算完成量，状态变化的任务在一个事务中写入，逐任务记录 `construction_priority_updated`，另写批次 action `construction_priority_imported`。存在 conflict/malformed 时确认返回 `422` 且零写入；确认时变成 100% 的任务改列为 completed 并跳过。

路由限制 `.xlsx`、2 MiB、5000 行，只允许 `require_admin`，模板文件名使用中文可读名和 RFC 兼容 Content-Disposition。

- [ ] **Step 5: 运行导入、权限和团队隔离测试确认 GREEN**

```powershell
Set-Location v2-api
..\.venv\Scripts\python.exe -m pytest tests\test_construction_priority_import.py tests\test_api.py -k "priority_import or priority_template" -q
```

Expected: 所有分类、二阶段重校验、跨团队同名终端、公式/大小/行数限制和管理员权限测试通过。

- [ ] **Step 6: 提交批量导入**

```powershell
git add v2-api/app/services/construction_priority_import.py v2-api/tests/test_construction_priority_import.py v2-api/tests/test_api.py v2-api/app/services/state_repository.py v2-api/app/api/routes/local_test.py
git commit -m "feat: import terminal construction priorities"
```

---

### Task 5: 前端任务类型、四类筛选与状态标签

**Files:**
- Create: `scripts/verify_claim_tasks_construction_priority.js`
- Modify: `v2-web/src/api/types.ts`
- Modify: `v2-web/src/api/services.ts`
- Modify: `v2-web/src/views/ClaimTasksView.vue`

**Interfaces:**
- Consumes backend fields: `construction_priority`、`construction_available`、`review_available`。
- Produces frontend fields: `constructionPriority`、`constructionAvailable`、`reviewAvailable`。
- Produces filter type: `'all' | 'priority' | 'construction' | 'review'`。

- [ ] **Step 1: 写字段映射、筛选和标签失败验证**

创建 `scripts/verify_claim_tasks_construction_priority.js`：

```javascript
import assert from 'node:assert/strict'
import fs from 'node:fs'

const view = fs.readFileSync('v2-web/src/views/ClaimTasksView.vue', 'utf8')
const services = fs.readFileSync('v2-web/src/api/services.ts', 'utf8')
assert.match(services, /constructionPriority:\s*Boolean\(raw\.construction_priority\)/)
assert.match(services, /constructionAvailable:\s*Boolean\(raw\.construction_available\)/)
assert.match(services, /reviewAvailable:\s*Boolean\(raw\.review_available\)/)
for (const label of ['全部', '优先施工', '可施工', '可领取审阅']) assert.ok(view.includes(label))
assert.match(view, /task\.constructionPriority/)
assert.match(view, /task\.constructionAvailable/)
assert.match(view, /task\.reviewAvailable/)
assert.doesNotMatch(view, /constructionAvailable\s*=\s*computed/)
console.log('Claim task construction priority verification passed.')
```

- [ ] **Step 2: 运行验证确认 RED**

```powershell
node scripts\verify_claim_tasks_construction_priority.js
```

Expected: 新字段和筛选不存在。

- [ ] **Step 3: 映射服务端字段并实现服务端状态筛选**

`ReviewTask` 与 `BackendTask` 增加三个布尔字段，`mapTask` 直接映射。`ClaimTasksView.vue` 用 Element Plus segmented/radio button 控件显示四个筛选；筛选只读取三个新字段。`priority` 只匹配 `constructionPriority`，`construction` 只匹配 `constructionAvailable`，`review` 只匹配 `reviewAvailable`。审阅员原有权限过滤继续要求待审任务，不因新筛选获得施工指派权限。

在“全部”和“可施工”中先按 `constructionPriority` true 排序，再保持现有同级排序；其他筛选保持现有排序。卡片按字段显示三个紧凑标签，100% 响应因服务端字段为 false 不显示优先与可施工。

- [ ] **Step 4: 增加管理员单条菜单并更新缓存**

`TaskMoreAction` 增加 `set-priority`/`clear-priority`，仅管理员、`constructionAvailable=true` 且未完成任务显示入口。`services.ts` 增加：

```ts
export async function setConstructionTaskPriority(taskId: string, priority: boolean): Promise<ReviewTask>
```

成功后替换 `tasks` 中对应项、清空 `taskStatusVersion`、调用 `rememberCachedTasks('')`；失败保持原卡片不变。领取、释放和改派返回的新 task payload 同样通过 mapTask 保留标识。

- [ ] **Step 5: 运行验证和前端构建确认 GREEN**

```powershell
node scripts\verify_claim_tasks_construction_priority.js
node scripts\verify_claim_tasks_completion_status.js
Set-Location v2-web
npm run build
```

Expected: 两个验证通过，TypeScript 与 Vite 构建成功。

- [ ] **Step 6: 提交筛选、标签和单条菜单**

```powershell
git add scripts/verify_claim_tasks_construction_priority.js v2-web/src/api/types.ts v2-web/src/api/services.ts v2-web/src/views/ClaimTasksView.vue
git commit -m "feat: filter and label construction-ready tasks"
```

---

### Task 6: 管理员批量标记弹窗

**Files:**
- Create: `v2-web/src/components/ConstructionPriorityImportDialog.vue`
- Create: `scripts/verify_construction_priority_import_dialog.js`
- Modify: `v2-web/src/api/types.ts`
- Modify: `v2-web/src/api/services.ts`
- Modify: `v2-web/src/views/ClaimTasksView.vue`

**Interfaces:**
- Consumes: 模板下载、`confirm=false` 预览、`confirm=true` 确认 API。
- Produces emit: `imported: []`，由父页面强制刷新任务和状态版本。
- Pagination: `pageSize = 20`，分页对象只作用于预览 items，不重新请求或重复解析文件。

- [ ] **Step 1: 写弹窗完整流程和 20 条分页失败验证**

创建 `scripts/verify_construction_priority_import_dialog.js`：

```javascript
import assert from 'node:assert/strict'
import fs from 'node:fs'

const dialog = fs.readFileSync('v2-web/src/components/ConstructionPriorityImportDialog.vue', 'utf8')
const view = fs.readFileSync('v2-web/src/views/ClaimTasksView.vue', 'utf8')
assert.match(dialog, /const pageSize = 20/)
assert.match(dialog, /downloadConstructionPriorityTemplate/)
assert.match(dialog, /previewConstructionPriorityImport/)
assert.match(dialog, /confirmConstructionPriorityImport/)
assert.match(dialog, /valid|duplicate|conflict|unknown|completed|unchanged|malformed/)
assert.match(dialog, /ElPagination|el-pagination/)
assert.match(view, /ConstructionPriorityImportDialog/)
assert.match(view, /批量标记/)
console.log('Construction priority import dialog verification passed.')
```

- [ ] **Step 2: 运行验证确认 RED**

```powershell
node scripts\verify_construction_priority_import_dialog.js
```

Expected: 弹窗文件不存在。

- [ ] **Step 3: 实现两阶段文件弹窗**

弹窗仅管理员入口可见，包含图标模板下载按钮、`.xlsx` 文件选择、预览统计、20 条分页明细和确认按钮。浏览器保留同一 `File` 对象；预览和确认分别重新构造 `FormData`。存在 conflict/malformed 或尚未预览时禁用确认。关闭弹窗清空文件、预览、分页和错误；上传失败不自动重试。明细横向展示行号、终端号、目标值、分类和原因，不添加解释性页面文字。

- [ ] **Step 4: 接入工具栏与导入后缓存失效**

任务页工具栏增加“批量标记”按钮和弹窗，不跳转新页面。收到 `imported` 后关闭弹窗并执行 `loadTasks({ force: true })`，清理当前 sessionStorage 任务缓存。非管理员不渲染按钮，直接调用接口仍由后端返回 `403`。

- [ ] **Step 5: 运行弹窗验证和前端构建确认 GREEN**

```powershell
node scripts\verify_construction_priority_import_dialog.js
node scripts\verify_claim_tasks_construction_priority.js
Set-Location v2-web
npm run build
```

Expected: 验证与构建通过。

- [ ] **Step 6: 提交批量弹窗**

```powershell
git add v2-web/src/components/ConstructionPriorityImportDialog.vue scripts/verify_construction_priority_import_dialog.js v2-web/src/api/types.ts v2-web/src/api/services.ts v2-web/src/views/ClaimTasksView.vue
git commit -m "feat: add priority batch import dialog"
```

---

### Task 7: V3.0.83 联合版本、验证与发布证据

**Files:**
- Create: `ops/releases/V3.0.83.md`
- Modify: `v2-web/src/version.json`
- Modify: `v2-web/package.json`
- Modify: `v2-web/index.html`
- Modify: `v2-web/src/components/AppLayout.vue`
- Modify: `v2-web/src/constants/releaseNotes.ts`
- Modify: `v2-api/pyproject.toml`
- Modify: `v2-api/app/main.py`
- Modify: `v2-api/app/services/ops_status.py`
- Modify: `v2-api/tests/test_api.py`
- Modify: `scripts/build-client-release.ps1`
- Modify: `scripts/test_verify_client_release.py`
- Modify: `scripts/test_verify_release_sop.py`
- Modify: `scripts/verify_release_sop.py`
- Modify: `AGENTS.md`
- Modify: `RELEASE_MANIFEST.md`

**Interfaces:**
- Produces application version `3.0.83` / display version `V3.0.83`。
- Produces Chinese release note entries for 图片框选识别/局部放大 and 终端优先施工/可施工筛选。
- Produces release package `build/server-release/module-manager-v2-server-3.0.83.zip` and SHA256 evidence。

- [ ] **Step 1: 先更新版本门禁测试到 3.0.83 并确认 RED**

把版本断言从 `3.0.82` 改为 `3.0.83`，发布生命周期基线写为 deployed `V3.0.82`、candidate `V3.0.83`，新增发布记录必含两个中文功能标题的断言：

```powershell
.\.venv\Scripts\python.exe -m pytest scripts\test_verify_client_release.py scripts\test_verify_release_sop.py -q
node scripts\verify_admin_release_notes.js
```

Expected: 应用、文档和构建脚本仍为 3.0.82，测试失败。

- [ ] **Step 2: 更新所有生产版本来源和中文更新内容**

统一改为 `3.0.83`，在 `releaseNotes.ts` 顶部增加 `V3.0.83` 中文条目，内容明确：桌面审阅图片支持局部放大和人工分类框选识别；管理员支持优先施工单条/批量标记及全部/优先施工/可施工/可领取审阅筛选；100% 上传自动清除优先标识。更新 `AGENTS.md` 发布候选但保留已部署基线 `V3.0.82`，创建发布记录并将部署后字段先标记 pending。

- [ ] **Step 3: 运行完整功能和发布门禁**

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests -q
.\.venv\Scripts\python.exe -m pytest scripts\test_verify_client_release.py scripts\test_verify_release_sop.py -q
node scripts\verify_review_image_inspector.js
node scripts\verify_task_hall_region_scan.js
node scripts\verify_project_board_unmatched_review.js
node scripts\verify_claim_tasks_construction_priority.js
node scripts\verify_construction_priority_import_dialog.js
node scripts\verify_claim_tasks_completion_status.js
node scripts\verify_admin_release_notes.js
Set-Location v2-web
npm run build
Set-Location ..
.\.venv\Scripts\python.exe scripts\verify_security_hardening.py
.\.venv\Scripts\python.exe scripts\verify_release_sop.py
```

Expected: 后端全量、所有 Node 验证、TypeScript/Vite、安全与发布 SOP 全部通过。

- [ ] **Step 4: 做管理员桌面浏览器验收**

在任务领取页验证四个筛选、三个标签、优先排序、单条设置/取消、模板下载、批量预览 20 条分页、冲突禁用确认和成功导入。领取/释放/改派后标识保持；把一个优先任务完成最后一组上传，确认“优先施工/可施工”立即消失而“可领取审阅”按未审数量保留。与图片框选计划 Task 5 一起完成两个审阅入口的桌面验收；控制台无错误、请求无重复提交。

- [ ] **Step 5: 独立只读审阅并清零阻断项**

对 `f4b703d..HEAD` 生成完整 review package，交给无本线程实现记忆的独立 reviewer。要求输出 Critical/Important/Minor；任何 Critical 或 Important 都必须修复、运行覆盖测试并重新审阅，直到 `Critical=0`、`Important=0`。把最终结论写入 `ops/releases/V3.0.83.md`。

- [ ] **Step 6: 构建发布包并记录哈希**

```powershell
.\scripts\build-client-release.ps1 -Version 3.0.83
Get-FileHash build\server-release\module-manager-v2-server-3.0.83.zip -Algorithm SHA256
.\.venv\Scripts\python.exe scripts\verify-client-release.py build\server-release\module-manager-v2-server-3.0.83.zip --version 3.0.83
```

Expected: 包验证通过；将实际 SHA256 写入 `RELEASE_MANIFEST.md` 与 `ops/releases/V3.0.83.md`，不得预填或猜测。

- [ ] **Step 7: 提交联合发布候选**

```powershell
git add AGENTS.md RELEASE_MANIFEST.md ops/releases/V3.0.83.md v2-web v2-api scripts
git commit -m "release: prepare V3.0.83 production package"
```

---

### Task 8: GitHub 同步与生产上线

**Files:**
- Modify: `ops/releases/V3.0.83.md`
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: 已验证包 `build/server-release/module-manager-v2-server-3.0.83.zip`、SSH key `C:\Users\Administrator\Downloads\XXXXXX.pem`。
- Produces: GitHub branch `production/V3/3.0.83`、tag `V3.0.83`、生产 release `/opt/module-manager-v2/releases/v3.0.83-<timestamp>`。
- Rollback target: 部署前 `readlink -f /opt/module-manager-v2/current` 的实际目录。

- [ ] **Step 1: 创建并推送独立生产版本分支**

在当前已验证提交上创建分支，不合并开发环境分支：

```powershell
git switch -c production/V3/3.0.83
git push -u origin production/V3/3.0.83
```

Expected: GitHub 生产分支指向本地已审阅的 release candidate commit；正式 tag 在生产证据回填后一次性创建。

- [ ] **Step 2: 上传包并校验服务器哈希**

```powershell
$key = 'C:\Users\Administrator\Downloads\XXXXXX.pem'
scp -i $key build\server-release\module-manager-v2-server-3.0.83.zip root@106.14.122.43:/tmp/module-manager-v2-server-3.0.83.zip
ssh -i $key root@106.14.122.43 "sha256sum /tmp/module-manager-v2-server-3.0.83.zip"
```

Expected: 服务器 SHA256 与 `RELEASE_MANIFEST.md` 完全一致，不一致则停止上线并删除服务器临时包。

- [ ] **Step 3: 执行全量生产备份并验证清单**

```powershell
ssh -i $key root@106.14.122.43 "set -euo pipefail; bash /opt/module-manager-v2/current/scripts/production_backup.sh /opt/module-manager-v2 V3.0.83"
```

记录输出的 `BACKUP_DIR`，确认其中存在 `.env`、`database.dump`、`database-schema.sql`、`data.tar.gz`、`uploads.tar.gz`、`current_release.tar.gz`、`current_release.txt` 和 `SHA256SUMS`，并在服务器目录执行 `sha256sum -c SHA256SUMS`。任一文件缺失或校验失败立即停止。

- [ ] **Step 4: 解包、复制环境并先执行数据库迁移**

```powershell
ssh -i $key root@106.14.122.43 @'
set -euo pipefail
APP_ROOT=/opt/module-manager-v2
STAMP=$(date +%Y%m%d_%H%M%S)
RELEASE_DIR="$APP_ROOT/releases/v3.0.83-$STAMP"
mkdir -p "$RELEASE_DIR"
unzip -q /tmp/module-manager-v2-server-3.0.83.zip -d "$RELEASE_DIR"
cp -a "$APP_ROOT/.env" "$RELEASE_DIR/.env"
cd "$RELEASE_DIR/v2-api"
/opt/module-manager-v2/venv/bin/alembic upgrade head
printf '%s\n' "$RELEASE_DIR"
'@
```

Expected: Alembic head 为 `20260721_0005`，迁移成功后 `tasks` 表三列存在；迁移失败时不切换 current。

- [ ] **Step 5: 原子切换 release 并做服务健康检查**

```powershell
ssh -i $key root@106.14.122.43 @'
set -euo pipefail
APP_ROOT=/opt/module-manager-v2
RELEASE_DIR=$(find "$APP_ROOT/releases" -maxdepth 1 -type d -name 'v3.0.83-*' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)
ln -sfn "$RELEASE_DIR" "$APP_ROOT/current"
systemctl restart module-manager-v2.service
systemctl is-active --quiet module-manager-v2.service
nginx -t
systemctl is-active --quiet nginx
curl -fsS http://127.0.0.1:8000/health
'@
```

随后本机验证 `https://www.sgcc.online/health`、`/login`、`/project-board`、`/task-hall`、`/construction` 返回 `200`，版本 API 为 `3.0.83`，`/docs`、`/redoc`、`/openapi.json` 仍为 `404`。

- [ ] **Step 6: 线上 API 和功能抽样验收**

用生产管理员会话确认：任务列表返回三个新字段；优先施工单条设置/取消与模板下载可用；批量预览不写数据；正常/未匹配区域识别路由可返回空或候选但不改变扫码状态。选择一个未完成测试终端完成设置后立即取消，不遗留测试优先值。检查 `journalctl -u module-manager-v2.service --since` 和 Nginx error log，无新 traceback、5xx 或持续 CPU 峰值。

- [ ] **Step 7: dry-run 后只保留最近五个服务器 release**

```powershell
ssh -i $key root@106.14.122.43 "set -euo pipefail; bash /opt/module-manager-v2/current/scripts/cleanup_old_releases.sh /opt/module-manager-v2 5 --dry-run"
ssh -i $key root@106.14.122.43 "set -euo pipefail; bash /opt/module-manager-v2/current/scripts/cleanup_old_releases.sh /opt/module-manager-v2 5"
ssh -i $key root@106.14.122.43 "find /opt/module-manager-v2/releases -mindepth 1 -maxdepth 1 -type d -printf '%T@ %f\n' | sort -nr"
```

Expected: current V3.0.83 保留，release 目录总数为 5；GitHub 中的旧 tag/分支不删除。

- [ ] **Step 8: 回填生产证据并完成发布生命周期**

把备份目录、release 目录、回滚目录、包/服务器 SHA256、迁移 head、测试数量、线上页面/API、服务状态、日志和五版本清单写入 `ops/releases/V3.0.83.md`。将 `AGENTS.md` 的 deployed baseline/candidate 同步为 `V3.0.83`，重新运行发布 SOP，提交并推送：

```powershell
.\.venv\Scripts\python.exe scripts\verify_release_sop.py
git add AGENTS.md ops/releases/V3.0.83.md RELEASE_MANIFEST.md
git commit -m "docs: finalize V3.0.83 production lifecycle"
git push origin production/V3/3.0.83
git tag -a V3.0.83 -m "V3.0.83 production release"
git push origin V3.0.83
```

Expected: 远端生产分支和 tag 指向最终生命周期提交，发布记录状态为 deployed and verified。
