from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from itertools import islice
from math import isfinite
from typing import Any, Literal, Protocol, cast

from blue_data_ops.operators.registry import OperatorCard, OperatorRegistry, is_builtin_card
from blue_data_ops.operators.types import DataBundle, ErrorCategory, Properties
from blue_data_ops.plan.context import (
    DataContextProvider,
    DataContextSnapshot,
    DataScope,
    PlanningError,
    PlanningErrorCode,
    PlanningStage,
    RegistryDataContextProvider,
    context_read_failure,
    detached_snapshots,
    invalid_request,
    planning_error,
)
from blue_data_ops.plan.executor import (
    PipelineError,
    PipelineExecutor,
    PipelinePreflight,
    PipelineRun,
)
from blue_data_ops.plan.pipeline import DataPipeline, Node
from blue_data_ops.plan.types import PlanRecord

_PLANNER_OPERATOR_VERSION = "2.0.0"
# The one built-in operator whose attributes name a data-source address.
_ADDRESSED_OPERATOR_NAME = "nl2sql"


def _invalid_generated_plan(
    message: str,
    *,
    stage: PlanningStage = PlanningStage.GENERATION,
    code: PlanningErrorCode = PlanningErrorCode.GENERATION_RESULT_INVALID,
) -> PlanningError:
    return planning_error(
        stage,
        code,
        message,
        category=ErrorCategory.FAILED,
        suggestion="Check the plan generator output.",
    )


def _invalid_compiled_plan(message: str) -> PlanningError:
    return planning_error(
        PlanningStage.COMPILATION,
        PlanningErrorCode.PLAN_INVALID,
        message,
        category=ErrorCategory.RECOVERABLE,
        suggestion="Use discovered 2.0.0 operators in a valid bounded plan.",
    )


def _plan_limit_exceeded(message: str) -> PlanningError:
    return planning_error(
        PlanningStage.COMPILATION,
        PlanningErrorCode.PLAN_LIMIT_EXCEEDED,
        message,
        category=ErrorCategory.RECOVERABLE,
        suggestion="Reduce the plan or raise the corresponding planning limit.",
    )


def _data_context_required() -> PlanningError:
    return planning_error(
        PlanningStage.DATA_CONTEXT,
        PlanningErrorCode.DATA_CONTEXT_REQUIRED,
        "planning a data scope requires a data context provider",
        category=ErrorCategory.RECOVERABLE,
        suggestion="Pass a data_context_provider or plan without a DataScope.",
    )


def _data_context_failed() -> PlanningError:
    return planning_error(
        PlanningStage.DATA_CONTEXT,
        PlanningErrorCode.DATA_CONTEXT_FAILED,
        "data context collection failed",
        category=ErrorCategory.FAILED,
        suggestion="Check the data context provider and try again.",
    )


def _invalid_data_context(
    message: str,
    *,
    code: PlanningErrorCode = PlanningErrorCode.DATA_CONTEXT_RESULT_INVALID,
) -> PlanningError:
    return planning_error(
        PlanningStage.DATA_CONTEXT,
        code,
        message,
        category=ErrorCategory.FAILED,
        suggestion="Check the data context provider output.",
    )


def _scope_anchor(request: PlanningRequest) -> DataScope | None:
    """An immutable copy of the request's scope, safe to compare after foreign calls."""

    scope = request.data_scope
    if scope is None:
        return None
    if type(scope) is not DataScope:
        raise _invalid_data_context("data context scope does not match the planning request")
    return DataScope(scope.source, scope.database, scope.collection, scope.entities)


def _empty_operator_attributes() -> Mapping[str, Mapping[str, Any]]:
    return {}


def _empty_attributes() -> Mapping[str, Any]:
    return {}


def _as_object(value: object) -> object:
    return value


def _is_portable_plan_data(
    value: object,
    *,
    active_containers: set[int] | None = None,
    depth: int = 0,
) -> bool:
    if type(value) in {type(None), bool, int, str}:
        return True
    if type(value) is float:
        return isfinite(value)
    if depth >= 64 or type(value) not in {list, dict}:
        return False

    active: set[int] = set() if active_containers is None else active_containers
    identity = id(value)
    if identity in active:
        return False
    active.add(identity)
    try:
        if type(value) is list:
            return all(
                _is_portable_plan_data(
                    item,
                    active_containers=active,
                    depth=depth + 1,
                )
                for item in cast(list[object], value)
            )
        mapping = cast(dict[object, object], value)
        return all(
            type(key) is str
            and _is_portable_plan_data(
                item,
                active_containers=active,
                depth=depth + 1,
            )
            for key, item in mapping.items()
        )
    finally:
        active.remove(identity)


def _validate_request_data(request: object) -> PlanningRequest:
    if type(request) is not PlanningRequest:
        raise invalid_request("planning request is malformed")
    typed = request
    if type(typed.goal) is not str:
        raise invalid_request("planning request is malformed")
    if not typed.goal.strip():
        raise invalid_request("planning goal must be nonempty")
    if type(typed.input_label) is not str or type(typed.output_label) is not str:
        raise invalid_request("planning request contains a malformed label")
    if type(typed.discovery_queries) is not tuple:
        raise invalid_request("planning request is malformed")
    if not typed.discovery_queries:
        raise invalid_request("at least one discovery query is required")
    for query in typed.discovery_queries:
        if type(query) is not DiscoveryQuery:
            raise invalid_request("planning request is malformed")
        if type(query.text) is not str or type(query.tags) is not tuple:
            raise invalid_request("planning request is malformed")
        if any(type(tag) is not str for tag in query.tags):
            raise invalid_request("planning request is malformed")
        if type(query.limit) is not int or query.limit < 1:
            raise invalid_request("planning request is malformed")
        if not query.text.strip() and not query.tags:
            raise invalid_request("planning request is malformed")
    if type(typed.allowed_operator_ids) is not tuple or any(
        type(operator_id) is not str for operator_id in typed.allowed_operator_ids
    ):
        raise invalid_request("planning request is malformed")
    if typed.data_scope is not None:
        # Re-checked rather than trusted from construction: a frozen dataclass still
        # yields to object.__setattr__, and the scope decides which collection the
        # provider is asked for and which addresses the compiler will accept.
        scope: object = typed.data_scope
        if type(scope) is not DataScope:
            raise invalid_request("planning request is malformed")
        for value in (scope.source, scope.database, scope.collection):
            if type(value) is not str or not value.strip():
                raise invalid_request("planning request is malformed")
        if type(scope.entities) is not tuple or any(
            type(entity) is not str or not entity.strip()
            for entity in cast(tuple[object, ...], scope.entities)
        ):
            raise invalid_request("planning request is malformed")
        if len(set(scope.entities)) != len(scope.entities):
            raise invalid_request("planning request is malformed")
    for name, value in {
        "max_discovery_cards": typed.max_discovery_cards,
        "max_candidates": typed.max_candidates,
        "max_steps": typed.max_steps,
        "max_nodes": typed.max_nodes,
        "max_edges": typed.max_edges,
    }.items():
        if type(value) is not int:
            raise invalid_request("planning request is malformed")
        if value < 1:
            raise invalid_request(f"{name} must be positive")
    raw_operator_attributes: object = typed.operator_attributes
    if type(raw_operator_attributes) is not dict:
        raise invalid_request("planning request contains non-portable data")
    operator_attributes = cast(dict[object, object], raw_operator_attributes)
    for name, attributes in operator_attributes.items():
        if type(name) is not str or type(attributes) is not dict:
            raise invalid_request("planning request contains non-portable data")
        if not _is_portable_plan_data(cast(object, attributes)):
            raise invalid_request("planning request contains non-portable data")
    return typed


