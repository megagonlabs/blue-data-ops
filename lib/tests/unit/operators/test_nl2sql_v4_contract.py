from __future__ import annotations

from typing import Any, cast

import pytest

from blue_data_ops.data import RegistrySeam
from blue_data_ops.llm import LLMError
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import (
    NL2SQLOperator,
    OperatorRegistry,
    active_registry,
    default_registry,
    versioned_registry,
)
from blue_data_ops.plan import (
    DataScope,
    DiscoveryQuery,
    OpenAIPlanGenerator,
    PipelinePlanner,
    PlanDraft,
    PlanningError,
    PlanningRequest,
    PlanStep,
    RegistryDataContextProvider,
    RulePlanGenerator,
)
from tests.unit.operators.test_nl2sql_security import ATTRS, TARGET, Host
from tests.unit.operators.test_nl2sql_security import host as sql_host
from tests.unit.operators.test_v2_llm_nl2 import ScriptedClient
from tests.unit.plan.test_openai_generator import RecordingClient, candidates, completed, step

host = sql_host


@pytest.mark.parametrize(
    "factory", [active_registry, versioned_registry, lambda: default_registry(nl2sql="4.0.0")]
)
def test_declared_card_is_outcome_and_resource_bound(factory: Any):
    registry = factory()
    op = registry.resolve("nl2sql@4.0.0")
    assert type(op).__name__ == "NL2SQLOutcomeOperator"
    view = OperatorSkillLoader(registry).load("nl2sql@4.0.0", level=2)
    assert view.card.operator_id == "nl2sql@4.0.0"
    assert "nl2sql@4.0.0" in view.guide
    _, _, meta = op.run([[]], ATTRS, {"execute_query": True})
    assert meta.errors[0].message == "read-only SQL execution is not configured"


@pytest.mark.parametrize("version", ["1.0.0", "2.0.0", "3.0.0", "4.0.0"])
def test_retained_cards_keep_host_execution_and_deny_caller_registry(host: Host, version: str):
    registry = OperatorRegistry()
    registry.register(NL2SQLOperator(read_only_executor=host[2]), version=version)
    op = registry.resolve("nl2sql@" + version)
    props = {
        "execute_query": True,
        "llm_client": ScriptedClient([{"query": "SELECT id FROM records"}]),
    }
    assert op.apply([[]], ATTRS, props) == [[{"id": 1}]]
    with pytest.raises(LLMError) as error:
        op.apply([[]], ATTRS, props | {"data_registry": RegistrySeam(host[0])})
    assert error.value.code == "sql_policy_invalid"


def test_builtin_rule_planner_admits_and_compiles_exact_contract(host: Host):
    host[0].sync_source(TARGET[0], recursive=True)
    registry = active_registry()
    draft = PlanDraft((PlanStep("read", "nl2sql@4.0.0", ATTRS),))

    def rule(*args: Any) -> PlanDraft:
        return draft

    planner = PipelinePlanner(
        registry,
        RulePlanGenerator((rule,)),
        data_context_provider=RegistryDataContextProvider(RegistrySeam(host[0])),
    )
    request = PlanningRequest(
        goal="Read records",
        data_scope=DataScope(*TARGET),
        discovery_queries=(DiscoveryQuery("nl2sql"),),
        allowed_operator_ids=("nl2sql@4.0.0",),
    )
    result = planner.plan(request)
    assert result.preflight.operator_ids == ("nl2sql@4.0.0",)


@pytest.mark.parametrize("name", ["nl2sql", "select"])
def test_custom_v4_never_gains_package_admission(name: str):
    registry = OperatorRegistry()
    op = NL2SQLOperator()
    cast(Any, op).name = name
    registry.register(op, version="4.0.0")
    planner = PipelinePlanner(registry, RulePlanGenerator())
    with pytest.raises(PlanningError):
        planner.plan(
            PlanningRequest(
                goal="Read records",
                discovery_queries=(DiscoveryQuery(name),),
                allowed_operator_ids=(name + "@4.0.0",),
            )
        )


def test_openai_admission_only_exact_builtin_v4(host: Host):
    host[0].sync_source(TARGET[0], recursive=True)
    registry = active_registry()
    response = candidates(step("read", "nl2sql@4.0.0", ATTRS))
    client = RecordingClient(completed(response))
    generator = OpenAIPlanGenerator(
        model="synthetic",
        registry=registry,
        allowed_operator_ids=("nl2sql@4.0.0",),
        client=client,
        send_data_context=True,
    )
    planner = PipelinePlanner(
        registry,
        generator,
        data_context_provider=RegistryDataContextProvider(RegistrySeam(host[0])),
    )
    request = PlanningRequest(
        goal="Read records",
        data_scope=DataScope(*TARGET),
        discovery_queries=(DiscoveryQuery("nl2sql"),),
        allowed_operator_ids=("nl2sql@4.0.0",),
    )
    # Actual generator validation and request construction; its response is synthetic.
    result = planner.plan(request)
    assert result.preflight.operator_ids == ("nl2sql@4.0.0",)
    assert client.create_calls
    with pytest.raises(PlanningError):
        OpenAIPlanGenerator(
            model="synthetic",
            registry=registry,
            allowed_operator_ids=("select@4.0.0",),
            client=client,
        )
