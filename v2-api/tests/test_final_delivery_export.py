from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from threading import Event, Thread
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook

from app.services import final_delivery_export
from app.services.final_delivery_export import (
    DeliveryPackageValidationError,
    build_delivery_package,
    build_delivery_workbook,
    cleanup_delivery_cache,
    delivery_evidence_fingerprint,
    get_or_build_delivery_package,
    release_delivery_cache_path,
    reserve_delivery_cache_path,
)


STANDARD_PHOTOS = (
    ("before_box", "表箱整体改造前"),
    ("collector_barcode", "采集器条形码"),
    ("module_meter", "模块与电能表"),
    ("after_box", "表箱整体改造后"),
)


def delivery_group(
    group_id: str = "group-001",
    *,
    terminal: str = "00123456",
    meter_no: str = "000012345678",
    module_no: str = "000098765432",
    collector: str = "00007777",
    address: str = "江宁路 1 号",
    completed_at: str = "2026-07-21T16:30:00Z",
) -> dict:
    photos = []
    for index, (category, _label) in enumerate(STANDARD_PHOTOS, start=1):
        content = f"photo-{group_id}-{category}".encode()
        photos.append(
            {
                "id": f"{group_id}-photo-{index}",
                "category": category,
                "sha256": hashlib.sha256(content).hexdigest(),
                "delivery_cache_content_sha256": hashlib.sha256(content).hexdigest(),
                "delivery_cache_path": f"objects/{index:02d}/{category}.jpeg",
                "delivery_cache_status": "ready",
                "delivery_cache_version": f"version-{index}",
                "original_filename": f"capture-{category}.jpeg",
                "is_active": True,
                "_content": content,
            }
        )
    return {
        "id": group_id,
        "terminal": terminal,
        "meter_no": meter_no,
        "module_asset_no": module_no,
        "collector": collector,
        "address": address,
        "client_completed_at": completed_at,
        "status": "archived",
        "photos": photos,
    }


def read_photo(photo: dict) -> bytes:
    return photo["_content"]


def test_delivery_workbook_has_exact_dual_sheet_contract_and_text_cells() -> None:
    group = delivery_group()

    workbook = load_workbook(BytesIO(build_delivery_workbook([group, dict(group)])))

    assert workbook.sheetnames == ["老设备", "新设备"]
    old_sheet = workbook["老设备"]
    new_sheet = workbook["新设备"]
    assert [cell.value for cell in old_sheet[1]] == [
        "终端地址",
        "终端厂家",
        "终端安装地址",
        "表号",
        "采集器设备号",
        "供服中心",
        "改造工程队",
        "旧设备拆除时间",
        "旧设备状态",
    ]
    assert [cell.value for cell in new_sheet[1]] == ["改造日期", "模块对应的表号", "新模块编号", "备注"]
    assert old_sheet.max_row == 2
    assert new_sheet.max_row == 2
    assert [cell.value for cell in old_sheet[2]] == [
        "00123456",
        None,
        "江宁路 1 号",
        "000012345678",
        "00007777",
        "南大供电服务中心",
        "奕福",
        None,
        None,
    ]
    assert [cell.value for cell in new_sheet[2]] == [
        "2026-07-22",
        "000012345678",
        "000098765432",
        None,
    ]
    for sheet in (old_sheet, new_sheet):
        for row in sheet.iter_rows(min_row=2):
            assert all(cell.number_format == "@" for cell in row)
    assert all(old_sheet.cell(2, column).data_type == "s" for column in (1, 4, 5))
    assert all(new_sheet.cell(2, column).data_type == "s" for column in (1, 2, 3))


def test_delivery_workbook_is_pure_and_preserves_replacement_remark() -> None:
    group = delivery_group()
    group["replacement_old_meter_no"] = "000000001111"
    for photo in group["photos"]:
        photo.pop("delivery_cache_path")
        photo.pop("delivery_cache_status")

    workbook = load_workbook(BytesIO(build_delivery_workbook([group])))

    assert workbook["新设备"]["D2"].value == "换表：旧表号 000000001111"


