# Task Dispatch Terminal Material Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有任务派发页面增加管理员终端资料导出，以项目级模块唯一校验、持久化采集器一对一分配、OSS 内网限速流式中转和浏览器本地断点写入完成交付。

**Architecture:** 后端新增独立的 `material_exports` API、纯领域校验模块、PostgreSQL 导出任务/终端/分配/文件/租约模型，复用现有 `terminal_review` 已施工证据投影、`data_center.group_anomalies()`、项目级 `PhysicalCollector`/`CollectorPhoto` 和 `photo_storage.require_oss_client()`。前端不新增路由，在 `ClaimTasksView.vue` 中异步加载轻量导出摘要，用 File System Access API、IndexedDB、增量 SHA256 和客户端 Excel 生成器逐文件写入本地目录；旧 `/exports`、ZIP 和 delivery worker 保持退休。

**Tech Stack:** FastAPI、Pydantic、SQLAlchemy 2、PostgreSQL、Alembic、oss2、pytest、Vue 3、TypeScript、Element Plus、Vitest、File System Access API、IndexedDB、ExcelJS 4.4.0、hash-wasm 4.12.0、PowerShell 发布工具、SSH/systemd/Nginx。

**Spec:** `docs/superpowers/specs/2026-09-01-task-dispatch-terminal-material-export-design.md`

## Global Constraints

- 只校验、只导出当前项目内有效且已施工的表计业务资料组；未施工资料不计异常、不计采集器需求、不生成任何文件。
- 模块唯一性按当前项目全部有效已施工资料组校验：模块号只能出现于一个资料组，同一表号只能对应一个不同模块号。
- 校验单位是资料组，不是照片；同一资料组的两张照片不得误判为模块重复。
- 表号、模块号、总清单地址、“模块与电能表”和“改造后”是表计导出的必需项。
- 采集器照片缺失不算异常、不阻止导出；有号码无照片时只省略图片。
- 最终采集器数量固定为 `max(已施工采集器号去重数量, 管理员填写数量)`。
- 同号实物优先，缺口从当前项目可用池随机补齐；有效分配一对一，失败保留预留，重复导出复用原分配。
- 池不足或正式锁定并发冲突时整批不产生任何新分配，也不开始下载。
- 每个终端生成模块目录、`采集器/`、`终端资料.xlsx`，仅有额外采集器时生成 `补充采集器.xlsx`；不生成采集器清单或 ZIP。
- 服务端只通过 OSS 内网端点串行读取单个对象，以 `250000` bytes/s（约 `2 Mbps`）限速流式中转，不落盘、不缓存完整照片。
- 全系统只允许一个下载租约；暂停或断线释放租约，但不释放采集器预留。
- 仅最新版 Windows Chrome/Edge 可正式导出；施工员看不到控件且所有新接口后端强制管理员鉴权。
- 旧 `/exports`、旧导出中心、最终交付包和 delivery worker 必须继续返回/遵守退休契约。
- 文档计划不提升版本。实施若仍基于 `V3.2.26`，应用版本提升至 `V3.2.27`；若基线先推进，则使用当时 patch `+0.0.1`。
- 数据库迁移、生产备份、迁移 dry-run、回滚和真实 3 Mbps 验收完成前不得发布。

---

## File Structure

- `v2-api/app/domain/material_export.py`: 已施工表计投影、项目级模块冲突、需求数量、文件名和预检指纹的纯函数。
- `v2-api/app/domain/terminal_review.py`: 仅增加公开的单资料组已施工判断入口，内部仍使用现有 `_has_construction_evidence` 规则。
- `v2-api/app/models.py`: 导出设置、任务、终端、持久化采集器分配、文件和全局租约模型。
- `v2-api/alembic/versions/0017_material_exports.py`: 前向迁移、约束、局部唯一索引和回滚保护。
- `v2-api/app/services/material_export.py`: 项目证据读取、预检、同号/池分配、稳定照片来源、清单、状态、释放和审计。
- `v2-api/app/services/material_export_stream.py`: OSS HEAD、内网读取、令牌桶限速、流完成/断开回调。
- `v2-api/app/api/schemas/material_export.py`: 严格请求/响应 DTO。
- `v2-api/app/api/routes/material_exports.py`: 管理员接口、稳定中文错误和 `StreamingResponse`。
- `v2-api/app/api/router.py`: 注册 `/material-exports`，不触碰旧 `/exports`。
- `v2-api/app/core/config.py`: `250000` bytes/s、`65536` 字节 chunk、`90` 秒租约配置。
- `v2-api/tests/test_material_export_domain.py`: 未施工、重复、一表多模块、需求和命名纯测试。
- `v2-api/tests/test_material_export_models.py`: 模型约束和 Alembic head 测试。
- `v2-api/tests/test_material_export_service.py`: PostgreSQL 预检、分配、复用、释放、清单和审计测试。
- `v2-api/tests/test_material_export_api.py`: 权限、项目隔离、DTO、状态和错误合同测试。
- `v2-api/tests/test_material_export_stream.py`: OSS 内网、限速、断线、SHA/长度和不落盘测试。
- `v2-web/src/api/types.ts`: 导出摘要、预检、清单、文件和状态类型。
- `v2-web/src/api/services.ts`: 导出 JSON 接口和原始文件流客户端。
- `v2-web/src/features/materialExport/state.ts`: 卡片排序、选择、中文状态和状态机纯函数。
- `v2-web/src/features/materialExport/checkpoint.ts`: IndexedDB 任务/目录句柄/文件校验点。
- `v2-web/src/features/materialExport/fileSystem.ts`: 安全目录名、递归目录、流式写入和增量 SHA256。
- `v2-web/src/features/materialExport/workbooks.ts`: 两种 Excel 的客户端生成。
- `v2-web/src/features/materialExport/runner.ts`: 单任务、单终端、单文件串行执行与暂停恢复。
- `v2-web/src/features/materialExport/useMaterialExport.ts`: 页面组合状态和 API 调度。
- `v2-web/src/components/material-export/MaterialExportToolbar.vue`: 顶部选择/批量导出/紧凑进度。
- `v2-web/src/components/material-export/MaterialExportCardControls.vue`: 卡片勾选、数量和单终端按钮。
- `v2-web/src/views/ClaimTasksView.vue`: 只组合现有任务派发 UI 与上述两个组件，不新增系统或路由。
- `v2-web/src/types/file-system-access.d.ts`: 受控浏览器 API 类型声明。
- `v2-web/src/features/materialExport/__tests__/*.spec.ts`: 状态、目录、Excel、断点和 runner 单元测试。
- `v2-web/src/views/__tests__/ClaimTasksMaterialExport.spec.ts`: 管理员/施工员和页面集成测试。
- `scripts/verify_material_export_gate.py`: 旧导出退休、无 ZIP/落盘、限速/权限/路由静态门禁。
- `ops/releases/V3.2.27.md`: 实施完成后的候选、备份、迁移、验证、生产和回滚证据。

### Task 1: Add pure export eligibility, module integrity, demand, and naming rules

**Files:**
- Create: `v2-api/app/domain/material_export.py`
- Modify: `v2-api/app/domain/terminal_review.py:51-96,373-440`
- Create: `v2-api/tests/test_material_export_domain.py`
- Modify: `v2-api/tests/test_terminal_review_domain.py`

**Interfaces:**
- Consumes: `ReviewMeterEvidence`, existing `_has_construction_evidence`, `MeterSource`, `normalize_identifier`.
- Produces: `is_constructed_evidence(evidence) -> bool`, `MaterialExportMeter`, `MaterialExportIssue`, `CollectorDemand`, `project_module_issues(meters)`, `required_meter_issues(meter)`, `collector_demand(meters, requested_count)`, `safe_windows_component(value)`, `preflight_fingerprint(payload)`.

- [ ] **Step 1: Write failing construction and project-level integrity tests**

```python
def test_unconstructed_rows_do_not_participate_in_module_conflicts() -> None:
    meters = (
        export_meter(group_id="g-1", terminal="T-1", meter_no="M-1", module_no="MOD-1", constructed=True),
        export_meter(group_id="g-2", terminal="T-2", meter_no="M-2", module_no="MOD-1", constructed=False),
    )
    assert project_module_issues(meters) == ()

def test_duplicate_module_blocks_every_constructed_terminal() -> None:
    meters = (
        export_meter(group_id="g-1", terminal="T-1", meter_no="M-1", module_no="MOD-1", constructed=True),
        export_meter(group_id="g-2", terminal="T-2", meter_no="M-2", module_no="MOD-1", constructed=True),
    )
    issues = project_module_issues(meters)
    assert {issue.terminal_code for issue in issues} == {"T-1", "T-2"}
    assert all(issue.code == "duplicate_module" for issue in issues)
    assert "MOD-1" in issues[0].message

def test_one_meter_many_modules_blocks_all_related_terminals() -> None:
    meters = (
        export_meter(group_id="g-1", terminal="T-1", meter_no="M-1", module_no="MOD-1", constructed=True),
        export_meter(group_id="g-2", terminal="T-2", meter_no="M-1", module_no="MOD-2", constructed=True),
    )
    issues = project_module_issues(meters)
    assert {issue.code for issue in issues} == {"meter_multiple_modules"}
    assert "MOD-1、MOD-2" in issues[0].message
```

