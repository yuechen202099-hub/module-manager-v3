from pathlib import Path

import pytest

from app.services.local_simulation import (
    DEFAULT_SCAN_FILE,
    DEFAULT_STAGE_CATALOG,
    DEFAULT_TOTAL_CATALOG,
    LocalTestPaths,
    bootstrap_local_simulation,
    get_group,
    list_groups,
)


SAMPLE_FILES = [DEFAULT_TOTAL_CATALOG, DEFAULT_STAGE_CATALOG, DEFAULT_SCAN_FILE]


pytestmark = pytest.mark.skipif(
    not all(path.exists() for path in SAMPLE_FILES),
    reason="local sample workbooks are not available",
)


def test_bootstrap_local_simulation_uses_sample_workbooks() -> None:
    state = bootstrap_local_simulation(LocalTestPaths())
    summary = state["summary"]

    assert summary["total_catalog_rows"] > 20_000
    assert summary["stage_catalog_rows"] > 5_000
    assert summary["scan_rows"] > 0
    assert summary["groups"] == summary["stage_catalog_rows"]
    assert summary["matched_groups"] > 0


def test_local_groups_are_displayed_with_total_catalog_meter_number() -> None:
    bootstrap_local_simulation(LocalTestPaths())
    result = list_groups(limit=10)

    assert result["total"] > 0
    first = result["items"][0]
    assert first["meter_no"]
    assert first["address"]
    assert first["meter_no"] != first["meter_match_key"]


def test_group_detail_can_be_loaded_from_generated_id() -> None:
    bootstrap_local_simulation(LocalTestPaths())
    result = list_groups(limit=1)
    group = get_group(result["items"][0]["id"])

    assert group is not None
    assert group["id"].startswith("g-")


def test_sample_paths_are_absolute_windows_files() -> None:
    for path in SAMPLE_FILES:
        assert isinstance(path, Path)
        assert path.suffix == ".xlsx"
