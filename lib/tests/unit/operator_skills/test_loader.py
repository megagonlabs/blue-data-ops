from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from blue_data_ops import operator_skills
from blue_data_ops.operator_skills import (
    INDEX_BYTE_LIMIT,
    RESOURCE_BYTE_LIMIT,
    OperatorSkillErrorCode,
    OperatorSkillLoader,
    OperatorSkillLoadError,
)
from blue_data_ops.operators import NL2SQLOperator, OperatorRegistry, versioned_registry

PACKAGE_ROOT = Path(operator_skills.__file__).resolve().parent
OPERATOR_ID = "nl2sql@2.0.0"


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _copy_resources(tmp_path: Path) -> Path:
    root = tmp_path / "operator_skills"
    shutil.copytree(PACKAGE_ROOT, root, ignore=shutil.ignore_patterns("*.py", "__pycache__"))
    return root


def _load_json(path: Path) -> dict[str, Any]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    assert type(value) is dict
    return cast(dict[str, Any], value)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _manifest(root: Path) -> Path:
    return root / "nl2sql" / "2.0.0" / "manifest.json"


def _error(call: Callable[[], object], code: OperatorSkillErrorCode) -> None:
    with pytest.raises(OperatorSkillLoadError) as raised:
        call()
    assert raised.value.code is code


def test_owner_check_loads_reviewed_nl2sql_resources() -> None:
    reads: list[str] = []
    registry = versioned_registry()
    view = OperatorSkillLoader(registry, _on_read=reads.append).load(OPERATOR_ID, level=3)

    assert view.card is registry.get_card(OPERATOR_ID)
    assert view.requested_level == 3
    assert view.loaded_kinds == ("guide", "examples")
    assert "translates a natural-language question" in view.guide
    assert view.examples is not None and "explicit Python check" in view.examples
    assert view.history is None
    assert view.io.input_shape == view.io.output_shape == "List[List[Dict]]"
    assert view.io.attributes["question"].required is True
    assert view.io.attributes["protocol"].default == "postgres"
    assert reads == [
        "_index.json",
        "nl2sql/2.0.0/manifest.json",
        "nl2sql/2.0.0/Operator.md",
        "nl2sql/2.0.0/examples.md",
    ]


def test_owner_check_refreshes_and_detaches_live_attribute_schema() -> None:
    registry = versioned_registry()
    operator = registry.resolve(OPERATOR_ID)
    definitions = operator.properties["attributes"]
    definitions["question"]["description"] = "Owner-check description"

    view = OperatorSkillLoader(registry).load(OPERATOR_ID)
    assert view.io.attributes["question"].description == "Owner-check description"
    definitions["question"]["description"] = "Changed after loading"
    assert view.io.attributes["question"].description == "Owner-check description"


def test_levels_are_cumulative_and_optional_resources_fail_explicitly() -> None:
    loader = OperatorSkillLoader(versioned_registry())
    level2 = loader.load(OPERATOR_ID, level=2)
    assert level2.loaded_kinds == ("guide",)
    assert level2.examples is None
    _error(lambda: loader.load(OPERATOR_ID, level=4), OperatorSkillErrorCode.NOT_AVAILABLE)
    _error(lambda: loader.read(OPERATOR_ID, "issues"), OperatorSkillErrorCode.NOT_AVAILABLE)
    _error(lambda: loader.read(OPERATOR_ID, "optimization"), OperatorSkillErrorCode.NOT_AVAILABLE)


def test_read_returns_verified_resource() -> None:
    resource = OperatorSkillLoader(versioned_registry()).read(OPERATOR_ID, "examples")
    assert resource.operator_id == OPERATOR_ID
    assert resource.kind == "examples"
    assert resource.sha256 == _digest(resource.text.encode("utf-8"))


@pytest.mark.parametrize(
    "operator_id",
    [
        "nl2sql",
        "nl2sql@2.0",
        "../nl2sql@2.0.0",
        "nl2sql\\x@2.0.0",
        "@2.0.0",
        None,
    ],
)
def test_operator_id_must_be_exact_and_path_safe(operator_id: object) -> None:
    _error(
        lambda: OperatorSkillLoader(versioned_registry()).load(operator_id),  # type: ignore[arg-type]
        OperatorSkillErrorCode.INVALID_OPERATOR_ID,
    )


@pytest.mark.parametrize("operator_id", [".@1.0.0", "..@1.0.0"])
def test_dot_segment_ids_fail_id_validation_before_the_index_is_read(
    tmp_path: Path, operator_id: str
) -> None:
    root = _copy_resources(tmp_path)
    index_path = root / "_index.json"
    index = _load_json(index_path)
    index["packages"][operator_id] = f"{operator_id.replace('@', '/')}/manifest.json"
    _write_json(index_path, index)
    reads: list[str] = []
    loader = OperatorSkillLoader(versioned_registry(), _resource_root=root, _on_read=reads.append)

    _error(lambda: loader.describe(operator_id), OperatorSkillErrorCode.INVALID_OPERATOR_ID)
    _error(lambda: loader.load(operator_id), OperatorSkillErrorCode.INVALID_OPERATOR_ID)
    _error(lambda: loader.read(operator_id, "guide"), OperatorSkillErrorCode.INVALID_OPERATOR_ID)
    assert reads == []


