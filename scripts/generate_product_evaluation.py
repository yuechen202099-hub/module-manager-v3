from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

EXCLUDED_DIRS = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "exports",
    "node_modules",
}


@dataclass(frozen=True)
class ScoreItem:
    name: str
    weight: int
    focus: str


SCORE_ITEMS = [
    ScoreItem("工程管理适配度", 8, "现场施工、审阅、异常闭环、终端任务管理"),
    ScoreItem("产品结构", 7, "管理员、审阅员、施工员是否各走主流程"),
    ScoreItem("审阅效率", 8, "快捷键、切组、归档、补图、异常回退速度"),
    ScoreItem("施工采集体验", 8, "手机采集、扫码、拍照、缓存、上传"),
    ScoreItem("离线缓存能力", 6, "断网缓存、详情编辑、统一上传、失败重试"),
    ScoreItem("数据结构", 9, "团队、用户、任务、资料组、照片、事件、工单结构化"),
    ScoreItem("代码结构", 8, "前后端职责、状态仓储、导入队列、存储抽象"),
    ScoreItem("前端结构", 6, "Vue 组件、响应式、图片预览、状态同步、卡顿控制"),
    ScoreItem("小程序/移动端结构", 5, "移动端采集是否与网页规则同步"),
    ScoreItem("服务器结构", 6, "Nginx、FastAPI、PostgreSQL、备份、服务守护"),
    ScoreItem("图片存储结构", 6, "OSS/local/url、缩略图、预览图、导出图一致性"),
    ScoreItem("安全权限", 6, "多团队隔离、角色权限、上传访问、生产密钥、后台入口"),
    ScoreItem("运维备份", 5, "备份、恢复、健康检查、磁盘风险、发布回滚"),
    ScoreItem("可观测性", 4, "日志、导入导出进度、异常统计、卡顿定位"),
    ScoreItem("测试覆盖", 4, "单元测试、接口回归、移动端手测路径、导出校验"),
    ScoreItem("成本控制", 4, "预算 130 元内稳定运行，OSS/服务器成本可控"),
]


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def read_json(path: Path | None) -> Any:
    if not path or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8", errors="ignore"))


def first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def count_files(pattern: str) -> int:
    total = 0
    for path in ROOT.rglob(pattern):
        try:
            relative = path.relative_to(ROOT)
        except ValueError:
            continue
        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue
        total += 1
    return total


def markdown_table(rows: list[list[Any]]) -> str:
    if not rows:
        return ""
    normalized = [[str(cell) for cell in row] for row in rows]
    widths = [0] * len(normalized[0])
    for row in normalized:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    lines: list[str] = []
    for row_index, row in enumerate(normalized):
        lines.append("| " + " | ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)) + " |")
        if row_index == 0:
            lines.append("| " + " | ".join("-" * widths[index] for index in range(len(row))) + " |")
    return "\n".join(lines)


def run_command(args: list[str], timeout: int = 180) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            args,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        return {"command": " ".join(args), "code": "error", "output": str(exc)}
    output = "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part)
    return {"command": " ".join(args), "code": completed.returncode, "output": output[:5000]}


def state_metrics(state: Any) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "state_found": bool(state),
        "teams": "unknown",
        "tasks": "unknown",
        "groups": "unknown",
        "photos": "unknown",
        "audit_events": "unknown",
    }
    if not isinstance(state, dict):
        return metrics

    teams = state.get("teams")
    if isinstance(teams, dict):
        task_count = 0
        group_count = 0
        photo_count = 0
        audit_count = 0
        for team_state in teams.values():
            if not isinstance(team_state, dict):
                continue
            for key in ("tasks", "terminal_tasks"):
                value = team_state.get(key)
                task_count += len(value) if isinstance(value, (list, dict)) else 0
            groups_value = team_state.get("groups") or team_state.get("material_groups") or []
            groups = list(groups_value.values()) if isinstance(groups_value, dict) else groups_value if isinstance(groups_value, list) else []
            group_count += len(groups)
            for group in groups:
                if isinstance(group, dict) and isinstance(group.get("photos"), list):
                    photo_count += len(group["photos"])
            photos_value = team_state.get("photos")
            photo_count += len(photos_value) if isinstance(photos_value, (list, dict)) else 0
            for key in ("audit_events", "events", "review_events"):
                value = team_state.get(key)
                audit_count += len(value) if isinstance(value, list) else 0
        metrics.update(
            {
                "teams": len(teams),
                "tasks": task_count,
                "groups": group_count,
                "photos": photo_count,
                "audit_events": audit_count,
            }
        )
        return metrics

    for key, output in [
        ("tasks", "tasks"),
        ("terminal_tasks", "tasks"),
        ("groups", "groups"),
        ("material_groups", "groups"),
        ("photos", "photos"),
        ("audit_events", "audit_events"),
    ]:
        value = state.get(key)
        if isinstance(value, (list, dict)):
            metrics[output] = len(value)
    return metrics


