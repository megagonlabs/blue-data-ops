"""Package-owned planning and execution paths."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest

from blue_data_ops.operators import versioned_registry
from blue_data_ops.plan import (
    DataPipeline,
    DiscoveryQuery,
    OpenAIPlanGenerator,
    PipelineExecutor,
    PipelinePlanner,
    PlanningRequest,
    RulePlanGenerator,
)
from blue_data_ops.plan.executor import PipelineError

MODEL = "gpt-5-2026-01-01"
ACTIVE_IDS = ("select@2.0.0", "avg@3.0.0")
ANSWER = [[{"average_total": 167.5}]]
ORDERS = [
    [
        {"order_id": 1, "total": 80.0},
        {"order_id": 2, "total": 125.0},
        {"order_id": 3, "total": 210.0},
        {"order_id": 4, "total": 100.0},
    ]
]
SELECT_ATTRIBUTES = {"operand_key": "total", "operand": ">", "operand_val": 100}
AVG_ATTRIBUTES = {"avg_key": "total", "output_key": "average_total"}


def integration_request() -> PlanningRequest:
    return PlanningRequest(
        goal="Find the average total above 100",
        discovery_queries=(
            DiscoveryQuery("filter", ("flow-transform", "accepts-data", "capability-filter")),
            DiscoveryQuery("average", ("flow-aggregate", "accepts-data", "capability-average")),
        ),
        operator_attributes={"select": dict(SELECT_ATTRIBUTES), "avg": dict(AVG_ATTRIBUTES)},
        allowed_operator_ids=ACTIVE_IDS,
        input_label="orders",
        output_label="answer",
    )


class InjectedClient:
    """Minimal client for the injected OpenAI adapter path."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def with_options(self, **kwargs: Any) -> InjectedClient:
        self.calls.append(("with_options", kwargs))
        return self

    @property
    def responses(self) -> InjectedClient:
        return self

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(("create", kwargs))
        payload: dict[str, Any] = {
            "candidates": [
                {
                    "label": "orders-plan",
                    "steps": [
                        {
                            "step_id": "filter",
                            "operator_id": ACTIVE_IDS[0],
                            "attributes_json": json.dumps(SELECT_ATTRIBUTES),
                            "depends_on": [],
                            "label": None,
                        },
                        {
                            "step_id": "average",
                            "operator_id": ACTIVE_IDS[1],
                            "attributes_json": json.dumps(AVG_ATTRIBUTES),
                            "depends_on": ["filter"],
                            "label": None,
                        },
                    ],
                }
            ]
        }
        part = SimpleNamespace(type="output_text", text=json.dumps(payload))
        return SimpleNamespace(status="completed", output=[SimpleNamespace(content=[part])])

    @property
    def offered_operator_ids(self) -> list[str]:
        create = [payload for name, payload in self.calls if name == "create"]
        document = json.loads(create[0]["input"][0]["content"])
        return [entry["operator_id"] for entry in document["operators"]]


def _pipeline(operator_ids: tuple[str, str] = ACTIVE_IDS) -> DataPipeline:
    pipeline = DataPipeline(id="orders")
    source = pipeline.define_input("orders")
    selected = pipeline.define_operator(operator_ids[0], attributes=dict(SELECT_ATTRIBUTES))
    average = pipeline.define_operator(operator_ids[1], attributes=dict(AVG_ATTRIBUTES))
    answer = pipeline.define_output("answer")
    pipeline.set_plan_input(source)
    pipeline.set_plan_output(answer)
    pipeline.connect_nodes(source, selected)
    pipeline.connect_nodes(selected, average)
    pipeline.connect_nodes(average, answer)
    return pipeline


def test_rule_planner_reaches_the_fixed_answer() -> None:
    registry = versioned_registry()
    run = PipelinePlanner(registry, RulePlanGenerator()).run(integration_request(), ORDERS)

    assert [step.operator_id for step in run.planning.selected.steps] == list(ACTIVE_IDS)
    assert run.planning.preflight.operator_ids == ACTIVE_IDS
    assert run.execution.output_data == ANSWER
    assert run.execution.succeeded


def test_hand_built_pipeline_reaches_the_fixed_answer() -> None:
    run = PipelineExecutor(versioned_registry()).execute(_pipeline(), ORDERS)

    assert run.output_data == ANSWER
    assert run.succeeded


def test_injected_client_reaches_the_fixed_answer_without_importing_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    real_import = builtins.__import__
    attempted: list[str] = []

    def recording(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "openai":
            attempted.append(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", recording)
    registry = versioned_registry()
    client = InjectedClient()
    generator = OpenAIPlanGenerator(
        MODEL,
        registry=registry,
        allowed_operator_ids=ACTIVE_IDS,
        client=cast(Any, client),
    )

    run = PipelinePlanner(registry, generator).run(integration_request(), ORDERS)

    assert client.offered_operator_ids == list(ACTIVE_IDS)
    assert run.execution.output_data == ANSWER
    assert attempted == []


@pytest.mark.parametrize(
    "operator_id",
    [
        "multipart_query@2.0.0",
        "nl2query_router@2.0.0",
        "plan_discover@2.0.0",
        "query_breakdown@2.0.0",
    ],
)
def test_saved_retired_operator_parses_but_fails_exact_preflight(operator_id: str) -> None:
    pipeline = _pipeline((operator_id, ACTIVE_IDS[1]))
    record = pipeline.to_dict()

    assert DataPipeline.from_dict(record).to_dict() == record
    with pytest.raises(PipelineError, match=f"cannot resolve {operator_id!r}"):
        PipelineExecutor(versioned_registry()).preflight(DataPipeline.from_dict(record))
