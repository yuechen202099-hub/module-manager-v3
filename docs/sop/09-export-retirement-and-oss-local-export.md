# V3.2.3 导出退休、外链迁移与 OSS 本机导出 SOP

本 SOP 只适用于 V3.2.3 候选发布完成本地验证之后的受控操作。导出中心、浏览器 CSV 和服务器交付包已退休；应用回滚到 V3.2.2 时仍保留 Nginx `410 Gone` 拦截。迁移、清单生成和本机下载互相独立，不得把生产数据库或 OSS 写凭据带到本机。

## 固定安全边界

- 外链迁移启动前要求 `MemAvailable >= 400 MiB`、临时空间 `>= 512 MiB`、API 健康且没有新增 OOM；运行中 `MemAvailable < 250 MiB`、健康检查失败、新 OOM 或连续 `5 次` OSS 错误时立即停止。
- 外链迁移严格为单 worker、一次一张、单文件 `30 MiB` 硬上限；`--execute` 和 `--resume` 必须提供私有来源主机 `allowlist`，下载采用 DNS 固定、禁止重定向并拒绝私网/回环/保留地址。
- 迁移报告目录权限为 `0700`，报告文件为 `0600`；报告与标准输出必须脱敏，不得包含 URL 查询参数、OSS 密钥、数据库凭据或签名 URL。默认服务器报告目录位于系统临时目录下的 `module-manager-v3-operations/external-photo-oss`，也可用 `MODULE_MANAGER_MIGRATION_DIR` 指向 release 目录之外的私有运维目录。
- 本机下载最多 `4` 并发，最多 `8` 个 pending 下载，重试等待固定为 `1/2/4` 秒，使用 `.part` 与原子替换。默认目录为 `C:\Users\Administrator\Downloads\module-manager-exports\<YYYYMMDD-HHmmss>`。
- 任何失败、冲突、未知存储类型、剩余有效 `external_url`、数量或 SHA256 不一致都表示导出或迁移不完整。保留成功文件和失败清单，立即停止“完整”结论，不得用空文件、占位文件或改写状态掩盖失败。
- 所有流程禁止覆盖、移动或删除 OSS 对象。回滚只恢复数据库字段，不删除 OSS；本机导出只读 OSS。

## 流程一：只读 dry-run 与私有报告

先在服务器建立 release 目录之外、仅部署用户可访问的目录，再运行只读预检。此流程不下载、不上传、不写数据库。

```bash
set -euo pipefail
REPORT_DIR=/var/lib/module-manager-v2/private-operations/v3.2.3-external-photo
install -d -o modulemgr -g modulemgr -m 0700 "$REPORT_DIR"
cd /opt/module-manager-v2/current/v2-api
umask 077
sudo -u modulemgr /opt/module-manager-v2/venv/bin/python scripts/migrate_external_photos_to_oss.py \
  --dry-run \
  --report "$REPORT_DIR/dry-run.json"
test "$(stat -c %a "$REPORT_DIR/dry-run.json")" = 600
```

检查 `source_hosts`、候选数、空/未知存储类型、声明哈希分类和预检失败。开始前仍须满足 `400 MiB` 内存和 `512 MiB` 临时空间；后续执行保持单 worker、`30 MiB` 上限、`250 MiB` 运行停止阈值及连续 `5 次` OSS 错误停止规则。由 `source_hosts` 人工核准并在同一 `0700` 目录建立 `0600` allowlist；不要将 allowlist 或报告打入发布包。

## 流程二：10 张 execute 与同 ID resume

以下两个命令必须使用同一个 `MIGRATION_ID`。先执行 10 张，核对预览、OSS HEAD、审计字段、条码证据、内存和零交付任务新增；全部通过才允许用 `--resume` 继续。

```bash
set -euo pipefail
REPORT_DIR=/var/lib/module-manager-v2/private-operations/v3.2.3-external-photo
ALLOWLIST="$REPORT_DIR/allowed-hosts.txt"
MIGRATION_ID=v323-external-photo-20260819
cd /opt/module-manager-v2/current/v2-api
umask 077
test "$(stat -c %a "$ALLOWLIST")" = 600
sudo -u modulemgr /opt/module-manager-v2/venv/bin/python scripts/migrate_external_photos_to_oss.py \
  --execute --migration-id "$MIGRATION_ID" --allowlist-file "$ALLOWLIST" --limit 10 \
  --report "$REPORT_DIR/$MIGRATION_ID-limit10.json"
```

### 人工核验与审批停止点

到此必须停止。逐张核对 10 张预览、OSS HEAD、数据库审计字段、条码证据、内存、OOM 记录和交付任务计数；只有结果全部通过且发布负责人明确批准继续，才可复制下一代码块。任何失败、冲突、剩余异常或未获得明确批准都不得执行 `--resume`。

