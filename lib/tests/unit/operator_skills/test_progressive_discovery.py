from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from blue_data_ops.operator_skills import (
    INDEX_BYTE_LIMIT,
    OperatorSkillDescriptor,
    OperatorSkillErrorCode,
    OperatorSkillLoader,
    OperatorSkillLoadError,
)
from blue_data_ops.operators import (
    NL2SQLOperator,
    OperatorRegistry,
    default_registry,
    versioned_registry,
)
from blue_data_ops.operators.registry import is_builtin_card

from ._settings_conformance import expected_skill_package_ids

RESOURCE_ROOT = Path(__file__).parents[3] / "src" / "blue_data_ops" / "operator_skills"
OPERATOR_ID = "nl2sql@2.0.0"


def _copy_resources(tmp_path: Path) -> Path:
    root = tmp_path / "operator_skills"
    shutil.copytree(RESOURCE_ROOT, root, ignore=shutil.ignore_patterns("*.py", "__pycache__"))
    return root


def _load_json(path: Path) -> dict[str, Any]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    assert type(value) is dict
    return cast(dict[str, Any], value)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _error(call: Callable[[], object], code: OperatorSkillErrorCode) -> None:
    with pytest.raises(OperatorSkillLoadError) as raised:
        call()
    assert raised.value.code is code


def test_available_ids_are_the_registry_ordered_eligible_intersection() -> None:
    registry = versioned_registry()
    actual = OperatorSkillLoader(registry).available_operator_ids()
    expected_set = set(expected_skill_package_ids(registry))

    assert set(actual) == expected_set
    assert actual == tuple(
        card.operator_id for card in registry.list_cards() if card.operator_id in expected_set
    )


def test_default_registry_has_no_eligible_skill_packages() -> None:
    assert OperatorSkillLoader(default_registry()).available_operator_ids() == ()


def test_public_registration_cannot_claim_indexed_resources(tmp_path: Path) -> None:
    registry = OperatorRegistry()
    registry.register(NL2SQLOperator(), "2.0.0")
    loader = OperatorSkillLoader(registry, _resource_root=_copy_resources(tmp_path))

    assert loader.available_operator_ids() == ()
    _error(lambda: loader.describe(OPERATOR_ID), OperatorSkillErrorCode.TRUST_REQUIRED)


def test_descriptors_retain_each_registrys_own_card_identity() -> None:
    first = versioned_registry()
    second = versioned_registry()

    assert (
        OperatorSkillLoader(first).available_operator_ids()
        == OperatorSkillLoader(second).available_operator_ids()
    )
    assert OperatorSkillLoader(first).describe(OPERATOR_ID).card is first.get_card(OPERATOR_ID)
    assert OperatorSkillLoader(second).describe(OPERATOR_ID).card is second.get_card(OPERATOR_ID)
    assert not is_builtin_card(first, second.get_card(OPERATOR_ID))


class _RegistrySubclass(OperatorRegistry):
    pass


@pytest.mark.parametrize("registry", [_RegistrySubclass(), object()])
def test_available_ids_refuse_nonexact_registries_before_any_read(registry: object) -> None:
    reads: list[str] = []
    loader = OperatorSkillLoader(cast(OperatorRegistry, registry), _on_read=reads.append)

    _error(loader.available_operator_ids, OperatorSkillErrorCode.TRUST_REQUIRED)
    assert reads == []


def test_describe_reports_declared_metadata_for_every_shipped_package() -> None:
    registry = versioned_registry()
    loader = OperatorSkillLoader(registry)

    for operator_id in loader.available_operator_ids():
        descriptor = loader.describe(operator_id)
        assert type(descriptor) is OperatorSkillDescriptor
        assert descriptor.card is registry.get_card(operator_id)
        assert descriptor.declared_kinds == ("guide", "examples")
        assert descriptor.declared_levels == (2, 3)


def test_describe_reads_only_the_index_and_selected_manifest() -> None:
    reads: list[str] = []
    descriptor = OperatorSkillLoader(versioned_registry(), _on_read=reads.append).describe(
        OPERATOR_ID
    )

    assert descriptor.card.operator_id == OPERATOR_ID
    assert reads == ["_index.json", "nl2sql/2.0.0/manifest.json"]


def test_availability_then_description_repeats_the_uncached_index_read() -> None:
    reads: list[str] = []
    loader = OperatorSkillLoader(versioned_registry(), _on_read=reads.append)

    assert OPERATOR_ID in loader.available_operator_ids()
    loader.describe(OPERATOR_ID)

    assert reads == [
        "_index.json",
        "_index.json",
        "nl2sql/2.0.0/manifest.json",
    ]


def test_availability_does_not_promise_manifest_validity(tmp_path: Path) -> None:
    root = _copy_resources(tmp_path)
    manifest = root / "nl2sql" / "2.0.0" / "manifest.json"
    manifest.write_text("{", encoding="utf-8")
    loader = OperatorSkillLoader(versioned_registry(), _resource_root=root)

    assert OPERATOR_ID in loader.available_operator_ids()
    _error(lambda: loader.describe(OPERATOR_ID), OperatorSkillErrorCode.MANIFEST_INVALID)


def test_description_does_not_promise_resource_integrity(tmp_path: Path) -> None:
    root = _copy_resources(tmp_path)
    (root / "nl2sql" / "2.0.0" / "examples.md").write_text("digest mismatch", encoding="utf-8")
    loader = OperatorSkillLoader(versioned_registry(), _resource_root=root)

    assert 3 in loader.describe(OPERATOR_ID).declared_levels
    _error(lambda: loader.load(OPERATOR_ID, level=3), OperatorSkillErrorCode.RESOURCE_INVALID)


