# Website Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the production website against common external attacks without breaking the current construction, review, data-center, and admin workflows.

**Architecture:** Add a thin, explicit security layer around the existing FastAPI app and Vue client. Keep business logic unchanged, add regression gates for every protection, and release in small production-safe increments with backup and health checks.

**Tech Stack:** FastAPI, Starlette middleware, Pydantic settings, Vue 3, Pinia/localStorage auth, existing PowerShell release packaging, pytest, Node verifier scripts, Nginx/systemd production deployment.

---

## Current Findings From Code Graph

- `v2-api/app/main.py` already hides `/docs`, `/redoc`, and `/openapi.json` in production and protects API prefixes with Bearer JWT.
- `v2-api/app/core/security.py` already creates JWTs that expire at the next local midnight.
- `v2-web/src/api/services.ts` clears local auth and redirects to `/login` on `401`.
- `v2-api/app/main.py` currently uses `CORSMiddleware` with `allow_origins=["*"]` and `allow_credentials=True`.
- `v2-api/app/main.py` mounts `/static/uploads` and `/vue/assets` with `follow_symlink=True`.
- `v2-api/app/api/routes/local_test.py` contains multipart upload routes, photo proxy routes, and several large admin/data operations.
- `v2-api/app/services/account_store.py` stores login history and password hashes, but there is no visible login-rate limiter in the current code graph.

## File Structure

- Modify `v2-api/app/core/config.py`: add security settings for allowed origins, trusted hosts, rate limits, upload size limits, and strict static serving.
- Modify `v2-api/app/main.py`: add security headers, stricter CORS, trusted host checks, request size guard, safer static mounts, and production startup validation.
- Create `v2-api/app/core/security_middleware.py`: isolate reusable security middleware and keep `main.py` readable.
- Create `v2-api/app/core/rate_limit.py`: in-process sliding-window limiter for login, upload, and admin mutation endpoints.
- Modify `v2-api/app/api/routes/auth.py`: apply login limiter, remove demo credentials from production config, audit login failures.
- Modify `v2-api/app/api/routes/local_test.py`: enforce upload count, file size, MIME sniffing, and safe proxy URL allowlist.
- Modify `v2-web/src/api/services.ts`: keep 401 redirect behavior and add one 403/429 message path without hiding the actual server response.
- Create `scripts/verify_security_hardening.py`: backend static checks and API behavior checks.
- Create `scripts/verify_frontend_auth_expiry.js`: verify expired token cleanup and redirect behavior.
- Modify `scripts/build-client-release.ps1` and `scripts/verify-client-release.py`: include new security verifiers in the release package.
- Modify `ops/releases/V3.0.74.md`: record the security hardening release evidence.

---

## Task 1: Baseline Security Regression Gate

**Files:**
- Create: `scripts/verify_security_hardening.py`
- Modify: `scripts/verify-client-release.py`
- Modify: `scripts/build-client-release.ps1`

- [ ] **Step 1: Write the failing verifier**

Create `scripts/verify_security_hardening.py` with checks for the known gaps:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def fail(message: str) -> None:
    raise SystemExit(f"[FAIL] {message}")


