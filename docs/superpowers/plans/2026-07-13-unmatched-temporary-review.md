# 扫码未匹配临时审阅 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在项目驾驶舱中逐条审阅扫码未匹配照片，持久化临时分类与扫码结果，并只在管理员确认总清单候选后原子化生成或并入正式资料组。

**Architecture:** 新建纯业务服务 `unmatched_review.py` 管理稳定照片 ID、版本化临时审阅状态、候选排序和迁移数据。JSON 与 PostgreSQL 仓储实现相同接口，临时状态只写入未匹配记录，最终匹配时才在单事务中写正式资料组；前端使用独立 `UnmatchedReviewDialog.vue`，由项目驾驶舱按单条记录打开。

**Tech Stack:** Python 3.12、FastAPI、Pydantic、SQLAlchemy/PostgreSQL、pytest、Vue 3、TypeScript、Element Plus、Vite、Node 静态验收脚本

## Global Constraints

- 从干净基线 `production/V3/3.0.79` 创建并只使用生产分支 `production/V3/3.0.80`。
- 临时审阅期间不得创建正式 `groupId`、终端任务或 `00000000` 等占位终端。
- 临时记录不得进入施工完成量、审阅完成量、KPI、归档数量或驾驶舱条码准确率。
- 未匹配清单和候选列表均按每页 20 条展示；不在列表预加载照片。
- 管理员和审阅员可临时审阅；只有管理员可最终匹配并确定终端；施工员无权访问。
- 重新扫码必须在后端复用现有条码、二维码和 OCR 识别链，不在浏览器执行识别。
- 临时人工确认不直接形成正式扫码通过；匹配后按正式资料组数据重新计算。
- 所有保存、重新扫码、人工确认和最终匹配均写审计；并发版本不一致返回 `409`。
- 小功能版本从 `V3.0.79` 升级为 `V3.0.80`，更新内容使用中文。
- 先测试后实现；独立代码审阅通过后才可打包、备份、发布和清理服务器旧版本。

## File Structure

- Create `v2-api/app/services/unmatched_review.py`: 纯临时审阅状态、照片 ID、候选与迁移辅助函数。
- Modify `v2-api/app/services/local_simulation.py`: JSON 状态后端的未匹配临时审阅操作与最终匹配。
- Modify `v2-api/app/services/state_repository.py`: 仓储接口、JSON 代理、PostgreSQL 事务实现和双写代理。
- Modify `v2-api/app/api/routes/local_test.py`: 请求模型、RBAC、图片内容、临时审阅和最终匹配接口。
- Create `v2-api/tests/test_unmatched_review.py`: 纯业务规则测试。
- Modify `v2-api/tests/test_local_simulation.py`: JSON 状态隔离、审计和迁移测试。
- Modify `v2-api/tests/test_state_repository.py`: PostgreSQL payload、锁、回滚和双写契约测试。
- Modify `v2-api/tests/test_api.py`: 接口、状态码和生产角色矩阵测试。
- Modify `v2-web/src/api/types.ts`: 临时审阅、照片和候选 TypeScript 类型。
- Modify `v2-web/src/api/services.ts`: 临时审阅 API 映射与鉴权图片对象 URL。
- Create `v2-web/src/components/UnmatchedReviewDialog.vue`: 单条未匹配记录的完整临时审阅界面。
- Modify `v2-web/src/views/ProjectBoardView.vue`: 行点击、审阅按钮、弹窗挂载和匹配后刷新。
- Create `scripts/verify_project_board_unmatched_review.js`: 前端结构和安全边界验收。
- Modify `scripts/build-client-release.ps1`, `scripts/verify-client-release.py`, `scripts/verify_release_sop.py`: 将新验收脚本纳入发布包门禁。
- Modify version and release files listed in Task 8.

---

### Task 1: 建立生产分支与纯临时审阅模型

**Files:**
- Create: `v2-api/app/services/unmatched_review.py`
- Create: `v2-api/tests/test_unmatched_review.py`

**Interfaces:**
- Consumes: 未匹配记录中的 `unmatched_id`, `photo_urls`, `meter_no`, `barcode`, `collector`, `module_asset_no`。
- Produces: `build_review(record) -> dict`, `apply_review_patch(review, *, actor, expected_version, metadata, photo_updates, state) -> dict`, `find_review_photo(review, photo_id) -> dict`。

- [ ] **Step 1: 从已确认基线创建生产分支**

```powershell
git status --short --branch
git switch -c production/V3/3.0.80
```

Expected: 工作区只包含已提交的设计和计划，当前分支显示 `production/V3/3.0.80`。

- [ ] **Step 2: 写稳定照片 ID、默认状态和版本冲突失败测试**

```python
from app.services import unmatched_review


def sample_record() -> dict:
    return {
        "unmatched_id": "unmatched-1",
        "meter_no": "120000912473",
        "collector": "C001",
        "module_asset_no": "M001",
        "photo_urls": ["https://photos.example/a.jpg", "https://photos.example/b.jpg"],
    }


def test_build_review_has_stable_photo_ids_and_does_not_create_terminal() -> None:
    first = unmatched_review.build_review(sample_record())
    second = unmatched_review.build_review(sample_record())
    assert [item["id"] for item in first["photos"]] == [item["id"] for item in second["photos"]]
    assert first["version"] == 1
    assert first["state"] == "pending"
    assert "group_id" not in first
    assert "terminal" not in first


def test_apply_review_patch_rejects_stale_version() -> None:
    review = unmatched_review.build_review(sample_record())
    review["version"] = 3
    with pytest.raises(unmatched_review.ReviewVersionConflict):
        unmatched_review.apply_review_patch(
            review,
            actor="reviewer-a",
            expected_version=2,
            metadata={"meter_no": "120000912474"},
            photo_updates=[],
            state="pending",
        )
```

- [ ] **Step 3: 运行测试确认 RED**

Run: `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_unmatched_review.py -q`

Expected: FAIL with `ImportError` because `app.services.unmatched_review` does not exist.

- [ ] **Step 4: 实现稳定 ID、白名单更新和版本递增**