def test_custom_registration_cannot_claim_package_resources(tmp_path: Path) -> None:
    registry = OperatorRegistry()
    registry.register(NL2SQLOperator(), "2.0.0")
    root = _copy_resources(tmp_path)
    _error(
        lambda: OperatorSkillLoader(registry, _resource_root=root).load(OPERATOR_ID),
        OperatorSkillErrorCode.TRUST_REQUIRED,
    )


def test_equal_card_from_another_registry_is_not_package_provenance() -> None:
    first = versioned_registry()
    second = versioned_registry()
    assert first.get_card(OPERATOR_ID) == second.get_card(OPERATOR_ID)
    assert first.get_card(OPERATOR_ID) is not second.get_card(OPERATOR_ID)
    assert OperatorSkillLoader(first).load(OPERATOR_ID).card is first.get_card(OPERATOR_ID)


INDEX_MUTATIONS: list[Callable[[dict[str, Any]], None]] = [
    lambda value: value.update(extra=True),
    lambda value: value.update(format="wrong"),
    lambda value: value.update(packages=[]),
    lambda value: value["packages"].update({"bad": "bad/1.0.0/manifest.json"}),
    lambda value: value["packages"].update({"other@1.0.0": "nl2sql/2.0.0/manifest.json"}),
    lambda value: value["packages"].update({OPERATOR_ID: "../manifest.json"}),
    lambda value: value["packages"].update({"..@1.0.0": "../1.0.0/manifest.json"}),
    lambda value: value["packages"].update({".@1.0.0": "./1.0.0/manifest.json"}),
]


@pytest.mark.parametrize("mutation", INDEX_MUTATIONS)
def test_index_uses_a_closed_exact_path_map(
    tmp_path: Path, mutation: Callable[[dict[str, Any]], None]
) -> None:
    root = _copy_resources(tmp_path)
    path = root / "_index.json"
    value = _load_json(path)
    mutation(value)
    _write_json(path, value)
    _error(
        lambda: OperatorSkillLoader(versioned_registry(), _resource_root=root).load(OPERATOR_ID),
        OperatorSkillErrorCode.MANIFEST_INVALID,
    )


def test_duplicate_json_keys_are_rejected(tmp_path: Path) -> None:
    root = _copy_resources(tmp_path)
    (root / "_index.json").write_text(
        '{"format":"blue-data-ops/operator-skill-index@1","format":"wrong","packages":{}}',
        encoding="utf-8",
    )
    _error(
        lambda: OperatorSkillLoader(versioned_registry(), _resource_root=root).load(OPERATOR_ID),
        OperatorSkillErrorCode.MANIFEST_INVALID,
    )


MANIFEST_MUTATIONS: list[tuple[Callable[[dict[str, Any]], None], OperatorSkillErrorCode]] = [
    (lambda value: value.update(extra=True), OperatorSkillErrorCode.MANIFEST_INVALID),
    (lambda value: value.update(format="wrong"), OperatorSkillErrorCode.MANIFEST_INVALID),
    (
        lambda value: value.update(operator_id="nl2sql@1.0.0"),
        OperatorSkillErrorCode.BINDING_MISMATCH,
    ),
    (lambda value: value.update(resources=[]), OperatorSkillErrorCode.MANIFEST_INVALID),
    (
        lambda value: value["resources"].pop("guide"),
        OperatorSkillErrorCode.MANIFEST_INVALID,
    ),
    (
        lambda value: value["resources"].update(
            {"unknown": {"path": "unknown.md", "sha256": "0" * 64}}
        ),
        OperatorSkillErrorCode.MANIFEST_INVALID,
    ),
    (
        lambda value: value["resources"]["guide"].update(path="../Operator.md"),
        OperatorSkillErrorCode.MANIFEST_INVALID,
    ),
    (
        lambda value: value["resources"]["guide"].update(sha256="wrong"),
        OperatorSkillErrorCode.MANIFEST_INVALID,
    ),
]


@pytest.mark.parametrize("mutation,code", MANIFEST_MUTATIONS)
def test_manifest_has_a_closed_schema(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], None],
    code: OperatorSkillErrorCode,
) -> None:
    root = _copy_resources(tmp_path)
    path = _manifest(root)
    value = _load_json(path)
    mutation(value)
    _write_json(path, value)
    _error(
        lambda: OperatorSkillLoader(versioned_registry(), _resource_root=root).load(OPERATOR_ID),
        code,
    )