def test_delivery_package_uses_exact_four_category_paths_and_original_extensions() -> None:
    group = delivery_group()

    package = build_delivery_package([group], read_photo)

    with ZipFile(BytesIO(package)) as archive:
        assert archive.namelist() == [
            "设备清单.xlsx",
            "00123456/000012345678-000098765432-江宁路 1 号/000098765432-表箱整体改造前.jpeg",
            "00123456/000012345678-000098765432-江宁路 1 号/000098765432-采集器条形码.jpeg",
            "00123456/000012345678-000098765432-江宁路 1 号/000098765432-模块与电能表.jpeg",
            "00123456/000012345678-000098765432-江宁路 1 号/000098765432-表箱整体改造后.jpeg",
        ]
        for photo, name in zip(group["photos"], archive.namelist()[1:], strict=True):
            assert archive.read(name) == photo["_content"]


def test_delivery_package_sanitizes_windows_paths_and_suffixes_sanitized_collisions() -> None:
    first = delivery_group(
        "stable/group:one",
        terminal="T:01.",
        meter_no="M:01",
        module_no="MOD:01",
        collector="C:01",
        address="一号楼? ",
    )
    second = delivery_group(
        "stable-group-two",
        terminal="T?01.",
        meter_no="M?01",
        module_no="MOD?01",
        collector="C?01",
        address="一号楼* ",
    )

    package = build_delivery_package([first, second], read_photo)

    with ZipFile(BytesIO(package)) as archive:
        photo_names = archive.namelist()[1:]
    assert len(photo_names) == 8
    assert len(set(photo_names)) == 8
    assert all(not any(character in name for character in '<>:"\\|?*\x00') for name in photo_names)
    assert any("stable-group-two" in name for name in photo_names)
    assert all(not part.endswith((" ", ".")) for name in photo_names for part in name.split("/"))


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (lambda group: group.update(terminal=""), "missing_terminal"),
        (lambda group: group.update(meter_no=""), "missing_meter_no"),
        (lambda group: group.update(module_asset_no=""), "missing_module_no"),
        (lambda group: group.update(collector=""), "missing_collector"),
        (lambda group: group.update(address=""), "missing_address"),
        (lambda group: group.update(client_completed_at="not-a-date"), "invalid_completed_at"),
        (lambda group: group["photos"].pop(), "invalid_photo_count"),
        (lambda group: group["photos"][1].update(category="before_box"), "invalid_photo_categories"),
        (lambda group: group.update(status="approved"), "not_archived"),
        (lambda group: group.update(terminal="00000000"), "placeholder_identity"),
        (lambda group: group["photos"][0].update(delivery_cache_status="pending"), "delivery_cache_pending"),
    ],
)
def test_delivery_package_blocks_invalid_groups_with_structured_errors(mutate, expected_code: str) -> None:
    group = delivery_group()
    mutate(group)
    reads = 0

    def guarded_reader(photo: dict) -> bytes:
        nonlocal reads
        reads += 1
        return read_photo(photo)

    with pytest.raises(DeliveryPackageValidationError) as captured:
        build_delivery_package([group], guarded_reader)

    assert reads == 0
    assert captured.value.errors
    assert captured.value.errors[0]["group_id"] == "group-001"
    assert expected_code in {error["code"] for error in captured.value.errors}


@pytest.mark.parametrize("field", ["terminal", "meter_no", "module_asset_no", "collector"])
@pytest.mark.parametrize(
    "placeholder",
    ["0", "00", "00000000", "000000000000", "test-device", "TEST123", "manual-device", "unmatched-device"],
)
def test_delivery_package_reuses_formal_identity_validation_for_every_device_field(
    field: str,
    placeholder: str,
) -> None:
    group = delivery_group()
    group[field] = placeholder

    with pytest.raises(DeliveryPackageValidationError) as captured:
        build_delivery_package([group], read_photo)

    assert any(
        error["code"] == "placeholder_identity" and error["field"] == field
        for error in captured.value.errors
    )


def test_delivery_package_reports_cross_group_device_conflicts_without_partial_output() -> None:
    first = delivery_group("group-001")
    second = delivery_group("group-002", address="江宁路 2 号")

    with pytest.raises(DeliveryPackageValidationError) as captured:
        build_delivery_package([first, second], read_photo)

    conflicts = [error for error in captured.value.errors if error["code"] == "device_conflict"]
    assert {error["group_id"] for error in conflicts} == {"group-001", "group-002"}
    assert {error["field"] for error in conflicts} == {"terminal", "meter_no", "module_asset_no", "collector"}