def main() -> int:
    main_py = read("v2-api/app/main.py")
    config_py = read("v2-api/app/core/config.py")

    if 'allow_origins=["*"]' in main_py or "allow_origins=['*']" in main_py:
        fail("production CORS must not use wildcard origins")
    if "allow_credentials=True" in main_py and "security_allowed_origins" not in main_py:
        fail("credentialed CORS must be tied to configured allowed origins")
    if "SecurityHeadersMiddleware" not in main_py:
        fail("security headers middleware must be installed")
    if "TrustedHostMiddleware" not in main_py:
        fail("trusted host middleware must be installed for production")
    if "RequestSizeLimitMiddleware" not in main_py:
        fail("request size limit middleware must be installed")
    if "LoginRateLimiter" not in read("v2-api/app/api/routes/auth.py"):
        fail("login route must use rate limiting")
    if "MAX_UPLOAD_MB" not in config_py:
        fail("upload size limit setting must exist")

    print("[OK] security hardening static checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run it and confirm it fails**

Run:

```powershell
.venv\Scripts\python.exe scripts\verify_security_hardening.py
```

Expected:

```text
[FAIL] production CORS must not use wildcard origins
```

- [ ] **Step 3: Wire it into packaging**

Add this copy line to `scripts/build-client-release.ps1` near the other verifier copy lines:

```powershell
Copy-ReleaseItem "scripts\verify_security_hardening.py" "scripts\verify_security_hardening.py"
```

Add this required file to `scripts/verify-client-release.py`:

```python
"scripts/verify_security_hardening.py",
```

- [ ] **Step 4: Commit**

```powershell
git add scripts\verify_security_hardening.py scripts\build-client-release.ps1 scripts\verify-client-release.py
git commit -m "test: add security hardening release gate"
```

---

## Task 2: Production Security Settings

**Files:**
- Modify: `v2-api/app/core/config.py`
- Modify: `.env.example`
- Modify: `docs/production_operations.md`

- [ ] **Step 1: Add explicit settings**

In `v2-api/app/core/config.py`, add these fields to `Settings`:

```python
security_allowed_origins: str = Field(
    default="https://www.sgcc.online,https://sgcc.online",
    alias="SECURITY_ALLOWED_ORIGINS",
)
security_trusted_hosts: str = Field(
    default="www.sgcc.online,sgcc.online,127.0.0.1,localhost",
    alias="SECURITY_TRUSTED_HOSTS",
)
security_frame_ancestors: str = Field(default="'self'", alias="SECURITY_FRAME_ANCESTORS")
security_login_rate_limit_per_minute: int = Field(default=8, alias="SECURITY_LOGIN_RATE_LIMIT_PER_MINUTE")
security_upload_rate_limit_per_minute: int = Field(default=60, alias="SECURITY_UPLOAD_RATE_LIMIT_PER_MINUTE")
max_upload_mb: int = Field(default=20, alias="MAX_UPLOAD_MB")
max_upload_files_per_request: int = Field(default=8, alias="MAX_UPLOAD_FILES_PER_REQUEST")
photo_proxy_allowed_hosts: str = Field(default="", alias="PHOTO_PROXY_ALLOWED_HOSTS")
```

Add helper methods to the same class:

```python
def split_csv(self, value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]

@property
def allowed_origins(self) -> list[str]:
    return self.split_csv(self.security_allowed_origins)

@property
def trusted_hosts(self) -> list[str]:
    return self.split_csv(self.security_trusted_hosts)

@property
def photo_proxy_hosts(self) -> set[str]:
    return set(self.split_csv(self.photo_proxy_allowed_hosts))
```

- [ ] **Step 2: Update `.env.example`**

Add:

```dotenv
SECURITY_ALLOWED_ORIGINS=https://www.sgcc.online,https://sgcc.online
SECURITY_TRUSTED_HOSTS=www.sgcc.online,sgcc.online,127.0.0.1,localhost
SECURITY_FRAME_ANCESTORS='self'
SECURITY_LOGIN_RATE_LIMIT_PER_MINUTE=8
SECURITY_UPLOAD_RATE_LIMIT_PER_MINUTE=60
MAX_UPLOAD_MB=20
MAX_UPLOAD_FILES_PER_REQUEST=8
PHOTO_PROXY_ALLOWED_HOSTS=
```

- [ ] **Step 3: Run config import smoke**

Run:

```powershell
.venv\Scripts\python.exe -c "from app.core.config import settings; print(settings.allowed_origins); print(settings.trusted_hosts)" 
```

Expected: it prints configured origin and host lists without exception.

- [ ] **Step 4: Commit**

```powershell
git add v2-api\app\core\config.py .env.example docs\production_operations.md
git commit -m "chore: add production security settings"
```

---

## Task 3: Security Headers, CORS, and Trusted Hosts

**Files:**
- Create: `v2-api/app/core/security_middleware.py`
- Modify: `v2-api/app/main.py`
- Test: `v2-api/tests/test_api.py`

- [ ] **Step 1: Add tests**

Append to `v2-api/tests/test_api.py`:

```python
def test_security_headers_present(client):
    response = client.get("/login")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_cors_rejects_untrusted_origin(client):
    response = client.options(
        "/auth/login",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.headers.get("access-control-allow-origin") != "https://evil.example"
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```powershell
.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py -k "security_headers_present or cors_rejects_untrusted_origin" -q
```

Expected: both tests fail before implementation.

- [ ] **Step 3: Create middleware**

Create `v2-api/app/core/security_middleware.py`:

```python
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware:
    def __init__(self, app, *, frame_ancestors: str = "'self'") -> None:
        self.app = app
        self.frame_ancestors = frame_ancestors

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = Response(headers=dict(message.get("headers", []))).headers
                raw_headers = list(message.get("headers", []))
                additions = {
                    "x-content-type-options": "nosniff",
                    "referrer-policy": "strict-origin-when-cross-origin",
                    "x-frame-options": "SAMEORIGIN",
                    "permissions-policy": "camera=(self), microphone=(), geolocation=()",
                    "content-security-policy": (
                        "default-src 'self'; "
                        "img-src 'self' data: blob: https:; "
                        "script-src 'self'; "
                        "style-src 'self' 'unsafe-inline'; "
                        f"frame-ancestors {self.frame_ancestors}"
                    ),
                }
                existing = {key.decode("latin1").lower() for key, _ in raw_headers}
                for key, value in additions.items():
                    if key not in existing:
                        raw_headers.append((key.encode("latin1"), value.encode("latin1")))
                message["headers"] = raw_headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
```

- [ ] **Step 4: Install middleware and strict CORS**

In `v2-api/app/main.py`:

```python
from starlette.middleware.trustedhost import TrustedHostMiddleware
from app.core.security_middleware import SecurityHeadersMiddleware
```

Replace the CORS middleware config with:

```python
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins if production_mode else ["*"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Team-Id", "X-Request-Id"],
    )
    if production_mode:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    app.add_middleware(SecurityHeadersMiddleware, frame_ancestors=settings.security_frame_ancestors)
```

- [ ] **Step 5: Run tests**

Run:

```powershell
.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py -k "security_headers_present or cors_rejects_untrusted_origin" -q
.venv\Scripts\python.exe scripts\verify_security_hardening.py
```

Expected: both commands pass.

- [ ] **Step 6: Commit**

```powershell
git add v2-api\app\core\security_middleware.py v2-api\app\main.py v2-api\tests\test_api.py scripts\verify_security_hardening.py
git commit -m "feat: add production security headers and strict cors"
```

---

## Task 4: Login Rate Limit and Audit

**Files:**
- Create: `v2-api/app/core/rate_limit.py`
- Modify: `v2-api/app/api/routes/auth.py`
- Test: `v2-api/tests/test_api.py`

- [ ] **Step 1: Add test**

Append to `v2-api/tests/test_api.py`:

```python
def test_login_rate_limit_blocks_repeated_bad_passwords(client):
    for _ in range(8):
        client.post("/auth/login", json={"username": "admin", "password": "wrong"})
    response = client.post("/auth/login", json={"username": "admin", "password": "wrong"})
    assert response.status_code == 429
```

- [ ] **Step 2: Run test and confirm failure**

```powershell
.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py::test_login_rate_limit_blocks_repeated_bad_passwords -q
```

Expected: fails with status `401` instead of `429`.

- [ ] **Step 3: Implement limiter**

Create `v2-api/app/core/rate_limit.py`:

```python
from collections import defaultdict, deque
from dataclasses import dataclass
from time import monotonic


@dataclass
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int


class SlidingWindowRateLimiter:
    def __init__(self, *, limit: int, window_seconds: int = 60) -> None:
        self.limit = max(1, limit)
        self.window_seconds = max(1, window_seconds)
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> RateLimitResult:
        now = monotonic()
        events = self._events[key]
        while events and now - events[0] >= self.window_seconds:
            events.popleft()
        if len(events) >= self.limit:
            retry_after = int(self.window_seconds - (now - events[0])) + 1
            return RateLimitResult(False, retry_after)
        events.append(now)
        return RateLimitResult(True, 0)
```

- [ ] **Step 4: Apply to login**

In `v2-api/app/api/routes/auth.py`, add:

```python
from app.core.rate_limit import SlidingWindowRateLimiter

login_limiter = SlidingWindowRateLimiter(limit=settings.security_login_rate_limit_per_minute)


def login_rate_key(request: Request, username: str) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",", 1)[0].strip() or (request.client.host if request.client else "unknown")
    return f"{ip}:{username.strip().lower()}"
