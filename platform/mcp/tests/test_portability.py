from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

import blue_data_ops_mcp
import blue_data_ops_mcp.registration as registration
import blue_data_ops_mcp.schema as schema_module
from blue_data_ops_mcp.registration import (
    ACTIVE_OPERATOR_IDS,
    V2_OPERATOR_IDS,
    freeze_deployment,
)
from blue_data_ops_mcp.server import create_server

ROOT = Path(__file__).parents[1]
CORE_SRC = ROOT.parents[1] / "lib" / "src"
TAG_DISCOVERY_FENCE = re.compile(
    r"<!-- blue-data-ops-mcp-test: tag-discovery -->\n"
    r"```python\n(?P<source>.*?)\n```",
    re.DOTALL,
)


def test_distribution_metadata_and_public_surface() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["name"] == "blue-data-ops-mcp"
    assert project["version"] == "0.13.0"
    assert project["requires-python"] == ">=3.11"
    assert set(project["dependencies"]) == {
        "blue-data-ops==3.0.0",
        "mcp==1.27.2",
        "pydantic>=2.11,<3",
    }
    assert blue_data_ops_mcp.__all__ == [
        "ACTIVE_OPERATOR_IDS",
        "V2_OPERATOR_IDS",
        "create_server",
        "serve",
    ]
    assert blue_data_ops_mcp.ACTIVE_OPERATOR_IDS == ACTIVE_OPERATOR_IDS
    assert blue_data_ops_mcp.V2_OPERATOR_IDS == V2_OPERATOR_IDS
    assert len(ACTIVE_OPERATOR_IDS) == len(V2_OPERATOR_IDS) == 32


def test_active_ids_match_core_active_registry() -> None:
    from blue_data_ops import operators as operators_module
    from blue_data_ops.operators import OperatorRegistry

    active_registry = cast(
        Callable[[], OperatorRegistry], getattr(operators_module, "active_registry")
    )
    cards = active_registry().list_cards()
    assert tuple(card.operator_id for card in cards) == ACTIVE_OPERATOR_IDS


def test_readme_states_current_pair_and_primary_only_surface() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    current = readme.split("## Migrating from", maxsplit=1)[0]
    lowered = current.lower()
    assert "blue-data-ops-mcp==0.13.0" in current
    assert "blue-data-ops[ml,vector,llm]==3.0.0" in current
    assert "ACTIVE_OPERATOR_IDS" in current
    assert "V2_OPERATOR_IDS" in current
    assert re.search(r"36.{0,120}32", current, flags=re.DOTALL)
    assert re.search(r"32.{0,80}primary", lowered, flags=re.DOTALL)
    assert re.search(r"(?:no|zero).{0,60}companions", lowered, flags=re.DOTALL)
    assert "exact supported raw package card" in current
    assert "retained `@2.0.0` card" in current
    assert "active `@3.0.0` card" in current
    assert "observed adapter behavior, not an ordinary-selection promise" in current
    assert "`_meta.tags` is empty" in current
    assert "does not grant ordinary or OpenAI planning authority" in current
    assert "does not authorize a write" in current
    assert "MCP has no server-side tag query" in current
    assert "filter them client-side" in current
    for axis in ("domain", "flow", "accepts", "produces", "capability", "requires"):
        assert f"`{axis}-*`" in current


def test_readme_tag_discovery_fence_executes_with_a_firing_control() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    matches = list(TAG_DISCOVERY_FENCE.finditer(readme))
    assert len(matches) == 1
    source = matches[0].group("source")
    exec(compile(source, "<mcp-tag-discovery-readme-fence>", "exec"), {})

    mutated = source.replace("flow-transform", "flow-combine", 1)
    assert mutated != source
    with pytest.raises(AssertionError):
        exec(compile(mutated, "<mcp-tag-discovery-mutation>", "exec"), {})


def test_removed_refinement_surface_is_not_importable() -> None:
    for module, names in (
        (
            registration,
            (
                "REFINE_SUFFIX",
                "REFINE_DESCRIPTION_PREFIX",
                "REFINE_DEPRECATION_SENTENCE",
                "make_refine_handler",
                "refine_payload",
            ),
        ),
        (schema_module, ("RefineResult",)),
    ):
        for name in names:
            assert not hasattr(module, name)


def test_source_tree_has_no_blue_or_refinement_runtime_import() -> None:
    source = "\n".join(path.read_text() for path in (ROOT / "src").rglob("*.py"))
    assert "from blue." not in source
    assert "import blue." not in source
    assert "RefinableOperator" not in source
    assert "_deprecation.expected" not in source


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


def test_every_default_binding_uses_exact_resolved_instance() -> None:
    from blue_data_ops.operators import versioned_registry

    registry = versioned_registry()
    snapshot = freeze_deployment(registry)
    for binding in snapshot:
        assert binding.operator is registry.resolve(binding.card.operator_id)


async def test_every_tool_meta_reports_exact_selected_version() -> None:
    tools = await create_server().list_tools()
    assert len(tools) == 32
    assert [(tool.meta or {})["operator_id"] for tool in tools] == list(ACTIVE_OPERATOR_IDS)
    assert [(tool.meta or {})["version"] for tool in tools] == [
        operator_id.partition("@")[2] for operator_id in ACTIVE_OPERATOR_IDS
    ]


def test_source_import_smoke_in_subprocess() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "src"), str(CORE_SRC), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import blue_data_ops_mcp as m; "
                "assert len(m.ACTIVE_OPERATOR_IDS) == 32; "
                "assert len(m.V2_OPERATOR_IDS) == 32"
            ),
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
