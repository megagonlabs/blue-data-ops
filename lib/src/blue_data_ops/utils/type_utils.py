"""Blue-compatible type parsing and validation helpers.

Implements the string type parser, dynamic Pydantic model builder, and value-type
validator without importing ``blue``. Private operator helpers delegate here.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any, Dict, List, Optional, Union  # noqa: UP035 - Blue return-object identity

from pydantic import BaseModel, ValidationError, create_model

__all__ = [
    "create_pydantic_model",
    "string_to_python_type",
    "validate_parameter_type",
]

# Basic type names. "none" -> NoneType, "any" -> Any, matching Blue. Bare
# "frozenset"/"deque"/"tuple" without brackets stay unknown -> Any.
_TYPE_MAPPING: dict[str, Any] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "dict": dict,
    "list": list,
    "tuple": tuple,
    "set": set,
    "none": type(None),
    "any": Any,
}


def _split_union_members(inner: str) -> list[str]:
    """Split comma-separated union members, respecting nested brackets (Blue)."""
    members: list[str] = []
    current = ""
    bracket_count = 0
    for char in inner:
        if char == "[":
            bracket_count += 1
        elif char == "]":
            bracket_count -= 1
        elif char == "," and bracket_count == 0:
            members.append(current.strip())
            current = ""
            continue
        current += char
    if current.strip():
        members.append(current.strip())
    return members


def string_to_python_type(type_str: str) -> Any:
    """Convert a Blue type string to an actual Python type for Pydantic.

    Reproduces Blue exactly, including its return-object identity: the
    ``list``/``dict``/``optional``/``union`` spellings return ``typing.List`` /
    ``typing.Dict`` / ``typing.Optional`` / ``typing.Union`` objects, while
    ``tuple``/``set``/``frozenset``/``deque`` return builtin generics. Unknown
    names and the empty string fall back to ``Any``.
    """
    if not type_str:
        return Any

    # Normalize typing-style prefixes for the case-insensitive parser.
    type_str = (
        type_str.strip()
        .replace("List[", "list[")
        .replace("Dict[", "dict[")
        .replace("Tuple[", "tuple[")
        .replace("Set[", "set[")
        .replace("FrozenSet[", "frozenset[")
        .replace("Deque[", "deque[")
    )
    type_str = type_str.lower()

    if type_str.startswith("list["):
        inner_type = string_to_python_type(type_str[5:-1].strip())
        return List[inner_type]  # noqa: UP006 - Blue identity
    if type_str.startswith("dict["):
        inner = type_str[5:-1].strip()
        if "," in inner:
            key_str, value_str = (part.strip() for part in inner.split(",", 1))
            return Dict[  # noqa: UP006 - Blue identity
                string_to_python_type(key_str), string_to_python_type(value_str)
            ]
        return Dict[str, Any]  # noqa: UP006 - Blue identity
    if type_str.startswith("tuple["):
        return tuple[string_to_python_type(type_str[6:-1].strip())]
    if type_str.startswith("set["):
        return set[string_to_python_type(type_str[4:-1].strip())]
    if type_str.startswith("frozenset["):
        return frozenset[string_to_python_type(type_str[10:-1].strip())]
    if type_str.startswith("deque["):
        return deque[string_to_python_type(type_str[6:-1].strip())]
    if type_str.startswith("union[") or "|" in type_str:
        if type_str.startswith("union["):
            member_names = _split_union_members(type_str[6:-1])
        else:
            member_names = [part.strip() for part in type_str.split("|")]
        types = [string_to_python_type(name) for name in member_names]
        if type(None) in types:
            non_none = [member for member in types if member is not type(None)]
            if len(non_none) == 1:
                return Optional[non_none[0]]  # noqa: UP045 - Blue identity
            return Union[tuple(non_none + [type(None)])]  # noqa: UP007 - Blue identity
        return Union[tuple(types)]  # noqa: UP007 - Blue identity
    if type_str.startswith("optional["):
        return Optional[string_to_python_type(type_str[9:-1].strip())]  # noqa: UP045

    return _TYPE_MAPPING.get(type_str, Any)


def create_pydantic_model(parameters: Dict[str, Any]) -> type[BaseModel]:  # noqa: UP006
    """Build a Pydantic model from ``{name: {"type", "required"}}`` definitions.

    Required fields use ``...``; optional fields default to ``None``. A missing
    or empty ``type`` becomes ``Any``. Matches Blue's ``create_pydantic_model``.
    """
    fields: dict[str, Any] = {}
    for param_name, param_def in parameters.items():
        param_type = param_def.get("type")
        required = param_def.get("required", False)
        python_type = string_to_python_type(param_type) if param_type else Any
        fields[param_name] = (python_type, ... if required else None)
    return create_model("ParameterModel", **fields)


def validate_parameter_type(value: Any, expected_type: str | None) -> bool:
    """Validate ``value`` against one Blue type string.

    ``None`` expected type accepts anything. A validation mismatch or a malformed
    type specification (including ``union[]``, which yields an empty Union and a
    ``TypeError``) returns ``False`` with a debug message. A genuine system fault is
    logged and re-raised as ``RuntimeError`` — Blue's fail boundary.
    """
    if expected_type is None:
        return True
    try:
        python_type = string_to_python_type(expected_type)
        single_field_model = create_model("SingleFieldModel", value=(python_type, ...))
        single_field_model(value=value)
        return True
    except ValidationError:
        return False
    except (TypeError, ValueError, AttributeError):
        logging.debug("Invalid type specification")
        return False
    except Exception as error:
        logging.debug("System error during parameter type validation")
        raise RuntimeError(f"Parameter type validation system error: {error}") from error
