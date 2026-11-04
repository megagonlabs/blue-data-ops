from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

import blue_data_ops.operator_skills as operator_skills
from blue_data_ops.operator_skills import (
    INDEX_BYTE_LIMIT,
    JSON_DEPTH_LIMIT,
    MANIFEST_BYTE_LIMIT,
    RESOURCE_BYTE_LIMIT,
    OperatorSkillErrorCode,
    OperatorSkillLoader,
    OperatorSkillLoadError,
)
from blue_data_ops.operators import OperatorRegistry, active_registry, versioned_registry
from blue_data_ops.operators.types import AttributeSpec

from ._conformance_support import (
    INDEX_FORMAT,
    MANIFEST_FORMAT,
    RESOURCE_FILES,
    CatalogSnapshot,
    inspect_catalog,
)
from ._settings_conformance import (
    ADDED_SKILL_PACKAGE_IDS,
    EffectiveReadCensus,
    assert_guide_matches_operator,
    assert_skill_package_inventory,
    effective_read_census,
    expected_skill_package_ids,
    expected_v2_skill_package_ids,
    parse_settings,
    render_expected_settings,
    runtime_metadata_reads,
)

PACKAGE_ROOT = Path(operator_skills.__file__).parent
EXPECTED_PACKAGE_IDS = expected_skill_package_ids(versioned_registry())
EXPECTED_PACKAGE_COUNT = len(EXPECTED_PACKAGE_IDS)
CATALOG = inspect_catalog(
    PACKAGE_ROOT,
    minimum_packages=1,
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
    assert_skill_package_inventory(observed.package_ids, versioned_registry())
    assert all(
        set(package.resources) == {"guide", "examples"} for package in observed.packages.values()
    )


def test_guide_settings_match_live_schema_and_effective_reads_across_the_catalog() -> None:
    registry = versioned_registry()
    loader = OperatorSkillLoader(registry)
    visited: set[str] = set()
    checked_summaries = 0

    for operator_id in CATALOG.package_ids:
        skill = loader.load(operator_id, level=2)
        guide = skill.guide or ""
        assert_guide_matches_operator(guide, registry.resolve(operator_id))
        checked_summaries += len(_attribute_summary_paragraphs(guide))
        assert _attribute_summary_issues(guide, set(skill.io.attributes)) == ()
        visited.add(operator_id)

    assert visited == set(EXPECTED_PACKAGE_IDS) == set(CATALOG.package_ids)
    assert checked_summaries > 0


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


class _SyntheticOperator:
    attributes = {
        "declared": AttributeSpec(type="str"),
        "structured_attribute": AttributeSpec(type="list[str]", default=[]),
    }
    DEFAULT_PROPERTIES: dict[str, object] = {
        "discarded": False,
        "output_cast": "json",
        "output_strip": True,
        "overwritten": "default",
        "service_prefix": "openai",
        "structured_property": [],
    }


_SYNTHETIC_SOURCE = """
def execute(self, attributes, properties):
    self.properties["attributes"]
    self.properties.get("attribute_cache")
    attributes.get("declared")
    attributes.get("compatibility")
    merged = {**self.DEFAULT_PROPERTIES, **(properties or {})}
    properties.get("scalar", 1)
    if "flag" in properties:
        pass
    merged.update(
        {
            "overwritten": attributes.get("declared"),
            "discarded": attributes.get("declared"),
        }
    )
    merged.get("overwritten")
    result = {"copied": properties.get("scalar")}
    result.get("result_only")
    payload = build_message({}, properties)
    payload.get("provider_only")
    resolve_registry(properties)
    resolve_llm_client(merged)
"""

_HELPER_SOURCES = {
    "resolve_registry": """
def resolve_registry(properties):
    properties.get("data_registry")
    properties.get("data_registry.name")
    properties.get("platform.name")
""",
    "resolve_llm_client": """
_ACCEPTED_LLM_KEYS = {
    "cache", "cache_dir", "max_parallel", "max_tokens", "model", "rate_limit", "stream",
    "temperature", "reasoning_effort"
}
def resolve_llm_client(properties):
    properties.get("llm_client")
    properties.get("service_prefix")
    properties.get("output_template")
    if "output_cast" in properties:
        properties["output_cast"]
    if "output_strip" in properties:
        pass
""",
}


def _guide_for(census: EffectiveReadCensus) -> str:
    lines = [
        "# Synthetic",
        "",
        "## Settings",
        "",
        "| Name | Input | Declared | Effective default | Validation | Kind |",
        "|---|---|---|---|---|---|",
    ]
    lines.extend(
        f"| {row.name} | {row.input} | {row.declared} | {row.effective_default} | "
        f"{row.validation} | {row.kind} |"
        for row in census.expected
    )
    return "\n".join(lines) + "\n"


def _synthetic_census() -> EffectiveReadCensus:
    return effective_read_census(
        _SyntheticOperator(), source=_SYNTHETIC_SOURCE, helper_sources=_HELPER_SOURCES
    )


def test_expected_membership_matches_the_exact_version_inventory() -> None:
    assert_skill_package_inventory(CATALOG.package_ids, versioned_registry())
    assert len(EXPECTED_PACKAGE_IDS) == EXPECTED_PACKAGE_COUNT == 55


def test_historical_package_membership_matches_all_retained_v2_cards() -> None:
    expected = expected_v2_skill_package_ids(versioned_registry())
    assert len(expected) == 33
    assert "multipart_query@2.0.0" not in expected
    assert all(operator_id.endswith("@2.0.0") for operator_id in expected)
    assert tuple(operator_id for operator_id in CATALOG.package_ids if operator_id in expected) == (
        expected
    )
    assert tuple(
        operator_id for operator_id in EXPECTED_PACKAGE_IDS if operator_id in expected
    ) == (expected)
    assert set(EXPECTED_PACKAGE_IDS) - set(expected) == set(ADDED_SKILL_PACKAGE_IDS)


def test_every_active_card_has_one_exact_skill_package() -> None:
    registry = active_registry()
    active_ids = tuple(card.operator_id for card in registry.list_cards())
    loader = OperatorSkillLoader(registry)

    assert len(active_ids) == 33
    assert loader.available_operator_ids() == active_ids
    assert all(
        loader.load(operator_id, level=3).card is registry.get_card(operator_id)
        for operator_id in active_ids
    )


def test_synthetic_inventory_accepts_exactly_the_expected_packages() -> None:
    registry = versioned_registry()
    assert_skill_package_inventory(expected_skill_package_ids(registry), registry)


@pytest.mark.parametrize("missing_id", ("avg@2.0.0", "select@2.0.0", *ADDED_SKILL_PACKAGE_IDS))
def test_synthetic_inventory_rejects_missing_old_or_new_packages(missing_id: str) -> None:
    registry = versioned_registry()
    actual = tuple(oid for oid in expected_skill_package_ids(registry) if oid != missing_id)
    with pytest.raises(AssertionError, match="skill package inventory differs"):
        assert_skill_package_inventory(actual, registry)


@pytest.mark.parametrize("unexpected_id", ("avg@3.0.1", "select@3.0.0", "ghost@2.0.0"))
@pytest.mark.parametrize("replace_id", (None, "avg@2.0.0", "avg@3.0.0"))
def test_synthetic_inventory_rejects_extra_or_replacement_packages(
    unexpected_id: str, replace_id: str | None
) -> None:
    registry = versioned_registry()
    expected = expected_skill_package_ids(registry)
    actual = tuple(
        sorted(
            (*[oid for oid in expected if oid != replace_id], unexpected_id),
            key=lambda item: item.encode("utf-8"),
        )
    )
    if replace_id is not None:
        assert len(actual) == len(expected) == 55
    with pytest.raises(AssertionError, match="skill package inventory differs"):
        assert_skill_package_inventory(actual, registry)


def test_census_covers_all_layers_and_setting_kinds() -> None:
    census = _synthetic_census()
    assert {row.kind for row in census.expected} == {
        "namespace",
        "presence",
        "scalar",
        "seam",
        "structured",
    }
    assert census.post_merge_reads == ("overwritten",)
    assert census.discarded_post_merge_writes == ("discarded",)
    discarded = next(
        row for row in census.expected if row.name == "discarded" and row.input == "properties"
    )
    assert (discarded.effective_default, discarded.validation) == (
        "discarded",
        "write-and-discard",
    )
    output_strip = next(
        row for row in census.expected if row.name == "output_strip" and row.input == "properties"
    )
    assert output_strip.kind == "presence"
    output_cast = next(
        row for row in census.expected if row.name == "output_cast" and row.input == "properties"
    )
    assert output_cast.kind == "scalar"
    identities = {(row.name, row.input) for row in census.expected}
    assert ("attributes", "properties") not in identities
    assert ("attribute_cache", "properties") not in identities
    assert ("result_only", "properties") not in identities
    assert ("provider_only", "properties") not in identities
    assert census.excluded_runtime_metadata
    assert {evidence.helper for evidence in census.indirect_evidence} == {
        "resolve_llm_client",
        "resolve_registry",
    }
    assert all(
        evidence.call_line > 0 and len(evidence.source_sha256) == 64
        for evidence in census.indirect_evidence
    )


def test_semantic_join_distinguishes_read_back_and_discarded_property_writes() -> None:
    census = effective_read_census(versioned_registry().resolve("semantic_join@2.0.0"))
    assert census.post_merge_reads == (
        "failure_probability",
        "optimize_thresholds",
        "precision_target",
        "recall_target",
        "sampling_percentage",
        "use_embedding_filter",
    )
    assert census.discarded_post_merge_writes == (
        "batch_size",
        "embedding_threshold",
    )
    properties = {row.name: row for row in census.expected if row.input == "properties"}
    for name in census.post_merge_reads:
        assert properties[name].validation.startswith("attribute-overwrites-property:")
    for name in census.discarded_post_merge_writes:
        assert (
            properties[name].effective_default,
            properties[name].validation,
        ) == ("discarded", "write-and-discard")
    assert properties["output_cast"].kind == "scalar"


def test_validation_reads_do_not_change_execution_defaults() -> None:
    source = """
def execute(self, attributes, properties):
    attributes.get("limit", 10)
    properties.get("batch_size", 32)

def _validate_input(self, attributes, properties):
    attributes.get("limit")
    properties.get("batch_size")
"""
    census = effective_read_census(_SyntheticOperator(), source=source, helper_sources={})
    rows = {(row.name, row.input): row for row in census.expected}
    assert rows[("limit", "attributes")].effective_default == "10"
    assert rows[("batch_size", "properties")].effective_default == "32"


def test_validation_provenance_is_scoped_to_one_function() -> None:
    source = """
def execute(self, attributes, properties):
    limit = properties.get("limit")
    return limit

def other(config):
    limit = 5
    isinstance(limit, int)
"""
    census = effective_read_census(_SyntheticOperator(), source=source, helper_sources={})
    row = next(row for row in census.expected if row.name == "limit" and row.input == "properties")
    assert row.validation == "none"


def test_alias_reads_defaults_and_post_merge_writes_are_function_scoped() -> None:
    source = """
def execute(self, attributes, properties):
    merged = {**self.DEFAULT_PROPERTIES, **(properties or {})}
    merged.get("real_setting", 1)

def unrelated(self, attributes, some_other_mapping):
    merged = some_other_mapping
    merged.get("not_a_setting", 99)
    merged.update({"not_a_write": attributes.get("declared")})
"""
    census = effective_read_census(_SyntheticOperator(), source=source, helper_sources={})
    rows = {(row.name, row.input): row for row in census.expected}
    assert rows[("real_setting", "properties")].effective_default == "1"
    assert ("not_a_setting", "properties") not in rows
    assert ("not_a_write", "properties") not in rows
    assert "not_a_write" not in census.discarded_post_merge_writes


def test_async_validation_provenance_matches_synchronous_validation() -> None:
    source = """
async def execute(self, attributes, properties):
    limit = properties.get("async_limit", 3)
    if not isinstance(limit, int):
        raise ValueError("async_limit")
"""
    census = effective_read_census(_SyntheticOperator(), source=source, helper_sources={})
    row = next(
        row for row in census.expected if row.name == "async_limit" and row.input == "properties"
    )
    assert row.effective_default == "3"
    assert row.validation == "runtime-check"


@pytest.mark.parametrize(
    ("validation_prefix", "helper_prefix"),
    (("def", "def"), ("async def", "async def")),
)
def test_nested_validation_helpers_do_not_supply_execution_defaults(
    validation_prefix: str, helper_prefix: str
) -> None:
    source = f"""
def execute(self, attributes, properties):
    properties["probe"]

{validation_prefix} _validate_input(self, attributes, properties):
    {helper_prefix} helper():
        return properties.get("probe", "VALIDATION-ONLY")
    return helper
"""
    census = effective_read_census(_SyntheticOperator(), source=source, helper_sources={})
    row = next(row for row in census.expected if row.name == "probe" and row.input == "properties")
    assert row.effective_default == "none"


def test_runtime_metadata_census_handles_subscript_and_get_without_rendering_rows() -> None:
    assert runtime_metadata_reads(
        """
def inspect(self):
    self.properties["attributes"]
    self.properties.get("attribute_cache")
"""
    ) == ("attribute_cache", "attributes")


def test_vector_search_presence_guard_is_not_reported_as_validation() -> None:
    operator = versioned_registry().resolve("vector_search@2.0.0")
    census = effective_read_census(operator)
    row = next(
        row for row in census.expected if row.name == "min_score" and row.input == "properties"
    )
    assert row.validation == "none"
    guide = _guide_for(census).replace(
        "| min_score | properties | no | none | none | scalar |",
        "| min_score | properties | no | none | runtime-check | scalar |",
    )
    with pytest.raises(AssertionError):
        assert_guide_matches_operator(guide, operator)


def test_synthetic_settings_table_matches_schema_and_effective_reads() -> None:
    census = _synthetic_census()
    guide = _guide_for(census)
    assert parse_settings(guide)
    assert_guide_matches_operator(
        guide,
        _SyntheticOperator(),
        source=_SYNTHETIC_SOURCE,
        helper_sources=_HELPER_SOURCES,
    )


def test_expected_row_dump_uses_the_machine_grammar() -> None:
    rendered = render_expected_settings(_SyntheticOperator())
    assert rendered.startswith(
        "| Name | Input | Declared | Effective default | Validation | Kind |"
    )
    assert parse_settings("# Synthetic\n\n## Settings\n\n" + rendered)


def test_validation_status_accepts_reader_detail_after_the_checked_prefix() -> None:
    census = _synthetic_census()
    guide = _guide_for(census).replace(
        "| declared | attributes | yes | none | attribute-spec:str | scalar |",
        "| declared | attributes | yes | none | attribute-spec:str; non-empty string | scalar |",
    )
    assert_guide_matches_operator(
        guide,
        _SyntheticOperator(),
        source=_SYNTHETIC_SOURCE,
        helper_sources=_HELPER_SOURCES,
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "section-missing",
        "section-duplicate",
        "declared-missing",
        "declared-invented",
        "property-missing",
        "property-invented",
        "input-misclassified",
        "kind-misclassified",
        "helper-presence-misclassified",
        "default-wrong",
        "validation-wrong",
        "machine-cell-backtick",
        "row-duplicate",
        "row-unsorted",
    ),
)
def test_settings_mutations_turn_the_instrument_red(mutation: str) -> None:
    guide = _guide_for(_synthetic_census())
    error_pattern: str | None = None
    if mutation == "section-missing":
        guide = guide.replace("## Settings", "## Configuration")
    elif mutation == "section-duplicate":
        guide += "\n## Settings\n"
    elif mutation == "declared-missing":
        guide = "\n".join(
            line for line in guide.splitlines() if not line.startswith("| declared | attributes |")
        )
    elif mutation == "declared-invented":
        guide = guide.replace(
            "| llm.* | properties:llm.* |",
            "| invented | attributes | yes | none | none | scalar |\n| llm.* | properties:llm.* |",
        )
        error_pattern = "Settings mismatch"
    elif mutation == "property-missing":
        guide = "\n".join(
            line for line in guide.splitlines() if not line.startswith("| scalar | properties |")
        )
    elif mutation == "property-invented":
        guide = guide.replace(
            "| scalar | properties |",
            "| property_extra | properties | no | none | none | scalar |\n| scalar | properties |",
        )
    elif mutation == "input-misclassified":
        guide = guide.replace("| scalar | properties |", "| scalar | attributes |")
    elif mutation == "kind-misclassified":
        guide = guide.replace(
            "| structured_property | properties | no | [] | none | structured |",
            "| structured_property | properties | no | [] | none | scalar |",
        )
    elif mutation == "helper-presence-misclassified":
        guide = guide.replace(
            "| output_strip | properties | no | true | reserved | presence |",
            "| output_strip | properties | no | true | reserved | scalar |",
        )
    elif mutation == "default-wrong":
        guide = guide.replace(
            "| structured_property | properties | no | [] | none | structured |",
            "| structured_property | properties | no | {} | none | structured |",
        )
    elif mutation == "validation-wrong":
        guide = guide.replace(
            "| discarded | properties | no | discarded | write-and-discard |",
            "| discarded | properties | no | discarded | none |",
        )
    elif mutation == "machine-cell-backtick":
        guide = guide.replace("| declared | attributes |", "| de`clared | attributes |")
    elif mutation == "row-duplicate":
        row = "| declared | attributes | yes | none | attribute-spec:str | scalar |"
        guide = guide.replace(row, row + "\n" + row)
        error_pattern = "duplicate Settings row"
    elif mutation == "row-unsorted":
        first = "| declared | attributes | yes | none | attribute-spec:str | scalar |"
        second = "| discarded | properties | no | discarded | write-and-discard | scalar |"
        guide = guide.replace(first + "\n" + second, second + "\n" + first)
        error_pattern = "not UTF-8-byte-sorted"
    else:
        raise AssertionError(f"unknown mutation: {mutation}")

    with pytest.raises(AssertionError, match=error_pattern):
        assert_guide_matches_operator(
            guide,
            _SyntheticOperator(),
            source=_SYNTHETIC_SOURCE,
            helper_sources=_HELPER_SOURCES,
        )


