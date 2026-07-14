# 甲方第一版历史视觉 QA 记录

本记录用于证明第一版演示页面已经做过真实浏览器视觉巡检。巡检目标不是替代现场演示，而是降低交付前出现页面跳动、横向溢出、中文乱码、首屏空白等低级观感问题的风险。

## 巡检环境

- 浏览器：Codex in-app browser
- 本地地址：`http://127.0.0.1:8000`
- 视口：`1366 x 760`
- 巡检时间：`2026-06-10`
- 巡检页面：
  - `/login`
  - `/project-board`
  - `/claim-tasks`
  - `/task-hall`
  - 当时的异常处理页面（现已退休）
  - `/sync-config`

## 视觉验收项

| 项目 | 结果 |
| --- | --- |
| 顶部导航高度 | 主工作台页面均为 `64px` |
| 主面板头高度 | 项目看板、任务领取、审阅工作台、异常处理均为 `48px` |
| 品牌区宽度 | 主工作台页面统一为 `230px` |
| 页面导航高度 | 主工作台页面统一为 `37px` |
| 横向溢出 | 未发现 |
| 可见中文乱码 | 未发现 |
| 首屏空白 | 未发现 |
| 当前页面选中态 | 项目看板、任务领取、审阅工作台、异常处理均可正确高亮 |

## 浏览器实测摘要

```text
/project-board
  topbar: 64px
  panel header: 48px
  page nav: 37px
  horizontal overflow: false
  mojibake hits: none

/claim-tasks
  topbar: 64px
  panel header: 48px
  page nav: 37px
  horizontal overflow: false
  mojibake hits: none

/task-hall
  topbar: 64px
  panel header: 48px
  page nav: 37px
  horizontal overflow: false
  mojibake hits: none

/sync-config
  topbar: 64px
  page nav: 37px
  horizontal overflow: false
  mojibake hits: none
```

## 防回退措施

- `scripts/verify-static-pages.py` 已检查主工作台页面必须使用 `--topbar-height: 64px`。
- `scripts/verify-static-pages.py` 已检查主工作台页面必须包含 `height: 48px` 和 `min-height: 48px` 的面板头规格。
- `scripts/verify-static-pages.py` 已检查常见中文乱码片段，例如 `椤圭洰`、`鐪嬫澘`、`浠诲姟`、`瀹￠槄`。
- `v2-api/tests/test_api.py` 已包含静态页面乱码防线自测试，确保真实乱码页面会被拒绝。

## V3.0.80 待验证项

- `/project-board` 的扫码未匹配清单与逐条审阅弹窗不继承 2026-06-10 的历史视觉结论。
- V3.0.80 本轮桌面与手机浏览器验证结果应写入 `ops/releases/V3.0.80.md`，在执行前保持待验证。

## 结论

本文件仅保留 2026-06-10 第一版页面的历史巡检证据，不作为 V3.0.80 新弹窗已验证的证明。现场验收前按 `docs/CLIENT_DEMO_SCRIPT.md` 和本轮发布记录重新执行视觉检查。
