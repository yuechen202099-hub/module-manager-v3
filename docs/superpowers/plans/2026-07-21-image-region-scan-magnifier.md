# V3.0.83 图片框选识别与局部放大实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在正常审阅和未匹配审阅中提供桌面端局部放大、人工分类后的框选条码/二维码/OCR 识别，并且只有原有保存动作才能把人工确认值写入数据库。

**Architecture:** 后端在 `photo_barcode_check.py` 内抽出可复用的图像级扫码与 OCR 函数，再由新的只读区域识别服务完成 EXIF 纠正、归一化坐标校验、内存裁剪和候选去重。前端新增共享 `ReviewImageInspector.vue` 负责 `object-fit: contain` 几何、2.5 倍放大镜、选区和单请求状态，父页面负责选择对应 API、展示新旧值确认框并把结果写入各自现有草稿。

**Tech Stack:** Python 3.14、FastAPI、Pillow、zxing-cpp、Tesseract OCR、pytest、Vue 3、TypeScript、Element Plus、Node 源码契约验证、Vite。

## Global Constraints

- 生产基线必须是 `origin/production/V3/3.0.82` 的 `f4b703d`；本功能与终端优先施工同版发布为 `V3.0.83`。
- 本次只支持桌面端，不增加移动端手势、布局或验收范围。
- 每次识别前必须人工选择 `meter`、`module` 或 `collector`，不提供自动分类。
- 区域识别是只读操作，不直接修改数据库、照片扫码状态、资料组状态、归档状态或驾驶舱准确率。
- 点击“替换”只写入当前页面草稿；继续使用原有保存动作入库并保留既有编辑审计。
- 识别结果与原值不同时必须同时展示原值和识别值，不得静默覆盖。
- 服务端只接受归一化坐标与人工类别，图片必须由路由中的资料组/未匹配记录和照片 ID 在当前团队内解析。
- 不接受客户端 URL、文件路径或图片二进制，不创建占位资料组、占位终端或 `00000000` 工单。
- 自动上传继续关闭，本功能不修改施工采集、缓存或上传链路。
- 同一页面同一时刻最多一个区域识别请求；无后台批量识别、自动重试或并行扫描。
- 选区图片只在内存中存在，不写磁盘、数据库或日志；沿用现有图片解码上限、候选上限和 OCR 信号量。

---

### Task 1: 图像级扫码与区域识别服务

**Files:**
- Modify: `v2-api/tests/test_photo_barcode_check.py`
- Modify: `v2-api/app/services/photo_barcode_check.py`

**Interfaces:**
- Consumes: `_photo_image(photo)`、`_barcode_scan_candidates(image)`、`_read_zxing_barcodes(zxingcpp, candidate)`、`_ocr_scan_candidates(image)`、`_run_tesseract(image)`、`_extract_ocr_candidates(text, expected_values)`、`OCR_RESCUE_SEMAPHORE`。
- Produces: `scan_photo_region(photo: dict[str, Any], barcode_type: str, region: Mapping[str, float]) -> dict[str, Any]`，返回 `barcode_type`、`values`、`normalized_values`、`method` 和原样规范化后的 `region`。
- Produces: `_scan_barcode_image(image, *, candidate_limit: int) -> list[str]` 和 `_scan_ocr_image(image, *, expected_values: list[str]) -> list[str]`，供整图包装函数与区域识别共同复用。

- [ ] **Step 1: 写区域校验、EXIF 裁剪和识别顺序失败测试**

在 `v2-api/tests/test_photo_barcode_check.py` 增加以下测试，测试图片只在内存中生成：