```python
REVIEW_SCHEMA_VERSION = 1
REVIEW_METADATA_FIELDS = {"meter_no", "collector", "module_asset_no"}
PHOTO_UPDATE_FIELDS = {"category"}


class ReviewVersionConflict(ValueError):
    pass


def normalized_photo_urls(record: dict[str, Any]) -> list[str]:
    values = record.get("photo_urls") or record.get("image_urls") or []
    if isinstance(values, str):
        values = re.split(r"[\r\n,]+", values)
    return [str(value).strip() for value in values if str(value).strip()]


def validate_category(category: str) -> None:
    if category not in {"unclassified", "before_box", "collector_barcode", "module_meter", "after_box"}:
        raise ValueError(f"Unsupported photo category: {category}")


def stable_photo_id(unmatched_id: str, index: int, source_url: str) -> str:
    digest = hashlib.sha256(f"{unmatched_id}|{index}|{source_url}".encode("utf-8")).hexdigest()[:16]
    return f"unmatched-photo-{digest}"


def build_review(record: dict[str, Any]) -> dict[str, Any]:
    existing = dict(record.get("temporary_review") or {})
    urls = normalized_photo_urls(record)
    photos_by_id = {str(item.get("id")): dict(item) for item in existing.get("photos") or []}
    photos = []
    for index, url in enumerate(urls):
        photo_id = stable_photo_id(str(record.get("unmatched_id") or ""), index, url)
        photos.append({
            "id": photo_id,
            "source_url": url,
            "category": "unclassified",
            "barcode_check_status": "not_checked",
            **photos_by_id.get(photo_id, {}),
        })
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "version": max(1, int(existing.get("version") or 1)),
        "state": str(existing.get("state") or "pending"),
        "meter_no": str(existing.get("meter_no") or record.get("meter_no") or record.get("barcode") or ""),
        "collector": str(existing.get("collector") or record.get("collector") or ""),
        "module_asset_no": str(existing.get("module_asset_no") or record.get("module_asset_no") or ""),
        "manual_confirmed": bool(existing.get("manual_confirmed")),
        "reviewer": str(existing.get("reviewer") or ""),
        "reviewed_at": str(existing.get("reviewed_at") or ""),
        "updated_at": str(existing.get("updated_at") or ""),
        "photos": photos,
    }


def find_review_photo(review: dict[str, Any], photo_id: str) -> dict[str, Any]:
    photo = next((item for item in review.get("photos") or [] if item.get("id") == photo_id), None)
    if photo is None:
        raise KeyError(photo_id)
    return photo


def apply_review_patch(
    review: dict[str, Any],
    *,
    actor: str,
    expected_version: int,
    metadata: dict[str, Any],
    photo_updates: list[dict[str, Any]],
    state: str,
) -> dict[str, Any]:
    if int(review.get("version") or 0) != expected_version:
        raise ReviewVersionConflict("Unmatched review was updated by another user")
    updated = copy.deepcopy(review)
    for key in REVIEW_METADATA_FIELDS:
        if key in metadata:
            updated[key] = str(metadata.get(key) or "").strip()
    for patch in photo_updates:
        photo = find_review_photo(updated, str(patch.get("id") or ""))
        if "category" in patch:
            validate_category(str(patch.get("category") or ""))
            photo["category"] = str(patch["category"])
    updated["state"] = state if state in {"pending", "reviewed"} else "pending"
    updated["reviewer"] = actor
    updated["updated_at"] = datetime.now(UTC).isoformat()
    updated["version"] = expected_version + 1
    return updated


def audit_diff(unmatched_id: str, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {
        "unmatched_id": unmatched_id,
        "before_version": before.get("version"),
        "after_version": after.get("version"),
        "before": before,
        "after": after,
    }
```

- [ ] **Step 5: 增加更新白名单测试并验证 GREEN**

```python
def test_apply_review_patch_updates_only_allowed_fields() -> None:
    review = unmatched_review.build_review(sample_record())
    photo_id = review["photos"][0]["id"]
    updated = unmatched_review.apply_review_patch(
        review,
        actor="reviewer-a",
        expected_version=1,
        metadata={"meter_no": "120000912474", "terminal": "00000000"},
        photo_updates=[{"id": photo_id, "category": "collector_barcode", "source_url": "tampered"}],
        state="reviewed",
    )
    assert updated["version"] == 2
    assert updated["meter_no"] == "120000912474"
    assert "terminal" not in updated
    assert updated["photos"][0]["category"] == "collector_barcode"
    assert updated["photos"][0]["source_url"] == "https://photos.example/a.jpg"
```

Run: `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_unmatched_review.py -q`

Expected: all tests in `test_unmatched_review.py` pass.

- [ ] **Step 6: 提交纯模型**

```powershell
git add v2-api/app/services/unmatched_review.py v2-api/tests/test_unmatched_review.py
git commit -m "feat: model unmatched temporary reviews"
```

### Task 2: 在 JSON 状态后端持久化临时审阅且隔离统计

**Files:**
- Modify: `v2-api/app/services/local_simulation.py:1392-1675`
- Modify: `v2-api/app/services/state_repository.py:1439-1675`
- Modify: `v2-api/app/services/state_repository.py:1931-2175`
- Modify: `v2-api/tests/test_local_simulation.py:803-957`

**Interfaces:**
- Consumes: Task 1 的 `build_review`, `apply_review_patch`, `find_review_photo`。
- Produces: `get_unmatched_review`, `save_unmatched_review`, `rescan_unmatched_review_photo`, `confirm_unmatched_review`, `list_unmatched_match_candidates`, `finalize_unmatched_match` 仓储契约；本任务先完成前两项 JSON 实现。

- [ ] **Step 1: 写临时打开、保存和统计隔离失败测试**

```python
def seed_unmatched_review_record() -> str:
    state = local_simulation.get_state()
    record = local_simulation.ensure_unmatched_record({
        "barcode": "3130001122100009124734",
        "meter_no": "120000912473",
        "collector": "C001",
        "module_asset_no": "M001",
        "photo_urls": [f"https://photos.example/{index}.jpg" for index in range(4)],
    })
    return record["unmatched_id"]


def test_unmatched_review_save_persists_without_creating_group_or_changing_summary() -> None:
    unmatched_id = seed_unmatched_review_record()
    before = copy.deepcopy(local_simulation.get_state())
    opened = local_simulation.get_unmatched_review(unmatched_id)
    saved = local_simulation.save_unmatched_review(
        unmatched_id,
        actor="reviewer-a",
        expected_version=opened["review"]["version"],
        metadata={"meter_no": "120000912474"},
        photo_updates=[{"id": opened["review"]["photos"][0]["id"], "category": "before_box"}],
        state="reviewed",
    )
    after = local_simulation.get_state()
    assert saved["review"]["meter_no"] == "120000912474"
    assert after["groups"] == before["groups"]
    assert after["tasks"] == before["tasks"]
    assert after["summary"] == before["summary"]
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_local_simulation.py -k "unmatched_review_save" -q`