def _normalize_draft(
    value: object,
    *,
    stage: PlanningStage,
    code: PlanningErrorCode,
) -> PlanDraft:
    if type(value) is not PlanDraft:
        raise _invalid_generated_plan(
            "plan generator returned a malformed candidate",
            stage=stage,
            code=code,
        )
    draft = value
    if draft.label is not None and type(draft.label) is not str:
        raise _invalid_generated_plan(
            "plan draft contains a malformed label",
            stage=stage,
            code=code,
        )
    if type(draft.steps) is not tuple:
        raise _invalid_generated_plan(
            "plan draft contains malformed steps",
            stage=stage,
            code=code,
        )

    steps: list[PlanStep] = []
    for raw_step in cast(tuple[object, ...], draft.steps):
        if type(raw_step) is not PlanStep:
            raise _invalid_generated_plan(
                "plan draft contains a malformed step",
                stage=stage,
                code=code,
            )
        step = raw_step
        if type(step.step_id) is not str or type(step.operator_id) is not str:
            raise _invalid_generated_plan(
                "plan draft contains a malformed step",
                stage=stage,
                code=code,
            )
        if step.label is not None and type(step.label) is not str:
            raise _invalid_generated_plan(
                "plan draft contains a malformed label",
                stage=stage,
                code=code,
            )
        if type(step.depends_on) is not tuple or any(
            type(dependency) is not str for dependency in step.depends_on
        ):
            raise _invalid_generated_plan(
                "plan draft contains malformed dependencies",
                stage=stage,
                code=code,
            )
        raw_attributes: object = step.attributes
        if type(raw_attributes) is not dict or not _is_portable_plan_data(
            cast(object, raw_attributes)
        ):
            raise _invalid_generated_plan(
                "plan draft contains non-portable data",
                stage=stage,
                code=code,
            )
        steps.append(
            PlanStep(
                step_id=step.step_id,
                operator_id=step.operator_id,
                attributes=deepcopy(cast(dict[str, Any], raw_attributes)),
                depends_on=step.depends_on,
                label=step.label,
            )
        )
    return PlanDraft(steps=tuple(steps), label=draft.label)


# The built-in refiners whose returned plan properties have a known projection contract.
_REFINABLE_SOURCE_IDS = frozenset(
    {
        "multipart_query@2.0.0",
        "nl2query_router@2.0.0",
        "plan_discover@2.0.0",
        "query_breakdown@2.0.0",
    }
)
_PRODUCES_PLAN_TAG = "produces-plan"


def _refinement_error(
    code: PlanningErrorCode,
    message: str,
    *,
    category: ErrorCategory,
    suggestion: str,
    stage: PlanningStage = PlanningStage.GENERATION,
) -> PlanningError:
    return planning_error(stage, code, message, category=category, suggestion=suggestion)


def _ineligible_source() -> PlanningError:
    return _refinement_error(
        PlanningErrorCode.GENERATION_RESULT_INVALID,
        "refinement source is not eligible",
        category=ErrorCategory.RECOVERABLE,
        suggestion="Choose one discovered v2 plan-producing operator.",
    )


def _source_resolution_failed() -> PlanningError:
    return _refinement_error(
        PlanningErrorCode.DISCOVERY_FAILED,
        "refinement source resolution failed",
        category=ErrorCategory.FAILED,
        suggestion="Check the operator registry and discovery filters.",
        stage=PlanningStage.DISCOVERY,
    )


def _refinement_input_copy_failed() -> PlanningError:
    return _refinement_error(
        PlanningErrorCode.GENERATION_FAILED,
        "refinement input could not be copied",
        category=ErrorCategory.FAILED,
        suggestion="Use refinement input and attributes containing copyable data.",
    )


def _refinement_result_invalid() -> PlanningError:
    return _refinement_error(
        PlanningErrorCode.GENERATION_RESULT_INVALID,
        "operator refinement returned an invalid plan result",
        category=ErrorCategory.FAILED,
        suggestion=(
            "Check the refinement operator output and materialize nested refiners separately."
        ),
    )


def _refinement_conversion_failed() -> PlanningError:
    return _refinement_error(
        PlanningErrorCode.GENERATION_FAILED,
        "refinement plan conversion failed",
        category=ErrorCategory.FAILED,
        suggestion="Check the refinement operator and returned plan.",
    )


def _refinement_child_failed() -> PlanningError:
    return _refinement_error(
        PlanningErrorCode.GENERATION_FAILED,
        "refinement plan resolution failed",
        category=ErrorCategory.FAILED,
        suggestion="Check the operator registry and refinement output.",
    )


def _refinement_limit() -> PlanningError:
    return _refinement_error(
        PlanningErrorCode.CANDIDATE_LIMIT_EXCEEDED,
        "operator refinement exceeded a planning limit",
        category=ErrorCategory.RECOVERABLE,
        suggestion="Return fewer alternatives or raise the corresponding planning limit.",
    )


# One operator failure maps to one planning record, so several operator errors collapse by
# severity: a failure outranks a timeout, which outranks a recoverable error.
_OPERATOR_FAILURE_SUGGESTIONS = {
    ErrorCategory.FAILED: "Check the refinement operator and its runtime dependencies.",
    ErrorCategory.TIMEOUT: "Increase the bounded timeout or simplify refinement.",
    ErrorCategory.RECOVERABLE: "Correct the refinement input and try again.",
}


def _operator_refinement_failed(categories: tuple[ErrorCategory, ...]) -> PlanningError:
    for category in (ErrorCategory.FAILED, ErrorCategory.TIMEOUT, ErrorCategory.RECOVERABLE):
        if category in categories:
            chosen = category
            break
    else:
        chosen = ErrorCategory.FAILED
    return _refinement_error(
        PlanningErrorCode.GENERATION_FAILED,
        "operator refinement failed",
        category=chosen,
        suggestion=_OPERATOR_FAILURE_SUGGESTIONS[chosen],
    )


def _exact_str_keyed_dict(value: object) -> dict[str, Any]:
    """Return an exact dict with exact string keys."""

    if type(value) is not dict:
        raise _refinement_result_invalid()
    exact = cast("dict[Any, Any]", value)
    for key in exact:
        if type(key) is not str:
            raise _refinement_result_invalid()
    return cast("dict[str, Any]", exact)


def _exact_str(value: object) -> str:
    """Require an exact string before anything compares it to one."""

    if type(value) is not str:
        raise _refinement_result_invalid()
    return value


