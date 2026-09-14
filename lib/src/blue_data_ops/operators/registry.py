from __future__ import annotations

import importlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from blue_data_ops.operators._discovery import (
    DiscoverySpec,
    normalize_filter_tag,
    validate_builtin_discovery,
)
from blue_data_ops.operators.operator import (
    Operator,
    _VersionBoundOperator,  # pyright: ignore[reportPrivateUsage]
)

# Resolution is deliberately strict and discovery deliberately loose (two distinct
# APIs): resolve() accepts only a pinned "name@<MAJOR.MINOR.PATCH>" and never answers
# "latest"; find()/find_latest() take loose queries and return already-pinned cards.
# A registered name@version is immutable — no overwrite, no deregister.

_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_PINNED_ID = re.compile(r"^(?P<name>[^@]+)@(?P<version>\d+\.\d+\.\d+)$")
# Blue deployment reference: /server/<server>/(operator|tool)/<name>
_DEPLOYMENT_PATH = re.compile(r"^/server/[^/]+/(?:operator|tool)/(?P<name>[^/]+)$")


class UpgradeError(Exception):
    """A legacy operator reference could not be upgraded to a pinned id (recoverable)."""


# Text-discovery weights: name outranks a tag concept, which outranks invocation
# guidance, which outranks incidental description text. Each field scores at most once.
_NAME_HIT = 10
_TAG_HIT = 8
_WHEN_TO_INVOKE_HIT = 6
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
    when_to_invoke: str = field(default="")
    deprecated: bool = field(default=False)


class OperatorRegistry:
    """In-process operator registry: register, discover, resolve pinned ids."""

    def __init__(self) -> None:
        self._operators: dict[str, Operator] = {}
        self._cards: dict[str, OperatorCard] = {}
        # Built-in origin: pinned ids registered through the built-in path below, never
        # through public register(). It is a set on the registry rather than a field on
        # the card: nothing serializes it, no caller can pass it, and no planning record
        # exports it.
        self._builtin_ids: set[str] = set()
        self._reviewed_builtin_operators: dict[str, Operator] = {}
        self._reviewed_builtin_cards: dict[str, OperatorCard] = {}

    def register(
        self,
        operator: Operator,
        version: str,
        tags: Sequence[str] = (),
        *,
        when_to_invoke: str = "",
        deprecated: bool = False,
    ) -> OperatorCard:
        """Register operator under its class name at version; returns the pinned card.

        Legacy positional ``register(operator, version, tags)`` remains valid; ``when_to_invoke``
        and ``deprecated`` are keyword-only with inert defaults, so custom registrations keep their
        permissive behavior and stay active unless the caller says otherwise. Built-in registration
        passes validated discovery metadata and derives the lifecycle flag.
        """
        name = operator.name
        if not name:
            raise ValueError("operator has no name")
        if not _SEMVER.match(version):
            raise ValueError(f"version must be MAJOR.MINOR.PATCH semver, got: {version!r}")
        operator_id = f"{name}@{version}"
        if operator_id in self._operators:
            raise ValueError(f"{operator_id} is already registered (registrations are immutable)")
        try:
            operator._bind_operator_id(operator_id)  # pyright: ignore[reportPrivateUsage]
            bound_operator = operator
        except ValueError:
            bound_operator = _VersionBoundOperator(operator, operator_id)
        card = OperatorCard(
            operator_id=operator_id,
            name=name,
            version=version,
            description=operator.description,
            tags=tuple(tags),
            when_to_invoke=when_to_invoke,
            deprecated=deprecated,
        )
        self._operators[operator_id] = bound_operator
        self._cards[operator_id] = card
        return card

    def _register_builtin(
        self,
        operator: Operator,
        version: str,
        tags: Sequence[str] = (),
        *,
        when_to_invoke: str = "",
        reviewed: bool = False,
    ) -> OperatorCard:
        """Register a package built-in and, when requested, its planning authority.

        Public ``register()`` remains permissive. Raw compatibility factories use this
        path without granting planner or model-facing authority.
        """
        card = self.register(
            operator,
            version,
            tags,
            when_to_invoke=when_to_invoke,
        )
        self._builtin_ids.add(card.operator_id)
        if reviewed:
            self._reviewed_builtin_operators[card.operator_id] = self._operators[card.operator_id]
            self._reviewed_builtin_cards[card.operator_id] = OperatorCard(
                operator_id=card.operator_id,
                name=card.name,
                version=card.version,
                description=card.description,
                tags=card.tags,
                when_to_invoke=card.when_to_invoke,
                deprecated=card.deprecated,
            )
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

    def find(self, query: str, tags: Sequence[str] | None = None) -> list[OperatorCard]:
        """Rule-based discovery: exact AND tag filter, then case-insensitive text scoring.

        Exact filter (``tags``): each requested tag is normalized (stripped, case-folded), rejected
        if malformed, and matched as a complete token; every requested tag must be present (AND).
        ``None`` or ``[]`` means no filter. Text scoring: name 10, any tag 8, ``when_to_invoke`` 6,
        description 5 — each field at most once; positive scores only; ties order by name then
        descending version. A blank query with tags performs tag-only discovery (name-ascending,
        version-descending); a blank query without tags returns ``[]``.
        """
        filter_tags: set[str] | None = None
        if tags is not None:
            filter_tags = {normalize_filter_tag(token) for token in tags}
        candidates = list(self._cards.values())
        if filter_tags:
            candidates = [card for card in candidates if filter_tags.issubset(set(card.tags))]

        needle = query.strip().lower()
        if not needle:
            if not filter_tags:
                return []
            return sorted(
                candidates,
                key=lambda card: (card.name, tuple(-part for part in _semver_key(card.version))),
            )

        scored: list[tuple[int, str, tuple[int, int, int], OperatorCard]] = []
        for card in candidates:
            score = 0
            if needle in card.name.lower():
                score += _NAME_HIT
            if any(needle in tag.lower() for tag in card.tags):
                score += _TAG_HIT
            if needle in card.when_to_invoke.lower():
                score += _WHEN_TO_INVOKE_HIT
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


