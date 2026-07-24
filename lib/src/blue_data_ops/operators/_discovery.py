"""Built-in operator discovery metadata: the six-namespace tag model.

Each concrete operator module owns one static ``DiscoverySpec`` (its ``when_to_invoke`` string and
ordered public ``tags``); the registry factories combine it with the class name/description/version
into an ``OperatorCard``. Built-in specs are validated against closed vocabularies and fail fast
before any partial catalog registration. Custom, non-built-in registrations keep their permissive
legacy behavior (arbitrary tags, empty invocation string) and never reach this validation.

Namespaces (order fixed): ``domain-*`` (exactly one), ``flow-*``, ``accepts-*``, ``produces-*``,
``capability-*`` are always present; ``requires-*`` is optional and names unconditional runtime
infrastructure. A tag asserts a fact that holds in at least one productive public mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field

NAMESPACE_ORDER: tuple[str, ...] = (
    "domain",
    "flow",
    "accepts",
    "produces",
    "capability",
    "requires",
)
REQUIRED_NAMESPACES: frozenset[str] = frozenset(
    {"domain", "flow", "accepts", "produces", "capability"}
)
SINGLE_VALUED: frozenset[str] = frozenset({"domain"})

# Closed built-in vocabularies. Values are the
# full namespaced tags except ``domain-*`` and ``flow-*``, whose bare values are listed.
_DOMAINS: frozenset[str] = frozenset(
    {
        "arithmetic",
        "ml",
        "plan",
        "query-compound",
        "relational",
        "semantic",
        "set",
        "text",
        "vector",
    }
)
_FLOWS: frozenset[str] = frozenset(
    {"plan", "head", "transform", "combine", "aggregate", "control", "sink"}
)
_ACCEPTS: frozenset[str] = frozenset(
    {"accepts-none", "accepts-data", "accepts-metadata", "accepts-query"}
)
_PRODUCES: frozenset[str] = frozenset(
    {
        "produces-data",
        "produces-metadata",
        "produces-plan",
        "produces-query",
        "produces-side-effect",
    }
)
_REQUIRES: frozenset[str] = frozenset(
    {
        "requires-ml",
        "requires-llm",
        "requires-vector",
        "requires-data-registry",
        "requires-database-backend",
        "requires-query-backend",
        "requires-operator-registry",
    }
)
_CAPABILITIES: frozenset[str] = frozenset(
    {
        "capability-average",
        "capability-bayesian-query",
        "capability-classification",
        "capability-clustering",
        "capability-create-database",
        "capability-create-table",
        "capability-delete",
        "capability-discovery",
        "capability-embedding",
        "capability-embedding-filter",
        "capability-extraction",
        "capability-extrema",
        "capability-filter",
        "capability-generation",
        "capability-insert",
        "capability-intersection",
        "capability-join",
        "capability-metadata-search",
        "capability-normalization",
        "capability-operator-discovery",
        "capability-persist",
        "capability-projection",
        "capability-query-decomposition",
        "capability-query-execution",
        "capability-query-generation",
        "capability-query-orchestration",
        "capability-query-routing",
        "capability-record-selection",
        "capability-reduction",
        "capability-search",
        "capability-segmentation",
        "capability-similarity",
        "capability-sql",
        "capability-sum",
        "capability-transformation",
        "capability-union",
    }
)

# Namespace -> the closed set of admissible full tags (None means "any bare value from a set").
_CLOSED_TAGS: dict[str, frozenset[str]] = {
    "accepts": _ACCEPTS,
    "produces": _PRODUCES,
    "capability": _CAPABILITIES,
    "requires": _REQUIRES,
}
_BARE_VALUES: dict[str, frozenset[str]] = {"domain": _DOMAINS, "flow": _FLOWS}


class DiscoveryError(ValueError):
    """A built-in discovery record violates the closed metadata contract (fail fast)."""


@dataclass(frozen=True)
class DiscoverySpec:
    """One built-in operator's authored discovery metadata (invocation guidance + public tags)."""

    when_to_invoke: str
    tags: tuple[str, ...] = field(default=())


def namespace_of(tag: str) -> str:
    """The namespace prefix of a tag (text before the first hyphen)."""
    return tag.split("-", 1)[0]


def _canonical_sort_key(tag: str) -> tuple[int, str]:
    ns = namespace_of(tag)
    return (NAMESPACE_ORDER.index(ns) if ns in NAMESPACE_ORDER else len(NAMESPACE_ORDER), tag)


def validate_builtin_discovery(name: str, spec: DiscoverySpec) -> None:
    """Validate a built-in ``DiscoverySpec`` against the closed vocabularies; raise on violation.

    Enforces: nonempty invocation text; lowercase, hyphenated, unique tags in canonical
    namespace-then-lexicographic order; exactly one ``domain-*``; the five required namespaces
    present; every ``accepts/produces/requires/capability`` tag in its closed vocabulary; and every
    ``domain/flow`` bare value admissible. Custom registrations do not pass through here.
    """
    if not spec.when_to_invoke.strip():
        raise DiscoveryError(f"{name}: when_to_invoke must be nonempty")

    tags = spec.tags
    if len(set(tags)) != len(tags):
        raise DiscoveryError(f"{name}: duplicate tags")
    by_ns: dict[str, list[str]] = {}
    for tag in tags:
        if not tag or tag != tag.lower() or " " in tag or "_" in tag or "-" not in tag:
            raise DiscoveryError(f"{name}: non-canonical tag {tag!r}")
        ns = namespace_of(tag)
        if ns not in NAMESPACE_ORDER:
            raise DiscoveryError(f"{name}: out-of-namespace tag {tag!r}")
        by_ns.setdefault(ns, []).append(tag)

    if list(tags) != sorted(tags, key=_canonical_sort_key):
        raise DiscoveryError(f"{name}: tags not in canonical namespace+lexicographic order")

    for ns in REQUIRED_NAMESPACES:
        if not by_ns.get(ns):
            raise DiscoveryError(f"{name}: missing required namespace {ns}-*")
    for ns in SINGLE_VALUED:
        if len(by_ns.get(ns, [])) != 1:
            raise DiscoveryError(f"{name}: {ns}-* must be single-valued, got {by_ns.get(ns)}")

    for tag in tags:
        ns = namespace_of(tag)
        if ns in _CLOSED_TAGS and tag not in _CLOSED_TAGS[ns]:
            raise DiscoveryError(f"{name}: {tag!r} outside the closed {ns}-* vocabulary")
        if ns in _BARE_VALUES and tag.split("-", 1)[1] not in _BARE_VALUES[ns]:
            raise DiscoveryError(f"{name}: {tag!r} outside the closed {ns}-* vocabulary")


def normalize_filter_tag(token: str) -> str:
    """Normalize one exact-filter tag: strip surrounding whitespace and case-fold.

    Rejects a malformed token — empty after strip, ANY internal whitespace (space, tab, newline, …),
    or no namespace hyphen — with ``DiscoveryError`` so a planner filter fails loudly rather than
    silently matching nothing.
    """
    normalized = token.strip().lower()
    if not normalized or any(ch.isspace() for ch in normalized) or "-" not in normalized:
        raise DiscoveryError(f"malformed filter tag {token!r}")
    return normalized