```

At the start of `login(...)`:

```python
    rate = login_limiter.check(login_rate_key(request, payload.username))
    if not rate.allowed:
        response = error_response(request, "rate_limited", "Too many login attempts.", status_code=429)
        response.headers["Retry-After"] = str(rate.retry_after_seconds)
        return response
```

- [ ] **Step 5: Run tests**

```powershell
.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py::test_login_rate_limit_blocks_repeated_bad_passwords -q
.venv\Scripts\python.exe scripts\verify_security_hardening.py
```

Expected: both pass.

- [ ] **Step 6: Commit**

```powershell
git add v2-api\app\core\rate_limit.py v2-api\app\api\routes\auth.py v2-api\tests\test_api.py scripts\verify_security_hardening.py
git commit -m "feat: rate limit login attempts"
```

---

## Task 5: Upload and Photo Proxy Hardening

**Files:**
- Modify: `v2-api/app/api/routes/local_test.py`
- Modify: `v2-api/app/core/security_middleware.py`
- Test: `v2-api/tests/test_api.py`

- [ ] **Step 1: Add request size middleware**

In `v2-api/app/core/security_middleware.py`, add:

```python
class RequestSizeLimitMiddleware:
    def __init__(self, app, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max(1, max_bytes)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > self.max_bytes:
            response = Response("Request body too large", status_code=413)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
```

Install it in `v2-api/app/main.py`:

```python
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=settings.max_upload_mb * 1024 * 1024)
```

- [ ] **Step 2: Add upload validation helpers**

In `v2-api/app/api/routes/local_test.py`, near upload handling:

```python
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


