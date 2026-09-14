from __future__ import annotations

import ast
import hashlib
import inspect
import json
import re
import textwrap
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from types import FunctionType, MethodType
from typing import cast

from blue_data_ops.operators import OperatorRegistry
from blue_data_ops.operators.types import AttributeSpec

SETTINGS_COLUMNS = (
    "Name",
    "Input",
    "Declared",
    "Effective default",
    "Validation",
    "Kind",
)
SETTING_KINDS = frozenset({"scalar", "presence", "structured", "seam", "namespace"})
ADDED_SKILL_PACKAGE_IDS = (
    "avg@3.0.0",
    "classify@3.0.0",
    "cluster@3.0.0",
    "insert@3.0.0",
    "insert_table@3.0.0",
    "intersect@3.0.0",
    "join@3.0.0",
    "max@3.0.0",
    "min@3.0.0",
    "nl2bn@3.0.0",
    "nl2llm@3.0.0",
    "nl2sql@3.0.0",
    "project@3.0.0",
    "semantic_extract@3.0.0",
    "semantic_filter@3.0.0",
    "semantic_join@3.0.0",
    "semantic_project@3.0.0",
    "semantic_transform@3.0.0",
    "vector_embed@3.0.0",
    "vector_search@3.0.0",
    "vector_similarity@3.0.0",
)
BASE_SETTING = "execution.timeout_seconds"
_NAMESPACE_INPUT = re.compile(
    r"^properties:(?:<[A-Za-z_][A-Za-z0-9_]*>|[A-Za-z_][A-Za-z0-9_]*)\.\*$"
)
_NAMESPACE_NAME = re.compile(r"^(?:<[A-Za-z_][A-Za-z0-9_]*>|[A-Za-z_][A-Za-z0-9_]*)\.\*$")
_TABLE_DIVIDER = re.compile(r"^:?-{3,}:?$")
_VALIDATION_FUNCTIONS = frozenset({"validate", "_validate_input"})
_REVIEWED_LLM_KEYS = frozenset(
    {
        "cache",
        "cache_dir",
        "max_parallel",
        "max_tokens",
        "model",
        "rate_limit",
        "stream",
        "temperature",
    }
)


@dataclass(frozen=True)
class SettingRow:
    name: str
    input: str
    declared: str
    effective_default: str
    validation: str
    kind: str


@dataclass(frozen=True)
class SettingExpectation:
    name: str
    input: str
    declared: str
    effective_default: str
    validation: str
    kind: str


@dataclass(frozen=True)
class IndirectEvidence:
    helper: str
    call_line: int
    source_sha256: str


@dataclass(frozen=True)
class EffectiveReadCensus:
    expected: tuple[SettingExpectation, ...]
    post_merge_reads: tuple[str, ...]
    discarded_post_merge_writes: tuple[str, ...]
    excluded_runtime_metadata: tuple[str, ...]
    indirect_evidence: tuple[IndirectEvidence, ...]


@dataclass(frozen=True)
class SourceProvenance:
    kind: str
    module: str
    symbol: str
    source_sha256: str


@dataclass(frozen=True)
class OperatorSource:
    text: str
    provenance: tuple[SourceProvenance, ...]


def _normalize_cell(cell: str, *, machine: bool) -> str:
    value = cell.strip()
    if value.startswith("`") and value.endswith("`") and value.count("`") == 2:
        value = value[1:-1]
    if machine and (value.startswith("`") or value.endswith("`") or "`" in value):
        raise AssertionError(f"invalid Settings code cell: {value!r}")
    value = value.replace("\\|", "|")
    assert value, "Settings cells cannot be empty"
    return value


def _split_table_cells(body: str) -> tuple[str, ...]:
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for character in body:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            current.append(character)
            escaped = True
        elif character == "|":
            cells.append("".join(current))
            current = []
        else:
            current.append(character)
    assert not escaped, "Settings row ends with an escape"
    cells.append("".join(current))
    return tuple(cells)


def _cells(line: str) -> tuple[str, ...]:
    stripped = line.strip()
    assert stripped.startswith("|") and stripped.endswith("|"), (
        f"Settings table row must start and end with '|': {line!r}"
    )
    cells = tuple(
        _normalize_cell(cell, machine=index in {0, 1, 2, 5})
        for index, cell in enumerate(_split_table_cells(stripped[1:-1]))
    )
    assert len(cells) == len(SETTINGS_COLUMNS), f"Settings row has {len(cells)} columns"
    return cells