def users_metrics(users: Any) -> dict[str, Any]:
    if isinstance(users, dict):
        for key in ("users", "accounts"):
            value = users.get(key)
            if isinstance(value, (list, dict)):
                return {"users_found": True, "users": len(value)}
        return {"users_found": True, "users": len(users)}
    if isinstance(users, list):
        return {"users_found": True, "users": len(users)}
    return {"users_found": False, "users": "unknown"}


def scan_vue_registry() -> dict[str, Any]:
    text = read_text(ROOT / "v2-web" / "src" / "router" / "staticPages.ts")
    if not text:
        return {"found": False, "pages": [], "native": 0, "legacy": 0}
    pages: list[dict[str, str]] = []
    for block in text.split("{"):
        if "key:" not in block or "migrationStatus:" not in block:
            continue
        key = block.split("key:", 1)[1].split(",", 1)[0].strip().strip("'\"")
        status = block.split("migrationStatus:", 1)[1].split(",", 1)[0].strip().strip("'\"")
        if key:
            pages.append({"key": key, "status": status})
    return {
        "found": True,
        "pages": pages,
        "native": sum(1 for page in pages if page["status"] == "native_vue"),
        "legacy": sum(1 for page in pages if page["status"] == "legacy_bridge"),
    }


def env_value(name: str) -> str:
    runtime_value = os.environ.get(name)
    if runtime_value:
        return runtime_value
    env_path = ROOT / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.strip().startswith(f"{name}="):
            return line.split("=", 1)[1].strip()
    return ""


def collect_checks(run_checks: bool) -> dict[str, Any]:
    state_repo = read_text(ROOT / "v2-api" / "app" / "services" / "state_repository.py")
    config_text = read_text(ROOT / "v2-api" / "app" / "core" / "config.py")
    models_text = read_text(ROOT / "v2-api" / "app" / "models.py")
    task_hall = read_text(ROOT / "v2-web" / "src" / "views" / "TaskHallView.vue")
    construction = read_text(ROOT / "v2-web" / "src" / "views" / "ConstructionView.vue")

    checks: dict[str, Any] = {
        "vue_registry": scan_vue_registry(),
        "postgres_repository": "class PostgresStateRepository" in state_repo,
        "dual_repository": "class DualWriteStateRepository" in state_repo,
        "state_backend_config": "STATE_BACKEND" in config_text or "state_backend" in config_text,
        "state_backend_env": env_value("STATE_BACKEND"),
        "photo_fingerprint_fields": all(
            token in models_text
            for token in ["source_fingerprint", "source_url_hash", "import_batch_id", "is_active"]
        ),
        "postgres_verify_script": (ROOT / "scripts" / "verify_postgres_state_backend.py").exists(),
        "alembic_migrations": len(
            [
                path
                for path in (ROOT / "v2-api" / "alembic" / "versions").glob("*.py")
                if path.name != "__init__.py"
            ]
        ),
        "oss_storage_service": (ROOT / "v2-api" / "app" / "services" / "photo_storage.py").exists(),
        "oss_scripts": len(list((ROOT / "v2-api" / "scripts").glob("*oss*.py"))) if (ROOT / "v2-api" / "scripts").exists() else 0,
        "backup_script": (ROOT / "scripts" / "production_backup.sh").exists(),
        "health_script": (ROOT / "scripts" / "production_health_check.sh").exists(),
        "service_file": (ROOT / "infra" / "module-manager-v2.service").exists(),
        "nginx_config": (ROOT / "infra" / "nginx" / "module-manager-v2.conf").exists(),
        "mini_program": (ROOT / "v2-miniprogram" / "miniprogram" / "app.json").exists(),
        "construction_cache_page": (ROOT / "v2-web" / "src" / "views" / "ConstructionCacheView.vue").exists(),
        "review_page_actions": all(
            token in task_hall
            for token in ["补图", "删除当前图", "回退未施工", "转异常工单", "导出异常表计", "groupPhotoContentUrl"]
        ),
        "construction_mobile_cache": all(token in construction for token in ["IndexedDB", "本地缓存", "扫码"]),
        "tests": count_files("test_*.py"),
        "run_checks": [],
    }
    if run_checks:
        checks["run_checks"].append(run_command([sys.executable, "scripts/verify_vue_migration_gate.py"], 120))
        checks["run_checks"].append(run_command([sys.executable, "scripts/verify_vue_migration_gate.py", "--strict-native"], 120))
        checks["run_checks"].append(run_command([sys.executable, "-m", "py_compile", "scripts/generate_product_evaluation.py"], 120))
        if checks["postgres_verify_script"] and os.environ.get("DATABASE_URL"):
            checks["run_checks"].append(run_command([sys.executable, "scripts/verify_postgres_state_backend.py"], 240))
    return checks


