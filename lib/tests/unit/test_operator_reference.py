from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest

LIB_ROOT = Path(__file__).resolve().parents[2]


def _generator() -> ModuleType:
    path = LIB_ROOT / "scripts" / "generate_operator_reference.py"
    spec = spec_from_file_location("generate_operator_reference", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_manifest_includes_the_generator_input() -> None:
    generator = _generator()
    outcomes_path = cast(Path, generator.OUTCOMES_PATH)
    fixture_path = outcomes_path.relative_to(LIB_ROOT).as_posix()
    directives = [
        tuple(line.strip().split(maxsplit=1))
        for line in (LIB_ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert ("include", fixture_path) in directives


def test_operator_reference_matches_live_registry_and_fixtures() -> None:
    generated = _generator().render_reference()
    assert (LIB_ROOT / "OPERATORS.md").read_text(encoding="utf-8") == generated
    assert "registry = versioned_registry()" in generated
    assert "Profiles `seam` and" in generated
    assert "`seam_sql` require a registry seam" in generated
    assert "`llm` and `llm_refine` require a model client" in generated
    assert "`llm_seam` requires both" in generated
    assert "beginning with `plan`" not in generated
    assert "name a seam, model, or planner" not in generated
    assert (
        "Source component. Refines an explicit scope only; it does not construct one when scope is "
        "omitted" in generated
    )
    assert "Database component; requires source." in generated
    assert "Collection component; requires source and database." in generated
    assert "When omitted, source, database, and collection do not construct one" in generated


def _sections(generated: str) -> list[str]:
    """Split the reference on its per-operator headings, keeping each heading's body."""
    blocks = generated.split("\n## `")[1:]
    return [f"## `{block}" for block in blocks]


def test_the_reference_marks_the_deprecated_cards_the_registry_reports() -> None:
    from blue_data_ops.operators import versioned_registry

    generated = _generator().render_reference()
    sections = _sections(generated)
    marked = {section.split("`")[1] for section in sections if "**Deprecated in 2.8.0" in section}
    live = {
        card.operator_id
        for card in versioned_registry().list_cards()
        if card.version == "2.0.0" and card.deprecated
    }

    assert len(sections) == 36
    assert marked == live
    assert marked == {
        "multipart_query@2.0.0",
        "nl2query_router@2.0.0",
        "plan_discover@2.0.0",
        "query_breakdown@2.0.0",
    }
    assert len(sections) - len(marked) == 32


def test_a_marked_section_keeps_its_ordinary_reference_content() -> None:
    sections = _sections(_generator().render_reference())
    section = next(block for block in sections if "plan_discover@2.0.0" in block)

    assert "removed in 3.0.0" in section
    assert "COMPATIBILITY.md#deprecated-in-280" in section
    for expected in ("When to invoke:", "Tags: ", "| Attribute |", "Fixture-backed call:"):
        assert expected in section, expected


def test_the_tag_taxonomy_survives_the_lifecycle_marking() -> None:
    generated = _generator().render_reference()

    assert "## Tag taxonomy" in generated
    for axis in ("capability", "domain", "flow", "accepts", "produces", "requires"):
        assert f"| `{axis}-*` |" in generated, axis


def test_operator_reference_check_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    generator = _generator()
    output = tmp_path / "OPERATORS.md"
    output.write_text(generator.render_reference(), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["generate_operator_reference.py", "--check", "--output", str(output)],
    )
    generator.main()

    output.write_text("stale\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="is not current"):
        generator.main()