Expected: FAIL because `get_unmatched_review` and `save_unmatched_review` do not exist.

- [ ] **Step 3: 实现 JSON 状态读取、保存和审计**

```python
def get_unmatched_review(unmatched_id: str) -> dict[str, Any]:
    record = get_unmatched_record(unmatched_id)
    if record is None:
        raise KeyError(unmatched_id)
    review = unmatched_review.build_review(record)
    return {"record": record, "review": review}


def save_unmatched_review(
    unmatched_id: str,
    *,
    actor: str,
    expected_version: int,
    metadata: dict[str, Any] | None = None,
    photo_updates: list[dict[str, Any]] | None = None,
    state: str = "pending",
) -> dict[str, Any]:
    record = get_unmatched_record(unmatched_id)
    if record is None:
        raise KeyError(unmatched_id)
    previous = unmatched_review.build_review(record)
    updated = unmatched_review.apply_review_patch(
        previous,
        actor=actor,
        expected_version=expected_version,
        metadata=metadata or {},
        photo_updates=photo_updates or [],
        state=state,
    )
    record["temporary_review"] = updated
    append_audit_event("unmatched_review_saved", actor, unmatched_review.audit_diff(unmatched_id, previous, updated))
    return {"record": record, "review": updated}
```

在 `StateRepository` 增加相同签名的抽象方法，并让 `JsonStateRepository` 直接委托 `local_simulation`。

- [ ] **Step 4: 验证重新加载、审计和 409 领域异常**

Run: `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_local_simulation.py -k "unmatched_review" -q`

Expected: 临时状态持久化、审计存在、版本冲突测试全部通过，groups/tasks/summary 不变。

- [ ] **Step 5: 提交 JSON 仓储实现**

```powershell
git add v2-api/app/services/local_simulation.py v2-api/app/services/state_repository.py v2-api/tests/test_local_simulation.py
git commit -m "feat: persist unmatched temporary reviews"
```

### Task 3: 接入重新扫码、二维码、OCR和临时人工确认

**Files:**
- Modify: `v2-api/app/services/unmatched_review.py`
- Modify: `v2-api/app/services/local_simulation.py:5635-5705`
- Modify: `v2-api/app/services/state_repository.py:1633-1644`
- Modify: `v2-api/tests/test_unmatched_review.py`
- Modify: `v2-api/tests/test_local_simulation.py`

**Interfaces:**
- Consumes: `photo_barcode_check.check_photo_barcode(photo, group_context, use_ocr=True)`。
- Produces: `rescan_unmatched_review_photo(unmatched_id, photo_id, *, actor, category="") -> dict` 和 `confirm_unmatched_review(unmatched_id, *, actor, expected_version, confirmed=True) -> dict`。

- [ ] **Step 1: 写扫码/OCR结果保存与临时确认不进入准确率的失败测试**

```python
def test_unmatched_rescan_uses_ocr_and_keeps_result_temporary(monkeypatch) -> None:
    unmatched_id = seed_unmatched_review_record()
    opened = local_simulation.get_unmatched_review(unmatched_id)
    photo_id = opened["review"]["photos"][0]["id"]
    monkeypatch.setattr(
        local_simulation.photo_barcode_check,
        "check_photo_barcode",
        lambda photo, group, use_ocr=False: {
            "barcode_check_status": "matched",
            "barcode_check_values": ["120000912473"],
            "barcode_check_ocr_values": ["120000912473"],
            "barcode_check_method": "barcode_ocr",
        },
    )
    before = local_simulation.get_state()["summary"].get("group_barcode_accuracy_passed", 0)
    result = local_simulation.rescan_unmatched_review_photo(
        unmatched_id, photo_id, actor="reviewer-a", category="module_meter"
    )
    assert result["photo"]["barcode_check_method"] == "barcode_ocr"
    assert local_simulation.get_state()["summary"].get("group_barcode_accuracy_passed", 0) == before
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_local_simulation.py -k "unmatched_rescan" -q`

Expected: FAIL because the unmatched rescan function does not exist.

- [ ] **Step 3: 实现后端识别和确认**

```python
def rescan_unmatched_review_photo(unmatched_id: str, photo_id: str, *, actor: str, category: str = "") -> dict:
    payload = get_unmatched_review(unmatched_id)
    review = payload["review"]
    photo = unmatched_review.find_review_photo(review, photo_id)
    if category:
        unmatched_review.validate_category(category)
        photo["category"] = category
    result = photo_barcode_check.check_photo_barcode(
        {**photo, "image_url": photo["source_url"]},
        unmatched_review.barcode_context(review),
        use_ocr=True,
    )
    photo.update(result)
    photo["barcode_rescanned_by"] = actor
    photo["barcode_rescanned_at"] = now_iso()
    review["version"] += 1
    payload["record"]["temporary_review"] = review
    append_audit_event("unmatched_review_barcode_rescan", actor, {"unmatched_id": unmatched_id, "photo_id": photo_id, "result": result})
    return {"review": review, "photo": photo}


def barcode_context(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "meter_no": review.get("meter_no") or "",
        "meter_match_key": build_total_catalog_match_key(review.get("meter_no") or ""),
        "collector": review.get("collector") or "",
        "module_asset_no": review.get("module_asset_no") or "",
        "photos": review.get("photos") or [],
    }
```

`confirm_unmatched_review` 只更新 `manual_confirmed`, `reviewer`, `reviewed_at`, `version` 和审计，不调用正式资料组准确率缓存刷新。

