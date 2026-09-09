"""End-to-end proof that the package-owned integration paths survive the lifecycle filter.

Three legs reach the same fixed answer: the rule planner through `PipelinePlanner.run()`, a
hand-built `DataPipeline` through `PipelineExecutor`, and `OpenAIPlanGenerator` driven by an
injected client. The LLM leg imports no SDK, reads no credential, and opens no socket.

A "no deprecation warning" assertion on its own would not prove much, so each leg also
records what it was offered, what it selected, what it resolved, and what it executed, and
the two refinement seams are watched by recorders that are proven to fire before the leg
runs. Both planner legs pass `allowed_operator_ids=()`: with an allowlist in place the
cohort would be absent for a reason that has nothing to do with the lifecycle.
"""

from __future__ import annotations

import json
import warnings
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any, cast

import pytest

from blue_data_ops import BlueDataOpsDeprecationWarning
from blue_data_ops.operators import OperatorRegistry, versioned_registry
from blue_data_ops.operators.multipart_query_operator import MultipartQueryOperator
from blue_data_ops.operators.nl2query_router_operator import NL2QueryRouterOperator
from blue_data_ops.operators.plan_discover_operator import PlanDiscoverOperator
from blue_data_ops.operators.query_breakdown_operator import QueryBreakdownOperator
from blue_data_ops.plan import (
    DataContextSnapshot,
    DataPipeline,
    DiscoveryQuery,
    DiscoverySnapshot,
    OpenAIPlanGenerator,
    PipelineExecutor,
    PipelinePlanner,
    PlanDraft,
    PlanningRequest,
    RulePlanGenerator,
)
from blue_data_ops.plan.executor import PipelineError
from blue_data_ops.plan.refiner import RefinableOperator

MODEL = "gpt-5-2026-01-01"
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

COHORT_NAMES = ("plan_discover", "multipart_query", "nl2query_router", "query_breakdown")
COHORT_IDS = tuple(f"{name}@{version}" for name in COHORT_NAMES for version in ("2.0.0", "1.0.0"))
COHORT_CLASSES = (
    PlanDiscoverOperator,
    MultipartQueryOperator,
    NL2QueryRouterOperator,
    QueryBreakdownOperator,
)
CALIBRATION_ID = "plan_discover@2.0.0"

# Static, and deliberately not read back from a planner: the hand-built leg has no
# discovery step to borrow an answer from.
ACTIVE_IDS = ("select@2.0.0", "avg@2.0.0")


def integration_request() -> PlanningRequest:
    """One request whose first query ranks the whole deprecated cohort above the rest."""

    return PlanningRequest(
        goal="Find the average total above 100",
        discovery_queries=(
            DiscoveryQuery("plan", limit=4),
            DiscoveryQuery("filter", ("flow-transform", "accepts-data", "capability-filter")),
            DiscoveryQuery("average", ("flow-aggregate", "accepts-data", "capability-average")),
        ),
        operator_attributes={"select": dict(SELECT_ATTRIBUTES), "avg": dict(AVG_ATTRIBUTES)},
        allowed_operator_ids=(),
        input_label="orders",
        output_label="answer",
    )


class OfferedRecorder(RulePlanGenerator):
    """The rule generator, plus the catalog each call was offered."""

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