# No underscore because plan.openai_generator and plan.planner both import it; it stays
# out of the blue_data_ops.operators surface, so it remains package-internal.
def is_builtin_card(registry: object, card: object) -> bool:
    """Whether `card` is the exact card this registry built from the package factory.

    This is the one origin model every planning caller shares; nothing adds a second.
    Both halves are load-bearing and neither implies the other. Identity proves the
    caller holds *this* registry's card rather than an equal-looking one from another
    `versioned_registry()` result, which matters because the generator goes on to read
    live declarations out of this instance. The provenance set proves the package
    factory registered it, because public `register()` accepts anything a caller hands
    it and an equal-looking custom card would otherwise pass identity.
    """

    if type(registry) is not OperatorRegistry or type(card) is not OperatorCard:
        return False
    return (
        registry.get_card(card.operator_id) is card and card.operator_id in registry._builtin_ids  # pyright: ignore[reportPrivateUsage]
    )


def is_reviewed_builtin_card(registry: object, card: object) -> bool:
    """Return whether a card still matches its reviewed planning registration."""

    if not is_builtin_card(registry, card):
        return False
    typed_registry = cast(OperatorRegistry, registry)
    typed_card = cast(OperatorCard, card)
    operator_id = typed_card.operator_id
    return (
        typed_registry._reviewed_builtin_operators.get(operator_id)  # pyright: ignore[reportPrivateUsage]
        is typed_registry._operators.get(operator_id)  # pyright: ignore[reportPrivateUsage]
        and typed_registry._reviewed_builtin_cards.get(operator_id) == typed_card  # pyright: ignore[reportPrivateUsage]
    )


def _semver_key(version: str) -> tuple[int, int, int]:
    major, minor, patch = version.split(".")
    return int(major), int(minor), int(patch)


