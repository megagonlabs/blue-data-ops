from __future__ import annotations

import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import blue_data_ops_mcp
from blue_data_ops_mcp.registration import (
    DEPRECATION_SENTENCE,
    REFINE_DEPRECATION_SENTENCE,
    REFINE_DESCRIPTION_PREFIX,
    REFINE_SUFFIX,
    V2_OPERATOR_IDS,
    freeze_deployment,
)
from blue_data_ops_mcp.server import create_server

ROOT = Path(__file__).parents[1]
DEPRECATED_PRIMARY_NAMES = (
    "multipart_query",
    "nl2query_router",
    "plan_discover",
    "query_breakdown",
)


def test_distribution_metadata_and_public_surface() -> None:
    metadata = importlib.metadata.metadata("blue-data-ops-mcp")
    requirements = metadata.get_all("Requires-Dist") or []
    assert metadata["Name"] == "blue-data-ops-mcp"
    assert metadata["Version"] == "0.11.0"
    assert metadata["Requires-Python"] == ">=3.11"
    runtime = {requirement for requirement in requirements if "extra ==" not in requirement}
    # 0.11.0 tracks core 2.9.0. The operator cards this adapter serves are still @2.0.0;
    # only the core distribution version moved.
    assert runtime == {
        "blue-data-ops==2.9.0",
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


def _readme() -> str:
    return (ROOT / "README.md").read_text(encoding="utf-8")


def test_readme_quotes_the_two_lifecycle_sentences_verbatim() -> None:
    readme = _readme()

    assert DEPRECATION_SENTENCE in readme
    assert REFINE_DEPRECATION_SENTENCE in readme


async def test_readme_describes_where_each_kind_carries_its_lifecycle_sentence() -> None:
    """The two kinds place the sentence differently, so the README has to say which is which.

    A deprecated primary opens with its sentence. A companion opens with its ordinary refinement
    note and carries its sentence second, ahead of the invocation guidance and card description.
    """

    readme = _readme()
    tools = {tool.name: tool for tool in await create_server().list_tools()}
    companion_opening = f"{REFINE_DESCRIPTION_PREFIX}\n\n{REFINE_DEPRECATION_SENTENCE}\n\n"

    for name in DEPRECATED_PRIMARY_NAMES:
        primary = tools[name].description or ""
        companion = tools[f"{name}{REFINE_SUFFIX}"].description or ""

        assert primary.startswith(f"{DEPRECATION_SENTENCE}\n\n")
        assert companion.startswith(companion_opening)
        # second, not first: the companion sentence begins with the primary one, so a companion
        # that opened with the lifecycle text would still satisfy a bare containment check
        assert not companion.startswith(DEPRECATION_SENTENCE)
        # invocation guidance and the card description still follow it
        assert companion.removeprefix(companion_opening).strip()

    assert REFINE_DESCRIPTION_PREFIX in readme
    assert readme.index(REFINE_DESCRIPTION_PREFIX) < readme.index(REFINE_DEPRECATION_SENTENCE)


async def test_readme_names_exactly_the_annotated_tools() -> None:
    readme = _readme()
    tools = await create_server().list_tools()
    annotated = {tool.name for tool in tools if (tool.meta or {}).get("deprecated") is True}

    assert len(tools) == 40
    assert [tool.name for tool in tools] == [
        operator_id.partition("@")[0] for operator_id in V2_OPERATOR_IDS
    ] + [f"{name}{REFINE_SUFFIX}" for name in DEPRECATED_PRIMARY_NAMES]
    assert len(annotated) == 8
    assert annotated == {
        "multipart_query",
        "nl2query_router",
        "plan_discover",
        "query_breakdown",
        "multipart_query__refine",
        "nl2query_router__refine",
        "plan_discover__refine",
        "query_breakdown__refine",
    }
    # a retained tool carries no key at all, which `.get(...) is True` above cannot observe
    for tool in tools:
        if tool.name not in annotated:
            assert "deprecated" not in (tool.meta or {})
    assert "eight of its 40 bindings" in readme
    assert "The other 32 tools are untouched." in readme
    # the README tells readers to test for the key's presence, not for a false value
    assert "`deprecated: false`" in readme
    assert '"deprecated": false' not in readme


def test_readme_states_the_current_versions_and_the_exact_core_pin() -> None:
    readme = _readme()

    assert 'version("blue-data-ops-mcp") == "0.11.0"' in readme
    assert "blue-data-ops-mcp 0.11.0" in readme
    assert "blue-data-ops-mcp==0.11.0" in readme
    assert "blue-data-ops[ml,vector,llm]==2.9.0" in readme
    assert "`blue-data-ops==2.9.0`" in readme
    # the 0.9.0 migration section and its install pair are history and stay as written
    assert readme.count("blue-data-ops-mcp==0.9.0") == 1
    assert readme.count("blue-data-ops[ml,vector,llm]==2.7.0") == 1
    assert "## Migrating from 0.9.0" in readme
    assert readme.index("## Migrating from 0.9.0") < readme.index("## Migrating from 0.8.0")


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