@pytest.mark.parametrize(
    ("helper", "key"),
    (
        ("resolve_registry", "data_registry.name"),
        ("resolve_llm_client", "service_prefix"),
        ("resolve_llm_client", "output_template"),
        ("resolve_llm_client", "_ACCEPTED_LLM_KEYS"),
    ),
)
def test_stale_indirect_and_wildcard_evidence_turns_the_census_red(helper: str, key: str) -> None:
    helper_sources = dict(_HELPER_SOURCES)
    helper_sources[helper] = helper_sources[helper].replace(key, "removed")
    with pytest.raises(AssertionError, match="stale"):
        effective_read_census(
            _SyntheticOperator(),
            source=_SYNTHETIC_SOURCE,
            helper_sources=helper_sources,
        )


def test_an_unmodelled_exact_helper_read_turns_the_census_red() -> None:
    helper_sources = dict(_HELPER_SOURCES)
    helper_sources["resolve_llm_client"] += '\nproperties.get("unmodelled_helper_setting")\n'
    with pytest.raises(AssertionError, match="uncovered"):
        effective_read_census(
            _SyntheticOperator(),
            source=_SYNTHETIC_SOURCE,
            helper_sources=helper_sources,
        )


@pytest.mark.parametrize(
    "replacement",
    (
        '{"model", "temperature", "seed"}',
        '{"unrelated"}',
    ),
)
def test_changed_reviewed_llm_key_set_turns_the_census_red(replacement: str) -> None:
    helper_sources = dict(_HELPER_SOURCES)
    start = helper_sources["resolve_llm_client"].index("_ACCEPTED_LLM_KEYS =")
    function = helper_sources["resolve_llm_client"].index("\ndef resolve_llm_client")
    helper_sources["resolve_llm_client"] = (
        helper_sources["resolve_llm_client"][:start]
        + "_ACCEPTED_LLM_KEYS = "
        + replacement
        + helper_sources["resolve_llm_client"][function:]
    )
    with pytest.raises(AssertionError, match="stale llm.* key-set evidence"):
        effective_read_census(
            _SyntheticOperator(),
            source=_SYNTHETIC_SOURCE,
            helper_sources=helper_sources,
        )


def test_code_formatted_machine_cells_and_inline_code_in_free_text_are_parsed() -> None:
    guide = """# Synthetic

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `value` | `attributes` | `yes` | `none` | accepts `str` values | `scalar` |
"""
    assert parse_settings(guide)[0].validation == "accepts `str` values"
