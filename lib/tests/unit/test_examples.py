from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import OperatorCard, active_registry, versioned_registry

LIB_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = LIB_ROOT.parent
EXAMPLES = REPO_ROOT / "examples"
OFFLINE_EXAMPLES = (
    "quickstart/core_quickstart.py",
    "quickstart/sqlite_quickstart.py",
    "quickstart/ml_quickstart.py",
    "quickstart/vector_quickstart.py",
    "integration-demos/embedding_planner.py",
    "feature-demos/operator_skill_discovery.py",
    "feature-demos/operator_skill_integrations.py",
    "feature-demos/operator_outcomes.py",
)
OPTIONAL_EXAMPLES = (
    "feature-demos/nl2llm.py",
    "feature-demos/nl2sql_sqlite.py",
    "feature-demos/semantic_filter.py",
)
SKILL_DISCOVERY_EXAMPLE = "feature-demos/operator_skill_discovery.py"
SKILL_INELIGIBLE_OPERATOR_ID = "avg@1.0.0"


def _runnable_example_paths() -> set[str]:
    """Example paths relative to ``EXAMPLES``, skipping the underscore-prefixed shared helpers."""

    return {
        path.relative_to(EXAMPLES).as_posix()
        for path in EXAMPLES.rglob("*.py")
        if not path.name.startswith("_")
    }


