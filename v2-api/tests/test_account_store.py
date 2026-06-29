from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services import account_store


def test_ensure_user_store_does_not_hash_default_admin_when_admin_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    users_path = tmp_path / "users.json"
    users_path.write_text(
        json.dumps(
            {
                "version": 1,
                "users": [
                    {
                        "username": "root-admin",
                        "name": "Root Admin",
                        "roles": ["reviewer"],
                        "team_id": "default-team",
                        "status": "active",
                        "home": "/app",
                        "password_hash": "already-hashed",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        account_store,
        "settings",
        SimpleNamespace(
            admin_username="root-admin",
            admin_password="expensive-password",
            admin_team_id="default-team",
            auth_users_path=str(users_path),
        ),
    )

    def fail_hash_password(_password: str) -> str:
        raise AssertionError("default admin password hash should not be recomputed")

    monkeypatch.setattr(account_store, "hash_password", fail_hash_password)

    users = account_store.ensure_user_store()

    assert users["root-admin"]["password_hash"] == "already-hashed"
