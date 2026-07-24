from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any, cast

from blue_data_ops.operators.types import ABSENT, AttributeSpec
from blue_data_ops.utils.json_utils import merge_json
from blue_data_ops.utils.tool_utils import (
    annotation_to_type_str as _annotation_to_type_string,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)
from blue_data_ops.utils.tool_utils import (
    convert_type_string_to_mcp as type_string_to_mcp,
)
from blue_data_ops.utils.tool_utils import (
    extract_signature as _utils_extract_signature,
)

# The Blue-surface metadata helpers now share one implementation in
# blue_data_ops.utils; these names delegate rather than keeping a second copy.
# merge_metadata is jsonmerge's object merge (via merge_json);
# _annotation_to_type_string and type_string_to_mcp are re-exported from
# tool_utils; extract_signature is the MCP-mode signature extractor.
merge_metadata = merge_json

__all__ = [
    "definitions_from_specs",
    "enrich_attribute_signature",
    "extract_signature",
    "merge_metadata",
    "project_specs",
    "type_string_to_mcp",
]


def _metadata_snapshot(value: Any) -> Any:
    try:
        return deepcopy(value)
    except Exception:
        if type(value) is dict:
            mapping = cast(dict[Any, Any], value)
            return {key: _metadata_snapshot(item) for key, item in mapping.items()}
        if type(value) is list:
            sequence = cast(list[Any], value)
            return [_metadata_snapshot(item) for item in sequence]
        if type(value) is tuple:
            sequence = cast(tuple[Any, ...], value)
            return tuple(_metadata_snapshot(item) for item in sequence)
        return value


def extract_signature(function: Callable[..., Any]) -> dict[str, Any]:
    """Extract the Blue-compatible MCP signature for a callable (mcp_format=True)."""
    return _utils_extract_signature(function, mcp_format=True)


def definitions_from_specs(
    specs: Mapping[str, AttributeSpec],
) -> tuple[dict[str, dict[str, Any]], dict[str, bool]]:
    """Create per-instance live definitions from frozen class declarations."""
    definitions: dict[str, dict[str, Any]] = {}
    materialize_defaults: dict[str, bool] = {}
    for name, spec in specs.items():
        definition: dict[str, Any] = {
            "type": spec.type,
            "description": spec.description,
            "required": spec.required,
            "hidden": False,
        }
        if spec.has_default:
            definition["default"] = _metadata_snapshot(spec.default)
        definitions[name] = definition
        materialize_defaults[name] = spec.materialize_default
    return definitions, materialize_defaults


def project_specs(
    definitions: object,
    materialize_defaults: Mapping[str, bool],
) -> dict[str, AttributeSpec]:
    """Project the live Blue metadata view into frozen runtime specifications."""
    if not isinstance(definitions, dict):
        raise TypeError("attribute definitions must be a dictionary")

    projected: dict[str, AttributeSpec] = {}
    definition_map = cast(dict[object, object], definitions)
    for name, value in definition_map.items():
        if not isinstance(name, str) or not isinstance(value, dict):
            raise TypeError("each attribute definition must be a named dictionary")
        value_map = cast(dict[str, Any], value)
        type_name = value_map.get("type", "")
        description = value_map.get("description", "")
        required = value_map.get("required", False)
        if not isinstance(type_name, str):
            raise TypeError("attribute type must be a string")
        if not isinstance(description, str):
            raise TypeError("attribute description must be a string")
        if type(required) is not bool:
            raise TypeError("attribute required flag must be a boolean")
        default = value_map["default"] if "default" in value_map else ABSENT
        projected[name] = AttributeSpec(
            type=type_name,
            description=description,
            required=required,
            default=default,
            materialize_default=materialize_defaults.get(name, True),
        )
    return projected


def enrich_attribute_signature(
    signature: dict[str, Any],
    definitions: Mapping[str, Any],
) -> None:
    """Attach live attribute definitions only to a parameter named attributes."""
    parameters = signature.get("parameters", {})
    if "attributes" not in parameters:
        return
    attribute_parameter = cast(dict[str, Any], parameters["attributes"])
    attribute_parameter["properties"] = _metadata_snapshot(dict(definitions))
    properties = cast(dict[str, dict[str, Any]], attribute_parameter["properties"])
    for definition in properties.values():
        definition["type"] = type_string_to_mcp(definition["type"])