def test_delivery_package_rejects_an_empty_formal_scope() -> None:
    with pytest.raises(DeliveryPackageValidationError) as captured:
        build_delivery_package([], read_photo)

    assert captured.value.errors == [
        {
            "group_id": "",
            "code": "no_groups",
            "field": "scope",
            "message": "No archived groups are eligible for formal delivery",
        }
    ]


def test_get_or_build_delivery_package_reuses_same_fingerprint_for_seven_days(tmp_path: Path) -> None:
    group = delivery_group()
    reads = 0
    builds = 0

    def counting_reader(photo: dict) -> bytes:
        nonlocal reads
        reads += 1
        return read_photo(photo)

    def counting_builder(groups, reader) -> bytes:
        nonlocal builds
        builds += 1
        return build_delivery_package(groups, reader)

    now = datetime(2026, 7, 22, 8, tzinfo=UTC)
    first = get_or_build_delivery_package(
        "team-a/task-1",
        "a" * 64,
        groups=[group],
        photo_reader=counting_reader,
        cache_root=tmp_path,
        now=now,
        package_builder=counting_builder,
    )
    second = get_or_build_delivery_package(
        "team-a/task-1",
        "a" * 64,
        groups=[group],
        photo_reader=counting_reader,
        cache_root=tmp_path,
        now=now + timedelta(days=6, hours=23),
        package_builder=counting_builder,
    )

    try:
        assert first == second
        assert first.is_file()
        assert builds == 1
        assert reads == 4
    finally:
        first.release()
        second.release()


def test_get_or_build_delivery_package_rebuilds_after_ttl_or_fingerprint_change(tmp_path: Path) -> None:
    group = delivery_group()
    builds = 0

    def counting_builder(groups, reader) -> bytes:
        nonlocal builds
        builds += 1
        return build_delivery_package(groups, reader)

    now = datetime(2026, 7, 22, 8, tzinfo=UTC)
    first = get_or_build_delivery_package(
        "task-1",
        "a" * 64,
        groups=[group],
        photo_reader=read_photo,
        cache_root=tmp_path,
        now=now,
        package_builder=counting_builder,
    )
    changed = get_or_build_delivery_package(
        "task-1",
        "b" * 64,
        groups=[group],
        photo_reader=read_photo,
        cache_root=tmp_path,
        now=now + timedelta(hours=1),
        package_builder=counting_builder,
    )
    first.release()
    rebuilt = get_or_build_delivery_package(
        "task-1",
        "a" * 64,
        groups=[group],
        photo_reader=read_photo,
        cache_root=tmp_path,
        now=now + timedelta(days=8),
        package_builder=counting_builder,
    )

    try:
        assert first != changed
        assert rebuilt == first
        assert builds == 3
    finally:
        changed.release()
        rebuilt.release()


def test_cached_package_never_bypasses_current_group_validation(tmp_path: Path) -> None:
    group = delivery_group()
    now = datetime(2026, 7, 22, 8, tzinfo=UTC)
    path = get_or_build_delivery_package(
        "task-1",
        "a" * 64,
        groups=[group],
        photo_reader=read_photo,
        cache_root=tmp_path,
        now=now,
    )
    group["photos"][0]["delivery_cache_status"] = "pending"

    with pytest.raises(DeliveryPackageValidationError) as captured:
        get_or_build_delivery_package(
            "task-1",
            "a" * 64,
            groups=[group],
            photo_reader=lambda _photo: (_ for _ in ()).throw(AssertionError("must not read photos")),
            cache_root=tmp_path,
            now=now + timedelta(hours=1),
        )

    try:
        assert path.is_file()
        assert {error["code"] for error in captured.value.errors} == {"delivery_cache_pending"}
    finally:
        path.release()


def test_identity_category_and_photo_changes_invalidate_delivery_fingerprint() -> None:
    group = delivery_group()
    original = delivery_evidence_fingerprint([group])
    group["module_asset_no"] = "000098765433"
    identity_changed = delivery_evidence_fingerprint([group])
    group["photos"][0]["category"] = "collector_barcode"
    category_changed = delivery_evidence_fingerprint([group])
    group["photos"][0]["sha256"] = "f" * 64
    group["photos"][0]["delivery_cache_content_sha256"] = "f" * 64
    photo_changed = delivery_evidence_fingerprint([group])

    assert len({original, identity_changed, category_changed, photo_changed}) == 4


