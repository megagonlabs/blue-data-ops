from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from types import SimpleNamespace
from typing import Any, cast

import pytest

from blue_data_ops.operators import (
    OperatorCard,
    OperatorRegistry,
    active_registry,
    versioned_registry,
)
from blue_data_ops.plan import (
    DiscoveryQuery,
    OpenAIPlanGenerator,
    PipelinePlanner,
    PlanDraft,
    PlanningError,
    PlanningRequest,
)
from blue_data_ops.plan.planner import DiscoverySnapshot


class DeclarationClient:
    def __init__(
        self, on_call: Callable[[dict[str, Any], dict[str, Any]], None] | None = None
    ) -> None:
        self.documents: list[dict[str, Any]] = []
        self.responses = self
        self.on_call = on_call

    def with_options(self, **kwargs: Any) -> DeclarationClient:
        return self

    def create(self, **kwargs: Any) -> SimpleNamespace:
        document = json.loads(kwargs["input"][0]["content"])
        self.documents.append(document)
        declared = document["operators"][0]["attributes"]
        assert {"operand_key", "operand", "operand_val"} <= declared.keys()
        attributes = {
            key: value
            for key, value in zip(("operand_key", "operand", "operand_val"), ("total", ">", 100))
        }
        if self.on_call:
            self.on_call(declared, attributes)
        body: dict[str, Any] = {
            "candidates": [
                {
                    "label": None,
                    "steps": [
                        {
                            "step_id": "s",
                            "operator_id": document["operators"][0]["operator_id"],
                            "attributes_json": json.dumps(attributes),
                            "depends_on": [],
                            "label": None,
                        }
                    ],
                }
            ]
        }
        return SimpleNamespace(
            status="completed",
            output=[
                SimpleNamespace(
                    content=[SimpleNamespace(type="output_text", text=json.dumps(body))]
                )
            ],
        )


def generate(registry: OperatorRegistry, client: DeclarationClient) -> Sequence[PlanDraft]:
    generator = OpenAIPlanGenerator(
        "offline", registry=registry, allowed_operator_ids=("select@2.0.0",), client=client
    )
    return generator.generate(
        PlanningRequest(
            goal="select totals over 100", discovery_queries=(DiscoveryQuery("select"),)
        ),
        DiscoverySnapshot((cast(OperatorCard, registry.get_card("select@2.0.0")),)),
        None,
    )


def test_model_uses_declarations_and_pipeline_executes_without_caller_select_values():
    registry = active_registry()
    client = DeclarationClient()
    generator = OpenAIPlanGenerator(
        "offline", registry=registry, allowed_operator_ids=("select@2.0.0",), client=client
    )
    request = PlanningRequest(
        goal="select totals over 100", discovery_queries=(DiscoveryQuery("select"),)
    )
    result = PipelinePlanner(registry, generator).run(request, [[{"total": 50}, {"total": 150}]])
    assert result.execution.output_data == [[{"total": 150}]]
    assert result.execution.succeeded


def test_one_snapshot_survives_provider_time_edits_and_next_call_sees_edits():
    registry = versioned_registry()
    op = registry.resolve("select@2.0.0")
    op.get_attributes()["hidden_key"] = {
        "type": "str",
        "description": "visible declaration",
        "hidden": True,
    }

    def edit(declared: dict[str, Any], attributes: dict[str, Any]) -> None:
        assert declared["hidden_key"]["hidden"] is True
        del op.get_attributes()["hidden_key"]
        attributes["hidden_key"] = "admitted by request snapshot"

    first = DeclarationClient(edit)
    assert generate(registry, first)[0].steps[0].attributes["hidden_key"]
    second = DeclarationClient(lambda declared, attrs: attrs.update(hidden_key="guessed"))
    with pytest.raises(PlanningError, match="undeclared"):
        generate(registry, second)
    assert "hidden_key" not in second.documents[0]["operators"][0]["attributes"]