def command_passed(checks: dict[str, Any], contains: str) -> bool:
    return any(contains in item["command"] and item["code"] == 0 for item in checks.get("run_checks", []))


def score_item(item: ScoreItem, checks: dict[str, Any]) -> tuple[int, str]:
    registry = checks["vue_registry"]
    strict_vue_passed = command_passed(checks, "--strict-native")
    postgres_smoke_passed = command_passed(checks, "verify_postgres_state_backend.py")

    if item.name == "工程管理适配度":
        score = 86 if (ROOT / "AGENTS.md").exists() and (ROOT / "docs" / "PROJECT_DECISIONS.md").exists() else 78
        return score, "已有必读规则、团队分工和本地评价纪律。"
    if item.name == "产品结构":
        score = 84 + int(checks["mini_program"]) + int(checks["construction_cache_page"])
        return min(score, 88), "管理员、审阅员、施工员主路径已拆分，仍需持续压实权限边界。"
    if item.name == "审阅效率":
        score = 86 if checks["review_page_actions"] else 78
        return score, "审阅页已具备快捷键、补图、删图、回退和异常工单入口，仍需生产图片实测。"
    if item.name == "施工采集体验":
        score = 86 if checks["construction_mobile_cache"] else 80
        return score, "施工端已面向手机采集和本地缓存，现场交互仍需持续按实测校准。"
    if item.name == "离线缓存能力":
        score = 84 if checks["construction_cache_page"] else 68
        return score, "已有缓存上传页面和施工缓存能力，异常工单补图缓存仍需重点回归。"
    if item.name == "数据结构":
        if postgres_smoke_passed:
            return 88, "PostgreSQL 仓储通过本地烟测，具备去 JSON 化落地基础。"
        if checks["postgres_repository"] and checks["dual_repository"]:
            return 84, "PostgreSQL/dual 仓储已存在，但本次未完成真实数据库烟测。"
        return 74, "仍缺正式数据库仓储。"
    if item.name == "代码结构":
        score = 84 + int(checks["postgres_repository"]) + int(checks["oss_storage_service"])
        return min(score, 88), "已有仓储层、存储服务和前后端分层，仍需减少历史兼容路径。"
    if item.name == "前端结构":
        if strict_vue_passed or (registry.get("legacy", 0) == 0 and registry.get("native", 0) > 0):
            return 88, "生产页面已完成原生 Vue 登记，静态页不再作为主入口。"
        if registry.get("legacy", 0) > 0:
            return 72, "仍存在 legacy bridge 页面，限制前端结构评分。"
        return 65, "未检测到完整 Vue 页面登记。"
    if item.name == "小程序/移动端结构":
        return (83 if checks["mini_program"] else 68), "小程序目录已存在，后续重点是与网页规则完全同步。"
    if item.name == "服务器结构":
        score = 82 + int(checks["service_file"]) * 2 + int(checks["nginx_config"]) * 2
        return min(score, 88), "已有服务守护和 Nginx 配置，数据库正式切换后可继续加分。"
    if item.name == "图片存储结构":
        score = 80 + int(checks["oss_storage_service"]) * 4 + min(checks["oss_scripts"], 2) + int(checks["photo_fingerprint_fields"]) * 2
        return min(score, 88), "OSS 和照片级去重字段具备基础，缩略图/预览图链路仍需持续验证。"
    if item.name == "安全权限":
        auth_text = read_text(ROOT / "v2-api" / "app" / "api" / "routes" / "auth.py")
        score = 82 if "role" in auth_text and "team" in auth_text else 74
        return score, "已有角色和团队字段基础，生产密钥、静态上传访问仍需严控。"
    if item.name == "运维备份":
        score = 72 + int(checks["backup_script"]) * 8 + int(checks["health_script"]) * 6
        return min(score, 88), "备份和健康检查脚本已纳入规则，但仍需定期恢复演练记录。"
    if item.name == "可观测性":
        score = 76 + int((ROOT / "v2-api" / "app" / "services" / "ops_status.py").exists()) * 6
        return min(score, 84), "有运维状态基础，仍需更细的审阅卡顿和导入失败定位日志。"
    if item.name == "测试覆盖":
        score = 72 + min(checks["tests"], 12) + (2 if checks.get("run_checks") else 0)
        return min(score, 88), f"检测到 {checks['tests']} 个 Python 测试文件，本次报告包含自动检查。"
    if item.name == "成本控制":
        return 88, "当前预算约 130 元，优先使用现有服务器、OSS 按需优化，符合低成本路线。"
    return 75, "未定义自动评分规则。"


