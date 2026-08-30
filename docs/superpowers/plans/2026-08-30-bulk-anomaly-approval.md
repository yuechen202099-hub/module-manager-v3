# Bulk Anomaly Approval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让管理员在正式通过当前表计资料组时，一次确认并原子关闭该资料组全部未关闭异常。

**Architecture:** 扩展现有 `PATCH /groups/data-center/groups/{group_id}/review` 合约，增加默认关闭的 `resolve_all_anomalies`。JSON 与 PostgreSQL 仓库均在现有正式通过事务中重算异常、写入逐项解决记录及聚合审计，再完成正式通过；Vue 只负责在存在当前异常时弹窗并传递标志。

**Tech Stack:** FastAPI、Pydantic、SQLAlchemy、Vue 3、TypeScript、Element Plus、pytest、Vitest

**Spec:** `docs/superpowers/specs/2026-08-30-bulk-anomaly-approval.md`

## Global Constraints

- 版本从 V3.2.20 升至 V3.2.21。
- 仅管理员可使用，不放宽现有路由权限。
- 只修改当前资料组；不修改数据库结构、生产数据或 OSS 对象。
- 不带批量确认标志时保持原有异常阻断。
- 每项异常和聚合动作都必须留痕。

---

### Task 1: 后端正式通过原子批量确认

**Files:**
- Modify: `v2-api/app/api/routes/groups.py`
- Modify: `v2-api/app/services/state_repository.py`
- Modify: `v2-api/app/services/local_simulation.py`
- Test: `v2-api/tests/test_data_center_review.py`
- Test: `v2-api/tests/test_state_repository.py`

**Interfaces:**
- Consumes: 当前异常生成函数 `data_center_service.group_anomalies(group)` 和解决记录键 `ANOMALY_RESOLUTIONS_KEY`。
- Produces: `review_group(..., resolve_all_anomalies: bool = False, expected_open_anomalies: dict[str, str] | None = None, source_page: str = "review_rephoto_workbench")`；请求字段 `resolve_all_anomalies`、`expected_open_anomalies` 与 `source_page`。

- [ ] **Step 1: Write the failing tests**