- [ ] **Step 2: Run the new domain tests and verify RED**

```powershell
.venv\Scripts\python.exe -m pytest v2-api/tests/test_material_export_domain.py -q
```

Expected: collection fails because `app.domain.material_export` does not exist.

- [ ] **Step 3: Implement the exact immutable domain types and normalization**

```python
@dataclass(frozen=True, slots=True)
class MaterialExportMeter:
    group_id: str
    task_id: str
    terminal_code: str
    meter_no: str
    module_no: str
    collector_no: str
    installation_address: str
    module_meter_photo_id: str | None
    after_box_photo_id: str | None
    constructed: bool
    open_module_anomalies: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class MaterialExportIssue:
    code: str
    terminal_code: str
    group_ids: tuple[str, ...]
    meter_nos: tuple[str, ...]
    module_nos: tuple[str, ...]
    message: str

@dataclass(frozen=True, slots=True)
class CollectorDemand:
    source_collector_nos: tuple[str, ...]
    final_count: int
    extra_count: int

def is_constructed_evidence(evidence: ReviewMeterEvidence) -> bool:
    return _has_construction_evidence(evidence)
```

`project_module_issues()` must filter `constructed=True`, compare identifiers after `NFKC + strip`, group by logical资料组 rather than photo, emit one deterministic issue per affected terminal, and preserve original numbers in Chinese messages. Exact duplicate photo slots inside one `group_id` never create an issue.

- [ ] **Step 4: Add failing demand, required-field, filename, and fingerprint tests**

```python
def test_collector_demand_uses_max_and_deduplicates_constructed_numbers() -> None:
    meters = (
        export_meter(group_id="g-1", terminal="T-1", collector_no="C-1", constructed=True),
        export_meter(group_id="g-2", terminal="T-1", collector_no="C-1", constructed=True),
        export_meter(group_id="g-3", terminal="T-1", collector_no="C-2", constructed=True),
        export_meter(group_id="g-4", terminal="T-1", collector_no="C-9", constructed=False),
    )
    demand = collector_demand(meters, requested_count=4)
    assert demand.source_collector_nos == ("C-1", "C-2")
    assert demand.final_count == 4
    assert demand.extra_count == 2

def test_collector_photo_is_not_a_required_meter_field() -> None:
    meter = export_meter(module_meter_photo_id="p-1", after_box_photo_id="p-2", constructed=True)
    assert required_meter_issues(meter) == ()

def test_windows_component_is_safe_and_stable() -> None:
    assert safe_windows_component(' MOD:01/02 ') == 'MOD：01／02'
    assert safe_windows_component('CON') == 'CON_'
    assert safe_windows_component('...') == '_'

def test_preflight_fingerprint_is_order_stable_and_change_sensitive() -> None:
    assert preflight_fingerprint([{"id": "2"}, {"id": "1"}]) == preflight_fingerprint([{"id": "1"}, {"id": "2"}])
    assert preflight_fingerprint([{"id": "1"}]) != preflight_fingerprint([{"id": "1", "sha256": "changed"}])
```

- [ ] **Step 5: Implement the minimal deterministic functions**

```python
def collector_demand(meters: Iterable[MaterialExportMeter], requested_count: int) -> CollectorDemand:
    source = tuple(sorted({normalize_business_no(item.collector_no) for item in meters if item.constructed and normalize_business_no(item.collector_no)}))
    final_count = max(len(source), max(0, int(requested_count)))
    return CollectorDemand(source_collector_nos=source, final_count=final_count, extra_count=final_count - len(source))

def preflight_fingerprint(rows: Iterable[Mapping[str, object]]) -> str:
    canonical = sorted((dict(row) for row in rows), key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
```

Implement `required_meter_issues()` for meter/module/address/two slots only, and `safe_windows_component()` with Windows invalid characters, trailing dot/space, reserved device names, blank fallback, and a 120-character component cap.

- [ ] **Step 6: Verify GREEN and commit**

```powershell
.venv\Scripts\python.exe -m pytest v2-api/tests/test_material_export_domain.py v2-api/tests/test_terminal_review_domain.py -q
git add -- v2-api/app/domain/material_export.py v2-api/app/domain/terminal_review.py v2-api/tests/test_material_export_domain.py v2-api/tests/test_terminal_review_domain.py
git commit --only -m "feat: define terminal material export rules" -- v2-api/app/domain/material_export.py v2-api/app/domain/terminal_review.py v2-api/tests/test_material_export_domain.py v2-api/tests/test_terminal_review_domain.py
```

### Task 2: Add forward-only export persistence and database constraints

**Files:**
- Modify: `v2-api/app/models.py:590-980`
- Create: `v2-api/alembic/versions/0017_material_exports.py`
- Create: `v2-api/tests/test_material_export_models.py`
- Modify: `v2-api/tests/test_models.py`
- Modify: `v2-api/tests/test_migrations.py`
- Modify: `v2-api/tests/test_postgres_migration.py`

**Interfaces:**
- Consumes: `Task`, `Project`, `PhysicalCollector`, `CollectorAssignment`, `Photo`, `CollectorPhoto`, `AuditLog`.
- Produces: `TerminalExportSetting`, `MaterialExportJob`, `MaterialExportTerminal`, `MaterialExportCollectorAllocation`, `MaterialExportFile`, `MaterialExportLease`.

- [ ] **Step 1: Write failing model-contract tests**

```python
def test_material_export_models_have_required_uniqueness_and_checks() -> None:
    setting = TerminalExportSetting.__table__
    allocation = MaterialExportCollectorAllocation.__table__
    assert {column.name for column in setting.primary_key.columns} == {"id"}
    assert any(constraint.name == "uq_terminal_export_settings_team_project_task" for constraint in setting.constraints)
    assert any(index.name == "uq_material_export_allocations_active_requirement" for index in allocation.indexes)
    assert any(index.name == "uq_material_export_allocations_active_physical" for index in allocation.indexes)

def test_collector_photo_is_optional_for_export_allocation() -> None:
    assert MaterialExportCollectorAllocation.__table__.c.collector_photo_id.nullable is True
    assert MaterialExportCollectorAllocation.__table__.c.group_photo_id.nullable is True
```

- [ ] **Step 2: Run model tests and verify RED**

```powershell
.venv\Scripts\python.exe -m pytest v2-api/tests/test_material_export_models.py -q
```

Expected: import fails because the six models do not exist.

- [ ] **Step 3: Add the exact model boundaries**

Implement these tables and constraints in `models.py`:

```python
class TerminalExportSetting(Base, TimestampMixin):
    __tablename__ = "terminal_export_settings"
    id: Mapped[uuid.UUID] = uuid_column()
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    terminal_code: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_collector_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_by_username: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default=text("''"))

class MaterialExportJob(Base, TimestampMixin):
    __tablename__ = "material_export_jobs"
    id: Mapped[uuid.UUID] = uuid_column()
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="reserved")
    preflight_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_by_username: Mapped[str] = mapped_column(String(64), nullable=False)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    diagnostics: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
```

Add `MaterialExportTerminal` with job/task/team/project/terminal, statuses from the spec, requested/source/final counts, immutable `source_revision`, `manifest_json`, diagnostics and unique `(job_id, task_id)`. Add `MaterialExportCollectorAllocation` with `requirement_key`, optional `original_collector_no`, physical collector, optional existing `source_assignment_id`, optional `collector_photo_id`/`group_photo_id`, `allocation_mode`, `photo_source_kind`, `prior_pool_status`, status, creator/releaser timestamps and the two active partial unique indexes. Add `MaterialExportFile` with one of `source_photo_id`/`source_collector_photo_id` or `source_kind='client_workbook'`, immutable storage snapshot, relative path, content type, state and retry fields. Photo file size/SHA256 is non-null at creation; client workbook size/SHA256 is nullable until the first acknowledgement fixes it. Add singleton `MaterialExportLease(scope='global-download')` with job, owner token, heartbeat and expiry.

Every status and source kind gets a named `CheckConstraint`. Add project/task lookup indexes and prevent negative counts. Do not change nullability or behavior of existing `CollectorAssignment.collector_photo_id`.

