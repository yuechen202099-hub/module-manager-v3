from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence


RETIREMENT_MESSAGE = "导出中心已下线，请联系管理员由 OSS 导出到本机。"
RETIREMENT_BLOCK = f"""
    location = /exports {{
        default_type application/json;
        return 410 '{{"detail":"{RETIREMENT_MESSAGE}"}}';
    }}
    location ^~ /exports/ {{
        default_type application/json;
        return 410 '{{"detail":"{RETIREMENT_MESSAGE}"}}';
    }}
    location = /local-test/export-manifest/final-delivery {{
        default_type application/json;
        return 410 '{{"detail":"{RETIREMENT_MESSAGE}"}}';
    }}
    location = /local-test/unmatched/export {{
        default_type application/json;
        return 410 '{{"detail":"{RETIREMENT_MESSAGE}"}}';
    }}
    location = /local-test/photo-barcode/review-groups/export {{
        default_type application/json;
        return 410 '{{"detail":"{RETIREMENT_MESSAGE}"}}';
    }}
"""


def patch_nginx_config(source: str) -> str:
    marker = "    location / {"
    retirement_route_markers = (
        "location = /exports {",
        "location ^~ /exports/ {",
        "location = /local-test/export-manifest/final-delivery {",
        "location = /local-test/unmatched/export {",
        "location = /local-test/photo-barcode/review-groups/export {",
    )
    retirement_route_counts = tuple(
        source.count(route_marker) for route_marker in retirement_route_markers
    )
    complete_block_count = source.count(RETIREMENT_BLOCK.strip())
    if complete_block_count == 2 and all(
        route_count == 2 for route_count in retirement_route_counts
    ):
        return source
    if complete_block_count or any(retirement_route_counts):
        raise ValueError("partial export retirement block detected")
    if source.count(marker) != 2:
        raise ValueError("expected exactly two production location / markers")
    return source.replace(marker, RETIREMENT_BLOCK + "\n" + marker)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create an Nginx config candidate with export routes retired."
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    config_path = args.config.resolve()
    output_path = args.output.resolve()
    if config_path == output_path:
        parser.error("--config and --output must differ; in-place writes are forbidden")

    with config_path.open("r", encoding="utf-8", newline="") as source_file:
        source = source_file.read()
    patched = patch_nginx_config(source)
    with output_path.open("w", encoding="utf-8", newline="") as output_file:
        output_file.write(patched)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
