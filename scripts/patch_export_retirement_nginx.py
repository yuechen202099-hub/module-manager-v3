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
    if source.count("location = /exports") == 2:
        return source
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