class InjectedClient:
    """The three attributes the OpenAI adapter touches, and nothing else."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def with_options(self, **kwargs: Any) -> InjectedClient:
        self.calls.append(("with_options", kwargs))
        return self

    @property
    def responses(self) -> InjectedClient:
        return self

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(("create", kwargs))
        part = SimpleNamespace(type="output_text", text=json.dumps(self.payload))
        return SimpleNamespace(status="completed", output=[SimpleNamespace(content=[part])])

    @property
    def offered_operator_ids(self) -> list[str]:
        create = [payload for name, payload in self.calls if name == "create"]
        document = json.loads(create[0]["input"][0]["content"])
        return [entry["operator_id"] for entry in document["operators"]]


LLM_PAYLOAD: dict[str, Any] = {
    "candidates": [
        {
            "label": "orders-plan",
            "steps": [
                {
                    "step_id": "filter",
                    "operator_id": "select@2.0.0",
                    "attributes_json": json.dumps(SELECT_ATTRIBUTES),
                    "depends_on": [],
                    "label": None,
                },
                {
                    "step_id": "average",
                    "operator_id": "avg@2.0.0",
                    "attributes_json": json.dumps(AVG_ATTRIBUTES),
                    "depends_on": ["filter"],
                    "label": None,
                },
            ],
        }
    ]
}


class Observers:
    """Recorders on every seam a retained path could reach, in four ordered phases."""

    def __init__(self, registry: OperatorRegistry) -> None:
        self.registry = registry
        self.raw_refiner: list[str] = []
        self.class_refiner: list[str] = []
        self.refine: list[str] = []
        self.resolved: list[str] = []
        self.calibration: dict[str, list[str]] = {}
        self._undo: list[Callable[[], None]] = []

    # Phase 1 --------------------------------------------------------------------- #
    def install(self) -> None:
        for operator_id in COHORT_IDS:
            operator = self.registry.resolve(operator_id)
            assert "refiner" in operator.__dict__, operator_id
            self._patch_instance(operator, operator_id)
        for operator_class in COHORT_CLASSES:
            assert "_refiner" in operator_class.__dict__, operator_class.__name__
            self._patch_class(operator_class, "_refiner", self.class_refiner)
        assert "refine" in RefinableOperator.__dict__
        assert not any("refine" in cls.__dict__ for cls in COHORT_CLASSES)
        self._patch_class(RefinableOperator, "refine", self.refine)
        self._patch_resolve()

    def _patch_instance(self, operator: Any, operator_id: str) -> None:
        original = cast("Callable[..., Any]", operator.__dict__["refiner"])
        buffer = self.raw_refiner

        def record(*args: Any, **kwargs: Any) -> Any:
            buffer.append(operator_id)
            return original(*args, **kwargs)

        object.__setattr__(operator, "refiner", record)
        self._undo.append(lambda: object.__setattr__(operator, "refiner", original))

    def _patch_class(self, owner: type, name: str, buffer: list[str]) -> None:
        original = cast("Callable[..., Any]", owner.__dict__[name])

        def record(operator_self: Any, *args: Any, **kwargs: Any) -> Any:
            buffer.append(operator_self.operator_id)
            return original(operator_self, *args, **kwargs)

        setattr(owner, name, record)
        self._undo.append(lambda: setattr(owner, name, original))

    def _patch_resolve(self) -> None:
        original = OperatorRegistry.resolve
        buffer = self.resolved

        def record(self: OperatorRegistry, operator_id: str) -> Any:
            buffer.append(operator_id)
            return original(self, operator_id)

        OperatorRegistry.resolve = record
        self._undo.append(lambda: setattr(OperatorRegistry, "resolve", original))

    # Phase 2 --------------------------------------------------------------------- #
    def calibrate(self) -> None:
        """Fire every recorder once, then record what firing looked like.

        Each self-test asserts only that its recorder ran. Two of the three calls raise on
        the degenerate input, which says nothing about whether the observation worked.
        """

        resolved = cast(Any, self.registry.resolve(CALIBRATION_ID))
        for call in (resolved.refiner, resolved._refiner, resolved.refine):
            try:
                call([[]], {}, {})
            except Exception:
                pass
        assert self.raw_refiner, "the instance refiner recorder never fired"
        assert self.class_refiner, "the concrete-class _refiner recorder never fired"
        assert self.refine, "the RefinableOperator.refine recorder never fired"
        assert self.resolved, "the registry resolve recorder never fired"
        self.calibration = {
            "raw_refiner": list(self.raw_refiner),
            "class_refiner": list(self.class_refiner),
            "refine": list(self.refine),
            "resolved": list(self.resolved),
        }

    # The phase boundary ---------------------------------------------------------- #
    def clear(self) -> None:
        """Every buffer, not just the refiner ones.

        Calibration had to resolve a deprecated operator to reach its own recorders, so a
        resolution buffer carried across the boundary would fail the leg's "no deprecated
        id was resolved" assertion against the setup rather than against the product.
        """

        for buffer in (self.raw_refiner, self.class_refiner, self.refine, self.resolved):
            buffer.clear()

    # Phase 4 --------------------------------------------------------------------- #
    def restore(self) -> None:
        for undo in reversed(self._undo):
            undo()
        self._undo.clear()

    def assert_no_refinement_seam_was_entered(self) -> None:
        assert self.raw_refiner == []
        assert self.class_refiner == []
        assert self.refine == []

    def assert_no_deprecated_id_was_resolved(self) -> None:
        assert [item for item in self.resolved if item in COHORT_IDS] == []


@pytest.fixture
def observers() -> Iterator[Observers]:
    """Phases 0-2, the boundary, then the measured phase; phase 4 on the way out."""

    registry = versioned_registry()
    watcher = Observers(registry)
    watcher.install()
    try:
        watcher.calibrate()
        watcher.clear()
        yield watcher
    finally:
        watcher.restore()


@pytest.fixture
def recorded_warnings() -> Iterator[list[warnings.WarningMessage]]:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        yield caught


def package_warnings(caught: list[warnings.WarningMessage]) -> list[str]:
    return [str(item.message) for item in caught if item.category is BlueDataOpsDeprecationWarning]


def test_every_observer_fires_during_calibration(observers: Observers) -> None:
    """The measured zeros below are only worth reading if the recorders can reach one.

    A recorder on `RefinableOperator._refiner` or on a synthesized `Operator.refiner`
    would leave these lists empty: the four concrete classes define their own `_refiner`,
    and `Operator` carries no `refiner` attribute at all.
    """

    assert observers.calibration["raw_refiner"] == [CALIBRATION_ID]
    assert observers.calibration["class_refiner"] == [CALIBRATION_ID]
    assert observers.calibration["refine"] == [CALIBRATION_ID]
    assert observers.calibration["resolved"] == [CALIBRATION_ID]
    assert observers.raw_refiner == []
    assert observers.resolved == []


def test_the_rule_planner_leg_reaches_the_fixed_answer(
    observers: Observers,
    recorded_warnings: list[warnings.WarningMessage],
) -> None:
    generator = OfferedRecorder()
    planner = PipelinePlanner(observers.registry, generator)

    run = planner.run(integration_request(), ORDERS)

    assert generator.offered == [
        ("data_discover@2.0.0", "semantic_filter@2.0.0", "select@2.0.0", "avg@2.0.0")
    ]
    assert [step.operator_id for step in run.planning.selected.steps] == list(ACTIVE_IDS)
    assert observers.resolved == ["select@2.0.0", "avg@2.0.0", "select@2.0.0", "avg@2.0.0"]
    assert run.planning.preflight.operator_ids == ACTIVE_IDS
    assert run.execution.output_data == ANSWER
    assert run.execution.succeeded
    observers.assert_no_refinement_seam_was_entered()
    observers.assert_no_deprecated_id_was_resolved()
    assert package_warnings(recorded_warnings) == []


def test_the_hand_built_pipeline_leg_reaches_the_fixed_answer(
    observers: Observers,
    recorded_warnings: list[warnings.WarningMessage],
) -> None:
    pipeline = DataPipeline(id="orders")
    source = pipeline.define_input("orders")
    selected = pipeline.define_operator(ACTIVE_IDS[0], attributes=dict(SELECT_ATTRIBUTES))
    average = pipeline.define_operator(ACTIVE_IDS[1], attributes=dict(AVG_ATTRIBUTES))
    answer = pipeline.define_output("answer")
    pipeline.set_plan_input(source)
    pipeline.set_plan_output(answer)
    pipeline.connect_nodes(source, selected)
    pipeline.connect_nodes(selected, average)
    pipeline.connect_nodes(average, answer)

    run = PipelineExecutor(observers.registry).execute(pipeline, ORDERS)

    assert not set(ACTIVE_IDS) & set(COHORT_IDS)
    assert run.output_data == ANSWER
    assert run.succeeded
    observers.assert_no_refinement_seam_was_entered()
    observers.assert_no_deprecated_id_was_resolved()
    assert package_warnings(recorded_warnings) == []


def test_the_injected_client_leg_reaches_the_fixed_answer(
    observers: Observers,
    recorded_warnings: list[warnings.WarningMessage],
) -> None:
    """The generator's own allowlist names the cohort, so only the lifecycle can drop it."""

    client = InjectedClient(LLM_PAYLOAD)
    generator = OpenAIPlanGenerator(
        MODEL,
        registry=observers.registry,
        allowed_operator_ids=("plan_discover@2.0.0", "query_breakdown@2.0.0") + ACTIVE_IDS,
        client=cast(Any, client),
    )
    planner = PipelinePlanner(observers.registry, generator)

    run = planner.run(integration_request(), ORDERS)

    assert client.offered_operator_ids == list(ACTIVE_IDS)
    assert [step.operator_id for step in run.planning.selected.steps] == list(ACTIVE_IDS)
    assert run.planning.preflight.operator_ids == ACTIVE_IDS
    assert run.execution.output_data == ANSWER
    assert run.execution.succeeded
    observers.assert_no_refinement_seam_was_entered()
    observers.assert_no_deprecated_id_was_resolved()
    assert package_warnings(recorded_warnings) == []