def validate_upload_file_name(filename: str) -> str:
    clean = Path(filename or "").name
    if not clean:
        raise HTTPException(status_code=400, detail="Upload filename is required")
    if clean.lower().endswith((".html", ".svg", ".js", ".exe", ".bat", ".cmd", ".ps1")):
        raise HTTPException(status_code=400, detail="Unsupported upload filename")
    return clean


def validate_upload_content_type(content_type: str) -> None:
    clean = (content_type or "").split(";", 1)[0].strip().lower()
    if clean not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Only jpeg, png, and webp images are allowed")
```

Use the helpers before saving every multipart file.

- [ ] **Step 3: Add SSRF guard to photo proxy**

For any route accepting external `url`, parse and restrict:

```python
def validate_proxy_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"https", "http"}:
        raise HTTPException(status_code=400, detail="Unsupported photo URL scheme")
    allowed_hosts = settings.photo_proxy_hosts
    if allowed_hosts and parsed.hostname not in allowed_hosts:
        raise HTTPException(status_code=400, detail="Photo URL host is not allowed")
    if parsed.hostname in {"localhost", "127.0.0.1", "0.0.0.0"}:
        raise HTTPException(status_code=400, detail="Local photo proxy URLs are not allowed")
    return raw_url
```

- [ ] **Step 4: Add tests**

Append:

```python
def test_upload_rejects_html_file(client, admin_auth_headers):
    response = client.post(
        "/local-test/upload-batch",
        headers=admin_auth_headers,
        files={"files": ("bad.html", b"<script>alert(1)</script>", "text/html")},
        data={"group_id": "missing"},
    )
    assert response.status_code in {400, 404}


