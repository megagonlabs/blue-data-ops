from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, cast

from blue_data_ops import _execution_scope as _scope
from blue_data_ops.llm.errors import LLMError
from blue_data_ops.operators import (
    ErrorRecord,
    ExecMeta,
    Operator,
    OperatorCard,
    OperatorRegistry,
    ResolveError,
    versioned_registry,
)
from blue_data_ops.operators._execution_fallback import run_body
from blue_data_ops.operators._nl2bn_outcome import NL2BNOutcomeOperator
from blue_data_ops.operators._nl2sql_outcome import NL2SQLOutcomeOperator
from blue_data_ops.operators.nl2bn_operator import NL2BNOperator
from blue_data_ops.operators.nl2sql_operator import NL2SQLOperator
from blue_data_ops.operators.operator import (
    _VersionBoundOperator,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.registry import is_builtin_card
from blue_data_ops.operators.vector_search_operator import VectorSearchOperator
from mcp.server.fastmcp import FastMCP

from blue_data_ops_mcp.data_registry import DeploymentRegistry, failure_result
from blue_data_ops_mcp.schema import RunResult, handler_signature

# The adapter-committed selections are explicit policy, not a semver maximum or registry query.
# Both tuples are ordered by logical name. V2_OPERATOR_IDS preserves the retained historical-v2
# selection; ACTIVE_OPERATOR_IDS is the ordinary 3.0 deployment default.
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
    "nl2bn@2.0.0",
    "nl2llm@2.0.0",
    "nl2sql@2.0.0",
    "normalize_text@2.0.0",
    "project@2.0.0",
    "segment_text@2.0.0",
    "select@2.0.0",
    "semantic_extract@2.0.0",
    "semantic_filter@2.0.0",
    "semantic_join@2.0.0",
    "semantic_project@2.0.0",
    "semantic_transform@2.0.0",
    "sklearn_estimator@2.0.0",
    "sum@2.0.0",
    "union@2.0.0",
    "vector_embed@2.0.0",
    "vector_search@2.0.0",
    "vector_similarity@2.0.0",
)

ACTIVE_OPERATOR_IDS: tuple[str, ...] = (
    "argmax@2.0.0",
    "argmin@2.0.0",
    "avg@3.0.0",
    "classify@3.0.0",
    "cluster@3.0.0",
    "create_database@2.0.0",
    "create_table@2.0.0",
    "data_discover@2.0.0",
    "delete@2.0.0",
    "insert@3.0.0",
    "insert_table@3.0.0",
    "intersect@3.0.0",
    "join@3.0.0",
    "max@3.0.0",
    "min@3.0.0",
    "nl2bn@3.0.0",
    "nl2llm@3.0.0",
    "nl2sql@4.0.0",
    "normalize_text@2.0.0",
    "project@3.0.0",
    "segment_text@2.0.0",
    "select@2.0.0",
    "semantic_extract@3.0.0",
    "semantic_filter@3.0.0",
    "semantic_join@3.0.0",
    "semantic_project@3.0.0",
    "semantic_transform@3.0.0",
    "sklearn_estimator@2.0.0",
    "sum@2.0.0",
    "union@2.0.0",
    "vector_embed@3.0.0",
    "vector_search@3.0.0",
    "vector_similarity@3.0.0",
)

_SUPPORTED_BUILTIN_IDS = frozenset((*V2_OPERATOR_IDS, *ACTIVE_OPERATOR_IDS, "nl2sql@3.0.0"))
_SUPPORTED_BUILTIN_NAMES = frozenset(
    operator_id.partition("@")[0] for operator_id in _SUPPORTED_BUILTIN_IDS
)
_SUPPORTED_VERSIONS = frozenset({"2.0.0", "3.0.0"})
DEPRECATION_SENTENCE = "This operator is marked deprecated by its registry metadata."

