from __future__ import annotations

import hashlib
import json
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from blue_data_ops.operator_skills import (
    INDEX_BYTE_LIMIT,
    JSON_DEPTH_LIMIT,
    MANIFEST_BYTE_LIMIT,
    RESOURCE_BYTE_LIMIT,
)

INDEX_FORMAT = "blue-data-ops/operator-skill-index@1"
MANIFEST_FORMAT = "blue-data-ops/operator-skill@1"
RESOURCE_FILES = {
    "guide": "Operator.md",
    "examples": "examples.md",
    "optimization": "optimization.md",
    "issues": "issues.md",
    "history": "history.md",
}
PINNED_ID = re.compile(
    r"^(?P<name>[^/@\\]+)@(?P<version>(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))$"
)
DIGEST = re.compile(r"^[0-9a-f]{64}$")
ROOT_SUPPORT_FILES = {"_index.json", "__init__.py", "loader.py"}


@dataclass(frozen=True)
class ResourceRecord:
    kind: str
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class PackageRecord:
    operator_id: str
    manifest_path: str
    resources: dict[str, ResourceRecord]


@dataclass(frozen=True)
class CatalogSnapshot:
    root: Path
    package_ids: tuple[str, ...]
    packages: dict[str, PackageRecord]
    index_size: int


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        assert key not in result, f"duplicate JSON key: {key}"
        result[key] = value
    return result


def _depth(value: object) -> int:
    if type(value) is dict:
        mapping = cast(dict[object, object], value)
        return 1 + max((_depth(item) for item in mapping.values()), default=0)
    if type(value) is list:
        sequence = cast(list[object], value)
        return 1 + max((_depth(item) for item in sequence), default=0)
    return 0


def _json_object(path: Path, limit: int) -> tuple[dict[str, Any], int]:
    assert not path.is_symlink(), f"JSON path is a symlink: {path}"
    metadata = path.stat()
    assert stat.S_ISREG(metadata.st_mode), f"JSON path is not a regular file: {path}"
    raw = path.read_bytes()
    assert len(raw) <= limit, f"JSON file exceeds {limit} bytes: {path}"
    value: object = json.loads(raw.decode("utf-8"), object_pairs_hook=_object_without_duplicates)
    assert type(value) is dict, f"JSON document is not an object: {path}"
    assert _depth(cast(object, value)) <= JSON_DEPTH_LIMIT, f"JSON document is too deep: {path}"
    return cast(dict[str, Any], value), len(raw)


def _id_for_directory(path: Path) -> str:
    operator_id = f"{path.parent.name}@{path.name}"
    assert PINNED_ID.fullmatch(operator_id), f"invalid package directory: {path}"
    return operator_id


