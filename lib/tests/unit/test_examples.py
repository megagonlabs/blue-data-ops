from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from blue_data_ops.operators import OperatorCard, versioned_registry

LIB_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = LIB_ROOT / "examples"
ACTIVE_OFFLINE_EXAMPLES = (
    "core_quickstart.py",
    "sqlite_quickstart.py",
    "ml_quickstart.py",
    "vector_quickstart.py",
    "embedding_planner.py",
    "operator_skill_discovery.py",
    "operator_skill_integrations.py",
)
LEGACY_OFFLINE_EXAMPLES = ("refinement.py",)
OFFLINE_EXAMPLES = ACTIVE_OFFLINE_EXAMPLES + LEGACY_OFFLINE_EXAMPLES
OPTIONAL_EXAMPLES = (
    "nl2llm.py",
    "nl2sql_sqlite.py",
    "semantic_filter.py",
)
SKILL_DISCOVERY_EXAMPLE = "operator_skill_discovery.py"
SKILL_INELIGIBLE_OPERATOR_ID = "avg@1.0.0"
LEGACY_REFINEMENT_IDS = frozenset(
    {"multipart_query@2.0.0", "nl2query_router@2.0.0", "plan_discover@2.0.0"}
)


def _run_example(name: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    source_path = str(LIB_ROOT / "src")
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (source_path, env.get("PYTHONPATH", "")) if part
    )
    # Warning visibility is asserted below, so an ambient PYTHONWARNINGS must not decide it.
    env.pop("PYTHONWARNINGS", None)
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
    cards = {card.operator_id: card for card in registry.list_cards() if card.version == "2.0.0"}
    class_ids = {type(registry.resolve(operator_id)).__name__: operator_id for operator_id in cards}
    return cards, class_ids


def _source_operator_ids(
    path: Path, cards: Mapping[str, OperatorCard], class_ids: Mapping[str, str]
) -> set[str]:
    """Operator ids an example names outright: a constructor call or a ``resolve("…")`` literal.

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
            and node.func.attr == "resolve"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and node.args[0].value in cards
        ):
            source_ids.add(node.args[0].value)
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


def test_the_offline_partition_is_disjoint_and_covers_every_offline_example() -> None:
    assert not set(ACTIVE_OFFLINE_EXAMPLES) & set(LEGACY_OFFLINE_EXAMPLES)
    assert len(OFFLINE_EXAMPLES) == len(set(OFFLINE_EXAMPLES))
    runnable = {path.name for path in EXAMPLES.glob("*.py") if not path.name.startswith("_")}
    assert set(OFFLINE_EXAMPLES) == runnable - set(OPTIONAL_EXAMPLES)
    # The eight names the flat offline tuple carried; a new example joins one side or the other.
    assert set(OFFLINE_EXAMPLES) >= {
        "core_quickstart.py",
        "sqlite_quickstart.py",
        "ml_quickstart.py",
        "vector_quickstart.py",
        "embedding_planner.py",
        "operator_skill_discovery.py",
        "operator_skill_integrations.py",
        "refinement.py",
    }


def test_the_legacy_examples_name_exactly_the_retained_refinement_ids() -> None:
    cards, class_ids = _registry_view()
    claimed: set[str] = set()
    for name in LEGACY_OFFLINE_EXAMPLES:
        claimed |= _source_operator_ids(EXAMPLES / name, cards, class_ids)

    assert claimed == set(LEGACY_REFINEMENT_IDS)
    assert all(cards[operator_id].deprecated for operator_id in claimed)


def test_ordinary_examples_name_no_deprecated_operator() -> None:
    cards, class_ids = _registry_view()
    deprecated_ids = {operator_id for operator_id, card in cards.items() if card.deprecated}
    assert deprecated_ids

    for name in ACTIVE_OFFLINE_EXAMPLES + OPTIONAL_EXAMPLES:
        named = _source_operator_ids(EXAMPLES / name, cards, class_ids)
        assert not named & deprecated_ids, name


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

    deprecated_names = {card.name for card in registry.list_cards() if card.deprecated}
    assert deprecated_names
    assert sentinel.split("@")[0] not in deprecated_names
    for name in deprecated_names:
        assert name not in source


def test_the_legacy_example_surfaces_the_package_deprecation_warning() -> None:
    result = _run_example("refinement.py")

    assert result.returncode == 0, result.stderr
    assert result.stderr.count("BlueDataOpsDeprecationWarning") == len(LEGACY_REFINEMENT_IDS)
    for operator_id in LEGACY_REFINEMENT_IDS:
        assert f"operator {operator_id.split('@')[0]!r}" in result.stderr
    outcomes = [line.split(":", 1)[0] for line in result.stdout.strip().splitlines()]
    assert outcomes == ["multipart", "router", "discovery"]


def test_the_skill_discovery_example_expands_only_the_eligible_card() -> None:
    result = _run_example(SKILL_DISCOVERY_EXAMPLE)

    assert result.returncode == 0, result.stderr
    assert "BlueDataOpsDeprecationWarning" not in result.stderr
    lines = result.stdout.strip().splitlines()
    assert lines[0].startswith("expanded: avg@2.0.0 ")
    assert lines[1] == f"skipped without loading: {SKILL_INELIGIBLE_OPERATOR_ID}"


def test_example_map_covers_public_tag_families() -> None:
    coverage = json.loads((EXAMPLES / "coverage.json").read_text(encoding="utf-8"))
    mapped_examples = set(coverage["examples"])
    runnable_examples = {
        path.name for path in EXAMPLES.glob("*.py") if not path.name.startswith("_")
    }
    assert mapped_examples == runnable_examples
    cards, class_ids = _registry_view()
    claimed_ids: set[str] = set()
    for example, operator_ids in coverage["examples"].items():
        source_ids = _source_operator_ids(EXAMPLES / example, cards, class_ids)
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
