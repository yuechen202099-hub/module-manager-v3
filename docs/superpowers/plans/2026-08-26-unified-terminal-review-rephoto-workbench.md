# V3.2.10 Unified Terminal Review and Re-photo Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在一个管理员页面内按终端完成已施工表计审阅、两张新装资料翻拍、终端级采集器去重及缺失采集器替换，同时确保未施工表计不阻塞、不生成翻拍项，施工员只能访问施工采集页面。

**Architecture:** 新增纯函数终端审阅投影，以数据库中的资料组、活动照片和持久化条码核验为唯一事实来源；现有采集器服务使用该投影扩展有界候选查询，并通过统一打开接口在服务器确认全终端审阅完成后才创建或复用隐藏翻拍快照。前端抽取现有数据中台审阅面板，在新的三栏工作台内复用，所有替换、回滚、刷新和完成写操作在持有既有规范锁后再次执行服务器端审阅门禁。

**Tech Stack:** Python 3.12、FastAPI、Pydantic、SQLAlchemy 2、PostgreSQL、pytest、Vue 3、TypeScript、Element Plus、Vue Router、Vitest、PowerShell、SSH/systemd/Nginx。

**Spec:** `docs/superpowers/specs/2026-08-26-unified-terminal-review-rephoto-workbench-design.md`

## Global Constraints

- 目标版本只能是 `V3.2.10`，维护分支只能是 `production/V3/3.2.10`；已部署的 V3.2.9 源码、ZIP、tag、发布记录和 release 目录不可改写。
- V3.2.10 必须包含已上线的 V3.2.9 盘点 Quagga-first 扫码修复及启动失败清理回归；后续构建或发布不得把盘点页回退为 native-first。
- 数据库保持 Alembic head `20260824_0016`；本计划不新增迁移。若现有表无法表达状态，停止执行并重新打开规格评审，不能自行加迁移。
- 已施工的定义是“存在至少一张活动源照片，或资料组持久化施工照片数大于 0”；未审阅但有照片的表计仍属于已施工。
- 未施工表计显示为 `未施工，不参与本次翻拍`，不计入审阅锁、来源版本、表计翻拍项、采集器需求或隐藏运行。
- 每个已施工表计只有 `module_meter`（电表和模块）与 `after_box`（改造完成）两个新装位置；每个终端采集器号去重后只有一个拆旧位置。
- 终端中任何一个已施工表计未达到服务器端 `review_ready`，整个终端的翻拍、替换、回滚、刷新和完成操作全部锁定。
- 同号实物采集器保持“有实物、无需网站照片、可直接翻拍”；缺失采集器仅能从同团队/同项目可用池随机一次性分配，数量不足必须零写入。
- `terminal_key` 只是内部标识，不是授权凭据；每次调用都按已认证 `team_id` 重新解析和核验项目、终端与资料组。
- 管理员可以访问施工页；施工员只能访问 `/construction`。施工员直接访问其他页面必须重定向，直接调用审阅、数据中台或采集器 API 必须在查询/写入前返回 HTTP 403。
- 统一页面不调用浏览器相机，也不向甲方平台发送请求；它只显示供掌机/手机翻拍的资料与条码。
- 原始资料组、源照片、总清单、历史审阅、采集器照片、分配与扫码记录，只能通过现有审计服务变更；不得批量改写历史数据。
- 所有提交使用显式路径；绝不编辑、暂存、删除、提交或打包受保护文件 `v2-api/uv.lock`。
- 顺序执行修改同一热点文件的任务：Task 2 与 Task 3 依次拥有 `v2-api/app/services/collector_transfer.py`，Task 5 与 Task 6 依次拥有审阅组件，Task 7 最后拥有路由/导航；不要并行派发这些热点文件。
- 每个测试命令必须出现明确的零失败总结；超时、被中断、无最终总结或仅有进程退出状态都不算通过。

---

## File Structure

- `v2-api/app/domain/terminal_review.py`: 纯终端审阅投影、阻断码、构造/未构造分区、构造表计来源版本和工作流状态推导。
- `v2-api/app/domain/collector_transfer.py`: 继续提供规范化、终端 key、来源 hash、表计/采集器快照与一次性随机分配；只补充安全解析 `terminal_key` 的函数。
- `v2-api/app/services/collector_transfer.py`: 轻量资料组/照片/核验查询、候选计数、统一打开、隐藏快照生命周期和所有采集器写操作的审阅复检。
- `v2-api/app/api/routes/collector_transfer.py`: 统一打开 DTO、稳定错误映射，以及整个采集器域的管理员前置授权。
- `v2-api/app/api/routes/groups.py`: 正式的数据中台审阅决定接口；继续复用 `PostgresStateRepository.review_group` 的审计与缓存失效行为。
- `v2-api/tests/test_terminal_review_domain.py`: 纯投影及构造表计来源版本测试。
- `v2-api/tests/test_collector_transfer_service.py`: 混合终端、有界查询、统一打开、隐藏运行和每个写入口的复检测试。
- `v2-api/tests/test_collector_transfer_api.py`: DTO、稳定错误、团队隔离和采集器全域管理员权限测试。
- `v2-api/tests/test_data_center_review.py`: 正式审阅决定接口、管理员授权和持久化审计测试。
- `v2-api/tests/test_collector_transfer_postgres_integration.py`: PostgreSQL 规范锁顺序、并发审阅变化与零部分写入测试。
- `v2-api/tests/test_collector_transfer_scale.py`: 生产基数下的候选分页、选列加载和查询数上限回归。
- `v2-web/src/api/types.ts`: 候选计数、审阅表计、阻断项、统一打开与可空 `rephoto` DTO。
- `v2-web/src/api/services.ts`: 统一候选/打开客户端、正式审阅决定客户端和既有采集器写客户端。
- `v2-web/src/features/collectorTransfer/state.ts`: 纯工作流标签、终端锁、可操作性与构造/未构造列表投影。
- `v2-web/src/components/data-center/DataCenterGroupReviewPanel.vue`: 可嵌入的受保护图片、字段修正、分类、重扫、框选、人工确认、通过/资料不全/异常与审计面板。
- `v2-web/src/components/data-center/DataCenterReviewDialog.vue`: 保留未匹配对话框；资料组分支改为薄对话框包装新面板。
- `v2-web/src/views/ReviewRephotoWorkbenchView.vue`: `/review-workbench` 三栏终端审阅与翻拍工作台。
- `v2-web/src/views/CollectorWorkbenchView.vue`: 统一页面验收通过后删除，防止两份逻辑漂移。
- `v2-web/src/components/__tests__/DataCenterGroupReviewPanel.spec.ts`: 嵌入审阅、图片 URL/Abort 清理和最终审阅动作测试。
- `v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts`: 混合终端、整终端锁、两位置翻拍、采集器去重、替换/回滚/完成和迟到响应测试。
- `v2-web/src/views/__tests__/CollectorInventoryRouting.spec.ts`: 管理员/施工员路由、导航和旧 URL 兼容测试。
- `v2-web/src/router/index.ts`, `v2-web/src/router/staticPages.ts`, `v2-web/src/layouts/AppLayout.vue`: 规范页面、旧路由收敛和施工员仅施工页策略。
- `v2-api/app/static/vue/**`: 最终源码提交后重新构建的 Vue 静态资产。
- `AGENTS.md`, `RELEASE_MANIFEST.md`, `v2-api/pyproject.toml`, `v2-api/app/main.py`, `v2-api/app/services/ops_status.py`, `v2-api/scripts/verify_v3_1_release.py`, `v2-api/tests/test_v3_1_release.py`, `v2-web/package.json`, `v2-web/index.html`, `v2-web/src/components/AppLayout.vue`, `v2-web/src/version.json`, `v2-web/src/constants/releaseNotes.ts`: V3.2.10 版本事实。
- `scripts/build-client-release.ps1`, `scripts/verify-client-release.py`, `scripts/verify_release_sop.py`, `scripts/verify_v3_2_10_release.py` 及对应测试：V3.2.10 源码/包/验收门禁，同时保留 V3.2.9 发布记录和历史验证行为不变。
- `ops/releases/V3.2.10.md`: 本地、包、生产、回滚和逐条验收证据；`ops/releases/V3.2.9.md` 仅作已发布历史保留。

### Task 1: 建立纯终端审阅投影

**Files:**
- Create: `v2-api/app/domain/terminal_review.py`
- Modify: `v2-api/app/domain/collector_transfer.py`
- Create: `v2-api/tests/test_terminal_review_domain.py`
- Modify: `v2-api/tests/test_collector_transfer_domain.py`

