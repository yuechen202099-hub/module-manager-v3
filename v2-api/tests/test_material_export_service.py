from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.material_export import MaterialExportMeter
from app.services.material_export import (
    MaterialExportAllocationResult,
    MaterialExportBusy,
    MaterialExportCompletedCannotRelease,
    MaterialExportFileMismatch,
    MaterialExportLeaseMismatch,
    MaterialExportPoolShortage,
    MaterialExportProjectMismatch,
    ProjectExportEvidence,
    build_preflight,
)


def meter(
    *,
    group: str,
    task: str,
    terminal: str,
    meter_no: str,
    module_no: str,
    collector_no: str = "C-1",
    constructed: bool = True,
    module_photo: str | None = "photo-module",
    after_photo: str | None = "photo-after",
    anomalies: tuple[str, ...] = (),
) -> MaterialExportMeter:
    return MaterialExportMeter(
        group_id=group,
        task_id=task,
        terminal_code=terminal,
        meter_no=meter_no,
        module_no=module_no,
        collector_no=collector_no,
        installation_address="总清单地址",
        module_meter_photo_id=module_photo,
        after_box_photo_id=after_photo,
        constructed=constructed,
        open_module_anomalies=anomalies,
    )


def test_build_preflight_uses_all_project_rows_but_exports_only_constructed_selected_rows() -> None:
    project_id = uuid4()
    task_a_id, task_b_id = uuid4(), uuid4()
    task_a = SimpleNamespace(id=task_a_id, project_id=project_id, terminal="T-1")
    task_b = SimpleNamespace(id=task_b_id, project_id=project_id, terminal="T-2")
    rows = (
        meter(group="g-a1", task=str(task_a_id), terminal="T-1", meter_no="M-1", module_no="MOD-1"),
        meter(
            group="unconstructed-group",
            task=str(task_a_id),
            terminal="T-1",
            meter_no="M-X",
            module_no="MOD-2",
            constructed=False,
        ),
        meter(group="g-a2", task=str(task_a_id), terminal="T-1", meter_no="M-2", module_no="MOD-2"),
        meter(group="g-b1", task=str(task_b_id), terminal="T-2", meter_no="M-3", module_no="MOD-1"),
        meter(group="g-b2", task=str(task_b_id), terminal="T-2", meter_no="M-2", module_no="MOD-3"),
    )
    evidence = ProjectExportEvidence(meters=rows, group_payloads={}, photo_storage_rows={})
    settings = {
        str(task_a_id): SimpleNamespace(requested_collector_count=4),
        str(task_b_id): SimpleNamespace(requested_collector_count=0),
    }

    preflight = build_preflight(tasks=(task_a, task_b), evidence=evidence, settings=settings)

    terminal_a = preflight.terminals[str(task_a_id)]
    assert terminal_a.constructed_meter_count == 2
    assert terminal_a.final_collector_count == 4
    assert "unconstructed-group" not in preflight.source_group_ids
    assert {issue.code for issue in terminal_a.issues} >= {
        "duplicate_module",
        "meter_multiple_modules",
    }
    assert all(
        issue.code != "missing_collector_photo"
        for terminal in preflight.terminals.values()
        for issue in terminal.issues
    )
    assert preflight.terminals[str(task_b_id)].can_export is False


def test_preflight_ignores_duplicate_photo_projection_of_one_group() -> None:
    project_id, task_id = uuid4(), uuid4()
    task = SimpleNamespace(id=task_id, project_id=project_id, terminal="T-1")
    row = meter(group="g-1", task=str(task_id), terminal="T-1", meter_no="M-1", module_no="MOD-1")
    evidence = ProjectExportEvidence(meters=(row, row), group_payloads={}, photo_storage_rows={})
    preflight = build_preflight(tasks=(task,), evidence=evidence, settings={})
    assert preflight.terminals[str(task_id)].can_export is True
    assert preflight.terminals[str(task_id)].constructed_meter_count == 1


def test_preflight_blocks_open_module_anomaly_but_not_collector_photo_absence() -> None:
    project_id, task_id = uuid4(), uuid4()
    task = SimpleNamespace(id=task_id, project_id=project_id, terminal="T-1")
    row = meter(
        group="g-1",
        task=str(task_id),
        terminal="T-1",
        meter_no="M-1",
        module_no="MOD-1",
        anomalies=("模块号需人工确认",),
    )
    preflight = build_preflight(
        tasks=(task,),
        evidence=ProjectExportEvidence(meters=(row,), group_payloads={}, photo_storage_rows={}),
        settings={},
    )
    assert {issue.code for issue in preflight.terminals[str(task_id)].issues} == {
        "open_module_anomaly"
    }


def test_preflight_rejects_cross_project_task_selection() -> None:
    tasks = (
        SimpleNamespace(id=uuid4(), project_id=uuid4(), terminal="T-1"),
        SimpleNamespace(id=uuid4(), project_id=uuid4(), terminal="T-2"),
    )
    with pytest.raises(MaterialExportProjectMismatch, match="同一项目"):
        build_preflight(
            tasks=tasks,
            evidence=ProjectExportEvidence(meters=(), group_payloads={}, photo_storage_rows={}),
            settings={},
        )


def test_pool_shortage_keeps_batch_and_terminal_diagnostics() -> None:
    error = MaterialExportPoolShortage(
        "采集器池库存不足，本批次未开始分配",
        total_shortage=2,
        terminal_shortages={"task-a": 1, "task-b": 1},
    )
    assert error.code == "pool_shortage"
    assert error.total_shortage == 2
    assert error.terminal_shortages == {"task-a": 1, "task-b": 1}


def test_allocation_result_distinguishes_replacement_and_extra() -> None:
    replacement = MaterialExportAllocationResult(
        allocation_id="a-1",
        physical_collector_id="p-1",
        original_collector_no="C-OLD",
        final_collector_no="C-NEW",
        allocation_mode="pool_replacement",
        is_extra=False,
    )
    extra = MaterialExportAllocationResult(
        allocation_id="a-2",
        physical_collector_id="p-2",
        original_collector_no=None,
        final_collector_no="C-EXTRA",
        allocation_mode="extra_pool",
        is_extra=True,
    )
    assert replacement.is_extra is False
    assert extra.is_extra is True
    assert MaterialExportCompletedCannotRelease.code == "completed_cannot_release"


def test_resumable_export_errors_have_stable_contract_codes() -> None:
    assert MaterialExportBusy.code == "export_busy"
    assert MaterialExportLeaseMismatch.code == "lease_mismatch"
    assert MaterialExportFileMismatch.code == "file_mismatch"