```python
from PIL import Image


def test_scan_photo_region_crops_exif_corrected_image_and_prefers_barcode(monkeypatch) -> None:
    source = Image.new("RGB", (200, 100), "white")
    source.getexif()[274] = 6
    observed: dict[str, tuple[int, int]] = {}
    monkeypatch.setattr(photo_barcode_check, "_photo_image", lambda _photo: source.copy())

    def barcode_reader(image, *, candidate_limit: int):
        observed["size"] = image.size
        assert candidate_limit > 0
        return [" 3130001122100009124734 "]

    monkeypatch.setattr(photo_barcode_check, "_scan_barcode_image", barcode_reader)
    monkeypatch.setattr(
        photo_barcode_check,
        "_scan_ocr_image",
        lambda _image, *, expected_values: pytest.fail("OCR must not run after barcode success"),
    )

    result = photo_barcode_check.scan_photo_region(
        {"id": "photo-1"},
        "module",
        {"x": 0.25, "y": 0.20, "width": 0.50, "height": 0.40},
    )

    assert observed["size"] == (50, 80)
    assert result == {
        "barcode_type": "module",
        "values": ["3130001122100009124734"],
        "normalized_values": ["3130001122100009124734"],
        "method": "barcode",
        "region": {"x": 0.25, "y": 0.2, "width": 0.5, "height": 0.4},
    }


@pytest.mark.parametrize(
    ("barcode_type", "region"),
    [
        ("automatic", {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5}),
        ("meter", {"x": -0.1, "y": 0.1, "width": 0.5, "height": 0.5}),
        ("meter", {"x": 0.8, "y": 0.1, "width": 0.3, "height": 0.5}),
        ("meter", {"x": float("nan"), "y": 0.1, "width": 0.5, "height": 0.5}),
        ("meter", {"x": 0.1, "y": 0.1, "width": 0.0, "height": 0.5}),
    ],
)
def test_scan_photo_region_rejects_invalid_category_or_geometry(barcode_type, region) -> None:
    with pytest.raises(ValueError):
        photo_barcode_check.scan_photo_region({"id": "photo-1"}, barcode_type, region)


def test_scan_photo_region_uses_ocr_only_when_barcode_has_no_candidate(monkeypatch) -> None:
    monkeypatch.setattr(photo_barcode_check, "_photo_image", lambda _photo: Image.new("RGB", (120, 80)))
    monkeypatch.setattr(photo_barcode_check, "_scan_barcode_image", lambda _image, *, candidate_limit: [])
    monkeypatch.setattr(
        photo_barcode_check,
        "_scan_ocr_image",
        lambda _image, *, expected_values: ["120000912473", "120000912473"],
    )

    result = photo_barcode_check.scan_photo_region(
        {"id": "photo-1"},
        "meter",
        {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
    )

    assert result["values"] == ["120000912473"]
    assert result["method"] == "ocr"


def test_scan_photo_region_rejects_tiny_pixel_crop(monkeypatch) -> None:
    monkeypatch.setattr(photo_barcode_check, "_photo_image", lambda _photo: Image.new("RGB", (100, 100)))

    with pytest.raises(ValueError, match="too small"):
        photo_barcode_check.scan_photo_region(
            {"id": "photo-1"},
            "collector",
            {"x": 0.0, "y": 0.0, "width": 0.1, "height": 0.1},
        )
```

- [ ] **Step 2: 运行测试确认 RED**

```powershell
Set-Location v2-api
..\.venv\Scripts\python.exe -m pytest tests\test_photo_barcode_check.py -q
```

Expected: 新测试因 `scan_photo_region`、`_scan_barcode_image` 和 `_scan_ocr_image` 尚不存在而失败。

- [ ] **Step 3: 抽取图像级复用函数并实现内存区域识别**

在 `photo_barcode_check.py` 中保留 `default_barcode_scanner(photo)` 和 `default_ocr_reader(photo, expected_values)` 的公开签名，把它们现有的循环体分别移入 `_scan_barcode_image` 和 `_scan_ocr_image`。新增常量和服务入口：

```python
REGION_BARCODE_TYPES = frozenset({"meter", "module", "collector"})
REGION_MIN_SIDE_PIXELS = 24


def scan_photo_region(
    photo: dict[str, Any],
    barcode_type: str,
    region: Mapping[str, float],
) -> dict[str, Any]:
    from PIL import ImageOps

    normalized_region = _validated_normalized_region(region)
    if barcode_type not in REGION_BARCODE_TYPES:
        raise ValueError("Unsupported barcode type")
    image = _photo_image(photo)
    if image is None:
        raise ValueError("Photo image is unavailable")
    try:
        oriented = ImageOps.exif_transpose(image)
        left = round(normalized_region["x"] * oriented.width)
        top = round(normalized_region["y"] * oriented.height)
        right = round((normalized_region["x"] + normalized_region["width"]) * oriented.width)
        bottom = round((normalized_region["y"] + normalized_region["height"]) * oriented.height)
        if right - left < REGION_MIN_SIDE_PIXELS or bottom - top < REGION_MIN_SIDE_PIXELS:
            raise ValueError("Selected region is too small")
        crop = oriented.crop((left, top, right, bottom))
        values = _scan_barcode_image(crop, candidate_limit=_scan_candidate_limit(photo))
        method = "barcode" if values else ""
        if not values:
            values = _scan_ocr_image(crop, expected_values=[])
            method = "ocr" if values else "none"
        normalized_values = _normalized_values(values)
        return {
            "barcode_type": barcode_type,
            "values": _unique_text_values(values),
            "normalized_values": _unique_text_values(normalized_values),
            "method": method,
            "region": normalized_region,
        }
    finally:
        image.close()
```

