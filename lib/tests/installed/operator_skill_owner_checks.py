from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import itertools
import json
import re
import site
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import cast

INDEX_BYTE_LIMIT = 4_096
MANIFEST_BYTE_LIMIT = 4_096
RESOURCE_BYTE_LIMIT = 16_384
JSON_DEPTH_LIMIT = 4
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
ENVIRONMENTS = frozenset({"base", "ml", "vector", "llm"})
ENVIRONMENT_LINE = re.compile(r"^Environment: (?P<value>\S+)$", re.MULTILINE)
LIVE_NETWORK_NOTICE = "running this example may send requests over the network."
LIVE_CREDENTIAL_NOTICE = "a remote service may require credentials."
LIVE_NON_EXECUTION_NOTICE = "the test suite does not run this example."
LIVE_NOTICE_PARAGRAPHS = frozenset(
    " ".join(order)
    for order in itertools.permutations(
        (LIVE_NETWORK_NOTICE, LIVE_CREDENTIAL_NOTICE, LIVE_NON_EXECUTION_NOTICE)
    )
)


@dataclass(frozen=True)
class Fence:
    language: str
    source: str
    line: int


def extract_fences(text: str) -> tuple[Fence, ...]:
    fences: list[Fence] = []
    language: str | None = None
    opening_line = 0
    body: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if language is None:
            if line in {"```python", "```python live"}:
                language = line.removeprefix("```")
                opening_line = line_number
                body = []
            continue
        if line == "```":
            fences.append(Fence(language, "\n".join(body) + "\n", opening_line))
            language = None
            opening_line = 0
            body = []
            continue
        body.append(line)
    if language is not None:
        raise AssertionError(f"unclosed {language!r} fence at line {opening_line}")
    return tuple(fences)


def parse_environment(text: str) -> str:
    prose: list[str] = []
    inside_fence = False
    for line in text.splitlines():
        if line.startswith("```"):
            inside_fence = not inside_fence
            continue
        if not inside_fence:
            prose.append(line)
    matches = tuple(ENVIRONMENT_LINE.finditer("\n".join(prose)))
    assert len(matches) == 1, f"expected one Environment field, found {len(matches)}"
    value = matches[0].group("value")
    assert value in ENVIRONMENTS, f"unknown Environment: {value}"
    return value


def environment_partitions(pages: dict[str, str]) -> dict[str, tuple[str, ...]]:
    partitions: dict[str, list[str]] = {name: [] for name in sorted(ENVIRONMENTS)}
    for operator_id, page in pages.items():
        partitions[parse_environment(page)].append(operator_id)
    return {
        name: tuple(sorted(operator_ids, key=lambda item: item.encode("utf-8")))
        for name, operator_ids in partitions.items()
    }


def _without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        assert key not in result, f"duplicate JSON key: {key}"
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


def _json_object(path: Path, limit: int) -> dict[object, object]:
    assert not path.is_symlink()
    metadata = path.stat()
    assert stat.S_ISREG(metadata.st_mode)
    raw = path.read_bytes()
    assert len(raw) <= limit
    value: object = json.loads(raw.decode("utf-8"), object_pairs_hook=_without_duplicate_keys)
    assert type(value) is dict
    assert _depth(cast(object, value)) <= JSON_DEPTH_LIMIT
    return cast(dict[object, object], value)


def _load_index(resource_root: Path) -> dict[str, str]:
    value = _json_object(resource_root / "_index.json", INDEX_BYTE_LIMIT)
    assert set(value) == {"format", "packages"}
    assert value["format"] == INDEX_FORMAT
    packages = value.get("packages")
    assert type(packages) is dict
    result: dict[str, str] = {}
    for key, path in cast(dict[object, object], packages).items():
        assert type(key) is str and type(path) is str
        match = PINNED_ID.fullmatch(key)
        assert match is not None
        assert path == f"{match.group('name')}/{match.group('version')}/manifest.json"
        result[key] = path
    assert tuple(result) == tuple(sorted(result, key=lambda item: item.encode("utf-8")))
    package_directories = {
        f"{name.name}@{version.name}"
        for name in resource_root.iterdir()
        if name.is_dir() and not name.is_symlink() and name.name != "__pycache__"
        for version in name.iterdir()
        if version.is_dir() and not version.is_symlink()
    }
    manifest_ids = {
        f"{path.parent.parent.name}@{path.parent.name}"
        for path in resource_root.glob("*/*/manifest.json")
    }
    assert set(result) == package_directories == manifest_ids
    return result