def _builtin_operator_classes() -> tuple[type[Operator], ...]:
    """The 33 retained built-in operator classes as one explicit, name-ordered tuple.

    Imported lazily so this module stays out of the operator/registry import
    cycle. All public factories build their inventory from this single tuple;
    package export scanning never decides the catalog.
    """
    from blue_data_ops.operators.argmax_operator import ArgmaxOperator
    from blue_data_ops.operators.argmin_operator import ArgminOperator
    from blue_data_ops.operators.avg_operator import AvgOperator
    from blue_data_ops.operators.classify_operator import ClassifyOperator
    from blue_data_ops.operators.cluster_operator import ClusterOperator
    from blue_data_ops.operators.create_database_operator import CreateDatabaseOperator
    from blue_data_ops.operators.create_table_operator import CreateTableOperator
    from blue_data_ops.operators.data_discover_operator import DataDiscoverOperator
    from blue_data_ops.operators.delete_operator import DeleteOperator
    from blue_data_ops.operators.insert_operator import InsertOperator
    from blue_data_ops.operators.insert_table_operator import InsertTableOperator
    from blue_data_ops.operators.intersect_operator import IntersectOperator
    from blue_data_ops.operators.join_operator import JoinOperator
    from blue_data_ops.operators.max_operator import MaxOperator
    from blue_data_ops.operators.min_operator import MinOperator
    from blue_data_ops.operators.nl2bn_operator import NL2BNOperator
    from blue_data_ops.operators.nl2llm_operator import NL2LLMOperator
    from blue_data_ops.operators.nl2sql_operator import NL2SQLOperator
    from blue_data_ops.operators.normalize_text_operator import NormalizeTextOperator
    from blue_data_ops.operators.project_operator import ProjectOperator
    from blue_data_ops.operators.segment_text_operator import SegmentTextOperator
    from blue_data_ops.operators.select_operator import SelectOperator
    from blue_data_ops.operators.semantic_extract_operator import SemanticExtractOperator
    from blue_data_ops.operators.semantic_filter_operator import SemanticFilterOperator
    from blue_data_ops.operators.semantic_join_operator import SemanticJoinOperator
    from blue_data_ops.operators.semantic_project_operator import SemanticProjectOperator
    from blue_data_ops.operators.semantic_transform_operator import SemanticTransformOperator
    from blue_data_ops.operators.sklearn_estimator import SklearnEstimator
    from blue_data_ops.operators.sum_operator import SumOperator
    from blue_data_ops.operators.union_operator import UnionOperator
    from blue_data_ops.operators.vector_embed_operator import VectorEmbedOperator
    from blue_data_ops.operators.vector_search_operator import VectorSearchOperator
    from blue_data_ops.operators.vector_similarity_operator import VectorSimilarityOperator

    return (
        ArgmaxOperator,
        ArgminOperator,
        AvgOperator,
        ClassifyOperator,
        ClusterOperator,
        CreateDatabaseOperator,
        CreateTableOperator,
        DataDiscoverOperator,
        DeleteOperator,
        InsertOperator,
        InsertTableOperator,
        IntersectOperator,
        JoinOperator,
        MaxOperator,
        MinOperator,
        NL2BNOperator,
        NL2LLMOperator,
        NL2SQLOperator,
        NormalizeTextOperator,
        ProjectOperator,
        SegmentTextOperator,
        SelectOperator,
        SemanticExtractOperator,
        SemanticFilterOperator,
        SemanticJoinOperator,
        SemanticProjectOperator,
        SemanticTransformOperator,
        SklearnEstimator,
        SumOperator,
        UnionOperator,
        VectorEmbedOperator,
        VectorSearchOperator,
        VectorSimilarityOperator,
    )


def upgrade_legacy_operator_id(
    reference: str,
    registry: OperatorRegistry,
    *,
    target_version: str,
    aliases: dict[str, str] | None = None,
) -> str:
    """Convert a legacy operator reference to a registered pinned id — never implicitly.

    Accepts an already pinned ``name@version`` unchanged (validated as registered). Otherwise parses
    an explicit alias, a bare name, or a legacy ``/server/<server>/(operator|tool)/<name>`` path and
    resolves it to ``name@target_version``. Alias values must themselves be registered pinned ids.
    Missing, malformed, ambiguous, or unregistered targets raise ``UpgradeError``. ``resolve()`` and
    ``DataPipeline.from_dict()`` never call this; upgrading is always an explicit caller choice.
    """
    if not _SEMVER.match(target_version):
        raise UpgradeError(f"target_version must be MAJOR.MINOR.PATCH semver: {target_version!r}")

    pinned = _PINNED_ID.match(reference)
    if pinned:
        if registry.get_card(reference) is None:
            raise UpgradeError(f"pinned reference is not registered: {reference!r}")
        return reference

    is_alias = bool(aliases) and reference in (aliases or {})
    bare_candidate = (
        f"{reference}@{target_version}"
        if reference and "@" not in reference and "/" not in reference
        else None
    )
    bare_is_registered = (
        bare_candidate is not None and registry.get_card(bare_candidate) is not None
    )
    if is_alias and bare_is_registered:
        # A token that is both a registered bare name and an alias key is ambiguous; the contract
        # says ambiguous references fail (it does not grant alias precedence).
        raise UpgradeError(
            f"ambiguous reference {reference!r}: both a registered name and an alias key"
        )
    if is_alias:
        alias_target = (aliases or {})[reference]
        if not _PINNED_ID.match(alias_target):
            raise UpgradeError(f"alias value must be a pinned id: {alias_target!r}")
        if registry.get_card(alias_target) is None:
            raise UpgradeError(f"alias target is not registered: {alias_target!r}")
        return alias_target

    path = _DEPLOYMENT_PATH.match(reference)
    name = path.group("name") if path else reference
    if not name or "@" in name or "/" in name:
        raise UpgradeError(f"unrecognized legacy operator reference: {reference!r}")
    candidate = f"{name}@{target_version}"
    if registry.get_card(candidate) is None:
        raise UpgradeError(f"no operator registered as {candidate!r}")
    return candidate


