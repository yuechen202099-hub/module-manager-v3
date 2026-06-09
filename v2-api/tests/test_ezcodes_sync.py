import json

import pytest
from fastapi.testclient import TestClient

from app.api.routes.ezcodes import set_ezcodes_backend
from app.main import create_app
from app.services.ezcodes_sync import (
    EZCODES_INSTALLERS,
    EzcodesCloudBaseBackend,
    EzcodesCredentials,
    EzcodesError,
    EzcodesFile,
    build_target_sync_plan,
    normalize_barcode_record,
)


MODULE_FOLDER = "\u6a21\u5757\u6539\u9020"
LUO = "\u7f57\u7231\u6c11"
LONG = "\u9f99\u7fd4"
ZHANG = "\u5f20\u6d77\u519b"
DENG = "\u9093\u5353"


class FakeEzcodesBackend:
    def __init__(self) -> None:
        self.files = {
            "0": [
                EzcodesFile(id="root-module", name=MODULE_FOLDER, type=0, parent_id="0"),
                EzcodesFile(id="other", name="\u5176\u4ed6", type=0, parent_id="0"),
            ],
            "root-module": [
                EzcodesFile(id="luo", name=LUO, type=0, parent_id="root-module"),
                EzcodesFile(id="long", name=LONG, type=0, parent_id="root-module"),
                EzcodesFile(id="zhang", name=ZHANG, type=0, parent_id="root-module"),
                EzcodesFile(id="deng", name=DENG, type=0, parent_id="root-module"),
            ],
            "luo": [
                EzcodesFile(id="luo-file-1", name="20260608110259", type=1, parent_id="luo", created_at="2026-06-08 11:02:59"),
                EzcodesFile(id="luo-sub", name="\u8865\u5145", type=0, parent_id="luo"),
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


class FakeHttpResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_build_target_sync_plan_recurses_installer_folders() -> None:
    plan = build_target_sync_plan(FakeEzcodesBackend(), EzcodesCredentials(access_token="token", team_id="team"))

    assert plan["root_folder"] == {"id": "root-module", "name": MODULE_FOLDER}
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
            "collector": "\u91c7\u96c6\u5668A",
            "meterNo": "120000784940",
            "moduleAssetNo": "M-001",
            "address": "\u805a\u4e30\u56ed\u8def188\u5f0483\u53f7",
            "assetType": "\u6a21\u5757",
            "creator": LUO,
            "createTime": "2026-06-08 11:02:59",
            "images": ["cloud://photo-1.jpg", "cloud://photo-2.jpg"],
        },
        file=file,
        installer=LUO,
    )

    assert record.meter_match_key == "123456789"
    assert record.terminal == "350000434929"
    assert record.collector == "\u91c7\u96c6\u5668A"
    assert record.meter_no == "120000784940"
    assert record.module_asset_no == "M-001"
    assert record.address == "\u805a\u4e30\u56ed\u8def188\u5f0483\u53f7"
    assert record.image_file_ids == ("cloud://photo-1.jpg", "cloud://photo-2.jpg")


def test_normalize_barcode_record_rejects_missing_barcode() -> None:
    with pytest.raises(EzcodesError):
        normalize_barcode_record({}, file=EzcodesFile(id="f1", name="file", type=1, parent_id="p"), installer=LUO)


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
    assert payload["plan"]["root_folder"]["name"] == MODULE_FOLDER
    assert payload["plan"]["total_files"] == 2


def test_cloudbase_backend_queries_files_and_barcodes(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = []

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        requests.append(body)
        if body["collectionName"] == "BGFiles":
            return FakeHttpResponse(
                {
                    "data": {
                        "list": [
                            json.dumps(
                                {
                                    "_id": "file-1",
                                    "name": "20260608110259",
                                    "type": 1,
                                    "parentId": "luo",
                                    "createTime": "2026-06-08 11:02:59",
                                }
                            )
                        ]
                    }
                }
            )
        return FakeHttpResponse({"data": {"list": [{"_id": "barcode-1", "txtValue": "ABCDEFGHIJK123456789X"}]}})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    backend = EzcodesCloudBaseBackend()
    credentials = EzcodesCredentials(access_token="token", team_id="team")

    files = backend.list_files(credentials, "luo")
    barcodes = backend.list_barcodes(credentials, "file-1")

    assert files[0].id == "file-1"
    assert barcodes[0]["_id"] == "barcode-1"
    assert requests[0]["action"] == "database.queryDocument"
    assert requests[0]["collectionName"] == "BGFiles"
    assert requests[0]["query"]["teamId"] == {"$eq": "team"}
    assert requests[0]["query"]["parentId"] == "luo"
    assert requests[1]["collectionName"] == "BGBarcodes"
    assert requests[1]["query"]["fileId"] == {"$eq": "file-1"}


def test_cloudbase_backend_resolves_temp_file_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured.update(json.loads(request.data.decode("utf-8")))
        return FakeHttpResponse(
            {
                "data": {
                    "download_list": [
                        {"fileid": "cloud://photo-1.jpg", "download_url": "https://download.example/photo-1.jpg"}
                    ]
                }
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    backend = EzcodesCloudBaseBackend()

    urls = backend.get_temp_file_urls(
        EzcodesCredentials(access_token="token", team_id="team"),
        ["cloud://photo-1.jpg"],
    )

    assert captured["action"] == "storage.batchGetDownloadUrl"
    assert captured["file_list"] == [{"fileid": "cloud://photo-1.jpg", "max_age": 7200}]
    assert urls == {"cloud://photo-1.jpg": "https://download.example/photo-1.jpg"}