def _package_directories(root: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for name_directory in root.iterdir():
        assert not name_directory.is_symlink(), (
            f"resource-root child is a symlink: {name_directory}"
        )
        if name_directory.is_file():
            assert name_directory.name in ROOT_SUPPORT_FILES, (
                f"unexpected resource-root file: {name_directory}"
            )
            continue
        assert name_directory.is_dir(), f"invalid resource-root child: {name_directory}"
        if name_directory.name == "__pycache__":
            continue
        for version_directory in name_directory.iterdir():
            assert not version_directory.is_symlink(), (
                f"package directory is a symlink: {version_directory}"
            )
            assert version_directory.is_dir(), (
                f"unexpected package-ancestor child: {version_directory}"
            )
            operator_id = _id_for_directory(version_directory)
            assert operator_id not in found, f"duplicate package directory: {operator_id}"
            found[operator_id] = version_directory
    return found


def inspect_catalog(
    root: Path,
    *,
    minimum_packages: int,
    expected_package_count: int | None = None,
    exercised_package_ids: set[str] | None = None,
) -> CatalogSnapshot:
    assert root.is_dir() and not root.is_symlink(), f"invalid resource root: {root}"
    index, index_size = _json_object(root / "_index.json", INDEX_BYTE_LIMIT)
    assert set(index) == {"format", "packages"}
    assert index["format"] == INDEX_FORMAT
    assert type(index["packages"]) is dict
    raw_packages = cast(dict[object, object], index["packages"])

    package_ids = tuple(raw_packages)
    assert len(package_ids) >= minimum_packages
    if expected_package_count is not None:
        assert len(package_ids) == expected_package_count
    assert all(type(operator_id) is str for operator_id in package_ids)
    typed_ids = cast(tuple[str, ...], package_ids)
    assert typed_ids == tuple(sorted(typed_ids, key=lambda item: item.encode("utf-8")))
    assert len(set(typed_ids)) == len(typed_ids)

    manifest_paths: dict[str, str] = {}
    for operator_id, raw_path in raw_packages.items():
        assert type(operator_id) is str and PINNED_ID.fullmatch(operator_id)
        assert type(raw_path) is str
        match = PINNED_ID.fullmatch(operator_id)
        assert match is not None
        expected = f"{match.group('name')}/{match.group('version')}/manifest.json"
        assert raw_path == expected
        manifest_paths[operator_id] = raw_path

    directories = _package_directories(root)
    manifest_files = tuple(root.glob("*/*/manifest.json"))
    manifest_ids = {_id_for_directory(path.parent) for path in manifest_files}
    expected_ids = set(typed_ids)
    assert expected_ids == set(directories) == manifest_ids
    expected_names = {operator_id.split("@", 1)[0] for operator_id in expected_ids}
    actual_names = {
        path.name for path in root.iterdir() if path.is_dir() and path.name != "__pycache__"
    }
    assert actual_names == expected_names
    if exercised_package_ids is not None:
        assert expected_ids == exercised_package_ids

    packages: dict[str, PackageRecord] = {}
    for operator_id in typed_ids:
        version_directory = directories[operator_id]
        assert not any(child.is_dir() for child in version_directory.iterdir())
        manifest_path = root / manifest_paths[operator_id]
        manifest, _ = _json_object(manifest_path, MANIFEST_BYTE_LIMIT)
        assert set(manifest) == {"format", "operator_id", "resources"}
        assert manifest["format"] == MANIFEST_FORMAT
        assert manifest["operator_id"] == operator_id
        assert type(manifest["resources"]) is dict
        raw_resources = cast(dict[object, object], manifest["resources"])
        assert {"guide", "examples"}.issubset(raw_resources)
        assert set(raw_resources).issubset(RESOURCE_FILES)

        resources: dict[str, ResourceRecord] = {}
        declared_files = {"manifest.json"}
        for kind, raw_record in raw_resources.items():
            assert type(kind) is str and kind in RESOURCE_FILES
            assert type(raw_record) is dict
            record = cast(dict[object, object], raw_record)
            assert set(record) == {"path", "sha256"}
            resource_path = record["path"]
            digest = record["sha256"]
            assert type(resource_path) is str and resource_path == RESOURCE_FILES[kind]
            assert type(digest) is str and DIGEST.fullmatch(digest)
            declared_files.add(resource_path)

            path = version_directory / resource_path
            assert not path.is_symlink(), f"resource path is a symlink: {path}"
            metadata = path.stat()
            assert stat.S_ISREG(metadata.st_mode), f"resource is not a regular file: {path}"
            raw = path.read_bytes()
            assert len(raw) <= RESOURCE_BYTE_LIMIT
            raw.decode("utf-8")
            assert hashlib.sha256(raw).hexdigest() == digest
            resources[kind] = ResourceRecord(kind, resource_path, digest, len(raw))

        eligible_files = {path.name for path in version_directory.iterdir() if path.is_file()}
        assert eligible_files == declared_files
        packages[operator_id] = PackageRecord(
            operator_id=operator_id,
            manifest_path=manifest_paths[operator_id],
            resources=resources,
        )

    return CatalogSnapshot(root, typed_ids, packages, index_size)