def parse_settings(guide: str) -> tuple[SettingRow, ...]:
    lines = guide.splitlines()
    headings = [position for position, line in enumerate(lines) if line.strip() == "## Settings"]
    assert len(headings) == 1, f"expected one Settings section, found {len(headings)}"
    start = headings[0] + 1
    while start < len(lines) and not lines[start].strip():
        start += 1
    assert start + 1 < len(lines), "Settings table is missing"
    assert _cells(lines[start]) == SETTINGS_COLUMNS
    divider = _cells(lines[start + 1])
    assert all(_TABLE_DIVIDER.fullmatch(cell) for cell in divider), "invalid Settings divider"

    rows: list[SettingRow] = []
    position = start + 2
    while position < len(lines):
        line = lines[position]
        if line.startswith("## "):
            break
        if not line.strip():
            position += 1
            continue
        values = _cells(line)
        row = SettingRow(*values)
        assert row.input in {"attributes", "properties", "base-properties"} or (
            _NAMESPACE_INPUT.fullmatch(row.input)
        ), f"invalid Settings input: {row.input}"
        assert row.declared in {"yes", "no"}, f"invalid Declared value: {row.declared}"
        assert row.kind in SETTING_KINDS, f"invalid Settings kind: {row.kind}"
        assert row.name, "setting names are exact keys"
        if row.kind == "namespace":
            assert _NAMESPACE_NAME.fullmatch(row.name), f"invalid namespace name: {row.name}"
            assert _NAMESPACE_INPUT.fullmatch(row.input), (
                f"namespace row has non-namespace input: {row.input}"
            )
        else:
            assert not _NAMESPACE_NAME.fullmatch(row.name), (
                f"wildcard setting must use namespace kind: {row.name}"
            )
        rows.append(row)
        position += 1

    assert rows, "Settings table has no rows"
    identities = tuple((row.name, row.input) for row in rows)
    assert len(set(identities)) == len(identities), "duplicate Settings row"
    assert identities == tuple(sorted(identities, key=lambda item: (item[0].encode(), item[1]))), (
        "Settings rows are not UTF-8-byte-sorted by name and input"
    )
    return tuple(rows)


def expected_v2_skill_package_ids(registry: OperatorRegistry) -> tuple[str, ...]:
    cards = tuple(card for card in registry.list_cards() if card.version == "2.0.0")
    assert len(cards) == 32
    expected = {card.operator_id for card in cards}
    return tuple(sorted(expected, key=lambda item: item.encode("utf-8")))


def expected_skill_package_ids(registry: OperatorRegistry) -> tuple[str, ...]:
    legacy = expected_v2_skill_package_ids(registry)
    expected = (*legacy, *ADDED_SKILL_PACKAGE_IDS)
    assert len(expected) == len(set(expected)) == 53
    return tuple(sorted(expected, key=lambda item: item.encode("utf-8")))


def assert_skill_package_inventory(actual: tuple[str, ...], registry: OperatorRegistry) -> None:
    assert actual == expected_skill_package_ids(registry), "skill package inventory differs"


