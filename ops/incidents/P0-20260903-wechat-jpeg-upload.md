# P0 Incident: WeChat JPEG Upload Replacement Rejection

## Incident

- Title: 微信 JPEG 上传替换误报不完整
- Start time: 2026-09-03 21:00 +08:00
- Detected by: 现场用户反馈
- Production version: V3.2.28
- Commit: a095c7fd0fd90f1e9cb79705f937bbd689b81002
- Severity: P0

## Impact

- Affected users: 使用上传替换功能的管理员
- Affected workflow: 资料照片上传与替换
- Data risk: 无数据破坏；请求在保存数据库或 OSS 前被拒绝
- Customer-visible symptom: 微信图片提示 `jpeg is incomplete`

## Immediate Actions

- [x] Freeze unrelated changes.
- [x] Preserve the reported filename and error text.
- [x] Record current release and package hash.
- [x] Choose a minimal hotfix without modifying existing data or OSS objects.

## Root Cause

公共图片校验要求 JPEG 结束标记必须位于文件最后。微信生成的部分 JPEG 主体可完整解码，但结束标记后保留应用附加数据，因此被错误判定为截断图片。

## Fix

- Branch: `production/V3/3.2.29`
- Commit: 3e02390502a77dceb226232a61e2eee82163bd31
- Tests: JPEG 校验、上传替换接口、完整后端回归和发布契约
- Review: 单线程差异与安全边界复核
- Package: `build/server-release/module-manager-v2-server-3.2.29.zip`
- SHA256: d579be3f89b49ab845a8098323880a90bdeabf9e2c851e345add3fafc2972a78

## Production Evidence

- Backup directory: /opt/module-manager-v2/backups/V3.2.29-pre-20260903_214054
- Release directory: /opt/module-manager-v2/releases/v3.2.29-20260903T134524Z
- Health check: local and public HTTP 200, version 3.2.29
- Page/API checks: key local/public pages returned HTTP 200; deployed JPEG validator accepted the reported trailing-data shape and still rejected missing EOI
- Rollback target: V3.2.28

## Follow-Up

- New tests added: 可完整解码且 EOI 后带附加数据的 JPEG；缺少 EOI 的截断 JPEG
- SOP gap: 无
- Preventive action: 对容器格式完整性判断同时使用结构标记和完整解码证据
- Owner: Codex production maintainer
- Due date: 2026-09-03
