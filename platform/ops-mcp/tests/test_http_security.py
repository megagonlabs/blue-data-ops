from __future__ import annotations

import asyncio
import importlib
import json
import logging
import runpy
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocket

from blue_data_ops_mcp import server as server_module
from blue_data_ops_mcp.server import create_server

PREFIX = "BLUE_DATA_OPS_MCP"
KEY = "http-fixture"
AUTH = {"X-API-Key": KEY}
BASE = "http://127.0.0.1:8010"


@pytest.fixture(autouse=True)
def clean_http_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for suffix in ("KEY", "AUTH_DISABLED", "HOST", "PORT"):
        monkeypatch.delenv(f"{PREFIX}_{suffix}", raising=False)


def app_with_route(kind: str, **settings: Any) -> tuple[Any, Any]:
    server = create_server(operator_ids=(), **settings)

    @server.custom_route("/health", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def health(request: Any) -> JSONResponse:
        return JSONResponse({"ok": True})

    app = server.sse_app() if kind == "sse" else server.streamable_http_app()
    return server, app


async def request(app: Any, path: str = "/health", **kwargs: Any) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app, raise_app_exceptions=kwargs.pop("raise_app_exceptions", True)
        ),
        base_url=BASE,
    ) as client:
        return await client.request(kwargs.pop("method", "GET"), path, **kwargs)


