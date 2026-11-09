"""Executable checks for shipped README examples and compatibility claims."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

blue_data = pytest.importorskip("blue_data")

from blue_data.registry.data_registry import (  # noqa: E402  # pyright: ignore[reportMissingTypeStubs]
    DataRegistry,
)
from blue_data.source.json.memory_json_source import (  # noqa: E402  # pyright: ignore[reportMissingTypeStubs]
    MemoryJSONSource,
)
from blue_data.source.sql.sqlite.sqlite_sql_source import (  # noqa: E402  # pyright: ignore[reportMissingTypeStubs]
    SQLiteDBSource,
)

from blue_data_ops import CreateDatabaseOperator, RegistrySeam, SelectOperator  # noqa: E402
from blue_data_ops.operator_skills import (  # noqa: E402
    OperatorSkillErrorCode,
    OperatorSkillLoader,
    OperatorSkillLoadError,
)
from blue_data_ops.operators import (  # noqa: E402
    DiscoveryError,
    OperatorEmbeddingIndex,
    ResolveError,
    active_registry,
    versioned_registry,
)
from blue_data_ops.plan import (  # noqa: E402
    SELECT_THEN_AVERAGE_TEMPLATE,
    DataPipeline,
    DiscoveryQuery,
    PipelineError,
    PipelineExecutor,
    PipelinePlanner,
    PlanningError,
    PlanningRequest,
    RulePlanGenerator,
    project_then_aggregate_template,
)

LIB_ROOT = Path(__file__).parents[2]
PROJECT_ROOT = Path(__file__).parents[3]
MARKED_FENCE = re.compile(
    r"<!-- blue-data-ops-test: (?P<name>[a-z0-9-]+) -->\n"
    r"```python\n(?P<source>.*?)\n```",
    re.DOTALL,
)


def _marked_readme_fences() -> dict[str, str]:
    fences: dict[str, str] = {}
    for path in (LIB_ROOT / "README.md", PROJECT_ROOT / "platform/ops-mcp/README.md"):
        text = path.read_text(encoding="utf-8")
        marker_count = text.count("<!-- blue-data-ops-test:")
        matches = list(MARKED_FENCE.finditer(text))
        assert len(matches) == marker_count, f"unmatched README test marker in {path}"
        for match in matches:
            name = match.group("name")
            assert name not in fences, f"duplicate README test marker: {name}"
            fences[name] = match.group("source")
    assert fences, "no shipped README test markers found"
    return fences


def _execute(source: str) -> dict[str, object]:
    namespace: dict[str, object] = {}
    exec(compile(source, "<shipped-readme-fence>", "exec"), namespace)
    return namespace


def test_all_marked_shipped_readme_fences_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    for source in _marked_readme_fences().values():
        _execute(source)


@pytest.mark.parametrize(
    ("old", "new"),
    (
        ("active_registry, default_registry", "versioned_registry, default_registry"),
        ("ordinary = active_registry()", "ordinary = default_registry()"),
        ('default_registry(avg="2.7.4")', 'default_registry(avg="2.7.5")'),
        ('history.resolve("avg@2.0.0")', 'history.resolve("avg@9.0.0")'),
        ('== "avg@3.0.0"', '== "avg@2.0.0"'),
    ),
    ids=("import", "constructor", "override", "argument", "asserted-version"),
)
def test_registry_fence_mutations_fail(old: str, new: str) -> None:
    source = _marked_readme_fences()["registry-roles"]
    assert source.count(old) == 1
    mutated = source.replace(old, new, 1)
    with pytest.raises((AssertionError, NameError, ResolveError)):
        _execute(mutated)


def test_api_reference_property_preparation_example() -> None:
    text = (PROJECT_ROOT / "docs/api-reference.md").read_text(encoding="utf-8")
    examples = [
        source
        for source in re.findall(r"```python\n(.*?)```", text, re.DOTALL)
        if 'defaults = {"openai.model"' in source
    ]
    assert len(examples) == 1
    namespace = _execute(examples[0])
    assert namespace["merged"] == {
        "openai.model": "gpt-6-luna",
        "openai.temperature": 0,
        "openai.max_tokens": 512,
        "openai.max_completion_tokens": 256,
    }


def test_readme_select_example() -> None:
    operator = SelectOperator()
    data = [[{"name": "a", "score": 3}, {"name": "b", "score": 9}]]
    output = operator.invoke(
        data,
        {"operand_key": "score", "operand": ">", "operand_val": 5},
    )
    assert output == [[{"name": "b", "score": 9}]]
    assert "operand_key" in operator.attributes
    assert operator.validate(data, {}) is False


def test_readme_documents_per_operator_model_and_effort_controls() -> None:
    readme = (LIB_ROOT / "README.md").read_text(encoding="utf-8")

    assert 'registry.resolve("nl2llm@3.0.0")' in readme
    assert 'registry.resolve("semantic_filter@3.0.0")' in readme
    assert '"llm.model": "gpt-5-mini"' in readme
    assert '"llm.reasoning_effort": "low"' in readme
    assert "Omit\n`llm.reasoning_effort`" in readme
    assert "operator node overrides stored pipeline values" in readme
    assert "Other execution properties keep the\nexisting node, invocation" in readme


def test_readme_serializes_the_documented_llm_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    source = _marked_readme_fences()["llm-pipeline-serialization"]
    _execute(source)

    record = json.loads((tmp_path / "llm-pipeline.json").read_text(encoding="utf-8"))
    assert record["properties"] == {
        "llm.model": "gpt-5-mini",
        "llm.reasoning_effort": "medium",
    }
    operator = next(iter(record["entities"]["OPERATOR"].values()))
    assert operator["operator_id"] == "nl2llm@3.0.0"
    assert operator["properties"] == {
        "llm.model": "gpt-4o-mini",
        "llm.reasoning_effort": None,
    }


def test_root_readme_routes_to_install_and_package_guides() -> None:
    root_readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    lib_readme = (LIB_ROOT / "README.md").read_text(encoding="utf-8")
    examples_readme = (PROJECT_ROOT / "examples/README.md").read_text(encoding="utf-8")
    mcp_readme = (PROJECT_ROOT / "platform/ops-mcp/README.md").read_text(encoding="utf-8")
    headings = [line for line in root_readme.splitlines() if line.startswith("## ")]
    assert headings == [
        "## What it does",
        "## Repository layout",
        "## Requirements",
        "## Quick start",
        "## Packages",
        "## Conduct and disclosures",
    ]
    assert "python3.12 -m venv blue-data-ops/lib/.venv" in root_readme
    assert "source blue-data-ops/lib/.venv/bin/activate" in root_readme
    assert "./blue-data-ops/lib/scripts/install.sh" in root_readme
    assert "python blue-data-ops/examples/quickstart/core_quickstart.py" in root_readme
    assert "docs/installation.md" in root_readme
    assert "docs/cli.md" in root_readme
    assert "docs/mcp.md" in root_readme
    assert "docs/features.md" in root_readme
    assert "platform/ops-mcp/README.md" in root_readme
    assert "platform/ops-cli/README.md" in root_readme
    assert "python -m pytest" not in root_readme
    assert "## Running tests" in lib_readme
    assert "## Tests" in mcp_readme
    assert "python3.12 -m venv blue-data-ops/lib/.venv" in lib_readme
    assert "source blue-data-ops/lib/.venv/bin/activate" in lib_readme
    assert "directory containing this README" in lib_readme
    assert "in an extracted source distribution" in lib_readme
    assert "cd blue-data-ops/lib" not in lib_readme
    assert "directory containing the main README" in examples_readme
    assert "from `lib/`" not in examples_readme
    assert 'python -m pip install "../blue-data/lib[server]"' in mcp_readme


def test_readme_tag_discovery_uses_the_active_registry() -> None:
    source = _marked_readme_fences()["tag-discovery"]
    assert "available_tags" in source
    assert '"capability-metadata-search" in available_tags' in source
    assert 'find("", tags=["domain-vector", "flow-transform"])' in source
    assert 'find("filter", tags=["domain-relational", "flow-transform"])' in source
    _execute(source)

    mutated = source.replace("flow-transform", "flow-combine", 1)
    assert mutated != source
    with pytest.raises(AssertionError):
        _execute(mutated)


def test_readme_defines_the_tag_axes_and_filter_contract() -> None:
    readme = (LIB_ROOT / "README.md").read_text(encoding="utf-8")
    discovery = readme.split("### Discovery", 1)[1].split("### Operator skill resources", 1)[0]

    for axis in ("domain", "flow", "accepts", "produces", "capability", "requires"):
        assert f"`{axis}-*`" in discovery
    assert "exact AND tag filter" in discovery
    assert "A blank query with tags performs tag-only discovery" in discovery
    assert "A malformed filter raises `DiscoveryError`" in discovery
    assert "nonempty, contains no whitespace, and includes at least one hyphen" in discovery
    assert "does not check taxonomy membership or hyphen position" in discovery
    assert "There is no OR or negative-tag syntax" in discovery
    assert "`accepts-none` does not make the `input_data` argument optional" in discovery
    assert "`register()` preserves arbitrary custom tags for compatibility" in discovery
    assert "a custom tag is discoverable only when its stored value equals" in discovery
    assert "use `capability-metadata-search` or `produces-metadata`" in discovery

    catalog = active_registry()
    for malformed in ("", "  ", "domain vector", "domain"):
        with pytest.raises(DiscoveryError):
            catalog.find("", tags=[malformed])
    for absent in ("domain-", "-vector", "domain_-vector"):
        assert catalog.find("", tags=[absent]) == []


def test_wheel_metadata_readme_does_not_link_to_sdist_only_files() -> None:
    readme = (LIB_ROOT / "README.md").read_text(encoding="utf-8")
    sdist_only_link = re.compile(
        r"\]\((?:COMPATIBILITY\.md(?:#[^)]+)?|OPERATORS\.md(?:#[^)]+)?|(?:\.\./)?examples/[^)]+)\)"
    )

    assert sdist_only_link.search(readme) is None
    assert "A wheel exposes this README through distribution metadata" in readme
    assert "download and extract the matching `blue-data-ops==1.0.0` source distribution" in readme
    assert "The supported migration boundary is stated above" in readme


def test_readme_embedding_discovery_example() -> None:
    readme = (LIB_ROOT / "README.md").read_text(encoding="utf-8")
    contract = (
        "With a nonblank query, `find()` returns every tag-matching card in cosine order. "
        "It applies no threshold or limit; callers limit the returned list."
    )

    class KeywordEmbedder:
        space_id = "readme-keywords-v1"

        def __call__(self, texts: tuple[str, ...]) -> list[list[float]]:
            terms = ("filter", "join", "query")
            return [[1.0, *(float(term in text.casefold()) for term in terms)] for text in texts]

    catalog = active_registry()
    embedding_index = OperatorEmbeddingIndex.build(catalog, KeywordEmbedder())
    cards = embedding_index.find("filter rows", tags=["produces-data"])
    expected_ids = {
        card.operator_id for card in catalog.list_cards() if "produces-data" in card.tags
    }
    limited = cards[:1]

    assert contract in readme
    assert len(cards) > len(limited) == 1
    assert {card.operator_id for card in cards} == expected_ids
    assert catalog.resolve(limited[0].operator_id) is catalog.resolve(cards[0].operator_id)


def test_readme_source_distribution_version() -> None:
    metadata = tomllib.loads((LIB_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert metadata["project"]["version"] == "1.0.0"
    assert metadata["project"]["requires-python"] == ">=3.12,<3.14"
    assert metadata["tool"]["ruff"]["target-version"] == "py312"
    assert metadata["tool"]["pyright"]["pythonVersion"] == "3.12"


def test_readme_operator_skill_inventory_matches_the_package_index() -> None:
    from tests.unit.operator_skills._settings_conformance import expected_skill_package_ids

    readme = (LIB_ROOT / "README.md").read_text(encoding="utf-8")
    index = json.loads(
        (LIB_ROOT / "src/blue_data_ops/operator_skills/_index.json").read_text(encoding="utf-8")
    )
    operator_ids = tuple(index["packages"])

    assert len(operator_ids) == 55
    assert operator_ids == expected_skill_package_ids(versioned_registry())
    assert {card.operator_id for card in active_registry().list_cards()} <= set(operator_ids)
    assert "55 exact-version packages" in readme
    assert "All 55 packages declare levels 2 and 3" in readme
    assert "`load()` defaults to level 2" in readme
    assert "`describe().declared_levels` reports the levels available" in readme
    assert "No package in this release includes level-4 `history.md`" in readme
    assert "multipart_query@2.0.0" not in operator_ids

    loader = OperatorSkillLoader(versioned_registry())
    assert all(
        loader.describe(operator_id).declared_levels == (2, 3)
        for operator_id in loader.available_operator_ids()
    )


def test_readme_documents_available_skill_levels() -> None:
    readme = (LIB_ROOT / "README.md").read_text(encoding="utf-8")
    assert "All 55 packages declare levels 2 and 3" in readme
    assert "`load()` defaults to level 2" in readme
    assert "`describe().declared_levels` reports the levels available" in readme
    assert "No package in this release includes level-4 `history.md`" in readme

    loader = OperatorSkillLoader(active_registry())
    assert loader.load("select@2.0.0").requested_level == 2
    assert loader.load("select@2.0.0").loaded_kinds == ("guide",)
    assert loader.load("select@2.0.0", level=3).requested_level == 3
    assert loader.load("select@2.0.0", level=3).loaded_kinds == ("guide", "examples")
    for level in (0, 1, 4):
        with pytest.raises(OperatorSkillLoadError) as unavailable:
            loader.load("select@2.0.0", level=level)
        assert unavailable.value.code is OperatorSkillErrorCode.NOT_AVAILABLE


def test_compatibility_states_how_the_loader_rejects_a_dot_segment_manifest_name(
    tmp_path: Path,
) -> None:
    compatibility = (LIB_ROOT / "COMPATIBILITY.md").read_text(encoding="utf-8")
    resources = tmp_path / "operator_skills"
    shutil.copytree(
        LIB_ROOT / "src/blue_data_ops/operator_skills",
        resources,
        ignore=shutil.ignore_patterns("*.py", "__pycache__"),
    )
    index_path = resources / "_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["packages"]["..@1.0.0"] = "../1.0.0/manifest.json"
    index_path.write_text(json.dumps(index, sort_keys=True), encoding="utf-8")
    reads: list[str] = []
    loader = OperatorSkillLoader(
        versioned_registry(), _resource_root=resources, _on_read=reads.append
    )

    for indexed in (
        loader.available_operator_ids,
        lambda: loader.describe("nl2sql@2.0.0"),
        lambda: loader.load("nl2sql@2.0.0"),
        lambda: loader.read("nl2sql@2.0.0", "guide"),
    ):
        with pytest.raises(OperatorSkillLoadError) as poisoned:
            indexed()
        assert poisoned.value.code is OperatorSkillErrorCode.MANIFEST_INVALID

    reads.clear()
    with pytest.raises(OperatorSkillLoadError) as malformed:
        loader.describe("..@1.0.0")
    assert malformed.value.code is OperatorSkillErrorCode.INVALID_OPERATOR_ID
    assert reads == []
    assert "`.` or `..` path segment invalidates the whole index" in compatibility
    assert "`MANIFEST_INVALID`" in compatibility
    assert "`INVALID_OPERATOR_ID` before the index is read at all" in compatibility


def test_readme_registry_example(tmp_path: Path) -> None:
    source = SQLiteDBSource(
        "demo_sqlite",
        properties={"connection": {"database_directory": str(tmp_path)}},
    )
    registry = DataRegistry(store=MemoryJSONSource(), rebuild=False)
    registry.register_source(source)
    registry.sync_source(source.name, recursive=True)
    seam = RegistrySeam(registry)

    output, output_attributes, meta = CreateDatabaseOperator().run(
        [[]], {"source": source.name, "database": "main"}, {"data_registry": seam}
    )
    assert output == [[]]
    assert output_attributes == {}
    assert meta.errors == []
    assert seam.get_record("main", "database", f"/source/{source.name}") is not None


def test_the_package_imports_with_no_optional_extra_installed() -> None:
    blocked = ["litellm", "diskcache", "jinja2", "sklearn", "sentence_transformers", "openai"]
    program = f"""
