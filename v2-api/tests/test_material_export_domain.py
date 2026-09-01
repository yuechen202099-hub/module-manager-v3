from __future__ import annotations

from dataclasses import replace

from app.domain.material_export import (
    MaterialExportMeter,
    collector_demand,
    preflight_fingerprint,
    project_module_issues,
    required_meter_issues,
    safe_windows_component,
)


def export_meter(
    *,
    group_id: str = "g-1",
    task_id: str = "task-1",
    terminal: str = "T-1",
    meter_no: str = "M-1",
    module_no: str = "MOD-1",
    collector_no: str = "C-1",
    address: str = "聚丰园路95弄21号",
    module_meter_photo_id: str | None = "p-module",
    after_box_photo_id: str | None = "p-after",
    constructed: bool = True,
) -> MaterialExportMeter:
    return MaterialExportMeter(
        group_id=group_id,
        task_id=task_id,
        terminal_code=terminal,
        meter_no=meter_no,
        module_no=module_no,
        collector_no=collector_no,
        installation_address=address,
        module_meter_photo_id=module_meter_photo_id,
        after_box_photo_id=after_box_photo_id,
        constructed=constructed,
    )


def test_unconstructed_rows_do_not_participate_in_module_conflicts() -> None:
    meters = (
        export_meter(group_id="g-1", terminal="T-1", meter_no="M-1", module_no="MOD-1"),
        export_meter(
            group_id="g-2",
            terminal="T-2",
            meter_no="M-2",
            module_no="MOD-1",
            constructed=False,
        ),
    )
    assert project_module_issues(meters) == ()


def test_duplicate_module_blocks_every_constructed_terminal() -> None:
    meters = (
        export_meter(group_id="g-1", terminal="T-1", meter_no="M-1", module_no="MOD-1"),
        export_meter(group_id="g-2", terminal="T-2", meter_no="M-2", module_no="MOD-1"),
    )
    issues = project_module_issues(meters)
    assert {issue.terminal_code for issue in issues} == {"T-1", "T-2"}
    assert all(issue.code == "duplicate_module" for issue in issues)
    assert all("MOD-1" in issue.message for issue in issues)


def test_two_photo_slots_in_one_group_do_not_create_duplicate_module() -> None:
    meter = export_meter(group_id="g-1", module_no="MOD-1")
    assert project_module_issues((meter, replace(meter))) == ()


def test_one_meter_many_modules_blocks_all_related_terminals() -> None:
    meters = (
        export_meter(group_id="g-1", terminal="T-1", meter_no="M-1", module_no="MOD-1"),
        export_meter(group_id="g-2", terminal="T-2", meter_no="M-1", module_no="MOD-2"),
    )
    issues = project_module_issues(meters)
    assert {issue.terminal_code for issue in issues} == {"T-1", "T-2"}
    assert {issue.code for issue in issues} == {"meter_multiple_modules"}
    assert all("MOD-1、MOD-2" in issue.message for issue in issues)


def test_integrity_matching_uses_nfkc_and_trimmed_identifiers() -> None:
    meters = (
        export_meter(group_id="g-1", terminal="T-1", module_no="ＭＯＤ-1"),
        export_meter(group_id="g-2", terminal="T-2", module_no=" MOD-1 "),
    )
    assert {issue.terminal_code for issue in project_module_issues(meters)} == {"T-1", "T-2"}


def test_collector_demand_uses_max_and_deduplicates_constructed_numbers() -> None:
    meters = (
        export_meter(group_id="g-1", collector_no="C-1"),
        export_meter(group_id="g-2", collector_no=" C-1 "),
        export_meter(group_id="g-3", collector_no="C-2"),
        export_meter(group_id="g-4", collector_no="C-9", constructed=False),
    )
    demand = collector_demand(meters, requested_count=4)
    assert demand.source_collector_nos == ("C-1", "C-2")
    assert demand.final_count == 4
    assert demand.extra_count == 2


def test_collector_photo_is_not_a_required_meter_field() -> None:
    assert required_meter_issues(export_meter()) == ()


def test_required_meter_fields_only_apply_to_constructed_rows() -> None:
    blank = export_meter(
        meter_no="",
        module_no="",
        address="",
        module_meter_photo_id=None,
        after_box_photo_id=None,
        constructed=False,
    )
    assert required_meter_issues(blank) == ()
    assert {issue.code for issue in required_meter_issues(replace(blank, constructed=True))} == {
        "missing_meter_no",
        "missing_module_no",
        "missing_installation_address",
        "missing_module_meter_photo",
        "missing_after_box_photo",
    }


def test_windows_component_is_safe_and_stable() -> None:
    assert safe_windows_component(" MOD:01/02 ") == "MOD：01／02"
    assert safe_windows_component("CON") == "CON_"
    assert safe_windows_component("...") == "_"
    assert len(safe_windows_component("a" * 140)) == 120


def test_preflight_fingerprint_is_order_stable_and_change_sensitive() -> None:
    assert preflight_fingerprint([{"id": "2"}, {"id": "1"}]) == preflight_fingerprint(
        [{"id": "1"}, {"id": "2"}]
    )
    assert preflight_fingerprint([{"id": "1"}]) != preflight_fingerprint(
        [{"id": "1", "sha256": "changed"}]
    )