def test_default_states_are_detached_and_never_stringified():
    registry = versioned_registry()
    op = registry.resolve("select@2.0.0")

    class Nonportable:
        def __str__(self):
            raise AssertionError("must not stringify")

    op.get_attributes().update(
        {
            "absent": {"type": "str"},
            "nullable": {"type": "str", "default": None},
            "required_default": {"type": "str", "required": True, "default": "x"},
            "opaque": {"type": "object", "default": Nonportable()},
            "mutable": {"type": "list", "default": [1]},
        }
    )
    cast(Any, op)._metadata_materialize_defaults["nullable"] = False
    client = DeclarationClient()
    generate(registry, client)
    declarations = client.documents[0]["operators"][0]["attributes"]
    assert declarations["absent"]["default_state"] == "absent"
    assert declarations["nullable"]["default_state"] == "deferred"
    assert declarations["required_default"]["default_state"] == "deferred"
    assert declarations["opaque"]["default_state"] == "unavailable"
    cast(Any, op)._metadata_materialize_defaults["nullable"] = True
    generate(registry, client)
    assert client.documents[-1]["operators"][0]["attributes"]["nullable"]["default"] is None
    op.get_attributes()["mutable"]["default"].append(2)
    assert declarations["mutable"]["default"] == [1]


@pytest.mark.parametrize(
    "field,value", [("hidden", 1), ("required", 1), ("type", []), ("description", 3)]
)
def test_malformed_declarations_refused_before_client(field: str, value: Any):
    registry = versioned_registry()
    registry.resolve("select@2.0.0").get_attributes()["operand_key"][field] = value
    client = DeclarationClient()
    with pytest.raises(PlanningError):
        generate(registry, client)
    assert client.documents == []


def test_discovered_stock_catalog_request_fits_bound():
    registry = active_registry()
    cards = tuple(registry.list_cards())

    class CatalogClient(DeclarationClient):
        def create(self, **kwargs: Any) -> SimpleNamespace:
            payload = kwargs["input"][0]["content"]
            assert len(payload.encode()) < 131072
            document = json.loads(payload)
            assert len(document["operators"]) >= 25
            assert all("attributes" in card for card in document["operators"])
            return SimpleNamespace(
                status="completed",
                output=[
                    SimpleNamespace(
                        content=[
                            SimpleNamespace(
                                type="output_text",
                                text=json.dumps(
                                    {
                                        "candidates": [
                                            {
                                                "label": None,
                                                "steps": [
                                                    {
                                                        "step_id": "first",
                                                        "operator_id": document["operators"][0][
                                                            "operator_id"
                                                        ],
                                                        "attributes_json": "{}",
                                                        "depends_on": [],
                                                        "label": None,
                                                    }
                                                ],
                                            }
                                        ]
                                    }
                                ),
                            )
                        ]
                    )
                ],
            )

    generator = OpenAIPlanGenerator(
        "offline",
        registry=registry,
        allowed_operator_ids=tuple(card.operator_id for card in cards),
        client=CatalogClient(),
    )
    generator.generate(
        PlanningRequest(goal="select records", discovery_queries=(DiscoveryQuery("select"),)),
        DiscoverySnapshot(cards),
        None,
    )


def test_oversized_attribute_description_refuses_before_client_resolution(
    monkeypatch: pytest.MonkeyPatch,
):
    registry = versioned_registry()
    registry.resolve("select@2.0.0").get_attributes()["operand_key"]["description"] = "x" * 140000
    generator = OpenAIPlanGenerator(
        "offline", registry=registry, allowed_operator_ids=("select@2.0.0",)
    )
    monkeypatch.setattr(
        generator,
        "_resolve_client",
        lambda: pytest.fail("client resolved for oversized declaration"),
    )
    with pytest.raises(PlanningError):
        generator.generate(
            PlanningRequest(goal="select", discovery_queries=(DiscoveryQuery("select"),)),
            DiscoverySnapshot((cast(OperatorCard, registry.get_card("select@2.0.0")),)),
            None,
        )