def indexed_example_pages(resource_root: Path) -> dict[str, str]:
    pages: dict[str, str] = {}
    for operator_id, relative_manifest in _load_index(resource_root).items():
        manifest_path = resource_root / relative_manifest
        value = _json_object(manifest_path, MANIFEST_BYTE_LIMIT)
        assert set(value) == {"format", "operator_id", "resources"}
        assert value["format"] == MANIFEST_FORMAT
        assert value["operator_id"] == operator_id
        resources = value.get("resources")
        assert type(resources) is dict
        raw_resources = cast(dict[object, object], resources)
        assert {"guide", "examples"}.issubset(raw_resources)
        assert set(raw_resources).issubset(RESOURCE_FILES)
        declared_files = {"manifest.json"}
        example_text: str | None = None
        for kind, raw_record in raw_resources.items():
            assert type(kind) is str and kind in RESOURCE_FILES
            assert type(raw_record) is dict
            record = cast(dict[object, object], raw_record)
            assert set(record) == {"path", "sha256"}
            path_name = record["path"]
            digest = record["sha256"]
            assert type(path_name) is str and path_name == RESOURCE_FILES[kind]
            assert type(digest) is str and DIGEST.fullmatch(digest)
            declared_files.add(path_name)
            resource_path = manifest_path.parent / path_name
            assert not resource_path.is_symlink()
            raw = resource_path.read_bytes()
            assert len(raw) <= RESOURCE_BYTE_LIMIT
            text = raw.decode("utf-8")
            assert hashlib.sha256(raw).hexdigest() == digest
            if kind == "examples":
                example_text = text
        actual_files = {path.name for path in manifest_path.parent.iterdir() if path.is_file()}
        assert actual_files == declared_files
        assert example_text is not None
        pages[operator_id] = example_text
    return pages


def validate_pages(pages: dict[str, str]) -> dict[str, tuple[Fence, ...]]:
    assert pages, "the package index contains no owner checks"
    extracted: dict[str, tuple[Fence, ...]] = {}
    for operator_id, text in pages.items():
        parse_environment(text)
        fences = extract_fences(text)
        plain = tuple(fence for fence in fences if fence.language == "python")
        assert plain, f"{operator_id} has no executable python fence"
        for fence in fences:
            compile(fence.source, f"{operator_id}:examples.md:{fence.line}", "exec")
            if fence.language == "python live":
                preceding = text.splitlines()[: fence.line - 1]
                while preceding and not preceding[-1].strip():
                    preceding.pop()
                paragraph: list[str] = []
                while preceding and preceding[-1].strip() and not preceding[-1].startswith("```"):
                    paragraph.append(preceding.pop())
                notice = " ".join(reversed(paragraph)).lower()
                assert LIVE_NETWORK_NOTICE in notice, (
                    f"{operator_id} live fence lacks an outbound network notice"
                )
                assert LIVE_CREDENTIAL_NOTICE in notice, (
                    f"{operator_id} live fence lacks a credential notice"
                )
                assert LIVE_NON_EXECUTION_NOTICE in notice, (
                    f"{operator_id} live fence lacks a non-execution notice"
                )
                assert notice in LIVE_NOTICE_PARAGRAPHS, (
                    f"{operator_id} live fence has additional or altered warning text"
                )
        extracted[operator_id] = fences
    assert set(extracted) == set(pages)
    return extracted


def execute_page(operator_id: str, fences: tuple[Fence, ...]) -> None:
    namespace: dict[str, object] = {
        "__name__": "__operator_skill_owner_check__",
        "__package__": None,
    }
    for fence in fences:
        if fence.language != "python":
            continue
        code = compile(fence.source, f"{operator_id}:examples.md:{fence.line}", "exec")
        exec(code, namespace, namespace)


def installed_resource_root(forbidden_roots: tuple[Path, ...]) -> tuple[Path, Path]:
    import blue_data_ops.operator_skills as operator_skills

    module_location = operator_skills.__file__
    assert isinstance(module_location, str)
    module_file = Path(module_location).resolve()
    distribution_location = importlib.metadata.distribution("blue-data-ops").locate_file("")
    distribution_root = Path(str(distribution_location)).resolve()
    site_roots = tuple(Path(item).resolve() for item in site.getsitepackages())
    assert site_roots
    assert any(module_file.is_relative_to(root) for root in site_roots)
    assert any(distribution_root.is_relative_to(root) for root in site_roots)
    assert module_file.is_relative_to(distribution_root)
    resource_root = module_file.parent
    for forbidden in forbidden_roots:
        resolved = forbidden.resolve()
        assert not resource_root.is_relative_to(resolved)
        assert all(not Path(item).resolve().is_relative_to(resolved) for item in sys.path if item)
    return resource_root, distribution_root


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--forbid-root", action="append", default=[])
    parser.add_argument("--only", action="append", default=[])
    arguments = parser.parse_args()

    forbidden = tuple(Path(item) for item in cast(list[str], arguments.forbid_root))
    resource_root, distribution_root = installed_resource_root(forbidden)
    pages = indexed_example_pages(resource_root)
    fences = validate_pages(pages)
    partitions = environment_partitions(pages)
    selected = set(cast(list[str], arguments.only)) or set(pages)
    assert selected.issubset(pages)
    print(
        json.dumps(
            {
                "distribution_root": str(distribution_root),
                "environments": {
                    name: list(operator_ids) for name, operator_ids in partitions.items()
                },
                "executed": sorted(selected),
                "resource_root": str(resource_root),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    for operator_id in sorted(selected):
        execute_page(operator_id, fences[operator_id])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
