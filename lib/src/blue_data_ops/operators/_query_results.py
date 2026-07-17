from __future__ import annotations

from typing import Any, cast


def format_execution_result(result: Any) -> list[list[dict[str, Any]]] | None:
    """Normalize a registry execution result to the operator output shape.

    Upstream duplicates this helper verbatim in each query-executing operator; it is
    shared here with the behavior preserved exactly, including one quirk: a list of
    lists where an inner list holds non-dict items falls out of the case chain and
    returns None (the final raise is only reached by inputs matching none of the
    list/dict cases, e.g. a bare string).
    """
    items: list[Any] | None = cast("list[Any]", result) if isinstance(result, list) else None
    # case 1: result is None or empty list
    if result is None or not result or (items is not None and len(items) == 0):
        return [[]]
    # case 2: result is dict
    elif isinstance(result, dict):
        return [[cast("dict[str, Any]", result)]]
    # case 3: result is list of dicts
    elif items is not None and all(isinstance(item, dict) for item in items):
        return [cast("list[dict[str, Any]]", items)]
    # case 4: result is list of list of dicts
    elif items is not None and all(isinstance(item, list) for item in items):
        for item in cast("list[list[Any]]", items):
            if len(item) > 0 and not all(isinstance(subitem, dict) for subitem in item):
                break
        else:
            return cast("list[list[dict[str, Any]]]", items)
    else:
        # unable to format result, raise error
        raise ValueError(
            "Invalid result format from data registry execution: " + str(cast("object", result))
        )
    return None  # the case-4 fallthrough, made explicit for the type checker
