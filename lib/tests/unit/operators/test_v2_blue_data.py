from __future__ import annotations

from copy import deepcopy
from typing import Any, cast
from unittest.mock import patch

import pytest

blue_data = pytest.importorskip("blue_data")

from blue_data_ops import (  # noqa: E402
    ErrorCategory,
    ErrorCode,
    ErrorStage,
    FunctionResult,
    ValidationResult,
)
from blue_data_ops.data import RegistrySeam  # noqa: E402
from blue_data_ops.operators import (  # noqa: E402
    Attributes,
    CreateDatabaseOperator,
    CreateTableOperator,
    DataBundle,
    DataDiscoverOperator,
    InsertTableOperator,
    Operator,
    OperatorRegistry,
)
from tests.doubles.data import RegistrySeamDouble, SQLSourceDouble  # noqa: E402

INPUT: DataBundle = [[{"name": "row", "value": 1}]]
ROWS: DataBundle = [[{"a": 1}, {"a": 2}]]
EMPTY_INPUT: DataBundle = [[]]
CREATE_DATABASE: Attributes = {"source": "src", "database": "db"}
CREATE_TABLE: Attributes = {
    "source": "src",
    "database": "db",
    "table": "t",
    "columns": [{"name": "a", "type": "INTEGER"}],
}
DISCOVER: Attributes = {"search_query": "orders", "approximate": False}
INSERT: Attributes = {"source": "src", "database": "db", "table": "t"}


class _Seam(RegistrySeamDouble, RegistrySeam):
    pass


class _CreateDatabaseFailure(_Seam):
    def create_source_database(self, *args: Any, **kwargs: Any) -> None:
        super().create_source_database(*args, **kwargs)
        raise RuntimeError("registry detail must stay private")


class _CreateTableFailure(_Seam):
    def create_source_database_collection_entity(self, *args: Any, **kwargs: Any) -> None:
        super().create_source_database_collection_entity(*args, **kwargs)
        raise RuntimeError("registry detail must stay private")


class _CreateDatabaseMetadataFailure(_Seam):
    def set_source_database_description(self, *args: Any, **kwargs: Any) -> None:
        super().set_source_database_description(*args, **kwargs)
        raise RuntimeError("metadata detail must stay private")


class _CreateTableMetadataFailure(_Seam):
    def set_source_database_collection_entity_description(self, *args: Any, **kwargs: Any) -> None:
        super().set_source_database_collection_entity_description(*args, **kwargs)
        raise RuntimeError("metadata detail must stay private")


class _ProbeFailure(_Seam):
    def get_source_properties(self, source: str) -> dict[str, Any]:
        super().get_source_properties(source)
        raise RuntimeError("probe detail")


