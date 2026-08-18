from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.patch_export_retirement_nginx import RETIREMENT_BLOCK, patch_nginx_config


BASE = """
server {
    listen 80;
    location / {
        proxy_pass http://127.0.0.1:8000;
    }
}
server {
    listen 443 ssl;
    location / {
        proxy_pass http://127.0.0.1:8000;
    }
}
"""


def test_patch_inserts_block_in_both_production_servers() -> None:
    patched = patch_nginx_config(BASE)
    assert patched.count("location = /exports") == 2
    assert patched.count("location ^~ /exports/") == 2
    assert patched.count("proxy_pass http://127.0.0.1:8000;") == 2
    assert patched.count(RETIREMENT_BLOCK.strip()) == 2


def test_patch_is_idempotent() -> None:
    once = patch_nginx_config(BASE)
    assert patch_nginx_config(once) == once


def test_patch_rejects_partial_retirement_state() -> None:
    partial_block = """
    location = /exports {
        default_type application/json;
        return 410 '{"detail":"partial"}';
    }
"""
    partial = BASE.replace(
        "    location / {", partial_block + "\n" + "    location / {"
    )

    with pytest.raises(ValueError, match="partial export retirement block"):
        patch_nginx_config(partial)


def test_similarly_prefixed_locations_do_not_bypass_patching() -> None:
    unrelated_block = """
    location = /exports-archive {
        return 404;
    }
"""
    source = BASE.replace(
        "    location / {", unrelated_block + "\n" + "    location / {"
    )

    patched = patch_nginx_config(source)

    assert patched.count(RETIREMENT_BLOCK.strip()) == 2
    assert patched.count("location = /exports-archive") == 2


def test_patch_rejects_unexpected_server_shape() -> None:
    with pytest.raises(ValueError, match="exactly two"):
        patch_nginx_config(BASE.split("server {", 2)[1])


def test_cli_writes_utf8_output_without_modifying_source(tmp_path: Path) -> None:
    source_path = tmp_path / "nginx.conf"
    output_path = tmp_path / "nginx.conf.patched"
    source_path.write_text(BASE, encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            "scripts/patch_export_retirement_nginx.py",
            "--config",
            str(source_path),
            "--output",
            str(output_path),
        ],
        check=True,
    )

    assert source_path.read_text(encoding="utf-8") == BASE
    assert output_path.read_text(encoding="utf-8") == patch_nginx_config(BASE)


def test_cli_refuses_to_write_in_place(tmp_path: Path) -> None:
    source_path = tmp_path / "nginx.conf"
    source_path.write_text(BASE, encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/patch_export_retirement_nginx.py",
            "--config",
            str(source_path),
            "--output",
            str(source_path),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "must differ" in result.stderr
    assert source_path.read_text(encoding="utf-8") == BASE