@pytest.mark.parametrize(
    "mutation",
    [
        lambda group: group.update(replacement_old_meter_no="000000001111"),
        lambda group: group.update(exception_reasons=["reason-a"]),
        lambda group: group.update(exception_note="note-a"),
        lambda group: group.update(group_barcode_manual_confirmed=True),
        lambda group: group.update(export_remark="export-a"),
    ],
    ids=["replacement", "exception-reasons", "exception-note", "manual-confirmation", "export-remark"],
)
def test_delivery_fingerprint_includes_every_workbook_visible_remark(mutation) -> None:
    group = delivery_group()
    original = delivery_evidence_fingerprint([group])

    mutation(group)

    assert delivery_evidence_fingerprint([group]) != original


@pytest.mark.parametrize(
    "mutation",
    [
        lambda photo: photo.update(is_active=False),
        lambda photo: photo.update(upload_status="invalid"),
    ],
    ids=["inactive", "invalid-upload"],
)
def test_invalid_photo_evidence_cannot_satisfy_formal_four_photo_contract(mutation) -> None:
    group = delivery_group()
    mutation(group["photos"][0])

    with pytest.raises(DeliveryPackageValidationError) as captured:
        build_delivery_package(
            [group],
            lambda _photo: (_ for _ in ()).throw(AssertionError("invalid evidence must block before reads")),
        )

    assert "invalid_photo_count" in {error["code"] for error in captured.value.errors}


@pytest.mark.parametrize("content", [b"", b"wrong-content"], ids=["empty", "wrong-hash"])
def test_delivery_package_converts_invalid_cached_bytes_to_group_error(content: bytes) -> None:
    group = delivery_group()

    with pytest.raises(DeliveryPackageValidationError) as captured:
        build_delivery_package([group], lambda _photo: content)

    assert captured.value.errors[0]["group_id"] == group["id"]
    assert {error["code"] for error in captured.value.errors} == {"delivery_cache_invalid"}


def test_windows_casefold_collision_assignment_is_stable_and_suffixes_every_member() -> None:
    upper = delivery_group(
        "group-UPPER",
        terminal="TERM-A",
        meter_no="METER-A",
        module_no="MODULE-A",
        collector="COLLECTOR-A",
        address="ADDRESS-A",
    )
    lower = delivery_group(
        "group-lower",
        terminal="term-a",
        meter_no="meter-a",
        module_no="module-a",
        collector="collector-a",
        address="address-a",
    )

    first = build_delivery_package([upper, lower], read_photo)
    reordered = build_delivery_package([lower, upper], read_photo)

    with ZipFile(BytesIO(first)) as archive:
        first_names = archive.namelist()[1:]
    with ZipFile(BytesIO(reordered)) as archive:
        reordered_names = archive.namelist()[1:]
    assert first_names == reordered_names
    assert len({name.casefold() for name in first_names}) == 8
    assert all("group-UPPER" in name or "group-lower" in name for name in first_names)


def test_cleanup_rechecks_a_late_path_reservation_before_delete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "objects" / "aa" / "late.jpg"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"late-reservation")
    paused = Event()
    resume = Event()
    original_stat = Path.stat

    def pausing_stat(path: Path, *args, **kwargs):
        if path == target and not paused.is_set():
            paused.set()
            assert resume.wait(5)
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", pausing_stat)
    cleanup = Thread(
        target=cleanup_delivery_cache,
        kwargs={"cache_root": tmp_path, "max_object_bytes": 0, "groups": []},
        daemon=True,
    )
    cleanup.start()
    lease = None
    try:
        assert paused.wait(5)
        lease = reserve_delivery_cache_path(target)
        resume.set()
        cleanup.join(5)
        assert not cleanup.is_alive()
        assert target.exists()
    finally:
        resume.set()
        if lease is not None:
            release_delivery_cache_path(lease)
        if cleanup.is_alive():
            cleanup.join(5)
            assert not cleanup.is_alive()


def test_package_is_reserved_before_build_lock_releases_to_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original_lock = final_delivery_export._package_lock
    cleanup_ran = Event()

    @contextmanager
    def cleanup_on_release(key: str):
        with original_lock(key):
            yield
        cleanup_delivery_cache(
            tmp_path,
            max_object_bytes=0,
            groups=[],
            now=datetime.now(UTC) + timedelta(days=8),
        )
        cleanup_ran.set()

    monkeypatch.setattr(final_delivery_export, "_package_lock", cleanup_on_release)

    package = get_or_build_delivery_package(
        "cleanup-gap",
        "a" * 64,
        groups=[delivery_group()],
        photo_reader=read_photo,
        cache_root=tmp_path,
    )
    try:
        assert cleanup_ran.is_set()
        assert package.path.is_file()
    finally:
        package.release()


