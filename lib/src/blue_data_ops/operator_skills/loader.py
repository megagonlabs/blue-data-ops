from __future__ import annotations

import hashlib
import json
import re
import stat
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, NoReturn, cast

from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.registry import OperatorCard, OperatorRegistry, is_builtin_card
from blue_data_ops.operators.types import AttributeSpec

_INDEX_FORMAT = "blue-data-ops/operator-skill-index@1"
_MANIFEST_FORMAT = "blue-data-ops/operator-skill@1"
_PINNED_ID = re.compile(
    r"^(?P<name>[^/@\\]+)@(?P<version>(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))$"
)
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_INDEX_KEYS = frozenset({"format", "packages"})
_MANIFEST_KEYS = frozenset({"format", "operator_id", "resources"})
_RESOURCE_KEYS = frozenset({"path", "sha256"})
_RESOURCE_FILES = {
    "guide": "Operator.md",
    "examples": "examples.md",
    "optimization": "optimization.md",
    "issues": "issues.md",
    "history": "history.md",
}

# Resource bounds apply before decoding or returning package text.
INDEX_BYTE_LIMIT = 4_096
MANIFEST_BYTE_LIMIT = 4_096
RESOURCE_BYTE_LIMIT = 16_384
JSON_DEPTH_LIMIT = 4


class OperatorSkillErrorCode(str, Enum):
    INVALID_OPERATOR_ID = "INVALID_OPERATOR_ID"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    BINDING_MISMATCH = "BINDING_MISMATCH"
    MANIFEST_INVALID = "MANIFEST_INVALID"
    RESOURCE_INVALID = "RESOURCE_INVALID"
    TRUST_REQUIRED = "TRUST_REQUIRED"
    SCHEMA_INVALID = "SCHEMA_INVALID"


_ERROR_MESSAGES = {
    OperatorSkillErrorCode.INVALID_OPERATOR_ID: "operator id must be exact and path-safe",
    OperatorSkillErrorCode.NOT_AVAILABLE: "operator skill resource is not available",
    OperatorSkillErrorCode.BINDING_MISMATCH: ("operator skill binding does not match the registry"),
    OperatorSkillErrorCode.MANIFEST_INVALID: "operator skill manifest is invalid",
    OperatorSkillErrorCode.RESOURCE_INVALID: "operator skill resource is invalid",
    OperatorSkillErrorCode.TRUST_REQUIRED: (
        "operator skill loading requires a package-owned built-in"
    ),
    OperatorSkillErrorCode.SCHEMA_INVALID: "operator attribute schema is invalid",
}


class OperatorSkillLoadError(ValueError):
    """A stable failure at the operator-skill loading boundary."""

    def __init__(self, code: OperatorSkillErrorCode) -> None:
        self.code = code
        super().__init__(_ERROR_MESSAGES[code])


@dataclass(frozen=True)
class OperatorIOSchema:
    input_shape: str
    output_shape: str
    attributes: dict[str, AttributeSpec]


@dataclass(frozen=True)
class OperatorResource:
    operator_id: str
    kind: str
    text: str
    sha256: str


@dataclass(frozen=True)
class OperatorSkillView:
    card: OperatorCard
    requested_level: int
    loaded_kinds: tuple[str, ...]
    io: OperatorIOSchema
    guide: str
    examples: str | None = None
    history: str | None = None


@dataclass(frozen=True)
class OperatorSkillDescriptor:
    card: OperatorCard
    declared_kinds: tuple[str, ...]
    declared_levels: tuple[int, ...]


class _ReadFailure(str, Enum):
    ROOT_UNAVAILABLE = "root-unavailable"
    UNSAFE_PATH = "unsafe-path"
    MISSING = "missing"
    TOO_LARGE = "too-large"


class _ResourceReadError(OSError):
    def __init__(self, reason: _ReadFailure) -> None:
        self.reason = reason
        super().__init__(reason.value)