def _literal_key(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and type(node.value) is str:
        return node.value
    return None


def _mapping_key(node: ast.Subscript, aliases: set[str]) -> str | None:
    if isinstance(node.value, ast.Name) and node.value.id in aliases:
        return _literal_key(node.slice)
    return None


def _empty_mapping(node: ast.AST) -> bool:
    return isinstance(node, ast.Dict) and not node.keys


def _alias_preserving(node: ast.AST, aliases: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in aliases
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        return any(_alias_preserving(value, aliases) for value in node.values) and all(
            _alias_preserving(value, aliases)
            or _empty_mapping(value)
            or (isinstance(value, ast.Constant) and value.value is None)
            for value in node.values
        )
    if isinstance(node, ast.IfExp):
        branches = (node.body, node.orelse)
        return any(_alias_preserving(branch, aliases) for branch in branches) and all(
            _alias_preserving(branch, aliases) or _empty_mapping(branch) for branch in branches
        )
    if isinstance(node, ast.Dict):
        return any(
            key is None and _alias_preserving(value, aliases)
            for key, value in zip(node.keys, node.values, strict=True)
        )
    if isinstance(node, ast.Call):
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "copy"
            and _alias_preserving(node.func.value, aliases)
            and not node.args
        ):
            return True
        if isinstance(node.func, ast.Name) and node.func.id in {"dict", "deepcopy"}:
            return bool(node.args) and _alias_preserving(node.args[-1], aliases)
        if isinstance(node.func, ast.Name) and node.func.id == "cast" and len(node.args) >= 2:
            return _alias_preserving(node.args[-1], aliases)
    return False


def _aliases_from_nodes(nodes: tuple[ast.AST, ...], root: str) -> set[str]:
    aliases = {root}
    changed = True
    while changed:
        changed = False
        for node in nodes:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if value is None or not _alias_preserving(value, aliases):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in aliases:
                    aliases.add(target.id)
                    changed = True
    return aliases


def _function_body_nodes(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[ast.AST, ...]:
    found: list[ast.AST] = []
    pending: list[ast.AST] = list(reversed(function.body))
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        found.append(node)
        pending.extend(reversed(tuple(ast.iter_child_nodes(node))))
    return tuple(found)


def _mapping_get_receiver(node: ast.AST, aliases: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in aliases
    return (
        isinstance(node, ast.BoolOp)
        and isinstance(node.op, ast.Or)
        and len(node.values) == 2
        and isinstance(node.values[0], ast.Name)
        and node.values[0].id in aliases
        and _empty_mapping(node.values[1])
    )


def _read_kinds_from_nodes(nodes: tuple[ast.AST, ...], aliases: set[str]) -> dict[str, set[str]]:
    reads: dict[str, set[str]] = defaultdict(set)
    for node in nodes:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (
                node.func.attr == "get"
                and _mapping_get_receiver(node.func.value, aliases)
                and node.args
            ):
                key = _literal_key(node.args[0])
                if key is not None:
                    reads[key].add("value")
        elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
            key = _mapping_key(node, aliases)
            if key is not None:
                reads[key].add("value")
        elif isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            for index, operation in enumerate(node.ops):
                if not isinstance(operation, (ast.In, ast.NotIn)):
                    continue
                key = _literal_key(operands[index])
                mapping = operands[index + 1]
                if key is not None and isinstance(mapping, ast.Name) and mapping.id in aliases:
                    reads[key].add("presence")
    return reads


def _read_kinds(tree: ast.AST, aliases: set[str]) -> dict[str, set[str]]:
    return _read_kinds_from_nodes(tuple(ast.walk(tree)), aliases)


def _literal_default(node: ast.AST) -> str:
    try:
        return canonical_default(ast.literal_eval(node))
    except (TypeError, ValueError):
        return "source-dependent"


def _read_defaults_from_nodes(nodes: tuple[ast.AST, ...], aliases: set[str]) -> dict[str, set[str]]:
    defaults: dict[str, set[str]] = defaultdict(set)
    for node in nodes:
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if (
            node.func.attr != "get"
            or not _mapping_get_receiver(node.func.value, aliases)
            or not node.args
        ):
            continue
        key = _literal_key(node.args[0])
        if key is None:
            continue
        defaults[key].add(_literal_default(node.args[1]) if len(node.args) > 1 else "none")
    return defaults


def _literal_default_kind(node: ast.AST) -> str:
    try:
        return _default_kind(ast.literal_eval(node))
    except (TypeError, ValueError):
        return "unknown"


def _read_default_kinds_from_nodes(
    nodes: tuple[ast.AST, ...], aliases: set[str]
) -> dict[str, set[str]]:
    kinds: dict[str, set[str]] = defaultdict(set)
    for node in nodes:
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if (
            node.func.attr != "get"
            or not _mapping_get_receiver(node.func.value, aliases)
            or not node.args
        ):
            continue
        key = _literal_key(node.args[0])
        if key is None:
            continue
        kinds[key].add(_literal_default_kind(node.args[1]) if len(node.args) > 1 else "scalar")
    return kinds


def _combined_default(values: set[str]) -> str:
    if not values:
        return "none"
    return next(iter(values)) if len(values) == 1 else "path-dependent"


def _mapping_value_provenance_from_nodes(
    nodes: tuple[ast.AST, ...], mapping_aliases: set[str]
) -> dict[str, frozenset[str]]:
    provenance: dict[str, set[str]] = defaultdict(set)

    def source_keys(node: ast.AST) -> set[str]:
        if isinstance(node, ast.Name):
            return provenance.get(node.id, set())
        if isinstance(node, ast.Subscript):
            key = _mapping_key(node, mapping_aliases)
            return {key} if key is not None else set()
        if isinstance(node, ast.Call):
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in mapping_aliases
                and node.args
            ):
                key = _literal_key(node.args[0])
                return {key} if key is not None else set()
            if isinstance(node.func, ast.Name) and node.func.id == "cast" and len(node.args) >= 2:
                return source_keys(node.args[-1])
        return set()

    changed = True
    while changed:
        changed = False
        for node in nodes:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
                continue
            keys = source_keys(node.value)
            if not keys:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and not keys.issubset(provenance[target.id]):
                    provenance[target.id].update(keys)
                    changed = True
    return {name: frozenset(keys) for name, keys in provenance.items()}


def _validated_property_keys(tree: ast.AST) -> set[str]:
    validated: set[str] = set()
    for function in (
        node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ):
        nodes = _function_body_nodes(function)
        aliases = _aliases_from_nodes(nodes, "properties")
        provenance = _mapping_value_provenance_from_nodes(nodes, aliases)
        for node in nodes:
            candidates: tuple[ast.AST, ...] = ()
            if isinstance(node, ast.Call) and node.args:
                function_name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else ""
                )
                if function_name == "isinstance" or function_name.startswith(
                    ("validate_", "_validate_", "valid_", "_valid_")
                ):
                    candidates = tuple(node.args)
            for candidate in candidates:
                if isinstance(candidate, ast.Name):
                    validated.update(provenance.get(candidate.id, ()))
    return validated


def _post_merge_writes_from_nodes(
    nodes: tuple[ast.AST, ...],
    property_aliases: set[str],
    attribute_aliases: set[str],
) -> dict[str, tuple[int, str]]:
    writes: dict[str, tuple[int, str]] = {}
    provenance = _mapping_value_provenance_from_nodes(nodes, attribute_aliases)

    def source_key(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            keys = provenance.get(node.id, ())
            return next(iter(keys)) if len(keys) == 1 else None
        if isinstance(node, ast.Subscript):
            return _mapping_key(node, attribute_aliases)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in attribute_aliases
            and node.args
        ):
            return _literal_key(node.args[0])
        return None

    for node in nodes:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Subscript):
                    key = _mapping_key(target, property_aliases)
                    attribute_key = source_key(node.value)
                    if key is not None and attribute_key is not None:
                        writes[key] = (node.lineno, attribute_key)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "update"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in property_aliases
            and node.args
            and isinstance(node.args[0], ast.Dict)
        ):
            update = node.args[0]
            for raw_key, value in zip(update.keys, update.values, strict=True):
                key = _literal_key(raw_key) if raw_key is not None else None
                attribute_key = source_key(value)
                if key is not None and attribute_key is not None:
                    writes[key] = (node.lineno, attribute_key)
    return writes