- [ ] **Step 4: 运行临时识别测试并验证 GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_unmatched_review.py v2-api\tests\test_local_simulation.py -k "unmatched_review or unmatched_rescan" -q`

Expected: 所有选中测试通过，临时识别不改变正式准确率。

- [ ] **Step 5: 提交识别与人工确认实现**

```powershell
git add v2-api/app/services/unmatched_review.py v2-api/app/services/local_simulation.py v2-api/app/services/state_repository.py v2-api/tests/test_unmatched_review.py v2-api/tests/test_local_simulation.py
git commit -m "feat: review unmatched photos with OCR"
```

### Task 4: 实现候选匹配和原子化正式迁移

**Files:**
- Modify: `v2-api/app/services/unmatched_review.py`
- Modify: `v2-api/app/services/local_simulation.py:1787-2091`
- Modify: `v2-api/app/services/state_repository.py:1456-1675`
- Modify: `v2-api/app/services/state_repository.py:3593-3700`
- Modify: `v2-api/app/services/state_repository.py:4879-5050`
- Modify: `v2-api/app/services/state_repository.py:5691-5785`
- Modify: `v2-api/tests/test_local_simulation.py`
- Modify: `v2-api/tests/test_state_repository.py`

**Interfaces:**
- Consumes: `build_total_catalog_match_key`, `list_catalog_rows`, 现有 `associate_unmatched_record` 和 `create_group_from_unmatched_record` 迁移能力。
- Produces: `list_unmatched_match_candidates(unmatched_id) -> {items,total}` 和 `finalize_unmatched_match(unmatched_id, *, actor, candidate_key, expected_version) -> dict`。

- [ ] **Step 1: 写零候选、多候选、唯一候选和回滚失败测试**

```python
def test_unmatched_match_requires_server_candidate_and_creates_no_placeholder() -> None:
    unmatched_id = seed_unmatched_review_record()
    candidates = local_simulation.list_unmatched_match_candidates(unmatched_id)
    assert candidates == {"total": 0, "items": []}
    with pytest.raises(ValueError, match="candidate"):
        local_simulation.finalize_unmatched_match(
            unmatched_id,
            actor="admin-a",
            candidate_key="catalog:missing",
            expected_version=1,
        )
    assert all(task.get("terminal") != "00000000" for task in local_simulation.get_state()["tasks"])


def test_unmatched_finalize_migrates_review_and_removes_open_record() -> None:
    unmatched_id = seed_catalog_and_unmatched_with_unique_terminal()
    review = local_simulation.get_unmatched_review(unmatched_id)["review"]
    candidate = local_simulation.list_unmatched_match_candidates(unmatched_id)["items"][0]
    result = local_simulation.finalize_unmatched_match(
        unmatched_id,
        actor="admin-a",
        candidate_key=candidate["candidate_key"],
        expected_version=review["version"],
    )
    assert result["group"]["terminal"] == candidate["terminal"]
    assert result["group"]["source_unmatched_id"] == unmatched_id
    assert local_simulation.get_unmatched_record(unmatched_id) is None
```

- [ ] **Step 2: 运行匹配测试确认 RED**

Run: `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_local_simulation.py -k "unmatched_match or unmatched_finalize" -q`

Expected: FAIL because candidate and finalize functions do not exist.

- [ ] **Step 3: 实现确定性候选和迁移 payload**

```python
def build_match_candidates(record: dict, review: dict, catalog_rows: list[dict], groups: list[dict]) -> list[dict]:
    meter_key = build_total_catalog_match_key(review.get("meter_no") or record.get("meter_no") or "")
    if not meter_key:
        return []
    groups_by_terminal = {str(group.get("terminal") or ""): group for group in groups}
    candidates: dict[str, dict] = {}
    for row in catalog_rows:
        if build_total_catalog_match_key(row.get("meter_no") or row.get("meter_match_key") or "") != meter_key:
            continue
        terminal = str(row.get("terminal") or "").strip()
        if not terminal or terminal == "00000000":
            continue
        target_group = groups_by_terminal.get(terminal) or {}
        catalog_id = str(row.get("id") or row.get("legacy_id") or meter_key)
        candidate_key = f"catalog:{catalog_id}:{terminal}"
        reasons = ["表号精确匹配"]
        if review.get("collector") and review.get("collector") == row.get("collector"):
            reasons.append("采集器号一致")
        if review.get("module_asset_no") and review.get("module_asset_no") in {row.get("module_asset_no"), row.get("asset_no")}:
            reasons.append("模块号一致")
        candidates[candidate_key] = {
            "candidate_key": candidate_key,
            "target_group_id": str(target_group.get("id") or ""),
            "terminal": terminal,
            "meter_no": str(row.get("meter_no") or review.get("meter_no") or ""),
            "address": str(row.get("address") or row.get("installation_address") or ""),
            "match_reasons": reasons,
        }
    return sorted(candidates.values(), key=lambda item: (-len(item["match_reasons"]), item["terminal"]))
```

`migrate_review_to_photo_rows(review)` 必须保留 `category`、扫码/OCR字段、人工确认来源和原始 URL；正式资料组创建后调用 `build_group_barcode_check` 重新计算，不直接复制临时通过结论。

```python
def require_version(review: dict[str, Any], expected_version: int) -> None:
    if int(review.get("version") or 0) != expected_version:
        raise ReviewVersionConflict("Unmatched review was updated by another user")


