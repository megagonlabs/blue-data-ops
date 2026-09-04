from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from blue_data_ops.operator_skills import (
    INDEX_BYTE_LIMIT,
    JSON_DEPTH_LIMIT,
    MANIFEST_BYTE_LIMIT,
    RESOURCE_BYTE_LIMIT,
    OperatorSkillErrorCode,
    OperatorSkillLoader,
    OperatorSkillLoadError,
)
from blue_data_ops.operators import OperatorRegistry, versioned_registry

from ._conformance_support import (
    INDEX_FORMAT,
    MANIFEST_FORMAT,
    RESOURCE_FILES,
    CatalogSnapshot,
    inspect_catalog,
)

PACKAGE_ROOT = Path(__file__).parents[3] / "src" / "blue_data_ops" / "operator_skills"
EXPECTED_PACKAGE_COUNT = 9
CATALOG = inspect_catalog(
    PACKAGE_ROOT,
    minimum_packages=1,
    expected_package_count=EXPECTED_PACKAGE_COUNT,
)
EXERCISED_PACKAGE_IDS = frozenset(CATALOG.package_ids)
ATTRIBUTE_SUMMARY_VERB = re.compile(
    r"\b(?:declares|describes|gives|lists|enumerates|contains|covers)\b",
    re.IGNORECASE,
)
ATTRIBUTE_DECLARATION = re.compile(r"\bdeclares\b(?P<terms>[^.]+)\.", re.IGNORECASE)
INLINE_CODE = re.compile(r"`([^`\n]+)`")


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _attribute_summary_paragraphs(guide: str) -> tuple[str, ...]:
    return tuple(
        paragraph.replace("\n", " ")
        for paragraph in guide.split("\n\n")
        if "`io.attributes`" in paragraph and ATTRIBUTE_SUMMARY_VERB.search(paragraph)
    )


def _mentions_attribute(paragraph: str, name: str) -> bool:
    spellings = (name, name.replace("_", " "), name.replace("_", "-"))
    return any(
        re.search(rf"(?<![A-Za-z0-9_]){re.escape(spelling)}(?![A-Za-z0-9_])", paragraph)
        for spelling in spellings
    )


def _attribute_summary_issues(guide: str, declared_attributes: set[str]) -> tuple[str, ...]:
    issues: set[str] = set()
    for paragraph in _attribute_summary_paragraphs(guide):
        for name in declared_attributes:
            if not _mentions_attribute(paragraph, name):
                issues.add(f"missing:{name}")
        for match in ATTRIBUTE_DECLARATION.finditer(paragraph):
            claimed = set(INLINE_CODE.findall(match.group("terms")))
            for name in claimed - declared_attributes:
                issues.add(f"unexpected:{name}")
    return tuple(sorted(issues))


def _synthetic_catalog(tmp_path: Path) -> tuple[Path, tuple[str, str]]:
    registry = versioned_registry()
    selected_ids = sorted(
        card.operator_id for card in registry.list_cards() if card.version == "2.0.0"
    )[:2]
    assert len(selected_ids) == 2
    operator_ids = (selected_ids[0], selected_ids[1])
    packages: dict[str, str] = {}
    for operator_id in operator_ids:
        name, version = operator_id.split("@", 1)
        package = tmp_path / name / version
        package.mkdir(parents=True)
        guide = f"# {name}\n\nSynthetic guide for catalog conformance.\n".encode()
        examples = (
            f"# Owner check\n\n```python\nassert {operator_id!r}.endswith('@2.0.0')\n```\n"
        ).encode()
        (package / "Operator.md").write_bytes(guide)
        (package / "examples.md").write_bytes(examples)
        _write_json(
            package / "manifest.json",
            {
                "format": MANIFEST_FORMAT,
                "operator_id": operator_id,
                "resources": {
                    "guide": {"path": "Operator.md", "sha256": _digest(guide)},
                    "examples": {"path": "examples.md", "sha256": _digest(examples)},
                },
            },
        )
        packages[operator_id] = f"{name}/{version}/manifest.json"
    _write_json(tmp_path / "_index.json", {"format": INDEX_FORMAT, "packages": packages})
    return tmp_path, operator_ids


def _copy_synthetic(tmp_path: Path, suffix: str) -> tuple[Path, tuple[str, str]]:
    source, operator_ids = _synthetic_catalog(tmp_path / f"{suffix}-source")
    target = tmp_path / suffix
    shutil.copytree(source, target)
    return target, operator_ids