def _require_representable_record(
    record: PlanRecord,
    *,
    max_steps: int,
    max_nodes: int,
    max_edges: int,
) -> dict[str, dict[str, Any]]:
    """Validate the returned graph before projecting it to a draft."""

    # Establish every structural container and key before interrogating a value.
    top = _exact_str_keyed_dict(record)
    node_records = _exact_str_keyed_dict(top.get("nodes"))
    if len(node_records) > max_nodes:
        raise _refinement_limit()
    # Every node record, completely, before any edge or membership question is asked of
    # the node map: a key validated late is a key some earlier lookup already trusted.
    for node_id in node_records:
        _exact_str_keyed_dict(node_records[node_id])
    entity_sections = _exact_str_keyed_dict(top.get("entities"))
    operator_entities = _exact_str_keyed_dict(entity_sections.get("OPERATOR"))
    for entity_key in operator_entities:
        _exact_str_keyed_dict(operator_entities[entity_key])

    kinds: dict[str, list[str]] = {"INPUT": [], "OUTPUT": [], "OPERATOR": []}
    adjacency_counts = {"prev": 0, "next": 0}
    for node_id in node_records:
        node = cast("dict[str, Any]", node_records[node_id])
        kind = _exact_str(node.get("type"))
        if kind not in kinds:
            raise _refinement_result_invalid()
        kinds[kind].append(node_id)
        for direction in ("prev", "next"):
            neighbours = node.get(direction)
            if type(neighbours) is not list:
                raise _refinement_result_invalid()
            entries = cast("list[Any]", neighbours)
            adjacency_counts[direction] += len(entries)
            if adjacency_counts[direction] > max_edges:
                raise _refinement_limit()
            for other in entries:
                if type(other) is not str:
                    raise _refinement_result_invalid()
            exact_entries = cast("list[str]", entries)
            if len(exact_entries) != len(set(exact_entries)):
                raise _refinement_result_invalid()
            for other in exact_entries:
                if other not in node_records:
                    raise _refinement_result_invalid()

    if len(kinds["INPUT"]) != 1 or len(kinds["OUTPUT"]) != 1 or not kinds["OPERATOR"]:
        raise _refinement_result_invalid()
    if len(kinds["OPERATOR"]) > max_steps:
        raise _refinement_limit()
    source, sink = kinds["INPUT"][0], kinds["OUTPUT"][0]

    if _exact_str(top.get("input")) != source:
        raise _refinement_result_invalid()
    if _exact_str(top.get("output")) != sink:
        raise _refinement_result_invalid()

    # Other entity sections carry state that a PlanDraft cannot preserve.
    if set(entity_sections) != {"OPERATOR"}:
        raise _refinement_result_invalid()

    # The entity and node hold independently writable links; both must agree.
    by_node: dict[str, dict[str, Any]] = {}
    for key in operator_entities:
        entity_record = cast("dict[str, Any]", operator_entities[key])
        if _exact_str(entity_record.get("id")) != key:
            raise _refinement_result_invalid()
        if _exact_str(entity_record.get("type")) != "OPERATOR":
            raise _refinement_result_invalid()
        owned = entity_record.get("nodes")
        if type(owned) is not list:
            raise _refinement_result_invalid()
        entries = cast("list[Any]", owned)
        if len(entries) != 1:
            raise _refinement_result_invalid()
        node_id = _exact_str(entries[0])
        if node_id not in node_records:
            raise _refinement_result_invalid()
        node = cast("dict[str, Any]", node_records[node_id])
        if _exact_str(node.get("type")) != "OPERATOR" or node_id in by_node:
            raise _refinement_result_invalid()
        # The reverse link, to the same entity, by exact key.
        if _exact_str(node.get("OPERATOR")) != key:
            raise _refinement_result_invalid()
        # Dropping child properties could change execution semantics.
        properties = entity_record.get("properties")
        if type(properties) is not dict:
            raise _refinement_result_invalid()
        if len(cast("dict[Any, Any]", properties)) != 0:
            raise _refinement_result_invalid()
        by_node[node_id] = entity_record
    if set(by_node) != set(kinds["OPERATOR"]):
        raise _refinement_result_invalid()
    # An input or output node claiming an operator entity is a link the projection would
    # never follow, so it would otherwise pass unexamined.
    for node_id in kinds["INPUT"] + kinds["OUTPUT"]:
        if cast("dict[str, Any]", node_records[node_id]).get("OPERATOR") is not None:
            raise _refinement_result_invalid()

    # Unique adjacency plus reciprocal membership establishes one-for-one edges.
    for node_id in node_records:
        node = cast("dict[str, Any]", node_records[node_id])
        for other in cast("list[str]", node.get("next")):
            back = cast("dict[str, Any]", node_records[other])
            if node_id not in cast("list[str]", back.get("prev")):
                raise _refinement_result_invalid()
        for other in cast("list[str]", node.get("prev")):
            back = cast("dict[str, Any]", node_records[other])
            if node_id not in cast("list[str]", back.get("next")):
                raise _refinement_result_invalid()
    if cast("dict[str, Any]", node_records[source]).get("prev"):
        raise _refinement_result_invalid()
    if cast("dict[str, Any]", node_records[sink]).get("next"):
        raise _refinement_result_invalid()

    def reachable(start: str, direction: str) -> set[str]:
        seen: set[str] = set()
        stack = [start]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(
                cast("list[str]", cast("dict[str, Any]", node_records[current]).get(direction))
            )
        return seen

    if reachable(source, "next") != set(node_records):
        raise _refinement_result_invalid()
    if reachable(sink, "prev") != set(node_records):
        raise _refinement_result_invalid()

    remaining = {
        node_id: len(cast("dict[str, Any]", raw).get("prev", []))
        for node_id, raw in node_records.items()
    }
    ready = [node_id for node_id, count in remaining.items() if count == 0]
    settled = 0
    while ready:
        current = ready.pop()
        settled += 1
        for other in cast("list[str]", cast("dict[str, Any]", node_records[current]).get("next")):
            remaining[other] -= 1
            if remaining[other] == 0:
                ready.append(other)
    if settled != len(node_records):
        raise _refinement_result_invalid()

    roots = [
        n for n in kinds["OPERATOR"] if "OPERATOR" not in _neighbour_kinds(node_records, n, "prev")
    ]
    tails = [
        n for n in kinds["OPERATOR"] if "OPERATOR" not in _neighbour_kinds(node_records, n, "next")
    ]
    if len(roots) != 1 or len(tails) != 1:
        raise _refinement_result_invalid()
    root, tail = roots[0], tails[0]

    # Compilation can preserve only these endpoint edges. This rejects direct
    # input-to-output bypasses and endpoint edges to non-root or non-terminal steps.
    source_next = cast("list[str]", cast("dict[str, Any]", node_records[source]).get("next"))
    sink_previous = cast("list[str]", cast("dict[str, Any]", node_records[sink]).get("prev"))
    if source_next != [root] or sink_previous != [tail]:
        raise _refinement_result_invalid()
    return by_node


def _neighbour_kinds(nodes: dict[str, Any], node_id: str, direction: str) -> set[str]:
    # Every type here was established as an exact string by the caller, so this reads
    # them rather than converting them: str() on an unestablished value would be one
    # more place a replaced field gets to answer for itself.
    node = cast("dict[str, Any]", nodes[node_id])
    return {
        cast(str, cast("dict[str, Any]", nodes[other]).get("type"))
        for other in cast("list[str]", node.get(direction))
    }


@dataclass(frozen=True)
class DiscoveryQuery:
    text: str
    tags: tuple[str, ...] = ()
    limit: int = 20

    def __post_init__(self) -> None:
        if (
            type(self.text) is not str
            or type(self.tags) is not tuple
            or any(type(tag) is not str for tag in self.tags)
            or type(self.limit) is not int
        ):
            raise invalid_request("discovery query is malformed")
        if self.limit < 1:
            raise invalid_request("discovery query limit must be positive")
        if not self.text.strip() and not self.tags:
            raise invalid_request("discovery query needs text or tags")


@dataclass(frozen=True)
class PlanningRequest:
    goal: str
    discovery_queries: tuple[DiscoveryQuery, ...]
    operator_attributes: Mapping[str, Mapping[str, Any]] = field(
        default_factory=_empty_operator_attributes
    )
    data_scope: DataScope | None = None
    allowed_operator_ids: tuple[str, ...] = ()
    input_label: str = "input"
    output_label: str = "output"
    max_discovery_cards: int = 40
    max_candidates: int = 8
    max_steps: int = 16
    max_nodes: int = 18
    max_edges: int = 17

    def __post_init__(self) -> None:
        if type(self.goal) is not str:
            raise invalid_request("planning request is malformed")
        if not self.goal.strip():
            raise invalid_request("planning goal must be nonempty")
        if type(self.discovery_queries) is not tuple:
            raise invalid_request("planning request is malformed")
        if not self.discovery_queries:
            raise invalid_request("at least one discovery query is required")
        for name, value in {
            "max_discovery_cards": self.max_discovery_cards,
            "max_candidates": self.max_candidates,
            "max_steps": self.max_steps,
            "max_nodes": self.max_nodes,
            "max_edges": self.max_edges,
        }.items():
            if type(value) is not int:
                raise invalid_request("planning request is malformed")
            if value < 1:
                raise invalid_request(f"{name} must be positive")


@dataclass(frozen=True)
class DiscoverySnapshot:
    cards: tuple[OperatorCard, ...]

    @property
    def operator_ids(self) -> tuple[str, ...]:
        return tuple(card.operator_id for card in self.cards)

    def one(self, name: str) -> OperatorCard:
        matches = [card for card in self.cards if card.name == name]
        if len(matches) != 1:
            raise planning_error(
                PlanningStage.DISCOVERY,
                PlanningErrorCode.DISCOVERY_RESULT_INVALID,
                f"expected one discovered {name!r} operator, got "
                f"{[card.operator_id for card in matches]!r}",
                category=ErrorCategory.RECOVERABLE,
                suggestion="Narrow discovery until exactly one required operator remains.",
            )
        return matches[0]


@dataclass(frozen=True)
class PlanStep:
    step_id: str
    operator_id: str
    attributes: Mapping[str, Any] = field(default_factory=_empty_attributes)
    depends_on: tuple[str, ...] = ()
    label: str | None = None


@dataclass(frozen=True)
class PlanDraft:
    steps: tuple[PlanStep, ...]
    label: str | None = None


@dataclass(frozen=True)
class PlanningResult:
    request: PlanningRequest
    discovery: DiscoverySnapshot
    candidates: tuple[PlanDraft, ...]
    selected: PlanDraft
    pipeline: DataPipeline
    preflight: PipelinePreflight
    data_context: DataContextSnapshot | None = None


@dataclass(frozen=True)
class PlannerRun:
    planning: PlanningResult
    execution: PipelineRun


