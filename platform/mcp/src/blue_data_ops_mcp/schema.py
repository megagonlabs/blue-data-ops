from __future__ import annotations

import copy
import inspect
from typing import Annotated, Any

from blue_data_ops.operators import Operator
from pydantic import WithJsonSchema

InputData = list[list[dict[str, Any]]]
Attributes = dict[str, Any]
Properties = dict[str, Any]


def attributes_json_schema(operator: Operator) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for name, spec in operator.attributes.items():
        properties[name] = {
            "default": copy.deepcopy(spec.default),
            "description": spec.description,
        }
    return {
        "type": "object",
        "properties": properties,
        "additionalProperties": True,
    }


def handler_signature(operator: Operator) -> inspect.Signature:
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
        return_annotation=str,
    )