import sys

BLOCKED = {blocked!r}

class Blocker:
    def find_spec(self, name, path=None, target=None):
        root = name.split(".", 1)[0]
        if root in BLOCKED:
            raise ModuleNotFoundError(f"blocked optional dependency {{root!r}}", name=root)
        return None

sys.meta_path.insert(0, Blocker())

import blue_data_ops
import blue_data_ops.data
import blue_data_ops.operators
import blue_data_ops.plan
import blue_data_ops.utils
from blue_data_ops.operators import versioned_registry

print(len(versioned_registry().list_cards()))
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(LIB_ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    assert result.stdout.strip() == "88"


def test_sklearn_operator_contains_missing_optional_dependency() -> None:
    blocked = ["sklearn"]
    program = f"""
import sys

BLOCKED = {blocked!r}

class Blocker:
    def find_spec(self, name, path=None, target=None):
        root = name.split(".", 1)[0]
        if root in BLOCKED:
            raise ModuleNotFoundError(f"blocked optional dependency {{root!r}}", name=root)
        return None

sys.meta_path.insert(0, Blocker())

import pytest

from blue_data_ops.operators import ClusterOperator, SklearnEstimator

operator = SklearnEstimator()
data = [[{{"vector": [1.0]}}]]
with pytest.raises(ModuleNotFoundError):
    operator.apply(data, {{"vector_key": "vector"}}, {{"algorithm": "KMeans"}})
output, output_attributes, meta = operator.run(
    data,
    {{"vector_key": "vector"}},
    {{"algorithm": "KMeans"}},
)
assert output == [[]]
assert output_attributes == {{}}
assert [(error.code.value, error.stage.value) for error in meta.errors] == [
    ("EXECUTION_FAILED", "EXECUTE")
]

cluster = ClusterOperator()
cluster_data = [[{{"vector": [0.0]}}, {{"vector": [1.0]}}]]
cluster_attributes = {{"vector_key": "vector", "n_cluster": 2}}
with pytest.raises(ModuleNotFoundError):
    cluster.apply(cluster_data, cluster_attributes, {{"algorithm": "kmeans"}})
_, _, cluster_meta = cluster.run(
    cluster_data,
    cluster_attributes,
    {{"algorithm": "kmeans"}},
)
assert [(error.code.value, error.stage.value) for error in cluster_meta.errors] == [
    ("EXECUTION_FAILED", "EXECUTE")
]
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(LIB_ROOT / "src")
    subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )


def _readme_planning_request() -> PlanningRequest:
    return PlanningRequest(
        goal="average total of orders above 100",
        discovery_queries=(
            DiscoveryQuery("filter", tags=("capability-filter",)),
            DiscoveryQuery("average", tags=("capability-average",)),
        ),
        operator_attributes={
            "select": {"operand_key": "total", "operand": ">", "operand_val": 100},
            "avg": {"avg_key": "total", "output_key": "average_total"},
        },
    )


def test_readme_rule_template_planner_example() -> None:
    planner = PipelinePlanner(
        active_registry(),
        RulePlanGenerator([SELECT_THEN_AVERAGE_TEMPLATE]),
    )
    run = planner.run(
        _readme_planning_request(),
        [[{"total": 120.0}, {"total": 215.0}, {"total": 50.0}]],
    )
    assert run.execution.output_data == [[{"average_total": 167.5}]]
    assert all(not node.exec_meta.errors for node in run.execution.node_runs)
    assert [step.operator_id for step in run.planning.selected.steps] == [
        "select@2.0.0",
        "avg@3.0.0",
    ]


def test_readme_documents_pipeline_execution_metadata() -> None:
    readme = (LIB_ROOT / "README.md").read_text(encoding="utf-8")
    source = _marked_readme_fences()["pipeline-execution"]

    assert "run.node_runs[0]" in source
    assert "select_run.exec_meta.errors" in source
    assert "`PipelineRun.node_runs` records completed operator nodes" in readme
    assert "`PipelineRun.node_runs[*].exec_meta`" in readme
    _execute(source)


def test_readme_project_then_aggregate_template() -> None:
    assert project_then_aggregate_template("sum").label == "project-then-sum"


def test_readme_stored_retired_plan_fails_at_preflight() -> None:
    plan = DataPipeline(label="saved")
    source = plan.define_input("records")
    step = plan.define_operator("plan_discover@2.0.0", attributes={"task": "select"})
    result = plan.define_output("result")
    plan.set_plan_input(source)
    plan.set_plan_output(result)
    plan.connect_nodes(source, step)
    plan.connect_nodes(step, result)
    restored = DataPipeline.from_dict(plan.to_dict())

    with pytest.raises(PipelineError, match="cannot resolve 'plan_discover@2.0.0'"):
        PipelineExecutor(active_registry()).preflight(restored)


def test_readme_operator_skill_history_example_uses_the_average_cards() -> None:
    readme = (LIB_ROOT / "README.md").read_text(encoding="utf-8")
    registry = versioned_registry()
    eligible_ids = set(OperatorSkillLoader(registry).available_operator_ids())
    matches = registry.find("average", tags=["domain-arithmetic"])
    skipped = next(card for card in matches if card.operator_id not in eligible_ids)

    assert skipped.operator_id == "avg@1.0.0"
    assert "avg@2.0.0" in eligible_ids
    assert "`avg@1.0.0` remains searchable in the history registry" in readme


def test_readme_and_mcp_readme_carry_current_versions_and_migrations() -> None:
    lib_readme = (LIB_ROOT / "README.md").read_text(encoding="utf-8")
    compatibility = (LIB_ROOT / "COMPATIBILITY.md").read_text(encoding="utf-8")
    mcp_readme = (PROJECT_ROOT / "platform/ops-mcp/README.md").read_text(encoding="utf-8")
    registry_integrity_boundary = (
        "The private in-memory tables that distinguish reviewed built-ins from raw cards are "
        "integrity controls for ordinary planner admission. They are not a tamper-proof isolation "
        "boundary against arbitrary same-process code that mutates private registry state."
    )

    assert "blue-data-ops 1.0.0" in lib_readme
    assert 'version("blue-data-ops") == "1.0.0"' in lib_readme
    assert "non-drop-in" in compatibility
    assert "DeclarativeOperator" in compatibility
    assert "`BlueDataOpsDeprecationWarning` remains importable" in compatibility
    assert "Package 3.0 no longer emits it" in compatibility
    assert "automatic refinement" in compatibility
    assert "compatible core 2.x/MCP 0.x pair" in compatibility
    assert "admitted, supported exact operator IDs" in compatibility
    assert "raw override card is not automatically planning-authorized" in lib_readme
    assert "caller-created v2 cards" in lib_readme
    assert registry_integrity_boundary in lib_readme
    assert 'version("blue-data-ops-mcp") == "1.0.0"' in mcp_readme
    assert "blue-data-ops==1.0.0" in mcp_readme
    assert "33 primary tools and no refinement companions" in mcp_readme
    assert "select caller-created `@2.0.0` cards" in mcp_readme
    assert "supported raw package cards" in mcp_readme
    assert "retained `@2.0.0` cards" in mcp_readme
    assert "active `@3.0.0` cards" in mcp_readme
    assert "Raw cards have empty `tags` and `when_to_invoke`" in mcp_readme
    assert "does not change planner eligibility" in mcp_readme
    assert "does not authorize a write" in mcp_readme
    assert "Operator resources remain available through `OperatorSkillLoader`" in mcp_readme
    assert "freezes `operator_ids` at construction" in mcp_readme
    assert "cannot shadow any of the 33 supported built-in logical names" in mcp_readme
    assert "Custom v1 and v3 cards are rejected" in mcp_readme
    assert "It contains the 33 retained v2 exact IDs" in mcp_readme
    assert mcp_readme.count("blue-data-ops-mcp==0.9.0") == 1
    assert mcp_readme.count("blue-data-ops[ml,vector,llm]==2.7.0") == 1
    assert "## Migrating from 0.9.0" in mcp_readme
    assert mcp_readme.index("## Migrating from 0.9.0") < mcp_readme.index("## Migrating from 0.8.0")


def test_readme_pipeline_error_marks_the_preflight_boundary() -> None:
    with pytest.raises(PipelineError, match="pipeline has no nodes"):
        PipelineExecutor(active_registry()).preflight(DataPipeline())


def test_readme_planning_error_carries_a_structured_record() -> None:
    planner = PipelinePlanner(active_registry(), RulePlanGenerator())
    request = PlanningRequest(
        goal="average total of orders above 100",
        discovery_queries=(DiscoveryQuery("filter", tags=("capability-filter",)),),
    )
    with pytest.raises(PlanningError) as caught:
        planner.plan(request)
    record = caught.value.record
    assert (record.stage.value, record.category.value) == ("DISCOVERY", "RECOVERABLE")
    assert record.retryable is False
    assert record.suggestion is not None