def test_description_does_not_promise_a_valid_live_schema() -> None:
    registry = versioned_registry()
    registry.resolve(OPERATOR_ID).properties["attributes"]["question"]["required"] = "yes"
    loader = OperatorSkillLoader(registry)

    assert loader.describe(OPERATOR_ID).card is registry.get_card(OPERATOR_ID)
    _error(lambda: loader.load(OPERATOR_ID), OperatorSkillErrorCode.SCHEMA_INVALID)


def test_description_rechecks_live_binding_before_reading_metadata() -> None:
    registry = versioned_registry()
    card = registry.get_card(OPERATOR_ID)
    assert card is not None
    object.__setattr__(card, "name", "changed")

    _error(
        lambda: OperatorSkillLoader(registry).describe(OPERATOR_ID),
        OperatorSkillErrorCode.BINDING_MISMATCH,
    )


def test_describe_binding_failure_precedes_a_corrupt_index(tmp_path: Path) -> None:
    root = _copy_resources(tmp_path)
    (root / "_index.json").write_text("{", encoding="utf-8")
    reads: list[str] = []
    loader = OperatorSkillLoader(versioned_registry(), _resource_root=root, _on_read=reads.append)

    _error(
        lambda: loader.describe("missing@2.0.0"),
        OperatorSkillErrorCode.BINDING_MISMATCH,
    )
    assert reads == []
    _error(loader.available_operator_ids, OperatorSkillErrorCode.MANIFEST_INVALID)
    assert reads == ["_index.json"]


def test_whole_index_validation_rejects_an_unrelated_bad_entry(tmp_path: Path) -> None:
    root = _copy_resources(tmp_path)
    index_path = root / "_index.json"
    index = _load_json(index_path)
    index["packages"]["unrelated@1.0.0"] = "wrong/path/manifest.json"
    _write_json(index_path, index)
    loader = OperatorSkillLoader(versioned_registry(), _resource_root=root)

    _error(loader.available_operator_ids, OperatorSkillErrorCode.MANIFEST_INVALID)
    _error(lambda: loader.describe(OPERATOR_ID), OperatorSkillErrorCode.MANIFEST_INVALID)


def test_existing_argument_checks_still_precede_index_reads(tmp_path: Path) -> None:
    root = _copy_resources(tmp_path)
    (root / "_index.json").write_text("{", encoding="utf-8")
    reads: list[str] = []
    loader = OperatorSkillLoader(versioned_registry(), _resource_root=root, _on_read=reads.append)

    _error(lambda: loader.load(OPERATOR_ID, level=1), OperatorSkillErrorCode.NOT_AVAILABLE)
    _error(lambda: loader.read(OPERATOR_ID, "unknown"), OperatorSkillErrorCode.RESOURCE_INVALID)
    assert reads == []


def _write_oversized_index(path: Path) -> None:
    path.write_bytes(b" " * (INDEX_BYTE_LIMIT + 1))


def _write_too_deep_index(path: Path) -> None:
    path.write_text(
        '{"format":"blue-data-ops/operator-skill-index@1","packages":'
        + "[" * 1_200
        + "0"
        + "]" * 1_200
        + "}",
        encoding="utf-8",
    )


def _write_duplicate_index_key(path: Path) -> None:
    path.write_text(
        '{"format":"blue-data-ops/operator-skill-index@1","format":"wrong","packages":{}}',
        encoding="utf-8",
    )


INDEX_FAILURES: tuple[Callable[[Path], None], ...] = (
    _write_oversized_index,
    _write_too_deep_index,
    _write_duplicate_index_key,
)


@pytest.mark.parametrize("mutation", INDEX_FAILURES)
def test_index_limits_are_shared_by_availability_and_description(
    tmp_path: Path, mutation: Callable[[Path], None]
) -> None:
    root = _copy_resources(tmp_path)
    mutation(root / "_index.json")
    loader = OperatorSkillLoader(versioned_registry(), _resource_root=root)

    _error(loader.available_operator_ids, OperatorSkillErrorCode.MANIFEST_INVALID)
    _error(lambda: loader.describe(OPERATOR_ID), OperatorSkillErrorCode.MANIFEST_INVALID)


def _symlinked_root(tmp_path: Path) -> Path:
    target = _copy_resources(tmp_path)
    alias = tmp_path / "operator-skills-alias"
    alias.symlink_to(target, target_is_directory=True)
    return alias


def _missing_root(tmp_path: Path) -> Path:
    return tmp_path / "missing" / "operator_skills"


ROOT_FAILURES: tuple[tuple[Callable[[Path], Path], OperatorSkillErrorCode], ...] = (
    (_symlinked_root, OperatorSkillErrorCode.RESOURCE_INVALID),
    (_missing_root, OperatorSkillErrorCode.NOT_AVAILABLE),
)


@pytest.mark.parametrize("root_factory,expected", ROOT_FAILURES)
def test_all_loader_entry_points_share_root_failure_mapping(
    tmp_path: Path,
    root_factory: Callable[[Path], Path],
    expected: OperatorSkillErrorCode,
) -> None:
    loader = OperatorSkillLoader(versioned_registry(), _resource_root=root_factory(tmp_path))

    _error(loader.available_operator_ids, expected)
    _error(lambda: loader.describe(OPERATOR_ID), expected)
    _error(lambda: loader.load(OPERATOR_ID), expected)
    _error(lambda: loader.read(OPERATOR_ID, "guide"), expected)