`_validated_normalized_region` 必须用 `math.isfinite` 校验四个值，要求 `0 <= x,y,width,height <= 1`、`width > 0`、`height > 0`、`x + width <= 1`、`y + height <= 1`。`default_ocr_reader` 仍在获取 `OCR_RESCUE_SEMAPHORE` 后调用 `_scan_ocr_image`；区域入口也必须沿同一信号量包装 OCR 调用，获取失败时返回 `method="none"`，不能绕过并发限制。

- [ ] **Step 4: 运行扫码服务回归测试确认 GREEN**

```powershell
Set-Location v2-api
..\.venv\Scripts\python.exe -m pytest tests\test_photo_barcode_check.py -q
```

Expected: 全部通过；原整图扫码、二维码、旋转增强、候选上限和 OCR 测试保持绿色。

- [ ] **Step 5: 提交区域识别核心**

```powershell
git add v2-api/tests/test_photo_barcode_check.py v2-api/app/services/photo_barcode_check.py
git commit -m "feat: add read-only photo region recognition"
```

---

### Task 2: 可信图片路由与权限边界

**Files:**
- Modify: `v2-api/tests/test_api.py`
- Modify: `v2-api/app/api/routes/local_test.py`

**Interfaces:**
- Consumes: `state_repository().get_group(group_id)`、`state_repository().get_unmatched_review(unmatched_id)`、`unmatched_review.find_review_photo(review, photo_id)`、`photo_barcode_check.scan_photo_region(photo, barcode_type, region)`、`bound_review_actor(request, "")`。
- Produces: `POST /local-test/groups/{group_id}/photos/{photo_id}/region-scan`。
- Produces: `POST /local-test/unmatched/{unmatched_id}/photos/{photo_id}/region-scan`。

- [ ] **Step 1: 写只读、越权和不信任客户端来源失败测试**

在 `v2-api/tests/test_api.py` 增加：

```python
def test_group_region_scan_resolves_trusted_photo_without_mutating_state(monkeypatch, production_client, headers) -> None:
    repo = state_repository.JsonStateRepository()
    before = deepcopy(repo.get_group("g-1"))
    monkeypatch.setattr(local_test, "state_repository", lambda: repo)
    monkeypatch.setattr(
        local_test.photo_barcode_check,
        "scan_photo_region",
        lambda photo, barcode_type, region: {
            "barcode_type": barcode_type,
            "values": ["3130001122100009124734"],
            "normalized_values": ["3130001122100009124734"],
            "method": "barcode",
            "region": region,
            "photo_id": photo["id"],
        },
    )

    response = production_client.post(
        "/local-test/groups/g-1/photos/p-1/region-scan",
        headers=headers["reviewer"],
        json={
            "barcode_type": "module",
            "region": {"x": 0.25, "y": 0.3, "width": 0.4, "height": 0.18},
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["photo_id"] == "p-1"
    assert repo.get_group("g-1") == before

    untrusted_source = production_client.post(
        "/local-test/groups/g-1/photos/p-1/region-scan",
        headers=headers["reviewer"],
        json={
            "barcode_type": "module",
            "region": {"x": 0.25, "y": 0.3, "width": 0.4, "height": 0.18},
            "url": "http://127.0.0.1/private",
        },
    )
    assert untrusted_source.status_code == 422


def test_unmatched_region_scan_rejects_worker_and_unknown_photo(production_client, headers) -> None:
    body = {
        "barcode_type": "meter",
        "region": {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5},
    }
    denied = production_client.post(
        "/local-test/unmatched/unmatched-1/photos/photo-1/region-scan",
        headers=headers["worker"],
        json=body,
    )
    missing = production_client.post(
        "/local-test/unmatched/unmatched-1/photos/not-present/region-scan",
        headers=headers["admin"],
        json=body,
    )

    assert denied.status_code == 403
    assert missing.status_code == 404
```

沿用本文件已有 fixture 的实际资料组/照片 ID；如果 fixture 使用其他 ID，只替换测试常量，不放宽断言。