def _merge_reads(target: dict[str, set[str]], source: dict[str, set[str]]) -> None:
    for name, kinds in source.items():
        target[name].update(kinds)


def _default_kind(value: object) -> str:
    return "structured" if isinstance(value, (dict, list, tuple, set)) else "scalar"


def _schema_kind(spec: AttributeSpec, read_kinds: set[str]) -> str:
    if read_kinds == {"presence"}:
        return "presence"
    if "list" in spec.type.lower() or "dict" in spec.type.lower():
        return "structured"
    if spec.has_default and isinstance(spec.default, (dict, list, tuple, set)):
        return "structured"
    return "scalar"


_SETTINGS_ENTRYPOINTS = ("apply", "_execute", "validate", "_validate_input")
_MAX_ACQUIRED_CALLABLES = 64


def _callable_definition(owner: type[object], name: str) -> FunctionType:
    raw: object = owner.__dict__[name]
    assert isinstance(raw, (FunctionType, classmethod, staticmethod)), (
        f"unsupported operator callable {owner.__qualname__}.{name}: {type(raw).__name__}"
    )
    definition: object = raw if isinstance(raw, FunctionType) else getattr(owner, name)
    if isinstance(definition, MethodType):
        definition = definition.__func__
    assert isinstance(definition, FunctionType)
    unwrapped: object = inspect.unwrap(definition)
    assert isinstance(unwrapped, FunctionType)
    return unwrapped