```bash
set -euo pipefail
REPORT_DIR=/var/lib/module-manager-v2/private-operations/v3.2.3-external-photo
ALLOWLIST="$REPORT_DIR/allowed-hosts.txt"
MIGRATION_ID=v323-external-photo-20260819
cd /opt/module-manager-v2/current/v2-api
umask 077
test "$(stat -c %a "$ALLOWLIST")" = 600
sudo -u modulemgr /opt/module-manager-v2/venv/bin/python scripts/migrate_external_photos_to_oss.py \
  --resume --migration-id "$MIGRATION_ID" --allowlist-file "$ALLOWLIST" \
  --report "$REPORT_DIR/$MIGRATION_ID-resume.json"
```

执行/恢复始终是单 worker、单文件最多 `30 MiB`，启动阈值为 `400 MiB`/`512 MiB`，运行低于 `250 MiB` 或连续 `5 次` OSS 错误即停止。报告必须为脱敏 `0600` 文件；若 `remaining_external_url`、失败或冲突不为零，保留同一 ID 并再次诊断/恢复，不得宣布完成。

## 流程三：仅数据库 rollback，不删除 OSS

回退批次时只使用原迁移 ID。该模式不读取 allowlist、不访问外链、不访问 OSS，只恢复批次保存的数据库存储字段并按证据版本规则失效条码验证。

```bash
set -euo pipefail
REPORT_DIR=/var/lib/module-manager-v2/private-operations/v3.2.3-external-photo
MIGRATION_ID=v323-external-photo-20260819
cd /opt/module-manager-v2/current/v2-api
umask 077
START_MEMORY_KIB=$((400 * 1024))
STOP_MEMORY_KIB=$((250 * 1024))
START_TEMP_FREE_KIB=$((512 * 1024))
MEM_AVAILABLE_KIB=$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)
test "$MEM_AVAILABLE_KIB" -ge "$START_MEMORY_KIB" || { echo "MemAvailable is below the 400 MiB start threshold" >&2; exit 1; }
test "$MEM_AVAILABLE_KIB" -ge "$STOP_MEMORY_KIB" || { echo "MemAvailable is below the 250 MiB emergency stop threshold" >&2; exit 1; }
TEMP_FREE_KIB=$(df -Pk "${TMPDIR:-/tmp}" | awk 'NR==2 {print $4}')
test "$TEMP_FREE_KIB" -ge "$START_TEMP_FREE_KIB" || { echo "Temporary free space is below 512 MiB" >&2; exit 1; }
sudo -u modulemgr /opt/module-manager-v2/venv/bin/python scripts/migrate_external_photos_to_oss.py \
  --rollback-run "$MIGRATION_ID" \
  --report "$REPORT_DIR/$MIGRATION_ID-rollback.json"
```

rollback 是数据库-only；不删除 OSS、不覆盖 OSS、不移动 OSS。报告仍须脱敏并为 `0600`。尽管 rollback 不做网络迁移，也不得绕过 `400 MiB`/`512 MiB` 运维预检；任何不完整或冲突报告都必须停止并人工核对，Nginx 410 继续保留。

## 流程四：服务器清单 stdout 直接 pipe 到本机下载器

在 Windows PowerShell 中执行。服务器只在只读事务中查询标量字段并输出 header-first JSON Lines；签名 URL 只存在于管道，不落盘。本机下载器从标准输入读取并直接从 OSS 下载。

```powershell
$Key = "C:\Users\Administrator\Downloads\production-readonly.pem"
$Server = "modulemgr@www.sgcc.online"
$TeamId = "default-team"
$TaskId = 17
$ExportSummary = ssh -i $Key $Server "cd /opt/module-manager-v2/current/v2-api && /opt/module-manager-v2/venv/bin/python scripts/build_oss_export_manifest.py --team-id '$TeamId' --task-id $TaskId --archived-only" |
  .\.venv\Scripts\python.exe .\scripts\oss_local_export.py --format files --format zip --format csv --format xlsx --max-workers 4
if ($LASTEXITCODE -ne 0) { throw "OSS 本机导出不完整；保留输出和失败清单并停止。" }
$Output = ($ExportSummary | ConvertFrom-Json).output_root
Write-Host "OSS 本机导出目录: $Output"
```

此命令必须省略 `--output`，让下载器把已识别的默认 Downloads known-folder 边界规范化后使用 `C:\Users\Administrator\Downloads\module-manager-exports\<YYYYMMDD-HHmmss>`；不要把可见的 Downloads Junction 作为自定义显式根目录传回工具。成功后从命令输出 JSON 的 `output_root` 读取实际显示路径。本机最多 `4` 并发/`8` pending，按 `1/2/4` 秒重试；报告不保存签名 URL。若任一对象不存在、签名失效、SHA256/大小不符、磁盘不足或计划/成功数不一致，保留 `.part` 清理后的成功文件与失败清单并停止，不得声称完整。此流程只读 OSS，绝不删除 OSS。