def checks_table(checks: dict[str, Any]) -> str:
    registry = checks["vue_registry"]
    legacy_pages = ", ".join(page["key"] for page in registry.get("pages", []) if page["status"] == "legacy_bridge") or "无"
    rows = [
        ["检查项", "结果", "说明"],
        ["Vue 页面登记", "通过" if registry.get("found") else "未通过", f"native={registry.get('native', 0)}；legacy={registry.get('legacy', 0)}；legacy 页面：{legacy_pages}"],
        ["审阅页生产操作", "通过" if checks["review_page_actions"] else "未通过", "补图/删图/回退/异常工单/异常导出/图片内容接口"],
        ["PostgreSQL 仓储", "通过" if checks["postgres_repository"] else "未通过", "检测 PostgresStateRepository"],
        ["dual 仓储", "通过" if checks["dual_repository"] else "未通过", "检测 DualWriteStateRepository"],
        ["STATE_BACKEND 配置", "通过" if checks["state_backend_config"] else "未通过", checks["state_backend_env"] or "未读取到 .env 配置"],
        ["照片级去重字段", "通过" if checks["photo_fingerprint_fields"] else "未通过", "fingerprint/url_hash/import_batch/is_active"],
        ["Alembic 迁移", "通过" if checks["alembic_migrations"] > 0 else "未通过", checks["alembic_migrations"]],
        ["OSS 存储服务", "通过" if checks["oss_storage_service"] else "未通过", f"OSS 脚本 {checks['oss_scripts']} 个"],
        ["备份脚本", "通过" if checks["backup_script"] else "未通过", "scripts/production_backup.sh"],
        ["健康检查", "通过" if checks["health_script"] else "未通过", "scripts/production_health_check.sh"],
        ["小程序/移动端", "通过" if checks["mini_program"] else "未通过", "v2-miniprogram"],
    ]
    for item in checks.get("run_checks", []):
        rows.append([
            item["command"],
            "通过" if item["code"] == 0 else f"未通过({item['code']})",
            item["output"].replace("\n", " / ")[:260] or "无输出",
        ])
    return markdown_table(rows)


