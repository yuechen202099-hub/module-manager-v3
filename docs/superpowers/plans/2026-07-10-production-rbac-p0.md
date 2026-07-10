# Production RBAC P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce the approved production role boundaries for scan clearing, review mutations, and construction mutations without changing local-development behavior.

**Architecture:** Keep authorization in `local_test.py` beside the existing request-auth helpers. A single production-aware role guard will validate the JWT payload already attached to the request, while the clear route and both actor binders will define their operation-specific allowed roles.

**Tech Stack:** Python 3, FastAPI, Starlette `TestClient`, pytest, JWT authentication

## Global Constraints

- Work only on branch `fix/production-rbac-p0` in the linked production worktree.
- Preserve behavior when `APP_ENV` is not `prod` or `production`.
- Do not change business data models, frontend behavior, production data, or deployment state. Per the user's 2026-07-10 correction, advance the bug-fix candidate from `V3.0.78` to `V3.0.79`.
- Return `401 Authentication required` when production authentication is missing.
- Return `403` with an operation-specific message when an authenticated production role is not allowed.
- Use real login tokens in API tests and prove rejected requests do not reach repository methods.

---

### Task 1: Add Production RBAC Regression Tests

**Files:**
- Modify: `v2-api/tests/test_api.py:13-20`
- Modify: `v2-api/tests/test_api.py:438-550`

**Interfaces:**
- Consumes: `production_test_settings(**overrides)`, `TestClient`, `/auth/login`, and `/auth/users`.
- Produces: `production_rbac_client(monkeypatch, tmp_path) -> tuple[TestClient, dict[str, dict[str, str]]]` and API-level regression coverage for all three role boundaries.

- [ ] **Step 1: Import the route module whose production settings and repository factory must be isolated**

```python
from app.api.routes import auth, local_test
```

- [ ] **Step 2: Add a production RBAC client helper using real account creation and login**

```python
def production_rbac_client(monkeypatch, tmp_path) -> tuple[TestClient, dict[str, dict[str, str]]]:
    production_settings = production_test_settings(
        demo_auth_enabled=False,
        admin_username="root-admin",
        admin_password="RootPass12345",
        admin_team_id="north-team-01",
        auth_users_path=str(tmp_path / "rbac-users.json"),
        jwt_secret="jwt-secret-for-production-rbac-test",
        jwt_expire_minutes=60,
        trusted_proxy_hosts={"testclient"},
    )
    monkeypatch.setattr(auth, "settings", production_settings)
    monkeypatch.setattr(account_store, "settings", production_settings)
    monkeypatch.setattr(security, "settings", production_settings)
    monkeypatch.setattr(main_module, "settings", production_settings)
    monkeypatch.setattr(local_test, "settings", production_settings)
    production_client = TestClient(main_module.create_app())

    admin_login = production_client.post(
        "/auth/login",
        json={"username": "root-admin", "password": "RootPass12345"},
    )
    assert admin_login.status_code == 200
    headers = {
        "admin": {"Authorization": f"bearer {admin_login.json()['data']['access_token']}"},
    }
    for username, password, role in (
        ("reviewer-a", "ReviewPass12345", "reviewer"),
        ("constructor-a", "ConstructPass12345", "constructor"),
    ):
        created = production_client.post(
            "/auth/users",
            headers=headers["admin"],
            json={
                "username": username,
                "password": password,
                "name": username,
                "roles": [role],
                "team_id": "north-team-01",
                "status": "active",
            },
        )
        assert created.status_code == 200
        login = production_client.post(
            "/auth/login",
            json={"username": username, "password": password},
        )
        assert login.status_code == 200
        headers[role] = {"Authorization": f"bearer {login.json()['data']['access_token']}"}
    return production_client, headers
```

- [ ] **Step 3: Add the failing scan-clear role test**

```python
def test_production_scan_clear_requires_admin_role(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    class FakeRepository:
        clear_calls = 0

        def clear_scan_data(self):
            self.clear_calls += 1
            return {"summary": {"scan_rows": 0}}

    repository = FakeRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)

    assert production_client.post("/local-test/scan/clear").status_code == 401
    assert production_client.post("/local-test/scan/clear", headers=headers["reviewer"]).status_code == 403
    assert production_client.post("/local-test/scan/clear", headers=headers["constructor"]).status_code == 403
    assert repository.clear_calls == 0

    allowed = production_client.post("/local-test/scan/clear", headers=headers["admin"])
    assert allowed.status_code == 200
    assert repository.clear_calls == 1
```

- [ ] **Step 4: Run the scan-clear test and verify RED**

Run: `..\.venv\Scripts\python.exe -m pytest tests\test_api.py::test_production_scan_clear_requires_admin_role -q`

Expected: FAIL because a reviewer receives `200` and `FakeRepository.clear_calls` increments before an authorization check exists.

- [ ] **Step 5: Add failing review and construction mutation role tests**

