from urllib.parse import urlparse

from starlette.types import ASGIApp, Receive, Scope, Send


class PublicURLMiddleware:
    """Rewrite the ASGI scope's scheme, server, and host header to match public_url.

    Without this, request.url_for() derives URLs from the incoming Host header,
    which breaks OGC API link generation when the app is accessed via a different
    hostname than what external clients should use (e.g. host.docker.internal in CI).
    """

    def __init__(self, app: ASGIApp, public_url: str) -> None:
        self.app = app
        parsed = urlparse(public_url)
        self._scheme = parsed.scheme or "http"
        self._host = parsed.hostname or "localhost"
        default_port = 443 if self._scheme == "https" else 80
        self._port = parsed.port or default_port
        host_header = self._host
        if self._port != default_port:
            host_header = f"{self._host}:{self._port}"
        self._host_header = host_header.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            scope = dict(scope)
            scope["scheme"] = self._scheme
            scope["server"] = (self._host, self._port)
            headers = [(k, v) for k, v in scope["headers"] if k.lower() != b"host"]
            headers.append((b"host", self._host_header))
            scope["headers"] = headers
        await self.app(scope, receive, send)
