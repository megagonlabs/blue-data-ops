from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from tests.installed import operator_skill_owner_checks as owner_checks
from tests.installed.operator_skill_owner_checks import (
    environment_partitions,
    execute_page,
    extract_fences,
    indexed_example_pages,
    parse_environment,
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
            "# Check\n\nEnvironment: base\n\n"
            "```python\nvalue = 40\n```\n\n"
            "```python\nassert value + 2 == 42\n```\n",
        ),
        second: _write_package(
            tmp_path,
            second,
            "# Check\n\nEnvironment: ml\n\n```python\nassert 6 * 7 == 42\n```\n",
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
    pages["beta@2.0.0"] = "# Check\n\nEnvironment: ml\n\nNo executable fence.\n"

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
        "Environment: llm\n\nThe request body leaves the process. A credential is required. "
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
            {
                "synthetic@2.0.0": "Environment: llm\n\n"
                "```python\nassert True\n```\n"
                "```python live\nx = 1\n```\n"
            }
        )


@pytest.mark.parametrize(
    "page",
    (
        "# Missing\n",
        "Environment:base\n",
        "Environment: gpu\n",
        "Environment: base\nEnvironment: ml\n",
    ),
)
def test_missing_unknown_or_duplicate_environment_turns_the_gate_red(page: str) -> None:
    with pytest.raises(AssertionError):
        parse_environment(page)


def test_environment_inside_a_code_fence_is_not_metadata() -> None:
    page = "```python\nEnvironment: base\n```\n"

    with pytest.raises(AssertionError, match="found 0"):
        parse_environment(page)


def test_environment_partitions_are_derived_from_pages(tmp_path: Path) -> None:
    pages = _pages(tmp_path)
    partitions = environment_partitions(pages)

    assert partitions == {
        "base": ("alpha@2.0.0",),
        "llm": (),
        "ml": ("beta@2.0.0",),
        "vector": (),
    }


def test_environment_partition_drives_the_existing_only_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected = environment_partitions(_pages(tmp_path))["ml"]
    assert selected
    executed: list[str] = []

    def installed_root(forbidden_roots: tuple[Path, ...]) -> tuple[Path, Path]:
        del forbidden_roots
        return tmp_path, tmp_path

    def record_execution(operator_id: str, fences: tuple[owner_checks.Fence, ...]) -> None:
        del fences
        executed.append(operator_id)

    monkeypatch.setattr(
        owner_checks,
        "installed_resource_root",
        installed_root,
    )
    monkeypatch.setattr(
        owner_checks,
        "execute_page",
        record_execution,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "operator-skill-owner-checks",
            *(item for value in selected for item in ("--only", value)),
        ],
    )

    assert owner_checks.main() == 0
    assert executed == list(selected)


def test_main_prints_partitions_before_an_owner_check_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _pages(tmp_path)

    def installed_root(forbidden_roots: tuple[Path, ...]) -> tuple[Path, Path]:
        del forbidden_roots
        return tmp_path, tmp_path

    def fail_execution(operator_id: str, fences: tuple[owner_checks.Fence, ...]) -> None:
        del operator_id, fences
        raise RuntimeError("owner check failed")

    monkeypatch.setattr(owner_checks, "installed_resource_root", installed_root)
    monkeypatch.setattr(owner_checks, "execute_page", fail_execution)
    monkeypatch.setattr(sys, "argv", ["operator-skill-owner-checks"])

    with pytest.raises(RuntimeError, match="owner check failed"):
        owner_checks.main()

    report = json.loads(capsys.readouterr().out)
    assert report["environments"] == {
        "base": ["alpha@2.0.0"],
        "llm": [],
        "ml": ["beta@2.0.0"],
        "vector": [],
    }
    assert report["executed"] == ["alpha@2.0.0", "beta@2.0.0"]