@pytest.mark.parametrize("kind", ["http", "sse"])
async def test_auth_every_path_and_per_request_env(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app = app_with_route(kind)
    for path in ("/health", "/docs", "/unknown", "/sse", "/messages/", "/mcp"):
        assert (await request(app, path, method="OPTIONS")).status_code == 401
    monkeypatch.setenv(f"{PREFIX}_KEY", KEY)
    assert (await request(app)).status_code == 401
    assert (await request(app, headers={"X-API-Key": "wrong"})).status_code == 401
    assert (await request(app, headers=AUTH)).json() == {"ok": True}
    assert (await request(app, headers={"authorization": f"bEaReR {KEY}"})).status_code == 200
    monkeypatch.setenv(f"{PREFIX}_KEY", "changed-fixture")
    assert (await request(app, headers=AUTH)).status_code == 401


@pytest.mark.parametrize("kind", ["http", "sse"])
@pytest.mark.parametrize(
    "flag,allowed",
    [
        ("1", True),
        ("TRUE", True),
        ("yes", True),
        ("false", False),
        ("on", False),
        (" true ", False),
    ],
)
async def test_shared_opt_out(
    kind: str, flag: str, allowed: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(f"{PREFIX}_AUTH_DISABLED", flag)
    _, app = app_with_route(kind)
    assert (await request(app)).status_code == (200 if allowed else 401)
    monkeypatch.setenv(f"{PREFIX}_KEY", KEY)
    assert (await request(app)).status_code == 401
    assert (await request(app, headers=AUTH)).status_code == 200


@pytest.mark.parametrize("kind", ["http", "sse"])
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize(
    "content_type",
    [
        "application/x-www-form-urlencoded",
        "Multipart/Form-Data; boundary=x",
        "TEXT/PLAIN; charset=utf-8",
    ],
)
async def test_auth_before_csrf(
    kind: str, method: str, content_type: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(f"{PREFIX}_KEY", KEY)
    _, app = app_with_route(kind)
    headers = {"Content-Type": content_type}
    assert (await request(app, method=method, headers=headers, content="x")).status_code == 401
    headers.update(AUTH)
    assert (await request(app, method=method, headers=headers, content="x")).status_code == 415
    for safe in ("application/json", "application/octet-stream", ""):
        assert (
            await request(app, method=method, headers={**AUTH, "Content-Type": safe})
        ).status_code == 200


def test_bind_precedence_and_helper_integer_syntax(monkeypatch: pytest.MonkeyPatch) -> None:
    defaults = create_server(operator_ids=()).settings
    assert (defaults.host, defaults.port) == ("127.0.0.1", 8010)
    monkeypatch.setenv(f"{PREFIX}_HOST", " localhost ")
    monkeypatch.setenv(f"{PREFIX}_PORT", "8_012")
    settings = create_server(operator_ids=()).settings
    assert (settings.host, settings.port) == ("localhost", 8012)
    settings = create_server(operator_ids=(), host="::1").settings
    assert (settings.host, settings.port) == ("::1", 8012)
    monkeypatch.setenv(f"{PREFIX}_PORT", "bad")
    assert create_server(operator_ids=(), port=9001).settings.port == 9001
    monkeypatch.setenv(f"{PREFIX}_HOST", " ")
    assert create_server(operator_ids=(), host="0.0.0.0", port=9002).settings.host == "0.0.0.0"
    for text in (" +8010 ", "８０１０"):
        monkeypatch.setenv(f"{PREFIX}_PORT", text)
        assert create_server(operator_ids=(), host="localhost").settings.port == 8010


@pytest.mark.parametrize("value", ["", " ", 1, False])
def test_invalid_explicit_host(value: Any) -> None:
    with pytest.raises(ValueError, match="HOST"):
        create_server(operator_ids=(), host=value)


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_environment_host_uses_loopback_default(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(f"{PREFIX}_HOST", value)
    settings = create_server(operator_ids=()).settings
    assert (settings.host, settings.port) == ("127.0.0.1", 8010)


@pytest.mark.parametrize("value", [0, -1, 65536, True, False, "8010", 8010.0])
def test_invalid_explicit_port(value: Any) -> None:
    with pytest.raises(ValueError, match="PORT"):
        create_server(operator_ids=(), port=value)


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_environment_port_uses_default(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(f"{PREFIX}_PORT", value)
    settings = create_server(operator_ids=()).settings
    assert (settings.host, settings.port) == ("127.0.0.1", 8010)


@pytest.mark.parametrize("value", ["bad", "0", "-1", "65536", "1.2"])
def test_invalid_environment_port(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(f"{PREFIX}_PORT", value)
    with pytest.raises(ValueError, match="PORT") as error:
        create_server(operator_ids=())
    assert value not in str(error.value) if value == "bad" else True


@pytest.mark.parametrize("kind", ["http", "sse"])
def test_refuse_edited_host_or_invalid_port(kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    server = create_server(operator_ids=())
    builder = server.sse_app if kind == "sse" else server.streamable_http_app
    server.settings.host = "0.0.0.0"
    with pytest.raises(ValueError, match="changed after construction"):
        builder()
    server.settings.host = "127.0.0.1"
    server.settings.port = 0
    with pytest.raises(ValueError, match="PORT"):
        builder()


@pytest.mark.parametrize(
    "host,protected",
    [
        ("127.0.0.1", True),
        ("localhost", True),
        ("::1", True),
        ("127.0.0.2", False),
        ("0.0.0.0", False),
        ("example.invalid", False),
    ],
)
def test_actual_sdk_protection_scope(host: str, protected: bool) -> None:
    settings = create_server(operator_ids=(), host=host).settings.transport_security
    assert bool(settings and settings.enable_dns_rebinding_protection) is protected
    assert settings == FastMCP("sdk-reference", host=host).settings.transport_security


@pytest.mark.parametrize("kind", ["http", "sse"])
async def test_nonloopback_opt_out_warns_and_key_wins(
    kind: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(f"{PREFIX}_AUTH_DISABLED", "true")
    with caplog.at_level(logging.WARNING):
        _, app = app_with_route(kind, host="0.0.0.0")
    assert "incur costs" in caplog.text
    assert (await request(app)).status_code == 200
    caplog.clear()
    monkeypatch.setenv(f"{PREFIX}_KEY", KEY)
    with caplog.at_level(logging.WARNING):
        _, app = app_with_route(kind, host="0.0.0.0")
    assert "unauthenticated" not in caplog.text
    assert KEY not in caplog.text
    assert (await request(app)).status_code == 401


@pytest.mark.parametrize("kind", ["http", "sse"])
async def test_websocket_unknown_scope_and_guard_layers(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(f"{PREFIX}_AUTH_DISABLED", "true")
    server, app = app_with_route(kind)
    reached: list[bool] = []

    async def websocket(ws: WebSocket) -> None:
        reached.append(True)
        await ws.accept()

    app.router.routes.append(WebSocketRoute("/socket", websocket))
    events: list[dict[str, Any]] = []

    async def receive() -> Any:
        return {"type": "websocket.connect"}

    async def send(message: Any) -> None:
        events.append(message)

    await app({"type": "websocket", "path": "/socket", "headers": []}, receive, send)
    assert events == [{"type": "websocket.close", "code": 1008}]
    assert reached == []
    with pytest.raises(RuntimeError, match="Unsupported MCP ASGI scope"):
        await app({"type": "custom"}, receive, send)
    for built in (app, server.sse_app(), server.streamable_http_app()):
        assert sum(item.cls.__name__ == "_HTTPGuard" for item in built.user_middleware) == 1


@pytest.mark.parametrize("kind,path", [("http", "/health"), ("sse", "/sse")])
async def test_custom_mcp_path_and_rebinding(
    kind: str, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(f"{PREFIX}_KEY", KEY)
    server = create_server(operator_ids=(), path="/health")
    app = server.sse_app() if kind == "sse" else server.streamable_http_app()
    async with app.router.lifespan_context(app):
        assert (await request(app, path, method="POST")).status_code == 401
        for headers, status in (
            ({"host": "attacker.invalid"}, 421),
            ({"origin": "http://attacker.invalid"}, 403),
        ):
            response = await request(
                app,
                path,
                method="GET" if kind == "sse" else "POST",
                headers={**AUTH, **headers, "content-type": "application/json"},
                json={},
                raise_app_exceptions=False,
            )
            assert response.status_code == status


@pytest.mark.parametrize("transport", ["streamable-http", "sse"])
def test_sync_runners_capture_guarded_apps(transport: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(f"{PREFIX}_KEY", KEY)
    captured: list[tuple[str, int]] = []

    async def recording_serve(self: Any, *args: Any, **kwargs: Any) -> None:
        captured.append((self.config.host, self.config.port))
        assert (await request(self.config.app)).status_code == 401
        assert (await request(self.config.app, headers=AUTH)).status_code == 200

    monkeypatch.setattr(uvicorn.Server, "serve", recording_serve)
    server, _ = app_with_route("http", port=9012)
    server.run(transport=transport)
    assert captured == [("127.0.0.1", 9012)]


@pytest.mark.parametrize("kind", ["http", "sse"])
async def test_async_runners_capture_guarded_apps(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(f"{PREFIX}_KEY", KEY)
    captured: list[tuple[str, int]] = []

    async def recording_serve(self: Any, *args: Any, **kwargs: Any) -> None:
        captured.append((self.config.host, self.config.port))
        assert (await request(self.config.app)).status_code == 401
        assert (await request(self.config.app, headers=AUTH)).status_code == 200

    monkeypatch.setattr(uvicorn.Server, "serve", recording_serve)
    server, _ = app_with_route(kind, port=9013)
    if kind == "sse":
        await server.run_sse_async()
    else:
        await server.run_streamable_http_async()
    assert captured == [("127.0.0.1", 9013)]


def test_main_and_serve_use_guarded_apps(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[str, int]] = []

    async def recording_serve(self: Any, *args: Any, **kwargs: Any) -> None:
        captured.append((self.config.host, self.config.port))
        assert (await request(self.config.app, "/mcp")).status_code == 401

    monkeypatch.setattr(uvicorn.Server, "serve", recording_serve)
    server_module.serve(operator_ids=())
    server_module.main()
    assert captured == [("127.0.0.1", 8010)] * 2


def parse_sse(text: str) -> Any:
    return json.loads(next(line[6:] for line in text.splitlines() if line.startswith("data: ")))


async def streamable_protocol(app: Any) -> None:
    headers = {**AUTH, "accept": "application/json, text/event-stream"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url=BASE, headers=headers
    ) as client:
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "fixture", "version": "1"},
                },
            },
        )
        assert response.status_code == 200, response.text
        initialized = parse_sse(response.text)
        assert initialized["result"]["serverInfo"]["version"] == "1.0.0"
        client.headers["mcp-session-id"] = response.headers["mcp-session-id"]
        client.headers["mcp-protocol-version"] = initialized["result"]["protocolVersion"]
        assert (
            await client.post(
                "/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}
            )
        ).status_code == 202
        tools = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert parse_sse(tools.text)["result"]["tools"][0]["name"] == "ops_select"
        result = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "ops_select",
                    "arguments": {
                        "input_data": [[{"a": 5}]],
                        "attributes": {"operand_key": "a", "operand": ">", "operand_val": 1},
                    },
                },
            },
        )
        assert parse_sse(result.text)["result"]["structuredContent"]["output_data"] == [[{"a": 5}]]
        assert (await client.delete("/mcp")).status_code == 200
        assert (
            await client.post("/mcp", json={"jsonrpc": "2.0", "id": 4, "method": "tools/list"})
        ).status_code == 404


async def test_authenticated_protocol_and_direct_lifespan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(f"{PREFIX}_KEY", KEY)
    app = create_server(operator_ids=("select@2.0.0",)).streamable_http_app()
    async with app.router.lifespan_context(app):
        await streamable_protocol(app)


async def test_mounted_host_lifespan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(f"{PREFIX}_KEY", KEY)
    server = create_server(operator_ids=("select@2.0.0",))
    child = server.streamable_http_app()
    starts: list[bool] = []

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        starts.append(True)
        async with server.session_manager.run():
            yield

    host = FastAPI(lifespan=lifespan)
    host.mount("/ops", child)

    # A root-path adapter lets the same real protocol sequence address the mounted child.
    async def mounted(scope: Any, receive: Any, send: Any) -> None:
        scope = {**scope, "path": "/ops" + scope["path"], "raw_path": b"/ops" + scope["raw_path"]}
        await host(scope, receive, send)

    async with host.router.lifespan_context(host):
        assert (await request(host, "/ops/mcp")).status_code == 401
        await streamable_protocol(mounted)
    assert starts == [True]


async def test_sse_stream_message_handshake_and_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(f"{PREFIX}_KEY", KEY)
    app = create_server(operator_ids=("select@2.0.0",)).sse_app()
    incoming: asyncio.Queue[Any] = asyncio.Queue()
    outgoing: asyncio.Queue[Any] = asyncio.Queue()
    await incoming.put({"type": "http.request", "body": b"", "more_body": False})
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/sse",
        "raw_path": b"/sse",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"127.0.0.1:8010"), (b"x-api-key", KEY.encode())],
        "server": ("127.0.0.1", 8010),
        "client": ("127.0.0.1", 1),
    }
    task = asyncio.create_task(app(scope, incoming.get, outgoing.put))

    async def next_event() -> str:
        while True:
            message = await asyncio.wait_for(outgoing.get(), 3)
            if message["type"] == "http.response.body" and message.get("body"):
                return message["body"].decode()

    try:
        start = await asyncio.wait_for(outgoing.get(), 3)
        assert start["status"] == 200
        endpoint = next(
            line[6:] for line in (await next_event()).splitlines() if line.startswith("data: ")
        )
        endpoint = urlsplit(endpoint).path + "?" + urlsplit(endpoint).query
        assert (await request(app, endpoint, method="POST", json={})).status_code == 401

        async def post(payload: Any) -> None:
            response = await request(app, endpoint, method="POST", json=payload, headers=AUTH)
            assert response.status_code == 202, response.text

        await post(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "fixture", "version": "1"},
                },
            }
        )
        assert parse_sse(await next_event())["result"]["serverInfo"]["version"] == "1.0.0"
        await post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        await post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert parse_sse(await next_event())["result"]["tools"][0]["name"] == "ops_select"
        await post(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "ops_select",
                    "arguments": {
                        "input_data": [[{"a": 5}]],
                        "attributes": {"operand_key": "a", "operand": ">", "operand_val": 1},
                    },
                },
            }
        )
        assert parse_sse(await next_event())["result"]["structuredContent"]["output_data"] == [
            [{"a": 5}]
        ]
        await incoming.put({"type": "http.disconnect"})
        await asyncio.wait_for(task, 3)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("kind", ["http", "sse"])
