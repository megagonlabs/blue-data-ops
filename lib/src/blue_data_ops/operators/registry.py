from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from types import GenericAlias
from typing import Any

from blue_data_ops.operators.operator import Operator

# Resolution is deliberately strict and discovery deliberately loose (two distinct
# APIs): resolve() accepts only a pinned "name@<MAJOR.MINOR.PATCH>" and never answers
# "latest"; find()/find_latest() take loose queries and return already-pinned cards.
# A registered name@version is immutable — no overwrite, no deregister.

_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

# Rule-based discovery scoring, mirroring the registry keyword convention
# (name over description), with tags between the two.
_NAME_HIT = 10
_TAG_HIT = 8
_DESCRIPTION_HIT = 5


class ResolveError(Exception):
    """A pinned operator reference could not be resolved (recoverable)."""


@dataclass(frozen=True)
class OperatorCard:
    """Discovery-facing operator metadata; its operator_id is always pinned."""

    operator_id: str  # "<name>@<MAJOR.MINOR.PATCH>"
    name: str
    version: str
    description: str
    tags: tuple[str, ...] = field(default=())


class OperatorRegistry:
    """In-process operator registry: register, discover, resolve pinned ids."""

    def __init__(self) -> None:
        self._operators: dict[str, Operator] = {}
        self._cards: dict[str, OperatorCard] = {}

    def register(self, operator: Operator, version: str, tags: Sequence[str] = ()) -> OperatorCard:
        """Register operator under its class name at version; returns the pinned card."""
        name = operator.name
        if not name:
            raise ValueError("operator has no name")
        if not _SEMVER.match(version):
            raise ValueError(f"version must be MAJOR.MINOR.PATCH semver, got: {version!r}")
        operator_id = f"{name}@{version}"
        if operator_id in self._operators:
            raise ValueError(f"{operator_id} is already registered (registrations are immutable)")
        card = OperatorCard(
            operator_id=operator_id,
            name=name,
            version=version,
            description=operator.description,
            tags=tuple(tags),
        )
        self._operators[operator_id] = operator
        self._cards[operator_id] = card
        return card

    def resolve(self, operator_id: str) -> Operator:
        """Resolve a pinned "name@version" to exactly that operator.

        A bare name (or any non-pinned reference) is a ResolveError — "latest"
        lives only in discovery.
        """
        name, separator, version = operator_id.partition("@")
        if not separator or not name or not _SEMVER.match(version):
            raise ResolveError(
                f"not a pinned operator id (expected name@<MAJOR.MINOR.PATCH>): {operator_id!r}"
            )
        operator = self._operators.get(operator_id)
        if operator is None:
            raise ResolveError(f"no operator registered as {operator_id!r}")
        return operator

    def get_card(self, operator_id: str) -> OperatorCard | None:
        """Pinned-id card lookup; not-found is None."""
        return self._cards.get(operator_id)

    def find(self, query: str) -> list[OperatorCard]:
        """Rule-based discovery over name/description/tags (query may be a bare name).

        Case-insensitive substring scoring: a name hit outranks a tag hit outranks
        a description hit; ties order by name then by descending version.
        """
        needle = query.strip().lower()
        if not needle:
            return []
        scored: list[tuple[int, str, tuple[int, int, int], OperatorCard]] = []
        for card in self._cards.values():
            score = 0
            if needle in card.name.lower():
                score += _NAME_HIT
            if any(needle in tag.lower() for tag in card.tags):
                score += _TAG_HIT
            if needle in card.description.lower():
                score += _DESCRIPTION_HIT
            if score > 0:
                scored.append((score, card.name, _semver_key(card.version), card))
        scored.sort(key=lambda item: (-item[0], item[1], tuple(-part for part in item[2])))
        return [card for _, _, _, card in scored]

    def find_latest(self, name: str) -> OperatorCard | None:
        """The highest-version card for an exact name; None when unregistered."""
        candidates = [card for card in self._cards.values() if card.name == name]
        if not candidates:
            return None
        return max(candidates, key=lambda card: _semver_key(card.version))

    def list_cards(self) -> list[OperatorCard]:
        """Every registered card, ordered by name then descending version."""
        return sorted(
            self._cards.values(),
            key=lambda card: (card.name, tuple(-part for part in _semver_key(card.version))),
        )


def _semver_key(version: str) -> tuple[int, int, int]:
    major, minor, patch = version.split(".")
    return int(major), int(minor), int(patch)


def default_registry(**versions: Any) -> OperatorRegistry:
    """Convenience: a registry pre-loaded with this package's operators at 1.0.0.

    Keyword overrides pin individual operators to other versions,
    e.g. default_registry(nl2sql="1.1.0").
    """
    from blue_data_ops import operators as operator_package

    registry = OperatorRegistry()
    for attr_name in operator_package.__all__:
        candidate = getattr(operator_package, attr_name)
        # Python 3.10 treats PEP 585 aliases as types that ABCMeta rejects.
        if isinstance(candidate, GenericAlias):
            continue
        if (
            isinstance(candidate, type)
            and issubclass(candidate, Operator)
            and candidate is not Operator
        ):
            instance = candidate()
            version = str(versions.get(instance.name, "1.0.0"))
            registry.register(instance, version)
    return registry