def _assert_invalid_catalog(root: Path) -> None:
    with pytest.raises((AssertionError, UnicodeDecodeError, json.JSONDecodeError, OSError)):
        inspect_catalog(root, minimum_packages=2)


def _load_json(path: Path) -> dict[str, Any]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    assert type(value) is dict
    return cast(dict[str, Any], value)


def _error(call: Callable[[], object], code: OperatorSkillErrorCode) -> None:
    with pytest.raises(OperatorSkillLoadError) as raised:
        call()
    assert raised.value.code is code


def test_shipped_catalog_sets_and_generic_test_ids_are_equal() -> None:
    assert (INDEX_BYTE_LIMIT, MANIFEST_BYTE_LIMIT, RESOURCE_BYTE_LIMIT, JSON_DEPTH_LIMIT) == (
        4_096,
        4_096,
        16_384,
        4,
    )
    observed = inspect_catalog(
        PACKAGE_ROOT,
        minimum_packages=1,
        expected_package_count=EXPECTED_PACKAGE_COUNT,
        exercised_package_ids=set(EXERCISED_PACKAGE_IDS),
    )
    assert observed.package_ids == CATALOG.package_ids
    assert all(
        set(package.resources) == {"guide", "examples"} for package in observed.packages.values()
    )


def test_guide_attribute_summaries_match_the_live_schema_across_the_catalog() -> None:
    loader = OperatorSkillLoader(versioned_registry())
    checked = 0
    visited: set[str] = set()

    for operator_id in CATALOG.package_ids:
        skill = loader.load(operator_id, level=2)
        guide = skill.guide or ""
        checked += len(_attribute_summary_paragraphs(guide))
        visited.add(operator_id)
        assert _attribute_summary_issues(guide, set(skill.io.attributes)) == ()

    assert visited == set(CATALOG.package_ids)
    assert checked > 0


@pytest.mark.parametrize(
    ("guide", "declared_attributes", "expected"),
    (
        (
            "The live `io.attributes` mapping declares only `strategy`.",
            {"strategy"},
            (),
        ),
        (
            "The live `io.attributes` mapping declares `by_key` and `by_position`.",
            {"strategy"},
            ("missing:strategy", "unexpected:by_key", "unexpected:by_position"),
        ),
        (
            "The live `io.attributes` mapping describes vector, label, output, and tree settings. "
            "A fixed `random_state` makes a repeated check deterministic.",
            {
                "vector_key",
                "label_key",
                "output_key",
                "criterion",
                "splitter",
                "max_depth",
                "min_samples_split",
                "min_samples_leaf",
                "random_state",
                "n_neighbors",
                "weights",
                "alpha",
                "fit_prior",
            },
            (
                "missing:alpha",
                "missing:criterion",
                "missing:fit_prior",
                "missing:label_key",
                "missing:max_depth",
                "missing:min_samples_leaf",
                "missing:min_samples_split",
                "missing:n_neighbors",
                "missing:output_key",
                "missing:splitter",
                "missing:vector_key",
                "missing:weights",
            ),
        ),
    ),
)
def test_attribute_summary_check_rejects_values_as_keys_and_stale_category_lists(
    guide: str, declared_attributes: set[str], expected: tuple[str, ...]
) -> None:
    assert _attribute_summary_issues(guide, declared_attributes) == expected


@pytest.mark.parametrize("operator_id", CATALOG.package_ids)
def test_every_indexed_package_passes_the_same_loader_contract(operator_id: str) -> None:
    registry = versioned_registry()
    loader = OperatorSkillLoader(registry)
    first = loader.load(operator_id, level=3)
    second = loader.load(operator_id, level=3)
    package = CATALOG.packages[operator_id]

    assert first.card is registry.get_card(operator_id)
    assert first.loaded_kinds == ("guide", "examples")
    assert first.guide
    assert first.examples
    assert first.io.input_shape == first.io.output_shape == "List[List[Dict]]"
    assert first.io.attributes == second.io.attributes
    assert first.io.attributes is not second.io.attributes

    if first.io.attributes:
        key = next(iter(first.io.attributes))
        first.io.attributes.pop(key)
        assert key in second.io.attributes

    for kind, record in package.resources.items():
        resource = loader.read(operator_id, kind)
        assert resource.operator_id == operator_id
        assert resource.kind == kind
        assert resource.sha256 == record.sha256
        assert len(resource.text.encode("utf-8")) == record.size

    for kind in set(RESOURCE_FILES) - set(package.resources):
        _error(
            lambda kind=kind: loader.read(operator_id, kind), OperatorSkillErrorCode.NOT_AVAILABLE
        )
    if "history" not in package.resources:
        _error(lambda: loader.load(operator_id, level=4), OperatorSkillErrorCode.NOT_AVAILABLE)


