from __future__ import annotations

import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import blue_data_ops_mcp
from blue_data_ops_mcp.registration import V2_OPERATOR_IDS, freeze_deployment
from blue_data_ops_mcp.server import create_server

ROOT = Path(__file__).parents[1]


def test_distribution_metadata_and_public_surface() -> None:
    metadata = importlib.metadata.metadata("blue-data-ops-mcp")
    requirements = metadata.get_all("Requires-Dist") or []
    assert metadata["Name"] == "blue-data-ops-mcp"
    assert metadata["Version"] == "0.8.0"
    assert metadata["Requires-Python"] == ">=3.11"
    runtime = {requirement for requirement in requirements if "extra ==" not in requirement}
    # 0.8.0 tracks core 2.6.0. The operator cards this adapter serves are still @2.0.0;
    # only the core distribution version moved.
    assert runtime == {
        "blue-data-ops==2.6.0",
        "mcp==1.27.2",
        "pydantic<3,>=2.11",
    }
    assert not any(
        forbidden in requirement.lower()
        for forbidden in ("uvicorn", "anyio", "mcp[cli]", "registry-mcp")
        for requirement in runtime
    )
    assert blue_data_ops_mcp.__all__ == ["V2_OPERATOR_IDS", "create_server", "serve"]
    assert blue_data_ops_mcp.V2_OPERATOR_IDS == V2_OPERATOR_IDS
    assert len(V2_OPERATOR_IDS) == 36
    assert all(operator_id.endswith("@2.0.0") for operator_id in V2_OPERATOR_IDS)


def test_source_tree_has_no_blue_import() -> None:
    source = "\n".join(path.read_text() for path in (ROOT / "src").rglob("*.py"))
    assert "from blue." not in source
    assert "import blue." not in source


def test_pipeline_executor_stays_outside_the_mcp_adapter() -> None:
    from blue_data_ops.plan import DataPipeline, PipelineExecutor

    for forbidden in ("run", "execute", "traverse"):
        assert not hasattr(DataPipeline, forbidden)
    assert callable(PipelineExecutor)
    source = "\n".join(path.read_text() for path in (ROOT / "src").rglob("*.py"))
    assert "PipelineExecutor" not in source


def test_server_defaults_are_stateful_loopback_streamable_http() -> None:
    server = create_server(operator_ids=())
    assert server.settings.host == "127.0.0.1"
    assert server.settings.port == 8000
    assert server.settings.streamable_http_path == "/mcp"
    assert server.settings.json_response is False
    assert server.settings.stateless_http is False


def test_serve_selects_streamable_http_without_opening_listener() -> None:
    from blue_data_ops_mcp import server as server_module

    calls: list[dict[str, Any]] = []

    class ServerDouble:
        def run(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    def create_server_double(**kwargs: Any) -> ServerDouble:
        del kwargs
        return ServerDouble()

    original = server_module.create_server
    server_module.create_server = create_server_double  # type: ignore[assignment]
    try:
        server_module.serve(operator_ids=())
    finally:
        server_module.create_server = original  # type: ignore[assignment]
    assert calls == [{"transport": "streamable-http"}]


def test_every_default_binding_uses_the_exact_resolved_instance() -> None:
    from blue_data_ops.operators import versioned_registry

    registry = versioned_registry()
    snapshot = freeze_deployment(registry)
    for binding in snapshot:
        assert binding.operator is registry.resolve(binding.card.operator_id)


async def test_every_tool_meta_reports_operator_version_2_0_0() -> None:
    tools = await create_server().list_tools()
    assert len(tools) == 40
    for tool in tools:
        assert (tool.meta or {})["version"] == "2.0.0"


def test_source_import_smoke_in_subprocess() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), env.get("PYTHONPATH", "")]).rstrip(
        os.pathsep
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import blue_data_ops_mcp; assert len(blue_data_ops_mcp.V2_OPERATOR_IDS) == 36",
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
