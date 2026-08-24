# 采集器盘点与翻拍工作台实施计划

> 基线：V3.2.5 线上源码提交 `ef4394c687610c2ba4f65423c4801f1138c7ad41`。
>
> 开发分支：`feature/collector-transfer-workbench`；生产数据库和服务器不在本计划自动执行范围内。

## Task 1：固化领域不变量和数据库结构

**文件**

- 新增：`v2-api/tests/test_collector_transfer_domain.py`
- 修改：`v2-api/app/models.py`
- 新增：`v2-api/alembic/versions/0015_collector_transfer_workbench.py`
- 修改：`v2-api/tests/test_models.py`
- 修改：`v2-api/tests/test_migrations.py`

**步骤**

1. 先写失败测试，覆盖终端内采集器去重、同号判定、池不足整笔失败和不重复消耗。
2. 新增旁路 SQLAlchemy 模型及数据库唯一/检查约束。
3. 新增从 `20260724_0014` 链接的可逆迁移。
4. 运行聚焦测试，确认先红后绿。

## Task 2：实现快照生成、扫码与分配服务

**文件**

- 新增：`v2-api/app/services/collector_transfer.py`
- 新增：`v2-api/tests/test_collector_transfer_service.py`

**步骤**

1. 为现有资料组投影写失败测试：每表一个新装项、终端内采集器去重、两个固定照片槽位。
2. 实现号码文本规范化和兼容字段读取，不修改来源模型。
3. 为扫码决策写失败测试，覆盖同号有图、同号无图、非同号三种结果及幂等重扫。
4. 实现照片登记、SHA256 去重与池状态转换。
5. 为随机分配事务写失败测试，覆盖候选不足零副作用、结果持久化和重复调用幂等。
6. 实现数据库锁、唯一约束冲突处理和审计写入。

## Task 3：实现后端 API 与逐个扫码初始化

**文件**

- 新增：`v2-api/app/api/routes/collector_transfer.py`
- 修改：`v2-api/app/api/router.py`
- 修改：`v2-api/app/main.py`
- 新增：`v2-api/tests/test_collector_transfer_api.py`

**步骤**

1. 先写 API 契约失败测试，验证团队隔离、角色权限、错误码和返回结构。
2. 注册 `/collector-transfer` 路由并加入生产认证前缀。
3. 实现运行创建/查询、扫码、补拍、分配、工作台查询和完成/撤销接口。
4. 手机端只保留逐个扫码和逐个补拍；不提供新采集器 Excel 或照片批量导入接口。
5. 确认所有接口都不接受甲方凭据、不调用甲方平台。

## Task 4：实现 Vue API 契约和条形码组件

**文件**

- 修改：`v2-web/src/api/types.ts`
- 修改：`v2-web/src/api/services.ts`
- 新增：`v2-web/src/components/Code128Barcode.vue`
- 新增：`v2-web/src/components/__tests__/Code128Barcode.spec.ts`

**步骤**

1. 先写条形码可访问文本与空值行为测试。
2. 增加采集器中转类型和 API 调用。
3. 使用项目现有依赖或小型受测实现生成 Code 128；条形码下保留原始文本。

## Task 5：实现手机盘点页

**文件**

- 新增：`v2-web/src/views/CollectorInventoryView.vue`
- 新增：`v2-web/src/views/__tests__/CollectorInventoryView.spec.ts`
- 修改：`v2-web/src/router/index.ts`
- 修改：`v2-web/src/router/staticPages.ts`

**步骤**

1. 按已认可手机草图建立允许文案、色彩、间距、状态与组件清单。
2. 先写失败测试，覆盖扫码提交后的三种判定、补拍按钮和“无甲方录入入口”。
3. 实现 `BarcodeDetector` 摄像头扫码；不支持时提供手工输入/外接扫码枪回退。
4. 实现手机相机补拍、预览、上传进度和重复扫码反馈。
5. 在 390px 与现有桌面宽度验证无横向溢出。

## Task 6：实现桌面翻拍工作台

**文件**

- 新增：`v2-web/src/views/CollectorWorkbenchView.vue`
- 新增：`v2-web/src/views/__tests__/CollectorWorkbenchView.spec.ts`
- 修改：`v2-web/src/router/index.ts`
- 修改：`v2-web/src/router/staticPages.ts`

**步骤**

1. 先写失败测试，覆盖终端选择、新装两张照片、拆除一张照片、上一项/下一项和完成/撤销。
2. 实现左侧终端队列和右侧翻拍画布，保持编号条码与文本同时可见。
3. 明确显示该页面仅辅助人工录入，不自动登录或上传甲方平台。
4. 在 1440px 桌面和较窄窗口验证布局、键盘操作和图片适配。

## Task 7：回归、视觉对照与交付

1. 运行所有聚焦后端测试、迁移测试、前端测试、类型检查和生产构建。
2. 运行完整后端测试；超时或无输出不视为通过。
3. 启动本地 FastAPI/Vue，使用内置浏览器走通：创建运行 -> 手机同号/非同号扫码 -> 补拍 -> 随机分配 -> 桌面逐项翻拍确认。
4. 分别截取手机和桌面实现图，与已认可草图用 `view_image` 对照；记录至少五项视觉核对和修正。
5. 运行 `git diff --check`、查看变更影响和工作区状态。
6. 只交付本地分支、迁移文件和验证证据；生产执行前重新申请确认。
