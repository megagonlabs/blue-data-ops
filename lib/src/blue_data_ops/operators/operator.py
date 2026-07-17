from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from typing import Any, ClassVar

from pydantic import BaseModel, ValidationError, create_model

from blue_data_ops.operators.types import Attributes, AttributeSpec, DataBundle, Properties


# This behavior-carrying base stays beside the operators it validates, invokes, and
# explains; it is not a data-only interface.
class Operator(ABC):
    """Abstract base for a flat, single-output, type-aware data operator."""

    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    attributes: ClassVar[dict[str, AttributeSpec]] = {}

    @abstractmethod
    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        """Transform input_data under attributes and return the operator output."""

    def validate(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> bool:
        """Validate attributes against the declared spec; total (never raises)."""
        return self._validate_attributes(attributes)

    def invoke(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle | None:
        """Validate unconditionally, then apply; return None when invalid."""
        if not self.validate(input_data, attributes, properties):
            return None
        return self.apply(input_data, attributes, properties)

    def explain(
        self,
        output: DataBundle,
        input_data: DataBundle,
        attributes: Attributes,
    ) -> dict[str, Any]:
        """Describe the transformation with input/output statistics."""
        total_input_records = sum(len(data) for data in input_data)
        output_count = len(output)
        return {
            "output": output,
            "num_input_data": len(input_data),
            "num_input_records": total_input_records,
            "num_input_records_per_data": [len(data) for data in input_data],
            "num_output_data": len(output),
            "num_output_records": output_count,
            "transformation_ratio": output_count / total_input_records
            if total_input_records > 0
            else 0,
            "attributes": attributes,
        }

    def is_required(self, attribute: str) -> bool | None:
        """Report whether attribute is declared required (None if unknown)."""
        spec = self.attributes.get(attribute)
        return spec.required if spec is not None else None

    def default_of(self, attribute: str) -> Any:
        """Return the declared default for attribute (None if unknown or unset)."""
        spec = self.attributes.get(attribute)
        return spec.default if spec is not None else None

    def _validate_attributes(self, attributes: Attributes) -> bool:
        for attr_name, spec in self.attributes.items():
            if spec.required and attr_name not in attributes:
                return False
            if attr_name in attributes and not _check_type(attributes[attr_name], spec.type):
                return False
        return True


# Attribute checks use Pydantic's lax coercion: values such as "yes" and 1 validate as
# bool, and bytes validate as str. Composite spellings include list/dict/tuple/set,
# frozenset/deque, Union/"|", and Optional. Unknown names fall back to Any. Bare
# "frozenset" and "deque" are intentionally unknown; only their bracketed forms parse.
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

_MODEL_CACHE: dict[str, type[BaseModel]] = {}


def _split_top_level(inner: str) -> list[str]:
    parts: list[str] = []
    current = ""
    bracket_count = 0
    for char in inner:
        if char == "[":
            bracket_count += 1
        elif char == "]":
            bracket_count -= 1
        elif char == "," and bracket_count == 0:
            parts.append(current.strip())
            current = ""
            continue
        current += char
    if current.strip():
        parts.append(current.strip())
    return parts


def _string_to_python_type(type_str: str) -> Any:
    if not type_str:
        return Any
    # Normalize typing-style prefixes before the case-insensitive parser runs.
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
        return list[_string_to_python_type(type_str[5:-1].strip())]
    if type_str.startswith("dict["):
        inner = type_str[5:-1].strip()
        if "," in inner:
            key_str, value_str = (s.strip() for s in inner.split(",", 1))
            return dict[_string_to_python_type(key_str), _string_to_python_type(value_str)]
        return dict[str, Any]
    if type_str.startswith("tuple["):
        return tuple[_string_to_python_type(type_str[6:-1].strip())]
    if type_str.startswith("set["):
        return set[_string_to_python_type(type_str[4:-1].strip())]
    if type_str.startswith("frozenset["):
        return frozenset[_string_to_python_type(type_str[10:-1].strip())]
    if type_str.startswith("deque["):
        return deque[_string_to_python_type(type_str[6:-1].strip())]
    if type_str.startswith("union[") or "|" in type_str:
        if type_str.startswith("union["):
            type_names = _split_top_level(type_str[6:-1])
        else:
            type_names = [t.strip() for t in type_str.split("|")]
        types = [_string_to_python_type(t) for t in type_names]
        union_type = types[0]
        for member in types[1:]:
            union_type = union_type | member
        return union_type
    if type_str.startswith("optional["):
        return _string_to_python_type(type_str[9:-1].strip()) | None

    return _TYPE_MAPPING.get(type_str, Any)


def _check_type(value: Any, type_name: str) -> bool:
    if not type_name:
        return True
    python_type = _string_to_python_type(type_name)
    if python_type is Any:
        return True
    model = _MODEL_CACHE.get(type_name)
    if model is None:
        model = create_model("SingleFieldModel", value=(python_type, ...))
        _MODEL_CACHE[type_name] = model
    try:
        model(value=value)
        return True
    except ValidationError:
        return False
    except (TypeError, ValueError, AttributeError):
        return False
