"""Shared HTTP policy for the two FastMCP app builders."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable
from importlib import import_module
from typing import Any, Protocol, cast

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class _SharedHelpers(Protocol):
    def env_flag(self, name: str) -> bool: ...

    def resolve_bind(self, prefix: str, default_port: int) -> tuple[str, int]: ...

    def make_api_key_guard(
        self, prefix: str, open_paths: Iterable[str]
    ) -> Callable[[Request], None]: ...

    def make_csrf_guard(self, open_paths: Iterable[str]) -> Callable[[Request], None]: ...


try:
    # blue-data does not publish typing metadata for these helpers.
    _helpers = cast(_SharedHelpers, import_module("blue_data.server"))
except ImportError as exc:
    raise ImportError(
        "MCP HTTP requires blue-data 1.0 or later with the server extra. "
        'Install "blue-data[server]>=1.0.0" from the authorized source or index.'
    ) from exc

PREFIX = "BLUE_DATA_OPS_MCP"
_SDK_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_LOG = logging.getLogger(__name__)


def _validate_bind(host: Any, port: Any) -> tuple[str, int]:
    if not isinstance(host, str) or not host.strip():
        raise ValueError(f"{PREFIX}_HOST or explicit host must be a nonempty string")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError(f"{PREFIX}_PORT or explicit port must be an integer from 1 to 65535")
    return host.strip(), port


def resolve_http_bind(host: str | None, port: int | None) -> tuple[str, int]:
    if port is None:
        try:
            env_host, port = _helpers.resolve_bind(PREFIX, default_port=8010)
        except (TypeError, ValueError):
            raise ValueError(f"{PREFIX}_PORT must be integer text from 1 to 65535") from None
        if host is None:
            host = env_host
    elif host is None:
        # An explicit port must not parse an overridden environment port.
        host = os.environ.get(f"{PREFIX}_HOST", "127.0.0.1")
    return _validate_bind(host, port)


class _HTTPGuard:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.auth = _helpers.make_api_key_guard(PREFIX, open_paths=())
        self.csrf = _helpers.make_csrf_guard(open_paths=())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            raise RuntimeError("Unsupported MCP ASGI scope type")
        try:
            request = Request(scope)
            self.auth(request)
            self.csrf(request)
        except HTTPException as exc:
            response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class GuardedFastMCP(FastMCP[Any]):
    def __init__(self, name: str, **settings: Any) -> None:
        super().__init__(name, **settings)
        self._construction_host = self.settings.host

    def _guard_app(self, app: Starlette) -> Starlette:
        app.add_middleware(_HTTPGuard)
        return app

    def _check_http_settings(self) -> None:
        host, _ = _validate_bind(self.settings.host, self.settings.port)
        if host != self._construction_host or self.settings.host != self._construction_host:
            raise ValueError("HTTP host changed after construction; create a new server instead")
        if (
            host not in _SDK_LOOPBACK_HOSTS
            and not os.environ.get(f"{PREFIX}_KEY")
            and _helpers.env_flag(f"{PREFIX}_AUTH_DISABLED")
        ):
            _LOG.warning(
                "%s_AUTH_DISABLED permits unauthenticated HTTP on a host outside the SDK's "
                "protected loopback forms. "
                "Reachable callers can run tools using deployment provider configuration "
                "and incur costs. Set %s_KEY and restrict network exposure.",
                PREFIX,
                PREFIX,
            )

    def streamable_http_app(self) -> Starlette:
        self._check_http_settings()
        return self._guard_app(super().streamable_http_app())

    def sse_app(self, mount_path: str | None = None) -> Starlette:
        self._check_http_settings()
        return self._guard_app(super().sse_app(mount_path))
