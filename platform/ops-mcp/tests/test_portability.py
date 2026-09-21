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
REGISTRY_INJECTION_FENCE = re.compile(
    r"<!-- blue-data-ops-mcp-test: registry-injection -->\n"
    r"```python\n(?P<source>.*?)\n```",
    re.DOTALL,
)


def test_distribution_metadata_and_public_surface() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["name"] == "blue-data-ops-mcp"
    assert project["version"] == "1.0.0"
    assert project["version"] == blue_data_ops_mcp.__version__
    assert project["requires-python"] == ">=3.11"
    assert set(project["dependencies"]) == {
        "blue-data-ops==3.1.0",
        "mcp==1.27.2",
        "pydantic>=2.11,<3",
    }
    assert project["scripts"] == {"blue-data-ops-mcp": "blue_data_ops_mcp.server:main"}
    assert blue_data_ops_mcp.__all__ == [
        "ACTIVE_OPERATOR_IDS",
        "TOOL_PREFIX",
        "V2_OPERATOR_IDS",
        "__version__",
        "create_server",
        "main",
        "serve",
    ]
    assert blue_data_ops_mcp.ACTIVE_OPERATOR_IDS == ACTIVE_OPERATOR_IDS
    assert blue_data_ops_mcp.V2_OPERATOR_IDS == V2_OPERATOR_IDS
    assert blue_data_ops_mcp.TOOL_PREFIX == "ops_"
    assert len(ACTIVE_OPERATOR_IDS) == len(V2_OPERATOR_IDS) == 33


def test_console_entry_point_resolves_to_a_callable() -> None:
    from blue_data_ops_mcp.server import main

    assert blue_data_ops_mcp.main is main
    assert callable(main)


def test_test_and_type_paths_reach_the_sibling_library() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]
    # Without the sibling on both paths the suite cannot import core from a source checkout
    # and every library symbol reads as Unknown under strict type checking.
    assert config["pytest"]["ini_options"]["pythonpath"] == ["src", "../../lib/src"]
    assert config["pyright"]["extraPaths"] == ["src", "../../lib/src"]
    assert (ROOT.parents[1] / "lib" / "src" / "blue_data_ops").is_dir()

    # And that the path actually wins: an environment carrying an older release of either
    # distribution in site-packages otherwise runs the suite against the wrong catalog.
    import blue_data_ops

    assert Path(blue_data_ops.__file__).resolve().is_relative_to(CORE_SRC.resolve())
    assert Path(blue_data_ops_mcp.__file__).resolve().is_relative_to((ROOT / "src").resolve())


def test_component_scripts_are_present_and_executable() -> None:
    for name in ("build.sh", "install.sh", "publish.sh"):
        script = ROOT / "scripts" / name
        assert script.is_file(), name
        assert script.stat().st_mode & 0o111 == 0o111, name
        assert script.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash")


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
    assert "blue-data-ops-mcp==1.0.0" in current
    assert "blue-data-ops[ml,vector,llm]==3.1.0" in current
    assert "ACTIVE_OPERATOR_IDS" in current
    assert "V2_OPERATOR_IDS" in current
    assert "It contains the 33 retained v2 exact IDs" in current
    assert re.search(r"33.{0,80}primary", lowered, flags=re.DOTALL)
    assert re.search(r"(?:no|zero).{0,60}companions", lowered, flags=re.DOTALL)
    assert "supported raw package cards" in current
    assert "retained `@2.0.0` cards" in current
    assert "active `@3.0.0` cards" in current
    assert "Raw cards have empty `tags` and `when_to_invoke`" in current
    assert "does not change planner eligibility" in current
    assert "does not authorize a write" in current
    assert "MCP has no server-side tag query" in current
    assert "ops_" in current
    assert "Operator resources remain available through `OperatorSkillLoader`" in current
    assert "Table and natural-language rendering are CLI features." in current
    assert "freezes `operator_ids` at construction" in current
    assert "OPENAI_API_KEY" in current
    # Core reads two names of its own now, and they are what makes dispatch the
    # deployment's rather than a caller's. Pin both, so the README cannot quietly go
    # back to claiming the package reads nothing.
    assert "`BLUE_DATA_LLM_PROVIDER`" in current
    assert "`BLUE_DATA_LLM_ALLOWED_MODELS`" in current
    assert "blue-data-ops-mcp\n```" in current
    assert '"url": "http://127.0.0.1:8000/mcp"' in current
    assert "The rest of the Blue Data family speaks stdio" in current
    assert "python -c 'from blue_data_ops_mcp import serve; serve()'" not in current
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


def test_readme_registry_injection_fence_executes() -> None:
    """The README's account of what a registry key does is checked against core.

    Core reads `data_registry` only as a live object, so the claim that the wire needs the
    two naming keys is a fact about `resolve_registry` rather than about this adapter, and
    it is the kind of fact that goes stale without anything failing.
    """
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    matches = list(REGISTRY_INJECTION_FENCE.finditer(readme))
    assert len(matches) == 1
    exec(compile(matches[0].group("source"), "<mcp-registry-injection-fence>", "exec"), {})


def test_the_wire_advertises_only_the_registry_keys_json_can_carry() -> None:
    """A client reads this description and sends what it names.

    `data_registry` named a key core reads only as a Python object, so a client that
    followed the description sent a string or an object, it was ignored, and the tool
    returned its contained empty result with nothing said about why.
    """
    published = schema_module.PROPERTIES_DESCRIPTION
    assert "`platform.name` together with `data_registry.name`" in published
    # The naming key contains the bare one as a substring, so it is taken out first.
    assert "data_registry" not in published.replace("data_registry.name", "")


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
    assert len(tools) == 33
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
                "assert len(m.ACTIVE_OPERATOR_IDS) == 33; "
                "assert len(m.V2_OPERATOR_IDS) == 33"
            ),
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
