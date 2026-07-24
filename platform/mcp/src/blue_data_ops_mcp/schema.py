from __future__ import annotations

import copy
import inspect
from typing import Annotated, Any

from blue_data_ops.operators import ErrorCategory, ErrorCode, ErrorStage, Operator
from pydantic import BaseModel, ConfigDict, WithJsonSchema

InputData = list[list[dict[str, Any]]]
Attributes = dict[str, Any]
Properties = dict[str, Any]


class ErrorRecordModel(BaseModel):
    """One canonical operator error projected onto the wire with the frozen error vocabulary."""

    model_config = ConfigDict(extra="forbid")

    category: ErrorCategory
    code: ErrorCode
    operator_id: str
    stage: ErrorStage
    message: str
    retryable: bool
    suggestion: str | None


class ExecMetaModel(BaseModel):
    """Execution metadata carried alongside every canonical result."""

    model_config = ConfigDict(extra="forbid")

    is_empty: bool
    errors: list[ErrorRecordModel]
    logs: list[str]
    traces: dict[str, Any]


class RunResult(BaseModel):
    """The structured envelope for a primary tool: canonical ``run()`` projected once."""

    model_config = ConfigDict(extra="forbid")

    output_data: InputData
    output_attributes: dict[str, Any]
    exec_meta: ExecMetaModel


class RefineResult(BaseModel):
    """The structured envelope for a companion: normalized ``refine()`` projected once."""

    model_config = ConfigDict(extra="forbid")

    plans: list[dict[str, Any]]
    exec_meta: ExecMetaModel


def attributes_json_schema(operator: Operator) -> dict[str, Any]:
    """Annotate known attributes, omitting defaults appropriately.

    Every attribute keeps its description. A default is published only for an optional attribute
    that both declares one and materializes it (``materialize_default`` true). Required attributes
    and the seven ``materialize_default=False`` declarations publish no default, matching the v2
    canonical materialization boundary. Published defaults are deep copies, never aliases of core
    state.
    """
    properties: dict[str, Any] = {}
    for name, spec in operator.attributes.items():
        entry: dict[str, Any] = {"description": spec.description}
        if not spec.required and spec.has_default and spec.materialize_default:
            entry["default"] = copy.deepcopy(spec.default)
        properties[name] = entry
    return {
        "type": "object",
        "properties": properties,
        "additionalProperties": True,
    }


def handler_signature(
    operator: Operator,
    return_annotation: type[BaseModel],
) -> inspect.Signature:
    """Build the tool handler signature: the open container arguments plus a structured return."""
    attributes_annotation = Annotated[
        Attributes,
        WithJsonSchema(attributes_json_schema(operator)),
    ]
    return inspect.Signature(
        parameters=[
            inspect.Parameter(
                "input_data",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=InputData,
            ),
            inspect.Parameter(
                "attributes",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=attributes_annotation,
                default={},
            ),
            inspect.Parameter(
                "properties",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=Properties | None,
                default=None,
            ),
        ],
        return_annotation=return_annotation,
    )