# A client holds one flat tool namespace across every server it has loaded, and this family
# ships a server per source. `create_database` already means one thing here and another in
# blue-data-user-source, and half this catalog is a bare verb. The prefix is the whole
# adapter's contribution to the name: the part after it is still the core operator's logical
# name, which `_meta.operator_id` continues to carry unprefixed.
TOOL_PREFIX = "ops_"


def tool_name(operator_name: str) -> str:
    """Return the served MCP tool name for one core operator name."""
    return f"{TOOL_PREFIX}{operator_name}"


@dataclass(frozen=True)
class OperatorBinding:
    card: OperatorCard
    operator: Operator


DeploymentSnapshot = tuple[OperatorBinding, ...]


def freeze_deployment(
    registry: OperatorRegistry | None = None,
    operator_ids: Iterable[str] | None = None,
) -> DeploymentSnapshot:
    """Validate and freeze one exact primary-only deployment.

    The backing registry may be a superset, but only selected cards become tools. Package-owned
    selections must be same-registry built-ins with the expected implementation class. Explicit
    caller registrations retain the v2 path; custom v3 and v1 cards are outside this contract.
    """
    deployment_registry = registry if registry is not None else versioned_registry()

    selected_ids = ACTIVE_OPERATOR_IDS if operator_ids is None else tuple(operator_ids)
    if len(set(selected_ids)) != len(selected_ids):
        raise ValueError("deployment selection contains a repeated operator id")

    selected: list[tuple[str, OperatorCard, Operator]] = []
    reference_registry: OperatorRegistry | None = None
    for requested_id in selected_ids:
        card = deployment_registry.get_card(requested_id)
        if card is None:
            raise ResolveError(f"no operator card registered as {requested_id!r}")
        if card.operator_id != requested_id:
            raise ValueError(
                f"registry returned card {card.operator_id!r} for requested id {requested_id!r}"
            )
        requested_name, separator, requested_version = requested_id.partition("@")
        if not separator or card.name != requested_name or card.version != requested_version:
            raise ValueError(f"requested/card identity mismatch for {requested_id!r}")
        if card.version not in _SUPPORTED_VERSIONS and requested_id != "nl2sql@4.0.0":
            raise ValueError(
                "the MCP adapter supports exact v2/v3 and built-in nl2sql@4.0.0 "
                f"selections only, got {requested_id!r}"
            )
        operator = deployment_registry.resolve(requested_id)
        if operator.operator_id != requested_id or operator.name != card.name:
            raise ValueError(f"operator/card mismatch for {requested_id!r}")

        if requested_id in _SUPPORTED_BUILTIN_IDS:
            if not is_builtin_card(deployment_registry, card):
                raise ValueError(f"built-in provenance mismatch for {requested_id!r}")
            if reference_registry is None:
                reference_registry = versioned_registry()
            expected = reference_registry.resolve(requested_id)
            if type(_implementation(operator)) is not type(_implementation(expected)):
                raise ValueError(f"resolved implementation mismatch for {requested_id!r}")
        elif is_builtin_card(deployment_registry, card) or card.name in _SUPPORTED_BUILTIN_NAMES:
            raise ValueError(f"unsupported built-in selection {requested_id!r}")
        elif card.version != "2.0.0":
            raise ValueError(f"custom operators are supported at 2.0.0 only, got {requested_id!r}")

        selected.append((requested_id, card, operator))

    names = [card.name for _, card, _ in selected]
    if len(set(names)) != len(names):
        raise ValueError("deployment selection contains multiple versions of one tool name")

    return tuple(
        OperatorBinding(card=card, operator=operator)
        for _, card, operator in sorted(selected, key=lambda item: item[1].name)
    )


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


def _implementation(operator: Operator) -> Operator:
    while type(operator) is _VersionBoundOperator:
        operator = operator._target  # pyright: ignore[reportPrivateUsage]
    return operator


