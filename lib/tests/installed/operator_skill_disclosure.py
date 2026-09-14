from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast


def _resource_root() -> Path:
    import blue_data_ops.operator_skills as operator_skills

    module_location = operator_skills.__file__
    assert isinstance(module_location, str)
    return Path(module_location).resolve().parent


def _resource_listener(events: list[Path]) -> None:
    def listener(event: str, arguments: tuple[object, ...]) -> None:
        if event != "open" or not arguments:
            return
        raw_path = arguments[0]
        if isinstance(raw_path, str):
            path_text = raw_path
        elif isinstance(raw_path, os.PathLike):
            path_text = os.fspath(cast(os.PathLike[str], raw_path))
        else:
            return
        try:
            path = Path(path_text).resolve()
        except (OSError, TypeError, ValueError):
            return
        if path.suffix in {".json", ".md"}:
            events.append(path)

    sys.addaudithook(listener)


def _resource_events(root: Path, events: list[Path]) -> list[str]:
    return [path.relative_to(root).as_posix() for path in events if path.is_relative_to(root)]


def _negative_paths(include_mcp: bool) -> None:
    import blue_data_ops
    from blue_data_ops.operators import active_registry
    from blue_data_ops.plan import (
        DiscoveryQuery,
        PipelinePlanner,
        PlanningRequest,
        RulePlanGenerator,
    )

    assert blue_data_ops.__file__
    registry = active_registry()
    cards = registry.list_cards()
    assert cards
    registry.find("average")
    average_card = next(card for card in cards if "capability-average" in card.tags)

    request = PlanningRequest(
        goal="average values",
        discovery_queries=(DiscoveryQuery("average", tags=("capability-average",)),),
        allowed_operator_ids=(average_card.operator_id,),
    )
    planner = PipelinePlanner(registry, RulePlanGenerator())
    planner.discover(request)
    registry.resolve(average_card.operator_id).run([[{"value": 1}]], {"avg_key": "value"})

    if include_mcp:
        registration = importlib.import_module("blue_data_ops_mcp.registration")
        freeze_deployment = cast(
            Callable[[object], object],
            getattr(registration, "freeze_deployment"),
        )
        assert freeze_deployment(registry)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("positive", "negative"))
    parser.add_argument("--include-mcp", action="store_true")
    arguments = parser.parse_args()

    observed_paths: list[Path] = []
    _resource_listener(observed_paths)
    root = _resource_root()
    if arguments.mode == "positive":
        (root / "_index.json").read_bytes()
        events = _resource_events(root, observed_paths)
        assert events == ["_index.json"]
    else:
        _negative_paths(bool(arguments.include_mcp))
        events = _resource_events(root, observed_paths)
        assert events == [], f"implicit operator skill reads: {events}"
    print(json.dumps({"events": events, "mode": arguments.mode}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