@pytest.mark.parametrize(
    "operator_id",
    tuple(
        sorted(
            {card.operator_id for card in versioned_registry().list_cards()}
            - set(CATALOG.package_ids)
        )
    ),
)
def test_unindexed_exact_ids_do_not_fall_back(operator_id: str) -> None:
    _error(
        lambda: OperatorSkillLoader(versioned_registry()).load(operator_id),
        OperatorSkillErrorCode.NOT_AVAILABLE,
    )


@pytest.mark.parametrize("operator_id", CATALOG.package_ids)
def test_public_custom_registration_cannot_claim_an_indexed_package(operator_id: str) -> None:
    source = versioned_registry()
    card = source.get_card(operator_id)
    assert card is not None
    registry = OperatorRegistry()
    registry.register(source.resolve(operator_id), card.version)
    _error(
        lambda: OperatorSkillLoader(registry).load(operator_id),
        OperatorSkillErrorCode.TRUST_REQUIRED,
    )


def test_synthetic_multi_package_catalog_passes_without_named_cases(tmp_path: Path) -> None:
    root, operator_ids = _synthetic_catalog(tmp_path)
    snapshot = inspect_catalog(
        root,
        minimum_packages=2,
        exercised_package_ids=set(operator_ids),
    )
    assert snapshot.package_ids == operator_ids


def test_index_directory_manifest_and_file_sets_fail_independently(tmp_path: Path) -> None:
    root, operator_ids = _copy_synthetic(tmp_path, "mutated")
    index_path = root / "_index.json"
    index = _load_json(index_path)
    index["packages"].pop(operator_ids[0])
    _write_json(index_path, index)
    _assert_invalid_catalog(root)

    root, operator_ids = _copy_synthetic(tmp_path, "missing-directory")
    first = _catalog_id_path(root, operator_ids[0])
    shutil.rmtree(first)
    _assert_invalid_catalog(root)

    root, _ = _copy_synthetic(tmp_path, "extra-directory")
    extra = root / "unindexed" / "2.0.0"
    extra.mkdir(parents=True)
    (extra / "manifest.json").write_text("{}\n", encoding="utf-8")
    _assert_invalid_catalog(root)

    root, operator_ids = _copy_synthetic(tmp_path, "missing-manifest")
    (_catalog_id_path(root, operator_ids[0]) / "manifest.json").unlink()
    _assert_invalid_catalog(root)

    root, operator_ids = _copy_synthetic(tmp_path, "extra-file")
    (_catalog_id_path(root, operator_ids[0]) / "history.md").write_text(
        "unindexed\n", encoding="utf-8"
    )
    _assert_invalid_catalog(root)

    root, _ = _copy_synthetic(tmp_path, "root-file")
    (root / "stray.md").write_text("unindexed\n", encoding="utf-8")
    _assert_invalid_catalog(root)

    root, _ = _copy_synthetic(tmp_path, "root-directory")
    unexpected = root / "junk"
    unexpected.mkdir()
    (unexpected / "leak.md").write_text("unindexed\n", encoding="utf-8")
    _assert_invalid_catalog(root)


def _catalog_id_path(root: Path, operator_id: str) -> Path:
    name, version = operator_id.split("@", 1)
    return root / name / version


