"""Blue-compatible annotation and signature conversion helpers.

Supports inspect-annotation to type-string conversion, plain and MCP signature
extraction, and type-string to MCP-shape conversion. The private
``operators/_metadata`` helpers delegate here; this module does not import ``blue``.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from blue_data_ops.utils.json_utils import merge_json

__all__ = [
    "annotation_to_type_str",
    "convert_type_string_to_mcp",
    "extract_signature",
]


def annotation_to_type_str(annotation: Any) -> str:
    """Convert an inspect annotation to a type string (Blue).

    A class annotation becomes its ``__name__`` (``inspect._empty`` -> ``unknown``);
    any other annotation becomes ``str(annotation)`` with the ``typing.`` prefix
    stripped, so ``typing.List[str]`` reads as ``List[str]``.
    """
    if type(annotation) is type:
        if annotation is inspect.Parameter.empty:
            return "unknown"
        return annotation.__name__
    return str(annotation).replace("typing.", "")


def convert_type_string_to_mcp(type_str: str) -> dict[str, Any]:
    """Convert a type string to an MCP JSON-schema shape (Blue).

    ``int``/``float`` -> number, ``str`` -> string, ``List[...]`` -> array with a
    recursively converted ``items``, ``Dict...`` -> object, everything else
    (including the empty string) -> unknown. The ``List`` slice offset is Blue's.
    """
    if type_str == "":
        return {"type": "unknown"}
    lowered = type_str.lower()
    if lowered in ("int", "float"):
        return {"type": "number"}
    if lowered == "str":
        return {"type": "string"}
    if lowered.find("list") == 0:
        return {
            "type": "array",
            "items": convert_type_string_to_mcp(type_str[len("List") + 1 : -1]),
        }
    if lowered.find("dict") == 0:
        return {"type": "object", "properties": {}}
    return {"type": "unknown"}


def extract_signature(function: Callable[..., Any], mcp_format: bool = False) -> dict[str, Any]:
    """Extract a function signature as a ``{parameters, returns}`` dict (Blue).

    A truthy default marks a parameter optional and records its value; a falsy or
    absent default marks it required (Blue's falsy-default quirk). ``mcp_format``
    merges each parameter's and the return's MCP shape onto the ``type`` entry. A
    ``None`` return annotation yields an empty ``returns`` dict, matching Blue.
    """
    signature = inspect.signature(function)
    inspection: dict[str, Any] = {"parameters": {}}
    for name, parameter in signature.parameters.items():
        entry: dict[str, Any] = {"type": annotation_to_type_str(parameter.annotation)}
        if mcp_format:
            entry = merge_json(entry, convert_type_string_to_mcp(entry["type"]))
        default = parameter.default
        if default is inspect.Parameter.empty:
            default = None
        if default:
            entry["required"] = False
            entry["default"] = default
        else:
            entry["required"] = True
        inspection["parameters"][name] = entry

    return_annotation = signature.return_annotation
    returns: dict[str, Any] = {}
    if return_annotation is not None:
        returns["type"] = annotation_to_type_str(return_annotation)
        if mcp_format:
            returns = merge_json(returns, convert_type_string_to_mcp(returns["type"]))
    inspection["returns"] = returns
    return inspection
