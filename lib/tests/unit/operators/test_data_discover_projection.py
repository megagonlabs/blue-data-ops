"""Discovery result fields are limited to registry identities."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

pytest.importorskip("blue_data")

import blue_data_ops.operators.data_discover_operator as discover_module  # noqa: E402
from blue_data_ops.data import RegistrySeam  # noqa: E402
from blue_data_ops.operators import versioned_registry  # noqa: E402
from blue_data_ops.operators.data_discover_operator import DataDiscoverOperator  # noqa: E402
from tests.doubles.data import RegistrySeamDouble  # noqa: E402

INPUT: list[list[dict[str, Any]]] = [[]]
MARKER = "synthetic-credential-value"


class _Seam(RegistrySeamDouble, RegistrySeam):
    pass


def _seam(concept_type: str = "source", kind: object = "sql") -> _Seam:
    seam = _Seam()
    seam.search_pages = {
        0: [
            {
                "name": "jobs_db",
                "type": concept_type,
                "id": f"/{concept_type}/jobs_db",
                "scope": "/",
                "score": 0.1,
            }
        ]
    }
    seam.records[("jobs_db", concept_type, "/")] = {
        "description": f"password={MARKER}",
        "properties": {
            "kind": kind,
            "connection": {"host": "db.local", "password": MARKER},
            "custom": MARKER,
        },
        "metadata": {"owner": "example", "token": MARKER},
    }
    return seam


def _discover(seam: _Seam, concept_type: str = "source") -> dict[str, Any]:
    output = DataDiscoverOperator().apply(
        INPUT,
        {"search_query": "jobs", "approximate": True, "concept_type": concept_type},
        {"data_registry": seam},
    )
    return output[0][0]


def test_source_result_keeps_only_identity_and_known_kind() -> None:
    seam = _seam()
    before = deepcopy(seam.records)

    assert _discover(seam) == {
        "type": "source",
        "name": "jobs_db",
        "id": "/source/jobs_db",
        "scope": "/",
        "score": 0.1,
        "properties": {"kind": "sql"},
    }
    assert seam.records == before


def test_reference_catalog_success() -> None:
    output, output_attributes, meta = DataDiscoverOperator().run(
        INPUT, {"search_query": "jobs", "approximate": True}, {"data_registry": _seam()}
    )
    assert meta.errors == []
    assert meta.is_empty is False
    assert output_attributes == {}
    assert output == [
        [
            {
                "type": "source",
                "name": "jobs_db",
                "id": "/source/jobs_db",
                "scope": "/",
                "score": 0.1,
                "properties": {"kind": "sql"},
            }
        ]
    ]


def test_reference_catalog_empty() -> None:
    seam = _Seam()
    output, output_attributes, meta = DataDiscoverOperator().run(
        INPUT, {"search_query": "absent", "approximate": True}, {"data_registry": seam}
    )
    assert output == [[]]
    assert output_attributes == {}
    assert meta.is_empty is True
    assert meta.errors == []


def test_reference_catalog_invalid() -> None:
    output, output_attributes, meta = DataDiscoverOperator().run(
        INPUT, {"search_query": " ", "approximate": True}, {"data_registry": _seam()}
    )
    assert output == [[]]
    assert output_attributes == {}
    assert meta.is_empty is False
    assert len(meta.errors) == 1
    assert meta.errors[0].code == "INVALID_INPUT"
    assert meta.errors[0].stage == "VALIDATE"


def test_reference_catalog_failure() -> None:
    class RaisingSeam(_Seam):
        def search_records_hierarchical(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
            raise RuntimeError("synthetic registry failure")

    output, output_attributes, meta = DataDiscoverOperator().run(
        INPUT, {"search_query": "jobs", "approximate": True}, {"data_registry": RaisingSeam()}
    )
    assert output == [[]]
    assert output_attributes == {}
    assert meta.is_empty is False
    assert len(meta.errors) == 1
    assert meta.errors[0].code == "EXECUTION_FAILED"
    assert meta.errors[0].stage == "EXECUTE"


@pytest.mark.parametrize(
    "stored",
    [
        f"postgresql://reader:{MARKER}@db.local/jobs",
        f"postgresql://db.local/jobs?password={MARKER}",
        f"jdbc:sqlserver://db.local;password={MARKER};",
        f"Driver=X;Pwd={{alpha {MARKER}}};Server=db.local",
        f"postgresql://db.local/jobs?api%5Fkey={MARKER}",
        f"postgresql://db.local/jobs?api+key={MARKER}",
        f"Driver=X; api key={MARKER}; Server=db.local",
        f"password={MARKER}",
    ],
)
def test_connection_spellings_never_enter_source_result(stored: str) -> None:
    seam = _seam()
    seam.records[("jobs_db", "source", "/")]["properties"]["custom"] = stored
    seam.records[("jobs_db", "source", "/")]["description"] = stored

    assert MARKER not in repr(_discover(seam))


@pytest.mark.parametrize("kind", ["unknown", f"sql:{MARKER}", 4, ["sql"], {"name": "sql"}])
def test_unrecognized_source_kind_is_omitted(kind: object) -> None:
    assert "properties" not in _discover(_seam(kind=kind))


@pytest.mark.parametrize(
    "kind", ["file", "graph", "json", "network", "redis", "sql", "stream", "vector"]
)
def test_known_source_kind_is_returned(kind: str) -> None:
    assert _discover(_seam(kind=kind))["properties"] == {"kind": kind}


@pytest.mark.parametrize(
    "concept_type", ["database", "collection", "entity", "relation", "attribute"]
)
def test_other_record_types_do_not_read_free_form_fields(concept_type: str) -> None:
    seam = _seam(concept_type)
    assert _discover(seam, concept_type) == {
        "type": concept_type,
        "name": "jobs_db",
        "id": f"/{concept_type}/jobs_db",
        "scope": "/",
        "score": 0.1,
    }
    assert seam.calls_to("get_record") == []


@pytest.mark.parametrize("version", ["1.0.0", "2.0.0"])
def test_historical_versions_use_the_same_catalog_boundary(version: str) -> None:
    operator = versioned_registry().resolve(f"data_discover@{version}")
    output, _, meta = operator.run(
        INPUT, {"search_query": "jobs", "approximate": True}, {"data_registry": _seam()}
    )
    assert meta.errors == []
    assert output[0][0]["properties"] == {"kind": "sql"}
    assert "description" not in output[0][0]
    assert "metadata" not in output[0][0]


@pytest.mark.parametrize("concept_type", ["source", "entity"])
def test_include_metadata_is_an_explicit_error(concept_type: str) -> None:
    operator = DataDiscoverOperator()
    output, _, meta = operator.run(
        INPUT,
        {
            "search_query": "jobs",
            "approximate": True,
            "concept_type": concept_type,
            "include_metadata": True,
        },
        {"data_registry": _seam(concept_type)},
    )
    assert output == [[]]
    assert len(meta.errors) == 1
    assert "include_metadata must be false" in (meta.errors[0].suggestion or "")


def test_registry_exception_text_stays_out_of_logs(caplog: pytest.LogCaptureFixture) -> None:
    class RaisingSeam(_Seam):
        def search_records_hierarchical(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
            raise RuntimeError(f"password={MARKER}")

    output, _, meta = DataDiscoverOperator().run(
        INPUT, {"search_query": "jobs", "approximate": True}, {"data_registry": RaisingSeam()}
    )
    assert output == [[]]
    assert len(meta.errors) == 1
    assert MARKER not in caplog.text
    assert MARKER not in repr(meta.errors)


def test_registry_resolution_error_is_raw_in_apply_and_contained_in_run(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def fail_resolution(_: object) -> RegistrySeam:
        raise RuntimeError(f"password={MARKER}")

    monkeypatch.setattr(discover_module, "resolve_registry", fail_resolution)
    operator = DataDiscoverOperator()
    with pytest.raises(RuntimeError):
        operator.apply(INPUT, {"search_query": "jobs"})
    output, _, meta = operator.run(INPUT, {"search_query": "jobs"})
    assert output == [[]]
    assert len(meta.errors) == 1
    assert MARKER not in repr(meta.errors)
    assert MARKER not in caplog.text