- [ ] **Step 2: 运行路由测试确认 RED**

```powershell
Set-Location v2-api
..\.venv\Scripts\python.exe -m pytest tests\test_api.py -k "region_scan" -q
```

Expected: 两个新路由返回 `404` 或测试导入失败。

- [ ] **Step 3: 增加严格请求模型和两个只读路由**

在 `local_test.py` 导入 `photo_barcode_check`，并增加禁止额外字段的请求模型：

```python
class NormalizedRegionRequest(BaseModel):
    model_config = {"extra": "forbid"}
    x: float
    y: float
    width: float
    height: float


class PhotoRegionScanRequest(BaseModel):
    model_config = {"extra": "forbid"}
    barcode_type: str
    region: NormalizedRegionRequest
```

两个路由都先调用 `bound_review_actor(request, "")` 做服务端鉴权。正常资料组路由调用当前团队范围的 `repo.get_group(group_id)` 并仅在 `group["photos"]` 中按 ID 查找；未匹配路由调用 `repo.get_unmatched_review(unmatched_id)["review"]` 和 `find_review_photo`。只把服务端找到的 photo、`payload.barcode_type` 和 `payload.region.model_dump()` 传给 `scan_photo_region`，把 `KeyError` 映射为 `404`、坐标/分类/选区过小的 `ValueError` 映射为 `422`、图片解码失败映射为不泄露来源的明确识别失败响应，并且不调用任何 repository 写方法或缓存失效函数。

- [ ] **Step 4: 运行 API 与安全回归测试确认 GREEN**

```powershell
Set-Location v2-api
..\.venv\Scripts\python.exe -m pytest tests\test_api.py -k "region_scan or unmatched_review_response_hides_raw_photo_urls" -q
..\.venv\Scripts\python.exe -m pytest tests\test_security.py -q
```

Expected: 全部通过，未知资料组/记录/照片为 `404`，无权限用户为 `403`，非法分类/坐标/过小选区和额外 `url` 字段为 `422`，响应不含文件路径和 URL。

- [ ] **Step 5: 提交可信路由**

```powershell
git add v2-api/tests/test_api.py v2-api/app/api/routes/local_test.py
git commit -m "feat: expose trusted region scan routes"
```

---

### Task 3: 共享桌面图片检查器

**Files:**
- Create: `scripts/verify_review_image_inspector.js`
- Create: `v2-web/src/components/ReviewImageInspector.vue`

**Interfaces:**
- Consumes props: `src: string`、`alt: string`、`loading: boolean`、`disabled?: boolean`。
- Produces event: `scan`，负载 `{ barcodeType: 'meter' | 'module' | 'collector'; region: { x: number; y: number; width: number; height: number } }`。
- Produces event: `image-load`、`image-error`、`open`。
- Exposes method: `resetSelection(): void`。

- [ ] **Step 1: 写共享组件源码契约失败验证**

创建 `scripts/verify_review_image_inspector.js`：

```javascript
import assert from 'node:assert/strict'
import fs from 'node:fs'

const source = fs.readFileSync('v2-web/src/components/ReviewImageInspector.vue', 'utf8')
assert.match(source, /type BarcodeType = 'meter' \| 'module' \| 'collector'/)
assert.match(source, /const MAGNIFIER_SCALE = 2\.5/)
assert.match(source, /naturalWidth/)
assert.match(source, /naturalHeight/)
assert.match(source, /object-fit:\s*contain/)
assert.match(source, /emit\('scan'/)
assert.match(source, /emit\('open'/)
assert.match(source, /0\.\.1|Math\.min\(1/)
assert.match(source, /框选扫码/)
assert.match(source, /识别选区/)
assert.match(source, /取消框选/)
assert.doesNotMatch(source, /自动判断|自动分类/)
console.log('Review image inspector verification passed.')
```

- [ ] **Step 2: 运行验证确认 RED**

```powershell
node scripts\verify_review_image_inspector.js
```

Expected: `ENOENT`，共享组件尚不存在。

- [ ] **Step 3: 实现稳定几何、放大镜和单选区状态机**

组件内部使用以下稳定类型和状态：

```ts
type BarcodeType = 'meter' | 'module' | 'collector'
type NormalizedRegion = { x: number; y: number; width: number; height: number }
type ContentRect = { left: number; top: number; width: number; height: number }
const MAGNIFIER_SCALE = 2.5
const MIN_SELECTION_CSS_PIXELS = 12
const mode = ref<'view' | 'selecting' | 'ready' | 'submitting'>('view')
```