def _run_example(name: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    source_path = str(LIB_ROOT / "src")
    # The SQLite examples import ``_sqlite_demo`` from the examples root, not from their own
    # category directory, so that root has to be importable as well.
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (source_path, str(EXAMPLES), env.get("PYTHONPATH", "")) if part
    )
    return subprocess.run(
        [sys.executable, str(EXAMPLES / name)],
        cwd=LIB_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _registry_view() -> tuple[dict[str, OperatorCard], dict[str, str]]:
    registry = versioned_registry()
    cards = {card.operator_id: card for card in registry.list_cards()}
    class_ids = {
        type(registry.resolve(operator_id)).__name__: operator_id
        for operator_id, card in cards.items()
        if card.version == "2.0.0"
    }
    return cards, class_ids


def _source_operator_ids(
    path: Path, cards: Mapping[str, OperatorCard], class_ids: Mapping[str, str]
) -> set[str]:
    """Ids named by constructors or literal ``resolve`` / ``define_operator`` calls.

    An example that reaches operators through ``registry.find(...)`` names none of them here,
    and this returns an empty set for it. That boundary is why the skill-discovery example
    carries its own source sentinel instead of relying on this extraction.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    source_ids: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id in class_ids:
            source_ids.add(class_ids[node.func.id])
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in {"resolve", "define_operator"}
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and node.args[0].value in cards
        ):
            source_ids.add(node.args[0].value)
        for keyword in node.keywords:
            if keyword.arg != "allowed_operator_ids" or not isinstance(
                keyword.value, (ast.List, ast.Tuple)
            ):
                continue
            for item in keyword.value.elts:
                if (
                    isinstance(item, ast.Constant)
                    and isinstance(item.value, str)
                    and item.value in cards
                ):
                    source_ids.add(item.value)
    return source_ids


def _module_string_constant(tree: ast.Module, name: str) -> str:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            value = node.value
            assert isinstance(value, ast.Constant) and isinstance(value.value, str)
            return value.value
    raise AssertionError(f"{name} is not a module-level string constant")


@pytest.mark.parametrize("name", OFFLINE_EXAMPLES)
def test_offline_example_runs_from_lib(name: str) -> None:
    result = _run_example(name)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()


@pytest.mark.parametrize("name", OPTIONAL_EXAMPLES)
def test_optional_example_is_valid_python(name: str) -> None:
    source = (EXAMPLES / name).read_text(encoding="utf-8")
    compile(source, str(EXAMPLES / name), "exec")


def test_the_offline_partition_covers_every_offline_example() -> None:
    assert len(OFFLINE_EXAMPLES) == len(set(OFFLINE_EXAMPLES))
    runnable = _runnable_example_paths()
    assert set(OFFLINE_EXAMPLES) == runnable - set(OPTIONAL_EXAMPLES)
    assert set(OFFLINE_EXAMPLES) == {
        "quickstart/core_quickstart.py",
        "quickstart/sqlite_quickstart.py",
        "quickstart/ml_quickstart.py",
        "quickstart/vector_quickstart.py",
        "integration-demos/embedding_planner.py",
        "feature-demos/operator_skill_discovery.py",
        "feature-demos/operator_skill_integrations.py",
        "feature-demos/operator_outcomes.py",
    }


def test_ordinary_examples_use_the_active_registry_and_exact_active_ids() -> None:
    cards, class_ids = _registry_view()
    active_ids = {card.operator_id for card in active_registry().list_cards()}
    for name in OFFLINE_EXAMPLES + OPTIONAL_EXAMPLES:
        if name == SKILL_DISCOVERY_EXAMPLE:
            continue
        source = (EXAMPLES / name).read_text(encoding="utf-8")
        named = _source_operator_ids(EXAMPLES / name, cards, class_ids)
        assert "active_registry" in source, name
        assert named <= active_ids, name


def test_the_skill_ineligibility_sentinel_is_a_used_source_constant() -> None:
    path = EXAMPLES / SKILL_DISCOVERY_EXAMPLE
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    sentinel = _module_string_constant(tree, "SKILL_INELIGIBLE_OPERATOR_ID")
    assert sentinel == SKILL_INELIGIBLE_OPERATOR_ID

    registry = versioned_registry()
    card = registry.get_card(sentinel)
    assert card is not None
    assert card.deprecated is False

    asserted_on = [
        statement
        for statement in ast.walk(tree)
        if isinstance(statement, ast.Assert)
        and any(
            isinstance(node, ast.Name) and node.id == "SKILL_INELIGIBLE_OPERATOR_ID"
            for node in ast.walk(statement)
        )
    ]
    assert len(asserted_on) >= 2

    retired_names = {"multipart_query", "nl2query_router", "plan_discover", "query_breakdown"}
    assert not {card.name for card in registry.list_cards()} & retired_names
    for name in retired_names:
        assert name not in source


def test_the_skill_discovery_example_expands_only_the_eligible_card() -> None:
    registry = versioned_registry()
    loader = OperatorSkillLoader(registry)
    eligible_ids = set(loader.available_operator_ids())
    expected = next(
        card
        for card in registry.find("average", tags=["domain-arithmetic"])
        if card.operator_id in eligible_ids
    )
    descriptor = loader.describe(expected.operator_id)
    result = _run_example(SKILL_DISCOVERY_EXAMPLE)

    assert result.returncode == 0, result.stderr
    assert "BlueDataOpsDeprecationWarning" not in result.stderr
    lines = result.stdout.strip().splitlines()
    assert lines == [
        f"expanded: {expected.operator_id} {descriptor.declared_levels}",
        f"skipped without loading: {SKILL_INELIGIBLE_OPERATOR_ID}",
    ]


def test_example_map_covers_public_tag_families() -> None:
    coverage = json.loads((EXAMPLES / "coverage.json").read_text(encoding="utf-8"))
    mapped_examples = set(coverage["examples"])
    assert mapped_examples == _runnable_example_paths()
    history_cards, class_ids = _registry_view()
    active_cards = {card.operator_id: card for card in active_registry().list_cards()}
    claimed_ids: set[str] = set()
    for example, operator_ids in coverage["examples"].items():
        source_ids = _source_operator_ids(EXAMPLES / example, history_cards, class_ids)
        assert source_ids == set(operator_ids), example
        claimed_ids.update(source_ids)
    assert claimed_ids <= active_cards.keys()

    reference_only = set(coverage["reference_only_axes"])
    live_axes = {tag.split("-", 1)[0] for card in active_cards.values() for tag in card.tags}
    assert reference_only <= live_axes
    expected = {
        tag
        for card in active_cards.values()
        for tag in card.tags
        if tag.split("-", 1)[0] not in reference_only
    }
    represented = {tag for operator_id in claimed_ids for tag in active_cards[operator_id].tags}
    assert expected <= represented


def test_every_capability_has_generated_reference_coverage() -> None:
    text = (LIB_ROOT / "OPERATORS.md").read_text(encoding="utf-8")
    cards = active_registry().list_cards()
    assert len(cards) == 33
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
