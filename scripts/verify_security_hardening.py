import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def parse_python(path: str) -> ast.Module:
    source = read(path)
    return ast.parse(source, filename=path)


def fail(message: str) -> None:
    raise SystemExit(f"[FAIL] {message}")


def node_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def dotted_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def references_name(module: ast.AST, name: str) -> bool:
    return any(node_name(node) == name for node in ast.walk(module))


def get_keyword(call: ast.Call, keyword_name: str) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == keyword_name:
            return keyword.value
    return None


def is_true(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def is_direct_wildcard_origin(node: ast.AST | None) -> bool:
    return (
        isinstance(node, ast.List)
        and len(node.elts) == 1
        and isinstance(node.elts[0], ast.Constant)
        and node.elts[0].value == "*"
    )


def add_middleware_calls(module: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(module)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_middleware"
    ]


def installed_middlewares(module: ast.AST) -> set[str]:
    installed = set()
    for call in add_middleware_calls(module):
        if call.args:
            installed.add(node_name(call.args[0]))
    return installed


def cors_middleware_calls(module: ast.AST) -> list[ast.Call]:
    return [
        call
        for call in add_middleware_calls(module)
        if call.args and node_name(call.args[0]) == "CORSMiddleware"
    ]


def has_config_field(module: ast.AST, field_name: str) -> bool:
    return any(
        isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == field_name
        for node in ast.walk(module)
    )


def has_login_rate_limiter(module: ast.AST) -> bool:
    has_sliding_window = references_name(module, "SlidingWindowRateLimiter")
    has_login_limiter = references_name(module, "login_limiter")
    has_login_check = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "check"
        and dotted_name(node.func.value).endswith("login_limiter")
        for node in ast.walk(module)
    )
    return has_sliding_window and has_login_limiter and has_login_check


def main() -> int:
    main_py = parse_python("v2-api/app/main.py")
    config_py = parse_python("v2-api/app/core/config.py")
    auth_py = parse_python("v2-api/app/api/routes/auth.py")

    cors_calls = cors_middleware_calls(main_py)
    if any(is_direct_wildcard_origin(get_keyword(call, "allow_origins")) for call in cors_calls):
        fail("production CORS must not use wildcard origins")
    if any(is_true(get_keyword(call, "allow_credentials")) for call in cors_calls) and not references_name(
        main_py, "security_allowed_origins"
    ):
        fail("credentialed CORS must be tied to configured allowed origins")

    middlewares = installed_middlewares(main_py)
    if "SecurityHeadersMiddleware" not in middlewares:
        fail("security headers middleware must be installed")
    if "TrustedHostMiddleware" not in middlewares:
        fail("trusted host middleware must be installed for production")
    if "RequestSizeLimitMiddleware" not in middlewares:
        fail("request size limit middleware must be installed")
    if not has_login_rate_limiter(auth_py):
        fail("login route must use rate limiting")
    if not has_config_field(config_py, "MAX_UPLOAD_MB"):
        fail("upload size limit setting must exist")

    print("[OK] security hardening static checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