- [ ] **Step 4: Write the forward-only Alembic migration**

Create revision `20260901_0017`, down revision `20260824_0016`. The upgrade must create all six tables, foreign keys, checks, normal indexes and PostgreSQL partial unique indexes. Use this exact active predicate for allocations:

```sql
status IN ('reserved', 'used')
```

The migration must contain no update/delete of `material_groups`, `photos`, collector inventory, assignments, anomalies or OSS references. `downgrade()` raises `RuntimeError("material export persistence is forward-only")`.

- [ ] **Step 5: Verify migration and constraints against PostgreSQL**

```powershell
.venv\Scripts\python.exe -m pytest v2-api/tests/test_material_export_models.py v2-api/tests/test_models.py v2-api/tests/test_migrations.py v2-api/tests/test_postgres_migration.py -q
```

Expected: all tests pass; Alembic head is `20260901_0017`; duplicate active requirement/physical inserts fail; released rows allow a new active allocation.

- [ ] **Step 6: Commit the schema slice**

```powershell
git add -- v2-api/app/models.py v2-api/alembic/versions/0017_material_exports.py v2-api/tests/test_material_export_models.py v2-api/tests/test_models.py v2-api/tests/test_migrations.py v2-api/tests/test_postgres_migration.py
git commit --only -m "feat: persist material export reservations" -- v2-api/app/models.py v2-api/alembic/versions/0017_material_exports.py v2-api/tests/test_material_export_models.py v2-api/tests/test_models.py v2-api/tests/test_migrations.py v2-api/tests/test_postgres_migration.py
```

### Task 3: Build project-scoped evidence loading, settings, and preflight

**Files:**
- Create: `v2-api/app/services/material_export.py`
- Modify: `v2-api/app/services/state_repository.py:1080-1342`
- Create: `v2-api/tests/test_material_export_service.py`
- Modify: `v2-api/tests/test_state_repository.py`

**Interfaces:**
- Consumes: Task 1 domain functions, `project_terminal_review` photo precedence, `group_anomalies`, `MaterialGroup`, `Photo`, `TotalCatalogRow`, `Task`.
- Produces: `PostgresMaterialExportService.list_terminal_summaries(task_ids)`, `set_requested_collector_count(task_id, count)`, `preflight(task_ids) -> MaterialExportPreflight`.

- [ ] **Step 1: Write failing project evidence tests**

Seed one fully constructed group, one unconstructed group sharing a module number, one constructed duplicate in another terminal, one one-meter-two-module pair, closed/open module anomalies, and collector-photo absence. Assert:

```python
preflight = service.preflight(task_ids=[str(task_a.id), str(task_b.id)])
assert preflight.terminals[str(task_a.id)].constructed_meter_count == 2
assert "unconstructed-group" not in preflight.source_group_ids
assert {issue.code for issue in preflight.terminals[str(task_a.id)].issues} >= {"duplicate_module", "meter_multiple_modules"}
assert all(issue.code != "missing_collector_photo" for terminal in preflight.terminals.values() for issue in terminal.issues)
assert preflight.terminals[str(task_b.id)].can_export is False
```

Add a regression proving two required photo rows in one资料组 do not create a duplicate-module issue and the address comes from `TotalCatalogRow`, not conflicting raw data.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
.venv\Scripts\python.exe -m pytest v2-api/tests/test_material_export_service.py -q -k "preflight or evidence"
```

- [ ] **Step 3: Implement bounded selected-column evidence loading**

Add:

```python
class MaterialExportError(RuntimeError):
    code = "material_export_error"

class MaterialExportProjectMismatch(MaterialExportError):
    code = "project_mismatch"

class MaterialExportSnapshotChanged(MaterialExportError):
    code = "snapshot_changed"

@dataclass(frozen=True, slots=True)
class MaterialExportTerminalPreflight:
    task_id: str
    terminal_code: str
    constructed_meter_count: int
    source_collector_count: int
    requested_collector_count: int
    final_collector_count: int
    source_revision: str
    can_export: bool
    issues: tuple[MaterialExportIssue, ...]
    pool_shortage: int

@dataclass(frozen=True, slots=True)
class ProjectExportEvidence:
    meters: tuple[MaterialExportMeter, ...]
    group_payloads: Mapping[str, Mapping[str, object]]
    photo_storage_rows: Mapping[str, Mapping[str, object]]

@dataclass(frozen=True, slots=True)
class MaterialExportPreflight:
    project_id: str
    fingerprint: str
    terminals: Mapping[str, MaterialExportTerminalPreflight]
    source_group_ids: tuple[str, ...]
    total_pool_shortage: int

def build_preflight(*, tasks: Sequence[Task], evidence: ProjectExportEvidence, settings: Mapping[str, TerminalExportSetting]) -> MaterialExportPreflight:
    selected_task_ids = {str(task.id) for task in tasks}
    project_issues = project_module_issues(evidence.meters)
    terminal_rows = build_terminal_preflight_rows(selected_task_ids, evidence, settings, project_issues)
    fingerprint = preflight_fingerprint(build_preflight_fingerprint_rows(evidence, terminal_rows))
    return MaterialExportPreflight(
        project_id=str(tasks[0].project_id),
        fingerprint=fingerprint,
        terminals={row.task_id: row for row in terminal_rows},
        source_group_ids=tuple(sorted(item.group_id for item in evidence.meters if item.constructed)),
        total_pool_shortage=sum(row.pool_shortage for row in terminal_rows),
    )

def build_terminal_preflight_rows(
    selected_task_ids: set[str],
    evidence: ProjectExportEvidence,
    settings: Mapping[str, TerminalExportSetting],
    project_issues: Sequence[MaterialExportIssue],
) -> tuple[MaterialExportTerminalPreflight, ...]:
    return tuple(
        terminal_preflight_from_evidence(task_id, evidence, settings.get(task_id), project_issues)
        for task_id in sorted(selected_task_ids, key=str)
    )

def build_preflight_fingerprint_rows(
    evidence: ProjectExportEvidence,
    terminals: Sequence[MaterialExportTerminalPreflight],
) -> tuple[Mapping[str, object], ...]:
    return canonical_preflight_rows(evidence=evidence, terminals=terminals)

class PostgresMaterialExportService:
    def __init__(self, session: Session, *, team_id: str, actor_id: UUID | None, actor: str) -> None:
        self.session = session
        self.team_id = team_id
        self.actor_id = actor_id
        self.actor = actor

    def preflight(self, *, task_ids: Sequence[str]) -> MaterialExportPreflight:
        tasks = self._owned_tasks(task_ids, lock=False)
        project_ids = {task.project_id for task in tasks}
        if len(project_ids) != 1:
            raise MaterialExportProjectMismatch("一次导出只能选择同一项目的终端")
        evidence = self._load_project_evidence(project_ids.pop())
        return build_preflight(tasks=tasks, evidence=evidence, settings=self._settings(tasks))
```

Implement `terminal_preflight_from_evidence()` to filter constructed meters by exact `task_id`, calculate required-field/open-module/project-conflict issues, apply the persisted requested count and produce one deterministic terminal row. Implement `canonical_preflight_rows()` to include every constructed project meter relation, selected photo ID/SHA256, unresolved module anomaly fingerprint, terminal setting, active allocation ID/status and current inventory status; source changes therefore change the preflight fingerprint. After rows are built, the service simulates reusable/same-number/pool availability and replaces each row's `pool_shortage` plus the batch total without writing allocation rows.

`_load_project_evidence()` selects only required group/catalog/photo columns, orders by stable IDs, converts each group to `ReviewMeterEvidence`, uses public `is_constructed_evidence()` and existing single-group `project_terminal_review()` for photo precedence, then calls `group_anomalies()` and keeps unresolved module codes or Chinese messages containing“模块”. It must load all constructed relations for the selected project so cross-terminal conflicts cannot escape, while only building terminal manifests for selected tasks.

- [ ] **Step 4: Add setting and task-project identity tests**

```python
summary = service.set_requested_collector_count(task_id=str(task.id), count=4)
assert summary.requested_collector_count == 4
assert summary.source_collector_count == 2
assert summary.final_collector_count == 4
assert session.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "material_export.setting_updated")) == 1

with pytest.raises(ValueError, match="非负整数"):
    service.set_requested_collector_count(task_id=str(task.id), count=-1)
