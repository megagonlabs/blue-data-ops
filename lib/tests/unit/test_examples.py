from __future__ import annotations

import ast
import json
import os
import runpy
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any

import pytest

from blue_data_ops.llm import LLMClient
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
    "feature-demos/llm_settings.py",
)
OPTIONAL_EXAMPLES = (
    "feature-demos/nl2llm.py",
    "feature-demos/nl2sql_sqlite.py",
    "feature-demos/semantic_filter.py",
    "integration-demos/openai_planner_sqlite.py",
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


def test_llm_settings_example_shows_each_precedence_layer() -> None:
    name = "feature-demos/llm_settings.py"
    result = _run_example(name)
    assert result.returncode == 0, result.stderr
    assert result.stdout == (EXAMPLES / "feature-demos/llm_settings.output.txt").read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize("name", OPTIONAL_EXAMPLES)
def test_optional_example_is_valid_python(name: str) -> None:
    source = (EXAMPLES / name).read_text(encoding="utf-8")
    compile(source, str(EXAMPLES / name), "exec")


class _EmbeddingEndpoint:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        texts = kwargs["input"]
        vectors = [
            SimpleNamespace(index=index, embedding=[1.0, float(index + 1)])
            for index, _ in enumerate(texts)
        ]
        return SimpleNamespace(data=vectors)


class _PlannerEndpoint:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        payload: dict[str, Any] = {
            "candidates": [
                {
                    "label": "sqlite-plan",
                    "steps": [
                        {
                            "step_id": "query",
                            "operator_id": "nl2sql@3.0.0",
                            "attributes_json": "{}",
                            "depends_on": [],
                            "label": None,
                        }
                    ],
                }
            ]
        }
        part = SimpleNamespace(type="output_text", text=json.dumps(payload))
        return SimpleNamespace(status="completed", output=[SimpleNamespace(content=[part])])


class _PlannerExampleClient:
    def __init__(self) -> None:
        self.embeddings = _EmbeddingEndpoint()
        self.responses = _PlannerEndpoint()

    def with_options(self, **_: Any) -> _PlannerExampleClient:
        return self


class _NL2SQLClient(LLMClient):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any] | None] = []

    def execute_api_call(
        self,
        input: Any,
        properties: dict[str, Any] | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> Any:
        del input, properties
        self.calls.append(additional_data)
        return {"query": "SELECT COUNT(*) AS order_count FROM orders"}


def test_openai_planner_example_discovers_plans_and_executes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "path", [str(EXAMPLES), *sys.path])
    namespace = runpy.run_path(str(EXAMPLES / "integration-demos/openai_planner_sqlite.py"))
    run_example = namespace["run_example"]
    client = _PlannerExampleClient()
    nl2sql_client = _NL2SQLClient()

    with TemporaryDirectory(prefix="blue-data-ops-test-") as directory:
        result = run_example(
            "How many orders are there?",
            directory=directory,
            planner_model="planner-test-model",
            embedding_model="embedding-test-model",
            nl2sql_model="nl2sql-test-model",
            openai_client=client,
            nl2sql_client=nl2sql_client,
        )

    run = result.planner_run
    active_ids = tuple(card.operator_id for card in active_registry().list_cards())
    assert run.planning.request.allowed_operator_ids == active_ids
    assert set(run.planning.discovery.operator_ids) == set(active_ids)
    assert result.tag_operator_ids == ("nl2bn@3.0.0", "nl2llm@3.0.0", "nl2sql@3.0.0")
    assert set(result.embedding_operator_ids) == set(active_ids)
    assert [step.operator_id for step in run.planning.selected.steps] == ["nl2sql@3.0.0"]
    assert run.execution.output_data == [[{"sql": "SELECT COUNT(*) AS order_count FROM orders"}]]
    assert run.execution.succeeded
    assert result.embedding_provider_calls == 2
    assert [len(request["input"]) for request in client.embeddings.requests] == [33, 1]
    request = json.loads(client.responses.requests[0]["input"][0]["content"])
    model_ids = [card["operator_id"] for card in request["operators"]]
    assert model_ids == list(result.model_candidate_operator_ids)
    assert "nl2sql@3.0.0" in model_ids
    side_effect_ids = {
        "create_database@2.0.0",
        "create_table@2.0.0",
        "insert_table@3.0.0",
    }
    assert set(model_ids) == set(active_ids) - side_effect_ids
    assert "data_context" in request
    assert request["data_context"]["provenance"]["raw_rows"] == 0
    planner_entities = request["data_context"]["schema"]["entities"]
    assert [attribute["name"] for attribute in planner_entities[0]["attributes"]] == [
        "id",
        "region",
        "total",
    ]
    assert len(nl2sql_client.calls) == 1
    assert nl2sql_client.calls[0] is not None
    assert '"name": "orders"' in nl2sql_client.calls[0]["schema"]


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
        "feature-demos/llm_settings.py",
    }


def test_ordinary_examples_use_the_active_registry_and_exact_active_ids() -> None:
    cards, class_ids = _registry_view()
    active_ids = {card.operator_id for card in active_registry().list_cards()}
    for name in OFFLINE_EXAMPLES + OPTIONAL_EXAMPLES:
        if name == SKILL_DISCOVERY_EXAMPLE:
            continue
        source = (EXAMPLES / name).read_text(encoding="utf-8")
        named = _source_operator_ids(EXAMPLES / name, cards, class_ids)
        if name == "feature-demos/nl2sql_sqlite.py":
            assert "ReadOnlySQLExecutor" in source and "OperatorRegistry" in source, name
            expected = {"nl2sql@3.0.0"}
            assert named == expected, name
        else:
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
