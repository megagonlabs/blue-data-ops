from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import zipfile
from dataclasses import dataclass
from email.message import Message
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import cast

CORE_DISTRIBUTION = "blue-data-ops"
MCP_DISTRIBUTION = "blue-data-ops-mcp"
PACKAGE_PREFIX = PurePosixPath("blue_data_ops")
RESOURCE_PREFIX = PACKAGE_PREFIX / "operator_skills"
FIXED_NON_CODE_MEMBERS = {
    (PACKAGE_PREFIX / "py.typed").as_posix(),
    (PACKAGE_PREFIX / "plan/_schemas/plan-candidates.schema.json").as_posix(),
}
INDEX_FORMAT = "blue-data-ops/operator-skill-index@1"
MANIFEST_FORMAT = "blue-data-ops/operator-skill@1"
INDEX_BYTE_LIMIT = 4_096
MANIFEST_BYTE_LIMIT = 4_096
RESOURCE_BYTE_LIMIT = 16_384
JSON_DEPTH_LIMIT = 4
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


@dataclass(frozen=True)
class WheelRecord:
    path: Path
    name: str
    version: str
    requirements: tuple[str, ...]


def _metadata(archive: zipfile.ZipFile, path: Path) -> WheelRecord:
    members = tuple(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
    assert len(members) == 1, f"{path} has {len(members)} METADATA files"
    message: Message = BytesParser().parsebytes(archive.read(members[0]))
    name = message.get("Name")
    version = message.get("Version")
    assert isinstance(name, str) and isinstance(version, str)
    return WheelRecord(path, name, version, tuple(message.get_all("Requires-Dist", [])))


def _without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        assert key not in result
        result[key] = value
    return result


def _depth(value: object) -> int:
    if type(value) is dict:
        return 1 + max(
            (_depth(item) for item in cast(dict[object, object], value).values()),
            default=0,
        )
    if type(value) is list:
        return 1 + max((_depth(item) for item in cast(list[object], value)), default=0)
    return 0


def _regular_member_bytes(archive: zipfile.ZipFile, path: PurePosixPath) -> bytes:
    member = archive.getinfo(path.as_posix())
    assert not member.is_dir()
    assert not stat.S_ISLNK(member.external_attr >> 16)
    return archive.read(member)


def _json_object(archive: zipfile.ZipFile, path: PurePosixPath, limit: int) -> dict[object, object]:
    raw = _regular_member_bytes(archive, path)
    assert len(raw) <= limit
    value: object = json.loads(raw.decode("utf-8"), object_pairs_hook=_without_duplicate_keys)
    assert type(value) is dict
    assert _depth(cast(object, value)) <= JSON_DEPTH_LIMIT
    return cast(dict[object, object], value)


def _non_code_package_members(archive: zipfile.ZipFile) -> set[str]:
    prefix = PACKAGE_PREFIX.as_posix() + "/"
    return {
        name
        for name in archive.namelist()
        if name.startswith(prefix)
        and not name.endswith("/")
        and PurePosixPath(name).suffix != ".py"
    }


def _wheel_data_members(archive: zipfile.ZipFile) -> set[str]:
    return {
        name
        for name in archive.namelist()
        if name.partition("/")[0].endswith(".data") and not name.endswith("/")
    }


def _check_core_resources(archive: zipfile.ZipFile) -> tuple[str, ...]:
    index_path = RESOURCE_PREFIX / "_index.json"
    index = _json_object(archive, index_path, INDEX_BYTE_LIMIT)
    assert set(index) == {"format", "packages"}
    assert index["format"] == INDEX_FORMAT
    packages = index["packages"]
    assert type(packages) is dict
    typed_packages = cast(dict[object, object], packages)
    assert tuple(typed_packages) == tuple(
        sorted(typed_packages, key=lambda item: str(item).encode("utf-8"))
    )
    operator_ids: list[str] = []
    expected_members = FIXED_NON_CODE_MEMBERS | {index_path.as_posix()}
    for operator_id, manifest_name in typed_packages.items():
        assert type(operator_id) is str and type(manifest_name) is str
        match = PINNED_ID.fullmatch(operator_id)
        assert match is not None
        expected_manifest = (
            RESOURCE_PREFIX / match.group("name") / match.group("version") / "manifest.json"
        )
        assert manifest_name == expected_manifest.relative_to(RESOURCE_PREFIX).as_posix()
        manifest = _json_object(archive, expected_manifest, MANIFEST_BYTE_LIMIT)
        assert set(manifest) == {"format", "operator_id", "resources"}
        assert manifest["format"] == MANIFEST_FORMAT
        assert manifest.get("operator_id") == operator_id
        resources = manifest.get("resources")
        assert type(resources) is dict
        raw_resources = cast(dict[object, object], resources)
        assert {"guide", "examples"}.issubset(raw_resources)
        assert set(raw_resources).issubset(RESOURCE_FILES)
        expected_members.add(expected_manifest.as_posix())
        for kind, record in raw_resources.items():
            assert type(kind) is str and kind in RESOURCE_FILES
            assert type(record) is dict
            record_map = cast(dict[object, object], record)
            assert set(record_map) == {"path", "sha256"}
            path_name = record_map.get("path")
            digest = record_map.get("sha256")
            assert type(path_name) is str and path_name == RESOURCE_FILES[kind]
            assert type(digest) is str and re.fullmatch(r"[0-9a-f]{64}", digest)
            member = expected_manifest.parent / path_name
            raw = _regular_member_bytes(archive, member)
            assert len(raw) <= RESOURCE_BYTE_LIMIT
            raw.decode("utf-8")
            assert hashlib.sha256(raw).hexdigest() == digest
            expected_members.add(member.as_posix())
        operator_ids.append(operator_id)
    for fixed in FIXED_NON_CODE_MEMBERS:
        _regular_member_bytes(archive, PurePosixPath(fixed))
    assert not _wheel_data_members(archive)
    assert _non_code_package_members(archive) == expected_members
    return tuple(operator_ids)


def check_release(
    core_wheel: Path,
    mcp_wheel: Path,
    *,
    expected_core_version: str,
    expected_mcp_version: str,
    expected_operator_ids: tuple[str, ...],
) -> tuple[str, ...]:
    with zipfile.ZipFile(core_wheel) as archive:
        core = _metadata(archive, core_wheel)
        operator_ids = _check_core_resources(archive)
    with zipfile.ZipFile(mcp_wheel) as archive:
        mcp = _metadata(archive, mcp_wheel)
    assert core.name == CORE_DISTRIBUTION and core.version == expected_core_version
    assert mcp.name == MCP_DISTRIBUTION and mcp.version == expected_mcp_version
    assert expected_operator_ids
    assert expected_operator_ids == tuple(
        sorted(expected_operator_ids, key=lambda item: item.encode("utf-8"))
    )
    assert operator_ids == expected_operator_ids
    normalized_requirements = tuple(
        requirement.replace(" ", "") for requirement in mcp.requirements
    )
    assert f"{CORE_DISTRIBUTION}=={expected_core_version}" in normalized_requirements
    return operator_ids


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core-wheel", required=True, type=Path)
    parser.add_argument("--mcp-wheel", required=True, type=Path)
    parser.add_argument("--core-version", required=True)
    parser.add_argument("--mcp-version", required=True)
    parser.add_argument("--expect-operator-id", required=True, action="append")
    arguments = parser.parse_args()
    operator_ids = check_release(
        arguments.core_wheel,
        arguments.mcp_wheel,
        expected_core_version=arguments.core_version,
        expected_mcp_version=arguments.mcp_version,
        expected_operator_ids=tuple(arguments.expect_operator_id),
    )
    print(json.dumps({"operator_ids": operator_ids}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
