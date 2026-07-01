from starlette.datastructures import MutableHeaders


class SecurityHeadersMiddleware:
    def __init__(self, app, *, frame_ancestors: str = "'self'") -> None:
        self.app = app
        self.frame_ancestors = frame_ancestors

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                defaults = {
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
                for name, value in defaults.items():
                    if name not in headers:
                        headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_security_headers)
