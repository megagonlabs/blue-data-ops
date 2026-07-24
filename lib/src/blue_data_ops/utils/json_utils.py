"""Blue-compatible JSON merge and JSONPath helpers.

``merge_json`` is Blue's exact object merge, delegated to ``jsonmerge==1.9.2``
(a declared core dependency). ``json_query`` and ``json_query_set`` reproduce
Blue's JSONPath query/set behavior without importing ``blue``.
"""

from __future__ import annotations

from typing import Any, cast

import jsonmerge  # type: ignore[import-not-found]  # pyright: ignore[reportMissingImports]
import jsonpath_ng  # type: ignore[import-untyped]  # pyright: ignore[reportMissingTypeStubs]

# jsonpath-ng and jsonmerge ship no type information; cross the untyped boundary once
# here so downstream matches and merge results are plain ``Any``.
_jp: Any = jsonpath_ng
_Index: Any = jsonpath_ng.Index  # pyright: ignore[reportUnknownMemberType]

__all__ = [
    "json_query",
    "json_query_set",
    "merge_json",
]


def merge_json(original_json: Any, update_json: Any) -> Any:
    """Merge two JSON objects with jsonmerge's default object-merge strategy.

    Mirrors ``blue.utils.json_utils.merge_json`` byte-for-byte, including raising
    on a scalar base against an object head (jsonmerge ``BaseInstanceError``).
    """
    return cast(Any, jsonmerge.merge(original_json, update_json))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]


def json_query(
    json_object: dict[str, Any],
    json_path_query: str,
    single: bool = True,
    default: Any = None,
) -> Any:
    """Query a JSON object with JSONPath (Blue).

    With ``single`` the first match (or ``None``) is returned, otherwise the list
    of matches. When the result is ``None`` and a ``default`` is supplied, the
    default is returned.
    """
    parsed = _jp.parse(json_path_query)
    match_values = [match.value for match in parsed.find(json_object)]

    result: Any = match_values
    if single:
        result = match_values[0] if match_values else None

    if result is None:
        if default is None:
            return result
        return default
    return result


def json_query_set(
    json_object: dict[str, Any],
    attribute: str,
    value: Any,
    context: str = "$",
) -> None:
    """Set ``attribute`` to ``value`` at each JSONPath ``context`` match (Blue).

    At the root context the attribute is set directly. Otherwise each matched
    context must be a dict; index and field paths are updated in place. Raises if
    a non-root context match is not a dict.
    """
    parsed = _jp.parse(context)
    for match in parsed.find(json_object):
        if match.context is None:
            json_object[attribute] = value
        else:
            if type(match.value) is not dict:
                raise Exception("context must be a dict")
            if type(match.path) is _Index:
                match.context.value[match.path.index][attribute] = value
            else:
                for field in match.path.fields:
                    match.context.value[field][attribute] = value