def _callable_source(function: FunctionType) -> tuple[Path, str]:
    source_file = inspect.getsourcefile(function)
    assert source_file is not None, f"operator callable has no source: {function!r}"
    try:
        source = textwrap.dedent(inspect.getsource(function))
    except (OSError, TypeError) as exception:
        raise AssertionError(
            f"operator callable source is unavailable: {function!r}"
        ) from exception
    return Path(source_file).resolve(), source


def _operator_classes(operator: object) -> tuple[type[object], ...]:
    from blue_data_ops.operators.operator import Operator

    operator_type = type(operator)
    if not issubclass(operator_type, Operator):
        return (operator_type,)
    mro = cast(tuple[type[object], ...], operator_type.__mro__)
    boundary = mro.index(Operator)
    assert boundary > 0
    return mro[:boundary]


def _method_definition(
    classes: tuple[type[object], ...], start: int, name: str
) -> tuple[int, type[object], FunctionType] | None:
    for index in range(start, len(classes)):
        owner = classes[index]
        if name in owner.__dict__:
            return index, owner, _callable_definition(owner, name)
    return None


def _zero_arg_super_call(call: ast.Call) -> bool:
    return (
        isinstance(call.func, ast.Name)
        and call.func.id == "super"
        and not call.args
        and not call.keywords
    )


def source_for_operator(operator: object) -> OperatorSource:
    """Return the primary module plus settings-relevant effective inherited callables."""
    operator_type = type(operator)
    source_file = inspect.getsourcefile(operator_type)
    assert source_file is not None
    primary_path = Path(source_file).resolve()
    primary_text = primary_path.read_text(encoding="utf-8")
    classes = _operator_classes(operator)

    fragments: list[str] = [primary_text]
    provenance: list[SourceProvenance] = [
        SourceProvenance(
            kind="primary-module",
            module=operator_type.__module__,
            symbol=operator_type.__qualname__,
            source_sha256=hashlib.sha256(primary_text.encode("utf-8")).hexdigest(),
        )
    ]
    acquired: set[tuple[str, str]] = set()
    visiting: set[tuple[str, str]] = set()

    def acquire(function: FunctionType, owner_index: int | None, kind: str) -> None:
        module = cast(str, getattr(function, "__module__"))
        symbol = cast(str, getattr(function, "__qualname__"))
        key = (module, symbol)
        if key in acquired or key in visiting:
            return
        assert len(acquired) + len(visiting) < _MAX_ACQUIRED_CALLABLES, (
            "operator source acquisition exceeded its bound"
        )
        visiting.add(key)
        function_path, function_source = _callable_source(function)
        provenance.append(
            SourceProvenance(
                kind=kind,
                module=module,
                symbol=symbol,
                source_sha256=hashlib.sha256(function_source.encode("utf-8")).hexdigest(),
            )
        )
        if function_path != primary_path:
            fragments.append(function_source)

        tree = ast.parse(function_source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if (
                isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and node.args
                and (
                    isinstance(node.args[0], ast.Name)
                    and node.args[0].id == "self"
                    or isinstance(node.args[0], ast.Call)
                    and _zero_arg_super_call(node.args[0])
                )
            ):
                raise AssertionError(f"unsupported dynamic operator dispatch in {module}.{symbol}")

            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Call)
                and _zero_arg_super_call(node.func.value)
            ):
                assert owner_index is not None, (
                    f"super() outside an operator method: {module}.{symbol}"
                )
                delegated = _method_definition(classes, owner_index + 1, node.func.attr)
                if delegated is not None:
                    next_index, _, next_function = delegated
                    acquire(next_function, next_index, "delegated-method")
                continue

            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"
            ):
                resolved = _method_definition(classes, 0, node.func.attr)
                if resolved is not None:
                    next_index, _, next_function = resolved
                    acquire(next_function, next_index, "reachable-method")
                continue

            if isinstance(node.func, ast.Name):
                target = cast(dict[str, object], getattr(function, "__globals__", {})).get(
                    node.func.id
                )
                if target is None or not inspect.isfunction(target):
                    continue
                target = inspect.unwrap(target)
                target_file = inspect.getsourcefile(target)
                if target_file is not None and Path(target_file).resolve() == function_path:
                    acquire(target, None, "reachable-helper")

        visiting.remove(key)
        acquired.add(key)

    for method_name in _SETTINGS_ENTRYPOINTS:
        resolved = _method_definition(classes, 0, method_name)
        if resolved is None:
            continue
        owner_index, _, function = resolved
        acquire(function, owner_index, "effective-method")

    return OperatorSource(
        text="\n\n".join(fragment.rstrip() for fragment in fragments) + "\n",
        provenance=tuple(provenance),
    )


