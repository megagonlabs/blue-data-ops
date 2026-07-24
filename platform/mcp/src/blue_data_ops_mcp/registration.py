from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from blue_data_ops.operators import (
    ErrorRecord,
    ExecMeta,
    Operator,
    OperatorCard,
    OperatorRegistry,
    ResolveError,
    versioned_registry,
)
from blue_data_ops.plan import RefinableOperator
from mcp.server.fastmcp import FastMCP

from blue_data_ops_mcp.schema import RefineResult, RunResult, handler_signature

# The adapter-committed v2 selection: exactly the 36 name-sorted `name@2.0.0` ids. The default
# deployment freezes this tuple against a superset-tolerant registry; it is never derived from
# `list_cards()`.
V2_OPERATOR_IDS: tuple[str, ...] = (
    "argmax@2.0.0",
    "argmin@2.0.0",
    "avg@2.0.0",
    "classify@2.0.0",
    "cluster@2.0.0",
    "create_database@2.0.0",
    "create_table@2.0.0",
    "data_discover@2.0.0",
    "delete@2.0.0",
    "insert@2.0.0",
    "insert_table@2.0.0",
    "intersect@2.0.0",
    "join@2.0.0",
    "max@2.0.0",
    "min@2.0.0",
    "multipart_query@2.0.0",
    "nl2bn@2.0.0",
    "nl2llm@2.0.0",
    "nl2query_router@2.0.0",
    "nl2sql@2.0.0",
    "normalize_text@2.0.0",
    "plan_discover@2.0.0",
    "project@2.0.0",
    "query_breakdown@2.0.0",
    "segment_text@2.0.0",
    "select@2.0.0",
    "semantic_extract@2.0.0",
    "semantic_filter@2.0.0",
    "semantic_join@2.0.0",
    "semantic_project@2.0.0",
    "semantic_transform@2.0.0",
    "sum@2.0.0",
    "union@2.0.0",
    "vector_embed@2.0.0",
    "vector_search@2.0.0",
    "vector_similarity@2.0.0",
)

_SELECTED_VERSION = "2.0.0"
REFINE_SUFFIX = "__refine"
REFINE_DESCRIPTION_PREFIX = "Build candidate data-pipeline plans."


@dataclass(frozen=True)
class OperatorBinding:
    card: OperatorCard
    operator: Operator
    kind: Literal["primary", "refine"]


DeploymentSnapshot = tuple[OperatorBinding, ...]


def freeze_deployment(
    registry: OperatorRegistry | None = None,
    operator_ids: Iterable[str] | None = None,
) -> DeploymentSnapshot:
    """Freeze one v2 deployment: validate the selection, then bind primaries and companions.

    The registry defaults to the superset-tolerant `versioned_registry()`; the selection defaults
    to the adapter-committed `V2_OPERATOR_IDS`. An explicit `operator_ids` is a complete replacement
    and may be empty or a subset. Each requested id is held through validation and binding so the
    card the registry returns for it can never be swapped onto a different selection: the returned
    card's `operator_id` must equal the requested id, that card must be `2.0.0`, and the resolved
    operator, the card, and the requested id must all agree. Duplicate ids, duplicate logical names,
    malformed or missing ids, non-`2.0.0` selections, returned-card substitutions, and binding
    mismatches are rejected before any tool is bound. Registry supersets are accepted — the
    inventory is never compared with the selection.
    """
    active_registry = registry if registry is not None else versioned_registry()

    selected_ids = V2_OPERATOR_IDS if operator_ids is None else tuple(operator_ids)
    if len(set(selected_ids)) != len(selected_ids):
        raise ValueError("deployment selection contains a repeated operator id")

    # Keep each requested id bound to the card the registry returns for it, so validation and
    # sorting can never swap the returned card onto a different selection. `get_card` must answer
    # with a card whose `operator_id` is exactly the requested id; any other card (even another
    # valid 2.0.0 one) is a substitution and is rejected before the card is trusted for its version.
    selected: list[tuple[str, OperatorCard]] = []
    for requested_id in selected_ids:
        active_registry.resolve(requested_id)
        card = active_registry.get_card(requested_id)
        if card is None:
            raise ResolveError(f"no operator card registered as {requested_id!r}")
        if card.operator_id != requested_id:
            raise ValueError(
                f"registry returned card {card.operator_id!r} for requested id {requested_id!r}"
            )
        if card.version != _SELECTED_VERSION:
            raise ValueError(
                f"the v2 adapter selects {_SELECTED_VERSION} only, got {requested_id!r}"
            )
        selected.append((requested_id, card))

    names = [card.name for _, card in selected]
    if len(set(names)) != len(names):
        raise ValueError("deployment selection contains multiple versions of one tool name")

    primaries: list[OperatorBinding] = []
    companions: list[OperatorBinding] = []
    for requested_id, card in sorted(selected, key=lambda item: item[1].name):
        operator = active_registry.resolve(requested_id)
        if (
            operator.operator_id != requested_id
            or card.operator_id != requested_id
            or operator.name != card.name
        ):
            raise ValueError(f"operator/card mismatch for {requested_id!r}")
        primaries.append(OperatorBinding(card=card, operator=operator, kind="primary"))
        if isinstance(operator, RefinableOperator):
            companions.append(OperatorBinding(card=card, operator=operator, kind="refine"))
    return tuple(primaries) + tuple(companions)