class _FilesystemResourceReader:
    def __init__(
        self,
        root: Path,
        *,
        on_read: Callable[[str], None] | None = None,
    ) -> None:
        self.root = root.absolute()
        self._on_read = on_read

    def read(self, relative: Path, limit: int) -> bytes:
        root = self.root
        if root.is_symlink():
            raise _ResourceReadError(_ReadFailure.UNSAFE_PATH)
        if not root.is_dir():
            raise _ResourceReadError(_ReadFailure.ROOT_UNAVAILABLE)
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise _ResourceReadError(_ReadFailure.UNSAFE_PATH)

        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise _ResourceReadError(_ReadFailure.UNSAFE_PATH)

        try:
            resolved_root = root.resolve(strict=True)
            resolved = current.resolve(strict=True)
            resolved.relative_to(resolved_root)
            if not stat.S_ISREG(resolved.stat().st_mode):
                raise _ResourceReadError(_ReadFailure.MISSING)
            with resolved.open("rb") as handle:
                content = handle.read(limit + 1)
        except _ResourceReadError:
            raise
        except (OSError, ValueError):
            raise _ResourceReadError(_ReadFailure.MISSING) from None

        if len(content) > limit:
            raise _ResourceReadError(_ReadFailure.TOO_LARGE)
        if self._on_read is not None:
            self._on_read(relative.as_posix())
        return content


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _exceeds_json_depth(value: object, limit: int) -> bool:
    pending: list[tuple[object, int]] = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        if type(current) is dict:
            mapping = cast(dict[object, object], current)
            next_depth = depth + 1
            if next_depth > limit:
                return True
            pending.extend((item, next_depth) for item in mapping.values())
        elif type(current) is list:
            sequence = cast(list[object], current)
            next_depth = depth + 1
            if next_depth > limit:
                return True
            pending.extend((item, next_depth) for item in sequence)
    return False


def snapshot_attribute_specs(operator: Operator) -> dict[str, AttributeSpec]:
    """Refresh and detach the runtime attribute projection for a skill view."""

    try:
        projected = operator._refresh_attribute_projection()  # pyright: ignore[reportPrivateUsage]
        if type(projected) is not dict:
            raise TypeError("attribute projection must be a dictionary")
        if any(
            type(name) is not str or type(spec) is not AttributeSpec
            for name, spec in projected.items()
        ):
            raise TypeError("attribute projection contains an invalid entry")
        return deepcopy(projected)
    except Exception:
        raise OperatorSkillLoadError(OperatorSkillErrorCode.SCHEMA_INVALID) from None


