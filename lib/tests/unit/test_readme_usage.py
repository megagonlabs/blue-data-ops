"""Executable checks for the README usage examples."""

from __future__ import annotations

from copy import deepcopy
from importlib.metadata import version
from typing import Any

import pytest

blue_data = pytest.importorskip("blue_data")

from blue_data_ops import CreateDatabaseOperator, SelectOperator, resolve_registry  # noqa: E402
from blue_data_ops.operators import versioned_registry  # noqa: E402
from blue_data_ops.plan import (  # noqa: E402
    SELECT_THEN_AVERAGE_TEMPLATE,
    DataPipeline,
    DiscoveryQuery,
    PipelineError,
    PipelineExecutor,
    PipelinePlanner,
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


def test_readme_installed_distribution_version() -> None:
    assert version("blue-data-ops") == "2.2.0"


def test_readme_registry_example() -> None:
    class _Source:
        def __init__(self) -> None:
            self.name = "my_source"
            self.properties: dict[str, Any] = {"connection": {"protocol": "memory"}}
            self.databases: list[str] = []

        def create_database(self, database: str, **_kw: Any) -> dict[str, str]:
            self.databases.append(database)
            return {"status": "success"}

        def fetch_databases(self) -> list[str]:
            return list(self.databases)

        def fetch_metadata(self) -> dict[str, Any]:
            return {}

        def fetch_database_metadata(self, database: str) -> dict[str, Any]:
            return {}

        def fetch_database_collections(self, database: str) -> list[str]:
            return []

    seam = resolve_registry({"platform.name": "readme_p", "data_registry.name": "readme_r"})
    assert seam is not None
    seam.register_source(_Source())  # pyright: ignore[reportArgumentType] — structural stub

    result = CreateDatabaseOperator().invoke(
        [[]], {"source": "my_source", "database": "main"}, {"data_registry": seam}
    )
    assert result == [[]]
    assert seam.get_record("main", "database", "/source/my_source") is not None


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
    assert result.stdout.strip() == "72"


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