**Interfaces:**
- Consumes: `normalize_identifier(value) -> str`, `terminal_source_revision(rows) -> str`, `MeterSource`, `build_terminal_snapshots(records)`。
- Produces: `decode_terminal_key(value) -> tuple[str, str]`; `ReviewPhotoEvidence`; `ReviewMeterEvidence`; `ReviewMeterProjection`; `TerminalReviewProjection`; `project_terminal_review(meters: Iterable[ReviewMeterEvidence]) -> TerminalReviewProjection`; `derive_terminal_workflow_state(projection, missing_collector_count, pool_available_count, snapshot_state) -> TerminalWorkflowState`。

- [ ] **Step 1: 写出 terminal key 安全解析失败测试并确认 RED**

```python
import pytest

from app.domain.collector_transfer import decode_terminal_key, terminal_key


def test_terminal_key_round_trip_preserves_arbitrary_identifier_text() -> None:
    encoded = terminal_key("7d0ea83b-7621-4b56-95bf-f32cf444ee93", "00001234-A")
    assert decode_terminal_key(encoded) == (
        "7d0ea83b-7621-4b56-95bf-f32cf444ee93",
        "00001234-A",
    )


@pytest.mark.parametrize("value", ["", "%%%%", "W10=", "WyIiLCIxMjMiXQ"])
def test_decode_terminal_key_rejects_malformed_or_blank_parts(value: str) -> None:
    with pytest.raises(ValueError, match="terminal_key"):
        decode_terminal_key(value)
```

Run:

```powershell
& 'C:\Users\Administrator\.config\superpowers\worktrees\module-manager-v3\collector-transfer-workbench\v2-api\.venv\Scripts\python.exe' -m pytest v2-api/tests/test_collector_transfer_domain.py -k terminal_key -q
```

Expected: FAIL because `decode_terminal_key` does not exist.

- [ ] **Step 2: 实现最小安全解析并确认 GREEN**

实现必须补齐 URL-safe Base64 padding，JSON 结果必须是恰好两个字符串，并再次用 `normalize_identifier` 拒绝空项目/终端：

```python
def decode_terminal_key(value: str) -> tuple[str, str]:
    encoded = normalize_identifier(value)
    if not encoded:
        raise ValueError("terminal_key is required")
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("terminal_key is invalid") from exc
    if not isinstance(payload, list) or len(payload) != 2:
        raise ValueError("terminal_key is invalid")
    project_id, terminal_code = map(normalize_identifier, payload)
    if not project_id or not terminal_code:
        raise ValueError("terminal_key is invalid")
    return project_id, terminal_code
```

重新运行 Step 1 命令，Expected: PASS。

- [ ] **Step 3: 写出混合终端纯投影测试并确认 RED**

测试构造三块表：一块完整且已通过、一块有照片但未批准、一块零照片未施工。断言只有前两块进入构造来源版本，未施工表不阻塞也不产生 `MeterSource`：

```python
def test_mixed_terminal_partitions_unconstructed_and_locks_on_constructed_review() -> None:
    projection = project_terminal_review(
        (
            review_meter("g-1", status="approved", photo_count=2, barcode_status="passed"),
            review_meter("g-2", status="unreviewed", photo_count=2, barcode_status="passed"),
            review_meter("g-3", status="unreviewed", photo_count=0, active_photos=()),
        )
    )
    assert [item.group_id for item in projection.constructed_meters] == ["g-1", "g-2"]
    assert [item.group_id for item in projection.unconstructed_meters] == ["g-3"]
    assert projection.review_ready_count == 1
    assert projection.review_required_count == 1
    assert [item.group_id for item in projection.rephoto_sources] == ["g-1"]
    assert projection.source_revision != project_terminal_review(
        (review_meter("g-1", status="approved", photo_count=2, barcode_status="passed"),)
    ).source_revision
```

再增加八个独立测试，分别精确断言：正持久化照片数但无活动照片时为 constructed 且 `module_meter_photo_missing`/`after_box_photo_missing`；两个 slot 各一张时无 slot blocker；任一 slot 两张时出现对应 `_conflict`；占位身份与空模块分别产生身份 blocker；只有 `passed`/`manual_confirmed`/兼容 `manual` 通过条码门禁；活动异常、地址冲突、来源冲突分别阻断；只修改未施工行后来源版本相等；两个构造表共享同号采集器时 `collector_requirements` 长度为 1 且 `meter_group_ids == ("g-1", "g-2")`。

Run:

```powershell
& 'C:\Users\Administrator\.config\superpowers\worktrees\module-manager-v3\collector-transfer-workbench\v2-api\.venv\Scripts\python.exe' -m pytest v2-api/tests/test_terminal_review_domain.py -q
```

Expected: FAIL because the module and types do not exist.

- [ ] **Step 4: 实现纯类型、阻断码和来源版本**

使用不可变 dataclass，字段名固定如下，后续任务不得另造同义字段：

```python
ConstructionState = Literal["constructed", "unconstructed"]
TerminalWorkflowState = Literal[
    "no_construction", "needs_review", "blocked", "needs_replacement",
    "pool_shortage", "ready", "in_progress", "completed",
]


@dataclass(frozen=True, slots=True)
class ReviewPhotoEvidence:
    id: str
    category: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ReviewMeterEvidence:
    group_id: str
    status: str
    terminal_code: str
    installation_address: str
    meter_no: str
    collector_no: str
    module_no: str
    persisted_photo_count: int
    active_photos: tuple[ReviewPhotoEvidence, ...]
    barcode_status: str
    identity_blockers: tuple[str, ...] = ()
    source_blockers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReviewMeterProjection:
    group_id: str
    construction_state: ConstructionState
    review_ready: bool
    blockers: tuple[str, ...]
    source: MeterSource | None


@dataclass(frozen=True, slots=True)
class TerminalReviewProjection:
    constructed_meters: tuple[ReviewMeterProjection, ...]
    unconstructed_meters: tuple[ReviewMeterProjection, ...]
    rephoto_sources: tuple[MeterSource, ...]
    collector_requirements: tuple[CollectorRequirementSnapshot, ...]
    review_ready_count: int
    review_required_count: int
    source_revision: str
    hard_blocked: bool
```

固定阻断码为 `review_not_approved`, `terminal_missing`, `meter_missing`, `module_missing`, `collector_missing`, `module_meter_photo_missing`, `module_meter_photo_conflict`, `after_box_photo_missing`, `after_box_photo_conflict`, `barcode_verification_required`, `exception_open`, `address_conflict`, `source_conflict`。构造来源版本只序列化构造表计的身份、状态、阻断码、两张选定照片的 ID/SHA256 和条码核验状态。

- [ ] **Step 5: 写出工作流状态优先级测试并实现**

```python
from types import SimpleNamespace
from typing import cast


@pytest.mark.parametrize(
    ("constructed", "required", "hard_blocked", "missing", "available", "snapshot", "expected"),
    [
        (0, 0, False, 0, 0, None, "no_construction"),
        (2, 0, True, 0, 0, None, "blocked"),
        (2, 1, False, 0, 0, None, "needs_review"),
        (2, 0, False, 2, 1, None, "pool_shortage"),
        (2, 0, False, 1, 2, None, "needs_replacement"),
        (2, 0, False, 0, 2, None, "ready"),
        (2, 0, False, 0, 2, "in_progress", "in_progress"),
        (2, 0, False, 0, 2, "completed", "completed"),
    ],
)
def test_terminal_workflow_state_priority(
    constructed: int,
    required: int,
    hard_blocked: bool,
    missing: int,
    available: int,
    snapshot: str | None,
    expected: str,
) -> None:
    projection = cast(
        TerminalReviewProjection,
        SimpleNamespace(
            constructed_meters=tuple(object() for _ in range(constructed)),
            review_required_count=required,
            hard_blocked=hard_blocked,
        ),
    )
    assert derive_terminal_workflow_state(
        projection,
        missing_collector_count=missing,
        pool_available_count=available,
        snapshot_state=snapshot,
    ) == expected
```

实现 `derive_terminal_workflow_state`，严格按 `no_construction -> blocked -> needs_review -> progressed snapshot -> pool_shortage -> needs_replacement -> ready` 顺序判断。运行两个领域测试文件，Expected: PASS。

- [ ] **Step 6: 提交领域投影**

```powershell
git add -- v2-api/app/domain/terminal_review.py v2-api/app/domain/collector_transfer.py v2-api/tests/test_terminal_review_domain.py v2-api/tests/test_collector_transfer_domain.py
git commit --only -m "feat: add terminal review projection" -- v2-api/app/domain/terminal_review.py v2-api/app/domain/collector_transfer.py v2-api/tests/test_terminal_review_domain.py v2-api/tests/test_collector_transfer_domain.py
```