def migrate_review_to_photo_rows(review: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for photo in review.get("photos") or []:
        rows.append({
            "url": photo.get("source_url") or "",
            "category": photo.get("category") or "unclassified",
            "barcode_check_status": photo.get("barcode_check_status") or "not_checked",
            "barcode_check_values": list(photo.get("barcode_check_values") or []),
            "barcode_check_ocr_values": list(photo.get("barcode_check_ocr_values") or []),
            "barcode_check_method": photo.get("barcode_check_method") or "",
            "barcode_check_error": photo.get("barcode_check_error") or "",
            "temporary_review_manual_confirmed": bool(review.get("manual_confirmed")),
            "temporary_review_reviewer": review.get("reviewer") or "",
        })
    return rows
```

- [ ] **Step 4: 在 PostgreSQL 用行锁和单次 commit 实现 finalize**

```python
with self._session() as session:
    record = session.scalar(
        select(UnmatchedRecord)
        .where(UnmatchedRecord.team_id == team_id, UnmatchedRecord.legacy_id == unmatched_id, UnmatchedRecord.status == "open")
        .with_for_update()
    )
    review = unmatched_review.build_review(_unmatched_payload(record))
    unmatched_review.require_version(review, expected_version)
    candidate = self._resolve_unmatched_candidate(session, record, review, candidate_key)
    group, attached = self._materialize_unmatched_candidate(session, record, review, candidate, actor)
    record.status = "associated"
    record.payload = {**(record.payload or {}), "temporary_review": review, "associated_group_id": group.legacy_id}
    session.add(AuditLog(
        team_id=team_id,
        legacy_id=f"unmatched-review-finalized-{uuid4()}",
        actor_username=actor,
        action="unmatched_review_finalized",
        entity_type="unmatched_record",
        entity_id=None,
        before_data={"unmatched_id": unmatched_id, "review_version": expected_version},
        after_data={"group_id": group.legacy_id, "terminal": candidate["terminal"]},
        payload={"candidate_key": candidate_key, "attached": attached},
    ))
    session.commit()
```

不得在 commit 前调用会自行提交的旧仓储方法；抽出共享的 session 内辅助函数。异常离开 `_session` 上下文时必须 rollback。DualWrite 继续以 JSON 为权威并镜像同名操作。

- [ ] **Step 5: 增加 PostgreSQL 锁、单 commit 和失败不提交测试**

在 `test_state_repository.py` 使用现有 `FakeSession`/`TestPostgresRepository` 模式，断言：查询包含 `FOR UPDATE`、成功路径 `commit_calls == 1`、候选解析异常时 `commit_calls == 0`、临时 review 保存在 `UnmatchedRecord.payload`、正式组不使用占位终端。

Run: `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_state_repository.py -k "unmatched_review or finalize_unmatched" -q`

Expected: 所有选中 PostgreSQL 仓储测试通过。

- [ ] **Step 6: 提交匹配迁移实现**

```powershell
git add v2-api/app/services/unmatched_review.py v2-api/app/services/local_simulation.py v2-api/app/services/state_repository.py v2-api/tests/test_local_simulation.py v2-api/tests/test_state_repository.py
git commit -m "feat: finalize unmatched reviews atomically"
```

### Task 5: 暴露受保护的临时审阅 API

**Files:**
- Modify: `v2-api/app/api/routes/local_test.py:294-360`
- Modify: `v2-api/app/api/routes/local_test.py:941-975`
- Modify: `v2-api/app/api/routes/local_test.py:1583-1868`
- Modify: `v2-api/tests/test_api.py:95-212`
- Modify: `v2-api/tests/test_api.py:2532-2572`

**Interfaces:**
- Consumes: Task 2-4 的仓储方法和现有 `production_rbac_client`。
- Produces: `GET/PATCH review`、图片 content、单图 rescan、人工确认、候选和 finalize HTTP 接口。

- [ ] **Step 1: 写生产角色矩阵和状态码失败测试**

```python
def test_production_unmatched_review_role_matrix(monkeypatch, tmp_path) -> None:
    client, headers = production_rbac_client(monkeypatch, tmp_path)
    repository = FakeUnmatchedReviewRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)

    path = "/local-test/unmatched/unmatched-1/review"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=headers["constructor"]).status_code == 403
    assert client.get(path, headers=headers["reviewer"]).status_code == 200
    assert client.get(path, headers=headers["admin"]).status_code == 200

    finalize = "/local-test/unmatched/unmatched-1/finalize-match"
    body = {"candidate_key": "catalog:row-1", "expected_version": 2}
    assert client.post(finalize, headers=headers["reviewer"], json=body).status_code == 403
    assert client.post(finalize, headers=headers["admin"], json=body).status_code == 200
```

- [ ] **Step 2: 运行接口测试确认 RED**

Run: `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py -k "production_unmatched_review_role_matrix" -q`

Expected: FAIL with `404` because the routes do not exist.

- [ ] **Step 3: 增加请求模型和精确路由**

```python
class UnmatchedReviewPatchRequest(BaseModel):
    expected_version: int
    metadata: dict = Field(default_factory=dict)
    photo_updates: list[dict] = Field(default_factory=list)
    state: str = "pending"


class UnmatchedReviewConfirmRequest(BaseModel):
    expected_version: int
    confirmed: bool = True


class UnmatchedFinalizeMatchRequest(BaseModel):
    candidate_key: str
    expected_version: int
```

同时将路由文件的 Pydantic import 改为：

```python
from pydantic import BaseModel, Field
```

路由统一通过 `bound_review_actor(request, "")` 绑定管理员/审阅员身份；`finalize-match` 先调用 `require_production_admin_payload(request)`，再从 JWT subject 取得 actor。捕获 `ReviewVersionConflict` 返回 `409`，`KeyError` 返回 `404`，候选错误返回 `400`。

- [ ] **Step 4: 增加鉴权图片内容接口**

`GET /local-test/unmatched/{id}/photos/{photo_id}/content` 先校验角色，再从仓储返回稳定照片和源地址，复用 `group_photo_content` 的本地文件、OSS 签名和受控代理读取逻辑。禁止接收客户端传入任意 URL，避免 SSRF。

```python
@router.get("/unmatched/{unmatched_id}/photos/{photo_id}/content")
def unmatched_review_photo_content(unmatched_id: str, photo_id: str, request: Request):
    bound_review_actor(request, "")
    review = state_repository().get_unmatched_review(unmatched_id)["review"]
    photo = unmatched_review.find_review_photo(review, photo_id)
    return _photo_content_response_from_source(photo["source_url"], request=request, variant="original")
```

从现有 `group_photo_content` 抽取 `_photo_content_response_from_source(source_url, *, request, variant)`，只接收服务端存储的 URL；本地路径走 `FileResponse`，OSS 地址走服务端签名读取，外部地址继续经过 `_validate_photo_proxy_url` 和生产 allowlist。

- [ ] **Step 5: 验证状态码、无任意 URL 和版本冲突**

Run: `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py -k "unmatched_review or unmatched_finalize or unmatched_photo_content" -q`

Expected: 角色矩阵、`404`、`409`、候选校验和图片读取测试全部通过。

- [ ] **Step 6: 提交 API**

```powershell
git add v2-api/app/api/routes/local_test.py v2-api/tests/test_api.py
git commit -m "feat: expose unmatched review APIs"
```

### Task 6: 添加前端类型和 API 客户端

**Files:**
- Modify: `v2-web/src/api/types.ts:459-486`
- Modify: `v2-web/src/api/services.ts:269-298`
- Modify: `v2-web/src/api/services.ts:802-831`
- Modify: `v2-web/src/api/services.ts:1721-1850`
- Create: `scripts/verify_project_board_unmatched_review.js`

**Interfaces:**
- Consumes: Task 5 的 HTTP payload。
- Produces: `fetchUnmatchedReview`, `saveUnmatchedReview`, `rescanUnmatchedReviewPhoto`, `confirmUnmatchedReview`, `fetchUnmatchedMatchCandidates`, `finalizeUnmatchedMatch`, `fetchUnmatchedReviewPhotoObjectUrl`。

- [ ] **Step 1: 先写前端契约验收脚本并确认 RED**

```javascript
const fs = require('fs')
const types = fs.readFileSync('v2-web/src/api/types.ts', 'utf8')
const services = fs.readFileSync('v2-web/src/api/services.ts', 'utf8')

