"""Browser-facing hardening and the built single-page app.

In development Vite serves the UI on :5173 and proxies `/api`. In the container one process serves
both: the API under `/api` and the production build (`DWHCR_STATIC_DIR`) for every other path,
with deep links (e.g. `/analyses/7`) answered by `index.html`.
"""

from __future__ import annotations

from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: Same policy the organisation's nginx front end used for this app, plus framing and form limits.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; script-src 'self'; font-src 'self' data:; object-src 'none'; "
    "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)

SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


class SecurityHeadersMiddleware:
    """Adds the security headers to every HTTP response; API answers are never cached."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_api = str(scope.get("path", "")).startswith("/api/")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                extra = dict(SECURITY_HEADERS)
                if is_api:
                    extra["Cache-Control"] = "no-store"
                for name, value in extra.items():
                    if name.lower().encode() not in present:
                        headers.append((name.lower().encode(), value.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


class SpaStaticFiles(StaticFiles):
    """Static build with an `index.html` fallback for client-side routes (never for `/api`)."""

    async def get_response(self, path: str, scope: Scope):  # type: ignore[no-untyped-def]
        try:
            return await super().get_response(path, scope)
        except HTTPException as error:
            request_path = str(scope.get("path", ""))
            if error.status_code != 404 or request_path == "/api" or request_path.startswith("/api/"):
                raise
            return await super().get_response("index.html", scope)


def static_dir(value: str | None) -> Path | None:
    """The UI build directory when configured and built, else None (development)."""
    if not value:
        return None
    directory = Path(value)
    return directory if (directory / "index.html").is_file() else None