def test_photo_proxy_rejects_localhost(client, admin_auth_headers):
    response = client.get(
        "/local-test/photo-proxy?url=http%3A%2F%2F127.0.0.1%3A8000%2Fhealth",
        headers=admin_auth_headers,
    )
    assert response.status_code == 400
```

- [ ] **Step 5: Run tests**

```powershell
.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py -k "upload_rejects_html_file or photo_proxy_rejects_localhost" -q
.venv\Scripts\python.exe scripts\verify_security_hardening.py
```

Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add v2-api\app\api\routes\local_test.py v2-api\app\core\security_middleware.py v2-api\app\main.py v2-api\tests\test_api.py
git commit -m "feat: harden upload and photo proxy surfaces"
```

---

## Task 6: Frontend Auth Expiry and Error Handling Gate

**Files:**
- Modify: `v2-web/src/api/services.ts`
- Modify: `v2-web/src/stores/auth.ts`
- Create: `scripts/verify_frontend_auth_expiry.js`
- Modify: `scripts/build-client-release.ps1`
- Modify: `scripts/verify-client-release.py`

- [ ] **Step 1: Create frontend verifier**

Create `scripts/verify_frontend_auth_expiry.js`:

```javascript
const fs = require('fs')

const services = fs.readFileSync('v2-web/src/api/services.ts', 'utf8')
const auth = fs.readFileSync('v2-web/src/stores/auth.ts', 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

if (!services.includes('response.status === 401')) fail('services.ts must handle 401')
if (!services.includes('redirectToLogin')) fail('services.ts must redirect to login')
if (!services.includes('response.status === 429')) fail('services.ts must handle 429 rate limit')
if (!auth.includes('isTokenExpired')) fail('auth store must reject expired tokens')
if (!auth.includes('clearStoredAuth')) fail('auth store must clear expired auth')

console.log('[OK] frontend auth expiry checks passed')
```

- [ ] **Step 2: Run and confirm failure on 429**

```powershell
node scripts\verify_frontend_auth_expiry.js
```

Expected: fails until `429` handling is added.

- [ ] **Step 3: Handle 429 without breaking 401 redirect**

In `v2-web/src/api/services.ts`, extend `handleUnauthorizedResponse`:

```ts
function handleUnauthorizedResponse(response: Response) {
  if (response.status === 401) {
    clearLocalAuthSession()
    redirectToLogin()
  }
  if (response.status === 429) {
    const retryAfter = response.headers.get('Retry-After')
    console.warn(`请求过于频繁${retryAfter ? `，请 ${retryAfter} 秒后再试` : ''}`)
  }
}
```

- [ ] **Step 4: Wire verifier into release package**

Add to `scripts/build-client-release.ps1`:

```powershell
Copy-ReleaseItem "scripts\verify_frontend_auth_expiry.js" "scripts\verify_frontend_auth_expiry.js"
```

Add to `scripts/verify-client-release.py` required files:

```python
"scripts/verify_frontend_auth_expiry.js",
```

- [ ] **Step 5: Run checks**

```powershell
node scripts\verify_frontend_auth_expiry.js
node scripts\verify_admin_release_notes.js
```

Expected: both pass.

- [ ] **Step 6: Commit**