def runtime_metadata_reads(source: str | None = None) -> tuple[str, ...]:
    from blue_data_ops.operators.operator import Operator

    tree = ast.parse(inspect.getsource(Operator) if source is None else source)
    found: set[str] = set()
    for node in ast.walk(tree):
        key: str | None = None
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute):
            if (
                isinstance(node.value.value, ast.Name)
                and node.value.value.id == "self"
                and node.value.attr == "properties"
            ):
                key = _literal_key(node.slice)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Attribute)
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "self"
            and node.func.value.attr == "properties"
            and node.args
        ):
            key = _literal_key(node.args[0])
        if key is not None:
            found.add(key)
    assert found, "self.properties runtime-metadata census is empty"
    return tuple(sorted(found, key=lambda item: item.encode("utf-8")))


def _default_helper_sources() -> dict[str, str]:
    from blue_data_ops.data.provider import resolve_registry
    from blue_data_ops.llm import client, templating
    from blue_data_ops.llm.provider import resolve_llm_client

    return {
        "resolve_registry": inspect.getsource(resolve_registry),
        "resolve_llm_client": inspect.getsource(resolve_llm_client)
        + "\n"
        + inspect.getsource(templating)
        + "\n"
        + inspect.getsource(client),
    }


def _helper_evidence(
    helper: str, call_line: int, source: str
) -> tuple[tuple[SettingExpectation, ...], IndirectEvidence]:
    tree = ast.parse(source)
    reads = _read_kinds(tree, {"properties"})
    if helper == "resolve_registry":
        required = {"data_registry", "data_registry.name", "platform.name"}
        assert required.issubset(reads), "stale resolve_registry evidence"
        expected = tuple(
            SettingExpectation(name, "properties", "no", "none", "helper:resolve_registry", "seam")
            for name in sorted(required, key=lambda item: item.encode("utf-8"))
        )
    elif helper == "resolve_llm_client":
        assert "llm_client" in reads, "stale resolve_llm_client evidence"
        assert "service_prefix" in reads, "stale service-prefix evidence"
        assert "output_template" in reads, "stale output-template evidence"
        assert reads.get("output_strip") == {"presence"}, "stale output-strip evidence"
        accepted_llm_keys = tuple(
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            and any(
                isinstance(target, ast.Name) and target.id == "_ACCEPTED_LLM_KEYS"
                for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
            )
        )
        assert len(accepted_llm_keys) == 1, "stale llm.* key-set evidence"
        accepted_value = accepted_llm_keys[0].value
        assert accepted_value is not None
        try:
            accepted = ast.literal_eval(accepted_value)
        except (TypeError, ValueError) as exception:
            raise AssertionError("stale llm.* key-set evidence") from exception
        assert accepted == _REVIEWED_LLM_KEYS, "stale llm.* key-set evidence"
        expected = (
            SettingExpectation(
                "<service_prefix>.*",
                "properties:<service_prefix>.*",
                "no",
                "none",
                "helper:resolve_llm_client",
                "namespace",
            ),
            SettingExpectation(
                "llm.*",
                "properties:llm.*",
                "no",
                "none",
                "helper:resolve_llm_client",
                "namespace",
            ),
            SettingExpectation(
                "llm_client",
                "properties",
                "no",
                "none",
                "helper:resolve_llm_client",
                "seam",
            ),
            SettingExpectation(
                "output_template",
                "properties",
                "no",
                "none",
                "helper:resolve_llm_client",
                "scalar",
            ),
            SettingExpectation(
                "output_strip",
                "properties",
                "no",
                "none",
                "helper:resolve_llm_client",
                "presence",
            ),
        )
    else:
        raise AssertionError(f"unreviewed indirect helper: {helper}")
    evidence = IndirectEvidence(
        helper=helper,
        call_line=call_line,
        source_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
    )
    return expected, evidence


