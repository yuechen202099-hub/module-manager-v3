import pytest
from fastapi.testclient import TestClient

from app.api.routes.ezcodes import set_ezcodes_backend
from app.main import create_app
from app.services.ezcodes_sync import (
    EZCODES_INSTALLERS,
    EzcodesCredentials,
    EzcodesError,
    EzcodesFile,
    build_target_sync_plan,
    normalize_barcode_record,
)


class FakeEzcodesBackend:
    def __init__(self) -> None:
        self.files = {
            "0": [
                EzcodesFile(id="root-module", name="模块改造", type=0, parent_id="0"),
                EzcodesFile(id="other", name="其他", type=0, parent_id="0"),
            ],
            "root-module": [
                EzcodesFile(id="luo", name="罗爱民", type=0, parent_id="root-module"),
                EzcodesFile(id="long", name="龙翔", type=0, parent_id="root-module"),
                EzcodesFile(id="zhang", name="张海军", type=0, parent_id="root-module"),
                EzcodesFile(id="deng", name="邓卓", type=0, parent_id="root-module"),
            ],
            "luo": [
                EzcodesFile(id="luo-file-1", name="20260608110259", type=1, parent_id="luo", created_at="2026-06-08 11:02:59"),
                EzcodesFile(id="luo-sub", name="补充", type=0, parent_id="luo"),
            ],
            "luo-sub": [
                EzcodesFile(id="luo-file-2", name="20260608120000", type=1, parent_id="luo-sub", created_at="2026-06-08 12:00:00"),
            ],
            "long": [],
            "zhang": [],
            "deng": [],
        }

    def list_files(self, credentials: EzcodesCredentials, parent_id: str) -> list[EzcodesFile]:
        return self.files.get(parent_id, [])

    def list_barcodes(self, credentials: EzcodesCredentials, file_id: str) -> list[dict]:
        return []

    def get_temp_file_urls(self, credentials: EzcodesCredentials, file_ids: list[str]) -> dict[str, str]:
        return {}


def test_build_target_sync_plan_recurses_installer_folders() -> None:
    plan = build_target_sync_plan(FakeEzcodesBackend(), EzcodesCredentials(access_token="token", team_id="team"))

    assert plan["root_folder"] == {"id": "root-module", "name": "模块改造"}
    assert [item["name"] for item in plan["installers"]] == list(EZCODES_INSTALLERS)
    assert plan["installers"][0]["file_count"] == 2
    assert plan["total_files"] == 2
    assert plan["missing_installers"] == []


def test_normalize_barcode_record_preserves_project_baseline_fields() -> None:
    file = EzcodesFile(id="f1", name="20260608110259", type=1, parent_id="luo")
    record = normalize_barcode_record(
        {
            "txtValue": "ABCDEFGHIJK123456789X",
            "terminal": "350000434929",
            "collector": "采集器A",
            "meterNo": "120000784940",
            "moduleAssetNo": "M-001",
            "address": "聚丰园路188弄83号",
            "assetType": "模块",
            "creator": "罗爱民",
            "createTime": "2026-06-08 11:02:59",
            "images": ["cloud://photo-1.jpg", "cloud://photo-2.jpg"],
        },
        file=file,
        installer="罗爱民",
    )

    assert record.meter_match_key == "123456789"
    assert record.terminal == "350000434929"
    assert record.collector == "采集器A"
    assert record.meter_no == "120000784940"
    assert record.module_asset_no == "M-001"
    assert record.address == "聚丰园路188弄83号"
    assert record.image_file_ids == ("cloud://photo-1.jpg", "cloud://photo-2.jpg")


def test_normalize_barcode_record_rejects_missing_barcode() -> None:
    with pytest.raises(EzcodesError):
        normalize_barcode_record({}, file=EzcodesFile(id="f1", name="file", type=1, parent_id="p"), installer="罗爱民")


def test_ezcodes_preview_endpoint_uses_backend_without_frontend() -> None:
    set_ezcodes_backend(FakeEzcodesBackend())
    client = TestClient(create_app())

    response = client.post(
        "/projects/1/scan/ezcodes/preview",
        json={"credentials": {"access_token": "token", "team_id": "team"}},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["project_id"] == 1
    assert payload["plan"]["root_folder"]["name"] == "模块改造"
    assert payload["plan"]["total_files"] == 2