```powershell
git add v2-web\src\api\services.ts v2-web\src\stores\auth.ts scripts\verify_frontend_auth_expiry.js scripts\build-client-release.ps1 scripts\verify-client-release.py
git commit -m "feat: verify frontend auth expiry handling"
```

---

## Task 7: Production Configuration Audit Script

**Files:**
- Create: `scripts/audit_production_security.py`
- Modify: `docs/sop/06-production-deploy-runbook.md`

- [ ] **Step 1: Add script**

Create `scripts/audit_production_security.py`:

```python
import os
from pathlib import Path


REQUIRED_SECRET_KEYS = ["JWT_SECRET", "ADMIN_PASSWORD", "DATABASE_URL"]
FORBIDDEN_VALUES = {"", "change-me", "admin", "password", "module_manager_password"}


def fail(message: str) -> None:
    raise SystemExit(f"[FAIL] {message}")


def main() -> int:
    env_path = Path(os.environ.get("SECURITY_ENV_PATH", ".env"))
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" not in line or line.strip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

    if os.environ.get("APP_ENV", "").lower() not in {"prod", "production"}:
        fail("APP_ENV must be production on the server")

    for key in REQUIRED_SECRET_KEYS:
        value = os.environ.get(key, "").strip()
        if value in FORBIDDEN_VALUES:
            fail(f"{key} is missing or uses a default value")
        if key.endswith("SECRET") and len(value) < 32:
            fail(f"{key} must be at least 32 characters")

    if os.environ.get("DEMO_AUTH_ENABLED", "").lower() == "true":
        fail("DEMO_AUTH_ENABLED must not be true in production")

    print("[OK] production security environment audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run locally against example and expect failure**

```powershell
$env:SECURITY_ENV_PATH='.env.example'; .venv\Scripts\python.exe scripts\audit_production_security.py
```

Expected: failure because `.env.example` is not production.

- [ ] **Step 3: Add runbook command**

Add to `docs/sop/06-production-deploy-runbook.md`:

```bash
cd /opt/module-manager-v2/current
SECURITY_ENV_PATH=/opt/module-manager-v2/.env /opt/module-manager-v2/venv/bin/python scripts/audit_production_security.py
```

- [ ] **Step 4: Commit**

```powershell
git add scripts\audit_production_security.py docs\sop\06-production-deploy-runbook.md
git commit -m "chore: add production security audit script"
```

---

## Task 8: Security Release, Backup, and Verification

**Files:**
- Modify: `v2-web/src/constants/releaseNotes.ts`
- Modify: version surfaces already used by the production release flow
- Create: `ops/releases/V3.0.74.md`

- [ ] **Step 1: Bump version**

For this security hardening release, use small release increment from current `3.0.73` to `3.0.74`.

Update:

```text
v2-web/src/constants/releaseNotes.ts
v2-web/package.json
v2-web/index.html
v2-api/app/main.py
v2-api/app/services/ops_status.py
v2-api/pyproject.toml
v2-api/tests/test_api.py
AGENTS.md
RELEASE_MANIFEST.md
```

- [ ] **Step 2: Add release note**

Add `V3.0.74` entry:

```ts
{
  version: 'V3.0.74',
  date: '2026-07-01',
  type: '安全加固',
  title: '网站安全防护加固',
  items: [
    '生产环境启用严格 CORS、可信 Host 和安全响应头。',
    '登录接口增加限流保护，降低撞库和暴力尝试风险。',
    '上传和照片代理入口增加文件类型、大小和本地地址访问保护。',
    '新增生产安全配置审计脚本和发布包安全校验。',
  ],
}
```

- [ ] **Step 3: Run full verification**

```powershell
.venv\Scripts\python.exe scripts\verify_security_hardening.py
node scripts\verify_frontend_auth_expiry.js
.venv\Scripts\python.exe scripts\verify_release_sop.py
.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py
node scripts\verify_admin_release_notes.js
powershell -ExecutionPolicy Bypass -File scripts\build-client-release.ps1 -Version 3.0.74 -SkipSmoke
.venv\Scripts\python.exe scripts\verify-client-release.py build\server-release\module-manager-v2-server-3.0.74.zip
```

Expected:

```text
security hardening static checks passed
frontend auth expiry checks passed
release SOP files and references are consistent
61+ backend tests passed
admin release notes checks passed
release zip verification passed
```

- [ ] **Step 4: Deploy with backup**

Use the existing production-safe flow:

```bash
scp -i C:\Users\Administrator\Downloads\XXXXXX.pem build/server-release/module-manager-v2-server-3.0.74.zip root@106.14.122.43:/tmp/
ssh -i C:\Users\Administrator\Downloads\XXXXXX.pem root@106.14.122.43
```

On server:

```bash
sha256sum /tmp/module-manager-v2-server-3.0.74.zip
bash /opt/module-manager-v2/current/scripts/backup_current_release.sh /opt/module-manager-v2 v3.0.74
bash /opt/module-manager-v2/current/scripts/deploy_release_zip.sh /opt/module-manager-v2 /tmp/module-manager-v2-server-3.0.74.zip
systemctl restart module-manager-v2
systemctl is-active module-manager-v2
cd /opt/module-manager-v2/current
SECURITY_ENV_PATH=/opt/module-manager-v2/.env /opt/module-manager-v2/venv/bin/python scripts/audit_production_security.py
/opt/module-manager-v2/venv/bin/python scripts/production_health_check.py --base-url http://127.0.0.1:8000 --expected-version 3.0.74
/opt/module-manager-v2/venv/bin/python scripts/production_health_check.py --base-url https://www.sgcc.online --expected-version 3.0.74 --skip-admin
bash /opt/module-manager-v2/current/scripts/cleanup_old_releases.sh /opt/module-manager-v2 5 --dry-run
bash /opt/module-manager-v2/current/scripts/cleanup_old_releases.sh /opt/module-manager-v2 5
```

- [ ] **Step 5: Record evidence**

Fill `ops/releases/V3.0.74.md` with:

```text
Package path
SHA256
Backup directory
Release directory
Security audit result
Health check result
Public page check result
Admin API check result
Release retention result
Rollback target
```

- [ ] **Step 6: Commit and push**

```powershell
git add -A
git commit -m "release: V3.0.74 security hardening"
git switch -c production/V3/3.0.74
git push -u origin production/V3/3.0.74
```

---

## Deployment Order

1. `V3.0.74-a`: settings, headers, CORS, trusted hosts, no business logic change.
2. `V3.0.74-b`: login limiter and frontend 429 handling.
3. `V3.0.74-c`: upload/proxy hardening.
4. Final `V3.0.74`: package, deploy, audit, and record evidence.

If any stage breaks construction upload or admin pages, roll back to `V3.0.73` release directory immediately and keep the failing stage out of the final branch.

## Acceptance Criteria

- Production docs remain hidden.
- `/login`, `/project-board`, `/claim-tasks`, `/task-hall`, `/global-search`, `/construction` still return 200.
- Expired login still redirects to `/login`.
- Wrong-password bursts return `429` after the configured threshold.
- Unknown origins do not receive credentialed CORS permission.
- Responses include `Content-Security-Policy`, `X-Content-Type-Options`, and `Referrer-Policy`.
- Uploads reject non-image files and oversized requests.
- Photo proxy rejects localhost and private machine URLs.
- Release package includes all new verifier scripts.
- Production deployment has backup, health checks, security audit, and release retention evidence.

## Self-Review

- Spec coverage: covers website hardening, login/session protection, upload safety, admin operations, production release and rollback.
- Placeholder scan: no `TBD`, `TODO`, or unspecified test commands remain.
- Type consistency: settings names are defined before middleware/routes reference them.
- Production safety: every risky change has a failing test first, a verifier, and a rollback point.