def effective_read_census(
    operator: object,
    *,
    source: str | None = None,
    helper_sources: dict[str, str] | None = None,
) -> EffectiveReadCensus:
    text = source if source is not None else source_for_operator(operator).text
    tree = ast.parse(text)
    functions = tuple(
        node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    validation_scoped = {
        id(inner)
        for function in functions
        if function.name in _VALIDATION_FUNCTIONS
        for inner in ast.walk(function)
        if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    attribute_reads: dict[str, set[str]] = defaultdict(set)
    property_reads: dict[str, set[str]] = defaultdict(set)
    attribute_defaults: dict[str, set[str]] = defaultdict(set)
    attribute_default_kinds: dict[str, set[str]] = defaultdict(set)
    property_defaults: dict[str, set[str]] = defaultdict(set)
    post_writes: dict[str, tuple[int, str]] = {}
    for function in functions:
        nodes = _function_body_nodes(function)
        attribute_aliases = _aliases_from_nodes(nodes, "attributes")
        property_aliases = _aliases_from_nodes(nodes, "properties")
        _merge_reads(attribute_reads, _read_kinds_from_nodes(nodes, attribute_aliases))
        _merge_reads(property_reads, _read_kinds_from_nodes(nodes, property_aliases))
        if id(function) not in validation_scoped:
            _merge_reads(
                attribute_defaults,
                _read_defaults_from_nodes(nodes, attribute_aliases),
            )
            _merge_reads(
                attribute_default_kinds,
                _read_default_kinds_from_nodes(nodes, attribute_aliases),
            )
            _merge_reads(
                property_defaults,
                _read_defaults_from_nodes(nodes, property_aliases),
            )
        for name, write in _post_merge_writes_from_nodes(
            nodes, property_aliases, attribute_aliases
        ).items():
            previous = post_writes.get(name)
            assert previous is None or previous[1] == write[1], (
                f"ambiguous post-merge source for {name}: {previous[1]} vs {write[1]}"
            )
            if previous is None or write[0] < previous[0]:
                post_writes[name] = write
    helper_text = _default_helper_sources() if helper_sources is None else helper_sources
    helper_calls = tuple(
        (node.func.id, node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"resolve_registry", "resolve_llm_client"}
    )
    helper_read_kinds: dict[str, set[str]] = defaultdict(set)
    for helper, _ in helper_calls:
        assert helper in helper_text, f"missing reviewed evidence for {helper}"
        for name, kinds in _read_kinds(ast.parse(helper_text[helper]), {"properties"}).items():
            helper_read_kinds[name].update(kinds)

    schema = cast(dict[str, AttributeSpec], getattr(operator, "attributes"))
    validated_properties = _validated_property_keys(tree)
    expected: set[SettingExpectation] = set()
    for name, spec in schema.items():
        default = _combined_default(attribute_defaults.get(name, set()))
        if default == "none" and spec.has_default:
            default = canonical_default(spec.default)
        expected.add(
            SettingExpectation(
                name,
                "attributes",
                "yes",
                default,
                f"attribute-spec:{spec.type}",
                _schema_kind(spec, attribute_reads.get(name, set())),
            )
        )
    for name, kinds in attribute_reads.items():
        if name not in schema:
            kind = (
                "presence"
                if kinds == {"presence"}
                else "structured"
                if attribute_default_kinds.get(name, set()) == {"structured"}
                else "scalar"
            )
            expected.add(
                SettingExpectation(
                    name,
                    "attributes",
                    "no",
                    _combined_default(attribute_defaults.get(name, set())),
                    "none",
                    kind,
                )
            )

    raw_defaults: object = getattr(operator, "DEFAULT_PROPERTIES", {})
    defaults: dict[str, object] = (
        cast(dict[str, object], raw_defaults) if isinstance(raw_defaults, dict) else {}
    )
    direct_property_names = set(property_reads)
    property_names = set(defaults) | direct_property_names | set(post_writes)
    discarded_writes = set(post_writes) - direct_property_names
    for name in property_names:
        kinds = property_reads.get(name, set()) | helper_read_kinds.get(name, set())
        if kinds == {"presence"}:
            kind = "presence"
        elif name in defaults:
            kind = _default_kind(defaults[name])
        else:
            kind = "scalar"
        if name in discarded_writes:
            effective_default = "discarded"
            validation = "write-and-discard"
        elif name in post_writes:
            attribute_name = post_writes[name][1]
            attribute_spec = schema.get(attribute_name)
            effective_default = (
                canonical_default(attribute_spec.default)
                if attribute_spec is not None and attribute_spec.has_default
                else _combined_default(attribute_defaults.get(attribute_name, set()))
            )
            validation = (
                f"attribute-overwrites-property:{attribute_spec.type}"
                if attribute_spec is not None
                else "attribute-overwrites-property"
            )
        else:
            effective_default = (
                canonical_default(defaults[name])
                if name in defaults
                else _combined_default(property_defaults.get(name, set()))
            )
            validation = "runtime-check" if name in validated_properties else "none"
        expected.add(
            SettingExpectation(
                name,
                "properties",
                "no",
                effective_default,
                validation,
                kind,
            )
        )

    indirect: list[IndirectEvidence] = []
    for helper, call_line in helper_calls:
        additions, evidence = _helper_evidence(helper, call_line, helper_text[helper])
        for addition in additions:
            previous = next(
                (
                    row
                    for row in expected
                    if (row.name, row.input) == (addition.name, addition.input)
                ),
                None,
            )
            if previous is not None:
                addition = SettingExpectation(
                    addition.name,
                    addition.input,
                    addition.declared,
                    previous.effective_default,
                    addition.validation,
                    addition.kind,
                )
            expected = {
                row for row in expected if (row.name, row.input) != (addition.name, addition.input)
            }
            expected.add(addition)
        helper_reads = _read_kinds(ast.parse(helper_text[helper]), {"properties"})
        for name in helper_reads:
            if helper == "resolve_llm_client" and name.startswith("llm."):
                assert any(
                    row.name == "llm.*" and row.input == "properties:llm.*" for row in expected
                ), "uncovered llm.* helper read"
                continue
            assert any(row.name == name and row.input == "properties" for row in expected), (
                f"uncovered {helper} helper read: {name}"
            )
        indirect.append(evidence)

    expected.add(
        SettingExpectation(
            BASE_SETTING,
            "base-properties",
            "no",
            "none",
            "finite-positive-number",
            "scalar",
        )
    )
    ordered = tuple(
        sorted(expected, key=lambda row: (row.name.encode("utf-8"), row.input, row.kind))
    )
    return EffectiveReadCensus(
        expected=ordered,
        post_merge_reads=tuple(
            sorted(
                set(post_writes) & direct_property_names,
                key=lambda item: item.encode("utf-8"),
            )
        ),
        discarded_post_merge_writes=tuple(
            sorted(discarded_writes, key=lambda item: item.encode("utf-8"))
        ),
        excluded_runtime_metadata=runtime_metadata_reads(),
        indirect_evidence=tuple(indirect),
    )


def assert_guide_matches_operator(
    guide: str,
    operator: object,
    *,
    source: str | None = None,
    helper_sources: dict[str, str] | None = None,
) -> EffectiveReadCensus:
    rows = parse_settings(guide)
    census = effective_read_census(operator, source=source, helper_sources=helper_sources)
    observed = {
        SettingExpectation(
            row.name,
            row.input,
            row.declared,
            row.effective_default,
            _validation_status(row.validation),
            row.kind,
        )
        for row in rows
    }
    assert len(observed) == len(rows), "Settings rows disagree outside their identity columns"
    assert observed == set(census.expected), (
        f"Settings mismatch; missing={sorted(set(census.expected) - observed, key=repr)!r}; "
        f"unexpected={sorted(observed - set(census.expected), key=repr)!r}"
    )
    return census


def _validation_status(value: str) -> str:
    status, separator, detail = value.partition(";")
    status = status.strip()
    assert status, "Validation status is empty"
    if separator:
        assert detail.startswith(" ") and detail.strip(), (
            "Validation detail must follow '; ' and cannot be empty"
        )
    return status


def render_expected_settings(operator: object) -> str:
    census = effective_read_census(operator)
    lines = [
        "| Name | Input | Declared | Effective default | Validation | Kind |",
        "|---|---|---|---|---|---|",
    ]
    lines.extend(
        f"| {_code_cell(row.name)} | {_code_cell(row.input)} | {_code_cell(row.declared)} | "
        f"{_code_cell(row.effective_default)} | {_code_cell(row.validation)} | "
        f"{_code_cell(row.kind)} |"
        for row in census.expected
    )
    return "\n".join(lines) + "\n"


def _code_cell(value: str) -> str:
    return "`" + value.replace("|", "\\|") + "`"


def canonical_default(value: object) -> str:
    if value is None:
        return "none"
    rendered = json.dumps(value, sort_keys=True, separators=(",", ":"), default=repr)
    if len(rendered) > 120 or any(character in rendered for character in ("\n", "|", "`")):
        digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        return f"source-sha256:{digest}"
    return rendered
