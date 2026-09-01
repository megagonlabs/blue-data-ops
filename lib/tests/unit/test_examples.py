from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from blue_data_ops.operators import versioned_registry

LIB_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = LIB_ROOT / "examples"
OFFLINE_EXAMPLES = (
    "core_quickstart.py",
    "sqlite_quickstart.py",
    "ml_quickstart.py",
    "vector_quickstart.py",
    "refinement.py",
)
OPTIONAL_EXAMPLES = (
    "nl2llm.py",
    "nl2sql_sqlite.py",
    "semantic_filter.py",
)


@pytest.mark.parametrize("name", OFFLINE_EXAMPLES)
def test_offline_example_runs_from_lib(name: str) -> None:
    result = subprocess.run(
        [sys.executable, str(EXAMPLES / name)],
        cwd=LIB_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()


@pytest.mark.parametrize("name", OPTIONAL_EXAMPLES)
def test_optional_example_is_valid_python(name: str) -> None:
    source = (EXAMPLES / name).read_text(encoding="utf-8")
    compile(source, str(EXAMPLES / name), "exec")


def test_example_map_covers_public_tag_families() -> None:
    coverage = json.loads((EXAMPLES / "coverage.json").read_text(encoding="utf-8"))
    registry = versioned_registry()
    cards = {card.operator_id: card for card in registry.list_cards() if card.version == "2.0.0"}
    class_ids = {type(registry.resolve(operator_id)).__name__: operator_id for operator_id in cards}
    claimed_ids: set[str] = set()
    for example, operator_ids in coverage["examples"].items():
        path = EXAMPLES / example
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        source_ids: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id in class_ids:
                source_ids.add(class_ids[node.func.id])
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "resolve"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and node.args[0].value in cards
            ):
                source_ids.add(node.args[0].value)
        assert source_ids == set(operator_ids), example
        claimed_ids.update(source_ids)
    assert claimed_ids <= cards.keys()

    reference_only = set(coverage["reference_only_axes"])
    live_axes = {tag.split("-", 1)[0] for card in cards.values() for tag in card.tags}
    assert reference_only <= live_axes
    expected = {
        tag
        for card in cards.values()
        for tag in card.tags
        if tag.split("-", 1)[0] not in reference_only
    }
    represented = {tag for operator_id in claimed_ids for tag in cards[operator_id].tags}
    assert expected <= represented


def test_every_capability_has_generated_reference_coverage() -> None:
    text = (LIB_ROOT / "OPERATORS.md").read_text(encoding="utf-8")
    cards = [card for card in versioned_registry().list_cards() if card.version == "2.0.0"]
    assert len(cards) == 36
    live_axes = {tag.split("-", 1)[0] for card in cards for tag in card.tags}
    for axis in live_axes:
        assert f"| `{axis}-*` |" in text
    for card in cards:
        assert text.count(f"## `{card.operator_id}`") == 1


def test_real_llm_check_refuses_the_test_stub() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(LIB_ROOT / "tests" / "stubs")
    result = subprocess.run(
        [sys.executable, str(LIB_ROOT / "scripts" / "check_real_llm_install.py")],
        cwd=LIB_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "test stub" in result.stderr