def _install_atomic_cleanup_probe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    cleanup_now: datetime,
):
    original_reserve = final_delivery_export._reserve_delivery_cache_key_locked
    probe = {
        "hook_ran": Event(),
        "cleanup_attempted": Event(),
        "first_pass_done": Event(),
        "cleanup_completed": Event(),
        "reports": [],
        "errors": [],
        "worker": None,
        "target_key": None,
    }

    def cleanup_worker() -> None:
        try:
            probe["cleanup_attempted"].set()
            probe["reports"].append(
                cleanup_delivery_cache(
                    tmp_path,
                    max_object_bytes=0,
                    groups=[],
                    now=cleanup_now,
                )
            )
            with final_delivery_export._CACHE_PATH_CONDITION:
                probe["first_pass_done"].set()
                released = final_delivery_export._CACHE_PATH_CONDITION.wait_for(
                    lambda: not final_delivery_export._cache_path_is_reserved(probe["target_key"]),
                    timeout=5,
                )
            if not released:
                raise AssertionError("package lease was not released")
            probe["reports"].append(
                cleanup_delivery_cache(
                    tmp_path,
                    max_object_bytes=0,
                    groups=[],
                    now=cleanup_now,
                )
            )
        except BaseException as exc:
            probe["errors"].append(exc)
        finally:
            probe["first_pass_done"].set()
            probe["cleanup_completed"].set()

    def reserve_with_cleanup_attempt(key: str) -> None:
        probe["hook_ran"].set()
        probe["target_key"] = key
        worker = Thread(target=cleanup_worker, daemon=True)
        probe["worker"] = worker
        worker.start()
        assert probe["cleanup_attempted"].wait(5)
        assert not probe["first_pass_done"].wait(0.1)
        original_reserve(key)

    monkeypatch.setattr(
        final_delivery_export,
        "_reserve_delivery_cache_key_locked",
        reserve_with_cleanup_attempt,
    )
    return probe


def _finish_atomic_cleanup_probe(probe, package) -> None:
    if package is not None:
        package.release()
    worker = probe["worker"]
    if worker is not None:
        worker.join(5)
        assert not worker.is_alive()


def test_fresh_package_validation_and_lease_are_atomic_with_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 22, 8, tzinfo=UTC)
    original = get_or_build_delivery_package(
        "fresh-reserve-gap",
        "a" * 64,
        groups=[delivery_group()],
        photo_reader=read_photo,
        cache_root=tmp_path,
        now=now,
    )
    original.release()
    probe = _install_atomic_cleanup_probe(
        monkeypatch,
        tmp_path,
        cleanup_now=now + timedelta(days=8),
    )
    package = None
    try:
        package = get_or_build_delivery_package(
            "fresh-reserve-gap",
            "a" * 64,
            groups=[delivery_group()],
            photo_reader=read_photo,
            cache_root=tmp_path,
            now=now + timedelta(hours=1),
            package_builder=lambda _groups, _reader: pytest.fail("fresh package must be reused"),
        )
        assert probe["hook_ran"].is_set()
        assert probe["cleanup_attempted"].is_set()
        assert probe["first_pass_done"].wait(5)
        assert probe["reports"][0]["deleted_packages"] == 0
        assert not probe["cleanup_completed"].is_set()
        assert package.path.is_file()
    finally:
        _finish_atomic_cleanup_probe(probe, package)
    assert probe["cleanup_completed"].is_set()
    assert probe["errors"] == []
    assert probe["reports"][1]["deleted_packages"] == 1
    assert not package.path.exists()


