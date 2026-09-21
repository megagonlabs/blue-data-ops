from __future__ import annotations

import copy
import hashlib
import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

from blue_data_ops.operators import active_registry

LIB_ROOT = Path(__file__).resolve().parents[2]


def _generator() -> ModuleType:
    path = LIB_ROOT / "scripts" / "generate_operator_reference.py"
    spec = spec_from_file_location("generate_operator_reference", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reseal(generator: ModuleType, document: dict[str, Any]) -> dict[str, Any]:
    document["projection_seal_sha256"] = generator._document_seal(document)
    return document


def _document(generator: ModuleType) -> dict[str, Any]:
    return copy.deepcopy(generator._load_evidence())


def _sections(generated: str) -> tuple[str, ...]:
    return tuple(
        line.removeprefix("## `").removesuffix("`")
        for line in generated.splitlines()
        if line.startswith("## `") and line.endswith("`")
    )


def _supported_case_ids(document: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        claim["case_id"]
        for row in document["rows"]
        for claim in row["claims"].values()
        if claim["status"] == "supported"
    )


def _assert_no_source_case_ids(rendered: str, case_ids: tuple[str, ...]) -> None:
    leaked = tuple(case_id for case_id in case_ids if case_id in rendered)
    assert not leaked, f"source case IDs leaked: {leaked!r}"


def test_source_manifest_includes_the_sdist_only_generator_inputs() -> None:
    generator = _generator()
    directives = [
        tuple(line.strip().split(maxsplit=1))
        for line in (LIB_ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    for evidence_path in (
        cast(Path, generator.EVIDENCE_PATH),
        cast(Path, generator.SUPPLEMENTAL_EVIDENCE_PATH),
    ):
        fixture_path = evidence_path.relative_to(LIB_ROOT).as_posix()
        assert ("include", fixture_path) in directives
        assert not evidence_path.is_relative_to(LIB_ROOT / "src")


def test_generator_input_is_the_sealed_release_projection() -> None:
    generator = _generator()
    raw = cast(Path, generator.EVIDENCE_PATH).read_bytes()

    assert hashlib.sha256(raw).hexdigest() == generator.ACCEPTED_PROJECTION_SHA256
    document = json.loads(raw)
    assert document["source_instrument"] == generator.SOURCE_INSTRUMENT
    assert document["active_ids"] == list(generator.CORE_ACTIVE_IDS)
    assert "processor" not in document
    assert "artifacts" not in document
    assert "historical_inputs" not in document


def test_sklearn_supplement_is_sealed_separately() -> None:
    generator = _generator()
    path = cast(Path, generator.SUPPLEMENTAL_EVIDENCE_PATH)
    raw = path.read_bytes()
    source_path = LIB_ROOT / "tests" / "unit" / "operators" / "test_sklearn.py"

    assert hashlib.sha256(raw).hexdigest() == generator.SUPPLEMENTAL_ACCEPTED_PROJECTION_SHA256
    document = json.loads(raw)
    assert document["source_instrument"] == generator.SUPPLEMENTAL_SOURCE_INSTRUMENT
    assert (
        hashlib.sha256(source_path.read_bytes()).hexdigest()
        == generator.SUPPLEMENTAL_SOURCE_INSTRUMENT["document_sha256"]
    )
    assert document["active_ids"] == list(generator.SUPPLEMENTAL_ACTIVE_IDS)
    assert generator._document_seal(document) == document["projection_seal_sha256"]


def test_operator_reference_matches_the_active_registry_and_evidence() -> None:
    generator = _generator()
    generated = generator.render_reference()

    assert (LIB_ROOT / "OPERATORS.md").read_text(encoding="utf-8") == generated
    assert _sections(generated) == generator.EXPECTED_ACTIVE_IDS
    assert "registry = active_registry()" in generated
    assert "versioned_registry" not in generated
    assert "llm_refine" not in generated
    assert "**Deprecated in 2.8.0" not in generated
    assert "multipart_query" not in generated
    assert "plan_discover" not in generated
    assert "query_breakdown" not in generated
    assert "nl2query_router" not in generated


def test_every_reference_section_binds_live_implementation_and_evidence() -> None:
    generator = _generator()
    rows = generator._load_combined_rows()
    bound = generator._validate_registry(active_registry(), rows)

    assert tuple(card.operator_id for card, _, _ in bound) == generator.EXPECTED_ACTIVE_IDS
    generated = generator.render_reference()
    for card, operator, row in bound:
        section = generated.split(f"## `{card.operator_id}`", 1)[1].split("\n## `", 1)[0]
        assert type(operator).__module__ == row["implementation"]["module"]
        assert type(operator).__name__ == row["implementation"]["symbol"]
        for kind, claim in row["claims"].items():
            source_text = claim.get("summary") or claim["reason"]
            rendered_text = generator._claim_text(card.operator_id, kind, claim)
            if rendered_text is None:
                assert source_text not in section
            else:
                assert rendered_text in section


def test_reference_applies_reader_facing_overrides() -> None:
    generator = _generator()
    rows = generator._load_combined_rows()
    generated = generator.render_reference()
    rewritten_claims: set[tuple[str, str]] = set()

    for row in rows:
        operator_id = row["operator_id"]
        for kind, claim in row["claims"].items():
            source_text = claim.get("summary") or claim["reason"]
            rendered_text = generator._claim_text(operator_id, kind, claim)
            if rendered_text is None:
                assert source_text not in generated
            elif source_text not in rendered_text:
                rewritten_claims.add((operator_id, kind))
                assert source_text not in generated

    assert rewritten_claims == set(generator.CLAIM_TEXT_OVERRIDES)


def test_reference_omits_internal_source_case_ids_with_firing_control() -> None:
    generator = _generator()
    documents = (
        _document(generator),
        generator._load_evidence(
            generator.SUPPLEMENTAL_EVIDENCE_PATH,
            expected_sha256=generator.SUPPLEMENTAL_ACCEPTED_PROJECTION_SHA256,
        ),
    )
    case_ids = tuple(case_id for document in documents for case_id in _supported_case_ids(document))
    rendered = generator.render_reference()

    assert case_ids
    _assert_no_source_case_ids(rendered, case_ids)
    with pytest.raises(AssertionError, match="source case IDs leaked"):
        _assert_no_source_case_ids(f"{rendered}\n{case_ids[0]}\n", case_ids)


def test_the_tag_taxonomy_contains_only_active_card_values() -> None:
    generator = _generator()
    generated = generator.render_reference()
    cards = active_registry().list_cards()
    active_tags = {tag for card in cards for tag in card.tags}

    for axis in ("capability", "domain", "flow", "accepts", "produces", "requires"):
        assert f"| `{axis}-*` |" in generated
    for retired_tag in (
        "capability-query-routing",
        "flow-plan",
        "produces-plan",
        "requires-planner",
    ):
        assert retired_tag not in active_tags
        assert retired_tag not in generated

    rows = [line for line in generated.splitlines() if line.startswith("| `")]
    assert [row.split("`", 2)[1] for row in rows[:6]] == [
        "domain-*",
        "flow-*",
        "accepts-*",
        "produces-*",
        "capability-*",
        "requires-*",
    ]
    assert "| `domain-*` | primary subject area, not the output type | exactly one |" in generated
    assert (
        "| `requires-*` | unconditional operator-specific runtime requirement | zero or more |"
        in generated
    )
    assert "Values are flat exact labels, not a hierarchy." in generated
    assert "callers still pass `input_data`" in generated
    assert "Malformed filters" in generated
    assert "nonempty, contains no whitespace, and" in generated
    assert "includes at least one hyphen" in generated
    assert "does not check taxonomy membership" in generated
    assert "The filters `domain-`" in generated
    assert "`-vector`, and `domain_-vector` are well-formed" in generated
    assert "absent tags match no cards." in generated
    assert "use `capability-metadata-search` or" in generated
    assert "It returns metadata, not a plan." in generated
    assert "a custom tag is discoverable only when" in generated
    assert "its stored value equals the normalized filter" in generated
    assert 'tags=["domain-vector", "flow-transform"]' in generated
    assert '== ["select@2.0.0"]' in generated


def test_missing_generator_input_fails() -> None:
    generator = _generator()
    missing = LIB_ROOT / "tests" / "fixtures" / "missing-active-reference.json"
    with pytest.raises(FileNotFoundError):
        generator.render_reference(evidence_path=missing)
    with pytest.raises(FileNotFoundError):
        generator.render_reference(supplemental_evidence_path=missing)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("duplicate", "duplicate operator rows"),
        ("extra-history", "exact ID set or order mismatch"),
        ("reordered", "exact ID set or order mismatch"),
        ("wrong-version", "exact ID set or order mismatch"),
        ("wrong-evidence", "original exact evidence ID mismatch"),
        ("wrong-evidence-body", "evidence source/schema mismatch"),
    ),
)
def test_evidence_mutations_fail_closed(mutation: str, message: str) -> None:
    generator = _generator()
    document = _document(generator)
    if mutation == "duplicate":
        document["rows"][1] = copy.deepcopy(document["rows"][0])
    elif mutation == "extra-history":
        document["active_ids"].append("avg@2.0.0")
    elif mutation == "reordered":
        document["active_ids"][0], document["active_ids"][1] = (
            document["active_ids"][1],
            document["active_ids"][0],
        )
    elif mutation == "wrong-version":
        document["active_ids"][2] = "avg@2.0.0"
    elif mutation == "wrong-evidence-body":
        document["rows"][0]["evidence"]["source_kind"] = "accepted expected case"
    else:
        document["rows"][0]["evidence"]["original_operator_id"] = "argmin@2.0.0"

    with pytest.raises(ValueError, match=message):
        generator._validate_evidence(_reseal(generator, document))


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("missing", "supported success claim is incomplete"),
        ("empty", "supported success claim is incomplete"),
        ("not-distinct", "fewer than two distinct supported evidence cases"),
    ),
)
def test_supported_source_case_id_mutations_fail_closed(mutation: str, message: str) -> None:
    generator = _generator()
    document = _document(generator)
    claims = document["rows"][0]["claims"]
    if mutation == "missing":
        del claims["success"]["case_id"]
    elif mutation == "empty":
        claims["success"]["case_id"] = ""
    else:
        for claim in claims.values():
            if claim["status"] == "supported":
                claim["case_id"] = "one-source-case"

    with pytest.raises(ValueError, match=message):
        generator._validate_evidence(_reseal(generator, document))


def test_duplicate_json_key_fails_before_mapping(tmp_path: Path) -> None:
    generator = _generator()
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema_version": 1, "schema_version": 1}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate JSON key: schema_version"):
        generator._load_evidence(path, expected_sha256=None)


def test_wrong_live_implementation_fails_with_the_same_exact_id() -> None:
    generator = _generator()
    rows = list(generator._load_combined_rows())
    rows[2] = copy.deepcopy(rows[2])
    rows[2]["implementation"]["module"] = "blue_data_ops.operators.avg_operator"

    with pytest.raises(ValueError, match="avg@3.0.0: live implementation identity mismatch"):
        generator._validate_registry(active_registry(), tuple(rows))


def test_operator_reference_check_cli_does_not_rewrite_subject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generator = _generator()
    output = tmp_path / "OPERATORS.md"
    expected = generator.render_reference()
    output.write_text(expected, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["generate_operator_reference.py", "--check", "--output", str(output)],
    )
    generator.main()
    assert output.read_text(encoding="utf-8") == expected

    output.write_text("stale\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="is not current"):
        generator.main()
    assert output.read_text(encoding="utf-8") == "stale\n"
