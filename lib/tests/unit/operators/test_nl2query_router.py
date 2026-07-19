from __future__ import annotations

import copy
from typing import Any

import pytest

from blue_data_ops.operators import NL2QueryRouterOperator, default_registry
from blue_data_ops.operators.nl2query_router_operator import parse_scope
from tests.unit.operators._plan_operator_helpers import (
    assert_registry_resolves,
    assert_roundtrip,
    edge_names,
    operator_ids,
    operator_records,
)

ATTRIBUTES: dict[str, Any] = {
    "search_query": "find rows",
    "columns": [{"name": "value"}],
    "execute_query": False,
    "protocol": "sqlite",
}


def _source(name: str, protocol: str = "sqlite") -> dict[str, Any]:
    return {
        "name": name,
        "type": "source",
        "scope": f"/source/{name}",
        "properties": {"connection": {"protocol": protocol}, "owner": name},
    }


def _collection(name: str = "items") -> dict[str, Any]:
    return {
        "name": name,
        "type": "collection",
        "scope": "/source/s/database/d/collection/items",
    }


def test_compute_interface_and_explainer() -> None:
    op = NL2QueryRouterOperator()
    assert op.apply([[]], dict(ATTRIBUTES)) == [[]]
    assert op.name == "nl2query_router"
    assert op.description == "Routees the execution of query, based on source"
    assert op.PROPERTIES == {"refine": True}
    assert [spec.default for spec in op.attributes.values()] == [None, [], True, ""]
    assert op.explain([[{"x": 1}]], [[]], dict(ATTRIBUTES)) == {
        "output": [[{"x": 1}]],
        "input_data": [[]],
        "attributes": ATTRIBUTES,
        "explanation": "routes the execution of query to...",
    }


def test_guards_and_first_group_only() -> None:
    op = NL2QueryRouterOperator()
    assert op.refiner([], dict(ATTRIBUTES)) == []
    assert op.refiner([[]], dict(ATTRIBUTES)) == []
    first = _source("one", "openai")
    ignored = _source("two", "sqlite")
    plans = op.refiner([[first], [ignored]], dict(ATTRIBUTES))
    assert len(plans) == 1
    assert operator_ids(plans[0]) == ["nl2llm@1.0.0"]


@pytest.mark.parametrize(
    "protocol, expected",
    [
        ("openai", ["nl2llm@1.0.0"]),
        ("postgres", ["data_discover@1.0.0", "nl2query_router@1.0.0"]),
        ("mysql", ["data_discover@1.0.0", "nl2query_router@1.0.0"]),
        ("sqlite", ["data_discover@1.0.0", "nl2query_router@1.0.0"]),
    ],
)
def test_source_routing(protocol: str, expected: list[str]) -> None:
    plan = NL2QueryRouterOperator().refiner([[_source("s", protocol)]], dict(ATTRIBUTES))[0]
    assert operator_ids(plan) == expected
    records = operator_records(plan)
    if protocol == "openai":
        assert records[0][1] == {
            "source": "s",
            "query": "find rows",
            "attrs": [{"name": "value"}],
        }
    else:
        assert records[0][1] == {
            "source": "s",
            "scope": "/source/s",
            "search_query": "find rows",
            "approximate": True,
            "concept_type": "collection",
            "limit": 1,
            "use_hierarchical_search": True,
        }
        assert records[1][1]["execute_query"] is True
    assert_roundtrip(plan)
    assert_registry_resolves(plan, default_registry())
    assert "/server/" not in repr(plan)


@pytest.mark.parametrize(
    "source",
    [
        {"name": "s", "type": "source", "scope": "/source/s"},
        {"name": "s", "type": "source", "scope": "/source/s", "properties": {}},
        {
            "name": "s",
            "type": "source",
            "scope": "/source/s",
            "properties": {"connection": {}},
        },
        _source("s", "unsupported"),
    ],
)
def test_malformed_or_unsupported_source_is_dropped(source: dict[str, Any]) -> None:
    assert NL2QueryRouterOperator().refiner([[source]], dict(ATTRIBUTES)) == []