for (const token of [
  'UnmatchedReviewDetail',
  'UnmatchedReviewPhoto',
  'UnmatchedMatchCandidate',
  'fetchUnmatchedReview',
  'saveUnmatchedReview',
  'fetchUnmatchedReviewPhotoObjectUrl',
  'finalizeUnmatchedMatch',
]) {
  if (!types.includes(token) && !services.includes(token)) throw new Error(`missing ${token}`)
}
if (services.includes('photoProxyUrl(url: string)')) throw new Error('must not proxy caller supplied URLs')
```

Run: `node scripts\verify_project_board_unmatched_review.js`

Expected: FAIL with `missing UnmatchedReviewDetail`.

- [ ] **Step 2: 增加 TypeScript 类型**

```typescript
export type UnmatchedReviewPhoto = {
  id: string
  sourceUrl: string
  category: string
  barcodeCheckStatus: string
  barcodeCheckValues: string[]
  barcodeCheckOcrValues: string[]
  barcodeCheckMethod: string
  barcodeCheckError: string
}

export type UnmatchedReviewDetail = {
  record: UnmatchedRecord
  version: number
  state: 'pending' | 'reviewed'
  meterNo: string
  collector: string
  moduleAssetNo: string
  manualConfirmed: boolean
  reviewer: string
  photos: UnmatchedReviewPhoto[]
}

export type UnmatchedMatchCandidate = {
  candidateKey: string
  targetGroupId: string
  terminal: string
  meterNo: string
  address: string
  matchReasons: string[]
}
```

- [ ] **Step 3: 增加映射与 API 函数**

```typescript
export async function fetchUnmatchedReview(unmatchedId: string): Promise<UnmatchedReviewDetail> {
  const data = await api<BackendUnmatchedReview>(`/local-test/unmatched/${encodeURIComponent(unmatchedId)}/review`)
  return mapUnmatchedReview(data)
}

export async function fetchUnmatchedReviewPhotoObjectUrl(unmatchedId: string, photoId: string): Promise<string> {
  const path = `/local-test/unmatched/${encodeURIComponent(unmatchedId)}/photos/${encodeURIComponent(photoId)}/content`
  const response = await fetchWithAuth(path, { headers: formHeaders() })
  if (!response.ok) throw new Error(response.statusText || `HTTP ${response.status}`)
  const blob = await response.blob()
  if (!blob.type.startsWith('image/')) throw new Error('返回内容不是图片')
  return createVerifiedImageObjectUrl(blob)
}

export async function finalizeUnmatchedMatch(unmatchedId: string, candidateKey: string, expectedVersion: number) {
  return api(`/local-test/unmatched/${encodeURIComponent(unmatchedId)}/finalize-match`, {
    method: 'POST',
    body: JSON.stringify({ candidate_key: candidateKey, expected_version: expectedVersion }),
  })
}
```

- [ ] **Step 4: 运行契约脚本和 TypeScript 构建**

Run: `node scripts\verify_project_board_unmatched_review.js`

Expected: API 类型和函数检查通过；UI token 检查可暂时保持失败，Task 7 完成后全绿。

Run: `npm --prefix v2-web run build`

Expected: `vue-tsc --noEmit` 与 Vite build 通过。

- [ ] **Step 5: 提交前端契约**

```powershell
git add v2-web/src/api/types.ts v2-web/src/api/services.ts scripts/verify_project_board_unmatched_review.js
git commit -m "feat: add unmatched review client contract"
```

### Task 7: 构建单条临时审阅弹窗并接入驾驶舱

**Files:**
- Create: `v2-web/src/components/UnmatchedReviewDialog.vue`
- Modify: `v2-web/src/views/ProjectBoardView.vue:128-150`
- Modify: `v2-web/src/views/ProjectBoardView.vue:1191-1269`
- Modify: `v2-web/src/views/ProjectBoardView.vue:2133-2250`
- Modify: `scripts/verify_project_board_unmatched_review.js`

**Interfaces:**
- Consumes: Task 6 的前端 API 函数和类型。
- Produces: `v-model`, `unmatched-id`, `@matched`, `@updated` 的独立弹窗组件。

- [ ] **Step 1: 扩充静态验收脚本并确认 UI RED**

```javascript
const board = fs.readFileSync('v2-web/src/views/ProjectBoardView.vue', 'utf8')
const dialog = fs.readFileSync('v2-web/src/components/UnmatchedReviewDialog.vue', 'utf8')

for (const token of [
  '@row-click="openUnmatchedReviewRow"',
  '<UnmatchedReviewDialog',
  '@click.stop',
  'DIALOG_PAGE_SIZE',
]) if (!board.includes(token)) throw new Error(`board missing ${token}`)

for (const token of [
  '重新扫码',
  '人工确认',
  '完成审阅并匹配清单',
  'fetchUnmatchedReviewPhotoObjectUrl',
  'URL.revokeObjectURL',
  'candidatePageSize = 20',
]) if (!dialog.includes(token)) throw new Error(`dialog missing ${token}`)

if (dialog.includes('<el-image')) throw new Error('dialog must use verified object URLs with native img')
```

Run: `node scripts\verify_project_board_unmatched_review.js`

Expected: FAIL because the component and integration do not exist.

- [ ] **Step 2: 建立弹窗状态机和对象 URL 生命周期**

```typescript
const props = defineProps<{ modelValue: boolean; unmatchedId: string }>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  matched: [groupId: string]
  updated: []
}>()
const mode = ref<'review' | 'match'>('review')
const detail = ref<UnmatchedReviewDetail | null>(null)
const selectedPhotoId = ref('')
const imageObjectUrl = ref('')
const candidatePage = ref(1)
const candidatePageSize = 20