def make_run_handler(
    operator: Operator,
    *,
    deployment: DeploymentRegistry | None = None,
    requires_registry: bool = False,
) -> Any:
    implementation = _implementation(operator)
    sql = type(implementation) in (NL2SQLOperator, NL2SQLOutcomeOperator)
    bn = type(implementation) in (NL2BNOperator, NL2BNOutcomeOperator)
    try:
        preflight = getattr(implementation, "_preflight_execution", None) if sql else None
    except Exception:
        preflight = None

    async def handler(
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any] | None = None,
        properties: dict[str, Any] | None = None,
    ) -> RunResult:
        call_attributes: dict[str, Any] = {} if attributes is None else attributes
        call_properties = properties
        bound_execution = False
        if sql or bn:
            try:
                if sql:
                    if not callable(preflight):
                        raise LLMError(
                            "SQL preflight unavailable",
                            code="sql_execution_unavailable",
                            retryable=False,
                        )
                    bound_execution = preflight(call_attributes, properties)
                    if type(bound_execution) is not bool:
                        raise LLMError(
                            "SQL preflight invalid",
                            code="sql_execution_unavailable",
                            retryable=False,
                        )
                else:
                    from blue_data_ops.llm.client import validate_llm_caller_controls

                    validate_llm_caller_controls(
                        properties,
                        service_prefix=str(
                            cast(NL2BNOperator, implementation).DEFAULT_PROPERTIES.get(
                                "service_prefix", "openai"
                            )
                        ),
                    )
            except Exception as error:
                if not isinstance(error, LLMError):
                    error = LLMError(
                        "preflight unavailable",
                        code="sql_execution_unavailable" if sql else "reserved_field",
                        retryable=False,
                    )
                return RunResult.model_validate(run_payload(failure_result(operator, error)))
        if type(operator) is VectorSearchOperator:
            # The v2 implementation reads these declared attributes from properties.
            controls = {
                name: call_attributes[name]
                for name in ("top_k", "min_score", "normalize")
                if name in call_attributes
            }
            if controls:
                call_properties = {**controls, **(properties or {})}
        scope = _scope.create(None)
        try:
            with _scope.activate(scope):
                if deployment is not None and (requires_registry or bound_execution):
                    result = await deployment.run(
                        operator,
                        input_data,
                        call_attributes,
                        call_properties,
                        bound_execution=bound_execution,
                    )
                    payload = run_payload(result)
                else:
                    payload = await asyncio.to_thread(
                        lambda: run_payload(
                            run_body(operator, input_data, call_attributes, call_properties)
                        )
                    )
        except asyncio.CancelledError:
            scope.stop.set()
            raise
        except _scope.ScopeExpired as error:
            payload = run_payload(failure_result(operator, error))
        return RunResult.model_validate(payload)

    handler.__name__ = tool_name(operator.name)
    setattr(handler, "__signature__", handler_signature(operator, RunResult))
    return handler


def _compose_description(binding: OperatorBinding) -> str:
    card = binding.card
    parts: list[str] = []
    if card.deprecated:
        parts.append(DEPRECATION_SENTENCE)
    if card.when_to_invoke.strip():
        parts.append(card.when_to_invoke)
    parts.append(card.description)
    return "\n\n".join(parts)


def _meta(binding: OperatorBinding) -> dict[str, Any]:
    card = binding.card
    meta: dict[str, Any] = {
        "operator_id": card.operator_id,
        "version": card.version,
        "tags": list(card.tags),
    }
    if card.deprecated:
        meta["deprecated"] = True
    return meta


def register_snapshot(
    server: FastMCP[Any],
    snapshot: DeploymentSnapshot,
    *,
    deployment: DeploymentRegistry | None = None,
) -> None:
    if deployment is None:
        deployment = DeploymentRegistry()
    for binding in snapshot:
        card = binding.card
        server.add_tool(
            make_run_handler(
                binding.operator,
                deployment=deployment,
                requires_registry="requires-data-registry" in card.tags,
            ),
            name=tool_name(card.name),
            description=_compose_description(binding),
            meta=_meta(binding),
            structured_output=True,
        )