class _SearchFailure(_Seam):
    def search_records_hierarchical(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        del args, kwargs
        raise RuntimeError("search detail must stay private")


class _ProgressiveSearchFailure(_Seam):
    def __init__(self) -> None:
        super().__init__()
        self.attempted_pages: list[int] = []

    def search_records_hierarchical(
        self, *args: Any, page: int = 0, **kwargs: Any
    ) -> list[dict[str, Any]]:
        self.attempted_pages.append(page)
        if page == 1:
            raise RuntimeError("later page detail must stay private")
        return super().search_records_hierarchical(*args, page=page, **kwargs)


def _properties(seam: RegistrySeam) -> dict[str, Any]:
    return {"data_registry": seam}


def _insert_seam() -> _Seam:
    seam = _Seam()
    seam.sources["src"] = SQLSourceDouble("src")
    return seam


def _assert_execution_failure(
    result: tuple[DataBundle, Attributes, Any],
    operator_id: str,
) -> None:
    output_data, output_attributes, meta = result
    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is False
    assert len(meta.errors) == 1
    error = meta.errors[0]
    assert error.category is ErrorCategory.FAILED
    assert error.code is ErrorCode.EXECUTION_FAILED
    assert error.stage is ErrorStage.EXECUTE
    assert error.operator_id == operator_id
    assert error.retryable is False


@pytest.mark.parametrize(
    "operator_type",
    [CreateDatabaseOperator, CreateTableOperator, DataDiscoverOperator, InsertTableOperator],
)
def test_blue_data_operators_own_native_hooks(operator_type: type[Operator]) -> None:
    assert "_execute" in operator_type.__dict__
    assert "_validate_input" in operator_type.__dict__


@pytest.mark.parametrize(
    ("operator", "input_data", "valid", "invalid"),
    [
        (CreateDatabaseOperator(), INPUT, CREATE_DATABASE, {"database": "db"}),
        (CreateTableOperator(), INPUT, CREATE_TABLE, {**CREATE_TABLE, "columns": []}),
        (DataDiscoverOperator(), EMPTY_INPUT, DISCOVER, {**DISCOVER, "search_query": " "}),
        (InsertTableOperator(), ROWS, INSERT, {**INSERT, "batch_size": 0}),
    ],
)
def test_structured_validation_preserves_boolean_adapter(
    operator: Operator,
    input_data: DataBundle,
    valid: Attributes,
    invalid: Attributes,
) -> None:
    valid_result = operator._validate_input(input_data, valid)  # pyright: ignore[reportPrivateUsage]
    invalid_result = operator._validate_input(  # pyright: ignore[reportPrivateUsage]
        input_data, invalid
    )

    assert type(valid_result) is ValidationResult
    assert valid_result == ValidationResult(True, None)
    assert type(invalid_result) is ValidationResult
    assert invalid_result.ok is False
    assert invalid_result.reason
    assert operator.validate(input_data, valid) is True
    assert operator.validate(input_data, invalid) is False


@pytest.mark.parametrize(
    ("operator", "input_data", "attributes", "legacy_empty"),
    [
        (CreateDatabaseOperator(), INPUT, CREATE_DATABASE, False),
        (CreateTableOperator(), INPUT, CREATE_TABLE, False),
        (DataDiscoverOperator(), EMPTY_INPUT, DISCOVER, True),
        (InsertTableOperator(), ROWS, INSERT, False),
    ],
)
def test_missing_registry_keeps_raw_fallback_but_run_reports_failure(
    operator: Operator,
    input_data: DataBundle,
    attributes: Attributes,
    legacy_empty: bool,
) -> None:
    legacy_output = operator.apply(input_data, attributes)
    if legacy_empty:
        assert legacy_output == [[]]
    else:
        assert legacy_output is input_data

    result = operator.run(input_data, attributes)
    _assert_execution_failure(result, f"{operator.name}@2.0.0")


@pytest.mark.parametrize(
    ("operator", "input_data", "attributes", "module_name"),
    [
        (
            CreateDatabaseOperator(),
            INPUT,
            CREATE_DATABASE,
            "blue_data_ops.operators.create_database_operator.resolve_registry",
        ),
        (
            CreateTableOperator(),
            INPUT,
            CREATE_TABLE,
            "blue_data_ops.operators.create_table_operator.resolve_registry",
        ),
        (
            DataDiscoverOperator(),
            EMPTY_INPUT,
            DISCOVER,
            "blue_data_ops.operators.data_discover_operator.resolve_registry",
        ),
        (
            InsertTableOperator(),
            ROWS,
            INSERT,
            "blue_data_ops.operators.insert_table_operator.resolve_registry",
        ),
    ],
)
def test_resolver_failure_stays_raw_and_run_contains_it(
    operator: Operator,
    input_data: DataBundle,
    attributes: Attributes,
    module_name: str,
) -> None:
    with patch(module_name, side_effect=RuntimeError("resolver detail must stay private")):
        with pytest.raises(RuntimeError, match="resolver detail"):
            operator.apply(input_data, attributes, {"data_registry.name": "registry"})

        result = operator.run(input_data, attributes, {"data_registry.name": "registry"})

    _assert_execution_failure(result, f"{operator.name}@2.0.0")
    assert "resolver detail" not in result[2].errors[0].message


@pytest.mark.parametrize(
    ("operator", "attributes", "seam"),
    [
        (CreateDatabaseOperator(), CREATE_DATABASE, _CreateDatabaseFailure()),
        (CreateTableOperator(), CREATE_TABLE, _CreateTableFailure()),
    ],
)
def test_create_failure_keeps_pass_through_but_run_reports_failure(
    operator: Operator,
    attributes: Attributes,
    seam: RegistrySeam,
) -> None:
    assert operator.apply(INPUT, attributes, _properties(seam)) is INPUT

    result = operator.run(INPUT, attributes, _properties(seam))
    _assert_execution_failure(result, f"{operator.name}@2.0.0")
    assert "registry detail" not in result[2].errors[0].message


@pytest.mark.parametrize(
    ("operator", "attributes", "seam", "record_key", "create_method"),
    [
        (
            CreateDatabaseOperator(),
            {**CREATE_DATABASE, "description": "created before metadata fails"},
            _CreateDatabaseMetadataFailure(),
            ("db", "database", "/source/src"),
            "create_source_database",
        ),
        (
            CreateTableOperator(),
            {**CREATE_TABLE, "description": "created before metadata fails"},
            _CreateTableMetadataFailure(),
            ("t", "entity", "/source/src/database/db/collection/public"),
            "create_source_database_collection_entity",
        ),
    ],
)
def test_post_create_metadata_failure_reports_non_retryable_partial_side_effect(
    operator: Operator,
    attributes: Attributes,
    seam: _Seam,
    record_key: tuple[str, str, str],
    create_method: str,
) -> None:
    result = operator.run(INPUT, attributes, _properties(seam))

    _assert_execution_failure(result, f"{operator.name}@2.0.0")
    assert result[2].errors[0].retryable is False
    assert seam.records[record_key]["name"] == record_key[0]
    assert len(seam.calls_to(create_method)) == 1


def test_create_table_probe_failure_remains_successful() -> None:
    operator = CreateTableOperator()
    seam = _ProbeFailure()

    assert operator.apply(INPUT, CREATE_TABLE, _properties(seam)) is INPUT
    output_data, output_attributes, meta = operator.run(INPUT, CREATE_TABLE, _properties(seam))

    assert output_data is INPUT
    assert output_attributes == {}
    assert meta.errors == []


def test_insert_table_probe_failure_remains_successful() -> None:
    operator = InsertTableOperator()
    seam = _ProbeFailure()
    source = SQLSourceDouble("src")
    seam.sources["src"] = source

    output_data, output_attributes, meta = operator.run(ROWS, INSERT, _properties(seam))

    assert output_data == ROWS
    assert output_attributes == {}
    assert meta.errors == []
    assert len(seam.calls_to("get_source_properties")) == 1
    assert source.connections["db"].commits == 1


def test_create_table_run_does_not_mutate_caller_misc() -> None:
    operator = CreateTableOperator()
    seam = _Seam()
    misc: dict[str, Any] = {"primary_key": ["a"]}
    attributes = {**CREATE_TABLE, "misc": misc}

    output_data, _, meta = operator.run(INPUT, attributes, _properties(seam))

    assert output_data is INPUT
    assert meta.errors == []
    assert misc == {"primary_key": ["a"]}
    creation = seam.calls_to("create_source_database_collection_entity")[0]
    assert creation["creation_properties"] == {
        "primary_key": ["a"],
        "cols_definition": CREATE_TABLE["columns"],
    }
    assert creation["creation_properties"] is not misc


def test_discovery_failure_and_genuine_empty_are_distinct() -> None:
    operator = DataDiscoverOperator()
    failing = _SearchFailure()
    empty = _Seam()

    assert operator.apply([[]], DISCOVER, _properties(failing)) == [[]]
    _assert_execution_failure(
        operator.run([[]], DISCOVER, _properties(failing)),
        "data_discover@2.0.0",
    )

    output_data, output_attributes, meta = operator.run([[]], DISCOVER, _properties(empty))
    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is True
    assert meta.errors == []


def test_discovery_string_page_keeps_raw_validator_error_and_run_contains_it() -> None:
    operator = DataDiscoverOperator()
    attributes = {**DISCOVER, "page": "0"}

    with pytest.raises(TypeError):
        operator.validate([[]], attributes)

    output_data, output_attributes, meta = operator.run([[]], attributes)
    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.errors[0].category is ErrorCategory.FAILED
    assert meta.errors[0].code is ErrorCode.VALIDATION_FAILED
    assert meta.errors[0].stage is ErrorStage.VALIDATE


def test_discovery_limit_zero_calls_provider_and_succeeds_empty() -> None:
    operator = DataDiscoverOperator()
    seam = _Seam()
    seam.search_pages[0] = [
        {"name": "orders", "id": "orders-id", "scope": "/source/src", "score": 0.1}
    ]
    attributes = {**DISCOVER, "limit": 0}

    output_data, output_attributes, meta = operator.run([[]], attributes, _properties(seam))

    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is True
    assert meta.errors == []
    calls = seam.calls_to("search_records_hierarchical")
    assert len(calls) == 1
    assert calls[0]["page"] == 0


@pytest.mark.parametrize(
    "attributes",
    [
        {**DISCOVER, "approximate": True, "threshold": 0.5},
        {**DISCOVER, "filter_names": ["orders"]},
    ],
)
def test_discovery_threshold_and_name_filter_empties_are_successful(
    attributes: Attributes,
) -> None:
    operator = DataDiscoverOperator()
    seam = _Seam()
    seam.search_pages[0] = [
        {"name": "orders", "id": "orders-id", "scope": "/source/src", "score": 0.9}
    ]

    output_data, output_attributes, meta = operator.run([[]], attributes, _properties(seam))

    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is True
    assert meta.errors == []
    assert len(seam.calls_to("search_records_hierarchical")) == 1


def test_discovery_progressive_later_page_failure_is_canonical_failure() -> None:
    operator = DataDiscoverOperator()
    seam = _ProgressiveSearchFailure()
    seam.search_pages[0] = [
        {"name": "orders", "id": "orders-id", "scope": "/source/src", "score": 0.1}
    ]
    attributes = {
        **DISCOVER,
        "approximate": True,
        "progressive_pagination": True,
        "threshold": 0.5,
    }

    assert operator.apply([[]], attributes, _properties(seam)) == [[]]
    result = operator.run([[]], attributes, _properties(seam))

    _assert_execution_failure(result, "data_discover@2.0.0")
    assert "later page detail" not in result[2].errors[0].message
    assert seam.attempted_pages == [0, 1, 0, 1]


@pytest.mark.parametrize(
    ("attributes", "exception_type"),
    [
        ({**DISCOVER, "limit": "0"}, TypeError),
        ({**DISCOVER, "scope": b"/source/src"}, TypeError),
    ],
)
def test_discovery_invalid_runtime_shapes_stay_raw_but_are_contained_canonically(
    attributes: Attributes,
    exception_type: type[Exception],
) -> None:
    operator = DataDiscoverOperator()
    seam = _Seam()

    with pytest.raises(exception_type):
        operator.apply([[]], attributes, _properties(seam))

    output_data, output_attributes, meta = operator.run([[]], attributes, _properties(seam))
    _assert_execution_failure(
        (output_data, output_attributes, meta),
        "data_discover@2.0.0",
    )


def test_insert_empty_first_group_is_a_successful_empty() -> None:
    operator = InsertTableOperator()
    seam = _insert_seam()
    input_data: DataBundle = [[], [{"a": 1}]]

    assert operator.apply(input_data, INSERT, _properties(seam)) == [[]]
    output_data, output_attributes, meta = operator.run(input_data, INSERT, _properties(seam))

    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is True
    assert meta.errors == []


def test_insert_batch_failure_keeps_raw_empty_but_run_reports_failure() -> None:
    operator = InsertTableOperator()
    seam = _insert_seam()

    with patch(
        "blue_data_ops.operators.insert_table_operator._insert_data_group",
        return_value=None,
    ):
        assert operator.apply(ROWS, INSERT, _properties(seam)) == [[]]
        result = operator.run(ROWS, INSERT, _properties(seam))

    _assert_execution_failure(result, "insert_table@2.0.0")


def test_insert_late_batch_failure_keeps_first_commit_observable() -> None:
    operator = InsertTableOperator()
    seam = _insert_seam()
    source = cast(SQLSourceDouble, seam.sources["src"])
    connection = source._db_connect("db")  # pyright: ignore[reportPrivateUsage]
    cursor = connection.cursor_double
    original_executemany = cursor.executemany
    calls = 0

    def fail_second_batch(query: str, rows: list[Any]) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("second batch detail must stay private")
        original_executemany(query, rows)

    with patch.object(cursor, "executemany", side_effect=fail_second_batch):
        result = operator.run(
            ROWS,
            {**INSERT, "batch_size": 1},
            _properties(seam),
        )

    _assert_execution_failure(result, "insert_table@2.0.0")
    assert "second batch detail" not in result[2].errors[0].message
    assert connection.commits == 1
    assert cursor.executed == [('INSERT INTO "t" ("a") VALUES (?)', [(1,)])]
    assert source.disconnects == 2


def test_insert_outer_failure_keeps_raw_input_but_run_reports_failure() -> None:
    operator = InsertTableOperator()
    seam = _insert_seam()

    with patch(
        "blue_data_ops.operators.insert_table_operator._insert_data_group",
        side_effect=RuntimeError("outer detail must stay private"),
    ):
        assert operator.apply(ROWS, INSERT, _properties(seam)) is ROWS
        result = operator.run(ROWS, INSERT, _properties(seam))

    _assert_execution_failure(result, "insert_table@2.0.0")
    assert "outer detail" not in result[2].errors[0].message


def test_successful_native_bodies_execute_once_and_return_fresh_attributes() -> None:
    cases: list[tuple[Operator, DataBundle, Attributes, RegistrySeam]] = [
        (CreateDatabaseOperator(), INPUT, CREATE_DATABASE, _Seam()),
        (CreateTableOperator(), INPUT, CREATE_TABLE, _Seam()),
        (DataDiscoverOperator(), [[]], DISCOVER, _Seam()),
        (InsertTableOperator(), ROWS, INSERT, _insert_seam()),
    ]

    for operator, input_data, attributes, seam in cases:
        before = deepcopy(attributes)
        with patch.object(
            operator,
            "_execute",
            wraps=operator._execute,  # pyright: ignore[reportPrivateUsage]
        ) as execute:
            output_data, output_attributes, meta = operator.run(
                input_data, attributes, _properties(seam)
            )
        second_attributes = operator.run(input_data, attributes, _properties(seam))[1]

        assert execute.call_count == 1
        assert type(operator._execute(input_data, attributes, _properties(seam))) is FunctionResult  # pyright: ignore[reportPrivateUsage]
        assert output_data == operator.apply(input_data, attributes, _properties(seam))
        assert output_attributes == {}
        assert output_attributes is not second_attributes
        assert meta.errors == []
        assert attributes == before


@pytest.mark.parametrize(
    ("operator", "input_data", "attributes"),
    [
        (CreateDatabaseOperator(), INPUT, CREATE_DATABASE),
        (CreateTableOperator(), INPUT, CREATE_TABLE),
        (DataDiscoverOperator(), EMPTY_INPUT, DISCOVER),
        (InsertTableOperator(), ROWS, INSERT),
    ],
)
def test_selected_versions_keep_exact_blue_data_error_identity(
    operator: Operator,
    input_data: DataBundle,
    attributes: Attributes,
) -> None:
    registry = OperatorRegistry()
    registry.register(operator, "1.0.0")
    registry.register(operator, "2.0.0")

    for version in ("1.0.0", "2.0.0"):
        operator_id = f"{operator.name}@{version}"
        resolved = registry.resolve(operator_id)
        result = resolved.run(input_data, attributes)
        _assert_execution_failure(result, operator_id)


def test_raw_v1_create_table_still_mutates_caller_misc() -> None:
    operator = CreateTableOperator()
    seam = _Seam()
    misc: dict[str, Any] = {"primary_key": ["a"]}
    attributes = cast(Attributes, {**CREATE_TABLE, "misc": misc})

    operator.apply(INPUT, attributes, _properties(seam))

    assert misc["cols_definition"] == CREATE_TABLE["columns"]