class PlanGenerator(Protocol):
    def generate(
        self,
        request: PlanningRequest,
        discovery: DiscoverySnapshot,
        data_context: DataContextSnapshot | None,
    ) -> Sequence[PlanDraft]: ...


# Rules and generators take the same three arguments. A rule may ignore the snapshot,
# but the parameter is required so the protocol has a single shape.
PlanRule = Callable[
    [PlanningRequest, DiscoverySnapshot, "DataContextSnapshot | None"],
    "PlanDraft | None",
]


def _invalid_rule_template(message: str) -> PlanningError:
    return planning_error(
        PlanningStage.GENERATION,
        PlanningErrorCode.GENERATION_FAILED,
        message,
        category=ErrorCategory.RECOVERABLE,
        suggestion="Correct the rule template configuration.",
    )


@dataclass(frozen=True)
class RuleTemplateStep:
    """One exact operator slot in a linear rule template."""

    step_id: str
    operator_name: str
    required_attributes: tuple[str, ...]
    expected_tags: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            type(self.step_id) is not str
            or not self.step_id.strip()
            or type(self.operator_name) is not str
            or not self.operator_name.strip()
            or "@" in self.operator_name
            or type(self.required_attributes) is not tuple
            or any(
                type(attribute) is not str or not attribute.strip()
                for attribute in self.required_attributes
            )
            or type(self.expected_tags) is not tuple
            or any(type(tag) is not str or not tag.strip() for tag in self.expected_tags)
        ):
            raise _invalid_rule_template("rule template step is malformed")
        if len(self.required_attributes) != len(set(self.required_attributes)):
            raise _invalid_rule_template("rule template required attributes must be unique")
        if len(self.expected_tags) != len(set(self.expected_tags)):
            raise _invalid_rule_template("rule template expected tags must be unique")


@dataclass(frozen=True)
class RulePlanTemplate:
    """Build a linear draft from exact discovered operators and caller attributes."""

    label: str
    steps: tuple[RuleTemplateStep, ...]

    def __post_init__(self) -> None:
        if (
            type(self.label) is not str
            or not self.label.strip()
            or type(self.steps) is not tuple
            or not self.steps
            or any(type(step) is not RuleTemplateStep for step in self.steps)
        ):
            raise _invalid_rule_template("rule plan template is malformed")
        step_ids = tuple(step.step_id for step in self.steps)
        operator_names = tuple(step.operator_name for step in self.steps)
        if len(step_ids) != len(set(step_ids)):
            raise _invalid_rule_template("rule template step ids must be unique")
        if len(operator_names) != len(set(operator_names)):
            raise _invalid_rule_template("rule template operator names must be unique")

    def generate(
        self,
        request: PlanningRequest,
        discovery: DiscoverySnapshot,
        data_context: DataContextSnapshot | None,
    ) -> PlanDraft:
        del data_context  # a linear template plans from discovery and caller attributes
        typed_request = _validate_request_data(request)
        if (
            type(discovery) is not DiscoverySnapshot
            or type(discovery.cards) is not tuple
            or any(type(card) is not OperatorCard for card in discovery.cards)
        ):
            raise planning_error(
                PlanningStage.DISCOVERY,
                PlanningErrorCode.DISCOVERY_RESULT_INVALID,
                "rule template received a malformed discovery snapshot",
                category=ErrorCategory.RECOVERABLE,
                suggestion="Use the discovery snapshot returned by PipelinePlanner.",
            )

        names = tuple(step.operator_name for step in self.steps)
        display_names = " and ".join(names)
        plan_steps: list[PlanStep] = []
        previous_step_id: str | None = None
        for template_step in self.steps:
            card = discovery.one(template_step.operator_name)
            if (
                card.operator_id != f"{template_step.operator_name}@{_PLANNER_OPERATOR_VERSION}"
                or card.version != _PLANNER_OPERATOR_VERSION
                or card.tags != template_step.expected_tags
            ):
                raise planning_error(
                    PlanningStage.DISCOVERY,
                    PlanningErrorCode.DISCOVERY_RESULT_INVALID,
                    f"discovered {template_step.operator_name!r} metadata does not match "
                    "the rule template",
                    category=ErrorCategory.RECOVERABLE,
                    suggestion="Use the versioned built-in registry or update the rule template.",
                )
            try:
                attributes = deepcopy(
                    dict(typed_request.operator_attributes[template_step.operator_name])
                )
            except (KeyError, TypeError, ValueError):
                raise invalid_request(
                    f"{display_names} attributes are required for the {self.label} template"
                ) from None
            if not set(template_step.required_attributes).issubset(attributes):
                raise invalid_request(
                    f"{display_names} attributes are incomplete for the {self.label} template"
                )
            plan_steps.append(
                PlanStep(
                    step_id=template_step.step_id,
                    operator_id=card.operator_id,
                    attributes=attributes,
                    depends_on=(() if previous_step_id is None else (previous_step_id,)),
                )
            )
            previous_step_id = template_step.step_id
        return PlanDraft(steps=tuple(plan_steps), label=self.label)

    def __call__(
        self,
        request: PlanningRequest,
        discovery: DiscoverySnapshot,
        data_context: DataContextSnapshot | None,
    ) -> PlanDraft:
        return self.generate(request, discovery, data_context)


_PROJECT_TEMPLATE_STEP = RuleTemplateStep(
    step_id="project",
    operator_name="project",
    required_attributes=("kept_keys",),
    expected_tags=(
        "domain-relational",
        "flow-transform",
        "accepts-data",
        "produces-data",
        "capability-projection",
    ),
)

_AGGREGATE_TEMPLATE_FIELDS: Mapping[
    str,
    tuple[tuple[str, ...], tuple[str, ...]],
] = {
    "avg": (
        ("avg_key", "output_key"),
        (
            "domain-arithmetic",
            "flow-aggregate",
            "accepts-data",
            "produces-data",
            "capability-average",
            "capability-reduction",
        ),
    ),
    "sum": (
        ("sum_key", "output_key"),
        (
            "domain-arithmetic",
            "flow-aggregate",
            "accepts-data",
            "produces-data",
            "capability-reduction",
            "capability-sum",
        ),
    ),
    "min": (
        ("min_key", "output_key"),
        (
            "domain-arithmetic",
            "flow-aggregate",
            "accepts-data",
            "produces-data",
            "capability-extrema",
            "capability-reduction",
        ),
    ),
    "max": (
        ("max_key", "output_key"),
        (
            "domain-arithmetic",
            "flow-aggregate",
            "accepts-data",
            "produces-data",
            "capability-extrema",
            "capability-reduction",
        ),
    ),
}

SELECT_THEN_AVERAGE_TEMPLATE = RulePlanTemplate(
    label="select-then-average",
    steps=(
        RuleTemplateStep(
            step_id="select",
            operator_name="select",
            required_attributes=("operand_key", "operand", "operand_val"),
            expected_tags=(
                "domain-relational",
                "flow-transform",
                "accepts-data",
                "produces-data",
                "capability-filter",
            ),
        ),
        RuleTemplateStep(
            step_id="average",
            operator_name="avg",
            required_attributes=("avg_key", "output_key"),
            expected_tags=(
                "domain-arithmetic",
                "flow-aggregate",
                "accepts-data",
                "produces-data",
                "capability-average",
                "capability-reduction",
            ),
        ),
    ),
)

_PROJECT_AGGREGATE_TEMPLATES: Mapping[str, RulePlanTemplate] = {
    name: RulePlanTemplate(
        label=f"project-then-{name}",
        steps=(
            _PROJECT_TEMPLATE_STEP,
            RuleTemplateStep(
                step_id=name,
                operator_name=name,
                required_attributes=required_attributes,
                expected_tags=expected_tags,
            ),
        ),
    )
    for name, (required_attributes, expected_tags) in _AGGREGATE_TEMPLATE_FIELDS.items()
}


def project_then_aggregate_template(
    aggregate_name: Literal["avg", "sum", "min", "max"],
) -> RulePlanTemplate:
    """Return the project-to-aggregate template for an exact operator name."""

    if type(aggregate_name) is not str or aggregate_name not in _PROJECT_AGGREGATE_TEMPLATES:
        raise _invalid_rule_template(
            "unsupported aggregate operator; expected avg, sum, min, or max"
        )
    return _PROJECT_AGGREGATE_TEMPLATES[aggregate_name]


