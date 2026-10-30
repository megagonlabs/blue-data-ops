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


def test_fences_are_attributed_per_package_and_share_one_page_namespace(
    tmp_path: Path,
) -> None:
    pages = _pages(tmp_path)
    extracted = validate_pages(pages)

    assert set(extracted) == set(pages)
    assert [fence.language for fence in extracted["alpha@2.0.0"]] == [
        "python",
        "python",
    ]
    for operator_id, fences in extracted.items():
        execute_page(operator_id, fences)


def test_removing_every_fence_from_one_package_turns_coverage_red(
    tmp_path: Path,
) -> None:
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


def test_live_fences_are_compiled_and_require_reader_warnings() -> None:
    network = "Running this example may send requests over the network."
    credentials = "A remote service may require credentials."
    non_execution = "The test suite does not run this example."
    notice = f"{network} {credentials} {non_execution}"
    page = (
        "Environment: llm\n\n```python\nassert True\n```\n\n"
        f"{notice}\n\n"
        "```python live\nclient.call()\n```\n"
    )
    extracted = validate_pages({"synthetic@2.0.0": page})
    assert [fence.language for fence in extracted["synthetic@2.0.0"]] == [
        "python",
        "python live",
    ]
    execute_page("synthetic@2.0.0", extracted["synthetic@2.0.0"])

    with pytest.raises(AssertionError, match="non-execution notice"):
        validate_pages({"synthetic@2.0.0": page.replace(non_execution, "")})

    validate_pages(
        {"synthetic@2.0.0": page.replace(notice, f"{non_execution} {network} {credentials}")}
    )

    validate_pages(
        {"synthetic@2.0.0": page.replace(notice, f"{credentials} {non_execution} {network}")}
    )

    with pytest.raises(AssertionError, match="network notice"):
        validate_pages(
            {
                "synthetic@2.0.0": "Environment: llm\n\n"
                "```python\nassert True\n```\n"
                "```python live\nx = 1\n```\n"
            }
        )

    with pytest.raises(AssertionError, match="network notice"):
        validate_pages({"synthetic@2.0.0": page.replace(network, "This example runs locally.")})

    denials = (
        "This example won't run automatically or download anything over the network.",
        "The test suite does not run this example, nor does it download anything over the network.",
        "The test suite does not run this example; "
        "neither will it download anything over the network.",
        "Nothing in this example sends data over the network.",
        "None of its calls sends data over the network.",
        "This example sends nothing over the network.",
        "This example sends none of your data over the network.",
    )
    for denial in denials:
        with pytest.raises(AssertionError, match="network notice"):
            validate_pages({"synthetic@2.0.0": page.replace(network, denial)})

    with pytest.raises(AssertionError, match="credential notice"):
        validate_pages({"synthetic@2.0.0": page.replace(credentials, "The service is public.")})

    with pytest.raises(AssertionError, match="credential notice"):
        validate_pages(
            {"synthetic@2.0.0": page.replace(credentials, "Nothing here requires credentials.")}
        )

    with pytest.raises(AssertionError, match="additional or altered"):
        validate_pages({"synthetic@2.0.0": page.replace(notice, f"Nothing is sent. {notice}")})

    code_only_network = page.replace(network, "This example runs locally.")
    code_only_network = code_only_network.replace("client.call()", f"# {network}\nclient.call()")
    with pytest.raises(AssertionError, match="network notice"):
        validate_pages({"synthetic@2.0.0": code_only_network})

    distant_notice = page.replace("```python live", "Run the next example:\n\n```python live")
    with pytest.raises(AssertionError, match="network notice"):
        validate_pages({"synthetic@2.0.0": distant_notice})

    second_live_fence = page + "\nRun another example:\n\n```python live\nclient.call()\n```\n"
    with pytest.raises(AssertionError, match="network notice"):
        validate_pages({"synthetic@2.0.0": second_live_fence})

    adjacent_notice = page.replace("```\n\nRunning this", "```\nRunning this")
    assert adjacent_notice != page
    validate_pages({"synthetic@2.0.0": adjacent_notice})

    code_adjacent = adjacent_notice.replace(
        f"```python\nassert True\n```\n{network} ",
        (f"```python\n# {network}\nassert True\n```\nThis example runs locally. "),
    )
    assert code_adjacent != adjacent_notice
    with pytest.raises(AssertionError, match="network notice"):
        validate_pages({"synthetic@2.0.0": code_adjacent})

    with pytest.raises(AssertionError, match="network notice"):
        validate_pages(
            {
                "synthetic@2.0.0": page.replace(
                    network, "This example never sends requests over the network."
                )
            }
        )

    with pytest.raises(AssertionError, match="credential notice"):
        validate_pages(
            {
                "synthetic@2.0.0": page.replace(
                    credentials, "The service never requires credentials."
                )
            }
        )

    with pytest.raises(AssertionError, match="network notice"):
        validate_pages(
            {
                "synthetic@2.0.0": page.replace(
                    network, "This example doesn't send requests over the network."
                )
            }
        )

    with pytest.raises(AssertionError, match="credential notice"):
        validate_pages(
            {
                "synthetic@2.0.0": page.replace(
                    credentials, "The service doesn't require credentials."
                )
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
