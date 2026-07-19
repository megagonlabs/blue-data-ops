from __future__ import annotations

import importlib.metadata
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import blue_data_ops_mcp
from blue_data_ops_mcp.registration import DEFAULT_OPERATOR_IDS, freeze_deployment, make_handler
from blue_data_ops_mcp.server import create_server

ROOT = Path(__file__).parents[1]


def test_distribution_metadata_and_public_surface() -> None:
    metadata = importlib.metadata.metadata("blue-data-ops-mcp")
    requirements = metadata.get_all("Requires-Dist") or []
    assert metadata["Name"] == "blue-data-ops-mcp"
    assert metadata["Version"] == "0.1.0"
    assert metadata["Requires-Python"] == ">=3.10"
    runtime = {requirement for requirement in requirements if "extra ==" not in requirement}
    assert runtime == {
        "blue-data-ops==0.2.0",
        "mcp==1.27.2",
        "pydantic<3,>=2.11",
    }
    assert not any(
        forbidden in requirement.lower()
        for forbidden in ("uvicorn", "anyio", "mcp[cli]", "registry-mcp")
        for requirement in runtime
    )
    assert blue_data_ops_mcp.__all__ == ["DEFAULT_OPERATOR_IDS", "create_server", "serve"]
    assert blue_data_ops_mcp.DEFAULT_OPERATOR_IDS == DEFAULT_OPERATOR_IDS


def test_source_tree_has_no_blue_import_or_v2_surface() -> None:
    source = "\n".join(path.read_text() for path in (ROOT / "src").rglob("*.py"))
    assert "from blue." not in source
    assert "import blue." not in source
    for symbol in ("ExecMeta", "ErrorRecord", "ErrorCategory", "structuredContent", "refine("):
        assert symbol not in source


def test_server_defaults_are_stateful_loopback_streamable_http() -> None:
    server = create_server(operator_ids=())
    assert server.settings.host == "127.0.0.1"
    assert server.settings.port == 8000
    assert server.settings.streamable_http_path == "/mcp"
    assert server.settings.json_response is False
    assert server.settings.stateless_http is False


def test_serve_selects_streamable_http_without_opening_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from blue_data_ops_mcp import server as server_module

    calls: list[dict[str, Any]] = []

    class ServerDouble:
        def run(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    def create_server_double(**kwargs: Any) -> ServerDouble:
        del kwargs
        return ServerDouble()

    monkeypatch.setattr(server_module, "create_server", create_server_double)
    server_module.serve(operator_ids=())
    assert calls == [{"transport": "streamable-http"}]


def test_every_default_handler_closes_over_exact_resolved_instance() -> None:
    snapshot = freeze_deployment()
    assert len(snapshot) == len(DEFAULT_OPERATOR_IDS)
    for binding in snapshot:
        handler = make_handler(binding.operator)
        closure_values = tuple(cell.cell_contents for cell in handler.__closure__ or ())
        assert binding.operator in closure_values


def test_source_import_smoke_in_python_310_subprocess() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            ("import blue_data_ops_mcp; assert len(blue_data_ops_mcp.DEFAULT_OPERATOR_IDS) == 36"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