图片 `load` 时根据 `naturalWidth/naturalHeight` 与容器大小计算 `contain` 后的 `ContentRect`。指针坐标先 clamp 到此矩形，再换算为 `0..1` 坐标；小于 `12px` 的 CSS 选区不进入 `ready`。普通模式悬停时用同一张 `src` 和 `background-size: renderedWidth * 2.5 renderedHeight * 2.5` 显示固定尺寸放大镜；进入框选模式后隐藏放大镜。工具栏用 Element Plus 图标按钮、tooltip、三项单选控件和“识别选区/取消框选”，未选类别或没有有效选区时禁用识别按钮。`src` 改变、组件卸载或父级调用 `resetSelection` 时清空选区与指针状态。

组件不得包含业务 API、草稿字段、扫码状态、归档状态或可见解释性文字；双击/打开事件继续交给父组件既有大图能力。

- [ ] **Step 4: 运行源码验证和 TypeScript 构建确认 GREEN**

```powershell
node scripts\verify_review_image_inspector.js
Set-Location v2-web
npm run build
```

Expected: 验证输出 `Review image inspector verification passed.`，`vue-tsc` 与 Vite 构建成功。

- [ ] **Step 5: 提交共享组件**

```powershell
git add scripts/verify_review_image_inspector.js v2-web/src/components/ReviewImageInspector.vue
git commit -m "feat: add review image region inspector"
```

---

### Task 4: API 客户端与两个审阅入口集成

**Files:**
- Modify: `scripts/verify_project_board_unmatched_review.js`
- Create: `scripts/verify_task_hall_region_scan.js`
- Modify: `v2-web/src/api/types.ts`
- Modify: `v2-web/src/api/services.ts`
- Modify: `v2-web/src/components/UnmatchedReviewDialog.vue`
- Modify: `v2-web/src/views/TaskHallView.vue`

**Interfaces:**
- Consumes: `ReviewImageInspector` 的 `scan` 事件、Task 2 的两个只读 API、现有 `metadataDraft`、`draft`、`saveUnmatchedReview` 和正常审阅保存动作。
- Produces: `scanGroupPhotoRegion(groupId, photoId, request) -> Promise<RegionScanResult>`。
- Produces: `scanUnmatchedPhotoRegion(unmatchedId, photoId, request) -> Promise<RegionScanResult>`。

- [ ] **Step 1: 写客户端映射和双入口草稿替换失败验证**

在 `scripts/verify_project_board_unmatched_review.js` 增加对 `ReviewImageInspector`、`scanUnmatchedPhotoRegion`、`draft.meterNo/moduleAssetNo/collector` 和原值/识别值确认弹窗的断言。创建 `scripts/verify_task_hall_region_scan.js`：

```javascript
import assert from 'node:assert/strict'
import fs from 'node:fs'

const hall = fs.readFileSync('v2-web/src/views/TaskHallView.vue', 'utf8')
const services = fs.readFileSync('v2-web/src/api/services.ts', 'utf8')
const types = fs.readFileSync('v2-web/src/api/types.ts', 'utf8')
assert.match(hall, /ReviewImageInspector/)
assert.match(hall, /scanGroupPhotoRegion/)
assert.match(hall, /metadataDraft\.meterNo/)
assert.match(hall, /metadataDraft\.moduleAssetNo/)
assert.match(hall, /metadataDraft\.collector/)
assert.match(hall, /原值/)
assert.match(hall, /识别值/)
assert.match(hall, /替换/)
assert.match(services, /groups\/\$\{encodeURIComponent\(groupId\)\}\/photos\/\$\{encodeURIComponent\(photoId\)\}\/region-scan/)
assert.match(types, /export type RegionScanResult/)
assert.doesNotMatch(hall, /barcodeCheckStatus\s*=/)
console.log('Task hall region scan verification passed.')
```

- [ ] **Step 2: 运行验证确认 RED**

```powershell
node scripts\verify_project_board_unmatched_review.js
node scripts\verify_task_hall_region_scan.js
```

Expected: 新断言因客户端方法和共享组件集成尚不存在而失败。

- [ ] **Step 3: 增加严格前端类型和 API 映射**

在 `types.ts` 增加：

