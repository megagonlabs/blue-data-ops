from __future__ import annotations

from typing import Any, ClassVar, Protocol

PlanRecord = dict[str, Any]


class Constant(str):
    """String constant with value-based equality."""


class Status(Constant):
    """Execution status stored on a pipeline node."""

    INITED: ClassVar[Status]
    REFINING: ClassVar[Status]
    REFINED: ClassVar[Status]
    EXECUTING: ClassVar[Status]
    EXECUTED: ClassVar[Status]
    PLANNED: ClassVar[Status]
    FAILED: ClassVar[Status]


Status.INITED = Status("INITED")
Status.REFINING = Status("REFINING")
Status.REFINED = Status("REFINED")
Status.EXECUTING = Status("EXECUTING")
Status.EXECUTED = Status("EXECUTED")
Status.PLANNED = Status("PLANNED")
Status.FAILED = Status("FAILED")


class NodeType(Constant):
    """Node kinds supported by a data pipeline."""

    INPUT: ClassVar[NodeType]
    OUTPUT: ClassVar[NodeType]
    OPERATOR: ClassVar[NodeType]


NodeType.INPUT = NodeType("INPUT")
NodeType.OUTPUT = NodeType("OUTPUT")
NodeType.OPERATOR = NodeType("OPERATOR")


class EntityType(Constant):
    """Entity kinds linked to pipeline nodes."""

    OPERATOR: ClassVar[EntityType]
    DATA_PIPELINE: ClassVar[EntityType]


EntityType.OPERATOR = EntityType("OPERATOR")
EntityType.DATA_PIPELINE = EntityType("DATA_PIPELINE")


class SyncBackend(Protocol):
    """Optional callback receiving one synchronized pipeline change."""

    def __call__(self, path: str, key: str, value: Any) -> None:
        """Persist or publish one value at path and key."""
        ...