def _wire_json(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply the conversion once: `default=str` for exotic leaves; reject non-finite.

    A `ValueError` from a non-finite float (or any value neither JSON-native nor str-coercible) is
    an adapter error that becomes a tool error at the handler boundary; it never becomes a synthetic
    operator `ErrorRecord`.
    """
    return json.loads(json.dumps(payload, default=str, allow_nan=False))


def _error_payload(error: ErrorRecord) -> dict[str, Any]:
    return {
        "category": error.category.value,
        "code": error.code.value,
        "operator_id": error.operator_id,
        "stage": error.stage.value,
        "message": error.message,
        "retryable": error.retryable,
        "suggestion": error.suggestion,
    }


def _exec_meta_payload(exec_meta: ExecMeta) -> dict[str, Any]:
    return {
        "is_empty": exec_meta.is_empty,
        "errors": [_error_payload(error) for error in exec_meta.errors],
        "logs": list(exec_meta.logs),
        "traces": exec_meta.traces,
    }


def run_payload(
    result: tuple[list[list[dict[str, Any]]], dict[str, Any], ExecMeta],
) -> dict[str, Any]:
    """Project a canonical `run()` result into the wire object (post-conversion)."""
    output_data, output_attributes, exec_meta = result
    return _wire_json(
        {
            "output_data": output_data,
            "output_attributes": output_attributes,
            "exec_meta": _exec_meta_payload(exec_meta),
        }
    )


def refine_payload(result: tuple[list[Any], ExecMeta]) -> dict[str, Any]:
    """Project a normalized `refine()` result into the wire object (post-conversion)."""
    plans, exec_meta = result
    return _wire_json(
        {
            "plans": [plan.to_dict() for plan in plans],
            "exec_meta": _exec_meta_payload(exec_meta),
        }
    )


def make_run_handler(operator: Operator) -> Any:
    async def handler(
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any] | None = None,
        properties: dict[str, Any] | None = None,
    ) -> RunResult:
        call_attributes: dict[str, Any] = {} if attributes is None else attributes
        payload = await asyncio.to_thread(
            lambda: run_payload(operator.run(input_data, call_attributes, properties))
        )
        return RunResult.model_validate(payload)

    handler.__name__ = operator.name
    setattr(handler, "__signature__", handler_signature(operator, RunResult))
    return handler


def make_refine_handler(operator: RefinableOperator) -> Any:
    async def handler(
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any] | None = None,
        properties: dict[str, Any] | None = None,
    ) -> RefineResult:
        call_attributes: dict[str, Any] = {} if attributes is None else attributes
        payload = await asyncio.to_thread(
            lambda: refine_payload(operator.refine(input_data, call_attributes, properties))
        )
        return RefineResult.model_validate(payload)

    handler.__name__ = f"{operator.name}{REFINE_SUFFIX}"
    setattr(handler, "__signature__", handler_signature(operator, RefineResult))
    return handler


def _compose_description(card: OperatorCard) -> str:
    if card.when_to_invoke.strip():
        return f"{card.when_to_invoke}\n\n{card.description}"
    return card.description


def _meta(card: OperatorCard) -> dict[str, Any]:
    return {
        "operator_id": card.operator_id,
        "version": card.version,
        "tags": list(card.tags),
    }


def register_snapshot(server: FastMCP[Any], snapshot: DeploymentSnapshot) -> None:
    for binding in snapshot:
        card = binding.card
        if binding.kind == "primary":
            server.add_tool(
                make_run_handler(binding.operator),
                name=card.name,
                description=_compose_description(card),
                meta=_meta(card),
                structured_output=True,
            )
        else:
            companion = binding.operator
            assert isinstance(companion, RefinableOperator)
            server.add_tool(
                make_refine_handler(companion),
                name=f"{card.name}{REFINE_SUFFIX}",
                description=f"{REFINE_DESCRIPTION_PREFIX}\n\n{_compose_description(card)}",
                meta=_meta(card),
                structured_output=True,
            )