def test_replacement_and_new_lease_are_atomic_with_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 22, 8, tzinfo=UTC)
    original = get_or_build_delivery_package(
        "replacement-reserve-gap",
        "b" * 64,
        groups=[delivery_group()],
        photo_reader=read_photo,
        cache_root=tmp_path,
        now=now,
    )
    original.release()
    probe = _install_atomic_cleanup_probe(
        monkeypatch,
        tmp_path,
        cleanup_now=now + timedelta(days=16),
    )
    package = None
    try:
        package = get_or_build_delivery_package(
            "replacement-reserve-gap",
            "b" * 64,
            groups=[delivery_group()],
            photo_reader=read_photo,
            cache_root=tmp_path,
            now=now + timedelta(days=8),
            package_builder=lambda _groups, _reader: b"replacement-package",
        )
        assert probe["hook_ran"].is_set()
        assert probe["cleanup_attempted"].is_set()
        assert probe["first_pass_done"].wait(5)
        assert probe["reports"][0]["deleted_packages"] == 0
        assert not probe["cleanup_completed"].is_set()
        assert package.path.is_file()
        assert package.path.read_bytes() == b"replacement-package"
    finally:
        _finish_atomic_cleanup_probe(probe, package)
    assert probe["cleanup_completed"].is_set()
    assert probe["errors"] == []
    assert probe["reports"][1]["deleted_packages"] == 1
    assert not package.path.exists()


