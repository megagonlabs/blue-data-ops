"""Blue-compatible signature extraction in plain and MCP modes.

The tests cover ``-> None`` returns, ``typing.``-prefixed annotations, falsy
defaults, and delegation from ``operators/_metadata``.

This module intentionally omits ``from __future__ import annotations`` so the
sample functions carry annotation objects rather than strings.
"""
# ruff: noqa: UP006, UP007, UP045 - the samples require typing.* annotation objects.

import typing
from typing import Any

from blue_data_ops.operators import _metadata as metadata_module
from blue_data_ops.utils import tool_utils
from blue_data_ops.utils.tool_utils import (
    annotation_to_type_str,
    convert_type_string_to_mcp,
    extract_signature,
)


def _plain(x: int, y: str = "d", z: Any = None) -> dict[str, int]:  # noqa: ANN401
    return {}


def _builtin_generic_none_return(items: list[str], flag: bool = False) -> None:
    return None


def _typing_prefixed(
    values: typing.List[str], maybe: typing.Optional[int] = 3
) -> typing.Dict[str, int]:
    return {}


# --- annotation_to_type_str: strips the typing. prefix (Blue) ----------------------
def test_annotation_to_type_str_strips_typing_prefix() -> None:
    assert annotation_to_type_str(typing.List[str]) == "List[str]"  # noqa: UP006
    assert annotation_to_type_str(int) == "int"
    import inspect

    assert annotation_to_type_str(inspect.Parameter.empty) == "unknown"


# --- convert_type_string_to_mcp ----------------------------------------------------
MCP_CASES: list[tuple[str, dict[str, Any]]] = [
    ("", {"type": "unknown"}),
    ("int", {"type": "number"}),
    ("float", {"type": "number"}),
    ("str", {"type": "string"}),
    ("List[str]", {"type": "array", "items": {"type": "string"}}),
    ("dict[str, int]", {"type": "object", "properties": {}}),
    ("SomethingElse", {"type": "unknown"}),
]


def test_convert_type_string_to_mcp_matches_blue() -> None:
    for type_str, expected in MCP_CASES:
        assert convert_type_string_to_mcp(type_str) == expected


# --- extract_signature: plain and MCP modes ----------------------------------------
def test_extract_signature_plain_mode() -> None:
    sig = extract_signature(_plain)
    assert sig["parameters"]["x"] == {"type": "int", "required": True}
    # Truthy default recorded; falsy/None default -> required (Blue's quirk).
    assert sig["parameters"]["y"] == {"type": "str", "required": False, "default": "d"}
    assert sig["parameters"]["z"] == {"type": "Any", "required": True}
    # Real dict[str, int] return -> GenericAlias str form (not a bare class name).
    assert sig["returns"] == {"type": "dict[str, int]"}


def test_extract_signature_mcp_mode_and_none_return() -> None:
    sig = extract_signature(_builtin_generic_none_return, mcp_format=True)
    # list[str] resolves to an MCP array, not "unknown".
    assert sig["parameters"]["items"] == {
        "type": "array",
        "items": {"type": "string"},
        "required": True,
    }
    # Falsy default False -> required (falsy-default quirk).
    assert sig["parameters"]["flag"]["required"] is True
    assert "default" not in sig["parameters"]["flag"]
    # A None return annotation yields an empty returns dict.
    assert sig["returns"] == {}


def test_extract_signature_typing_prefixed_mcp() -> None:
    sig = extract_signature(_typing_prefixed, mcp_format=True)
    assert sig["parameters"]["values"]["type"] == "array"
    assert sig["parameters"]["values"]["items"] == {"type": "string"}
    assert sig["parameters"]["maybe"] == {"type": "unknown", "required": False, "default": 3}
    assert sig["returns"]["type"] == "object"


def test_falsy_default_is_required_quirk() -> None:
    def f(a: int = 0, b: str = "") -> None:  # noqa: ARG001
        return None

    sig = extract_signature(f)
    assert sig["parameters"]["a"]["required"] is True
    assert sig["parameters"]["b"]["required"] is True


# --- shared implementation ----------------------------------------------------------
def test_metadata_delegates_to_utils_implementation() -> None:
    assert metadata_module.type_string_to_mcp is convert_type_string_to_mcp
    assert (
        metadata_module._annotation_to_type_string  # pyright: ignore[reportPrivateUsage, reportPrivateImportUsage]
        is annotation_to_type_str
    )
    # _metadata.extract_signature is the MCP-mode wrapper over the shared extractor.
    stringless = metadata_module.extract_signature(_plain)
    assert stringless == extract_signature(_plain, mcp_format=True)
    assert tool_utils.extract_signature is extract_signature