function replaceImageObjectUrl(next = '') {
  if (imageObjectUrl.value) URL.revokeObjectURL(imageObjectUrl.value)
  imageObjectUrl.value = next
}
```

监听 `modelValue + unmatchedId` 加载详情；照片切换时递增请求序号，过期请求返回的 object URL 立即 revoke；关闭和卸载时释放 URL。

- [ ] **Step 3: 实现审阅面板**

主图使用固定比例容器和原生 `<img>`；照片使用稳定序号按钮，不预加载缩略图。右侧提供三个编号输入框、四类分类按钮、重新扫码、人工确认、保存和“完成审阅并匹配清单”。重新扫码成功只更新当前照片，失败保留既有分类和编号。

```vue
<button
  v-for="(photo, index) in detail?.photos || []"
  :key="photo.id"
  class="unmatched-photo-index"
  :class="{ active: photo.id === selectedPhotoId }"
  type="button"
  @click="selectPhoto(photo.id)"
>
  {{ index + 1 }}
</button>
```

- [ ] **Step 4: 在同一弹窗内实现候选终端模式**

点击完成按钮先保存，再切换 `mode = 'match'` 并加载候选。候选表显示终端、表号、地址、已有资料组和匹配依据；零候选只允许返回继续修改；多个候选单选；管理员确认后调用 finalize。审阅员看不到最终确认按钮。

- [ ] **Step 5: 将组件接入未匹配清单**

```vue
<el-table
  v-loading="unmatchedLoading"
  :data="pagedUnmatchedRows"
  height="520"
  size="small"
  @row-click="openUnmatchedReviewRow"
>
```

操作列增加“审阅”按钮，现有 dropdown 使用 `@click.stop`。匹配成功时关闭弹窗、调用 `loadUnmatchedRows()` 与 `loadBoard()`，并保持原清单页在仍有效的最大页码内。

- [ ] **Step 6: 添加响应式布局并运行前端门禁**

桌面弹窗宽度使用 `min(1180px, 96vw)`，图片和表单两列；`max-width: 768px` 时使用 `fullscreen` 或单列布局。按钮使用 Element Plus 图标，文字不重叠，不增加解释性段落。

Run: `node scripts\verify_project_board_unmatched_review.js`

Expected: `project board unmatched review checks passed`.

Run: `npm --prefix v2-web run build`

Expected: TypeScript 和 Vite 生产构建通过。

- [ ] **Step 7: 提交前端界面**

```powershell
git add v2-web/src/components/UnmatchedReviewDialog.vue v2-web/src/views/ProjectBoardView.vue scripts/verify_project_board_unmatched_review.js
git commit -m "feat: review unmatched photos from dashboard"
```

### Task 8: 纳入发布门禁并升级 V3.0.80

**Files:**
- Modify: `scripts/build-client-release.ps1:102-114`
- Modify: `scripts/verify-client-release.py:51-66`
- Modify: `scripts/verify_release_sop.py:62-107`
- Modify: `v2-api/app/main.py:39`
- Modify: `v2-api/app/services/ops_status.py:20`
- Modify: `v2-api/pyproject.toml:3-4`
- Modify: `v2-api/tests/test_api.py:537`
- Modify: `v2-web/package.json:3`
- Modify: `v2-web/index.html:6`
- Modify: `v2-web/src/components/AppLayout.vue:6`
- Modify: `v2-web/src/constants/releaseNotes.ts:1-20`
- Modify: `RELEASE_MANIFEST.md:5-6`
- Modify: `AGENTS.md:5-27`
- Create: `ops/releases/V3.0.80.md`

**Interfaces:**
- Consumes: 完成的后端、前端和验收脚本。
- Produces: 一致的 `3.0.80` 版本面、中文更新记录和可验证发布包清单。

- [ ] **Step 1: 先将 API 版本断言改为 3.0.80 并确认 RED**

```python
assert data["version"] == "3.0.80"
```

Run: `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py -k "health or system_status" -q`

Expected: FAIL because the application still reports `3.0.79`.

- [ ] **Step 2: 更新所有运行时版本和中文更新内容**

将运行时与包版本统一为 `3.0.80`。`releaseNotes.ts` 在首位新增：

```typescript
{
  version: 'V3.0.80',
  title: '扫码未匹配临时审阅',
  items: [
    '项目驾驶舱的扫码未匹配清单支持逐条打开照片并完成分类、重新扫码、二维码与OCR识别和人工确认。',
    '临时审阅结果保存到服务器并完整记录审计，匹配终端前不生成正式资料组，也不进入完成量、KPI、归档和条码准确率。',
    '管理员确认总清单候选后才原子化生成或并入正式资料组，系统禁止使用00000000等占位终端。',
  ],
}
```

- [ ] **Step 3: 将验收脚本纳入构建和发布校验**

在 `build-client-release.ps1` 增加：

```powershell
Copy-ReleaseItem "scripts\verify_project_board_unmatched_review.js" "scripts\verify_project_board_unmatched_review.js"
```

在 `verify-client-release.py` 和 `verify_release_sop.py` 的必需文件列表加入 `scripts/verify_project_board_unmatched_review.js`，并让 SOP 校验确认构建脚本实际复制该文件。

- [ ] **Step 4: 写 V3.0.80 发布记录骨架的已知内容**

`ops/releases/V3.0.80.md` 先记录版本、分支、功能范围、测试命令和待执行的发布证据字段；尚未产生的 hash、备份目录和 release 目录保留为空表格单元格，不填写虚构值。发布完成后 Task 9 必须补齐并提交。

- [ ] **Step 5: 运行版本和发布门禁**

Run: `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py -k "health or system_status" -q`

Expected: 版本相关测试通过。

Run: `node scripts\verify_admin_release_notes.js`

Expected: release notes checks pass.

Run: `.\.venv\Scripts\python.exe scripts\verify_release_sop.py`

Expected: release SOP checks pass and require the new verifier.

- [ ] **Step 6: 提交版本与发布门禁**

```powershell
git add scripts v2-api/app/main.py v2-api/app/services/ops_status.py v2-api/pyproject.toml v2-api/tests/test_api.py v2-web/package.json v2-web/index.html v2-web/src/components/AppLayout.vue v2-web/src/constants/releaseNotes.ts RELEASE_MANIFEST.md AGENTS.md ops/releases/V3.0.80.md
git commit -m "chore: prepare V3.0.80 release"
```

### Task 9: 全量验证、独立审阅、打包和生产发布

**Files:**
- Verify: all changed files
- Modify after deploy: `ops/releases/V3.0.80.md`

**Interfaces:**
- Consumes: 已完成的 V3.0.80 分支。
- Produces: 独立审阅结论、发布包 SHA256、生产备份、线上健康/API/UI证据和仅保留最近五个 release 的记录。

- [ ] **Step 1: 运行聚焦和全量本地验证**

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_unmatched_review.py v2-api\tests\test_local_simulation.py v2-api\tests\test_state_repository.py v2-api\tests\test_api.py -k "unmatched_review or unmatched_rescan or unmatched_match or unmatched_finalize" -q
.\.venv\Scripts\python.exe -m pytest v2-api\tests -q
npm --prefix v2-web run build
node scripts\verify_project_board_unmatched_review.js
node scripts\verify_photo_barcode_accuracy.js
node scripts\verify_project_board_photo_dialog.js
.\.venv\Scripts\python.exe scripts\verify_security_hardening.py
.\.venv\Scripts\python.exe scripts\verify_release_sop.py
git diff --check production/V3/3.0.79...HEAD
```