```

Modify `_task_payload()` to include the real `project_id` string. Add a state-repository regression proving task snapshots no longer hard-code `local-test` project identity.

- [ ] **Step 5: Implement summaries and setting persistence**

`list_terminal_summaries()` accepts at most 500 same-team task IDs and returns only task/project/terminal, requested count, constructed distinct collector count, final count, active allocation count and last job status; it never loads photo bytes. `set_requested_collector_count()` locks the owned task and setting row, upserts the nonnegative count, audits before/after and returns a refreshed summary.

- [ ] **Step 6: Verify GREEN, query shape, and commit**

```powershell
.venv\Scripts\python.exe -m pytest v2-api/tests/test_material_export_service.py v2-api/tests/test_state_repository.py -q -k "material_export or task_payload_project"
git add -- v2-api/app/services/material_export.py v2-api/app/services/state_repository.py v2-api/tests/test_material_export_service.py v2-api/tests/test_state_repository.py
git commit --only -m "feat: preflight terminal material exports" -- v2-api/app/services/material_export.py v2-api/app/services/state_repository.py v2-api/tests/test_material_export_service.py v2-api/tests/test_state_repository.py
```

### Task 4: Add atomic same-number and pool allocation with repeat reuse

**Files:**
- Modify: `v2-api/app/services/material_export.py`
- Modify: `v2-api/tests/test_material_export_service.py`
- Modify: `v2-api/tests/test_collector_transfer_postgres_integration.py`

**Interfaces:**
- Consumes: Task 3 preflight, existing `PhysicalCollector.pool_status`, active `CollectorAssignment`, `CollectorRequirement` terminal ownership and pool photos.
- Produces: `reserve_job(preflight_fingerprint, task_ids)`, `_reserve_terminal_collectors()`, `cancel_and_release(job_id, terminal_ids, reason)`.

- [ ] **Step 1: Write failing all-or-nothing allocation tests**

```python
result = service.reserve_job(preflight_fingerprint=preflight.fingerprint, task_ids=[str(task_a.id), str(task_b.id)])
assert result.terminals[0].allocations[0].allocation_mode == "same_number"
assert result.terminals[0].allocations[0].final_collector_no == "C-SAME"
assert result.terminals[0].allocations[1].allocation_mode == "pool_replacement"
assert result.terminals[0].allocations[2].allocation_mode == "extra_pool"
assert len({item.physical_collector_id for terminal in result.terminals for item in terminal.allocations}) == result.total_allocations

with pytest.raises(MaterialExportPoolShortage) as error:
    service.reserve_job(preflight_fingerprint=shortage.fingerprint, task_ids=[str(task_a.id), str(task_b.id)])
assert error.value.total_shortage == 2
assert session.scalar(select(func.count(MaterialExportCollectorAllocation.id))) == 0
```

Add stale fingerprint, cross-project, foreign-team, exact collector already owned by another terminal, active `CollectorAssignment`, and two concurrent jobs racing for one physical collector.

- [ ] **Step 2: Run focused allocation tests and verify RED**

```powershell
.venv\Scripts\python.exe -m pytest v2-api/tests/test_material_export_service.py v2-api/tests/test_collector_transfer_postgres_integration.py -q -k "material_export and (allocation or shortage or race)"
```

- [ ] **Step 3: Implement stable lock order and reuse**

Inside one transaction:

```python
class MaterialExportPoolShortage(MaterialExportError):
    code = "pool_shortage"

    def __init__(self, message: str, *, total_shortage: int, terminal_shortages: Mapping[str, int]) -> None:
        super().__init__(message)
        self.total_shortage = total_shortage
        self.terminal_shortages = dict(terminal_shortages)

class MaterialExportCompletedCannotRelease(MaterialExportError):
    code = "completed_cannot_release"

@dataclass(frozen=True, slots=True)
class MaterialExportShortageSimulation:
    total_shortage: int
    terminal_shortages: Mapping[str, int]

@dataclass(frozen=True, slots=True)
class MaterialExportAllocationResult:
    allocation_id: str
    physical_collector_id: str
    original_collector_no: str | None
    final_collector_no: str
    allocation_mode: str
    is_extra: bool

@dataclass(frozen=True, slots=True)
class MaterialExportTerminalResult:
    id: str
    task_id: str
    terminal_code: str
    allocations: tuple[MaterialExportAllocationResult, ...]

@dataclass(frozen=True, slots=True)
class MaterialExportJobResult:
    job_id: str
    total_allocations: int
    terminals: tuple[MaterialExportTerminalResult, ...]

def reserve_job(self, *, preflight_fingerprint: str, task_ids: Sequence[str]) -> MaterialExportJobResult:
    tasks = self._owned_tasks(task_ids, lock=True)
    current = self.preflight(task_ids=[str(task.id) for task in tasks])
    if current.fingerprint != preflight_fingerprint:
        raise MaterialExportSnapshotChanged("资料已变化，请重新预检")
    reusable = self._active_allocations(tasks)
    shortage = self._simulate_shortage(current, reusable)
    if shortage.total_shortage:
        raise MaterialExportPoolShortage(
            "采集器池库存不足，本批次未开始分配",
            total_shortage=shortage.total_shortage,
            terminal_shortages=shortage.terminal_shortages,
        )
    physical_rows = self._lock_candidate_physical_collectors(current, reusable)
    allocations = self._create_missing_allocations(current, reusable, physical_rows)
    return self._create_job_and_manifests(current, allocations)
```

Lock project/task rows, existing active export allocations, relevant existing `CollectorAssignment`/requirement ownership and candidate `PhysicalCollector` rows in UUID order. Same-number selection may reuse an existing direct/used assignment only when its requirement terminal equals the target terminal; otherwise that physical is unavailable and the requirement uses pool replacement. New reservations set physical status to `reserved` and store `prior_pool_status`. Pool candidates require current project, `pool_status='available'`, no active old assignment, no active export allocation; random order uses PostgreSQL `ORDER BY random()` only after bounded candidate locking.

- [ ] **Step 4: Add repeat, failure, completion and release tests**

```python
first = service.reserve_job(preflight_fingerprint=preflight.fingerprint, task_ids=[str(task.id)])
service.mark_terminal_completed(job_id=first.job_id, terminal_id=first.terminals[0].id)
second_preflight = service.preflight(task_ids=[str(task.id)])
second = service.reserve_job(preflight_fingerprint=second_preflight.fingerprint, task_ids=[str(task.id)])
assert [item.allocation_id for item in first.terminals[0].allocations] == [item.allocation_id for item in second.terminals[0].allocations]

with pytest.raises(MaterialExportCompletedCannotRelease):
    service.cancel_and_release(job_id=first.job_id, terminal_ids=[first.terminals[0].id], reason="误操作")
```

For a failed but incomplete terminal, release must mark allocation `released`, restore `prior_pool_status` only if no old/new active owner exists, retain audit history and never delete physical, photo or OSS records.

- [ ] **Step 5: Verify GREEN and commit**

```powershell
.venv\Scripts\python.exe -m pytest v2-api/tests/test_material_export_service.py v2-api/tests/test_collector_transfer_postgres_integration.py -q -k "material_export"
git add -- v2-api/app/services/material_export.py v2-api/tests/test_material_export_service.py v2-api/tests/test_collector_transfer_postgres_integration.py
git commit --only -m "feat: reserve collectors for material export" -- v2-api/app/services/material_export.py v2-api/tests/test_material_export_service.py v2-api/tests/test_collector_transfer_postgres_integration.py
```

### Task 5: Build immutable terminal manifests, photo selection, jobs, and lease lifecycle

**Files:**
- Modify: `v2-api/app/services/material_export.py`
- Modify: `v2-api/tests/test_material_export_service.py`

**Interfaces:**
- Consumes: Task 4 allocations, `Photo`, `CollectorPhoto`, `MeterSource` photo IDs and stable storage metadata.
- Produces: immutable `MaterialExportTerminal.manifest_json`, `MaterialExportFile` rows, `job_detail()`, `acquire_lease()`, `heartbeat()`, `pause()`, `ack_file()`, `mark_terminal_completed()`.

- [ ] **Step 1: Write failing manifest/photo-source tests**

```python
detail = service.job_detail(job_id=job.id)
terminal = detail.terminals[0]
assert terminal.meter_rows == [{"meter_no": "M-1", "address": "总清单地址", "module_no": "MOD-1", "final_collector_no": "C-1"}]
assert {item.relative_path for item in terminal.files} >= {
    "T-1/MOD-1/模块与电能表.jpg",
    "T-1/MOD-1/改造后.jpg",
    "T-1/终端资料.xlsx",
}
assert all("采集器清单" not in item.relative_path for item in terminal.files)
assert terminal.supplement_rows == []
assert "T-1/补充采集器.xlsx" not in {item.relative_path for item in terminal.files}
```

Add four collector photo cases: inventory same-number, terminal group fallback, pool own photo, and no photo. The no-photo case has collector number/workbook row but no image file and no blocking issue.

- [ ] **Step 2: Run manifest tests and verify RED**

```powershell
.venv\Scripts\python.exe -m pytest v2-api/tests/test_material_export_service.py -q -k "manifest or photo_source or workbook_rows"
```

- [ ] **Step 3: Implement stable file and workbook manifests**

Choose collector photos in this exact order: active inventory photo; earliest `(created_at, id)` effective group collector photo matching the original collector number in the same terminal; pool collector's active inventory photo; none. Snapshot source photo ID, storage bucket/key/type, original extension, size, SHA256 and content type into `MaterialExportFile`; never resolve or mutate OSS during manifest creation.

Create client-workbook file rows with no source photo. `终端资料.xlsx` always exists; `补充采集器.xlsx` exists only when `supplement_rows` is nonempty. Detect collisions after Windows-safe normalization; a second defensive module directory becomes `模块号__表号`, the terminal becomes `needs_recheck`, and no existing file is overwritten. Persist canonical manifest SHA256 and never alter terminal manifests after job creation.

- [ ] **Step 4: Write failing lease and state tests**

```python
lease = service.acquire_lease(job_id=str(job.id), owner_token="browser-a")
assert lease.scope == "global-download"
with pytest.raises(MaterialExportBusy):
    other_team_service.acquire_lease(job_id=str(other_job.id), owner_token="browser-b")