@pytest.mark.parametrize(
    "mutation",
    ("id", "path", "digest", "resource-set", "utf8", "size", "depth", "ordering"),
)
def test_manifest_resource_and_index_mutations_turn_the_instrument_red(
    tmp_path: Path, mutation: str
) -> None:
    root, operator_ids = _copy_synthetic(tmp_path, mutation)
    package = _catalog_id_path(root, operator_ids[0])
    manifest_path = package / "manifest.json"
    manifest = _load_json(manifest_path)

    if mutation == "id":
        manifest["operator_id"] = operator_ids[1]
        _write_json(manifest_path, manifest)
    elif mutation == "path":
        manifest["resources"]["guide"]["path"] = "examples.md"
        _write_json(manifest_path, manifest)
    elif mutation == "digest":
        manifest["resources"]["guide"]["sha256"] = "0" * 64
        _write_json(manifest_path, manifest)
    elif mutation == "resource-set":
        manifest["resources"].pop("examples")
        _write_json(manifest_path, manifest)
    elif mutation == "utf8":
        content = b"\xff"
        (package / "examples.md").write_bytes(content)
        manifest["resources"]["examples"]["sha256"] = _digest(content)
        _write_json(manifest_path, manifest)
    elif mutation == "size":
        content = b"x" * (RESOURCE_BYTE_LIMIT + 1)
        (package / "examples.md").write_bytes(content)
        manifest["resources"]["examples"]["sha256"] = _digest(content)
        _write_json(manifest_path, manifest)
    elif mutation == "depth":
        index = _load_json(root / "_index.json")
        index["extra"] = {"one": {"two": {"three": {"four": "too deep"}}}}
        _write_json(root / "_index.json", index)
    elif mutation == "ordering":
        index = _load_json(root / "_index.json")
        index["packages"] = dict(reversed(tuple(index["packages"].items())))
        _write_json(root / "_index.json", index)
    else:
        raise AssertionError(f"unknown mutation: {mutation}")
    _assert_invalid_catalog(root)


@pytest.mark.parametrize("location", ("root", "ancestor", "resource"))
def test_symlink_mutations_turn_the_instrument_red(tmp_path: Path, location: str) -> None:
    root, operator_ids = _copy_synthetic(tmp_path, location)
    package = _catalog_id_path(root, operator_ids[0])
    if location == "root":
        alias = tmp_path / "root-alias"
        alias.symlink_to(root, target_is_directory=True)
        _assert_invalid_catalog(alias)
    elif location == "ancestor":
        name_directory = package.parent
        target = root / "relocated"
        name_directory.rename(target)
        name_directory.symlink_to(target.name, target_is_directory=True)
        _assert_invalid_catalog(root)
    else:
        resource = package / "examples.md"
        target = resource.with_name("examples-target.md")
        resource.rename(target)
        resource.symlink_to(target.name)
        _assert_invalid_catalog(root)


def test_catalog_snapshot_records_every_resource_measurement() -> None:
    snapshot: CatalogSnapshot = CATALOG
    assert snapshot.index_size > 0
    assert all(
        package.resources and all(record.size > 0 for record in package.resources.values())
        for package in snapshot.packages.values()
    )


@pytest.mark.parametrize(
    "mutation,mutated_code,sibling_code",
    (
        ("row-removed", OperatorSkillErrorCode.NOT_AVAILABLE, None),
        ("manifest-missing", OperatorSkillErrorCode.MANIFEST_INVALID, None),
        (
            "row-malformed",
            OperatorSkillErrorCode.MANIFEST_INVALID,
            OperatorSkillErrorCode.MANIFEST_INVALID,
        ),
        ("resource-tampered", OperatorSkillErrorCode.RESOURCE_INVALID, None),
    ),
)
def test_loader_failure_taxonomy_records_a_healthy_sibling(
    tmp_path: Path,
    mutation: str,
    mutated_code: OperatorSkillErrorCode,
    sibling_code: OperatorSkillErrorCode | None,
) -> None:
    root, operator_ids = _synthetic_catalog(tmp_path)
    mutated_id, sibling_id = operator_ids
    index_path = root / "_index.json"
    if mutation == "row-removed":
        index = _load_json(index_path)
        index["packages"].pop(mutated_id)
        _write_json(index_path, index)
    elif mutation == "manifest-missing":
        (_catalog_id_path(root, mutated_id) / "manifest.json").unlink()
    elif mutation == "row-malformed":
        index = _load_json(index_path)
        index["packages"][mutated_id] = None
        _write_json(index_path, index)
    elif mutation == "resource-tampered":
        (_catalog_id_path(root, mutated_id) / "examples.md").write_text(
            "changed\n", encoding="utf-8"
        )
    else:
        raise AssertionError(f"unknown mutation: {mutation}")

    loader = OperatorSkillLoader(versioned_registry(), _resource_root=root)
    _error(lambda: loader.load(mutated_id, level=3), mutated_code)
    if sibling_code is None:
        assert loader.load(sibling_id, level=3).card.operator_id == sibling_id
    else:
        _error(lambda: loader.load(sibling_id, level=3), sibling_code)