```python
def test_production_review_mutation_requires_reviewer_or_admin(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    class FakeRepository:
        claim_calls = 0

        def claim_task(self, task_id, reviewer):
            self.claim_calls += 1
            return {"id": task_id, "reviewer": reviewer}

    repository = FakeRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)

    denied = production_client.post(
        "/local-test/tasks/999999/claim",
        headers=headers["constructor"],
        json={"reviewer": "constructor-a"},
    )
    assert denied.status_code == 403
    assert repository.claim_calls == 0

    allowed = production_client.post(
        "/local-test/tasks/999999/claim",
        headers=headers["reviewer"],
        json={"reviewer": "reviewer-a"},
    )
    assert allowed.status_code == 200
    assert repository.claim_calls == 1


def test_production_construction_mutation_requires_constructor_or_admin(monkeypatch, tmp_path) -> None:
    production_client, headers = production_rbac_client(monkeypatch, tmp_path)

    class FakeRepository:
        claim_calls = 0

        def claim_construction_task(self, task_id, actor):
            self.claim_calls += 1
            return {"id": task_id, "constructor": actor}

    repository = FakeRepository()
    monkeypatch.setattr(local_test, "state_repository", lambda: repository)

    denied = production_client.post(
        "/local-test/construction/tasks/999999/claim",
        headers=headers["reviewer"],
        json={"actor": "reviewer-a"},
    )
    assert denied.status_code == 403
    assert repository.claim_calls == 0

    allowed = production_client.post(
        "/local-test/construction/tasks/999999/claim",
        headers=headers["constructor"],
        json={"actor": "constructor-a"},
    )
    assert allowed.status_code == 200
    assert repository.claim_calls == 1
```

- [ ] **Step 6: Run both mutation tests and verify RED**

Run: `..\.venv\Scripts\python.exe -m pytest tests\test_api.py::test_production_review_mutation_requires_reviewer_or_admin tests\test_api.py::test_production_construction_mutation_requires_constructor_or_admin -q`

Expected: FAIL because each wrong-role request reaches its fake repository and returns `200`.

- [ ] **Step 7: Commit the failing tests**

```powershell
git add v2-api/tests/test_api.py
git commit -m "test: cover production RBAC boundaries"
```

### Task 2: Enforce Production Roles at the Route Boundary

**Files:**
- Modify: `v2-api/app/api/routes/local_test.py:294-360`
- Modify: `v2-api/app/api/routes/local_test.py:1023-1025`

**Interfaces:**
- Consumes: `request_auth_payload(request) -> dict`, `settings.app_env`, and JWT `roles` claims.
- Produces: `require_request_roles(request, allowed_roles, detail) -> dict` and production authorization for the clear route plus both actor binders.

- [ ] **Step 1: Add the reusable production-aware request role guard**

```python
def require_request_roles(request: Request, allowed_roles: set[str], detail: str) -> dict:
    payload = request_auth_payload(request)
    if settings.app_env.lower() not in {"prod", "production"}:
        return payload
    if not payload:
        raise HTTPException(status_code=401, detail="Authentication required")
    roles = set(payload.get("roles") or [])
    if roles.isdisjoint(allowed_roles):
        raise HTTPException(status_code=403, detail=detail)
    return payload
```

- [ ] **Step 2: Apply the guard before actor binding logic**

Add this as the first statement in `bound_review_actor`:

```python
require_request_roles(
    request,
    {"reviewer", "admin"},
    detail="Reviewer or administrator role required",
)
```

Add this as the first statement in `bound_construction_actor`:

```python
require_request_roles(
    request,
    {"constructor", "admin"},
    detail="Constructor or administrator role required",
)
```

- [ ] **Step 3: Guard scan clearing before repository access**

```python
@router.post("/scan/clear")
def clear_scan(request: Request):
    require_request_roles(request, {"admin"}, detail="Administrator role required")
    return ok(request, state_repository().clear_scan_data())
```

- [ ] **Step 4: Run the three new tests and verify GREEN**

Run: `..\.venv\Scripts\python.exe -m pytest tests\test_api.py -k "production_scan_clear_requires_admin_role or production_review_mutation_requires_reviewer_or_admin or production_construction_mutation_requires_constructor_or_admin" -q`

Expected: `3 passed`.

- [ ] **Step 5: Run existing local behavior regressions**

Run: `..\.venv\Scripts\python.exe -m pytest tests\test_api.py -k "clear_scan_data_route_resets_local_scan_state or local_test_task_and_review_flow or construction_task" -q`

Expected: all selected tests pass and unauthenticated local scan clearing remains allowed.

- [ ] **Step 6: Commit the implementation**

```powershell
git add v2-api/app/api/routes/local_test.py
git commit -m "fix: enforce production route roles"
```

### Task 3: Verify the Backend and Security Contract

**Files:**
- Verify: `v2-api/tests/`
- Verify: `scripts/`

**Interfaces:**
- Consumes: the completed tests and route guard.
- Produces: clean test, verifier, and whitespace evidence with no release artifact or deployment.

- [ ] **Step 1: Run the complete backend suite**

Run: `..\.venv\Scripts\python.exe -m pytest -q`

Expected: all backend tests pass.

- [ ] **Step 2: Run relevant security and production verifiers discovered in `scripts/`**

Run each existing verifier whose name or source explicitly checks authentication, production readiness, or route security. Record every command and result; do not create or package a release.

- [ ] **Step 3: Check patch hygiene**

Run: `git diff --check production/V3/3.0.78...HEAD`

Expected: no output and exit code `0`.

- [ ] **Step 4: Review the final diff against the approved design**

Run: `git diff --stat production/V3/3.0.78...HEAD` and `git diff production/V3/3.0.78...HEAD -- v2-api/app/api/routes/local_test.py v2-api/tests/test_api.py docs/superpowers`

Expected: only the design, plan, route guard, and focused tests are changed.

- [ ] **Step 5: Commit any verification-only corrections**

If verification required a source or test correction, stage only those files and commit with a message that describes the correction. If no files changed, do not create an empty commit.
