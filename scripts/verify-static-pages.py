from __future__ import annotations

import argparse
import html
import os
import re
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = ROOT / "v2-api" / "app" / "static"

STATIC_PAGES = {
    "login.html": ["模块更换项目管理器", "登录系统"],
    "app_shell.html": ["模块更换项目管理器", "项目看板", "任务领取", "审阅工作台"],
    "project_board.html": ["项目看板", "项目进度总览", "导入总清单", "导入扫码表格", "安装人员资料组占比", "导出异常表计"],
    "task_hall.html": ["任务审阅工作台", "审阅工作台", "快捷键分类"],
    "claim_tasks.html": ["任务领取", "可领取终端"],
    "sync_config.html": ["同步方案已停用", "表格导入", "供应商 API 不可用"],
}

NAV_TEXT = ["项目看板", "任务领取", "审阅工作台"]
UNICODE_ESCAPE_RE = re.compile(r"\\u([0-9a-fA-F]{4})")
MOJIBAKE_FRAGMENTS = [
    "\u599e\u3085\u6e71\u5a32\u4f34\u60c7\u7023\ue0a3\u7df2",
    "椤圭洰",
    "鐪嬫澘",
    "浠诲姟",
    "寮傚父",
    "琛ュ浘",
    "鏂板缓",
    "瀹￠槄",
    "绠＄悊",
    "鐧诲綍",
    "鍚屾",
    "锟",
    "\ufffd",
]


class InlineScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_script = False
        self.current: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "script" and not any(name.lower() == "src" for name, _ in attrs):
            self.in_script = True
            self.current = []

    def handle_data(self, data: str) -> None:
        if self.in_script:
            self.current.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self.in_script:
            script = "".join(self.current).strip()
            if script:
                self.scripts.append(script)
            self.in_script = False


def fail(message: str) -> None:
    raise AssertionError(message)


def resolve_node(explicit: str | None = None) -> Path | None:
    candidates = [
        explicit,
        os.environ.get("NODE_EXE"),
        r"C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe",
        "node",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file():
            return path
        if candidate == "node":
            return path
    return None


def extract_inline_scripts(source: str) -> list[str]:
    parser = InlineScriptParser()
    parser.feed(source)
    return parser.scripts


def decode_js_unicode_escapes(source: str) -> str:
    return UNICODE_ESCAPE_RE.sub(lambda match: chr(int(match.group(1), 16)), source)


def check_script_syntax(node: Path | None, page_name: str, scripts: list[str]) -> None:
    if not scripts:
        return
    if not node:
        fail("Node runtime not found for static page script syntax checks")
    with tempfile.TemporaryDirectory(prefix="module-manager-static-") as tmp:
        tmp_path = Path(tmp)
        for index, script in enumerate(scripts, start=1):
            script_path = tmp_path / f"{page_name}.{index}.js"
            script_path.write_text(script, encoding="utf-8")
            result = subprocess.run(
                [str(node), "--check", str(script_path)],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if result.returncode != 0:
                fail(f"{page_name} inline script #{index} has syntax error:\n{result.stderr or result.stdout}")


def verify_page(page_name: str, required_text: list[str], node: Path | None) -> None:
    page_path = STATIC_ROOT / page_name
    if not page_path.exists():
        fail(f"Missing static page: {page_path}")
    source = page_path.read_text(encoding="utf-8")
    rendered = decode_js_unicode_escapes(html.unescape(source))
    for text in required_text:
        if text not in rendered:
            fail(f"{page_name} missing required text: {text}")
    if page_name in {"project_board.html", "task_hall.html", "claim_tasks.html", "sync_config.html"}:
        for text in NAV_TEXT:
            if text not in rendered:
                fail(f"{page_name} missing fixed navigation text: {text}")
        if "--topbar-height: 64px" not in source:
            fail(f"{page_name} must use the shared 64px topbar height token")
        if "--page-nav-width: 440px" not in source:
            fail(f"{page_name} must use the shared 440px page navigation width token")
        if "grid-template-rows: 58px minmax(0, 1fr)" in source or "height: calc(100vh - 62px)" in source:
            fail(f"{page_name} still contains a legacy topbar height")
    if page_name in {"project_board.html", "task_hall.html", "claim_tasks.html"}:
        if "height: 48px" not in source and "height: var(--panel-head-height)" not in source:
            fail(f"{page_name} must use the shared 48px panel header height")
    if page_name in {"project_board.html", "claim_tasks.html"}:
        if "min-height: 84px" not in source and "--metric-card-height: 84px" not in source:
            fail(f"{page_name} must use the shared 84px metric card height")
    for fragment in MOJIBAKE_FRAGMENTS:
        if fragment in rendered:
            fail(f"{page_name} contains mojibake fragment: {fragment}")
    if page_name == "project_board.html":
        if 'id="photoUrls"' in source or "upload-images" in source or "manual-tools" in source:
            fail("project_board.html must not expose manual supplemental photo tools")
    if page_name == "login.html":
        if "admin / admin123" in source or "reviewer / review123" in source or 'value="admin123"' in source:
            fail("login.html must not hardcode demo credentials")
        if "/auth/config" not in source or "loadLoginConfig" not in source:
            fail("login.html must load auth display configuration dynamically")
    if page_name == "sync_config.html" and 'id="payload"' in source:
        fail("sync_config.html must not expose the discontinued token/request JSON input")
    check_script_syntax(node, page_name, extract_inline_scripts(source))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify static demo HTML pages and inline script syntax.")
    parser.add_argument("--node", type=str, default=None, help="Explicit Node.js executable path.")
    args = parser.parse_args()
    node = resolve_node(args.node)
    for page_name, required_text in STATIC_PAGES.items():
        verify_page(page_name, required_text, node)
        print(f"[OK] {page_name}")
    print("[OK] static page text, navigation, mojibake, and inline scripts verified")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)
