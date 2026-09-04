from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.installed.operator_skill_owner_checks import (
    execute_page,
    extract_fences,
    indexed_example_pages,
    validate_pages,
)


def _write_package(root: Path, operator_id: str, examples: str) -> str:
    name, version = operator_id.split("@", 1)
    package = root / name / version
    package.mkdir(parents=True)
    guide = f"# {name}\n"
    (package / "Operator.md").write_text(guide, encoding="utf-8")
    (package / "examples.md").write_text(examples, encoding="utf-8")
    manifest = {
        "format": "blue-data-ops/operator-skill@1",
        "operator_id": operator_id,
        "resources": {
            "guide": {
                "path": "Operator.md",
                "sha256": hashlib.sha256(guide.encode()).hexdigest(),
            },
            "examples": {
                "path": "examples.md",
                "sha256": hashlib.sha256(examples.encode()).hexdigest(),
            },
        },
    }
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return f"{name}/{version}/manifest.json"


def _pages(tmp_path: Path) -> dict[str, str]:
    first = "alpha@2.0.0"
    second = "beta@2.0.0"
    packages = {
        first: _write_package(
            tmp_path,
            first,
            "# Check\n\n```python\nvalue = 40\n```\n\n```python\nassert value + 2 == 42\n```\n",
        ),
        second: _write_package(
            tmp_path,
            second,
            "# Check\n\n```python\nassert 6 * 7 == 42\n```\n",
        ),
    }
    index = {"format": "blue-data-ops/operator-skill-index@1", "packages": packages}
    (tmp_path / "_index.json").write_text(json.dumps(index), encoding="utf-8")
    return indexed_example_pages(tmp_path)


def test_fences_are_attributed_per_package_and_share_one_page_namespace(tmp_path: Path) -> None:
    pages = _pages(tmp_path)
    extracted = validate_pages(pages)

    assert set(extracted) == set(pages)
    assert [fence.language for fence in extracted["alpha@2.0.0"]] == ["python", "python"]
    for operator_id, fences in extracted.items():
        execute_page(operator_id, fences)


def test_removing_every_fence_from_one_package_turns_coverage_red(tmp_path: Path) -> None:
    pages = _pages(tmp_path)
    pages["beta@2.0.0"] = "# Check\n\nNo executable fence.\n"

    with pytest.raises(AssertionError, match="no executable python fence"):
        validate_pages(pages)


def test_changing_a_fence_tag_turns_coverage_red(tmp_path: Path) -> None:
    pages = _pages(tmp_path)
    pages["beta@2.0.0"] = pages["beta@2.0.0"].replace("```python", "```py")

    with pytest.raises(AssertionError, match="no executable python fence"):
        validate_pages(pages)


@pytest.mark.parametrize("mutation", ("digest", "extra-file"))
def test_installed_catalog_mutations_turn_the_owner_check_red(
    tmp_path: Path, mutation: str
) -> None:
    _pages(tmp_path)
    package = tmp_path / "alpha" / "2.0.0"
    if mutation == "digest":
        (package / "examples.md").write_text("changed\n", encoding="utf-8")
    else:
        (package / "unlisted.txt").write_text("unlisted\n", encoding="utf-8")

    with pytest.raises(AssertionError):
        indexed_example_pages(tmp_path)


def test_a_changed_to_raise_block_turns_execution_red() -> None:
    fences = extract_fences("```python\nraise RuntimeError('control')\n```\n")

    with pytest.raises(RuntimeError, match="control"):
        execute_page("synthetic@2.0.0", fences)


def test_live_fences_are_compiled_and_require_disclosure_wording() -> None:
    page = (
        "The request body leaves the process. A credential is required. "
        "This is not release evidence.\n\n"
        "```python\nassert True\n```\n\n"
        "```python live\nclient.call()\n```\n"
    )
    extracted = validate_pages({"synthetic@2.0.0": page})
    assert [fence.language for fence in extracted["synthetic@2.0.0"]] == [
        "python",
        "python live",
    ]

    with pytest.raises(AssertionError):
        validate_pages(
            {"synthetic@2.0.0": "```python\nassert True\n```\n```python live\nx = 1\n```\n"}
        )