def test_the_injected_client_leg_never_imports_the_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__
    attempted: list[str] = []

    def recording(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "openai":
            attempted.append(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", recording)
    registry = versioned_registry()
    client = InjectedClient(LLM_PAYLOAD)
    generator = OpenAIPlanGenerator(
        MODEL,
        registry=registry,
        allowed_operator_ids=("plan_discover@2.0.0",) + ACTIVE_IDS,
        client=cast(Any, client),
    )

    run = PipelinePlanner(registry, generator).run(integration_request(), ORDERS)

    assert run.execution.output_data == ANSWER
    assert attempted == []


@pytest.mark.parametrize("operator_id", COHORT_IDS)
def test_a_saved_plan_naming_a_deprecated_operator_parses_but_will_not_run(
    operator_id: str,
    recorded_warnings: list[warnings.WarningMessage],
) -> None:
    """Stored artifacts keep their meaning; neither executor entry will run them.

    Parsing and exact resolution are retained for the whole of v2.x, and both entries have
    always rejected a refinable node, so a saved plan is exactly as (un)runnable as it was
    at 2.7.0. The 3.0.0 break for these records is the loss of `resolve()`, not the loss of
    an execution path that never existed.

    Each entry gets its own deserialization of the same record: `execute()` writes node
    state as it walks a pipeline, so a shared object would tie the second check to whatever
    the first one left behind. It also receives the ordinary input bundle, so its refusal
    cannot be read as a complaint about the data.
    """

    registry = versioned_registry()
    pipeline = DataPipeline(id="saved")
    source = pipeline.define_input("input")
    action = pipeline.define_operator(operator_id, attributes={"query": "How many rows?"})
    answer = pipeline.define_output("answer")
    pipeline.set_plan_input(source)
    pipeline.set_plan_output(answer)
    pipeline.connect_nodes(source, action)
    pipeline.connect_nodes(action, answer)
    record = pipeline.to_dict()

    assert DataPipeline.from_dict(record).to_dict() == record
    assert registry.resolve(operator_id).operator_id == operator_id
    assert package_warnings(recorded_warnings) == []

    with pytest.raises(PipelineError, match="materialized non-refinable") as preflighted:
        PipelineExecutor(registry).preflight(DataPipeline.from_dict(record))
    with pytest.raises(PipelineError, match="materialized non-refinable") as executed:
        PipelineExecutor(registry).execute(DataPipeline.from_dict(record), ORDERS)

    assert str(executed.value) == str(preflighted.value)
    assert package_warnings(recorded_warnings) == []