### Task 2: 扩展有界候选查询并实现统一打开

**Files:**
- Modify: `v2-api/app/services/collector_transfer.py`
- Modify: `v2-api/tests/test_collector_transfer_service.py`
- Modify: `v2-api/tests/test_collector_transfer_scale.py`

**Interfaces:**
- Consumes: Task 1 的 `decode_terminal_key`, `ReviewMeterEvidence`, `TerminalReviewProjection`, `project_terminal_review`, `derive_terminal_workflow_state`；现有 `meter_sources_from_groups`, `_global_terminal_projection`, `_active_global_terminal_run`, `_create_run_from_projection`, `_global_terminal_open_result`。
- Produces: `_TerminalReviewBundle`; `TerminalNotFoundError`; `_terminal_review_bundle(project_id: UUID, terminal_code: str, lock_groups: bool = False)`；扩展后的 `list_global_terminals(query: str, state: str | None, page: int, page_size: int, include_blocked: bool)`；`open_review_workbench_terminal(terminal_key_value: str, source_revision: str = "")`。

- [ ] **Step 1: 写出混合终端候选计数和有界查询测试并确认 RED**

在现有 SQLite 服务夹具中建立一个项目、同终端三组资料（两组有活动照片、一组未施工），让一组通过、一组未通过。断言候选字段：

```python
candidate = service.list_global_terminals(query="T-001", page=1, page_size=20)["items"][0]
assert candidate["constructed_meter_count"] == 2
assert candidate["unconstructed_meter_count"] == 1
assert candidate["review_ready_count"] == 1
assert candidate["review_required_count"] == 1
assert candidate["workflow_state"] == "needs_review"
assert candidate["selectable"] is True
assert candidate["terminal_code"] == "T-001"
assert candidate["terminal_key"] != "T-001"
```

在 `test_collector_transfer_scale.py` 记录 SQL 语句数和返回行规模，要求 page size 50 时不加载整表 ORM、不超过固定候选页查询预算，并且只对本页终端加载选定列。先运行：

```powershell
& 'C:\Users\Administrator\.config\superpowers\worktrees\module-manager-v3\collector-transfer-workbench\v2-api\.venv\Scripts\python.exe' -m pytest v2-api/tests/test_collector_transfer_service.py -k 'global_terminal_candidates and review' v2-api/tests/test_collector_transfer_scale.py -q
```

Expected: FAIL because the count fields and review projection are absent.

- [ ] **Step 2: 扩展轻量查询行并实现 `_terminal_review_bundle`**

扩展 `_ProjectGroupRow`，只选择以下列：内部 UUID、`legacy_id`、`status`、规范终端、显示表号、权威地址、`photo_count`、`exception_note`、`raw_data`。扩展 `_ProjectPhotoRow` 保留现有来源字段；一次查询加载活动照片，一次查询加载本终端 `GroupBarcodeVerification`。不要把 `MaterialGroup`, `Photo` 或核验 ORM 实例返回到投影层。

新增内部类型：

```python
@dataclass(frozen=True, slots=True)
class _TerminalReviewBundle:
    project_id: UUID
    terminal_code: str
    projection: TerminalReviewProjection
    photos: tuple[_ProjectPhotoRow, ...]
    review_rows: tuple[dict[str, object], ...]
```

`review_rows` 固定输出 `group_id`, `meter_no`, `module_no`, `collector_no`, `construction_state`, `review_ready`, `blockers`, `review_status`，其中 `group_id` 是可传给数据中台审阅接口的 `MaterialGroup.legacy_id`。身份是否为占位值必须复用 `local_simulation.is_placeholder_formal_identity_value`；条码状态必须复用 `resolve_persisted_barcode_verification`，只接受 `passed`, `manual`, `manual_confirmed`。

设备号与来源照片不能在新投影内另写优先级：先调用现有 `meter_sources_from_groups(groups, photos)` 得到 collector/module/两个 slot 的规范选择，再按内部 group UUID 与审阅证据合并；纯审阅层只负责精确 slot 数量冲突和 readiness。候选 `query` 额外匹配 `MaterialGroup.legacy_id`，供 `/review/:groupId` 兼容链接定位终端。

- [ ] **Step 3: 改造候选分页并确认 GREEN**

候选第一页先用数据库聚合确定终端身份和数量，再只对这一页调用轻量 bundle；不得按生产总终端数逐个发查询。候选响应保留 V3.2.9 字段，并新增四个计数和扩展状态。运行 Step 1 命令，Expected: PASS，且规模测试显示查询数不随总项目表计线性增长。

- [ ] **Step 4: 写出统一打开的零隐藏运行测试并确认 RED**

```python
before = transfer_run_count(session)
result = service.open_review_workbench_terminal(
    terminal_key_value=candidate["terminal_key"],
    source_revision=candidate["source_revision"],
)
assert result["workflow_state"] == "needs_review"
assert result["rephoto"] is None
assert result["constructed_meter_count"] == 2
assert result["unconstructed_meter_count"] == 1
assert [row["group_id"] for row in result["meters"]] == ["g-ready", "g-review", "g-unbuilt"]
assert transfer_run_count(session) == before
```

同时增加七个明确场景：零构造表返回 `no_construction` 且运行计数不变；全 ready 首次创建一个隐藏运行、同 revision 再开复用同一 run；请求体不接受项目/终端声明且服务只信解码后的 key；另一团队的 key 抛 `TerminalNotFoundError`；只改未施工组不 supersede ready 快照；构造组审阅/照片变化只 supersede 未进展快照；已进展快照保持历史行不变并返回 `source_changed=True`。

Expected: RED because unified open does not exist.

- [ ] **Step 5: 实现 `open_review_workbench_terminal`**

固定签名：

```python
def open_review_workbench_terminal(
    self,
    *,
    terminal_key_value: str,
    source_revision: str = "",
) -> dict[str, object]:
```

流程固定为：解析 key -> `_project` 验证团队项目 -> 获取规范终端锁 -> 重新查询 bundle -> 推导工作流 -> 对 `no_construction`/`needs_review`/`blocked` 返回 `rephoto=None` 且不创建运行 -> 全部 ready 时把 `projection.rephoto_sources` 传给现有隐藏快照创建/复用路径 -> 返回 `global_terminal_detail` 形状作为 `rephoto`。响应的顶层 `source_revision` 始终是构造表计来源版本。

- [ ] **Step 6: 运行服务和规模测试并提交**

```powershell
& 'C:\Users\Administrator\.config\superpowers\worktrees\module-manager-v3\collector-transfer-workbench\v2-api\.venv\Scripts\python.exe' -m pytest v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_scale.py -q
git add -- v2-api/app/services/collector_transfer.py v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_scale.py
git commit --only -m "feat: add bounded review workbench open" -- v2-api/app/services/collector_transfer.py v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_scale.py
```

Expected: zero failures；旧 `open_global_terminal` 测试继续通过，证明兼容逻辑没有退化。

### Task 3: 在每个采集器写入口加入服务器端审阅复检

**Files:**
- Modify: `v2-api/app/services/collector_transfer.py`
- Modify: `v2-api/tests/test_collector_transfer_service.py`
- Modify: `v2-api/tests/test_collector_transfer_postgres_integration.py`

**Interfaces:**
- Consumes: Task 2 的 `_terminal_review_bundle`、现有 `_lock_global_terminal_identity`、终端/运行/需求/实物的规范锁顺序。
- Produces: `_require_terminal_review_ready(run, terminal, client_source_revision="") -> TerminalReviewProjection`；`TerminalReviewRequiredError`; `TerminalNoConstructedMeterError`; `TerminalSourceChangedError`。

- [ ] **Step 1: 为五类写操作写零写入复检测试并确认 RED**

参数化现有服务夹具：先创建 ready 快照，再把任一构造表计改为 `UNREVIEWED` 或替换活动源照片，分别调用：

```python
@pytest.mark.parametrize(
    "operation",
    ["replace_missing", "rollback", "refresh", "complete_meter", "complete_collector"],
)
def test_every_collector_mutation_rechecks_terminal_review_gate(operation: str) -> None:
    before = mutation_fingerprint(session)
    make_constructed_group_not_ready(session, group_id="g-1")
    with pytest.raises(TerminalReviewRequiredError):
        invoke_operation(service, operation)
    assert mutation_fingerprint(session) == before
```

`mutation_fingerprint` 必须同时统计/摘要 `CollectorAssignment`, `CollectorRequirement`, `PhysicalCollector`, `CollectorWorkbenchItem`, `CollectorTransferRun.stats` 和审计事件。运行聚焦测试，Expected: FAIL，因为旧写路径只检查快照来源或局部状态。

