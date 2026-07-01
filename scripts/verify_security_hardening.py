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
