"""Executable checks for the README usage examples and the public compatibility statement."""

from __future__ import annotations

import json
import shutil
import tomllib
import warnings
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest

blue_data = pytest.importorskip("blue_data")

from blue_data.registry.data_registry import DataRegistry  # noqa: E402
from blue_data.source.json.memory_json_source import MemoryJSONSource  # noqa: E402
from blue_data.source.sql.sqlite.sqlite_sql_source import SQLiteDBSource  # noqa: E402

from blue_data_ops import (  # noqa: E402
    BlueDataOpsDeprecationWarning,
    CreateDatabaseOperator,
    RegistrySeam,
    SelectOperator,
)
from blue_data_ops.operator_skills import (  # noqa: E402
    OperatorSkillErrorCode,
    OperatorSkillLoader,
    OperatorSkillLoadError,
)
from blue_data_ops.operators import OperatorEmbeddingIndex, versioned_registry  # noqa: E402
from blue_data_ops.plan import (  # noqa: E402
    SELECT_THEN_AVERAGE_TEMPLATE,
    DataContextSnapshot,
    DataPipeline,
    DiscoveryQuery,
    DiscoverySnapshot,
    PipelineError,
    PipelineExecutor,
    PipelinePlanner,
    PlanDraft,
    PlanningError,
    PlanningRequest,
    RefinableOperator,
    RulePlanGenerator,
    project_then_aggregate_template,
)


def test_readme_select_example() -> None:
    op = SelectOperator()
    data = [[{"name": "a", "score": 3}, {"name": "b", "score": 9}]]
    out = op.invoke(data, {"operand_key": "score", "operand": ">", "operand_val": 5})
    assert out == [[{"name": "b", "score": 9}]]
    assert "operand_key" in op.attributes
    assert op.validate(data, {}) is False


def test_readme_explains_plan_operator_raw_call_shapes() -> None:
    for operator_id in ("multipart_query@2.0.0", "nl2query_router@2.0.0"):
        operator = versioned_registry().resolve(operator_id)
        with pytest.raises(TypeError, match="unexpected keyword argument 'input_data'"):
            operator.invoke([[]], {}, {})


def test_root_readme_has_a_complete_source_install_and_mcp_route() -> None:
    root_readme = (Path(__file__).parents[3] / "README.md").read_text(encoding="utf-8")
    lib_readme = (Path(__file__).parents[2] / "README.md").read_text(encoding="utf-8")
    mcp_readme = (Path(__file__).parents[3] / "platform/mcp/README.md").read_text(encoding="utf-8")
    assert "python -m venv blue-data-ops/lib/.venv" in root_readme
    assert "source blue-data-ops/lib/.venv/bin/activate" in root_readme
    assert "python3 -m venv blue-data-ops/lib/.venv" in lib_readme
    assert "source blue-data-ops/lib/.venv/bin/activate" in lib_readme
    assert "python -m pip install -e ./blue-data/lib" in root_readme
    assert 'python -m pip install -e "./blue-data-ops/lib[dev]"' in root_readme
    assert "cd blue-data-ops/lib" in root_readme
    assert "python -m pytest" in root_readme
    assert "platform/mcp/README.md" in root_readme
    assert "python -m pip install ../blue-data/lib" in mcp_readme


def test_readme_tag_discovery_uses_exact_and_filtering() -> None:
    registry = versioned_registry()
    cards = registry.find(
        "filter",
        tags=["domain-relational", "flow-transform"],
    )
    assert [card.operator_id for card in cards] == [
        "select@2.0.0",
        "select@1.0.0",
    ]
    assert all({"domain-relational", "flow-transform"} <= set(card.tags) for card in cards)


def test_readme_embedding_discovery_example() -> None:
    readme = (Path(__file__).parents[2] / "README.md").read_text(encoding="utf-8")
    contract = (
        "With a nonblank query, `find()` returns every tag-matching card in cosine order. "
        "It applies no threshold or limit; callers limit the returned list."
    )

    class KeywordEmbedder:
        @property
        def space_id(self) -> str:
            return "readme-keywords-v1"

        def __call__(self, texts: tuple[str, ...]) -> list[list[float]]:
            terms = ("filter", "join", "query")
            return [[1.0, *(float(term in text.casefold()) for term in terms)] for text in texts]

    catalog = versioned_registry()
    embedding_index = OperatorEmbeddingIndex.build(catalog, KeywordEmbedder())
    cards = embedding_index.find("filter rows", tags=["produces-data"])
    expected_ids = {
        card.operator_id for card in catalog.list_cards() if "produces-data" in card.tags
    }
    limited = cards[:1]
    op = catalog.resolve(limited[0].operator_id) if limited else None

    assert contract in readme
    assert len(cards) > len(limited) == 1
    assert {card.operator_id for card in cards} == expected_ids
    assert op is catalog.resolve(cards[0].operator_id)