def _builtin_discovery_specs() -> dict[type[Operator], DiscoverySpec]:
    """Read and validate every built-in's static ``DISCOVERY`` before any catalog registration.

    Validation runs in a pre-pass so an invalid built-in spec fails fast — no partial catalog is
    ever registered. The metadata lives beside each operator class as a module ``DISCOVERY`` const.
    """
    specs: dict[type[Operator], DiscoverySpec] = {}
    for operator_class in _builtin_operator_classes():
        module = importlib.import_module(operator_class.__module__)
        spec = cast(DiscoverySpec, module.DISCOVERY)
        validate_builtin_discovery(operator_class.name, spec)
        specs[operator_class] = spec
    return specs


def default_registry(**versions: Any) -> OperatorRegistry:
    """Convenience: a registry pre-loaded with this package's operators at 1.0.0.

    Keyword overrides pin individual operators to other versions,
    e.g. ``default_registry(nl2sql="1.1.0")``. Unknown override keys are
    silently ignored.

    This is the retained raw-v1 compatibility surface: it validates built-in discovery metadata
    fail-fast, but registers cards without tags or ``when_to_invoke``. The enriched metadata lives
    on ``active_registry()`` and ``versioned_registry()``.
    """
    _builtin_discovery_specs()  # fail-fast validation of the built-in metadata; raw v1 cards below
    outcome_classes = _outcome_operator_classes()
    registry = OperatorRegistry()
    for operator_class in _builtin_operator_classes():
        version = str(versions.get(operator_class.name, "1.0.0"))
        selected_class = (
            outcome_classes.get(operator_class.name, operator_class)
            if version == "3.0.0"
            else operator_class
        )
        instance = selected_class()
        registry._register_builtin(instance, version)  # pyright: ignore[reportPrivateUsage]
    return registry


def versioned_registry() -> OperatorRegistry:
    """Return 87 retained pinned cards, including 21 outcome operators at 3.0.0.

    Separate instances back each exact version. Every card carries validated
    discovery metadata.
    """
    specs = _builtin_discovery_specs()
    outcome_classes = _outcome_operator_classes()
    registry = OperatorRegistry()
    for operator_class in _builtin_operator_classes():
        spec = specs[operator_class]
        registry._register_builtin(  # pyright: ignore[reportPrivateUsage]
            operator_class(),
            "2.0.0",
            tags=spec.tags,
            when_to_invoke=spec.when_to_invoke,
            reviewed=True,
        )
        registry._register_builtin(  # pyright: ignore[reportPrivateUsage]
            operator_class(), "1.0.0", tags=spec.tags, when_to_invoke=spec.when_to_invoke
        )
        outcome_class = outcome_classes.get(operator_class.name)
        if outcome_class is not None:
            registry._register_builtin(  # pyright: ignore[reportPrivateUsage]
                outcome_class(),
                "3.0.0",
                tags=spec.tags,
                when_to_invoke=spec.when_to_invoke,
                reviewed=True,
            )
    return registry


_ACTIVE_OPERATOR_VERSIONS: tuple[tuple[str, str], ...] = (
    ("argmax", "2.0.0"),
    ("argmin", "2.0.0"),
    ("avg", "3.0.0"),
    ("classify", "3.0.0"),
    ("cluster", "3.0.0"),
    ("create_database", "2.0.0"),
    ("create_table", "2.0.0"),
    ("data_discover", "2.0.0"),
    ("delete", "2.0.0"),
    ("insert", "3.0.0"),
    ("insert_table", "3.0.0"),
    ("intersect", "3.0.0"),
    ("join", "3.0.0"),
    ("max", "3.0.0"),
    ("min", "3.0.0"),
    ("nl2bn", "3.0.0"),
    ("nl2llm", "3.0.0"),
    ("nl2sql", "3.0.0"),
    ("normalize_text", "2.0.0"),
    ("project", "3.0.0"),
    ("segment_text", "2.0.0"),
    ("select", "2.0.0"),
    ("semantic_extract", "3.0.0"),
    ("semantic_filter", "3.0.0"),
    ("semantic_join", "3.0.0"),
    ("semantic_project", "3.0.0"),
    ("semantic_transform", "3.0.0"),
    ("sklearn_estimator", "2.0.0"),
    ("sum", "2.0.0"),
    ("union", "2.0.0"),
    ("vector_embed", "3.0.0"),
    ("vector_search", "3.0.0"),
    ("vector_similarity", "3.0.0"),
)
_ACTIVE_OPERATOR_IDS: tuple[str, ...] = tuple(
    f"{name}@{version}" for name, version in _ACTIVE_OPERATOR_VERSIONS
)