def test_index_and_manifest_decoder_recursion_is_contained(tmp_path: Path) -> None:
    root = _copy_resources(tmp_path)
    nested = "[" * 1_200 + "0" + "]" * 1_200
    (root / "_index.json").write_text(
        '{"format":"blue-data-ops/operator-skill-index@1","packages":' + nested + "}",
        encoding="utf-8",
    )
    _error(
        lambda: OperatorSkillLoader(versioned_registry(), _resource_root=root).load(OPERATOR_ID),
        OperatorSkillErrorCode.MANIFEST_INVALID,
    )

    root = _copy_resources(tmp_path / "manifest")
    _manifest(root).write_text(nested, encoding="utf-8")
    _error(
        lambda: OperatorSkillLoader(versioned_registry(), _resource_root=root).load(OPERATOR_ID),
        OperatorSkillErrorCode.MANIFEST_INVALID,
    )


def test_structural_depth_and_byte_bounds_are_contained(tmp_path: Path) -> None:
    root = _copy_resources(tmp_path)
    index = _load_json(root / "_index.json")
    index["nested"] = {"a": {"b": {"c": {"d": "too deep"}}}}
    _write_json(root / "_index.json", index)
    _error(
        lambda: OperatorSkillLoader(versioned_registry(), _resource_root=root).load(OPERATOR_ID),
        OperatorSkillErrorCode.MANIFEST_INVALID,
    )

    root = _copy_resources(tmp_path / "bytes")
    (root / "_index.json").write_bytes(b" " * (INDEX_BYTE_LIMIT + 1))
    _error(
        lambda: OperatorSkillLoader(versioned_registry(), _resource_root=root).load(OPERATOR_ID),
        OperatorSkillErrorCode.MANIFEST_INVALID,
    )


def test_digest_utf8_and_resource_byte_failures_are_contained(tmp_path: Path) -> None:
    for suffix, content, digest in (
        ("digest", b"changed", "0" * 64),
        ("utf8", b"\xff", _digest(b"\xff")),
        ("bytes", b"x" * (RESOURCE_BYTE_LIMIT + 1), None),
    ):
        root = _copy_resources(tmp_path / suffix)
        resource = root / "nl2sql" / "2.0.0" / "examples.md"
        resource.write_bytes(content)
        manifest = _load_json(_manifest(root))
        manifest["resources"]["examples"]["sha256"] = digest or _digest(content)
        _write_json(_manifest(root), manifest)
        _error(
            lambda root=root: OperatorSkillLoader(versioned_registry(), _resource_root=root).read(
                OPERATOR_ID, "examples"
            ),
            OperatorSkillErrorCode.RESOURCE_INVALID,
        )


def test_live_schema_failure_is_contained() -> None:
    registry = versioned_registry()
    registry.resolve(OPERATOR_ID).properties["attributes"]["question"]["required"] = "yes"
    _error(
        lambda: OperatorSkillLoader(registry).load(OPERATOR_ID),
        OperatorSkillErrorCode.SCHEMA_INVALID,
    )


def test_missing_or_zip_style_resource_root_is_not_available(tmp_path: Path) -> None:
    missing = tmp_path / "package.zip" / "blue_data_ops" / "operator_skills"
    _error(
        lambda: OperatorSkillLoader(versioned_registry(), _resource_root=missing).load(OPERATOR_ID),
        OperatorSkillErrorCode.NOT_AVAILABLE,
    )


def test_resource_root_and_each_selected_descendant_reject_symlinks(tmp_path: Path) -> None:
    real_root = _copy_resources(tmp_path / "root")
    alias = tmp_path / "root-alias"
    alias.symlink_to(real_root, target_is_directory=True)
    _error(
        lambda: OperatorSkillLoader(versioned_registry(), _resource_root=alias).load(OPERATOR_ID),
        OperatorSkillErrorCode.RESOURCE_INVALID,
    )

    root = _copy_resources(tmp_path / "ancestor")
    package = root / "nl2sql"
    target = root / "relocated"
    package.rename(target)
    package.symlink_to(target.name, target_is_directory=True)
    _error(
        lambda: OperatorSkillLoader(versioned_registry(), _resource_root=root).load(OPERATOR_ID),
        OperatorSkillErrorCode.RESOURCE_INVALID,
    )

    root = _copy_resources(tmp_path / "file")
    resource = root / "nl2sql" / "2.0.0" / "examples.md"
    target = resource.with_name("examples-target.md")
    resource.rename(target)
    resource.symlink_to(target.name)
    _error(
        lambda: OperatorSkillLoader(versioned_registry(), _resource_root=root).read(
            OPERATOR_ID, "examples"
        ),
        OperatorSkillErrorCode.RESOURCE_INVALID,
    )