- [ ] **Step 2: 在规范锁内实现统一复检**

`_require_terminal_review_ready` 只能在调用方已经按既有顺序锁定运行/终端身份后执行。它重新查询构造表计投影：

```python
if not projection.constructed_meters:
    raise TerminalNoConstructedMeterError()
if projection.hard_blocked:
    raise CollectorTerminalSourceBlockedError()
if projection.review_required_count:
    raise TerminalReviewRequiredError(projection.constructed_meters)
if stored_revision != projection.source_revision:
    raise TerminalSourceChangedError()
return projection
```

把调用加入 `replace_terminal_missing`, `rollback_assignment`, `refresh_global_terminal`, `set_workbench_item_status` 的 meter/collector 两条分支，以及遗留 `allocate` 对隐藏全局运行的拒绝路径。复检失败前不得刷新统计、写审计或改变任何行。

- [ ] **Step 3: 覆盖最终批准后解锁及并发源变化**

增加服务测试：最后一个构造表计审批前统一打开返回 locked，调用现有审阅持久化后重新打开，只有在两张活动照片、分类和当前条码证据都满足时才出现非空 `rephoto`。增加 PostgreSQL 集成测试：一个事务持有终端锁做分配，另一个事务修改审阅/照片；断言无死锁，后到者得到 `terminal_source_changed` 或 `terminal_review_required`，且池分配保持全有或全无。

Run:

```powershell
& 'C:\Users\Administrator\.config\superpowers\worktrees\module-manager-v3\collector-transfer-workbench\v2-api\.venv\Scripts\python.exe' -m pytest v2-api/tests/test_collector_transfer_service.py -k 'review_gate or final_approval or source_changed' -q
& 'C:\Users\Administrator\.config\superpowers\worktrees\module-manager-v3\collector-transfer-workbench\v2-api\.venv\Scripts\python.exe' -m pytest v2-api/tests/test_collector_transfer_postgres_integration.py -k 'review or lock_order' -q
```

Expected: PASS or documented PostgreSQL skips only when the integration DSN is unavailable; on the production-like PostgreSQL gate it must execute and pass, not skip.

- [ ] **Step 4: 提交写操作门禁**

```powershell
git add -- v2-api/app/services/collector_transfer.py v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_postgres_integration.py
git commit --only -m "fix: enforce terminal review gate on collector mutations" -- v2-api/app/services/collector_transfer.py v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_postgres_integration.py
```

### Task 4: 固化统一 API、正式审阅决定和管理员授权

**Files:**
- Modify: `v2-api/app/api/routes/collector_transfer.py`
- Modify: `v2-api/app/api/routes/groups.py`
- Modify: `v2-api/tests/test_collector_transfer_api.py`
- Modify: `v2-api/tests/test_data_center_review.py`
- Modify: `v2-api/tests/test_security.py`

**Interfaces:**
- Consumes: Task 2/3 的统一打开服务与错误类型；`PostgresStateRepository.review_group`；`require_admin`。
- Produces: `POST /collector-transfer/review-workbench/terminals/open`；`PATCH /groups/data-center/groups/{group_id}/review`；稳定错误 `terminal_not_found`, `terminal_has_no_constructed_meter`, `terminal_review_required`, `terminal_source_changed`。

- [ ] **Step 1: 写出统一 DTO 与稳定错误 API 测试并确认 RED**

统一打开只接受：

```json
{"terminal_key":"opaque-key","source_revision":"64-char-revision"}
```

明确拒绝 `project_id`、`terminal_code` 和其他额外字段。测试 locked 响应 `rephoto: null`，ready 响应 `rephoto` 含现有表计/采集器详情，409 错误详情包含已授权终端内的安全 `group_ids` 和阻断码。跨团队 key 一律映射 `terminal_not_found`，不能泄露资源存在性。

Run:

```powershell
& 'C:\Users\Administrator\.config\superpowers\worktrees\module-manager-v3\collector-transfer-workbench\v2-api\.venv\Scripts\python.exe' -m pytest v2-api/tests/test_collector_transfer_api.py -k 'review_workbench or terminal_review or terminal_source' -q
```

Expected: FAIL because the route and mappings do not exist.

- [ ] **Step 2: 实现 Pydantic 请求和错误映射**

```python
class OpenReviewWorkbenchTerminalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    terminal_key: str = Field(min_length=1, max_length=2048)
    source_revision: str = Field(default="", max_length=64)
```

新增路由必须调用 `call_admin_service`。例如资料组 `g-1` 缺少批准和条码证据时，`TerminalReviewRequiredError` 的 details 固定为 `{"group_ids": ["g-1"], "blockers": [{"group_id": "g-1", "codes": ["review_not_approved", "barcode_verification_required"]}]}`；只从当前团队已加载的 bundle 生成。

- [ ] **Step 3: 写出正式审阅决定接口测试并确认 RED**

```python
def test_admin_can_approve_data_center_group_and_audit_actor(client, admin_headers) -> None:
    response = client.patch(
        "/groups/data-center/groups/g-1/review",
        headers=admin_headers,
        json={"status": "approved", "note": "资料核对完成"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "approved"
    assert latest_review_event("g-1")["actor"] == "admin"


@pytest.mark.parametrize("status", ["approved", "incomplete", "exception"])
def test_constructor_cannot_decide_data_center_review(status, client, constructor_headers) -> None:
    before = repository_call_count()
    response = client.patch(
        "/groups/data-center/groups/g-1/review",
        headers=constructor_headers,
        json={"status": status, "note": "x"},
    )
    assert response.status_code == 403
    assert repository_call_count() == before
```

实现 `DataCenterReviewDecisionRequest(status: Literal["approved", "incomplete", "exception"], note: str, exception_note: str)`，以 token 中管理员用户名为 actor，调用 `review_group`，失效任务快照并返回规范资料组响应。

- [ ] **Step 4: 把整个采集器域收紧为管理员前置授权**

先写参数化测试，覆盖项目列表、库存查询、库存扫码、照片登记/读取、候选列表、统一打开、详情、替换、回滚、刷新、完成及遗留 run API。施工员每一项都必须 403，且在 `SessionLocal`、文件保存或服务方法之前结束。

实现时在 `service_for_request` 打开数据库会话前调用 `require_admin`；对直接打开 `SessionLocal` 或先保存上传文件的端点显式把 `require_admin(request)` 放到第一条业务语句。不要用仅前端隐藏替代 API 权限。

- [ ] **Step 5: 运行 API/安全矩阵并提交**

```powershell
& 'C:\Users\Administrator\.config\superpowers\worktrees\module-manager-v3\collector-transfer-workbench\v2-api\.venv\Scripts\python.exe' -m pytest v2-api/tests/test_collector_transfer_api.py v2-api/tests/test_data_center_review.py v2-api/tests/test_security.py -q
git add -- v2-api/app/api/routes/collector_transfer.py v2-api/app/api/routes/groups.py v2-api/tests/test_collector_transfer_api.py v2-api/tests/test_data_center_review.py v2-api/tests/test_security.py
git commit --only -m "feat: expose admin review rephoto api" -- v2-api/app/api/routes/collector_transfer.py v2-api/app/api/routes/groups.py v2-api/tests/test_collector_transfer_api.py v2-api/tests/test_data_center_review.py v2-api/tests/test_security.py
```

Expected: zero failures and explicit constructor-before-repository assertions.

### Task 5: 抽取可嵌入的数据中台审阅面板

**Files:**
- Create: `v2-web/src/components/data-center/DataCenterGroupReviewPanel.vue`
- Modify: `v2-web/src/components/data-center/DataCenterReviewDialog.vue`
- Create: `v2-web/src/components/__tests__/DataCenterGroupReviewPanel.spec.ts`
- Modify: `v2-web/src/api/types.ts`
- Modify: `v2-web/src/api/services.ts`

**Interfaces:**
- Consumes: 现有 `fetchDataCenterDetail`, `fetchGroupPhotoObjectUrl`, 字段修正、分类、重扫、框选、人工确认、异常/回退 API；Task 4 的正式审阅决定接口。
- Produces: `reviewDataCenterGroup(groupId, status, note, exceptionNote)`；组件 props `groupId`, `rephotoItem`, `defaultStage`; emits `updated`, `review-decided`。

- [ ] **Step 1: 写出嵌入面板生命周期测试并确认 RED**

使用 Vue Test Utils mock API，断言：切换 `groupId` 会 abort 旧详情和旧图片请求；迟到响应不能覆盖当前组；替换的 object URL 与卸载时全部 `URL.revokeObjectURL`；面板不创建 dialog；点击通过/资料不全只调用正式审阅接口并在完成后重新加载服务器详情。