Expected: 全部命令退出码 `0`；记录完整 pytest 数量和现有非阻断构建警告。

- [ ] **Step 2: 使用全新审阅智能体检查全部改动**

审阅范围为 `production/V3/3.0.79...HEAD`，重点检查：未匹配状态是否污染正式统计、RBAC、SSRF、对象 URL 泄漏、版本冲突、PostgreSQL 原子性、人工确认是否误计准确率、任何 `00000000` 创建路径。审阅智能体不修改代码，只按严重度给出文件和行号。

Expected: 无 P0/P1/P2 未解决问题；若有发现，先补失败测试和修复提交，再重新运行 Step 1 与新一轮独立审阅。

- [ ] **Step 3: 使用浏览器验证桌面和手机交互**

启动本地服务后，用 in-app Browser 验证 `1280x800` 和 `390x844`：未匹配清单每页 20 条、整行和按钮打开正确记录、图片能加载和切换、分类与重新扫码可保存、候选在同一弹窗展示、审阅员无最终匹配按钮、无文字或按钮重叠。

Expected: 控制台无错误；页面与 API 网络请求成功；截图记录在发布说明的本地验证部分。

- [ ] **Step 4: 构建并验证发布包**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-client-release.ps1 -Version 3.0.80
.\.venv\Scripts\python.exe scripts\verify-client-release.py build\server-release\module-manager-v2-server-3.0.80.zip
Get-FileHash -Algorithm SHA256 build\server-release\module-manager-v2-server-3.0.80.zip
```

Expected: 发布包验证通过；记录本地 SHA256，包内含新 API、Vue 组件和验收脚本，不含 `.env`、数据库、uploads 或缓存。

- [ ] **Step 5: 推送生产分支并在服务器发布前备份**

```powershell
git push -u origin production/V3/3.0.80
ssh -i "C:\Users\Administrator\Downloads\XXXXXX.pem" root@www.sgcc.online "APP=/opt/module-manager-v2; bash \"\$APP/current/scripts/production_backup.sh\" \"\$APP\" V3.0.80"
```

Expected: 远端分支存在；备份输出包含 `.env`、当前 release、data、uploads、PostgreSQL dump/schema 和 `SHA256SUMS`，记录实际备份目录。

- [ ] **Step 6: 上传、校验 hash、解压并切换 release**

```powershell
scp -i "C:\Users\Administrator\Downloads\XXXXXX.pem" build\server-release\module-manager-v2-server-3.0.80.zip root@www.sgcc.online:/tmp/
ssh -i "C:\Users\Administrator\Downloads\XXXXXX.pem" root@www.sgcc.online "sha256sum /tmp/module-manager-v2-server-3.0.80.zip"
```

服务器 hash 必须与 Step 4 完全一致后，按 `docs/sop/06-production-deploy-runbook.md` 使用 `REL="/opt/module-manager-v2/releases/v3.0.80-$(date +%Y%m%d_%H%M%S)"` 创建 release、复制 `.env`、安装依赖、原子切换 current，并重启 `module-manager-v2.service`。任何失败立即恢复 V3.0.79 current symlink。

- [ ] **Step 7: 执行线上健康、权限、API和页面验证**

```bash
APP=/opt/module-manager-v2
"$APP/venv/bin/python" "$APP/current/scripts/production_health_check.py" --base-url http://127.0.0.1:8000 --expected-version 3.0.80 --env "$APP/.env"
SECURITY_ENV_PATH="$APP/.env" "$APP/venv/bin/python" "$APP/current/scripts/audit_production_security.py"
```

再对 `https://www.sgcc.online` 运行健康检查，并使用管理员、审阅员、施工员账号验证角色矩阵。创建一条专用未匹配测试记录，证明打开和保存不改变 groups/tasks/KPI/accuracy；最终匹配后才生成真实终端资料组；验证完成后按审计流程删除测试数据。

Expected: 服务和 nginx active，内部/公网健康检查通过，版本为 `3.0.80`，页面和图片 API 正常，错误角色返回 `403`，不存在 `00000000` 资料组。

- [ ] **Step 8: 清理旧 release 并补全发布记录**

```bash
APP=/opt/module-manager-v2
bash "$APP/current/scripts/cleanup_old_releases.sh" "$APP" 5 --dry-run
bash "$APP/current/scripts/cleanup_old_releases.sh" "$APP" 5
```

Expected: current 永不删除，服务器仅保留最近五个 release，备份目录不受影响。将备份目录、release 目录、local/server hash、测试数量、服务状态、页面/API验证和清理结果写入 `ops/releases/V3.0.80.md`。

- [ ] **Step 9: 提交发布证据并同步 GitHub**

```powershell
git add ops/releases/V3.0.80.md
git commit -m "docs: record V3.0.80 production deployment"
git push origin production/V3/3.0.80
git status --short --branch
```

Expected: 工作区干净，本地和 GitHub 分支一致，发布记录包含完整证据。