class RulePlanGenerator:
    """Generate plan candidates from deterministic caller-supplied rules."""

    def __init__(self, rules: Sequence[PlanRule] | None = None) -> None:
        self._rules = tuple(rules) if rules is not None else (_select_then_average_rule,)
        if not self._rules:
            raise planning_error(
                PlanningStage.GENERATION,
                PlanningErrorCode.GENERATION_FAILED,
                "at least one planning rule is required",
                category=ErrorCategory.RECOVERABLE,
                suggestion="Provide at least one planning rule.",
            )

    def generate(
        self,
        request: PlanningRequest,
        discovery: DiscoverySnapshot,
        data_context: DataContextSnapshot | None,
    ) -> tuple[PlanDraft, ...]:
        return tuple(
            candidate
            for rule in self._rules
            if (candidate := rule(request, discovery, data_context)) is not None
        )


class RequireSinglePlan:
    def select(self, candidates: Sequence[PlanDraft]) -> PlanDraft:
        if not candidates:
            raise planning_error(
                PlanningStage.SELECTION,
                PlanningErrorCode.NO_CANDIDATES,
                "planning produced no candidates",
                category=ErrorCategory.RECOVERABLE,
                suggestion="Adjust discovery or generation so at least one plan is produced.",
            )
        if len(candidates) != 1:
            raise planning_error(
                PlanningStage.SELECTION,
                PlanningErrorCode.AMBIGUOUS_CANDIDATES,
                f"planning produced {len(candidates)} candidates",
                category=ErrorCategory.RECOVERABLE,
                suggestion="Provide a selector that chooses one plan.",
            )
        return candidates[0]