```typescript
it('aborts stale detail and revokes every protected image url', async () => {
  const wrapper = mount(DataCenterGroupReviewPanel, { props: { groupId: 'g-1' } })
  await wrapper.setProps({ groupId: 'g-2' })
  resolveOldGroupAfterNewGroup()
  await flushPromises()
  expect(wrapper.text()).toContain('g-2')
  expect(wrapper.text()).not.toContain('g-1')
  wrapper.unmount()
  expect(URL.revokeObjectURL).toHaveBeenCalledTimes(createdObjectUrlCount())
})
```

Run:

```powershell
Push-Location v2-web
pnpm vitest run src/components/__tests__/DataCenterGroupReviewPanel.spec.ts
Pop-Location
```

Expected: FAIL because the component does not exist.

- [ ] **Step 2: 建立正式审阅客户端和显示类型**

给 `DataCenterRow` 增加 `reviewStatus: string`，映射后端 `status`；新增：

```typescript
export async function reviewDataCenterGroup(
  groupId: string,
  status: 'approved' | 'incomplete' | 'exception',
  note = '',
  exceptionNote = '',
): Promise<MaterialGroup>
```

请求固定发送 `/groups/data-center/groups/${encodeURIComponent(groupId)}/review`，actor 不从客户端传入。

- [ ] **Step 3: 抽取资料组面板并保留全部能力**

组件固定 props/emits：

```typescript
const props = withDefaults(defineProps<{
  groupId: string
  rephotoItem?: GlobalMeterInstallWorkbenchRow | null
  defaultStage?: 'source' | 'rephoto'
}>(), { rephotoItem: null, defaultStage: 'source' })

const emit = defineEmits<{
  (event: 'updated', detail: DataCenterDetail): void
  (event: 'review-decided', status: 'approved' | 'incomplete' | 'exception'): void
}>()
```

从旧 dialog 搬入受保护图片、图片分类、字段修正、重新扫码、框选扫码、人工确认、异常退回、回退和审计代码；新增通过与资料不全按钮。`rephotoItem` 非空时，中心区域提供“源资料/翻拍位置”切换，翻拍位置严格显示两个 slot 与表号/模块号条码。组件内不得使用 `navigator.mediaDevices`、`BarcodeDetector` 或甲方平台域名。

- [ ] **Step 4: 把旧 dialog 改成薄包装并验证无回归**

未匹配分支继续使用 `UnmatchedReviewDialog`；资料组分支只负责 `el-dialog`、标题、关闭和：

```vue
<DataCenterGroupReviewPanel
  v-if="props.row?.kind === 'group'"
  :group-id="props.row.id"
  @updated="emit('updated')"
  @review-decided="emit('updated')"
/>
```

运行组件测试、类型检查。Expected: 面板测试和现有 `ReviewImageInspector` 测试通过。

- [ ] **Step 5: 提交审阅面板**

```powershell
git add -- v2-web/src/components/data-center/DataCenterGroupReviewPanel.vue v2-web/src/components/data-center/DataCenterReviewDialog.vue v2-web/src/components/__tests__/DataCenterGroupReviewPanel.spec.ts v2-web/src/api/types.ts v2-web/src/api/services.ts
git commit --only -m "refactor: extract reusable group review panel" -- v2-web/src/components/data-center/DataCenterGroupReviewPanel.vue v2-web/src/components/data-center/DataCenterReviewDialog.vue v2-web/src/components/__tests__/DataCenterGroupReviewPanel.spec.ts v2-web/src/api/types.ts v2-web/src/api/services.ts
```

### Task 6: 建立三栏审阅与翻拍工作台

**Files:**
- Create: `v2-web/src/views/ReviewRephotoWorkbenchView.vue`
- Create: `v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts`
- Modify: `v2-web/src/api/types.ts`
- Modify: `v2-web/src/api/services.ts`
- Modify: `v2-web/src/features/collectorTransfer/state.ts`
- Modify: `v2-web/tests/collector-transfer-state.test.ts`
- Delete after GREEN: `v2-web/src/views/CollectorWorkbenchView.vue`
- Delete after GREEN: `v2-web/src/views/__tests__/CollectorWorkbenchView.spec.ts`

**Interfaces:**
- Consumes: Task 4 的候选/统一打开 API，Task 5 的 `DataCenterGroupReviewPanel`，现有 replacement/rollback/refresh/completion API 和 Code128 组件。
- Produces: 扩展的 `GlobalCollectorTerminalCandidate`, `ReviewWorkbenchMeter`, `ReviewWorkbenchOpenResult`, `canMutateRephoto(openResult)`, `/review-workbench` 页面。

- [ ] **Step 1: 扩展前端 DTO 和纯状态测试并确认 RED**

固定类型：

```typescript
export type GlobalCollectorTerminalState =
  | 'no_construction' | 'needs_review' | 'blocked' | 'needs_replacement'
  | 'pool_shortage' | 'ready' | 'in_progress' | 'completed'

export type ReviewWorkbenchBlocker = { group_id: string; codes: string[] }
export type ReviewWorkbenchCandidateCounts = {
  constructed_meter_count: number
  unconstructed_meter_count: number
  review_ready_count: number
  review_required_count: number
}
export type ReviewWorkbenchMeter = {
  group_id: string
  meter_no: string
  module_no: string
  collector_no: string
  construction_state: 'constructed' | 'unconstructed'
  review_status: string
  review_ready: boolean
  blockers: string[]
}
export type ReviewWorkbenchOpenResult = {
  terminal: { terminal_key: string; project_id: string; terminal_code: string; installation_address: string }
  workflow_state: GlobalCollectorTerminalState
  source_revision: string
  constructed_meter_count: number
  unconstructed_meter_count: number
  review_ready_count: number
  review_required_count: number
  review_blockers: ReviewWorkbenchBlocker[]
  meters: ReviewWorkbenchMeter[]
  rephoto: GlobalCollectorTerminalDetail | null
}
```

纯状态测试要求 `canMutateRephoto` 只在 `rephoto !== null && source_changed === false` 时为真；未施工行永远不进入 rephoto item count；固定工作流中文标签。

- [ ] **Step 2: 实现统一客户端并确认状态测试 GREEN**

`openReviewWorkbenchTerminal` 只发送 `terminal_key` 和 `source_revision`。保留已有写客户端，删除旧 `openGlobalCollectorTerminal` 的 UI 调用后再决定是否保留兼容导出。运行：

```powershell
Push-Location v2-web
node --test --experimental-strip-types tests/collector-transfer-state.test.ts
Pop-Location
```

- [ ] **Step 3: 写出页面整终端锁测试并确认 RED**

测试挂载页面并 mock 两次统一打开：第一次一块 ready、一块未 ready、一块未施工，第二次最终批准后全部 ready。断言第一次所有替换、回滚、刷新、meter/collector 完成控件都不存在或 disabled；未施工行显示精确文案；第二次服务器响应非空 `rephoto` 后同一页面展示每个构造表计恰好两个 slot 和去重采集器。

还必须用七个独立测试覆盖：页面文本显示 `terminal_code`，POST body 只含 opaque `terminal_key`/revision；先发搜索的迟到响应不能覆盖后发结果；每次 `review-decided` 后统一 open 调用数增加 1；两个构造表共享采集器时只渲染一个 `.collector-card`；shortage 时不调用 completion、替换成功后可 rollback 并回到 missing；`source_changed` 响应后所有 `.rephoto-mutation` 变 disabled；mock `navigator.mediaDevices.getUserMedia` 和全局 fetch 后断言相机调用为 0 且所有 URL 都是本站 API。

Run:

```powershell
Push-Location v2-web
pnpm vitest run --config tests/collector-transfer.vitest.config.ts src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts
Pop-Location
```

Expected: FAIL because the page does not exist.

- [ ] **Step 4: 实现三栏桌面与窄屏布局**

页面结构固定为：左侧构造表计队列与灰化未施工段；中间嵌入审阅面板的源照片/解锁后两张翻拍位置；右侧审阅动作、终端锁和审计。解锁后在三栏下方显示终端级去重采集器段，沿用 `present`, `missing`, `replaced`、随机全部替换、回滚与完成交互。

搜索必须 debounce/分页并使用既有 `latestRequestGate` 或等价 request serial；选中表计、审阅 mutation、替换/回滚/完成后都重新打开当前终端，只有新服务器响应能改变锁状态。

页面读取 `route.query.group_id` 时，以该 group ID 发起一次候选搜索，自动打开包含该组的唯一授权终端并选中对应表计；零结果或多义结果只显示安全提示，不猜测项目。页面模板不得出现项目选择器、批次选择器或运行选择器。