def test_readme_source_distribution_version() -> None:
    metadata = tomllib.loads((Path(__file__).parents[2] / "pyproject.toml").read_text())
    assert metadata["project"]["version"] == "2.9.0"
    assert metadata["project"]["requires-python"] == ">=3.11"
    assert metadata["tool"]["ruff"]["target-version"] == "py311"
    assert metadata["tool"]["pyright"]["pythonVersion"] == "3.11"


def test_readme_operator_skill_inventory_matches_the_package_index() -> None:
    from tests.unit.operator_skills._settings_conformance import (
        expected_skill_package_ids,
        expected_v2_skill_package_ids,
    )

    package_root = Path(__file__).parents[2]
    readme = (package_root / "README.md").read_text(encoding="utf-8")
    index_path = package_root / "src/blue_data_ops/operator_skills/_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    operator_ids = tuple(index["packages"])

    registry = versioned_registry()
    historical_ids = expected_v2_skill_package_ids(registry)
    assert tuple(oid for oid in operator_ids if oid in historical_ids) == historical_ids
    assert len(operator_ids) == 36
    assert operator_ids == expected_skill_package_ids(registry)
    assert "all 32 active execution operators" in readme
    assert "`multipart_query@2.0.0` package" in readme
    lowered = readme.lower()
    assert "first operator skill package" not in lowered
    assert "only operator skill package" not in lowered


def test_compatibility_states_how_the_loader_rejects_a_dot_segment_manifest_name(
    tmp_path: Path,
) -> None:
    """Both clauses of the published loader contract, checked against the loader itself."""

    package_root = Path(__file__).parents[2]
    compatibility = (package_root / "COMPATIBILITY.md").read_text(encoding="utf-8")
    resources = tmp_path / "operator_skills"
    shutil.copytree(
        package_root / "src/blue_data_ops/operator_skills",
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

    # `nl2sql@2.0.0` is a legitimate operator and its own row is untouched, so this is the
    # index closing rather than one bad row being skipped
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
    """A base install must remain importable without optional dependencies.

    Blocking optional modules directly keeps the check valid when dependencies or imports move.
    """

    import subprocess
    import sys

    # `tenacity` is a core dependency, and `numpy` arrives transitively through `blue-data`.
    blocked = [
        "litellm",
        "diskcache",
        "jinja2",
        "sklearn",
        "sentence_transformers",
        "openai",
    ]
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
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "75"


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
        versioned_registry(),
        RulePlanGenerator([SELECT_THEN_AVERAGE_TEMPLATE]),
    )
    run = planner.run(
        _readme_planning_request(),
        [[{"total": 120.0}, {"total": 215.0}, {"total": 50.0}]],
    )
    assert run.execution.output_data == [[{"average_total": 167.5}]]
    assert [step.operator_id for step in run.planning.selected.steps] == [
        "select@2.0.0",
        "avg@2.0.0",
    ]


def test_readme_project_then_aggregate_template() -> None:
    template = project_then_aggregate_template("sum")
    assert template.label == "project-then-sum"


def test_readme_refinement_and_live_record_examples() -> None:
    refinable = versioned_registry().resolve("multipart_query@2.0.0")
    assert isinstance(refinable, RefinableOperator)
    plans, meta = refinable.refine([[]], {})
    assert len(plans) == 1
    assert meta.errors == []

    record = plans[0].to_dict()
    plans[0].set_property("pipeline_owner", "live")
    assert record["properties"]["pipeline_owner"] == "live"

    restored = DataPipeline.from_dict(record)
    restored.set_property("owner", "live")
    assert record["properties"]["owner"] == "live"

    detached = DataPipeline.from_dict(deepcopy(record))
    detached.set_property("owner", "detached")
    assert record["properties"]["owner"] == "live"


def test_readme_deprecated_card_inventory_example() -> None:
    registry = versioned_registry()
    going_away = sorted(card.operator_id for card in registry.list_cards() if card.deprecated)

    assert len(going_away) == 8
    assert registry.resolve("plan_discover@2.0.0") is not None
    assert going_away == [
        "multipart_query@1.0.0",
        "multipart_query@2.0.0",
        "nl2query_router@1.0.0",
        "nl2query_router@2.0.0",
        "plan_discover@1.0.0",
        "plan_discover@2.0.0",
        "query_breakdown@1.0.0",
        "query_breakdown@2.0.0",
    ]
    from tests.unit.operators._registry_catalog_expectations import assert_full_inventory

    assert_full_inventory(registry.list_cards())


def test_readme_deprecation_warning_category_and_filter() -> None:
    registry = versioned_registry()
    operator = registry.resolve("multipart_query@2.0.0")
    assert isinstance(operator, RefinableOperator)

    assert issubclass(BlueDataOpsDeprecationWarning, DeprecationWarning)

    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        operator.refine([[]], {})
    # one per top-level entry, attributed to this file rather than to package internals
    assert len(seen) == 1
    assert Path(seen[0].filename) == Path(__file__)

    with warnings.catch_warnings(record=True) as filtered:
        warnings.simplefilter("always")
        warnings.filterwarnings("ignore", category=BlueDataOpsDeprecationWarning)
        operator.refine([[]], {})
    assert filtered == []