async def test_sse_messages_rebinding_and_nonloopback_absence(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(f"{PREFIX}_KEY", KEY)
    for host, enabled in (("127.0.0.1", True), ("0.0.0.0", False)):
        server = create_server(operator_ids=(), host=host)
        app = server.sse_app() if kind == "sse" else server.streamable_http_app()
        path = "/messages/?session_id=00000000000000000000000000000000" if kind == "sse" else "/mcp"
        async with app.router.lifespan_context(app):
            for extra, status in (
                ({"host": "attacker.invalid"}, 421),
                ({"origin": "http://attacker.invalid"}, 403),
            ):
                response = await request(
                    app,
                    path,
                    method="POST",
                    headers={**AUTH, **extra, "content-type": "application/json"},
                    json={},
                )
                if enabled:
                    assert response.status_code == status
                else:
                    assert response.status_code not in (401, 403, 421)


def test_invalid_serve_never_configures_listener(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(f"{PREFIX}_PORT", "invalid")
    configured: list[bool] = []

    def config(*args: Any, **kwargs: Any) -> None:
        configured.append(True)

    monkeypatch.setattr(uvicorn, "Config", config)
    with pytest.raises(ValueError, match="PORT"):
        server_module.serve(operator_ids=())
    assert configured == []


def test_stdio_dispatch_without_http_key(monkeypatch: pytest.MonkeyPatch) -> None:
    server = create_server(operator_ids=("select@2.0.0",))
    called: list[list[str]] = []

    async def stdio() -> None:
        called.append([tool.name for tool in await server.list_tools()])

    monkeypatch.setattr(server, "run_stdio_async", stdio)
    server.run(transport="stdio")
    assert called == [["ops_select"]]


@pytest.mark.parametrize("initial,changed", [("127.0.0.1", "0.0.0.0"), ("0.0.0.0", "127.0.0.1")])
def test_host_changes_refused_in_both_directions(initial: str, changed: str) -> None:
    server = create_server(operator_ids=(), host=initial)
    server.settings.host = changed
    for builder in (server.streamable_http_app, server.sse_app):
        with pytest.raises(ValueError, match="changed after construction"):
            builder()


def test_missing_shared_helper_gives_installation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    original = importlib.import_module

    def missing(name: str, package: str | None = None) -> Any:
        if name == "blue_data.server":
            raise ModuleNotFoundError("synthetic missing helper")
        return original(name, package)

    monkeypatch.setattr(importlib, "import_module", missing)
    path = Path(server_module.__file__).with_name("_http.py")
    with pytest.raises(ImportError, match=r"blue-data\[server\]>=1.0.0"):
        runpy.run_path(str(path))