390x844 下变为单列顺序：终端摘要 -> 表计队列 -> 当前资料/翻拍 -> 审阅动作 -> 采集器；不得横向溢出，也不得隐藏关键锁定原因。

- [ ] **Step 5: 运行页面矩阵并删除旧页面**

```powershell
Push-Location v2-web
pnpm run test:collector-transfer
pnpm run test:components
pnpm run type-check
Pop-Location
```

全部 GREEN 后删除旧 `CollectorWorkbenchView.vue` 及其专用 spec；新页面 spec 必须继承旧页面的终端搜索、替换、回滚、完成、shortage 与 stale-response 断言，不能通过删测试减少覆盖。

- [ ] **Step 6: 提交统一页面**

```powershell
git add -- v2-web/src/views/ReviewRephotoWorkbenchView.vue v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts v2-web/src/api/types.ts v2-web/src/api/services.ts v2-web/src/features/collectorTransfer/state.ts v2-web/tests/collector-transfer-state.test.ts
git add -u -- v2-web/src/views/CollectorWorkbenchView.vue v2-web/src/views/__tests__/CollectorWorkbenchView.spec.ts
git commit -m "feat: combine terminal review and rephoto workbench"
```

### Task 7: 收敛路由、导航和施工员权限

**Files:**
- Modify: `v2-web/src/router/index.ts`
- Modify: `v2-web/src/router/staticPages.ts`
- Modify: `v2-web/src/layouts/AppLayout.vue`
- Modify: `v2-web/src/views/__tests__/CollectorInventoryRouting.spec.ts`

**Interfaces:**
- Consumes: Task 6 的 `ReviewRephotoWorkbenchView.vue`；`defaultRouteForRole`；静态页角色元数据。
- Produces: 规范 `/review-workbench`；三个兼容重定向；施工员全局路由门禁；管理员导航 `审阅与翻拍工作台`。

- [ ] **Step 1: 写出角色和兼容路由测试并确认 RED**

断言：

```typescript
expect(resolve('/collector-workbench').redirect).toBe('/review-workbench')
expect(resolve('/collector-batches').redirect).toBe('/review-workbench')
expect(resolve('/review/g-123').redirect).toEqual({ path: '/review-workbench', query: { group_id: 'g-123' } })
```

使用施工员 auth 初始化内存 router，逐个访问 `/`, `/project-board`, `/global-search`, `/collector-inventory`, `/review-workbench`, `/projects`, `/checklists`, `/account-management`, `/sync-config`，最终都必须是 `/construction`；导航只渲染“施工采集”。管理员仍可访问 `/construction` 和全部管理员页。

- [ ] **Step 2: 实现规范页和全局施工员门禁**

把静态 key `collector-workbench` 改为 `review-workbench`，roles 只含 `admin`，标题为 `审阅与翻拍工作台`。在 auth hydrate 完成后，如果角色集合含 `constructor` 且不含 `admin`，除 `/construction` 与 `/login` 外统一返回 `{ name: 'construction' }`；不要依赖每条遗留 route 是否正确填写 meta。

兼容路由固定为：

```typescript
{ path: 'collector-workbench', redirect: '/review-workbench' }
{ path: 'collector-batches', redirect: '/review-workbench' }
{
  path: 'review/:groupId',
  redirect: (to) => ({ path: '/review-workbench', query: { group_id: String(to.params.groupId || '') } }),
}
```

数据中台当前保存链接继续使用自己的 dialog，不改 `/global-search?group_id=g-123&page=1&page_size=20&review=1` 行为。

- [ ] **Step 3: 运行路由/类型/构建测试并提交**

```powershell
Push-Location v2-web
pnpm vitest run --config tests/collector-transfer.vitest.config.ts src/views/__tests__/CollectorInventoryRouting.spec.ts
pnpm run type-check
pnpm run build
Pop-Location
git add -- v2-web/src/router/index.ts v2-web/src/router/staticPages.ts v2-web/src/layouts/AppLayout.vue v2-web/src/views/__tests__/CollectorInventoryRouting.spec.ts
git commit --only -m "fix: restrict constructors to construction collection" -- v2-web/src/router/index.ts v2-web/src/router/staticPages.ts v2-web/src/layouts/AppLayout.vue v2-web/src/views/__tests__/CollectorInventoryRouting.spec.ts
```

### Task 8: 完成后端集成、性能和需求级回归

**Files:**
- Modify: `v2-api/tests/test_collector_transfer_service.py`
- Modify: `v2-api/tests/test_collector_transfer_api.py`
- Modify: `v2-api/tests/test_collector_transfer_postgres_integration.py`
- Modify: `v2-api/tests/test_collector_transfer_scale.py`
- Modify if a proven defect exists: `v2-api/app/services/collector_transfer.py`
- Modify if a proven defect exists: `v2-api/app/api/routes/collector_transfer.py`

**Interfaces:**
- Consumes: Tasks 1-7 的完整实现。
- Produces: 混合终端、并发、租户、有界查询和旧行为兼容的完整零失败证据。

- [ ] **Step 1: 建立逐条验收参数矩阵**

矩阵至少包含：全未施工、混合且需审阅、混合全部通过、地址冲突、重复 slot、无模块号、条码证据失效、同号实物、一个缺失、多个缺失池不足、共享采集器、未进展源变化、已进展源变化、跨项目同终端号、跨团队 key。每行断言 workflow、计数、是否创建运行、是否可写、分配数、审计数。

- [ ] **Step 2: 运行完整 collector 后端矩阵**

```powershell
& 'C:\Users\Administrator\.config\superpowers\worktrees\module-manager-v3\collector-transfer-workbench\v2-api\.venv\Scripts\python.exe' -m pytest v2-api/tests/test_terminal_review_domain.py v2-api/tests/test_collector_transfer_domain.py v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_api.py v2-api/tests/test_collector_transfer_postgres_integration.py v2-api/tests/test_collector_transfer_scale.py v2-api/tests/test_data_center_review.py v2-api/tests/test_models.py v2-api/tests/test_migrations.py -q
```

Expected: zero failures；Alembic 仍为 `20260824_0016`；PostgreSQL DSN 可用时并发测试不得 skip。

- [ ] **Step 3: 检查查询形状和锁顺序**

对 `list_global_terminals`, `_terminal_review_bundle`, `open_review_workbench_terminal` 和五个写入口做调用链复核。确认候选不 materialize 源 ORM、打开只查询一个团队终端、所有写入口遵守相同 advisory/run/terminal/requirement/physical 顺序，且异常路径 rollback session。

- [ ] **Step 4: 只修复测试证明的问题并重新跑矩阵**

每个失败先保留失败测试，再做最小修复。重复 Step 2，直到得到完整零失败总结；不能用放宽断言、加 sleep 或删测试换 GREEN。

- [ ] **Step 5: 提交集成门禁**

```powershell
git add -- v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_api.py v2-api/tests/test_collector_transfer_postgres_integration.py v2-api/tests/test_collector_transfer_scale.py
git add -- v2-api/app/services/collector_transfer.py v2-api/app/api/routes/collector_transfer.py
git commit --only -m "test: gate unified review rephoto workflow" -- v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_api.py v2-api/tests/test_collector_transfer_postgres_integration.py v2-api/tests/test_collector_transfer_scale.py v2-api/app/services/collector_transfer.py v2-api/app/api/routes/collector_transfer.py
```

若生产文件没有修复，不要把它们放进该提交；按 `git diff --name-only` 缩小显式路径。