service.pause(job_id=str(job.id), owner_token="browser-a")
assert session.get(MaterialExportLease, "global-download") is None
assert service.job_detail(job_id=str(job.id)).status == "paused"
```

Add expiry reclaim, wrong owner, heartbeat extension, acknowledged file idempotency, wrong SHA/size rejection, terminal completion only after every required server/client file is acknowledged, and source revision change to `needs_recheck` before the next unstarted terminal.

- [ ] **Step 5: Implement state transitions and audit**

Define `MaterialExportBusy(MaterialExportError)` with code `export_busy`, `MaterialExportLeaseMismatch(MaterialExportError)` with code `lease_mismatch`, and `MaterialExportFileMismatch(MaterialExportError)` with code `file_mismatch`. Use database row locks for job/terminal/file/lease. `ack_file()` accepts exactly `(job_id, file_id, byte_size, sha256)` and is idempotent when values match; mismatched retry returns conflict. `pause()` releases only the lease. `mark_terminal_completed()` sets allocations to `used`, physical rows to `used`, then marks terminal complete. Every transition writes a normal `AuditLog` with job, terminal, counts, sources and actor.

- [ ] **Step 6: Verify GREEN and commit**

```powershell
.venv\Scripts\python.exe -m pytest v2-api/tests/test_material_export_service.py -q
git add -- v2-api/app/services/material_export.py v2-api/tests/test_material_export_service.py
git commit --only -m "feat: build resumable material export manifests" -- v2-api/app/services/material_export.py v2-api/tests/test_material_export_service.py
```

### Task 6: Add OSS-internal throttled streaming without server files

**Files:**
- Create: `v2-api/app/services/material_export_stream.py`
- Modify: `v2-api/app/services/photo_storage.py:315-334`
- Modify: `v2-api/app/core/config.py`
- Create: `v2-api/tests/test_material_export_stream.py`

**Interfaces:**
- Consumes: `require_oss_client(oss_server_endpoint())`, immutable `MaterialExportFile` storage snapshot.
- Produces: `MaterialExportFileSnapshot`, `StreamPolicy`, `head_export_object(file)`, `iter_export_object(file, on_complete, on_abort)`, `build_export_stream(file_row, on_complete, on_abort)`.

- [ ] **Step 1: Write failing internal-endpoint and no-fallback tests**

```python
def test_stream_uses_internal_oss_endpoint_only(fake_bucket_factory) -> None:
    stream = build_export_stream(file_row(), bucket_factory=fake_bucket_factory)
    assert fake_bucket_factory.endpoints == ["oss-cn-internal.aliyuncs.com"]
    assert b"".join(stream) == b"photo-bytes"

def test_missing_internal_endpoint_never_falls_back_publicly(settings) -> None:
    settings.oss_internal_endpoint = ""
    with pytest.raises(MaterialExportOssUnavailable, match="OSS 内网端点"):
        build_export_stream(file_row())
```

- [ ] **Step 2: Write failing rate, chunk, abort, and disk tests**

Use a fake monotonic clock and sleeper. For `500000` bytes, assert elapsed virtual time is at least `2.0` seconds at `250000` bytes/s, every yielded chunk is at most `65536`, abort invokes `on_abort` but not `on_complete`, and monkeypatched `open`, `NamedTemporaryFile`, `mkstemp` are never called.

- [ ] **Step 3: Implement a token-bucket iterator**

```python
@dataclass(frozen=True, slots=True)
class MaterialExportFileSnapshot:
    file_id: str
    storage_bucket: str
    storage_key: str
    byte_size: int
    sha256: str
    content_type: str

@dataclass(slots=True)
class StreamPolicy:
    bytes_per_second: int = 250_000
    chunk_bytes: int = 65_536

def iter_export_object(*, bucket, key: str, expected_size: int, policy: StreamPolicy, on_complete, on_abort):
    result = bucket.get_object(key)
    sent = 0
    started = time.monotonic()
    try:
        while True:
            chunk = result.read(policy.chunk_bytes)
            if not chunk:
                break
            sent += len(chunk)
            target_elapsed = sent / policy.bytes_per_second
            delay = target_elapsed - (time.monotonic() - started)
            if delay > 0:
                time.sleep(delay)
            yield chunk
        if sent != expected_size:
            raise MaterialExportObjectMismatch("OSS 对象大小与清单不一致")
        on_complete(sent)
    except GeneratorExit:
        on_abort(sent)
        raise
    except BaseException:
        on_abort(sent)
        raise
```

Perform OSS HEAD before yielding; require matching content length and matching `x-oss-meta-sha256` when metadata is present. Public endpoint fallback is forbidden. Never log signed URLs, credentials or complete keys.

`build_export_stream()` must call `require_oss_client(oss_server_endpoint())`, HEAD the snapshotted key, then return `iter_export_object()` with the configured `StreamPolicy`; it must not accept a client-supplied bucket, key, endpoint, size or SHA256.

- [ ] **Step 4: Verify GREEN and commit**

```powershell
.venv\Scripts\python.exe -m pytest v2-api/tests/test_material_export_stream.py -q
git add -- v2-api/app/services/material_export_stream.py v2-api/app/services/photo_storage.py v2-api/app/core/config.py v2-api/tests/test_material_export_stream.py
git commit --only -m "feat: stream OSS exports within bandwidth budget" -- v2-api/app/services/material_export_stream.py v2-api/app/services/photo_storage.py v2-api/app/core/config.py v2-api/tests/test_material_export_stream.py
```

### Task 7: Expose strict administrator material-export APIs

**Files:**
- Create: `v2-api/app/api/schemas/material_export.py`
- Create: `v2-api/app/api/routes/material_exports.py`
- Modify: `v2-api/app/api/router.py:1-15`
- Create: `v2-api/tests/test_material_export_api.py`

**Interfaces:**
- Consumes: Tasks 3-6 service methods, `Depends(require_admin)`, authenticated team/user identity.
- Produces: `/material-exports/terminal-summaries`, `/terminal-settings/{task_id}`, `/preflight`, `/jobs`, job detail/lifecycle/file stream/ack/release routes.

- [ ] **Step 1: Write failing role, tenancy, and request-model tests**

```python
def test_constructor_cannot_read_or_mutate_material_exports(constructor_client) -> None:
    for method, path in (("post", "/material-exports/preflight"), ("post", "/material-exports/jobs"), ("post", "/material-exports/terminal-summaries")):
        assert getattr(constructor_client, method)(path, json={"task_ids": ["1"]}).status_code == 403

def test_request_rejects_actor_team_and_negative_count(admin_client) -> None:
    response = admin_client.patch("/material-exports/terminal-settings/1", json={"requested_collector_count": -1, "actor": "spoof"})
    assert response.status_code == 422
```

Add foreign-team task/job/file 404 tests, mixed-project batch 409, more than 500 task IDs 422, stale fingerprint 409, pool shortage 409 with per-terminal gaps, and lease busy 423.

- [ ] **Step 2: Define strict DTOs**

```python
class TaskIdsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_ids: list[str] = Field(min_length=1, max_length=500)

class TerminalSettingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requested_collector_count: int = Field(ge=0, le=999)

class ReserveJobRequest(TaskIdsRequest):
    preflight_fingerprint: str = Field(min_length=64, max_length=64)

class FileAcknowledgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    byte_size: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64)
```

Define equally strict resume/heartbeat/pause/release payloads. Never accept actor, role, team, project ownership or OSS keys from the client.

- [ ] **Step 3: Implement routes and stable Chinese errors**

Register `APIRouter(prefix="/material-exports")`. Every route requires `Depends(require_admin)` before opening the service session. The file route is:

```python
@router.get("/jobs/{job_id}/files/{file_id}")
def stream_file(job_id: str, file_id: str, request: Request, lease_token: str = Header(alias="X-Material-Export-Lease"), admin_payload: dict = Depends(require_admin)):
    identity = admin_identity(request=request, admin_payload=admin_payload)
    file_row = authorize_material_export_stream(identity=identity, job_id=job_id, file_id=file_id, lease_token=lease_token)
    return StreamingResponse(
        build_export_stream(
            file_row=file_row,
            on_complete=lambda sent: record_material_export_stream_event(identity=identity, file_id=file_id, outcome="finished", byte_size=sent),
            on_abort=lambda sent: record_material_export_stream_event(identity=identity, file_id=file_id, outcome="aborted", byte_size=sent),
        ),
        media_type=file_row.content_type or "application/octet-stream",
        headers={"Content-Length": str(file_row.byte_size), "Cache-Control": "no-store"},
    )
```

`admin_identity()` derives `team_id`, authenticated user ID and actor name only from `admin_payload`/request context. `authorize_material_export_stream()` opens and closes a short SQLAlchemy session before streaming and returns an immutable storage snapshot. Each `record_material_export_stream_event()` callback opens its own short session, so no database transaction/session stays open for the duration of a slow file transfer.

Use these exact helper signatures in the route module:

```python
@dataclass(frozen=True, slots=True)
class AdminIdentity:
    team_id: str
    user_id: UUID | None
    actor: str

def admin_identity(*, request: Request, admin_payload: Mapping[str, object]) -> AdminIdentity:
    raw_user_id = str(admin_payload.get("user_id") or "").strip()
    try:
        user_id = UUID(raw_user_id) if raw_user_id else None
    except ValueError:
        user_id = None
    actor = str(admin_payload.get("username") or admin_payload.get("sub") or "admin").strip() or "admin"
    return AdminIdentity(
        team_id=current_team_id(),
        user_id=user_id,
        actor=actor,
    )

def authorize_material_export_stream(*, identity: AdminIdentity, job_id: str, file_id: str, lease_token: str) -> MaterialExportFileSnapshot:
    with SessionLocal() as session:
        return PostgresMaterialExportService(session, team_id=identity.team_id, actor_id=identity.user_id, actor=identity.actor).authorize_stream(
            job_id=job_id, file_id=file_id, lease_token=lease_token
        )

def record_material_export_stream_event(*, identity: AdminIdentity, file_id: str, outcome: str, byte_size: int) -> None:
    with SessionLocal.begin() as session:
        PostgresMaterialExportService(session, team_id=identity.team_id, actor_id=identity.user_id, actor=identity.actor).record_stream_event(
            file_id=file_id, outcome=outcome, byte_size=byte_size
        )
```

Return 400 invalid data, 403 non-admin, 404 hidden foreign ownership, 409 stale/conflict/shortage, 423 global lease busy, 502 OSS internal failure. All error bodies include stable `code`, Chinese `message`, and safe structured details.

- [ ] **Step 4: Prove old export retirement remains intact**

Add API regressions asserting `/exports`, `/exports/terminal-readiness`, `/exports/jobs` and legacy final-delivery routes still return `410`, and no new route imports old `export_center`, `delivery_cache` or ZIP builders.

- [ ] **Step 5: Verify GREEN and commit**

```powershell
.venv\Scripts\python.exe -m pytest v2-api/tests/test_material_export_api.py v2-api/tests/test_material_export_service.py v2-api/tests/test_material_export_stream.py v2-api/tests/test_export_center.py -q
git add -- v2-api/app/api/schemas/material_export.py v2-api/app/api/routes/material_exports.py v2-api/app/api/router.py v2-api/tests/test_material_export_api.py
git commit --only -m "feat: expose administrator material export APIs" -- v2-api/app/api/schemas/material_export.py v2-api/app/api/routes/material_exports.py v2-api/app/api/router.py v2-api/tests/test_material_export_api.py
```

### Task 8: Add browser file, checkpoint, hashing, and workbook foundations

**Files:**
- Modify: `v2-web/package.json`
- Modify: `v2-web/pnpm-lock.yaml`
- Modify: `v2-web/src/api/types.ts:99-135`
- Modify: `v2-web/src/api/services.ts:168-200,854-892,2112-2143`
- Create: `v2-web/src/types/file-system-access.d.ts`
- Create: `v2-web/src/features/materialExport/state.ts`
- Create: `v2-web/src/features/materialExport/checkpoint.ts`
- Create: `v2-web/src/features/materialExport/fileSystem.ts`
- Create: `v2-web/src/features/materialExport/workbooks.ts`
- Create: `v2-web/src/features/materialExport/__tests__/state.spec.ts`
- Create: `v2-web/src/features/materialExport/__tests__/checkpoint.spec.ts`
- Create: `v2-web/src/features/materialExport/__tests__/fileSystem.spec.ts`
- Create: `v2-web/src/features/materialExport/__tests__/workbooks.spec.ts`

**Interfaces:**
- Consumes: Task 7 JSON/file contracts.
- Produces: frontend DTOs/API clients, `saveResponseToDirectory()`, `loadCheckpoint()`, `saveCheckpoint()`, `buildTerminalWorkbook()`, `buildSupplementWorkbook()`, `sortExportTasks()`.

- [ ] **Step 1: Add pinned lazy dependencies and verify lock policy**

```powershell
Push-Location v2-web
pnpm add exceljs@4.4.0 hash-wasm@4.12.0
Pop-Location
pnpm --dir v2-web install --frozen-lockfile
```

Keep both imports dynamic inside workbook/hash execution so the normal task page does not eagerly load them. Run the repository lockfile supply-chain verifier and stop on any policy failure.

- [ ] **Step 2: Write failing state and API mapping tests**

```ts
it('sorts priority then completion descending then terminal', () => {
  const ordered = sortExportTasks([task('B', false, 80), task('A', true, 20), task('C', true, 90)])
  expect(ordered.map((item) => item.terminal)).toEqual(['C', 'A', 'B'])
})

it('maps the real project id and export summary', async () => {
  apiMock.mockResolvedValue({ items: [{ id: 1, project_id: 'project-a', terminal: 'T-1' }] })
  const snapshot = await fetchTaskSnapshot()
  expect(snapshot.items[0].projectId).toBe('project-a')
})
```

Add type/API clients for summary chunks, setting update, preflight, reserve, detail, resume, heartbeat, pause, file response, ack, terminal complete and cancel-release.

- [ ] **Step 3: Write failing file-system and incremental hash tests**

```ts
it('writes a response stream and hashes without buffering the complete file', async () => {
  const response = responseFromChunks([bytes(65536), bytes(65536), bytes(7)])
  const result = await saveResponseToDirectory(rootHandle, 'T-1/MOD-1/改造后.jpg', response)
  expect(result.byteSize).toBe(131079)
  expect(result.sha256).toMatch(/^[0-9a-f]{64}$/)
  expect(writable.write).toHaveBeenCalledTimes(3)
})