@pytest.mark.parametrize(
    "protocol, expected",
    [
        ("openai", ["nl2llm@1.0.0"]),
        ("sqlite", ["nl2sql@1.0.0"]),
        ("unknown", []),
    ],
)
def test_collection_routing_and_disconnected_case(protocol: str, expected: list[str]) -> None:
    attributes = {**ATTRIBUTES, "protocol": protocol}
    plan = NL2QueryRouterOperator().refiner([[_collection()]], attributes)[0]
    assert operator_ids(plan) == expected
    if protocol == "openai":
        assert operator_records(plan)[0][1] == {
            "query": "find rows",
            "attrs": [{"name": "value"}],
        }
    elif protocol == "sqlite":
        assert operator_records(plan)[0][1] == {
            "question": "find rows",
            "protocol": "sqlite",
            "source": "s",
            "database": "d",
            "collection": "items",
            "attr_names": ["value"],
            "execute_query": False,
        }
    else:
        assert edge_names(plan) == set()
    assert_roundtrip(plan)


def test_unknown_record_type_is_disconnected() -> None:
    record = {"name": "x", "type": "mystery", "scope": "/"}
    plan = NL2QueryRouterOperator().refiner([[record]], dict(ATTRIBUTES))[0]
    assert operator_ids(plan) == []
    assert edge_names(plan) == set()


def test_cross_record_protocol_and_properties_leaks_without_caller_mutation() -> None:
    source = _source("llm", "openai")
    collection = _collection()
    caller_properties = {"caller": {"kept": True}}
    original_source = copy.deepcopy(source)

    plans = NL2QueryRouterOperator().refiner(
        [[source, collection]],
        dict(ATTRIBUTES),
        caller_properties,
    )

    assert [operator_ids(plan) for plan in plans] == [
        ["nl2llm@1.0.0"],
        ["nl2llm@1.0.0"],
    ]
    assert plans[0]["properties"] == caller_properties
    assert plans[1]["properties"] == source["properties"]
    assert caller_properties == {"caller": {"kept": True}}
    assert source == original_source


@pytest.mark.parametrize(
    "records, exception",
    [
        ([{"name": "c", "type": "collection", "scope": "/source/s"}], KeyError),
        ([{"name": "c", "type": "collection", "scope": "/source/s/database"}], IndexError),
    ],
)
def test_malformed_collection_scope_propagates(
    records: list[dict[str, Any]], exception: type[Exception]
) -> None:
    with pytest.raises(exception):
        NL2QueryRouterOperator().refiner([records], dict(ATTRIBUTES))


def test_malformed_collection_columns_propagate() -> None:
    with pytest.raises(TypeError):
        NL2QueryRouterOperator().refiner(
            [[_collection()]],
            {**ATTRIBUTES, "columns": None},
        )
    with pytest.raises(KeyError, match="name"):
        NL2QueryRouterOperator().refiner(
            [[_collection()]],
            {**ATTRIBUTES, "columns": [{"type": "str"}]},
        )


def test_scope_parser_exact_edges() -> None:
    assert parse_scope("/source/x") == {}
    assert parse_scope("/source/s/database/d/collection/c") == {
        "source": "s",
        "database": "d",
        "collection": "c",
    }
    with pytest.raises(IndexError, match="list index out of range"):
        parse_scope("/source/s/database")


@pytest.mark.parametrize(
    "attributes, expected",
    [
        ({"search_query": "q"}, True),
        ({}, False),
        ({"search_query": ""}, True),
        ({"search_query": b"q", "protocol": b"sqlite"}, True),
        ({"search_query": "q", "columns": ({"name": "a"},)}, True),
        ({"search_query": "q", "columns": ["bad"]}, False),
        ({"search_query": "q", "execute_query": "false"}, True),
    ],
)
def test_direct_validator(attributes: dict[str, Any], expected: bool) -> None:
    assert NL2QueryRouterOperator().validate(attributes, {}) is expected


def test_canonical_validator_invocation_defect() -> None:
    op = NL2QueryRouterOperator()
    message = "default_attributes_validator() got an unexpected keyword argument 'input_data'"
    pattern = "^" + message.replace("(", r"\(").replace(")", r"\)") + "$"
    with pytest.raises(TypeError, match=pattern):
        op.validate(input_data=[[]], attributes={"search_query": "q"}, properties={})
    with pytest.raises(TypeError, match="unexpected keyword argument 'input_data'"):
        op.invoke([[]], {"search_query": "q"}, {})