def test_package_is_reserved_before_build_lock_releases_to_expired_rebuild(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original_lock = final_delivery_export._package_lock
    first_release = True
    rebuild_started = Event()
    rebuild_finished = Event()
    rebuilt_packages = []
    rebuild_errors = []
    worker = None

    def replacement_builder(_groups, _reader) -> bytes:
        rebuild_started.set()
        return b"replacement"

    def rebuild() -> None:
        try:
            rebuilt_packages.append(
                get_or_build_delivery_package(
                    "rebuild-gap",
                    "b" * 64,
                    groups=[delivery_group()],
                    photo_reader=read_photo,
                    cache_root=tmp_path,
                    now=datetime.now(UTC) + timedelta(days=8),
                    package_builder=replacement_builder,
                )
            )
        except BaseException as exc:
            rebuild_errors.append(exc)
        finally:
            rebuild_finished.set()

    @contextmanager
    def rebuild_on_release(key: str):
        nonlocal first_release, worker
        with original_lock(key):
            yield
        if first_release:
            first_release = False
            worker = Thread(target=rebuild, daemon=True)
            worker.start()
            rebuild_started.wait(5)

    monkeypatch.setattr(final_delivery_export, "_package_lock", rebuild_on_release)

    package = None
    try:
        package = get_or_build_delivery_package(
            "rebuild-gap",
            "b" * 64,
            groups=[delivery_group()],
            photo_reader=read_photo,
            cache_root=tmp_path,
        )
        assert rebuild_started.is_set()
        assert not rebuild_finished.is_set()
    finally:
        if package is not None:
            package.release()
        if worker is not None:
            worker.join(5)
            assert not worker.is_alive()
        for rebuilt in rebuilt_packages:
            rebuilt.release()

    assert rebuild_finished.is_set()
    assert rebuild_errors == []
    assert rebuilt_packages[0].path.read_bytes() == b"replacement"


def test_expired_package_replacement_waits_for_active_download(tmp_path: Path) -> None:
    group = delivery_group()
    now = datetime(2026, 7, 22, 8, tzinfo=UTC)
    target = get_or_build_delivery_package(
        "active-download",
        "a" * 64,
        groups=[group],
        photo_reader=read_photo,
        cache_root=tmp_path,
        now=now,
    )
    original = target.read_bytes()
    lease = reserve_delivery_cache_path(target)
    builder_started = Event()
    finished = Event()
    rebuild_errors = []

    def rebuilt_package(_groups, _reader) -> bytes:
        builder_started.set()
        return b"replacement-package"

    def rebuild() -> None:
        rebuilt = None
        try:
            rebuilt = get_or_build_delivery_package(
                "active-download",
                "a" * 64,
                groups=[group],
                photo_reader=read_photo,
                cache_root=tmp_path,
                now=now + timedelta(days=8),
                package_builder=rebuilt_package,
            )
        except BaseException as exc:
            rebuild_errors.append(exc)
        finally:
            if rebuilt is not None:
                rebuilt.release()
            finished.set()

    worker = Thread(target=rebuild, daemon=True)
    worker.start()
    try:
        assert builder_started.wait(5)
        assert not finished.wait(0.2)
        assert target.read_bytes() == original
    finally:
        release_delivery_cache_path(lease)
        target.release()
        worker.join(5)
        assert not worker.is_alive()
    assert rebuild_errors == []
    assert target.read_bytes() == b"replacement-package"


def test_package_lock_registry_is_bounded_after_key_churn(tmp_path: Path) -> None:
    group = delivery_group()
    now = datetime(2026, 7, 22, 8, tzinfo=UTC)

    for index in range(40):
        package = get_or_build_delivery_package(
            f"scope-{index}",
            f"{index:064x}",
            groups=[group],
            photo_reader=read_photo,
            cache_root=tmp_path,
            now=now,
        )
        package.release()

    assert final_delivery_export._PACKAGE_LOCKS == {}


def test_concurrent_same_key_builders_share_one_package_lock(tmp_path: Path) -> None:
    group = delivery_group()
    started = Event()
    release = Event()
    builds = 0
    paths: list[Path] = []

    def package_builder(_groups, _reader) -> bytes:
        nonlocal builds
        builds += 1
        started.set()
        assert release.wait(5)
        return b"one-package"

    def build() -> None:
        paths.append(
            get_or_build_delivery_package(
                "same-scope",
                "f" * 64,
                groups=[group],
                photo_reader=read_photo,
                cache_root=tmp_path,
                package_builder=package_builder,
            )
        )

    first = Thread(target=build, daemon=True)
    second = Thread(target=build, daemon=True)
    try:
        first.start()
        assert started.wait(5)
        second.start()
        release.set()
        first.join(5)
        second.join(5)
        assert not first.is_alive() and not second.is_alive()
        assert builds == 1
        assert paths[0] == paths[1]
        assert final_delivery_export._PACKAGE_LOCKS == {}
    finally:
        release.set()
        first.join(5)
        if second.ident is not None:
            second.join(5)
        for package in paths:
            package.release()


def test_delivery_lru_keeps_referenced_and_active_paths(tmp_path: Path) -> None:
    now = datetime(2026, 7, 22, 8, tzinfo=UTC)
    referenced = tmp_path / "objects" / "aa" / "referenced.jpg"
    active_object = tmp_path / "objects" / "bb" / "active.jpg"
    removable = tmp_path / "objects" / "cc" / "removable.jpg"
    active_package = tmp_path / "packages" / "scope" / "active.zip"
    for path, content in (
        (referenced, b"referenced"),
        (active_object, b"active"),
        (removable, b"remove-me"),
        (active_package, b"package"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        old = (now - timedelta(days=8)).timestamp()
        path.touch()
        import os

        os.utime(path, (old, old))
    group = {
        "delivery_cache_status": "ready",
        "photos": [
            {
                "is_active": True,
                "delivery_cache_status": "ready",
                "delivery_cache_path": str(referenced.relative_to(tmp_path)).replace("\\", "/"),
            }
        ],
    }
    object_lease = reserve_delivery_cache_path(active_object)
    package_lease = reserve_delivery_cache_path(active_package)
    try:
        result = cleanup_delivery_cache(tmp_path, max_object_bytes=0, groups=[group], now=now)

        assert referenced.exists()
        assert active_object.exists()
        assert active_package.exists()
        assert not removable.exists()
        assert result["protected_objects"] == 2
    finally:
        release_delivery_cache_path(object_lease)
        release_delivery_cache_path(package_lease)

    cleanup_delivery_cache(tmp_path, max_object_bytes=0, groups=[], now=now)

    assert not referenced.exists()
    assert not active_object.exists()
    assert not active_package.exists()


def test_delivery_content_builder_blocks_lru_for_its_object_store(tmp_path: Path) -> None:
    from app.services.delivery_cache import cache_group_photos

    old_object = tmp_path / "objects" / "old" / "old.jpg"
    old_object.parent.mkdir(parents=True, exist_ok=True)
    old_object.write_bytes(b"old")
    content = b"new-content"
    started = Event()
    finish = Event()
    group = {
        "id": "building-group",
        "photos": [
            {
                "id": "building-photo",
                "sha256": hashlib.sha256(content).hexdigest(),
                "sha256_source": "declared",
                "category": "before_box",
                "original_filename": "before.jpg",
                "is_active": True,
            }
        ],
    }

    def fetch_photo(_photo):
        started.set()
        assert finish.wait(5)
        return content, ".jpg", "image/jpeg"

    worker = Thread(
        target=cache_group_photos,
        kwargs={"group": group, "cache_root": tmp_path, "fetch_photo": fetch_photo},
        daemon=True,
    )
    worker.start()
    try:
        assert started.wait(5)
        cleanup_delivery_cache(tmp_path, max_object_bytes=0, groups=[])
        assert old_object.exists()
    finally:
        finish.set()
        worker.join(5)
        assert not worker.is_alive()