it('rejects unsafe manifest paths', async () => {
  await expect(saveResponseToDirectory(rootHandle, '../escape.jpg', responseFromChunks([bytes(1)]))).rejects.toThrow('非法导出路径')
})
```

Use `hash-wasm.createSHA256()` and `response.body.getReader()`. For each chunk: update hash, write chunk, increment bytes. On mismatch or error call `writable.abort()`. Never call `response.blob()` or `arrayBuffer()` for photos.

- [ ] **Step 4: Write failing checkpoint and workbook tests**

Checkpoint key is job ID; store directory handle, manifest SHA256 and completed `{fileId, relativePath, byteSize, sha256}`. Restored checkpoints with a different manifest hash are rejected. Workbook tests load the generated buffer with ExcelJS and assert exact sheet names, column order and values:

```ts
expect(rows).toEqual([
  ['表号', '地址', '模块号', '采集器号'],
  ['M-1', '总清单地址', 'MOD-1', 'C-1'],
])
expect(supplementRows).toEqual([
  ['采集器号', '照片文件名'],
  ['C-EXTRA', 'C-EXTRA.jpg'],
])
```

No supplement rows returns `null`, so the caller does not create `补充采集器.xlsx`.

- [ ] **Step 5: Implement and verify frontend foundations**

```powershell
Push-Location v2-web
pnpm vitest run src/features/materialExport/__tests__
pnpm type-check
Pop-Location
```

Expected: all feature tests and type check pass. Commit only the foundation paths.

- [ ] **Step 6: Commit**

```powershell
git add -- v2-web/package.json v2-web/pnpm-lock.yaml v2-web/src/api/types.ts v2-web/src/api/services.ts v2-web/src/types/file-system-access.d.ts v2-web/src/features/materialExport
git commit --only -m "feat: add browser material export foundation" -- v2-web/package.json v2-web/pnpm-lock.yaml v2-web/src/api/types.ts v2-web/src/api/services.ts v2-web/src/types/file-system-access.d.ts v2-web/src/features/materialExport
```

### Task 9: Integrate compact export controls and the serial resumable runner into task dispatch

**Files:**
- Create: `v2-web/src/features/materialExport/runner.ts`
- Create: `v2-web/src/features/materialExport/useMaterialExport.ts`
- Create: `v2-web/src/components/material-export/MaterialExportToolbar.vue`
- Create: `v2-web/src/components/material-export/MaterialExportCardControls.vue`
- Modify: `v2-web/src/views/ClaimTasksView.vue:1-130,300-470`
- Create: `v2-web/src/features/materialExport/__tests__/runner.spec.ts`
- Create: `v2-web/src/views/__tests__/ClaimTasksMaterialExport.spec.ts`

**Interfaces:**
- Consumes: Task 8 clients, directory/checkpoint/workbook functions and existing `ReviewTask` list.
- Produces: `runMaterialExport(job, directoryHandle, signal)`, `startLeaseHeartbeat(jobId, token)`, `checkpointMatches(root, job, file)`, `writeAndAcknowledgeWorkbooks(root, job, terminal)`, compact admin-only task-page controls, pause/resume/retry.

- [ ] **Step 1: Write failing runner sequence and resume tests**

```ts
it('downloads one terminal and one file at a time', async () => {
  await runMaterialExport(jobWithTwoTerminals(), directoryHandle, controller.signal)
  expect(callOrder).toEqual([
    'resume', 'file:t1-p1', 'ack:t1-p1', 'workbook:t1', 'ack:t1-xlsx', 'complete:t1',
    'file:t2-p1', 'ack:t2-p1', 'workbook:t2', 'ack:t2-xlsx', 'complete:t2',
  ])
  expect(maxConcurrentFileRequests).toBe(1)
})

it('skips locally verified checkpoint files after reload', async () => {
  checkpoint.completed['t1-p1'] = { fileId: 't1-p1', relativePath: 'T-1/MOD-1/改造后.jpg', byteSize: 8, sha256: SHA }
  await runMaterialExport(job, directoryHandle, controller.signal)
  expect(fetchFile).not.toHaveBeenCalledWith('t1-p1', expect.any(String), expect.any(AbortSignal))
})
```

Add pause-after-current-file, lease busy, directory permission loss, wrong local hash redownload, workbook acknowledgement, server `needs_recheck`, retry only failed file and heartbeat cleanup tests.

- [ ] **Step 2: Implement the exact serial loop**

```ts
export async function runMaterialExport(job: MaterialExportJobDetail, root: FileSystemDirectoryHandle, signal: AbortSignal) {
  const lease = await resumeMaterialExport(job.id)
  const heartbeat = startLeaseHeartbeat(job.id, lease.token)
  try {
    for (const terminal of job.terminals) {
      if (!terminal.canRun) continue
      for (const file of terminal.files.filter((item) => item.sourceKind !== 'client_workbook')) {
        if (await checkpointMatches(root, job, file)) continue
        const response = await fetchMaterialExportFile(job.id, file.id, lease.token, signal)
        const written = await saveResponseToDirectory(root, file.relativePath, response)
        await acknowledgeMaterialExportFile(job.id, file.id, written)
        await recordCheckpoint(root, job, file, written)
      }
      await writeAndAcknowledgeWorkbooks(root, job, terminal)
      await completeMaterialExportTerminal(job.id, terminal.id)
    }
  } finally {
    heartbeat.stop()
  }
}
```

Implement the neighboring helpers with these contracts:

```ts
export function startLeaseHeartbeat(jobId: string, token: string): { stop: () => void } {
  const timer = window.setInterval(() => void heartbeatMaterialExport(jobId, token), 30_000)
  return { stop: () => window.clearInterval(timer) }
}

export async function checkpointMatches(
  root: FileSystemDirectoryHandle,
  job: MaterialExportJobDetail,
  file: MaterialExportFile,
): Promise<boolean> {
  const checkpoint = await loadCheckpoint(job.id)
  const saved = checkpoint?.completed[file.id]
  if (!saved || checkpoint?.manifestSha256 !== job.manifestSha256) return false
  return verifyLocalFile(root, saved.relativePath, saved.byteSize, saved.sha256)
}