class OperatorSkillLoader:
    """Load reviewed resources for an exact package-owned operator."""

    def __init__(
        self,
        registry: OperatorRegistry,
        *,
        _resource_root: Path | None = None,
        _on_read: Callable[[str], None] | None = None,
    ) -> None:
        self._registry = registry
        root = Path(__file__).parent if _resource_root is None else _resource_root
        self._reader = _FilesystemResourceReader(root, on_read=_on_read)

    @staticmethod
    def _raise(code: OperatorSkillErrorCode) -> NoReturn:
        raise OperatorSkillLoadError(code)

    def _read_json(self, path: Path, limit: int) -> dict[str, Any]:
        try:
            raw = self._reader.read(path, limit)
            value: object = json.loads(
                raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
            )
        except _ResourceReadError as error:
            if error.reason is _ReadFailure.ROOT_UNAVAILABLE:
                self._raise(OperatorSkillErrorCode.NOT_AVAILABLE)
            if error.reason is _ReadFailure.UNSAFE_PATH:
                self._raise(OperatorSkillErrorCode.RESOURCE_INVALID)
            self._raise(OperatorSkillErrorCode.MANIFEST_INVALID)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
            self._raise(OperatorSkillErrorCode.MANIFEST_INVALID)
        if type(value) is not dict or _exceeds_json_depth(cast(object, value), JSON_DEPTH_LIMIT):
            self._raise(OperatorSkillErrorCode.MANIFEST_INVALID)
        return cast(dict[str, Any], value)

    def _binding(self, operator_id: str) -> tuple[OperatorCard, Operator]:
        if type(operator_id) is not str:
            self._raise(OperatorSkillErrorCode.INVALID_OPERATOR_ID)
        match = _PINNED_ID.fullmatch(operator_id)
        if match is None or match.group("name") in {".", ".."}:
            self._raise(OperatorSkillErrorCode.INVALID_OPERATOR_ID)
        if type(self._registry) is not OperatorRegistry:
            self._raise(OperatorSkillErrorCode.TRUST_REQUIRED)
        try:
            card = self._registry.get_card(operator_id)
            operator = self._registry.resolve(operator_id)
        except Exception:
            self._raise(OperatorSkillErrorCode.BINDING_MISMATCH)
        if card is None:
            self._raise(OperatorSkillErrorCode.BINDING_MISMATCH)
        if not is_builtin_card(self._registry, card):
            self._raise(OperatorSkillErrorCode.TRUST_REQUIRED)
        if type(card) is not OperatorCard:
            self._raise(OperatorSkillErrorCode.BINDING_MISMATCH)
        name = match.group("name")
        version = match.group("version")
        try:
            card_operator_id = card.operator_id
            card_name = card.name
            card_version = card.version
            bound_operator_id = operator.operator_id
            bound_name = operator.name
            if not all(
                type(value) is str
                for value in (
                    card_operator_id,
                    card_name,
                    card_version,
                    bound_operator_id,
                    bound_name,
                )
            ):
                self._raise(OperatorSkillErrorCode.BINDING_MISMATCH)
            matches = (
                card_operator_id == operator_id
                and card_name == name
                and card_version == version
                and bound_operator_id == operator_id
                and bound_name == name
            )
        except OperatorSkillLoadError:
            raise
        except Exception:
            self._raise(OperatorSkillErrorCode.BINDING_MISMATCH)
        if not matches:
            self._raise(OperatorSkillErrorCode.BINDING_MISMATCH)
        return card, operator

    @staticmethod
    def _manifest_path(operator_id: str, value: object) -> Path:
        if type(value) is not str:
            raise OperatorSkillLoadError(OperatorSkillErrorCode.MANIFEST_INVALID)
        match = _PINNED_ID.fullmatch(operator_id)
        if match is None or match.group("name") in {".", ".."}:
            raise OperatorSkillLoadError(OperatorSkillErrorCode.MANIFEST_INVALID)
        path = Path(value)
        expected = (match.group("name"), match.group("version"), "manifest.json")
        if path.is_absolute() or path.parts != expected:
            raise OperatorSkillLoadError(OperatorSkillErrorCode.MANIFEST_INVALID)
        return path

    def _index_paths(self) -> dict[str, Path]:
        index = self._read_json(Path("_index.json"), INDEX_BYTE_LIMIT)
        if set(index) != set(_INDEX_KEYS) or index.get("format") != _INDEX_FORMAT:
            self._raise(OperatorSkillErrorCode.MANIFEST_INVALID)
        raw_packages = index.get("packages")
        if type(raw_packages) is not dict:
            self._raise(OperatorSkillErrorCode.MANIFEST_INVALID)
        packages = cast(dict[object, object], raw_packages)

        paths: dict[str, Path] = {}
        for key, value in packages.items():
            if type(key) is not str or _PINNED_ID.fullmatch(key) is None:
                self._raise(OperatorSkillErrorCode.MANIFEST_INVALID)
            paths[key] = self._manifest_path(key, value)
        return paths

    def _manifest(self, operator_id: str) -> tuple[OperatorCard, Operator, Path, dict[str, Any]]:
        card, operator = self._binding(operator_id)
        paths = self._index_paths()
        if operator_id not in paths:
            self._raise(OperatorSkillErrorCode.NOT_AVAILABLE)

        manifest_path = paths[operator_id]
        manifest = self._read_json(manifest_path, MANIFEST_BYTE_LIMIT)
        if set(manifest) != set(_MANIFEST_KEYS):
            self._raise(OperatorSkillErrorCode.MANIFEST_INVALID)
        if manifest.get("format") != _MANIFEST_FORMAT:
            self._raise(OperatorSkillErrorCode.MANIFEST_INVALID)
        if manifest.get("operator_id") != operator_id:
            self._raise(OperatorSkillErrorCode.BINDING_MISMATCH)

        raw_resources = manifest.get("resources")
        if type(raw_resources) is not dict:
            self._raise(OperatorSkillErrorCode.MANIFEST_INVALID)
        resources = cast(dict[object, object], raw_resources)
        if "guide" not in resources:
            self._raise(OperatorSkillErrorCode.MANIFEST_INVALID)
        for kind, record in resources.items():
            if type(kind) is not str or kind not in _RESOURCE_FILES:
                self._raise(OperatorSkillErrorCode.MANIFEST_INVALID)
            if type(record) is not dict:
                self._raise(OperatorSkillErrorCode.MANIFEST_INVALID)
            record_map = cast(dict[object, object], record)
            if set(record_map) != set(_RESOURCE_KEYS):
                self._raise(OperatorSkillErrorCode.MANIFEST_INVALID)
            resource_path = record_map.get("path")
            if type(resource_path) is not str or resource_path != _RESOURCE_FILES[kind]:
                self._raise(OperatorSkillErrorCode.MANIFEST_INVALID)
            digest = record_map.get("sha256")
            if type(digest) is not str or _DIGEST.fullmatch(digest) is None:
                self._raise(OperatorSkillErrorCode.MANIFEST_INVALID)
        return card, operator, manifest_path.parent, manifest

    def available_operator_ids(self) -> tuple[str, ...]:
        if type(self._registry) is not OperatorRegistry:
            self._raise(OperatorSkillErrorCode.TRUST_REQUIRED)
        indexed = self._index_paths()
        return tuple(
            card.operator_id
            for card in self._registry.list_cards()
            if card.operator_id in indexed and is_builtin_card(self._registry, card)
        )

    def describe(self, operator_id: str) -> OperatorSkillDescriptor:
        card, _, _, manifest = self._manifest(operator_id)
        resources = cast(dict[str, object], manifest["resources"])
        declared_kinds = tuple(kind for kind in _RESOURCE_FILES if kind in resources)
        declared_levels = tuple(
            level
            for level, required in {
                2: ("guide",),
                3: ("guide", "examples"),
                4: ("guide", "examples", "history"),
            }.items()
            if all(kind in resources for kind in required)
        )
        return OperatorSkillDescriptor(
            card=card,
            declared_kinds=declared_kinds,
            declared_levels=declared_levels,
        )

    def _text(
        self,
        package: Path,
        manifest: dict[str, Any],
        kind: str,
    ) -> tuple[str, str]:
        resources = cast(dict[str, dict[str, str]], manifest["resources"])
        if kind not in resources:
            self._raise(OperatorSkillErrorCode.NOT_AVAILABLE)
        record = resources[kind]
        try:
            content = self._reader.read(package / record["path"], RESOURCE_BYTE_LIMIT)
        except _ResourceReadError as error:
            if error.reason is _ReadFailure.ROOT_UNAVAILABLE:
                self._raise(OperatorSkillErrorCode.NOT_AVAILABLE)
            self._raise(OperatorSkillErrorCode.RESOURCE_INVALID)
        actual = hashlib.sha256(content).hexdigest()
        if actual != record["sha256"]:
            self._raise(OperatorSkillErrorCode.RESOURCE_INVALID)
        try:
            return content.decode("utf-8"), actual
        except UnicodeDecodeError:
            self._raise(OperatorSkillErrorCode.RESOURCE_INVALID)

    def read(self, operator_id: str, kind: str) -> OperatorResource:
        if type(kind) is not str or kind not in _RESOURCE_FILES:
            self._raise(OperatorSkillErrorCode.RESOURCE_INVALID)
        _, _, package, manifest = self._manifest(operator_id)
        text, digest = self._text(package, manifest, kind)
        return OperatorResource(operator_id=operator_id, kind=kind, text=text, sha256=digest)

    def load(self, operator_id: str, level: int = 2) -> OperatorSkillView:
        if type(level) is not int or level not in {2, 3, 4}:
            self._raise(OperatorSkillErrorCode.NOT_AVAILABLE)
        card, operator, package, manifest = self._manifest(operator_id)
        required = {
            2: ("guide",),
            3: ("guide", "examples"),
            4: ("guide", "examples", "history"),
        }[level]
        loaded = {kind: self._text(package, manifest, kind)[0] for kind in required}
        io = OperatorIOSchema(
            input_shape="List[List[Dict]]",
            output_shape="List[List[Dict]]",
            attributes=snapshot_attribute_specs(operator),
        )
        return OperatorSkillView(
            card=card,
            requested_level=level,
            loaded_kinds=required,
            io=io,
            guide=loaded["guide"],
            examples=loaded.get("examples"),
            history=loaded.get("history"),
        )
