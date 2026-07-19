from __future__ import annotations

import copy
from typing import Any, cast

import pytest

from blue_data_ops.operators import MultipartQueryOperator, default_registry
from blue_data_ops.plan import NodeType
from tests.unit.operators._plan_operator_helpers import (
    assert_registry_resolves,
    assert_roundtrip,
    cte,
    edge_names,
    edges,
    operator_ids,
    operator_records,
)


def test_compute_interface_explainer_and_direct_validator() -> None:
    op = MultipartQueryOperator()
    assert op.apply([[]], {}) == [[]]
    assert op.name == "multipart_query"
    assert op.description == (
        "Orchestrates the execution of multi-part query, starting with data discovery, "
        "leading to execution"
    )
    assert op.PROPERTIES == {"refine": True}
    assert op.attributes["serialize"].default is True
    assert op.explain([[{"x": 1}]], [[]], {"serialize": False}) == {
        "output": [[{"x": 1}]],
        "input_data": [[]],
        "attributes": {"serialize": False},
        "explanation": "multipart query orchestrated the execution of...",
    }
    for attributes, expected in [
        ({}, True),
        ({"serialize": True}, True),
        ({"serialize": "false"}, True),
        ({"serialize": 0}, True),
        ({"serialize": None}, False),
    ]:
        assert op.validate(attributes, {}) is expected


def test_canonical_validator_invocation_defect() -> None:
    op = MultipartQueryOperator()
    with pytest.raises(
        TypeError,
        match="default_attributes_validator.*unexpected keyword argument 'input_data'",
    ):
        op.validate(input_data=[[]], attributes={}, properties={})
    with pytest.raises(TypeError, match="unexpected keyword argument 'input_data'"):
        op.invoke([[]], {}, {})


def test_zero_and_empty_alternatives() -> None:
    op = MultipartQueryOperator()
    assert op.refiner([], {}) == []
    [plan] = op.refiner([[]], {})
    assert operator_ids(plan) == ["create_database@1.0.0"]
    assert edge_names(plan) == {
        (str(NodeType.INPUT), "create_database@1.0.0"),
        ("create_database@1.0.0", str(NodeType.OUTPUT)),
    }
    assert_roundtrip(plan)


def test_independent_cte_attributes_and_generality() -> None:
    columns = [{"name": "answer", "type": "str"}]
    plan = MultipartQueryOperator().refiner(
        [[cte("facts", description="find facts", columns=columns, generality=5)]],
        {},
    )[0]
    records = operator_records(plan)
    assert [operator_id for operator_id, _, _ in records] == [
        "create_database@1.0.0",
        "data_discover@1.0.0",
        "create_table@1.0.0",
        "nl2query_router@1.0.0",
        "insert_table@1.0.0",
    ]
    db_name = cast(str, records[0][1]["database"])
    assert db_name == "db_" + cast(str, plan["id"])
    assert records[0][1] == {"source": "internal", "database": db_name}
    assert records[1][1] == {
        "search_query": "general knowledge",
        "approximate": True,
        "concept_type": "source",
        "limit": 1,
        "filter_names": ["internal"],
        "use_hierarchical_search": False,
    }
    assert records[2][1] == {
        "source": "internal",
        "database": db_name,
        "table": "facts",
        "columns": columns,
    }
    assert records[3][1] == {
        "search_query": "find facts",
        "execute_query": True,
        "columns": columns,
    }
    assert records[4][1] == {
        "source": "internal",
        "database": db_name,
        "table": "facts",
    }
    assert_registry_resolves(plan, default_registry())
    assert_roundtrip(plan)
    assert "/server/" not in repr(plan)


def test_dependent_cte_path_and_attributes() -> None:
    base = cte("base")
    child = cte(
        "child",
        description="join base",
        dependency=["base"],
        columns=[{"name": "joined"}],
    )
    plan = MultipartQueryOperator().refiner([[base, child]], {"serialize": False})[0]
    records = operator_records(plan)
    assert operator_ids(plan) == [
        "create_database@1.0.0",
        "data_discover@1.0.0",
        "create_table@1.0.0",
        "nl2query_router@1.0.0",
        "insert_table@1.0.0",
        "create_table@1.0.0",
        "nl2sql@1.0.0",
        "insert_table@1.0.0",
    ]
    db_name = records[0][1]["database"]
    assert records[6][1] == {
        "question": "join base",
        "protocol": "sqlite",
        "source": "internal",
        "database": db_name,
        "collection": "public",
        "attr_names": ["joined"],
        "execute_query": True,
    }
    assert (
        cast(str, records[4][2]["id"]),
        cast(str, records[5][2]["id"]),
    ) in edges(plan)
    assert (cast(str, records[7][2]["id"]), cast(str, plan["output"])) in edges(plan)
    assert_roundtrip(plan)


def test_serialized_topology_is_one_chain_in_input_order() -> None:
    plan = MultipartQueryOperator().refiner(
        [[cte("base"), cte("child", dependency=["base"])]],
        {"serialize": True},
    )[0]
    records = operator_records(plan)
    create_database = records[0][2]
    base_start = records[1][2]
    base_end = records[4][2]
    child_start = records[5][2]
    child_end = records[7][2]
    actual = edges(plan)
    assert (cast(str, create_database["id"]), cast(str, base_start["id"])) in actual
    assert (cast(str, base_end["id"]), cast(str, child_start["id"])) in actual
    assert (cast(str, child_end["id"]), cast(str, plan["output"])) in actual


def test_branch_topology_fans_all_sinks_into_output_by_membership() -> None:
    plan = MultipartQueryOperator().refiner(
        [[cte("a"), cte("b"), cte("c")]],
        {"serialize": False},
    )[0]
    records = operator_records(plan)
    root_id = cast(str, records[0][2]["id"])
    starts = [cast(str, records[index][2]["id"]) for index in (1, 5, 9)]
    ends = [cast(str, records[index][2]["id"]) for index in (4, 8, 12)]
    actual = edges(plan)
    assert {(root_id, start) for start in starts} <= actual
    assert {(end, cast(str, plan["output"])) for end in ends} <= actual


def test_alternative_order_and_missing_field_drop() -> None:
    invalid = cte("bad")
    del invalid["sql"]
    properties = {"caller": {"live": True}}
    plans = MultipartQueryOperator().refiner(
        [[cte("first")], [invalid], [cte("third")]],
        {},
        properties,
    )
    assert len(plans) == 2
    assert [operator_records(plan)[2][1]["table"] for plan in plans] == ["first", "third"]
    assert all(plan["properties"] == properties for plan in plans)


@pytest.mark.parametrize(
    "plan",
    [
        [cte("child", dependency=["base"]), cte("base")],
        [cte("child", dependency=["missing"])],
        [cte("base"), cte("child", dependency=["base", "base"])],
    ],
)
def test_dependency_ordering_errors_propagate(plan: list[dict[str, Any]]) -> None:
    with pytest.raises(KeyError):
        MultipartQueryOperator().refiner([plan], {})


def test_malformed_values_propagate() -> None:
    with pytest.raises(TypeError):
        MultipartQueryOperator().refiner([[cte("x", generality="high")]], {})
    with pytest.raises(KeyError, match="name"):
        MultipartQueryOperator().refiner(
            [[cte("base"), cte("child", dependency=["base"], columns=[{"type": "str"}])]],
            {},
        )


def test_caller_records_are_read_not_mutated() -> None:
    records = [[cte("x")]]
    original = copy.deepcopy(records)
    MultipartQueryOperator().refiner(records, {"serialize": False})
    assert records == original
