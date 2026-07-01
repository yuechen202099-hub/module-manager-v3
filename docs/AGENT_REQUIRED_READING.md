# 下一个 Agent 必读

本文是生产维护入口。接手前先读本文件、仓库根目录 `AGENTS.md`、`docs/sop/README.md`，再动代码。

## 当前生产身份

- GitHub 仓库：`https://github.com/yuechen202099-hub/module-manager-v3`
- 生产维护分支：`production/V3/3.0.72`
- 当前生产应用基线：`V3.0.72`
- 生产分支命名规则：`production/V3/<version>`，例如 `production/V3/3.0.72`。旧 `production/v3.0.35` 仅保留历史兼容，不作为新开发基线。
- 当前本地生产 worktree：`C:\Users\Administrator\.config\superpowers\worktrees\module-manager-v3\production-v3.0.24`
- worktree 路径里的 `production-v3.0.24` 是创建时名称，不代表当前线上版本。

## 不可突破的生产边界

- 不提交、不覆盖 `.env`、`data/`、`v2-api/data/`、`v2-api/app/static/uploads/`、生产数据库、真实上传图片和发布压缩包。
- 不直接修改 OSS 生产对象或 PostgreSQL 生产数据；如必须处理，需要用户单独确认备份、dry-run、回滚方案。
- 代码改动默认 patch 版本 `+0.01`；大流程或主业务规则变更先请用户确认是否 `+0.1`。
- 文档、SOP、协作规则只改文档版本，不改应用版本。
- 发布前必须备份生产环境，保留 `.env`、data、uploads、数据库 dump，并记录 release package hash。
- 每次生产发布健康检查通过后，服务器 `/opt/module-manager-v2/releases` 只保留最近 5 个 release 目录；旧版本留存在 GitHub 分支/tag 和 `ops/releases/` 记录中即可。清理必须先 dry-run，且不得删除 `.env`、data、uploads、backups 或数据库 dump。

## 业务硬规则

- 总清单是安装地址唯一来源。
- 安装地址不得去重；安装地址、表号、资料组保持一对一。
- 页面展示表号使用总清单原始表号。
- 长扫码条码匹配键：去掉前 11 位和最后 1 位。
- 总清单短表号匹配键：去掉前 2 位。
- 资料组异常时绝不能生成或展示 `00000000` 兜底工单；扫到不在工单中的任务应提示无工单。
- 自动上传目前按用户要求关闭；不要擅自恢复。
- 只有 4 张照片完整的资料组才做后台条码/二维码/OCR 扫描。
- 图片扫码判断在后台静默低速执行，不在前台同步计算；低性能服务器按小批次串行处理。

## 项目结构

- `v2-api/`：FastAPI 后端、服务层、测试。
- `v2-web/`：Vue 3 + TypeScript + Vite + Element Plus 前端。
- `v2-api/app/static/vue/`：生产静态前端构建产物，发布包会使用这里的文件。
- `docs/sop/`：生产维护 SOP。
- `ops/releases/`：每个生产版本的发布记录。
- `infra/`：生产 systemd、timer、Nginx 等部署辅助文件。
- `scripts/`：本地和生产验证、构建、维护脚本。

## 已使用和应继续使用的插件 / Skill

| 名称 | 用途 | 接手规则 |
| --- | --- | --- |
| `codebase-memory-mcp` | 代码图谱和架构发现 | 优先用 `search_graph`、`trace_path`、`get_code_snippet`、`query_graph`、`get_architecture`；图谱缺失时再用 `rg`。当前索引项目名是 `C-Users-Administrator-.config-superpowers-worktrees-module-manager-v3-production-v3.0.24`。 |
| `github:yeet` | 提交、推送、发 PR 或发布到 GitHub | 推送前先 `git status -sb` 和 `git diff --cached`，混合工作区必须显式排除数据、上传图片、密钥和构建压缩包。 |
| `browser:control-in-app-browser` | 页面验证 | 用于验证 `/login`、`/project-board`、`/task-hall`、`/construction` 等页面行为和截图问题。 |
| `build-web-apps:frontend-testing-debugging` | 前端问题定位 | 页面变慢、弹窗、分页、按钮状态、图片加载等 UI 问题优先用它做浏览器验证。 |
| `superpowers:systematic-debugging` | P0 bug 定位 | 生产 bug 先复现和定位根因，再改；不要猜测式修复。 |
| `superpowers:test-driven-development` | 新功能和 bugfix | 先补测试或验证脚本，再改实现。 |
| `superpowers:requesting-code-review` + multi-agent tools | 代码审阅 | 用户要求所有开发代码由子智能体审阅；发布前让审阅 agent 看 staged diff 或关键改动。 |
| `superpowers:verification-before-completion` | 完成前验证 | 最终汇报前必须有实际命令输出或线上/API/page 验证结果。 |

## 并行开发协作规则

- 生产维护线由当前线程负责，生产分支只保存已上线或即将上线的稳定版本。
- 小程序团队从最新生产分支切 `mp/<短功能名>` 分支，不直接提交到 `production/V3/<version>`。
- 项目管理平台团队从最新生产分支切 `pm-platform/<短功能名>` 分支，不直接提交到 `production/V3/<version>`。
- 外部团队交付代码时优先提交 PR；无法 PR 时提供 patch 包和验证结果，由生产维护线审阅、合并、统一升版本。
- 版本号由生产维护线统一分配：小更新或 BUG 修复 `+0.01`，大流程变更经用户确认后 `+0.1`。外部团队不得自行占用正式生产版本号。
- 多个团队并行时以合并进入生产线的顺序递增版本号；未合并分支只使用候选标识，不写入正式 `APP_VERSION`。

## 常用验证命令

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api/tests
.\.venv\Scripts\python.exe .\scripts\verify_release_sop.py
.\.venv\Scripts\python.exe .\scripts\verify-client-release.py --help
cd v2-web; npm run build
```

按风险选择验证范围。生产发布前还要做服务器健康检查和页面/API 验证。

## GitHub 发布前检查

```powershell
git status -sb
git diff --stat
git diff --cached --stat
git diff --cached --name-only
```

禁止 staged 文件中出现：

- `.env`、`.pem`、数据库 dump、真实账号密码或 token。
- `data/`、`v2-api/data/`、`v2-api/app/static/uploads/`。
- `build/`、发布 zip/tar 包、`__pycache__/`、`node_modules/`。

可以提交：

- `v2-api/app/static/vue/assets/` 的生产前端静态构建文件。
- `ops/releases/` 的版本记录。
- `infra/` 的 systemd/timer 脚本。
- 自动化验证脚本和测试。

## 当前维护重点

- 生产线以线上稳定为最高优先级，不混入开发环境 `3.0.56` 之类内容。
- 数据中台、项目驾驶舱、审阅工作台、施工采集页是当前高频维护页面。
- 图片扫码准确率、人工确认、分类完成状态、自动归档和后台慢速维护任务是当前重点链路。
- 登录有效期为当天有效；过期后任何操作应跳转登录页。
- 任务领取页进度 100% 后按钮应显示 `已施工` / `已审阅` 且不可用。
