from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

ROUTE_FILES = [
    ROOT / "v2-api" / "app" / "api" / "routes" / "local_test.py",
    ROOT / "v2-api" / "app" / "api" / "routes" / "exports.py",
]

# These calls may remain because they do not make local_state.json the
# production fact source. Everything else must move behind repositories or
# dedicated PostgreSQL services before strict cutover.
ALLOWED_LOCAL_SIMULATION_CALLS = {
    # Team context compatibility.
    "current_team_id",
    "reset_current_team",
    "set_current_team",
    # Import parsing utilities or explicit JSON/dual rollback adapters. In
    # STATE_BACKEND=postgres, route code must reach PostgreSQL import paths;
    # these are kept only for compatibility and shared row normalization.
    "build_photo_record",
    "expand_detail_pages_for_rows",
    "import_scan_template_xlsx",
    "import_total_catalog_xlsx",
    "import_url_scan_rows",
    "normalize_url_import_row",
    "read_catalog_xlsx_rows",
    "read_scan_template_xlsx_rows",
    "scan_record_to_photo_rows",
}


class LocalSimulationUsageVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.imported_names: set[str] = set()
        self.module_aliases: set[str] = set()
        self.calls: list[tuple[int, str]] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "app.services.local_simulation":
                self.module_aliases.add(alias.asname or "local_simulation")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "app.services.local_simulation":
            for alias in node.names:
                self.imported_names.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        call_name = self._call_name(node.func)
        if call_name:
            self.calls.append((node.lineno, call_name))
        self.generic_visit(node)

    def _call_name(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name) and node.id in self.imported_names:
            return node.id
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in self.module_aliases
        ):
            return f"{node.value.id}.{node.attr}"
        return None


def inspect_file(path: Path) -> list[str]:
    if not path.exists():
        raise AssertionError(f"Missing route file: {path.relative_to(ROOT)}")
    visitor = LocalSimulationUsageVisitor()
    visitor.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
    findings: list[str] = []
    for lineno, call_name in visitor.calls:
        normalized = call_name.split(".", 1)[-1]
        if normalized in ALLOWED_LOCAL_SIMULATION_CALLS:
            continue
        findings.append(f"{path.relative_to(ROOT)}:{lineno} uses local_simulation.{normalized}()")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit production API routes for direct local_simulation business-state calls."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when any production API route still bypasses the PostgreSQL repository.",
    )
    args = parser.parse_args()

    findings: list[str] = []
    for route_file in ROUTE_FILES:
        findings.extend(inspect_file(route_file))

    if findings:
        print("[WARN] API routes still bypass the PostgreSQL repository:")
        for item in findings:
            print(f"  - {item}")
        print(f"[INFO] direct business local_simulation calls: {len(findings)}")
        if args.strict:
            print("[FAIL] PostgreSQL cutover is not complete.", file=sys.stderr)
            return 1
    else:
        print("[OK] API routes no longer call local_simulation business-state functions directly.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
