from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

import pytest

LIB_ROOT = Path(__file__).resolve().parents[2]


def _generator() -> ModuleType:
    path = LIB_ROOT / "scripts" / "generate_operator_reference.py"
    spec = spec_from_file_location("generate_operator_reference", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
