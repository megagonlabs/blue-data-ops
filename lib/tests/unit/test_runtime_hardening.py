from __future__ import annotations

import hashlib
from typing import Any, cast

import pytest

from blue_data_ops.operator_skills.loader import (
    _PINNED_ID as LOADER_ID,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators import NL2LLMOperator, OperatorRegistry
from blue_data_ops.operators.registry import (
    _PINNED_ID,  # pyright: ignore[reportPrivateUsage]
    ResolveError,
    UpgradeError,
    upgrade_legacy_operator_id,
)
from blue_data_ops.plan import EntityType, PipelineError, PipelineExecutor
from blue_data_ops.plan.executor import PipelineError as ExecutorError
from blue_data_ops.plan.pipeline import DAG, Base, DataPipeline, EntityDAG


@pytest.mark.parametrize(
    "version", ["1.0.0\n", "1.0.0\r\n", " 1.0.0", "1.0.0 ", "01.0.0", "1٢.0.0"]
)
def test_invalid_versions_leave_registry_unchanged(version: str) -> None:
    registry = OperatorRegistry()
    operator = NL2LLMOperator()
    before = dict(vars(operator))
    with pytest.raises(ValueError):
        registry.register(operator, version)
    assert vars(operator) == before
    assert registry.get_card("nl2llm@" + version) is None
    with pytest.raises(ResolveError):
        registry.resolve("nl2llm@" + version)
    with pytest.raises(UpgradeError):
        upgrade_legacy_operator_id("nl2llm", registry, target_version=version)
    with pytest.raises(UpgradeError):
        upgrade_legacy_operator_id(
            "old", registry, target_version="1.0.0", aliases={"old": "nl2llm@" + version}
        )
    assert _PINNED_ID.fullmatch("nl2llm@" + version) is None
    assert LOADER_ID.fullmatch("nl2llm@" + version) is None


def test_valid_versions_and_aliases() -> None:
    registry = OperatorRegistry()
    for version in ("0.0.0", "1.20.300"):
        card = registry.register(NL2LLMOperator(), version)
        assert registry.resolve(card.operator_id)
        assert (
            upgrade_legacy_operator_id(
                "old", registry, target_version=version, aliases={"old": card.operator_id}
            )
            == card.operator_id
        )
        assert LOADER_ID.fullmatch(card.operator_id)


def test_pipeline_errors_keep_public_identity() -> None:
    assert PipelineError is ExecutorError
    base = Base()
    base.set_data("x", 1)
    dag = DAG()
    node = dag.create_node(label="duplicate")
    entities = EntityDAG()
    entities.create_entity(label="duplicate")
    actions = [
        lambda: base.append_data("x", 2),
        lambda: Base.from_dict({}),
        lambda: dag.create_node(label="duplicate"),
        lambda: dag.connect_nodes("absent", "absent"),
        lambda: dag.connect_nodes(node, "absent"),
        lambda: entities.create_entity(label="duplicate"),
        lambda: entities.set_node_entity("absent", None),
        lambda: entities.get_node_entity("absent"),
        lambda: DataPipeline().define_operator(cast(Any, None)),
    ]
    for action in actions:
        with pytest.raises(PipelineError) as error:
            action()
        assert "varification" not in str(error.value)


def test_semantic_join_works_when_md5_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    from blue_data_ops.llm import LLMClient
    from blue_data_ops.operators.semantic_join_operator import (
        SemanticJoinOperator,
        _get_cache_key,  # pyright: ignore[reportPrivateUsage]
    )

    class SyntheticClient(LLMClient):
        def __init__(self) -> None:
            super().__init__("synthetic")
            self.count = 0

        def execute_api_call(
            self, input: Any, properties: Any = None, additional_data: Any = None
        ) -> Any:
            self.count += 1
            return {"pair_1": True}

    def refused(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("MD5 disabled by synthetic policy")

    monkeypatch.setattr(hashlib, "md5", refused)
    client = SyntheticClient()
    output = SemanticJoinOperator().apply(
        [[{"name": "alpha"}, {"name": "alpha"}], [{"name": "alpha"}]],
        {
            "left_fields": ["name"],
            "right_fields": ["name"],
            "join_predicate": "equal",
            "estimate_cost": False,
            "batch_size": 1,
            "use_cache": True,
        },
        {"llm_client": client},
    )
    assert output == [[{"name": "alpha"}, {"name": "alpha"}]]
    assert client.count == 1
    assert len(_get_cache_key({"a": 1}, {"b": 2}, "equal", ["a"], ["b"])) == 64


@pytest.mark.parametrize("identity", ["nl2llm@1.0.1٣", "nl2llm@1.0.10\n"])
def test_pipeline_creation_and_import_refuse_invalid_pinned_ids(identity: str) -> None:
    with pytest.raises(ValueError, match="pinned"):
        DataPipeline().define_operator(identity)
    registry = OperatorRegistry()
    registry.register(NL2LLMOperator(), "1.0.10")
    plan = DataPipeline(id="invalid-reference")
    entry = plan.define_input("input")
    step = plan.define_operator("nl2llm@1.0.10", label="step")
    output = plan.define_output("output")
    plan.set_plan_input(entry)
    plan.set_plan_output(output)
    plan.connect_nodes(entry, step)
    plan.connect_nodes(step, output)
    entity = plan.get_node_entity(step, type=str(EntityType.OPERATOR))
    assert entity is not None
    entity.set_data("operator_id", identity)
    imported = DataPipeline.from_dict(plan.to_dict())
    with pytest.raises(PipelineError, match="cannot resolve"):
        PipelineExecutor(registry).preflight(imported)