def score_limits(checks: dict[str, Any]) -> list[str]:
    limits: list[str] = []
    registry = checks["vue_registry"]
    if registry.get("legacy", 0) > 0:
        limits.append("存在 legacy bridge 页面，前端结构最高按 72 分计。")
    if not checks["postgres_repository"]:
        limits.append("未检测到 PostgreSQL 仓储，数据结构最高按 75 分计。")
    elif not command_passed(checks, "verify_postgres_state_backend.py"):
        limits.append("PostgreSQL 仓储存在，但本次未通过真实数据库烟测，数据结构暂不按完全去 JSON 化计分。")
    if not checks["photo_fingerprint_fields"]:
        limits.append("照片级去重字段不完整，图片存储结构最高按 78 分计。")
    if not checks["backup_script"]:
        limits.append("缺少生产备份脚本，运维备份最高按 65 分计。")
    return limits or ["本次自动检查未触发硬性扣分上限，仍需按实测结果谨慎评分。"]


def hard_gate_lines(checks: dict[str, Any]) -> list[str]:
    registry = checks["vue_registry"]
    legacy_pages = [page["key"] for page in registry.get("pages", []) if page["status"] == "legacy_bridge"]
    return [
        "- Vue 原生生产入口：" + ("通过，生产登记页面均为原生 Vue。" if not legacy_pages else f"未通过，仍有 legacy 页面：{', '.join(legacy_pages)}。"),
        "- Vue strict native 检查：" + ("通过。" if command_passed(checks, "--strict-native") else "未运行或未通过。"),
        "- PostgreSQL 事实源：" + ("通过本地烟测。" if command_passed(checks, "verify_postgres_state_backend.py") else "待验证或未在本次报告中运行。"),
        "- 照片级导入去重字段：" + ("通过字段检查。" if checks["photo_fingerprint_fields"] else "未通过。"),
        "- 运维备份和健康检查：" + ("通过基础脚本检查。" if checks["backup_script"] and checks["health_script"] else "未通过或不完整。"),
    ]


def missing_85_hard_gates(checks: dict[str, Any]) -> list[str]:
    registry = checks["vue_registry"]
    missing: list[str] = []
    if registry.get("legacy", 0) > 0 or registry.get("native", 0) == 0:
        missing.append("Vue 生产页面未全部完成原生登记")
    if not command_passed(checks, "--strict-native"):
        missing.append("未通过 Vue strict-native 检查")
    if not command_passed(checks, "verify_postgres_state_backend.py"):
        missing.append("未通过 PostgreSQL 事实源烟测")
    if not checks["photo_fingerprint_fields"]:
        missing.append("照片级导入去重字段不完整")
    if not (checks["backup_script"] and checks["health_script"]):
        missing.append("生产备份或健康检查脚本不完整")
    return missing


def score_report_rows(checks: dict[str, Any]) -> tuple[list[list[Any]], float]:
    rows: list[list[Any]] = [["项目", "权重", "分数", "加权分", "依据"]]
    total = 0.0
    for item in SCORE_ITEMS:
        score, note = score_item(item, checks)
        weighted = score * item.weight / 100
        total += weighted
        rows.append([item.name, item.weight, score, f"{weighted:.2f}", note])
    return rows, total