class _OfferedIds(RulePlanGenerator):
    """A default rule generator that also keeps what `plan()` offered it."""

    def __init__(self) -> None:
        super().__init__()
        self.offered: list[tuple[str, ...]] = []

    def generate(
        self,
        request: PlanningRequest,
        discovery: DiscoverySnapshot,
        data_context: DataContextSnapshot | None = None,
    ) -> tuple[PlanDraft, ...]:
        self.offered.append(discovery.operator_ids)
        return super().generate(request, discovery, data_context)


def test_readme_plan_admits_active_cards_the_discovery_limit_would_hide() -> None:
    registry = versioned_registry()
    generator = _OfferedIds()
    planner = PipelinePlanner(registry, generator)
    request = PlanningRequest(
        goal="summarize a query",
        discovery_queries=(DiscoveryQuery("query"),),
        max_discovery_cards=2,
    )

    assert [card.operator_id for card in planner.discover(request).cards] == [
        "multipart_query@2.0.0",
        "nl2query_router@2.0.0",
    ]
    with pytest.raises(PlanningError):
        planner.plan(request)
    # the same budget of two, spent on the active cards the deprecated pair used to hide.
    # A skip that filtered the finished snapshot instead would leave this empty; discovery
    # itself is unchanged. The default rule builds nothing from these two, hence the error.
    assert generator.offered == [("nl2bn@2.0.0", "nl2llm@2.0.0")]


def test_readme_stored_plan_inventory_and_execution_boundary() -> None:
    registry = versioned_registry()
    plan = DataPipeline(label="saved")
    source = plan.define_input("records")
    step = plan.define_operator("plan_discover@2.0.0", attributes={"task": "select"})
    result = plan.define_output("result")
    plan.set_plan_input(source)
    plan.set_plan_output(result)
    plan.connect_nodes(source, step)
    plan.connect_nodes(step, result)
    record = plan.to_dict()

    restored = DataPipeline.from_dict(record)
    inventory: dict[str, bool] = {}
    for entity in restored.get_entities(type="OPERATOR").values():
        operator_id = cast(str, cast(dict[str, Any], entity)["operator_id"])
        registry.resolve(operator_id)
        card = registry.get_card(operator_id)
        assert card is not None
        inventory[operator_id] = card.deprecated

    assert inventory == {"plan_discover@2.0.0": True}
    for call in (
        lambda: PipelineExecutor(registry).preflight(restored),
        lambda: PipelineExecutor(registry).execute(restored, [[]]),
    ):
        with pytest.raises(PipelineError, match="materialized non-refinable operator"):
            call()


def test_readme_operator_skill_eligibility_illustration_uses_the_average_cards() -> None:
    readme = (Path(__file__).parents[2] / "README.md").read_text(encoding="utf-8")
    registry = versioned_registry()
    loader = OperatorSkillLoader(registry)
    eligible_ids = set(loader.available_operator_ids())

    matches = registry.find("average", tags=["domain-arithmetic"])
    skipped = next(card for card in matches if card.operator_id not in eligible_ids)

    assert skipped.operator_id == "avg@1.0.0"
    assert registry.get_card(skipped.operator_id) is not None
    assert "avg@2.0.0" in eligible_ids
    assert "`avg@1.0.0` is current and searchable" in readme

    skills_section = readme.split("### Operator skill resources")[1]
    skills_section = skills_section.split("### Structured execution")[0]
    # the ineligibility illustration used to reach for a plan operator, which now reads as
    # a lifecycle example rather than an eligibility one
    assert "plan_discover" not in skills_section


def test_readme_and_mcp_readme_carry_no_stale_current_version() -> None:
    lib_readme = (Path(__file__).parents[2] / "README.md").read_text(encoding="utf-8")
    mcp_readme = (Path(__file__).parents[3] / "platform/mcp/README.md").read_text(encoding="utf-8")

    assert "blue-data-ops 2.9.0" in lib_readme
    assert 'version("blue-data-ops") == "2.9.0"' in lib_readme
    assert "2.7.0" not in lib_readme
    assert 'version("blue-data-ops-mcp") == "0.11.0"' in mcp_readme
    assert "blue-data-ops==2.9.0" in mcp_readme
    # the four historical literals stay put; they describe the 0.9.0 release, not this one
    assert mcp_readme.count("blue-data-ops-mcp==0.9.0") == 1
    assert mcp_readme.count("blue-data-ops[ml,vector,llm]==2.7.0") == 1
    assert "## Migrating from 0.9.0" in mcp_readme
    assert mcp_readme.index("## Migrating from 0.9.0") < mcp_readme.index("## Migrating from 0.8.0")


def test_readme_pipeline_error_marks_the_preflight_boundary() -> None:
    with pytest.raises(PipelineError, match="pipeline has no nodes"):
        PipelineExecutor(versioned_registry()).preflight(DataPipeline())


def test_readme_planning_error_carries_a_structured_record() -> None:
    planner = PipelinePlanner(versioned_registry(), RulePlanGenerator())
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