增加 JSON 与 PostgreSQL 行为测试：默认仍拒绝未关闭异常；`resolve_all_anomalies=True` 且证据快照一致时返回 `approved`，所有当前异常为 `resolved` 且操作者一致，写入一次聚合审计；证据快照变化时返回冲突且不写任何状态。增加路由测试，确认管理员身份来自服务端且请求标志能传到仓库。

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest v2-api/tests/test_data_center_review.py v2-api/tests/test_state_repository.py -k "bulk or approved_review" -q`

Expected: FAIL，因为请求模型和 `review_group` 尚不接受 `resolve_all_anomalies`。

- [ ] **Step 3: Write minimal implementation**

请求模型增加：

```python
resolve_all_anomalies: bool = False
expected_open_anomalies: dict[str, str] = Field(default_factory=dict)
source_page: str = "review_rephoto_workbench"
```

仓库接口增加：

```python
def review_group(
    self,
    group_id: str,
    status: str,
    reviewer: str,
    note: str = "",
    exception_note: str = "",
    *,
    resolve_all_anomalies: bool = False,
    expected_open_anomalies: Mapping[str, str] | None = None,
    source_page: str = "review_rephoto_workbench",
) -> dict[str, Any]:
```

加锁并重算 `unresolved` 后，先将其代码和证据指纹与 `expected_open_anomalies` 精确比较；不一致抛出冲突且回滚。只有 `status == "approved" and resolve_all_anomalies` 且快照一致时，才为每项写入当前证据指纹、消息、操作者、时间及来源页面；随后调用现有 `rebind_anomaly_resolutions` 并写聚合审计。未设置标志时保留现有拒绝分支。

- [ ] **Step 4: Run tests to verify GREEN**

Run: `python -m pytest v2-api/tests/test_data_center_review.py v2-api/tests/test_state_repository.py -q`

Expected: PASS。

### Task 2: 前端确认弹窗和请求合约

**Files:**
- Modify: `v2-web/src/api/services.ts`
- Modify: `v2-web/src/components/data-center/DataCenterGroupReviewPanel.vue`
- Test: `v2-web/src/components/__tests__/DataCenterGroupReviewPanel.spec.ts`

**Interfaces:**
- Consumes: `detail.anomalies`、`openAnomalies` 与后端 `resolve_all_anomalies`。
- Produces: `reviewDataCenterGroup(..., resolveAllAnomalies = false, expectedOpenAnomalies = {})`；正式通过弹窗。

- [ ] **Step 1: Write the failing tests**

增加三项前端行为测试：无未关闭异常时不弹窗且发送 `false`；存在两项未关闭异常时弹窗显示数量、确认后发送 `true` 和精确证据快照；取消时不请求正式通过。增加冲突测试，确认 409 后刷新而不显示成功。

- [ ] **Step 2: Run tests to verify RED**

Run: `npm run test:components -- src/components/__tests__/DataCenterGroupReviewPanel.spec.ts`

Expected: FAIL，因为正式通过尚未弹窗且请求体没有 `resolve_all_anomalies`。

- [ ] **Step 3: Write minimal implementation**

```ts
export async function reviewDataCenterGroup(
  groupId: string,
  status: 'approved' | 'incomplete' | 'exception',
  note = '',
  exceptionNote = '',
  resolveAllAnomalies = false,
  expectedOpenAnomalies: Record<string, string> = {},
): Promise<MaterialGroup>
```

当 `status === 'approved' && openAnomalies.value.length > 0` 时使用 `ElMessageBox.confirm`，确认按钮文案为“确认全部已修复并正式通过”，取消按钮文案为“返回逐项处理”。确认后只调用一次正式通过接口。

- [ ] **Step 4: Run tests to verify GREEN**

Run: `npm run test:components -- src/components/__tests__/DataCenterGroupReviewPanel.spec.ts`

Expected: PASS。

### Task 3: 版本、发布记录和回归门禁

**Files:**
- Modify: `v2-web/package.json`
- Modify: `v2-web/src/version.json`
- Modify: `v2-web/index.html`
- Modify: `v2-web/src/components/AppLayout.vue`
- Modify: `v2-api/app/main.py`
- Modify: `v2-api/app/services/ops_status.py`
- Modify: `v2-api/pyproject.toml`
- Modify: `AGENTS.md`
- Modify: `docs/AGENT_REQUIRED_READING.md`
- Modify: `docs/sop/README.md`
- Create: `ops/releases/V3.2.21.md`

**Interfaces:**
- Consumes: 已验证的源提交和构建产物。
- Produces: 版本一致的 V3.2.21 源码、静态资源和发布审计记录。

- [ ] **Step 1: Bump every runtime version surface to V3.2.21**

保持现有格式，只把 V3.2.20 更新为 V3.2.21，并把生产基线说明更新为已上线 V3.2.20、候选 V3.2.21。

- [ ] **Step 2: Run regression and build gates**

Run targeted pytest、完整 `test_data_center_review.py`、前端组件测试、`npm run build`、`python scripts/verify_v3_2_0_data_center_ui.py`、Vue 迁移门禁和版本/发布 SOP 验证。

- [ ] **Step 3: Commit implementation and generated static assets**

显式检查 staged 文件，排除 `.env`、数据、上传、密钥、数据库和发布压缩包。

### Task 4: 独立审阅、打包和生产发布

**Files:**
- Modify: `ops/releases/V3.2.21.md`

**Interfaces:**
- Consumes: 独立审阅通过的 V3.2.21 提交和经哈希校验的发布包。
- Produces: GitHub 分支/tag、生产 release、备份、健康检查与验收记录。

- [ ] **Step 1: Request read-only independent review**

审阅需求对齐、原子性、JSON/PostgreSQL 等价性、权限、测试、静态资源、版本一致性和发布风险。Critical/Important 必须先处理。

- [ ] **Step 2: Build and verify package**

生成 `build/server-release/module-manager-v2-server-3.2.21.zip`，验证包内版本与源提交并记录本地 SHA256。

- [ ] **Step 3: Backup and deploy**

执行生产备份，上传并比对服务器 SHA256，创建不可变 release，保留共享 `.env`、data、uploads，切换 `current` 并重启服务。

- [ ] **Step 4: Verify production**

等待 Uvicorn 在 `127.0.0.1:8000` 就绪；验证健康、版本、`/project-board`、`/review-workbench`、审阅接口权限与弹窗静态产物。失败则回滚代码 release，不回退数据库。

- [ ] **Step 5: Retention and release record**

先 dry-run 再按规则保留最近 5 个 release，补齐备份目录、release 目录、提交、包哈希、服务状态、页面/API 结果和清理摘要。

## Self-Review

- Spec coverage: 交互、范围、原子性、留痕、权限、并发和自动发布均有对应任务。
- Placeholder scan: 无 TBD、TODO 或未定义接口。
- Type consistency: 前后端统一使用 `resolve_all_anomalies`，TypeScript 参数为 `resolveAllAnomalies`。