def active_registry() -> OperatorRegistry:
    """Return a fresh registry containing the exact reviewed active built-ins."""

    specs = _builtin_discovery_specs()
    classes = {
        operator_class.name: operator_class for operator_class in _builtin_operator_classes()
    }
    outcomes = _outcome_operator_classes()
    registry = OperatorRegistry()
    for name, version in _ACTIVE_OPERATOR_VERSIONS:
        operator_class = outcomes[name] if version == "3.0.0" else classes[name]
        spec = specs[classes[name]]
        registry._register_builtin(  # pyright: ignore[reportPrivateUsage]
            operator_class(),
            version,
            tags=spec.tags,
            when_to_invoke=spec.when_to_invoke,
            reviewed=True,
        )
    return registry


def _outcome_operator_classes() -> dict[str, type[Operator]]:
    from blue_data_ops.operators._avg_outcome import AvgOutcomeOperator
    from blue_data_ops.operators._classify_outcome import ClassifyOutcomeOperator
    from blue_data_ops.operators._cluster_outcome import ClusterOutcomeOperator
    from blue_data_ops.operators._insert_outcome import InsertOutcomeOperator
    from blue_data_ops.operators._insert_table_outcome import (
        InsertTableOutcomeOperator,
    )
    from blue_data_ops.operators._intersect_outcome import IntersectOutcomeOperator
    from blue_data_ops.operators._join_outcome import JoinOutcomeOperator
    from blue_data_ops.operators._max_outcome import MaxOutcomeOperator
    from blue_data_ops.operators._min_outcome import MinOutcomeOperator
    from blue_data_ops.operators._nl2bn_outcome import NL2BNOutcomeOperator
    from blue_data_ops.operators._nl2llm_outcome import NL2LLMOutcomeOperator
    from blue_data_ops.operators._nl2sql_outcome import NL2SQLOutcomeOperator
    from blue_data_ops.operators._project_outcome import ProjectOutcomeOperator
    from blue_data_ops.operators._semantic_extract_outcome import (
        SemanticExtractOutcomeOperator,
    )
    from blue_data_ops.operators._semantic_filter_outcome import (
        SemanticFilterOutcomeOperator,
    )
    from blue_data_ops.operators._semantic_join_outcome import (
        SemanticJoinOutcomeOperator,
    )
    from blue_data_ops.operators._semantic_project_outcome import (
        SemanticProjectOutcomeOperator,
    )
    from blue_data_ops.operators._semantic_transform_outcome import (
        SemanticTransformOutcomeOperator,
    )
    from blue_data_ops.operators._vector_embed_outcome import VectorEmbedOutcomeOperator
    from blue_data_ops.operators._vector_search_outcome import VectorSearchOutcomeOperator
    from blue_data_ops.operators._vector_similarity_outcome import (
        VectorSimilarityOutcomeOperator,
    )

    return {
        "avg": AvgOutcomeOperator,
        "classify": ClassifyOutcomeOperator,
        "cluster": ClusterOutcomeOperator,
        "insert": InsertOutcomeOperator,
        "insert_table": InsertTableOutcomeOperator,
        "intersect": IntersectOutcomeOperator,
        "join": JoinOutcomeOperator,
        "max": MaxOutcomeOperator,
        "min": MinOutcomeOperator,
        "nl2bn": NL2BNOutcomeOperator,
        "nl2llm": NL2LLMOutcomeOperator,
        "nl2sql": NL2SQLOutcomeOperator,
        "project": ProjectOutcomeOperator,
        "semantic_extract": SemanticExtractOutcomeOperator,
        "semantic_filter": SemanticFilterOutcomeOperator,
        "semantic_join": SemanticJoinOutcomeOperator,
        "semantic_project": SemanticProjectOutcomeOperator,
        "semantic_transform": SemanticTransformOutcomeOperator,
        "vector_embed": VectorEmbedOutcomeOperator,
        "vector_search": VectorSearchOutcomeOperator,
        "vector_similarity": VectorSimilarityOutcomeOperator,
    }