class PipelinePlanner:
    """Discover, generate, select, compile, and optionally execute a local plan."""

    def __init__(
        self,
        registry: OperatorRegistry,
        generator: PlanGenerator,
        selector: RequireSinglePlan | None = None,
        data_context_provider: DataContextProvider | None = None,
    ) -> None:
        self._registry = registry
        self._generator = generator
        self._selector = selector or RequireSinglePlan()
        self._executor = PipelineExecutor(registry)
        self._data_context_provider = data_context_provider

    def discover(self, request: PlanningRequest) -> DiscoverySnapshot:
        typed_request = _validate_request_data(request)
        try:
            return self._discover(typed_request)
        except Exception:
            raise planning_error(
                PlanningStage.DISCOVERY,
                PlanningErrorCode.DISCOVERY_FAILED,
                "operator discovery failed",
                category=ErrorCategory.FAILED,
                suggestion="Check the operator registry and discovery filters.",
            ) from None

    def _discover(self, request: PlanningRequest) -> DiscoverySnapshot:
        allowed = set(request.allowed_operator_ids)
        cards: list[OperatorCard] = []
        seen: set[str] = set()
        for query in request.discovery_queries:
            matches = self._registry.find(query.text, tags=query.tags)
            query_count = 0
            for card in matches:
                if card.version != _PLANNER_OPERATOR_VERSION:
                    continue
                if allowed and card.operator_id not in allowed:
                    continue
                if card.operator_id in seen:
                    continue
                cards.append(card)
                seen.add(card.operator_id)
                query_count += 1
                if len(cards) >= request.max_discovery_cards:
                    return DiscoverySnapshot(tuple(cards))
                if query_count >= query.limit:
                    break
        return DiscoverySnapshot(tuple(cards))

    def plan(self, request: PlanningRequest) -> PlanningResult:
        typed_request = _validate_request_data(request)
        # Anchored before the first caller callback. Discovery already calls the
        # caller-supplied registry, so an anchor taken after it would record a scope that
        # callback had already been free to change.
        scope_anchor = _scope_anchor(typed_request)
        discovery = self.discover(typed_request)
        self._require_anchor(typed_request, scope_anchor)
        # Two detached copies of one canonical document. The generator gets the
        # first and may do what it likes with it; `retained` never leaves this frame
        # until it lands on the result, so no later callback can reach it.
        generator_context, retained = self._collect_data_context(typed_request, scope_anchor)
        candidates = self._generate_candidates(typed_request, discovery, generator_context)
        _validate_request_data(typed_request)
        self._require_anchor(typed_request, scope_anchor)
        selected = self._select_candidate(candidates)
        self._require_anchor(typed_request, scope_anchor)
        try:
            pipeline = self._compile(typed_request, selected, discovery, scope_anchor)
        except PlanningError:
            raise
        except Exception:
            raise planning_error(
                PlanningStage.COMPILATION,
                PlanningErrorCode.COMPILATION_FAILED,
                "plan compilation failed",
                category=ErrorCategory.FAILED,
                suggestion="Check the plan compiler.",
            ) from None
        try:
            preflight = self._executor.preflight(pipeline)
        except PlanningError:
            raise
        except PipelineError as error:
            raise planning_error(
                PlanningStage.PREFLIGHT,
                PlanningErrorCode.PREFLIGHT_FAILED,
                str(error),
                category=ErrorCategory.RECOVERABLE,
                suggestion="Check operator resolution and materialize refinable steps.",
            ) from None
        except Exception:
            raise planning_error(
                PlanningStage.PREFLIGHT,
                PlanningErrorCode.PREFLIGHT_FAILED,
                "plan preflight failed",
                category=ErrorCategory.FAILED,
                suggestion="Check the planner registry and compiled pipeline.",
            ) from None
        self._require_anchor(typed_request, scope_anchor)
        try:
            request_snapshot = deepcopy(typed_request)
        except Exception:
            raise planning_error(
                PlanningStage.COMPILATION,
                PlanningErrorCode.RESULT_COPY_FAILED,
                "planning request could not be copied",
                category=ErrorCategory.FAILED,
                suggestion="Use a planning request containing portable data.",
            ) from None
        return PlanningResult(
            request=request_snapshot,
            discovery=discovery,
            candidates=candidates,
            selected=selected,
            pipeline=pipeline,
            preflight=preflight,
            data_context=retained,
        )

    def _require_anchor(self, request: PlanningRequest, anchor: DataScope | None) -> None:
        """Fail unless the request still carries the scope it was accepted with."""

        if _scope_anchor(request) != anchor:
            raise _invalid_data_context(
                "data context scope does not match the planning request",
                code=PlanningErrorCode.DATA_CONTEXT_SCOPE_MISMATCH,
            )

    def _collect_data_context(
        self,
        request: PlanningRequest,
        anchor: DataScope | None,
    ) -> tuple[DataContextSnapshot | None, DataContextSnapshot | None]:
        """Collect one snapshot and return the generator's copy and the retained copy."""

        scope = anchor
        if scope is None:
            # No scope, no provider call: a scopeless request must not reach the
            # registry at all, whether or not a provider was configured.
            return None, None
        provider = self._data_context_provider
        if provider is None:
            raise _data_context_required()
        # The provider never receives the request's own scope object: it would be free
        # to mutate it in place, and every later comparison — including the compiler's
        # address check — reads that same object. `expected` is a second copy that
        # never leaves this frame, so mutating the handed-out one is detected here
        # rather than after the generator has already seen the snapshot.
        handed_out = DataScope(scope.source, scope.database, scope.collection, scope.entities)
        expected = DataScope(scope.source, scope.database, scope.collection, scope.entities)
        # Trust follows the code path, not the object's type: an instance-level
        # `collect` shadow keeps `type(provider) is RegistryDataContextProvider` true,
        # so the trusted branch calls the class implementation directly and a shadow is
        # never invoked.
        trusted = type(provider) is RegistryDataContextProvider
        try:
            if trusted:
                collected = RegistryDataContextProvider.collect(provider, handed_out)
            else:
                collected = provider.collect(handed_out)
        except PlanningError:
            # The class implementation reaches the caller's registry only inside
            # `_read()` and dispatches through no replaceable attribute, so a
            # PlanningError out of the trusted branch was raised by package code and
            # carries a package record. Those outcomes have to stay distinct — a limit
            # violation is recoverable, an unregistered entity is actionable — so they
            # surface as they are. A foreign provider gets one generic record instead.
            if trusted:
                raise
            raise context_read_failure() from None
        except Exception:
            raise _data_context_failed() from None

        # Exact type, not isinstance: a subclass can override to_dict() or skip the
        # validating __post_init__, so a lookalike carries none of the guarantees the
        # planner is about to rely on. Everything after this point is package-built.
        if type(collected) is not DataContextSnapshot:
            raise _invalid_data_context("data context provider returned a malformed snapshot")
        try:
            generator_copy, retained = detached_snapshots(collected)
        except PlanningError:
            raise
        except Exception:
            raise _invalid_data_context(
                "data context provider returned a malformed snapshot"
            ) from None
        # Safe only after the rebuild: both scopes are now package-owned DataScope
        # instances holding exact strings, so this cannot run a hostile __eq__.
        if retained.scope != expected:
            raise _invalid_data_context(
                "data context scope does not match the planning request",
                code=PlanningErrorCode.DATA_CONTEXT_SCOPE_MISMATCH,
            )
        # A partial projection needs no separate check here: construction proves the
        # snapshot resolves its own scope's projection exactly, and the equality above
        # proves that scope is the request's. Completeness for a whole-collection
        # request stays the adapter's guarantee — the planner cannot prove it for an
        # arbitrary provider.
        return generator_copy, retained

    def _generate_candidates(
        self,
        request: PlanningRequest,
        discovery: DiscoverySnapshot,
        data_context: DataContextSnapshot | None,
    ) -> tuple[PlanDraft, ...]:
        try:
            generated = self._generator.generate(request, discovery, data_context)
        except PlanningError:
            raise
        except Exception:
            raise planning_error(
                PlanningStage.GENERATION,
                PlanningErrorCode.GENERATION_FAILED,
                "plan generation failed",
                category=ErrorCategory.FAILED,
                suggestion="Check the plan generator and try again.",
            ) from None
        raw_generated = _as_object(generated)
        if isinstance(raw_generated, (str, bytes)) or not isinstance(raw_generated, Sequence):
            raise _invalid_generated_plan("plan generator returned malformed candidates")
        try:
            candidate_sequence = cast(Sequence[object], raw_generated)
            raw_candidates = tuple(islice(iter(candidate_sequence), request.max_candidates + 1))
        except PlanningError:
            raise
        except Exception:
            raise planning_error(
                PlanningStage.GENERATION,
                PlanningErrorCode.GENERATION_FAILED,
                "plan candidate iteration failed",
                category=ErrorCategory.FAILED,
                suggestion="Check the plan generator and try again.",
            ) from None
        if len(raw_candidates) > request.max_candidates:
            raise planning_error(
                PlanningStage.GENERATION,
                PlanningErrorCode.CANDIDATE_LIMIT_EXCEEDED,
                "planning exceeded its candidate limit",
                category=ErrorCategory.RECOVERABLE,
                suggestion="Return fewer candidates or raise max_candidates.",
            )
        return tuple(
            _normalize_draft(
                candidate,
                stage=PlanningStage.GENERATION,
                code=PlanningErrorCode.GENERATION_RESULT_INVALID,
            )
            for candidate in raw_candidates
        )

    def _select_candidate(self, candidates: tuple[PlanDraft, ...]) -> PlanDraft:
        selector_candidates = tuple(
            _normalize_draft(
                candidate,
                stage=PlanningStage.SELECTION,
                code=PlanningErrorCode.SELECTION_RESULT_INVALID,
            )
            for candidate in candidates
        )
        try:
            selected = self._selector.select(selector_candidates)
        except PlanningError:
            raise
        except Exception:
            raise planning_error(
                PlanningStage.SELECTION,
                PlanningErrorCode.SELECTION_FAILED,
                "plan selection failed",
                category=ErrorCategory.FAILED,
                suggestion="Check the plan selector and try again.",
            ) from None
        return _normalize_draft(
            selected,
            stage=PlanningStage.SELECTION,
            code=PlanningErrorCode.SELECTION_RESULT_INVALID,
        )

    def plan_refinement(
        self,
        request: PlanningRequest,
        source_operator_id: str,
        input_data: DataBundle,
        attributes: Mapping[str, Any],
        properties: Properties | None = None,
    ) -> PlanningResult:
        """Plan from one built-in refiner's normalized alternatives.

        The caller names the source because eligible refiners take different inputs and
        may reach an LLM or registry. Returned pipelines are projected into drafts,
        selected, freshly compiled, and preflighted.
        """

        typed_request = _validate_request_data(request)
        scope_anchor = _scope_anchor(typed_request)
        discovery = self.discover(typed_request)
        self._require_anchor(typed_request, scope_anchor)
        resolved = self._eligible_refinement_source(typed_request, discovery, source_operator_id)
        self._require_anchor(typed_request, scope_anchor)
        alternatives, categories = self._refine_once(resolved, input_data, attributes, properties)
        # The refiner is caller-reachable code that just ran with caller-owned input, so
        # the request is revalidated exactly as it is after a generator call.
        _validate_request_data(typed_request)
        self._require_anchor(typed_request, scope_anchor)
        if categories:
            raise _operator_refinement_failed(categories)

        drafts, child_ids = self._convert_alternatives(typed_request, alternatives)
        extended = self._extend_discovery(typed_request, discovery, child_ids)
        self._require_anchor(typed_request, scope_anchor)
        selected = self._select_candidate(drafts)
        self._require_anchor(typed_request, scope_anchor)
        pipeline = self._compile(typed_request, selected, extended, scope_anchor)
        try:
            preflight = self._executor.preflight(pipeline)
        except PlanningError:
            raise
        except PipelineError as error:
            raise planning_error(
                PlanningStage.PREFLIGHT,
                PlanningErrorCode.PREFLIGHT_FAILED,
                str(error),
                category=ErrorCategory.RECOVERABLE,
                suggestion="Check operator resolution and materialize refinable steps.",
            ) from None
        except Exception:
            raise planning_error(
                PlanningStage.PREFLIGHT,
                PlanningErrorCode.PREFLIGHT_FAILED,
                "plan preflight failed",
                category=ErrorCategory.FAILED,
                suggestion="Check the planner registry and compiled pipeline.",
            ) from None
        self._require_anchor(typed_request, scope_anchor)
        try:
            request_snapshot = deepcopy(typed_request)
        except Exception:
            raise planning_error(
                PlanningStage.COMPILATION,
                PlanningErrorCode.RESULT_COPY_FAILED,
                "planning request could not be copied",
                category=ErrorCategory.FAILED,
                suggestion="Use a planning request containing portable data.",
            ) from None
        return PlanningResult(
            request=request_snapshot,
            discovery=extended,
            candidates=drafts,
            selected=selected,
            pipeline=pipeline,
            preflight=preflight,
        )

    def _eligible_refinement_source(
        self,
        request: PlanningRequest,
        discovery: DiscoverySnapshot,
        source_operator_id: object,
    ) -> Any:
        """Resolve an eligible package-built refinement source.

        Provenance and exact bound callables exclude public-registration lookalikes.
        This is an API boundary, not in-process tamper resistance.
        """

        if type(source_operator_id) is not str:
            raise _ineligible_source()
        if not source_operator_id.endswith(f"@{_PLANNER_OPERATOR_VERSION}"):
            raise _ineligible_source()
        if source_operator_id not in _REFINABLE_SOURCE_IDS:
            raise _ineligible_source()
        if source_operator_id not in discovery.operator_ids:
            raise _ineligible_source()
        # Refinement requires explicit admission for the source and every child.
        allowed = request.allowed_operator_ids
        if type(allowed) is not tuple or not allowed:
            raise _ineligible_source()
        if source_operator_id not in allowed:
            raise _ineligible_source()

        try:
            card = self._registry.get_card(source_operator_id)
            resolved = self._registry.resolve(source_operator_id)
        except Exception:
            raise _source_resolution_failed() from None
        if card is None or not is_builtin_card(self._registry, card):
            raise _ineligible_source()
        if _PRODUCES_PLAN_TAG not in card.tags:
            raise _ineligible_source()

        from blue_data_ops.operators.multipart_query_operator import MultipartQueryOperator
        from blue_data_ops.operators.nl2query_router_operator import NL2QueryRouterOperator
        from blue_data_ops.operators.plan_discover_operator import PlanDiscoverOperator
        from blue_data_ops.operators.query_breakdown_operator import QueryBreakdownOperator
        from blue_data_ops.plan.refiner import RefinableOperator

        expected_types = {
            "multipart_query@2.0.0": MultipartQueryOperator,
            "nl2query_router@2.0.0": NL2QueryRouterOperator,
            "plan_discover@2.0.0": PlanDiscoverOperator,
            "query_breakdown@2.0.0": QueryBreakdownOperator,
        }
        expected_type = expected_types[source_operator_id]
        if type(resolved) is not expected_type:
            raise _ineligible_source()
        expected_functions = {
            "refine": RefinableOperator.refine,
            "refiner": expected_type.refiner,
            "_refiner": expected_type._refiner,  # pyright: ignore[reportPrivateUsage]
        }
        for name, expected_function in expected_functions.items():
            bound = getattr(resolved, name, None)
            if (
                getattr(bound, "__self__", None) is not resolved
                or getattr(bound, "__func__", None) is not expected_function
            ):
                raise _ineligible_source()
        return resolved

    def _refine_once(
        self,
        resolved: Any,
        input_data: DataBundle,
        attributes: Mapping[str, Any],
        properties: Properties | None,
    ) -> tuple[tuple[object, ...], tuple[ErrorCategory, ...]]:
        """Call `refine()` exactly once and validate the transient result shape."""

        try:
            call_input = deepcopy(input_data)
            call_attributes = deepcopy(dict(attributes))
        except Exception:
            raise _refinement_input_copy_failed() from None
        try:
            outcome = resolved.refine(call_input, call_attributes, properties)
        except PlanningError:
            raise
        except Exception:
            raise _refinement_error(
                PlanningErrorCode.GENERATION_FAILED,
                "operator refinement failed",
                category=ErrorCategory.FAILED,
                suggestion="Check the refinement operator and its runtime dependencies.",
            ) from None

        if type(outcome) is not tuple:
            raise _refinement_result_invalid()
        pair = cast("tuple[object, ...]", outcome)
        if len(pair) != 2:
            raise _refinement_result_invalid()
        plans, meta = pair
        if type(plans) is not list:
            raise _refinement_result_invalid()
        alternatives: tuple[object, ...] = tuple(cast("list[object]", plans))
        # Lookalikes do not carry the normalized refinement contract.
        from blue_data_ops.operators.types import ErrorCode, ErrorRecord, ErrorStage, ExecMeta

        if type(meta) is not ExecMeta:
            raise _refinement_result_invalid()
        errors = meta.errors
        if type(errors) is not list:
            raise _refinement_result_invalid()
        categories: list[ErrorCategory] = []
        for record in cast("list[object]", errors):
            if type(record) is not ErrorRecord:
                raise _refinement_result_invalid()
            if (
                type(record.category) is not ErrorCategory
                or type(record.code) is not ErrorCode
                or type(record.stage) is not ErrorStage
                or type(record.operator_id) is not str
                or type(record.message) is not str
                or type(record.retryable) is not bool
                or (record.suggestion is not None and type(record.suggestion) is not str)
            ):
                raise _refinement_result_invalid()
            categories.append(record.category)
        # A refiner reporting errors must not also hand back plans; accepting both would
        # leave the planner deciding which half of a contradictory result to believe.
        if categories and alternatives:
            raise _refinement_result_invalid()
        is_empty = meta.is_empty
        if type(is_empty) is not bool:
            raise _refinement_result_invalid()
        if not categories and is_empty != (len(alternatives) == 0):
            raise _refinement_result_invalid()
        return alternatives, tuple(categories)

    def _convert_alternatives(
        self,
        request: PlanningRequest,
        alternatives: tuple[object, ...],
    ) -> tuple[tuple[PlanDraft, ...], tuple[str, ...]]:
        """Project each returned pipeline into an isolated draft, in returned order.

        The whole batch fails on the first bad alternative. Dropping one and keeping the
        rest would hand the selector a silently narrowed candidate set, which is the one
        outcome a caller could not detect from the result.
        """

        if len(alternatives) > request.max_candidates:
            raise _refinement_limit()
        drafts: list[PlanDraft] = []
        child_ids: list[str] = []
        for alternative in alternatives:
            draft, ids = self._project_alternative(request, alternative)
            drafts.append(draft)
            for operator_id in ids:
                if operator_id not in child_ids:
                    child_ids.append(operator_id)
        return tuple(drafts), tuple(child_ids)

    def _project_alternative(
        self,
        request: PlanningRequest,
        alternative: object,
    ) -> tuple[PlanDraft, tuple[str, ...]]:
        if type(alternative) is not DataPipeline:
            raise _refinement_result_invalid()
        try:
            # Class dispatch, and only the graph containers are read. Plan properties,
            # values, provenance, sync state, status, and statuses are all discarded, so
            # an object that raises on copy or comparison in one of them cannot affect a
            # conversion that never touches it.
            record = DataPipeline.to_dict(alternative)
        except Exception:
            raise _refinement_conversion_failed() from None
        if type(record) is not dict:
            raise _refinement_result_invalid()

        # The whole record, before anything is projected out of it.
        by_node = _require_representable_record(
            record,
            max_steps=request.max_steps,
            max_nodes=request.max_nodes,
            max_edges=request.max_edges,
        )
        node_records = cast("dict[str, Any]", record["nodes"])
        ordered = self._operator_order(node_records, by_node)
        steps: list[PlanStep] = []
        child_ids: list[str] = []
        position = {node_id: index for index, node_id in enumerate(ordered)}
        for index, node_id in enumerate(ordered, start=1):
            entity_record = by_node[node_id]
            operator_id = entity_record.get("operator_id")
            if type(operator_id) is not str:
                raise _refinement_result_invalid()
            attributes = entity_record.get("attributes")
            if type(attributes) is not dict or not _is_portable_plan_data(
                cast("object", attributes)
            ):
                raise _refinement_result_invalid()
            node = node_records.get(node_id)
            if type(node) is not dict:
                raise _refinement_result_invalid()
            previous = cast("dict[str, Any]", node).get("prev")
            if type(previous) is not list:
                raise _refinement_result_invalid()
            depends = tuple(
                f"step-{position[str(other)] + 1:03d}"
                for other in cast("list[Any]", previous)
                if type(other) is str and other in position
            )
            label = cast("dict[str, Any]", node).get("label")
            if label is not None and type(label) is not str:
                raise _refinement_result_invalid()
            steps.append(
                PlanStep(
                    step_id=f"step-{index:03d}",
                    operator_id=operator_id,
                    attributes=deepcopy(cast("dict[str, Any]", attributes)),
                    depends_on=depends,
                    label=label,
                )
            )
            if operator_id not in child_ids:
                child_ids.append(operator_id)
        if not steps:
            raise _refinement_result_invalid()
        if len(steps) > request.max_steps:
            raise _refinement_limit()
        draft = _normalize_draft(
            PlanDraft(steps=tuple(steps)),
            stage=PlanningStage.GENERATION,
            code=PlanningErrorCode.GENERATION_RESULT_INVALID,
        )
        return draft, tuple(child_ids)

    def _operator_order(
        self,
        nodes: dict[str, Any],
        operator_nodes: dict[str, dict[str, Any]],
    ) -> list[str]:
        """Stable topological order over operator nodes only."""

        remaining = dict.fromkeys(operator_nodes)
        ordered: list[str] = []
        while remaining:
            ready: list[str] = []
            for node_id in remaining:
                node = nodes.get(node_id)
                if type(node) is not dict:
                    raise _refinement_result_invalid()
                previous = cast("dict[str, Any]", node).get("prev")
                if type(previous) is not list:
                    raise _refinement_result_invalid()
                pending = [
                    other
                    for other in cast("list[Any]", previous)
                    if type(other) is str and other in remaining
                ]
                if not pending:
                    ready.append(node_id)
            if not ready:
                # A cycle among operator nodes: not representable as a PlanDraft.
                raise _refinement_result_invalid()
            for node_id in ready:
                ordered.append(node_id)
                del remaining[node_id]
        return ordered

    def _extend_discovery(
        self,
        request: PlanningRequest,
        discovery: DiscoverySnapshot,
        child_ids: tuple[str, ...],
    ) -> DiscoverySnapshot:
        """Add first-seen child cards by exact id, never by text discovery.

        Refinement legitimately introduces operators the request's query never named, so
        the snapshot has to grow. It grows only by exact pinned id resolved in this same
        registry, so it cannot pull in a v1 card, a rewritten id, or a "latest".
        """

        cards = list(discovery.cards)
        known = {card.operator_id for card in cards}
        allowed = request.allowed_operator_ids
        if type(allowed) is not tuple or not allowed:
            raise _ineligible_source()
        from blue_data_ops.plan.refiner import RefinableOperator

        for operator_id in child_ids:
            # Check every child, including one already present in the snapshot.
            if operator_id not in allowed:
                raise _refinement_result_invalid()
            try:
                card = self._registry.get_card(operator_id)
            except Exception:
                raise _refinement_child_failed() from None
            if card is None or card.version != _PLANNER_OPERATOR_VERSION:
                raise _refinement_result_invalid()
            try:
                resolved = self._registry.resolve(operator_id)
            except Exception:
                raise _refinement_child_failed() from None
            # Recursive refinement has no materialization contract here.
            if isinstance(resolved, RefinableOperator):
                raise _refinement_result_invalid()
            if operator_id in known:
                continue
            cards.append(card)
            known.add(operator_id)
        if len(cards) > request.max_discovery_cards:
            raise _refinement_limit()
        return DiscoverySnapshot(tuple(cards))

    def execute(
        self,
        planning: PlanningResult,
        input_data: DataBundle,
        properties: Properties | None = None,
    ) -> PipelineRun:
        pipeline = DataPipeline.from_dict(deepcopy(planning.pipeline.to_dict()))
        return self._executor.execute(pipeline, input_data, properties)

    def run(
        self,
        request: PlanningRequest,
        input_data: DataBundle,
        properties: Properties | None = None,
    ) -> PlannerRun:
        planning = self.plan(request)
        return PlannerRun(
            planning=planning,
            execution=self.execute(planning, input_data, properties),
        )

    def _compile(
        self,
        request: PlanningRequest,
        draft: PlanDraft,
        discovery: DiscoverySnapshot,
        scope: DataScope | None = None,
    ) -> DataPipeline:
        raw_steps = cast(tuple[object, ...], draft.steps)
        if not raw_steps:
            raise _invalid_compiled_plan("plan draft has no steps")
        if any(not isinstance(step, PlanStep) for step in raw_steps):
            raise _invalid_compiled_plan("plan draft contains a malformed step")
        steps = cast(tuple[PlanStep, ...], raw_steps)
        if len(steps) > request.max_steps or len(steps) + 2 > request.max_nodes:
            raise _plan_limit_exceeded("plan draft exceeds its node limit")

        raw_step_ids = [cast(object, step.step_id) for step in steps]
        if any(not isinstance(step_id, str) or not step_id.strip() for step_id in raw_step_ids):
            raise _invalid_compiled_plan("plan step ids must be nonempty")
        step_ids = cast(list[str], raw_step_ids)
        if len(step_ids) != len(set(step_ids)):
            raise _invalid_compiled_plan("plan step ids must be unique")

        discovered_ids = set(discovery.operator_ids)
        by_id = {step.step_id: step for step in steps}
        successor_ids: dict[str, list[str]] = {step.step_id: [] for step in steps}
        edge_count = 0
        for step in steps:
            raw_operator_id = cast(object, step.operator_id)
            if not isinstance(raw_operator_id, str) or not raw_operator_id.endswith(
                f"@{_PLANNER_OPERATOR_VERSION}"
            ):
                raise _invalid_compiled_plan(
                    f"planner requires @{_PLANNER_OPERATOR_VERSION} operator ids"
                )
            operator_id = raw_operator_id
            if operator_id not in discovered_ids:
                raise _invalid_compiled_plan(f"operator {operator_id!r} was not discovered")
            if operator_id.split("@", 1)[0] == _ADDRESSED_OPERATOR_NAME:
                _check_addressed_step(scope, step)
            raw_dependencies = cast(tuple[object, ...], step.depends_on)
            if any(not isinstance(dependency, str) for dependency in raw_dependencies):
                raise _invalid_compiled_plan(f"step {step.step_id!r} has a malformed dependency")
            dependencies = cast(tuple[str, ...], raw_dependencies)
            if len(dependencies) != len(set(dependencies)):
                raise _invalid_compiled_plan(f"step {step.step_id!r} has duplicate dependencies")
            for dependency in dependencies:
                if dependency not in by_id:
                    raise _invalid_compiled_plan(
                        f"step {step.step_id!r} depends on unknown step {dependency!r}"
                    )
                successor_ids[dependency].append(step.step_id)
                edge_count += 1

        _topological_steps(by_id)
        roots = [step.step_id for step in steps if not step.depends_on]
        terminals = [step_id for step_id, successors in successor_ids.items() if not successors]
        if len(roots) != 1 or len(terminals) != 1:
            raise _invalid_compiled_plan("plan draft must have one root and one terminal step")
        if edge_count + 2 > request.max_edges:
            raise _plan_limit_exceeded("plan draft exceeds its edge limit")
        pipeline = DataPipeline(label=draft.label or request.goal)
        input_node = pipeline.define_input(request.input_label)
        nodes: dict[str, Node] = {}
        try:
            for step in steps:
                nodes[step.step_id] = pipeline.define_operator(
                    step.operator_id,
                    label=step.label or step.step_id,
                    attributes=deepcopy(dict(step.attributes)),
                )
        except Exception:
            raise planning_error(
                PlanningStage.COMPILATION,
                PlanningErrorCode.COMPILATION_FAILED,
                "plan attributes could not be copied",
                category=ErrorCategory.FAILED,
                suggestion="Use portable plan attributes.",
            ) from None

        for step in steps:
            if step.depends_on:
                for dependency in step.depends_on:
                    pipeline.connect_nodes(nodes[dependency], nodes[step.step_id])
            else:
                pipeline.connect_nodes(input_node, nodes[step.step_id])
        output_node = pipeline.define_output(request.output_label)
        pipeline.connect_nodes(nodes[terminals[0]], output_node)
        pipeline.set_plan_input(input_node)
        pipeline.set_plan_output(output_node)
        return pipeline