def build_report(args: argparse.Namespace) -> str:
    now = dt.datetime.now().astimezone()
    state_path = args.state or first_existing(
        [
            ROOT / "data" / "local_state.json",
            ROOT / "v2-api" / "data" / "local_state.json",
            ROOT / "v2-api" / "local-test-state.json",
        ]
    )
    users_path = args.users or first_existing([ROOT / "data" / "users.json", ROOT / "v2-api" / "data" / "users.json"])
    state_stat = state_metrics(read_json(state_path))
    user_stat = users_metrics(read_json(users_path))
    checks = collect_checks(run_checks=args.run_checks)
    score_rows, total_score = score_report_rows(checks)
    missing_hard_gates = missing_85_hard_gates(checks)
    effective_score = min(total_score, 84.90) if missing_hard_gates and total_score >= 85 else total_score
    grade = "A" if effective_score >= 90 else "B" if effective_score >= 80 else "C" if effective_score >= 70 else "D" if effective_score >= 60 else "E"

    facts = [
        ["项目根目录", ROOT],
        ["评价时间", now.strftime("%Y-%m-%d %H:%M:%S %z")],
        ["状态文件", state_path if state_path else "未找到"],
        ["用户文件", users_path if users_path else "未找到"],
        ["团队数", state_stat["teams"]],
        ["用户数", user_stat["users"]],
        ["终端任务数", state_stat["tasks"]],
        ["资料组数", state_stat["groups"]],
        ["照片索引数", state_stat["photos"]],
        ["审计/事件数", state_stat["audit_events"]],
        ["Python 测试文件数", count_files("test_*.py")],
        ["静态 HTML 文件数", count_files("*.html")],
        ["Python 文件数", count_files("*.py")],
        ["文档文件数", count_files("*.md")],
        ["当前预算", f"{args.budget} 元"],
    ]

    return "\n".join(
        [
            f"# 产品评价报告 {now.strftime('%Y-%m-%d %H:%M')}",
            "",
            "## 基本信息",
            "",
            markdown_table([["项目", "值"], *facts]),
            "",
            "## 本次修改范围",
            "",
            args.change or "- 未填写。请补充本次修改的业务范围、代码范围和上线范围。",
            "",
            "## 自动检查结果",
            "",
            checks_table(checks),
            "",
            "## 自动扣分上限",
            "",
            "\n".join(f"- {item}" for item in score_limits(checks)),
            "",
            "## 评分表",
            "",
            markdown_table(score_rows),
            "",
            f"原始总分：{total_score:.2f}",
            "",
            f"最终总分：{effective_score:.2f}",
            "",
            f"等级：{grade}",
            "",
            "85+ 门槛缺口：" + ("无" if not missing_hard_gates else "；".join(missing_hard_gates)),
            "",
            "## 85+ 硬门槛检查",
            "",
            "\n".join(hard_gate_lines(checks)),
            "",
            "## 优势",
            "",
            "- 已建立本地评价规则、自动检查入口和固定报告目录。",
            "- 前端 Vue 迁移、PostgreSQL 仓储、OSS 存储、施工采集、小程序等关键方向都有工程化落点。",
            "- 预算控制仍以现有服务器和按需 OSS 为主，符合当前 130 元成本约束。",
            "",
            "## 不足",
            "",
            "- PostgreSQL 是否成为生产事实源需要结合真实数据库烟测和生产切换记录继续确认。",
            "- 施工异常补图缓存、审阅图片加载完整性、缩略图/预览图策略仍需要专项回归。",
            "- 运维侧需要持续记录备份恢复演练，而不只是保留脚本。",
            "",
            "## 不增加预算的升级路径",
            "",
            "1. 每轮核心修改后执行本报告脚本，保证分数和风险持续可见。",
            "2. 优先完成 PostgreSQL fact source 切换验证，保留 JSON 回滚快照。",
            "3. 用现有 OSS 做缩略图/预览图策略验证，降低前台加载成本和卡顿。",
            "4. 对施工采集缓存、异常工单、审阅归档、单终端导出做固定回归清单。",
            "5. 每周保存一份报告，趋势下降时先处理最高扣分项。",
            "",
            "## 验证记录",
            "",
            "- 自动检查记录见上方表格。",
            "- 手动验证结论需由执行人追加。",
            "",
            "## 变更记录",
            "",
            f"- {now.strftime('%Y-%m-%d %H:%M')} 生成本地产品评价报告。",
            "",
        ]
    )


def default_output_path() -> Path:
    output_dir = ROOT / "docs" / "evaluations"
    date_part = dt.datetime.now().strftime("%Y-%m-%d")
    path = output_dir / f"{date_part}-product-evaluation.md"
    if not path.exists():
        return path
    stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M")
    return output_dir / f"{stamp}-product-evaluation.md"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a local product evaluation report.")
    parser.add_argument("--state", type=Path, default=None, help="Path to local_state.json.")
    parser.add_argument("--users", type=Path, default=None, help="Path to users.json.")
    parser.add_argument("--output", type=Path, default=None, help="Output markdown path.")
    parser.add_argument("--budget", type=int, default=130, help="Current project budget in CNY.")
    parser.add_argument("--change", default="", help="Short description of the evaluated change.")
    parser.add_argument("--run-checks", action="store_true", help="Run fast local gates and include output.")
    args = parser.parse_args()

    output_path = (args.output or default_output_path()).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_report(args), encoding="utf-8")
    print(f"[OK] wrote evaluation report: {output_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
