"""Bounded read-only data context for planning.

The module holds the planning error vocabulary as well as the data-context contracts.
`DataScope` is part of `PlanningRequest` and the data-context boundary raises the same
structured records the planner does, so both need one record type; keeping that type
here rather than in `planner` is what lets `planner` import `context` without a cycle.

A snapshot is advisory schema context. It never carries rows, relations, connection
details, or arbitrary registry metadata: the payload shape below is closed, so there is
no field an unexpected value could travel in. Execution-time registry, query, and
operator validation stay authoritative.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import Any, NamedTuple, Protocol, cast

from blue_data_ops.data.registry_seam import RegistrySeam
from blue_data_ops.operators.types import ErrorCategory

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]

DATA_CONTEXT_FORMAT = "blue-data-ops/data-context@1"

# Fixed rather than an adapter argument, because it describes the wire representation
# of a name, not a caller-tunable budget.
MAX_NAME_OR_TYPE_CODEPOINTS = 128

_PAYLOAD_KEYS = frozenset({"protocol", "schema", "provenance", "limits"})
_ENTITY_KEYS = frozenset({"name", "description", "attributes"})
_ENTITY_REQUIRED_KEYS = frozenset({"name", "attributes"})
_ATTRIBUTE_KEYS = frozenset({"name", "type"})
_LIMIT_KEYS = (
    "max_entities",
    "max_attributes_per_entity",
    "max_total_attributes",
    "max_description_chars",
    "max_name_or_type_codepoints",
    "max_serialized_bytes",
    "max_raw_rows",
)
# No depth ceiling: an undeclared bound would reject finite acyclic JSON well inside
# the recorded byte limit. What has to terminate is a self-reference, and cycle
# detection is what does that.


class PlanningStage(str, Enum):
    VALIDATION = "VALIDATION"
    DISCOVERY = "DISCOVERY"
    DATA_CONTEXT = "DATA_CONTEXT"
    GENERATION = "GENERATION"
    SELECTION = "SELECTION"
    COMPILATION = "COMPILATION"
    PREFLIGHT = "PREFLIGHT"


class PlanningErrorCode(str, Enum):
    INVALID_REQUEST = "INVALID_REQUEST"
    DISCOVERY_FAILED = "DISCOVERY_FAILED"
    DISCOVERY_RESULT_INVALID = "DISCOVERY_RESULT_INVALID"
    DATA_CONTEXT_REQUIRED = "DATA_CONTEXT_REQUIRED"
    DATA_CONTEXT_UNAVAILABLE = "DATA_CONTEXT_UNAVAILABLE"
    DATA_CONTEXT_SCOPE_MISMATCH = "DATA_CONTEXT_SCOPE_MISMATCH"
    DATA_CONTEXT_RESULT_INVALID = "DATA_CONTEXT_RESULT_INVALID"
    DATA_CONTEXT_LIMIT_EXCEEDED = "DATA_CONTEXT_LIMIT_EXCEEDED"
    DATA_CONTEXT_FAILED = "DATA_CONTEXT_FAILED"
    # A snapshot reached a generator that was not configured to disclose one. It sits
    # with the data-context codes because that is the boundary it protects, but only a
    # provider-backed generator can raise it.
    DATA_CONTEXT_DISCLOSURE_REQUIRED = "DATA_CONTEXT_DISCLOSURE_REQUIRED"
    GENERATION_FAILED = "GENERATION_FAILED"
    GENERATION_RESULT_INVALID = "GENERATION_RESULT_INVALID"
    # Provider-backed generator outcomes. They are provider-independent by design: the
    # names describe what happened to planning, not which SDK or HTTP status produced
    # it, and no provider text reaches the record.
    GENERATOR_DEPENDENCY_MISSING = "GENERATOR_DEPENDENCY_MISSING"
    GENERATOR_REQUEST_REJECTED = "GENERATOR_REQUEST_REJECTED"
    GENERATOR_TIMEOUT = "GENERATOR_TIMEOUT"
    GENERATOR_RATE_LIMITED = "GENERATOR_RATE_LIMITED"
    GENERATOR_UNAVAILABLE = "GENERATOR_UNAVAILABLE"
    GENERATOR_REFUSED = "GENERATOR_REFUSED"
    GENERATOR_RESPONSE_INVALID = "GENERATOR_RESPONSE_INVALID"
    CANDIDATE_LIMIT_EXCEEDED = "CANDIDATE_LIMIT_EXCEEDED"
    NO_CANDIDATES = "NO_CANDIDATES"
    AMBIGUOUS_CANDIDATES = "AMBIGUOUS_CANDIDATES"
    SELECTION_FAILED = "SELECTION_FAILED"
    SELECTION_RESULT_INVALID = "SELECTION_RESULT_INVALID"
    PLAN_INVALID = "PLAN_INVALID"
    PLAN_LIMIT_EXCEEDED = "PLAN_LIMIT_EXCEEDED"
    COMPILATION_FAILED = "COMPILATION_FAILED"
    PREFLIGHT_FAILED = "PREFLIGHT_FAILED"
    RESULT_COPY_FAILED = "RESULT_COPY_FAILED"


class PlanningErrorRecord(NamedTuple):
    category: ErrorCategory
    code: PlanningErrorCode
    stage: PlanningStage
    message: str
    retryable: bool
    suggestion: str | None


class PlanningError(ValueError):
    """A planning failure with a stable structured record."""

    record: PlanningErrorRecord

    def __init__(self, value: str | PlanningErrorRecord) -> None:
        if isinstance(value, str):
            record = PlanningErrorRecord(
                category=ErrorCategory.FAILED,
                code=PlanningErrorCode.GENERATION_FAILED,
                stage=PlanningStage.GENERATION,
                message=value,
                retryable=False,
                suggestion=None,
            )
        else:
            record = value
        self.record = record
        super().__init__(record.message)


# planning_error() and invalid_request() carry no underscore because planner imports
# them; they stay out of the blue_data_ops.plan surface, so they remain package-internal.
def planning_error(
    stage: PlanningStage,
    code: PlanningErrorCode,
    message: str,
    *,
    category: ErrorCategory,
    suggestion: str | None,
    retryable: bool = False,
) -> PlanningError:
    return PlanningError(
        PlanningErrorRecord(
            category=category,
            code=code,
            stage=stage,
            message=message,
            retryable=retryable,
            suggestion=suggestion,
        )
    )


def invalid_request(message: str) -> PlanningError:
    return planning_error(
        PlanningStage.VALIDATION,
        PlanningErrorCode.INVALID_REQUEST,
        message,
        category=ErrorCategory.RECOVERABLE,
        suggestion="Correct the planning request and try again.",
    )


# Every data-context message below is a fixed string. Registry values — entity names,
# descriptions, declared types, connection properties — and provider exception text are
# never interpolated, so no record can carry schema content out of the boundary.
#
# The planner surfaces these records directly for an exact RegistryDataContextProvider.
# That is sound because the class implementation of `collect()` dispatches through no
# caller-replaceable attribute: the registry is reached only inside `_read()`, the limits
# are validated and copied into package-owned state on entry, and every helper it calls
# is a module-level function. A caller therefore has no way to raise a PlanningError from
# inside it, so no record needs to authenticate itself after the fact.
def _data_context_error(
    code: PlanningErrorCode,
    message: str,
    *,
    category: ErrorCategory,
    suggestion: str,
) -> PlanningError:
    return planning_error(
        PlanningStage.DATA_CONTEXT,
        code,
        message,
        category=category,
        suggestion=suggestion,
    )


def _malformed_context(message: str) -> PlanningError:
    return _data_context_error(
        PlanningErrorCode.DATA_CONTEXT_RESULT_INVALID,
        message,
        category=ErrorCategory.FAILED,
        suggestion="Return a well-formed data-context snapshot.",
    )


def _context_limit_exceeded(message: str) -> PlanningError:
    return _data_context_error(
        PlanningErrorCode.DATA_CONTEXT_LIMIT_EXCEEDED,
        message,
        category=ErrorCategory.RECOVERABLE,
        suggestion="Narrow DataScope.entities or raise the corresponding context limit.",
    )


def _context_unavailable(message: str) -> PlanningError:
    return _data_context_error(
        PlanningErrorCode.DATA_CONTEXT_UNAVAILABLE,
        message,
        category=ErrorCategory.RECOVERABLE,
        suggestion="Check the data scope against the registered collection.",
    )


def _context_read_failed() -> PlanningError:
    return _data_context_error(
        PlanningErrorCode.DATA_CONTEXT_FAILED,
        "data context collection failed",
        category=ErrorCategory.FAILED,
        suggestion="Check the data registry and the context provider.",
    )


def context_read_failure() -> PlanningError:
    """The generic record the planner uses for any failure of a foreign provider."""

    return _context_read_failed()


def _nonempty_str(value: object) -> str | None:
    """Return an exact, non-blank `str` — never a `str` subclass."""

    if type(value) is not str:
        return None
    return value if value.strip() else None


def _exact_count(value: object) -> int | None:
    # `type(...) is int` and not `isinstance`: bool is an int subclass, and an int
    # subclass can carry hostile behavior into a later comparison.
    return value if type(value) is int else None


def _string_keyed(value: object) -> dict[str, object] | None:
    """Return an exact `dict` whose keys are all exact `str`, else `None`."""

    if type(value) is not dict:
        return None
    mapping = cast("dict[object, object]", value)
    if any(type(key) is not str for key in mapping):
        return None
    return cast("dict[str, object]", mapping)


def _exact_list(value: object) -> list[object] | None:
    return cast("list[object]", value) if type(value) is list else None


@dataclass(frozen=True)
class DataScope:
    """The exact registry address, plus an advisory entity projection, used to plan.

    An empty `entities` tuple requests the whole collection subject to the schema
    limits; a nonempty tuple requests an exact projection and is canonicalized into
    name-sorted order. The projection is planning context, not SQL authorization.
    """

    source: str
    database: str
    collection: str
    entities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value in (self.source, self.database, self.collection):
            if type(value) is not str:
                raise invalid_request("data scope is malformed")
            if not value.strip():
                raise invalid_request("data scope source, database, and collection are required")
        if type(self.entities) is not tuple:
            raise invalid_request("data scope is malformed")
        for entity in cast("tuple[object, ...]", self.entities):
            if type(entity) is not str:
                raise invalid_request("data scope is malformed")
            if not entity.strip():
                raise invalid_request("data scope entity names must be nonempty")
        if len(set(self.entities)) != len(self.entities):
            raise invalid_request("data scope entity names must be unique")
        if self.entities:
            object.__setattr__(self, "entities", tuple(sorted(self.entities)))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "source": self.source,
            "database": self.database,
            "collection": self.collection,
            "entities": list(self.entities),
        }


def _freeze(value: object) -> Any:
    if isinstance(value, Mapping):
        mapping = cast("Mapping[str, object]", value)
        return MappingProxyType({key: _freeze(item) for key, item in mapping.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in cast("list[object]", value))
    return value


def _thaw(value: object) -> Any:
    if isinstance(value, Mapping):
        mapping = cast("Mapping[str, object]", value)
        return {key: _thaw(item) for key, item in mapping.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in cast("tuple[object, ...]", value)]
    return value


def _canonical_bytes(document: Mapping[str, JsonValue]) -> bytes:
    # RecursionError here is the interpreter's stack ceiling, not one of the declared
    # limits, so it is reported as a document that cannot be represented rather than as
    # a limit the payload exceeded.
    try:
        return json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except RecursionError:
        raise _malformed_context("data context could not be serialized") from None


def _validate_limits(payload: Mapping[str, object]) -> dict[str, int]:
    limits = _string_keyed(payload.get("limits"))
    if limits is None or set(limits) != set(_LIMIT_KEYS):
        raise _malformed_context("data context limits are malformed")
    checked: dict[str, int] = {}
    for key in _LIMIT_KEYS:
        count = _exact_count(limits[key])
        if count is None:
            raise _malformed_context("data context limits are malformed")
        checked[key] = count
    if checked["max_raw_rows"] != 0:
        raise _malformed_context("data context cannot declare a raw-row budget")
    if any(checked[key] < 1 for key in _LIMIT_KEYS if key != "max_raw_rows"):
        raise _malformed_context("data context limits must be positive")
    # The name/type bound describes the wire representation, so it is the one limit a
    # payload reports rather than chooses. Accepting a declared 129 here would let a
    # provider raise the very bound this validator is meant to enforce.
    if checked["max_name_or_type_codepoints"] != MAX_NAME_OR_TYPE_CODEPOINTS:
        raise _malformed_context("data context cannot redeclare the name and type limit")
    return checked


def _is_finite_json(value: object, *, active: set[int] | None = None) -> bool:
    """Accept exactly the finite JSON data a context allows, rejecting only self-references."""

    if type(value) in {type(None), bool, int, str}:
        return True
    if type(value) is float:
        return isfinite(value)
    if type(value) not in {list, dict}:
        return False
    seen: set[int] = set() if active is None else active
    identity = id(value)
    if identity in seen:
        return False
    seen.add(identity)
    try:
        if type(value) is list:
            return all(_is_finite_json(item, active=seen) for item in cast("list[object]", value))
        mapping = cast("dict[object, object]", value)
        return all(
            type(key) is str and _is_finite_json(item, active=seen) for key, item in mapping.items()
        )
    finally:
        seen.remove(identity)


def _validate_provenance(payload: Mapping[str, object]) -> None:
    # Provenance carries only the declared constraints: finite JSON data, a provider
    # name, and zero raw rows. Its size is already bounded by max_serialized_bytes, so
    # no separate entry or value-length cap is invented here.
    provenance = _string_keyed(payload.get("provenance"))
    if provenance is None:
        raise _malformed_context("data context provenance is malformed")
    try:
        finite = _is_finite_json(dict(provenance))
    except RecursionError:
        # The interpreter's stack ceiling, not a declared bound: the value simply cannot
        # be represented, so it is reported as such rather than as a limit it exceeded.
        raise _malformed_context("data context could not be serialized") from None
    if not finite:
        raise _malformed_context("data context provenance is malformed")
    if _nonempty_str(provenance.get("provider")) is None:
        raise _malformed_context("data context provenance is malformed")
    if _exact_count(provenance.get("raw_rows")) != 0:
        raise _malformed_context("data context provenance must record zero raw rows")


def _validate_attributes(raw: object, limits: Mapping[str, int]) -> int:
    attributes = _exact_list(raw)
    if attributes is None:
        raise _malformed_context("data context attributes are malformed")
    if len(attributes) > limits["max_attributes_per_entity"]:
        raise _context_limit_exceeded("data context exceeds its per-entity attribute limit")
    names: list[str] = []
    for entry in attributes:
        attribute = _string_keyed(entry)
        if attribute is None or set(attribute) != set(_ATTRIBUTE_KEYS):
            raise _malformed_context("data context attributes are malformed")
        name = _nonempty_str(attribute["name"])
        if name is None:
            raise _malformed_context("data context attributes are malformed")
        if len(name) > MAX_NAME_OR_TYPE_CODEPOINTS:
            raise _context_limit_exceeded("data context exceeds its name limit")
        declared = attribute["type"]
        if declared is not None:
            text = _nonempty_str(declared)
            if text is None:
                raise _malformed_context("data context attribute types must be a string or null")
            if len(text) > MAX_NAME_OR_TYPE_CODEPOINTS:
                raise _context_limit_exceeded("data context exceeds its type limit")
        names.append(name)
    if names != sorted(names) or len(set(names)) != len(names):
        raise _malformed_context("data context attributes must be unique and name-sorted")
    return len(names)


def _validate_schema(payload: Mapping[str, object], limits: Mapping[str, int]) -> tuple[str, ...]:
    schema = _string_keyed(payload.get("schema"))
    if schema is None or set(schema) != {"entities"}:
        raise _malformed_context("data context schema is malformed")
    entities = _exact_list(schema["entities"])
    if entities is None:
        raise _malformed_context("data context schema is malformed")
    if len(entities) > limits["max_entities"]:
        raise _context_limit_exceeded("data context exceeds its entity limit")

    names: list[str] = []
    total_attributes = 0
    for entry in entities:
        entity = _string_keyed(entry)
        if entity is None:
            raise _malformed_context("data context schema is malformed")
        keys = set(entity)
        if not keys.issubset(_ENTITY_KEYS) or not _ENTITY_REQUIRED_KEYS.issubset(keys):
            raise _malformed_context("data context schema is malformed")
        name = _nonempty_str(entity["name"])
        if name is None:
            raise _malformed_context("data context schema is malformed")
        if len(name) > MAX_NAME_OR_TYPE_CODEPOINTS:
            raise _context_limit_exceeded("data context exceeds its name limit")
        if "description" in entity:
            description = entity["description"]
            if type(description) is not str:
                raise _malformed_context("data context descriptions must be strings")
            if len(description) > limits["max_description_chars"]:
                raise _context_limit_exceeded("data context exceeds its description limit")
        total_attributes += _validate_attributes(entity["attributes"], limits)
        if total_attributes > limits["max_total_attributes"]:
            raise _context_limit_exceeded("data context exceeds its total attribute limit")
        names.append(name)
    if names != sorted(names) or len(set(names)) != len(names):
        raise _malformed_context("data context entities must be unique and name-sorted")
    return tuple(names)


def _validate_protocol(payload: Mapping[str, object], limits: Mapping[str, int]) -> None:
    protocol = payload["protocol"]
    if protocol is None:
        return
    text = _nonempty_str(protocol)
    if text is None:
        raise _malformed_context("data context protocol must be a string or null")
    if len(text) > MAX_NAME_OR_TYPE_CODEPOINTS:
        raise _context_limit_exceeded("data context exceeds its protocol limit")


def validate_scope_fields(scope: object) -> DataScope:
    """Check a `DataScope`'s current field values, not just its class.

    A frozen dataclass still yields to `object.__setattr__`, so an exact `DataScope`
    can carry a `str` subclass or a hostile tuple by the time anyone reads it. Every
    check below establishes an exact type before touching the value, so a replaced
    field cannot run `__eq__`, `__bool__`, or `strip()` first.
    """

    if type(scope) is not DataScope:
        raise _malformed_context("data context scope is malformed")
    for value in (scope.source, scope.database, scope.collection):
        if type(value) is not str or not value.strip():
            raise _malformed_context("data context scope is malformed")
        if len(value) > MAX_NAME_OR_TYPE_CODEPOINTS:
            # The scope is serialized into the snapshot, so its identifiers carry the
            # same wire bound the entity and attribute names carry.
            raise _context_limit_exceeded("data context exceeds its name limit")
    if type(scope.entities) is not tuple:
        raise _malformed_context("data context scope is malformed")
    for entity in cast("tuple[object, ...]", scope.entities):
        if type(entity) is not str or not entity.strip():
            raise _malformed_context("data context scope is malformed")
        if len(entity) > MAX_NAME_OR_TYPE_CODEPOINTS:
            raise _context_limit_exceeded("data context exceeds its name limit")
    return scope


def _validate_resolved_entities(value: object) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise _malformed_context("data context resolved entities are malformed")
    for entity in cast("tuple[object, ...]", value):
        if _nonempty_str(entity) is None:
            raise _malformed_context("data context resolved entities are malformed")
    return cast("tuple[str, ...]", value)


@dataclass(frozen=True)
class DataContextSnapshot:
    """A validated, immutable entity-and-attribute projection for one `DataScope`.

    Construction deep-copies and recursively freezes `payload`, then checks the whole
    document against the bounds the payload itself declares, so a snapshot that exists
    is a snapshot that already satisfies every limit it reports.

    A caller can still undo that with `object.__setattr__` on an instance it owns, which
    is why the planner never keeps a provider's snapshot: `detached_snapshots()` rebuilds
    the whole document into package-owned instances first.
    """

    scope: DataScope
    resolved_entities: tuple[str, ...]
    payload: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        scope = validate_scope_fields(self.scope)
        resolved = _validate_resolved_entities(self.resolved_entities)
        payload = _string_keyed(self.payload)
        if payload is None or set(payload) != set(_PAYLOAD_KEYS):
            raise _malformed_context("data context payload is malformed")

        limits = _validate_limits(payload)
        _validate_protocol(payload, limits)
        _validate_provenance(payload)
        if resolved != _validate_schema(payload, limits):
            raise _malformed_context("data context resolved entities must match its schema")
        if scope.entities and resolved != scope.entities:
            raise _malformed_context("data context must resolve the requested entity projection")

        try:
            object.__setattr__(self, "payload", _freeze(payload))
            # Class dispatch: `scope` is whatever the caller passed, so an instance
            # `to_dict` on it would otherwise decide the bytes this bound is measured on.
            serialized = _canonical_bytes(DataContextSnapshot.to_dict(self))
        except PlanningError:
            raise
        except RecursionError:
            raise _malformed_context("data context could not be serialized") from None
        if len(serialized) > limits["max_serialized_bytes"]:
            raise _context_limit_exceeded("data context exceeds its serialized byte limit")

    def to_dict(self) -> dict[str, JsonValue]:
        """Serialize to `data-context@1` with fresh mutable containers on every call."""

        document: dict[str, JsonValue] = {
            "format": DATA_CONTEXT_FORMAT,
            # Class dispatch: an instance attribute named `to_dict` on the scope would
            # otherwise decide what this snapshot claims to contain.
            "scope": DataScope.to_dict(self.scope),
            "resolved_entities": list(self.resolved_entities),
        }
        for key in ("protocol", "schema", "provenance", "limits"):
            document[key] = cast(JsonValue, _thaw(self.payload[key]))
        return document


def detached_snapshots(collected: object) -> tuple[DataContextSnapshot, DataContextSnapshot]:
    """Validate a provider's snapshot and rebuild it as two package-owned copies.

    A single instance reaching both the generator and `PlanningResult` would make the
    generator's argument and the planner's retained record the same mutable object, so
    every later caller callback would be a chance to corrupt the result. The two copies
    carry equal canonical content instead:

    - the returned pair are distinct objects that serialize identically;
    - the first is handed to the generator, which may do what it likes with it;
    - the second never reaches caller code before `PlanningResult` exists.

    Nothing the caller supplied survives into either copy. The document is thawed into
    package-owned containers and every field is re-derived through `DataScope` and
    `DataContextSnapshot` construction, which revalidates from scratch. A shadowed
    `to_dict`, a replacement proxy over a mapping the supplier still holds, or a field
    swapped in by `object.__setattr__` therefore has nothing left to act on, and the
    planner needs no fingerprint to detect a change it can no longer suffer.
    """

    if type(collected) is not DataContextSnapshot:
        raise _malformed_context("data context snapshot is malformed")
    scope = validate_scope_fields(collected.scope)
    resolved = tuple(_validate_resolved_entities(collected.resolved_entities))
    try:
        document = _string_keyed(_thaw(collected.payload))
    except RecursionError:
        raise _malformed_context("data context could not be serialized") from None
    except Exception:
        raise _malformed_context("data context payload is malformed") from None
    if document is None:
        raise _malformed_context("data context payload is malformed")
    # Still `object`-valued here; construction is what proves every leaf is JSON data.
    payload = cast("Mapping[str, JsonValue]", document)

    def build() -> DataContextSnapshot:
        # A fresh DataScope per copy as well: the two snapshots would otherwise share
        # one mutable scope object, and mutating the generator's would repoint both.
        return DataContextSnapshot(
            scope=DataScope(scope.source, scope.database, scope.collection, scope.entities),
            resolved_entities=resolved,
            payload=payload,
        )

    return build(), build()


class DataContextProvider(Protocol):
    def collect(self, scope: DataScope) -> DataContextSnapshot: ...


def _read(call: Callable[[], Any]) -> Any:
    # No exception class earns a pass-through here. The wrapped registry is a
    # caller-supplied object, so a PlanningError it raises is foreign text with a
    # forged classification, not one of this module's fixed records. Every bound and
    # shape check runs outside this wrapper, so nothing of ours is caught by it.
    try:
        return call()
    except Exception:
        raise _context_read_failed() from None


def _adapter_limits(raw: object) -> dict[str, int]:
    """Copy an adapter's limits into package-owned state, or fail generically.

    `_limits` is an ordinary instance attribute, so a caller can replace it after
    construction. Every value below is read out of an exact `dict` and pinned to an exact
    `int` before anything compares against it, which is what stops a replacement from
    running `__eq__`, `__gt__`, or `__hash__` inside the trusted collection path.
    """

    if type(raw) is not dict:
        raise _context_read_failed()
    checked: dict[str, int] = {}
    # .items() on an exact dict runs no caller code, and each key is type-checked before
    # it is used, so a hostile key never reaches a hash or a comparison.
    for key, value in cast("dict[object, object]", raw).items():
        if type(key) is not str:
            raise _context_read_failed()
        count = _exact_count(value)
        if count is None:
            raise _context_read_failed()
        checked[key] = count
    if set(checked) != set(_LIMIT_KEYS):
        raise _context_read_failed()
    if checked["max_raw_rows"] != 0:
        raise _context_read_failed()
    if any(checked[key] < 1 for key in _LIMIT_KEYS if key != "max_raw_rows"):
        raise _context_read_failed()
    if checked["max_name_or_type_codepoints"] != MAX_NAME_OR_TYPE_CODEPOINTS:
        raise _context_read_failed()
    return checked


def _read_protocol(registry: Any, scope: DataScope) -> str | None:
    properties = _string_keyed(_read(lambda: registry.get_source_properties(scope.source)))
    if properties is None:
        return None
    connection = _string_keyed(properties.get("connection"))
    if connection is None:
        return None
    protocol = _nonempty_str(connection.get("protocol"))
    if protocol is None:
        return None
    if len(protocol) > MAX_NAME_OR_TYPE_CODEPOINTS:
        raise _context_limit_exceeded("data context exceeds its protocol limit")
    return protocol


def _read_entity_records(registry: Any, scope: DataScope) -> dict[str, Mapping[str, object]]:
    raw = _exact_list(
        _read(
            lambda: registry.list_collection_entities(
                scope.source, scope.database, scope.collection
            )
        )
    )
    if raw is None:
        raise _malformed_context("registry returned a malformed entity listing")
    records: dict[str, Mapping[str, object]] = {}
    for entry in raw:
        record = _string_keyed(entry)
        if record is None:
            raise _malformed_context("registry returned a malformed entity record")
        name = _nonempty_str(record.get("name"))
        if name is None:
            raise _malformed_context("registry returned a malformed entity record")
        if name in records:
            raise _malformed_context("registry returned duplicate entity records")
        records[name] = record
    return records


def _select_entities(
    scope: DataScope,
    records: Mapping[str, Mapping[str, object]],
    limits: Mapping[str, int],
) -> tuple[str, ...]:
    if scope.entities:
        if len(scope.entities) > limits["max_entities"]:
            raise _context_limit_exceeded("data context exceeds its entity limit")
        if any(name not in records for name in scope.entities):
            raise _context_unavailable("requested entity is not registered in the collection")
        # Already canonicalized by DataScope, so this is the exact requested tuple.
        return scope.entities
    # The whole-collection request is complete or it fails: there is no separate
    # entity-listing call a caller could page through, so a truncated projection would
    # look exactly like a small collection.
    if len(records) > limits["max_entities"]:
        raise _context_limit_exceeded("data context exceeds its entity limit")
    return tuple(sorted(records))


def _entity_description(record: Mapping[str, object], limits: Mapping[str, int]) -> str | None:
    description = record.get("description")
    # Blank is omitted for the same reason empty is: it carries no information.
    if type(description) is not str or not description.strip():
        return None
    if len(description) > limits["max_description_chars"]:
        raise _context_limit_exceeded("data context exceeds its description limit")
    return description


def _declared_type(record: Mapping[str, object]) -> str | None:
    properties = _string_keyed(record.get("properties"))
    if properties is None:
        return None
    info = _string_keyed(properties.get("info"))
    if info is None:
        return None
    declared = _nonempty_str(info.get("type"))
    if declared is None:
        return None
    if len(declared) > MAX_NAME_OR_TYPE_CODEPOINTS:
        raise _context_limit_exceeded("data context exceeds its type limit")
    return declared


def _read_attributes(
    registry: Any,
    scope: DataScope,
    entity: str,
    limits: Mapping[str, int],
) -> list[JsonValue]:
    raw = _exact_list(
        _read(
            lambda: registry.list_entity_attributes(
                scope.source, scope.database, scope.collection, entity
            )
        )
    )
    if raw is None:
        raise _malformed_context("registry returned a malformed attribute listing")
    if len(raw) > limits["max_attributes_per_entity"]:
        raise _context_limit_exceeded("data context exceeds its per-entity attribute limit")
    collected: dict[str, str | None] = {}
    for entry in raw:
        record = _string_keyed(entry)
        if record is None:
            raise _malformed_context("registry returned a malformed attribute record")
        name = _nonempty_str(record.get("name"))
        if name is None:
            raise _malformed_context("registry returned a malformed attribute record")
        if len(name) > MAX_NAME_OR_TYPE_CODEPOINTS:
            raise _context_limit_exceeded("data context exceeds its name limit")
        if name in collected:
            raise _malformed_context("registry returned duplicate attribute records")
        collected[name] = _declared_type(record)
    return [{"name": name, "type": collected[name]} for name in sorted(collected)]


class RegistryDataContextProvider:
    """Collect a bounded snapshot from three read-only registry list operations.

    Entity and attribute records are read directly rather than through
    `build_schema_for_nl()`: that helper substitutes `TEXT` for an absent declared type
    and stringifies a non-mapping `properties.info`, so it cannot express "the registry
    does not know this type". Here an unknown type is `null`. Relations are not read at
    all — the pinned producer may leave their endpoints empty, so a relation projection
    would not mean what a planner would take it to mean.

    `collect()` keeps the collection logic and calls module-level functions for the rest.
    It deliberately dispatches through no instance attribute: the two it reads are pinned
    to package-owned values on entry, by `_adapter_limits()` and by confining every
    registry call to `_read()`. That is what lets the planner surface this class's
    structured errors as they are — a caller has no seam to raise one through.
    """

    def __init__(
        self,
        registry: RegistrySeam,
        *,
        max_entities: int = 32,
        max_attributes_per_entity: int = 64,
        max_total_attributes: int = 512,
        max_description_chars: int = 512,
        max_serialized_bytes: int = 131_072,
    ) -> None:
        bounds = {
            "max_entities": max_entities,
            "max_attributes_per_entity": max_attributes_per_entity,
            "max_total_attributes": max_total_attributes,
            "max_description_chars": max_description_chars,
            "max_serialized_bytes": max_serialized_bytes,
        }
        for value in bounds.values():
            count = _exact_count(value)
            if count is None or count < 1:
                raise invalid_request("data context limits must be positive integers")
        self._registry = registry
        self._limits: dict[str, int] = {
            **bounds,
            "max_name_or_type_codepoints": MAX_NAME_OR_TYPE_CODEPOINTS,
            "max_raw_rows": 0,
        }

    def collect(self, scope: DataScope) -> DataContextSnapshot:
        # Field-level, not just class-level: a caller can hand back an exact DataScope
        # whose source was replaced with a str subclass after construction, and this
        # adapter is about to send those identifiers to the registry and serialize them.
        scope = validate_scope_fields(scope)
        # The only two instance reads in the whole path, both pinned to package-owned
        # values here. Nothing below dispatches through an attribute a caller can set.
        registry: Any = self._registry
        limits = _adapter_limits(self._limits)

        protocol = _read_protocol(registry, scope)
        records = _read_entity_records(registry, scope)
        selected = _select_entities(scope, records, limits)

        entities: list[JsonValue] = []
        total_attributes = 0
        for name in selected:
            attributes = _read_attributes(registry, scope, name, limits)
            total_attributes += len(attributes)
            if total_attributes > limits["max_total_attributes"]:
                raise _context_limit_exceeded("data context exceeds its total attribute limit")
            entity: dict[str, JsonValue] = {"name": name, "attributes": attributes}
            description = _entity_description(records[name], limits)
            if description is not None:
                entity["description"] = description
            entities.append(entity)

        return DataContextSnapshot(
            scope=scope,
            resolved_entities=selected,
            payload={
                "protocol": protocol,
                "schema": {"entities": entities},
                "provenance": {
                    "provider": "blue-data-registry",
                    "source_properties_method": "get_source_properties",
                    "entity_method": "list_collection_entities",
                    "attribute_method": "list_entity_attributes",
                    "raw_rows": 0,
                },
                "limits": dict(limits),
            },
        )