export async function writeAndAcknowledgeWorkbooks(
  root: FileSystemDirectoryHandle,
  job: MaterialExportJobDetail,
  terminal: MaterialExportTerminalManifest,
): Promise<void> {
  const terminalWorkbook = await buildTerminalWorkbook(terminal.meterRows)
  await writeClientWorkbook(root, job, terminal.terminalWorkbookFile, terminalWorkbook)
  const supplementWorkbook = await buildSupplementWorkbook(terminal.supplementRows)
  if (supplementWorkbook && terminal.supplementWorkbookFile) {
    await writeClientWorkbook(root, job, terminal.supplementWorkbookFile, supplementWorkbook)
  }
}
```

`writeClientWorkbook()` uses the same incremental SHA256/checkpoint/acknowledgement path as server files. `verifyLocalFile()` reads the existing local file as a stream and hashes it incrementally; it never trusts filename/size alone.

Pause does not abort the current chunk/file; it sets a flag read before the next file, then calls pause API. Browser/page destruction may abort the active request; that file is redownloaded later.

- [ ] **Step 3: Write failing task-page integration tests**

Require:

```ts
expect(adminWrapper.findAll('[data-testid="material-export-card"]')).toHaveLength(2)
expect(adminWrapper.get('[data-testid="material-export-count-T-1"]').attributes('type')).toBe('number')
expect(adminWrapper.get('[data-testid="material-export-batch"]').text()).toContain('一键导出已勾选终端')
expect(constructorWrapper.find('[data-testid="material-export-toolbar"]').exists()).toBe(false)
expect(constructorWrapper.find('[data-testid="material-export-card"]').exists()).toBe(false)
```

Add sorting priority/completion/terminal, “全选当前结果” respecting search/filter, completely unconstructed terminal disabled, partially constructed selectable, count autosave, Chinese conflict details, pool-shortage total/per-terminal gaps, folder picker unsupported notice, repeat export, downloaded/total bytes, estimated remaining time computed from completed bytes and elapsed time, pause, resume and release-confirmation tests.

- [ ] **Step 4: Implement compact components without changing platform layout**

`MaterialExportCardControls` renders one checkbox, one narrow numeric input and one `导出资料` button inside the existing card action area. `MaterialExportToolbar` sits inside the existing panel heading and shows selection count, batch button and one-line progress; no sidebar, full-screen workbench, mobile camera or route is added. `useMaterialExport()` loads terminal summaries only after `fetchTaskSnapshot()` renders and chunks task IDs at 500.

Change `visibleTasks` ordering to priority first, `constructionProgressPercent` descending, terminal ascending. Preserve all current assignment/priority controls and filters.

- [ ] **Step 5: Verify frontend GREEN and commit**

```powershell
Push-Location v2-web
pnpm vitest run src/features/materialExport/__tests__ src/views/__tests__/ClaimTasksMaterialExport.spec.ts
pnpm test:components
pnpm type-check
pnpm build
Pop-Location
git add -- v2-web/src/features/materialExport/runner.ts v2-web/src/features/materialExport/useMaterialExport.ts v2-web/src/components/material-export/MaterialExportToolbar.vue v2-web/src/components/material-export/MaterialExportCardControls.vue v2-web/src/views/ClaimTasksView.vue v2-web/src/features/materialExport/__tests__/runner.spec.ts v2-web/src/views/__tests__/ClaimTasksMaterialExport.spec.ts
git commit --only -m "feat: add terminal export to task dispatch" -- v2-web/src/features/materialExport/runner.ts v2-web/src/features/materialExport/useMaterialExport.ts v2-web/src/components/material-export/MaterialExportToolbar.vue v2-web/src/components/material-export/MaterialExportCardControls.vue v2-web/src/views/ClaimTasksView.vue v2-web/src/features/materialExport/__tests__/runner.spec.ts v2-web/src/views/__tests__/ClaimTasksMaterialExport.spec.ts
```

### Task 10: Add static gates, full verification, browser acceptance, and V3.2.27 release candidate

**Files:**
- Create: `scripts/verify_material_export_gate.py`
- Modify: `v2-api/app/static/vue/**`
- Modify: `v2-api/pyproject.toml`
- Modify: `v2-web/package.json`
- Modify: `README.md`
- Modify: `RELEASE_MANIFEST.md`
- Create: `ops/releases/V3.2.27.md`
- Generate: `build/server-release/module-manager-v2-server-3.2.27.zip`

**Interfaces:**
- Consumes: Tasks 1-9.
- Produces: all-green source, database migration dry-run evidence, real browser folder export evidence, verified immutable package and rollback plan; no production cutover.

- [ ] **Step 1: Add a failing static release gate**

The gate must assert:

```python
assert 'prefix="/material-exports"' in routes_source
assert "Depends(require_admin)" in routes_source
assert "250_000" in stream_source
assert "TemporaryFile" not in stream_source
assert "NamedTemporaryFile" not in stream_source
assert "zipfile" not in material_export_sources
assert "build_final_delivery_export" not in material_export_sources
assert "path: '/material-exports'" not in vue_router_source
```

Also verify old export retirement scripts still pass, File System Access is feature-detected, photo code does not call `blob()`/`arrayBuffer()`, and dependency imports are dynamic.

- [ ] **Step 2: Run backend matrices with final summaries**

```powershell
.venv\Scripts\python.exe -m pytest v2-api/tests/test_material_export_domain.py v2-api/tests/test_material_export_models.py v2-api/tests/test_material_export_service.py v2-api/tests/test_material_export_api.py v2-api/tests/test_material_export_stream.py v2-api/tests/test_collector_transfer_postgres_integration.py v2-api/tests/test_export_center.py -q
.venv\Scripts\python.exe -m pytest v2-api/tests -q
```

Expected: both commands reach final pytest summaries with zero failures. Timeout/no summary is not a pass.

- [ ] **Step 3: Run frontend and static gates**

```powershell
Push-Location v2-web
pnpm vitest run src/features/materialExport/__tests__ src/views/__tests__/ClaimTasksMaterialExport.spec.ts
pnpm test:components
pnpm type-check
pnpm build
Pop-Location
.venv\Scripts\python.exe scripts/verify_material_export_gate.py
.venv\Scripts\python.exe scripts/verify_vue_migration_gate.py
```

- [ ] **Step 4: Run local Chrome/Edge rendered acceptance**

Use test data only. In latest Windows Chrome and Edge:

- confirm constructor cannot see controls or call API;
- confirm administrator task list sorts priority/completion/terminal and renders before export summaries;
- export one complete terminal to an empty local folder and inspect exact directory/Excel/photo bytes;
- export one partially constructed terminal and prove unconstructed groups are absent;
- preflight cross-terminal duplicate module and one-table-many-module fixtures and verify Chinese blockers;
- export a no-collector-photo terminal and prove success without collector image;
- pause after a file, reload, reauthorize the same folder, resume and prove verified files are not downloaded again;
- start a second browser and prove global lease returns busy while the first runs;
- verify console/network contain no `/exports`, ZIP or delivery worker request.

- [ ] **Step 5: Run a controlled 3 Mbps bandwidth and resource test**

Use a nonproduction OSS fixture through the internal endpoint, download at least `50 MiB`, and record server RSS, disk, public throughput, construction page latency and request concurrency. Acceptance: one active file stream, average payload throughput no more than `2.1 Mbps`, no temporary export file growth, no OOM/restart, and normal site requests retain usable latency.

- [ ] **Step 6: Perform migration upgrade/downgrade safety rehearsal**

Against a disposable PostgreSQL copy: upgrade from `20260824_0016` to `20260901_0017`, inspect constraints/indexes, run the material export integration tests, then invoke downgrade and require the deliberate forward-only error without table/data mutation. Produce read-only production preflight SQL that counts table-name conflicts and verifies current head; do not run production migration yet.

- [ ] **Step 7: Bump versions, rebuild tracked Vue assets, and commit candidate evidence**

Set API/web/release manifest to `3.2.27` only if production baseline remains `3.2.26`; otherwise substitute the deterministic patch+1 version everywhere. Create `ops/releases/V3.2.27.md` with migration head, exact test counts, browser evidence, bandwidth evidence, backup/rollback steps and `发布状态：待用户确认`.

```powershell
git add -- v2-api/pyproject.toml v2-web/package.json v2-api/app/static/vue README.md RELEASE_MANIFEST.md scripts/verify_material_export_gate.py ops/releases/V3.2.27.md
git commit --only -m "release: prepare V3.2.27 terminal material export" -- v2-api/pyproject.toml v2-web/package.json v2-api/app/static/vue README.md RELEASE_MANIFEST.md scripts/verify_material_export_gate.py ops/releases/V3.2.27.md
```

- [ ] **Step 8: Build and verify a source-bound package**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build-client-release.ps1 -Version 3.2.27
.venv\Scripts\python.exe scripts/verify-client-release.py build/server-release/module-manager-v2-server-3.2.27.zip
.venv\Scripts\python.exe scripts/verify_release_sop.py --version V3.2.27 --phase source
Get-FileHash -Algorithm SHA256 -LiteralPath build/server-release/module-manager-v2-server-3.2.27.zip
```

Require ZIP `SOURCE_COMMIT` equals final HEAD, Alembic `20260901_0017` is included, Vue `version.json` covers assets, and no `.env`, production data, uploads, database dump, OSS credential, local export, checkpoint or temporary file is packaged.

### Task 11: Back up, migrate, deploy, verify, and attest production only after separate approval

**Files:**
- Modify after successful production acceptance: `ops/releases/V3.2.27.md`
- Local backup root: `C:\Users\Administrator\Documents\module-manager-production-backups\<yyyyMMdd-HHmmss>`

**Interfaces:**
- Consumes: verified V3.2.27 package/hash, approved migration, current production and rollback release.
- Produces: verified backup, migrated schema, healthy production, one controlled export, bandwidth evidence and attested release.

- [ ] **Step 1: Stop at the production authorization gate**

Present the package SHA256, source commit, exact migration SQL summary, backup scope, rollback release and acceptance checklist. Do not connect for mutation, upload, migrate, restart or clean disk until the user explicitly approves this production release.

- [ ] **Step 2: Capture current production and create verified recovery artifacts**

After approval, verify SSH stability, current symlink/version, Uvicorn listener `127.0.0.1:8000`, PostgreSQL head, disk/memory/swap and services. Stream a fresh local `pg_dump -Fc`, schema SQL, `.env` backup through a nonprinting protected path, application `data/uploads`, current release metadata and hashes. Verify `pg_restore -l`, tar listings, hashes and rollback path before upload.

- [ ] **Step 3: Run production migration dry-run checks and migrate**

Require current head `20260824_0016`, no conflicting export tables/indexes and successful read-only module conflict counts. Stop on mismatch. Deploy the new immutable release, restore `.env` without overwrite from package, run Alembic upgrade to `20260901_0017`, verify all six tables/constraints/indexes, then atomically switch `current` and restart.

- [ ] **Step 4: Prove real readiness before business acceptance**

Wait for the actual Uvicorn listener, then verify `/health`, `/project-board`, `/claim-tasks`, construction upload, review/rephoto, collector inventory and retired `/exports` responses. Verify no migration error, OOM, restart loop or new delivery-package task.

- [ ] **Step 5: Run one controlled production export**

Choose one explicitly approved completed terminal with no module conflict. Set/restore its collector count deliberately, preflight, export to a local test folder, inspect directory/Excel/photo hashes, pause/resume once, and confirm server disk does not grow. Do not use a terminal with unresolved module conflict and do not release completed collector allocations.

- [ ] **Step 6: Soak fixed-bandwidth production**

During the controlled export and for at least one normal construction cycle, record throughput, API latency, Uvicorn RSS, PostgreSQL sessions, disk, journal and service restarts. Require one stream, about `2 Mbps` or less payload bandwidth, usable施工页面, no OOM and no temporary files.

- [ ] **Step 7: Roll back on any failed gate**

Stop the export, restore previous `current`, restore the previous database dump because migration is forward-only, restart, wait for `127.0.0.1:8000`, and re-run health/construction/review checks. Preserve the failed release and logs; do not delete OSS objects or collector audit history.

- [ ] **Step 8: Attest production only after every gate passes**

Record source/package hashes, backup verification, migration before/after head, release/rollback paths, listener/pages, controlled terminal, output hashes, bandwidth/resources, services and rollback readiness in `ops/releases/V3.2.27.md`. Commit only that file with explicit path and report the deployed version and residual risks.