### Task 9: 建立 V3.2.10 版本与不可变发布门禁

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/AGENT_REQUIRED_READING.md`
- Modify: `docs/sop/README.md`
- Modify: `RELEASE_MANIFEST.md`
- Modify: `v2-api/pyproject.toml`
- Modify: `v2-api/app/main.py`
- Modify: `v2-api/app/services/ops_status.py`
- Modify: `v2-api/scripts/verify_v3_1_release.py`
- Modify: `v2-api/tests/test_v3_1_release.py`
- Modify: `v2-web/package.json`
- Modify: `v2-web/index.html`
- Modify: `v2-web/src/components/AppLayout.vue`
- Modify: `v2-web/src/version.json`
- Modify: `v2-web/src/constants/releaseNotes.ts`
- Modify: `scripts/build-client-release.ps1`
- Modify: `scripts/verify-client-release.py`
- Modify: `scripts/verify_release_sop.py`
- Create: `scripts/verify_v3_2_10_release.py`
- Create: `scripts/test_verify_v3_2_10_release.py`
- Modify: `scripts/test_verify_client_release.py`
- Modify: `scripts/test_verify_release_sop.py`
- Restore unchanged from production proof commit `8a4bcd6`: `ops/releases/V3.2.9.md`
- Create: `ops/releases/V3.2.10.md`

**Interfaces:**
- Consumes: 完成的功能与测试提交；生产证明提交 `8a4bcd6` 中的 `ops/releases/V3.2.9.md` 及已发布 V3.2.9 门禁作为只读基线。
- Produces: 全部运行时版本 `3.2.10`、候选 `V3.2.10`、分支 `production/V3/3.2.10`、包名 `module-manager-v2-server-3.2.10.zip` 和三阶段 verifier。

- [ ] **Step 1: 复制并改写 V3.2.10 verifier 测试，确认 RED**

先从生产证明提交 `8a4bcd6` 原样恢复 `ops/releases/V3.2.9.md`，并用 blob hash/字节比较锁定其内容；保留 V3.2.9 已发布记录、tag 和历史验证行为原样。新建 3.2.10 测试，要求：准确版本/分支/包/记录；新领域、API、页面、角色和 V3.2.9 盘点扫码回归测试必须存在并执行；迁移头不变；包禁止 `.env`, uploads, backups, caches, repository metadata, `uv.lock`；V3.2.9 ZIP 不能满足 3.2.10。

```powershell
& 'C:\Users\Administrator\.config\superpowers\worktrees\module-manager-v3\collector-transfer-workbench\v2-api\.venv\Scripts\python.exe' -m pytest scripts/test_verify_v3_2_10_release.py scripts/test_verify_client_release.py scripts/test_verify_release_sop.py -q
```

Expected: FAIL before the V3.2.10 facts and verifier exist.

- [ ] **Step 2: 更新全部版本事实和候选记录**

`AGENTS.md`、`docs/AGENT_REQUIRED_READING.md` 和 `docs/sop/README.md` 统一标记当前已部署 `V3.2.9`、当前候选 `V3.2.10`、候选分支 `production/V3/3.2.10`。运行时、manifest、Web、发布说明全部改为 3.2.10。`ops/releases/V3.2.10.md` 先记录功能、测试栏目、Alembic head、包路径、回滚目标 `/opt/module-manager-v2/releases/v3.2.9-20260826T075447Z` 和所有生产字段为 pending；不能预填成功证据。`ops/releases/V3.2.9.md` 必须与 `8a4bcd6` 中的 blob 字节一致，不得为候选版本改写历史事实。

- [ ] **Step 3: 实现 source/package/attestation verifier**

`verify_v3_2_10_release.py` 延续已上线版本的源码绑定、CRC、路径大小写/重复、Vue 资产绑定和 attestation 规则；新增必需文件/测试 marker 及盘点 Quagga-first 回归 marker。`build-client-release.ps1` 只允许当前分支构建 3.2.10，并调用新的 verifier；`verify-client-release.py` 根据 manifest 版本加载归档内 3.2.10 verifier，不能改写 V3.2.9 的已发布记录。

- [ ] **Step 4: 运行发布源码门禁并提交**

```powershell
& 'C:\Users\Administrator\.config\superpowers\worktrees\module-manager-v3\collector-transfer-workbench\v2-api\.venv\Scripts\python.exe' -m pytest scripts/test_verify_v3_2_10_release.py scripts/test_verify_client_release.py scripts/test_verify_release_sop.py v2-api/tests/test_v3_1_release.py -q
& 'C:\Users\Administrator\.config\superpowers\worktrees\module-manager-v3\collector-transfer-workbench\v2-api\.venv\Scripts\python.exe' scripts/verify_v3_2_10_release.py --phase source
& 'C:\Users\Administrator\.config\superpowers\worktrees\module-manager-v3\collector-transfer-workbench\v2-api\.venv\Scripts\python.exe' scripts/verify_release_sop.py --version V3.2.10 --phase source
git diff --check
```

Expected: all pass。

```powershell
git add -- AGENTS.md docs/AGENT_REQUIRED_READING.md docs/sop/README.md RELEASE_MANIFEST.md v2-api/pyproject.toml v2-api/app/main.py v2-api/app/services/ops_status.py v2-api/scripts/verify_v3_1_release.py v2-api/tests/test_v3_1_release.py v2-web/package.json v2-web/index.html v2-web/src/components/AppLayout.vue v2-web/src/version.json v2-web/src/constants/releaseNotes.ts scripts/build-client-release.ps1 scripts/verify-client-release.py scripts/verify_release_sop.py scripts/verify_v3_2_10_release.py scripts/test_verify_v3_2_10_release.py scripts/test_verify_client_release.py scripts/test_verify_release_sop.py ops/releases/V3.2.9.md ops/releases/V3.2.10.md
git commit --only -m "release: prepare V3.2.10 review rephoto workbench" -- AGENTS.md docs/AGENT_REQUIRED_READING.md docs/sop/README.md RELEASE_MANIFEST.md v2-api/pyproject.toml v2-api/app/main.py v2-api/app/services/ops_status.py v2-api/scripts/verify_v3_1_release.py v2-api/tests/test_v3_1_release.py v2-web/package.json v2-web/index.html v2-web/src/components/AppLayout.vue v2-web/src/version.json v2-web/src/constants/releaseNotes.ts scripts/build-client-release.ps1 scripts/verify-client-release.py scripts/verify_release_sop.py scripts/verify_v3_2_10_release.py scripts/test_verify_v3_2_10_release.py scripts/test_verify_client_release.py scripts/test_verify_release_sop.py ops/releases/V3.2.9.md ops/releases/V3.2.10.md
```

### Task 10: 全量验证、渲染验收并构建源码绑定包

**Files:**
- Modify: `v2-api/app/static/vue/**`
- Modify: `ops/releases/V3.2.10.md`
- Generate: `build/server-release/module-manager-v2-server-3.2.10.zip`

**Interfaces:**
- Consumes: Tasks 1-9 的最终提交。
- Produces: 最终源码 commit、全量零失败证据、受源 commit 绑定的 ZIP 与 SHA256。

- [ ] **Step 1: 运行后端聚焦和全仓测试**

```powershell
$python = 'C:\Users\Administrator\.config\superpowers\worktrees\module-manager-v3\collector-transfer-workbench\v2-api\.venv\Scripts\python.exe'
& $python -m pytest v2-api/tests/test_terminal_review_domain.py v2-api/tests/test_collector_transfer_domain.py v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_api.py v2-api/tests/test_collector_transfer_postgres_integration.py v2-api/tests/test_collector_transfer_scale.py v2-api/tests/test_data_center_review.py v2-api/tests/test_security.py v2-api/tests/test_models.py v2-api/tests/test_migrations.py -q
& $python -m pytest v2-api/tests scripts -q
```

记录精确 passed/skipped 数；任何失败或无总结都停止打包。

- [ ] **Step 2: 运行全部前端测试、类型和生产构建**

```powershell
Push-Location v2-web
pnpm run test:collector-transfer
pnpm run test:components
pnpm run type-check
pnpm run build
Pop-Location
```

Expected: 所有测试、类型和 build 明确通过。

- [ ] **Step 3: 做本地桌面和 390x844 浏览器验收**

用测试数据启动实际 FastAPI/Vue 资产，验证管理员 `/review-workbench`：搜索可读终端但请求 opaque key；三栏；构造/未施工分段；未完成审阅时全锁；最后批准后同页出现两个表计位置；共享采集器只出现一次；替换/回滚/完成和 source_changed。验证施工员登录后只有施工导航，直接 URL 被送回 `/construction`，API 为 403。检查控制台和网络：零错误、零相机请求、零甲方平台请求。

- [ ] **Step 4: 重建并提交跟踪的 Vue 资产和本地证据**

使用仓库现有前端同步路径把最终 build 复制到 `v2-api/app/static/vue`。在 `ops/releases/V3.2.10.md` 记录精确命令、通过/跳过数和本地 viewport 证据，生产字段继续 pending。

```powershell
git add -- v2-api/app/static/vue ops/releases/V3.2.10.md
git commit --only -m "release: build V3.2.10 web assets" -- v2-api/app/static/vue ops/releases/V3.2.10.md
```

- [ ] **Step 5: 从最终 commit 重新跑 source gates**

```powershell
& $python scripts/verify_v3_2_10_release.py --phase source
& $python scripts/verify_release_sop.py --version V3.2.10 --phase source
git diff --check
git status --short
```

Expected: gates pass；状态干净，或最多只显示未跟踪受保护 `v2-api/uv.lock`，该文件不得被处理。

- [ ] **Step 6: 构建新的不可变 ZIP 并验证所有绑定**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build-client-release.ps1 -Version 3.2.10
& $python scripts/verify-client-release.py build/server-release/module-manager-v2-server-3.2.10.zip
& $python scripts/verify_v3_2_10_release.py --phase package --package build/server-release/module-manager-v2-server-3.2.10.zip
Get-FileHash -Algorithm SHA256 -LiteralPath build/server-release/module-manager-v2-server-3.2.10.zip
```

打开 ZIP 验证 `SOURCE_COMMIT` 等于最终 HEAD、根 `RELEASE_MANIFEST.md` 字节满足 EOL 规则、Vue `version.json` 覆盖所有 asset、CRC/path/case/duplicate 全过，并且没有 `.env`、uploads、backups、cache、`.git` 或 `uv.lock`。

- [ ] **Step 7: 冻结候选并记录外部证据**

把最终 HEAD、ZIP SHA256、文件长度和验证器输出保存到仓库外 `C:\Users\Administrator\Documents\module-manager-production-backups\V3.2.10-candidate-evidence.txt`。构包后不得修改跟踪文件；任何改动都必须重新 commit、重新全量验证和重新构包。

### Task 11: 新备份、不可变生产发布、回滚和验收

**Files:**
- Modify only after successful production acceptance: `ops/releases/V3.2.10.md`
- Local recovery root: `Join-Path 'C:\Users\Administrator\Documents\module-manager-production-backups' (Get-Date -Format 'yyyyMMdd-HHmmss')`，由下面 PowerShell 变量创建并打印准确路径。

**Interfaces:**
- Consumes: Task 10 的已验证 ZIP/SHA256/commit，服务器 `root@www.sgcc.online`，密钥 `C:\Users\Administrator\Downloads\XXXXXX.pem`，当前 rollback `/opt/module-manager-v2/releases/v3.2.9-20260826T075447Z`。
- Produces: 新的服务器路径 `release_dir="/opt/module-manager-v2/releases/v3.2.10-$release_stamp"`（`release_stamp=$(date -u +%Y%m%dT%H%M%SZ)`）、可恢复本地备份、真实 Uvicorn listener、只读业务验收、原子回滚证明和最终 attestation。

- [ ] **Step 1: 读取生产现状并冻结回滚边界**

用不打印秘密的 SSH 命令记录：`readlink -f /opt/module-manager-v2/current`、版本/commit、Alembic current/head、主服务/维护 worker/timer 状态、`127.0.0.1:8000` 实际 listener/PID、`/health`、磁盘/内存/swap、PostgreSQL 活动和 retained releases。要求当前仍是 `/opt/module-manager-v2/releases/v3.2.9-20260826T075447Z`、版本 3.2.9、head `20260824_0016`。SSH、数据库、磁盘或 listener 不稳定立即停止；本发布不清理任何 release 或 backup。

- [ ] **Step 2: 创建并验证新的本地流式备份**

```powershell
$key = 'C:\Users\Administrator\Downloads\XXXXXX.pem'
$server = 'root@www.sgcc.online'
$backupStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupRoot = Join-Path 'C:\Users\Administrator\Documents\module-manager-production-backups' $backupStamp
New-Item -ItemType Directory -Path $backupRoot | Out-Null
$backupRoot
```

通过 SSH 流式保存当前 symlink/release metadata/checksum、受限权限 `.env`、`pg_dump -Fc`、schema-only SQL、`data.tar.gz`、`uploads.tar.gz` 到 `$backupRoot`，不在远端 `/tmp` 留明文秘密。逐项验证 SHA256、`pg_restore -l`、非空 schema、tar 完整列表和源 release metadata；记录精确 rollback 目录后才能上传。

- [ ] **Step 3: 上传并准备新的不可变 release**

只上传 `module-manager-v2-server-3.2.10.zip`，比较本地/服务器 SHA256。在服务器用 UTC 时间创建全新 `/opt/module-manager-v2/releases/v3.2.10-$release_stamp`，禁止覆盖任何同名路径；解压、`unzip -t`、恢复 `.env` 链接/权限但不打印内容、安装依赖、设置 owner/group 和 `chmod -R g-w,g+rX`，以 `modulemgr` 导入 Pillow 与 `app.main`，运行归档 verifier，确认 Alembic 仍是 `20260824_0016`。

- [ ] **Step 4: 原子切换并证明真实监听**

原子重指 `current`，重启主服务；循环检查直到 Uvicorn 确实监听 `127.0.0.1:8000`，不能只相信 systemd `active`。要求本机与公网 `/health` 均 HTTP 200/version 3.2.10，`/project-board` 与 `/review-workbench` 可达，三个旧 URL 收敛到规范页。任一失败立即把 symlink 原子恢复到记录的 V3.2.9 目录并重启、等待旧 listener/health 恢复。

- [ ] **Step 5: 做不修改真实业务数据的生产验收**

管理员浏览器验证规范页面、导航和网络。用已认证只读候选查询确认分页/计数/可读 label/opaque key。只选择一个 `needs_review` 或 `no_construction` 终端执行统一打开，并在调用前后比较隐藏 run、assignment、requirement、workbench item、audit 数量完全不变；没有这种安全终端则跳过 open，并记录只读候选证据。除非用户另行明确指定测试终端，不审批真实资料、不分配真实采集器、不回滚、不刷新或完成翻拍项。

施工员账号验证只有施工采集导航，直接访问 `/review-workbench`, `/collector-inventory`, `/global-search`, `/projects`, `/account-management`, `/sync-config` 均回到 `/construction`；同账号直接调用审阅/统一打开/库存/采集器 API 全部 403，且生产数据库计数不变。浏览器网络不得出现 camera API 或甲方平台请求。

- [ ] **Step 6: 恢复维护服务并短时观察**

仅在 Step 4-5 全通过后，把维护 worker/timer 恢复到 Step 1 捕获的 enabled/active 状态。至少观察一个维护周期，重复检查 listener、health、PostgreSQL session、RSS/内存、磁盘和 journal；restart、listener 丢失、session 持续增长或 OOM 都阻止验收并触发回滚评估。

- [ ] **Step 7: 执行可回滚性核对**

不实际扰动健康生产时，用只读方式核对 V3.2.9 rollback 目录、服务 unit、`.env`、备份清单和恢复命令。若 Step 4-6 发生任何健康、授权、数据完整性或工作台失败，实际执行原子 symlink 回滚到 `/opt/module-manager-v2/releases/v3.2.9-20260826T075447Z`，等待 3.2.9 listener/health，保持数据库 head 不变，并记录失败证据；不能留在半切换状态。

- [ ] **Step 8: 写入最终 attestation 并逐条复核规格**

把 source commit、本地/服务器 ZIP SHA256、备份路径及验证、release/rollback 目录、Alembic head、listener/health、路由、管理员/施工员权限、零写入终端证据、无相机/甲方请求、维护状态和观察结果写入 `ops/releases/V3.2.10.md`。

```powershell
& $python scripts/verify_v3_2_10_release.py --phase attestation
& $python scripts/verify_release_sop.py --version V3.2.10 --phase attestation
git add -- ops/releases/V3.2.10.md AGENTS.md
git commit --only -m "release: attest V3.2.10 unified review workbench" -- ops/releases/V3.2.10.md AGENTS.md
```

只有所有证据真实存在后，才把 `AGENTS.md` 当前生产版本更新为 V3.2.10 并清空候选标记。最后重新核对生产 current/commit/hash、listener、health、head、页面、权限、维护服务、日志/资源、回滚目录、本地备份和 `git status`。

---

## Completion Audit

完成时逐项给出证据，不接受“代码已写”作为完成：

1. 管理员按终端搜索，并在同页看到全部表计。
2. 未施工表计灰化显示，既不阻塞，也不进入来源版本或翻拍/采集器需求。
3. 每块已施工表计都经过服务器端状态、身份、两张活动照片、分类、当前条码证据和异常/地址检查。
4. 任一已施工表计未 ready 时，全部翻拍/替换/回滚/刷新/完成入口前后端都锁定。
5. 全部 ready 后，每块已施工表计恰好两个新装位置，终端采集器去重且保持 present/missing/replaced。
6. 同号实物无网站照片也能直接翻拍；随机替换一次性、项目/团队隔离、池不足零写入。
7. 审阅、字段/照片/条码动作、替换、回滚、刷新和完成均保留 actor/time/before/after 审计。
8. 施工员只有施工采集页面，所有相关 API 在存储访问前 403；管理员仍可支持施工页。
9. `/collector-workbench`, `/collector-batches`, `/review/:groupId` 收敛到 `/review-workbench`，数据中台保存链接不受损。
10. 本地、PostgreSQL 并发、全仓、类型、生产构建、桌面/390x844、包绑定、生产、回滚和逐条规格验证全部有零失败或明确安全跳过证据。