```ts
export type BarcodeType = 'meter' | 'module' | 'collector'
export type NormalizedRegion = { x: number; y: number; width: number; height: number }
export type RegionScanRequest = { barcodeType: BarcodeType; region: NormalizedRegion }
export type RegionScanResult = {
  barcodeType: BarcodeType
  values: string[]
  normalizedValues: string[]
  method: 'barcode' | 'ocr' | 'none'
  region: NormalizedRegion
}
```

在 `services.ts` 增加唯一映射器和两个 POST 方法；请求体必须只含 `barcode_type` 和 `region`，不得加入 `imageUrl`、`sourceUrl`、路径或 base64。

- [ ] **Step 4: 集成父页面确认流程与过期请求防护**

两个页面都用 `regionScanSerial` 和当前 group/unmatched/photo ID 验证响应仍属于当前会话。收到零候选时保留选区并提示“当前选区未识别到可用内容”；单候选直接进入确认；多候选用单选列表选择后才能继续。确认弹窗固定展示类别、原值、识别值和识别方式，点击“替换”时按以下映射只写草稿：

```ts
const draftFieldByBarcodeType = {
  meter: 'meterNo',
  module: 'moduleAssetNo',
  collector: 'collector',
} as const
```

正常审阅写 `metadataDraft[field]`，未匹配审阅写 `draft[field]`；取消确认不修改草稿。页面切换照片、切换资料组/未匹配记录、关闭弹窗或请求过期时递增 serial 并调用检查器的 `resetSelection()`。不触发重新扫码、人工扫码确认、分类保存、审阅保存、归档或缓存失效 API。

- [ ] **Step 5: 运行双入口验证和前端构建确认 GREEN**

```powershell
node scripts\verify_review_image_inspector.js
node scripts\verify_project_board_unmatched_review.js
node scripts\verify_task_hall_region_scan.js
Set-Location v2-web
npm run build
```

Expected: 三个验证脚本通过，TypeScript 与 Vite 构建通过。

- [ ] **Step 6: 提交双入口集成**

```powershell
git add scripts/verify_project_board_unmatched_review.js scripts/verify_task_hall_region_scan.js v2-web/src/api/types.ts v2-web/src/api/services.ts v2-web/src/components/UnmatchedReviewDialog.vue v2-web/src/views/TaskHallView.vue
git commit -m "feat: integrate region scan into review flows"
```

---

### Task 5: 桌面浏览器验收与跨功能回归

**Files:**
- Modify: `ops/releases/V3.0.83.md`（由终端优先施工计划的联合发布任务创建后补充本功能证据）

**Interfaces:**
- Consumes: 正常审阅页、未匹配审阅弹窗、两个区域识别 API 和已有保存/审计流程。
- Produces: V3.0.83 发布记录中的桌面验收证据，不增加移动端验收。

- [ ] **Step 1: 运行聚焦后端和前端验证**

```powershell
Set-Location v2-api
..\.venv\Scripts\python.exe -m pytest tests\test_photo_barcode_check.py tests\test_api.py -k "region_scan or barcode or unmatched_review" -q
Set-Location ..
node scripts\verify_review_image_inspector.js
node scripts\verify_project_board_unmatched_review.js
node scripts\verify_task_hall_region_scan.js
```

Expected: 全部通过。

- [ ] **Step 2: 启动本地生产形态服务并做桌面浏览器验收**

```powershell
.\scripts\run-client-demo.ps1
```

在 `1440x900` 桌面视口验证：正常审阅与未匹配审阅均能悬停显示约 2.5 倍放大镜；框选不能进入 `contain` 留白；未选类别不能识别；条码、二维码、OCR 候选能显示；多候选必须单选；取消不改草稿；替换只改草稿；切换照片后旧响应不覆盖新照片；原有双击大图仍可用。再用浏览器网络与页面状态确认区域请求后 `barcode_check_status`、归档状态和驾驶舱准确率没有变化。

- [ ] **Step 3: 验证原有保存审计仍是唯一落库路径**

分别在两个入口执行一次“替换”后取消页面，确认数据库未变化；再次替换并点击原有保存，确认字段写入且现有审计记录包含操作者、实体 ID、修改前后值和时间。确认未产生 `00000000`、`manual-` 或 `unmatched-` 正式资料组。

- [ ] **Step 4: 记录浏览器证据并提交**

把桌面视口、测试账号角色、两个路由响应、保存前后数据库检查和无扫码状态副作用写入 `ops/releases/V3.0.83.md` 的“图片框选识别验收”段落：

```powershell
git add ops/releases/V3.0.83.md
git commit -m "docs: record V3.0.83 region scan acceptance"
```