def _check_addressed_step(scope: DataScope | None, step: PlanStep) -> None:
    """Require an `nl2sql` step to name the same address the request scoped.

    This stops a draft from collecting context for one collection and querying another.
    It is an address-consistency check on the step's own attributes, not a table
    authorization boundary: nothing here constrains the tables the generated SQL reads,
    and `DataScope.entities` remains advisory planning context.
    """

    if scope is None:
        raise _invalid_compiled_plan(f"step {step.step_id!r} requires a request data scope")
    attributes: Mapping[str, Any] = step.attributes
    for name, expected in (
        ("source", scope.source),
        ("database", scope.database),
        ("collection", scope.collection),
    ):
        value = attributes.get(name)
        if type(value) is not str or value != expected:
            raise _invalid_compiled_plan(
                f"step {step.step_id!r} must address the request data scope"
            )


def _topological_steps(by_id: Mapping[str, PlanStep]) -> tuple[str, ...]:
    indegree = {step_id: len(step.depends_on) for step_id, step in by_id.items()}
    following: dict[str, list[str]] = {step_id: [] for step_id in by_id}
    for step in by_id.values():
        for dependency in step.depends_on:
            following[dependency].append(step.step_id)
    ready = [step_id for step_id in by_id if indegree[step_id] == 0]
    order: list[str] = []
    while ready:
        step_id = ready.pop(0)
        order.append(step_id)
        for successor in following[step_id]:
            indegree[successor] -= 1
            if indegree[successor] == 0:
                ready.append(successor)
    if len(order) != len(by_id):
        raise _invalid_compiled_plan("plan draft contains a cycle")
    return tuple(order)


def _select_then_average_rule(
    request: PlanningRequest,
    discovery: DiscoverySnapshot,
    data_context: DataContextSnapshot | None,
) -> PlanDraft | None:
    del data_context  # this rule plans from the goal text and caller attributes
    goal = request.goal.casefold()
    if "average" not in goal or not any(token in goal for token in ("above", "greater")):
        return None
    discovery.one("select")
    discovery.one("avg")
    try:
        select_attributes = request.operator_attributes["select"]
        average_attributes = request.operator_attributes["avg"]
    except (KeyError, TypeError, ValueError):
        raise invalid_request(
            "select and avg attributes are required for the average rule"
        ) from None
    if not {"operand_key", "operand", "operand_val"}.issubset(select_attributes) or not {
        "avg_key",
        "output_key",
    }.issubset(average_attributes):
        raise invalid_request("select and avg attributes are incomplete for the average rule")
    return SELECT_THEN_AVERAGE_TEMPLATE.generate(request, discovery, None)
