"""Compatibility tests for NL-to-Bayesian-network execution.

The suite uses deterministic LLM and registry doubles to cover prompt bytes,
schema rendering, correction, exception boundaries, and registry execution.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import litellm  # the deterministic stub
import pytest

from blue_data_ops.llm.errors import is_reply_failure

blue_data = pytest.importorskip("blue_data")

from blue_data_ops.data import RegistrySeam  # noqa: E402
from blue_data_ops.llm import LLMError  # noqa: E402
from blue_data_ops.operators.nl2bn_operator import (  # noqa: E402
    NL2BNOperator,
    _extract_edges_info,  # pyright: ignore[reportPrivateUsage]
    _extract_node_descriptions,  # pyright: ignore[reportPrivateUsage]
    _extract_nodes_info,  # pyright: ignore[reportPrivateUsage]
    _validate_bn_query,  # pyright: ignore[reportPrivateUsage]
)
from tests.doubles.data import RegistrySeamDouble  # noqa: E402

INPUT: list[list[dict[str, Any]]] = [[]]

GRAPH: dict[str, Any] = {
    "description": "Liver disease network",
    "nodes": {
        "cirrhosis": {
            "states": ["present", "absent"],
            "description": "Liver cirrhosis",
            "states_description": {"present": "Cirrhosis observed", "absent": ""},
        },
        "alcoholism": {"states": ["yes", "no"], "description": "Alcohol abuse"},
    },
    "edges": {"alcoholism": ["cirrhosis"]},
}

ATTRS: dict[str, Any] = {
    "question": "What is the probability of cirrhosis being present given alcoholism?",
    "source": "bn_src",
    "collection": "hepar2",
}

VALID_RESPONSE = (
    '{"target_node": "cirrhosis", "target_state": "present", "context": {"alcoholism": "yes"}}'
)


class _RecordingSeam(RegistrySeamDouble, RegistrySeam):
    """The recording double, typed as a RegistrySeam so injection resolves it."""


@pytest.fixture(autouse=True)
def _reset_fake() -> None:  # pyright: ignore[reportUnusedFunction] — autouse
    litellm.calls.clear()
    litellm.fail_next.clear()


@pytest.fixture
def op() -> NL2BNOperator:
    return NL2BNOperator()


@pytest.fixture
def seam() -> _RecordingSeam:
    recording = _RecordingSeam()
    recording.schema_result = {"entities": [], "relations": [], "graph_structure": GRAPH}
    recording.query_result = [{"probability": 0.42, "explanation": "because reasons"}]
    return recording


def _props(seam: RegistrySeam, **extra: Any) -> dict[str, Any]:
    return {"data_registry": seam, **extra}


def _sequence_provider(monkeypatch: pytest.MonkeyPatch, *contents: str) -> None:
    """Provider fake: honors fail_next like the stub, then serves contents in order
    (the last one repeats)."""
    queue = list(contents)

    def fake(**kwargs: Any) -> Any:
        litellm.calls.append(kwargs)
        if litellm.fail_next:
            raise litellm.fail_next.pop(0)
        content = queue.pop(0) if len(queue) > 1 else queue[0]

        class _R:
            def model_dump(self) -> dict[str, Any]:
                return {
                    "choices": [{"message": {"role": "assistant", "content": content}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                }

        return _R()

    monkeypatch.setattr(litellm, "completion", fake)


def _prompt_of(call_index: int) -> str:
    return str(litellm.calls[call_index]["messages"][0]["content"])


# --- blank question returns [[]] without external calls ------------------------------
@pytest.mark.parametrize("question", ["", "   "])
def test_blank_question_returns_empty(
    op: NL2BNOperator, seam: _RecordingSeam, question: str
) -> None:
    assert op.apply(INPUT, {**ATTRS, "question": question}, _props(seam)) == [[]]
    assert litellm.calls == []
    assert seam.calls == []


# --- required attributes ------------------------------------------------------------
@pytest.mark.parametrize(
    "overrides",
    [{"source": ""}, {"collection": ""}, {"database": ""}, {"protocol_variant": ""}],
    ids=["source", "collection", "database", "protocol_variant"],
)
def test_missing_required_raises(
    op: NL2BNOperator, seam: _RecordingSeam, overrides: dict[str, Any]
) -> None:
    with pytest.raises(
        ValueError, match="Source, database, collection, and protocol_variant are required"
    ):
        op.apply(INPUT, {**ATTRS, **overrides}, _props(seam))


def test_unsupported_protocol_variant(op: NL2BNOperator, seam: _RecordingSeam) -> None:
    with pytest.raises(
        ValueError, match=r"Unsupported protocol_variant: bayes. Supported variants: \['pgmpy'\]"
    ):
        op.apply(INPUT, {**ATTRS, "protocol_variant": "bayes"}, _props(seam))


# --- no registry returns [[]] --------------------------------------------------------
@pytest.mark.parametrize("properties", [None, {}, {"unrelated": 1}])
def test_no_registry_returns_empty(op: NL2BNOperator, properties: dict[str, Any] | None) -> None:
    assert op.apply(INPUT, dict(ATTRS), properties) == [[]]
    assert litellm.calls == []


# --- schema resolution from registry results ----------------------------------------
def test_registry_schema_call_shape_and_database_default(
    op: NL2BNOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sequence_provider(monkeypatch, VALID_RESPONSE)
    op.apply(INPUT, dict(ATTRS), _props(seam))
    [schema_call] = seam.calls_to("get_data_source_schema")
    # Blue source's call shape through the facade; database defaults to "default"
    assert schema_call == {
        "source": "bn_src",
        "database": "default",
        "collection": "hepar2",
        "protocol": "bn",
        "format": "dict",
    }


def test_top_level_graph_structure_builds_structured_section(
    op: NL2BNOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sequence_provider(monkeypatch, VALID_RESPONSE)
    op.apply(INPUT, dict(ATTRS), _props(seam))
    content = _prompt_of(0)
    assert "**Nodes and their states:**" in content
    assert "- cirrhosis: [present, absent]" in content
    assert "- alcoholism → cirrhosis" in content
    assert "Collection: Liver disease network" in content
    assert "- cirrhosis: Liver cirrhosis\n  - present: Cirrhosis observed" in content


def test_metadata_wrapped_graph_structure_also_structured(
    op: NL2BNOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    seam.schema_result = {"metadata": {"graph_structure": GRAPH}}
    _sequence_provider(monkeypatch, VALID_RESPONSE)
    op.apply(INPUT, dict(ATTRS), _props(seam))
    assert "**Nodes and their states:**" in _prompt_of(0)


def test_registry_schema_without_graph_structure_is_unstructured(
    op: NL2BNOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    seam.schema_result = {"entities": [], "relations": []}
    _sequence_provider(monkeypatch, VALID_RESPONSE)
    op.apply(INPUT, dict(ATTRS), _props(seam))
    content = _prompt_of(0)
    assert "**Bayesian Network Schema:**" in content
    assert json.dumps(seam.schema_result, indent=2) in content
    # unstructured => no graph validation: the bogus-free response executed directly
    assert len(seam.calls_to("execute_query")) == 1


def test_empty_registry_schema_yields_empty_section(
    op: NL2BNOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    seam.schema_result = {}
    _sequence_provider(monkeypatch, VALID_RESPONSE)
    op.apply(INPUT, dict(ATTRS), _props(seam))
    assert "**Bayesian Network Schema:**\n\n\n" in _prompt_of(0)


# --- provided schema variants -------------------------------------------------------
@pytest.mark.parametrize(
    "provided,expect_structured",
    [
        (json.dumps(GRAPH), True),
        (GRAPH, True),
    ],
    ids=["json-string", "dict"],
)
def test_provided_structured_schema_skips_registry_fetch(
    op: NL2BNOperator,
    seam: _RecordingSeam,
    monkeypatch: pytest.MonkeyPatch,
    provided: Any,
    expect_structured: bool,
) -> None:
    _sequence_provider(monkeypatch, VALID_RESPONSE)
    op.apply(INPUT, {**ATTRS, "schema": provided}, _props(seam))
    assert seam.calls_to("get_data_source_schema") == []
    assert ("**Nodes and their states:**" in _prompt_of(0)) is expect_structured


def test_provided_unstructured_dict_string_is_dumped(
    op: NL2BNOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sequence_provider(monkeypatch, VALID_RESPONSE)
    op.apply(INPUT, {**ATTRS, "schema": '{"tables": ["jobs"]}'}, _props(seam))
    content = _prompt_of(0)
    assert "**Bayesian Network Schema:**" in content
    assert json.dumps({"tables": ["jobs"]}, indent=2) in content


def test_provided_invalid_json_string_used_raw(
    op: NL2BNOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sequence_provider(monkeypatch, VALID_RESPONSE)
    op.apply(INPUT, {**ATTRS, "schema": "not json {"}, _props(seam))
    assert "**Bayesian Network Schema:**\n\nnot json {" in _prompt_of(0)


def test_provided_json_non_dict_string_uses_original_string(
    op: NL2BNOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Valid JSON that parses to a non-dict keeps the ORIGINAL string (upstream branch)
    _sequence_provider(monkeypatch, VALID_RESPONSE)
    op.apply(INPUT, {**ATTRS, "schema": "[1, 2]"}, _props(seam))
    assert "**Bayesian Network Schema:**\n\n[1, 2]" in _prompt_of(0)


def test_provided_unstructured_dict_is_dumped(
    op: NL2BNOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sequence_provider(monkeypatch, VALID_RESPONSE)
    op.apply(INPUT, {**ATTRS, "schema": {"x": 1}}, _props(seam))
    assert json.dumps({"x": 1}, indent=2) in _prompt_of(0)


# --- graph stored by the registry's sync ----------------------------------------------
WRONG_STATE = (
    '{"target_node": "cirrhosis", "target_state": "True", "context": {"alcoholism": "yes"}}'
)


class _NetworkSource:
    """Reports one network the way a Bayesian-network source does, without pgmpy."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.properties: dict[str, Any] = {"connection": {"protocol": "network/bn"}}
        self.queries: list[Any] = []

    def fetch_metadata(self) -> dict[str, Any]:
        return {}

    def fetch_databases(self) -> list[str]:
        return ["default"]

    def fetch_database_metadata(self, database: str) -> dict[str, Any]:
        return {}

    def fetch_database_collections(self, database: str) -> list[str]:
        return ["hepar2"]

    def fetch_database_collection_metadata(self, database: str, collection: str) -> dict[str, Any]:
        return {
            "collection": collection,
            "node_count": 2,
            "edge_count": 1,
            "graph_structure": GRAPH,
        }

    def fetch_database_collection_entities(self, database: str, collection: str) -> dict[str, Any]:
        return {}

    def fetch_database_collection_relations(self, database: str, collection: str) -> dict[str, Any]:
        return {}

    def _query_requires_commit(self, query: Any) -> bool:
        return False

    def execute_query(self, query: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        self.queries.append(query)
        return [{"probability": 0.42}]


class _SchemaOnlyRegistry:
    """A registry that is not a DataRegistry and stores no collection properties."""

    def __init__(self, schema: Any = None) -> None:
        self.schema: Any = {"entities": [], "relations": []} if schema is None else schema

    def get_data_source_schema(self, **_kwargs: Any) -> Any:
        return self.schema

    def execute_query(self, **_kwargs: Any) -> list[dict[str, Any]]:
        return [{"probability": 0.42}]


class _StoredPropertiesRegistry(_SchemaOnlyRegistry):
    def __init__(self, stored: Any, schema: Any = None) -> None:
        super().__init__(schema)
        self.stored = stored
        self.reads: list[tuple[str, ...]] = []

    def get_source_database_collection_properties(self, *args: str) -> Any:
        self.reads.append(args)
        return self.stored


def test_synced_network_graph_validates_generated_query(
    op: NL2BNOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    from blue_data.registry.data_registry import (  # pyright: ignore[reportMissingTypeStubs]
        DataRegistry,
    )

    registry: Any = DataRegistry(name="bn_stored_graph", rebuild=False)
    source = _NetworkSource("bn_src")
    registry.register_source(source)
    registry.sync_source("bn_src", recursive=True)
    seam = RegistrySeam(registry)

    _sequence_provider(monkeypatch, WRONG_STATE, VALID_RESPONSE)
    out = op.apply(INPUT, dict(ATTRS), _props(seam))

    assert "- cirrhosis: [present, absent]" in _prompt_of(0)
    assert "Target state 'True' not valid for node 'cirrhosis'." in _prompt_of(1)
    assert len(litellm.calls) == 2
    assert source.queries == [json.dumps(json.loads(VALID_RESPONSE))]
    assert out[0][0]["prob"] == 0.42


@pytest.mark.parametrize(
    "stored",
    [
        {"metadata": {"graph_structure": GRAPH}},
        {"graph_structure": GRAPH},
        {"metadata": {"graph_structure": {"nodes": {}, "edges": {}}}, "graph_structure": GRAPH},
    ],
    ids=["metadata", "top-level", "unusable-metadata"],
)
def test_stored_graph_locations(
    op: NL2BNOperator, monkeypatch: pytest.MonkeyPatch, stored: dict[str, Any]
) -> None:
    registry = _StoredPropertiesRegistry(stored)
    _sequence_provider(monkeypatch, VALID_RESPONSE)
    op.apply(INPUT, dict(ATTRS), _props(RegistrySeam(cast(Any, registry))))
    assert registry.reads == [("bn_src", "default", "hepar2")]
    assert "- cirrhosis: [present, absent]" in _prompt_of(0)


@pytest.mark.parametrize(
    "stored",
    [
        None,
        [],
        {"metadata": {}},
        {"metadata": {"graph_structure": {"nodes": {"a": {}}}}},
        {"metadata": {"graph_structure": {"nodes": ["a"], "edges": {}}}},
        {"metadata": {"graph_structure": {"nodes": {"a": "x"}, "edges": {}}}},
        {"metadata": {"graph_structure": {"nodes": {"a": {}}, "edges": []}}},
    ],
    ids=["none", "list", "no-graph", "no-edges", "node-list", "node-text", "edge-list"],
)
def test_unusable_stored_graph_keeps_unstructured_schema(
    op: NL2BNOperator, monkeypatch: pytest.MonkeyPatch, stored: Any
) -> None:
    registry = _StoredPropertiesRegistry(stored)
    _sequence_provider(monkeypatch, WRONG_STATE)
    out = op.apply(INPUT, dict(ATTRS), _props(RegistrySeam(cast(Any, registry))))
    assert "**Bayesian Network Schema:**" in _prompt_of(0)
    assert len(litellm.calls) == 1
    assert out[0][0]["query"] == json.loads(WRONG_STATE)


def test_registry_without_stored_properties_keeps_unstructured_schema(
    op: NL2BNOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sequence_provider(monkeypatch, WRONG_STATE)
    out = op.apply(INPUT, dict(ATTRS), _props(RegistrySeam(cast(Any, _SchemaOnlyRegistry()))))
    assert "**Bayesian Network Schema:**" in _prompt_of(0)
    assert out[0][0]["query"] == json.loads(WRONG_STATE)


@pytest.mark.parametrize(
    "schema",
    [{"graph_structure": GRAPH}, {"metadata": {"graph_structure": GRAPH}}],
    ids=["top-level", "metadata"],
)
def test_registry_graph_is_used_without_reading_stored_graph(
    op: NL2BNOperator, monkeypatch: pytest.MonkeyPatch, schema: dict[str, Any]
) -> None:
    other = {"nodes": {"rain": {"states": ["yes", "no"]}}, "edges": {}}
    registry = _StoredPropertiesRegistry({"metadata": {"graph_structure": other}}, schema)
    _sequence_provider(monkeypatch, VALID_RESPONSE)
    op.apply(INPUT, dict(ATTRS), _props(RegistrySeam(cast(Any, registry))))
    assert registry.reads == []
    assert "- cirrhosis: [present, absent]" in _prompt_of(0)


@pytest.mark.parametrize("provided", [json.dumps(GRAPH), "free-text schema"])
def test_caller_schema_is_used_without_reading_stored_graph(
    op: NL2BNOperator, monkeypatch: pytest.MonkeyPatch, provided: str
) -> None:
    other = {"nodes": {"rain": {"states": ["yes", "no"]}}, "edges": {}}
    registry = _StoredPropertiesRegistry({"metadata": {"graph_structure": other}})
    _sequence_provider(monkeypatch, VALID_RESPONSE)
    op.apply(INPUT, {**ATTRS, "schema": provided}, _props(RegistrySeam(cast(Any, registry))))
    assert registry.reads == []
    assert "rain" not in _prompt_of(0)


def test_registry_with_own_schema_method_keeps_its_schema(
    op: NL2BNOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _OwnSchemaSeam(RegistrySeam):
        def get_data_source_schema(self, *args: Any, **kwargs: Any) -> Any:
            return {"entities": [], "relations": []}

    registry = _StoredPropertiesRegistry({"metadata": {"graph_structure": GRAPH}})
    _sequence_provider(monkeypatch, WRONG_STATE)
    op.apply(INPUT, dict(ATTRS), _props(_OwnSchemaSeam(cast(Any, registry))))
    assert registry.reads == []
    assert "**Bayesian Network Schema:**" in _prompt_of(0)


def test_real_bayesian_network_without_schema_corrects_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("pgmpy", reason="Bayesian-network sources need the blue-data bn extra")
    from blue_data.registry.data_registry import (  # pyright: ignore[reportMissingTypeStubs]
        DataRegistry,
    )
    from blue_data.source.network.bn.bayesian_network_source import (  # pyright: ignore[reportMissingTypeStubs]
        BayesianNetworkSource,
    )

    from blue_data_ops.operators import versioned_registry

    model = tmp_path / "models" / "weather"
    model.mkdir(parents=True)
    (model / "model.bif").write_text(
        "network unknown {}\n"
        "variable Rain { type discrete [ 2 ] { yes, no }; }\n"
        "variable WetGrass { type discrete [ 2 ] { yes, no }; }\n"
        "probability ( Rain ) { table 0.2, 0.8; }\n"
        "probability ( WetGrass | Rain ) { (yes) 0.9, 0.1; (no) 0.1, 0.9; }\n"
    )
    (model / "node_mapping.json").write_text('{"Rain": "Rain", "WetGrass": "WetGrass"}')
    (model / "state_mapping.json").write_text('{"yes": "yes", "no": "no"}')
    registry: Any = DataRegistry(name="bn_real", rebuild=False)
    registry.register_source(
        BayesianNetworkSource("bn", properties={"connection": {"source_directory": str(tmp_path)}})
    )
    registry.sync_source("bn", recursive=True)

    wrong = '{"target_node": "Rain", "target_state": "True", "context": {"WetGrass": "True"}}'
    right = '{"target_node": "Rain", "target_state": "yes", "context": {"WetGrass": "yes"}}'
    _sequence_provider(monkeypatch, wrong, right)
    attrs = {
        "question": "chance of rain if the grass is wet?",
        "source": "bn",
        "database": "models",
        "collection": "weather",
        "protocol_variant": "pgmpy",
        "explanation": False,
    }
    out, _, meta = (
        versioned_registry()
        .resolve("nl2bn@3.0.0")
        .run(INPUT, attrs, {"data_registry": registry, "llm.model": "test-model"})
    )

    assert meta.errors == []
    assert "- Rain: [yes, no]" in _prompt_of(0)
    assert len(litellm.calls) == 2
    assert out[0][0]["prob"] == pytest.approx(0.18 / 0.26)


# --- successful execution -----------------------------------------------------------
def test_happy_path_output_and_execution_call(
    op: NL2BNOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sequence_provider(monkeypatch, VALID_RESPONSE)
    out = op.apply(INPUT, dict(ATTRS), _props(seam))

    query = json.loads(VALID_RESPONSE)
    assert out == [[{"prob": 0.42, "query": query, "explanation": "because reasons"}]]
    assert len(litellm.calls) == 1  # no correction round

    [execute_call] = seam.calls_to("execute_query")
    assert execute_call == {
        "query": json.dumps(query),
        "source": "bn_src",
        "database": "default",
        "collection": "hepar2",
        "optional_properties": {
            "explanation": True,
            "structured_explanation": False,
            "max_num_paths": 50,
        },
    }


def test_context_defaulted_when_missing(
    op: NL2BNOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sequence_provider(monkeypatch, '{"target_node": "cirrhosis", "target_state": "present"}')
    out = op.apply(INPUT, dict(ATTRS), _props(seam))
    assert out[0][0]["query"]["context"] == {}


def test_explanation_false_empty_optional_properties(
    op: NL2BNOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    seam.query_result = [{"prob": 0.7}]
    _sequence_provider(monkeypatch, VALID_RESPONSE)
    out = op.apply(INPUT, {**ATTRS, "explanation": False}, _props(seam))
    [execute_call] = seam.calls_to("execute_query")
    assert execute_call["optional_properties"] == {}
    assert out[0][0] == {"prob": 0.7, "query": json.loads(VALID_RESPONSE)}  # "prob" fallback key


def test_explanation_requested_but_absent_result_key(
    op: NL2BNOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    seam.query_result = [{"probability": 0.9}]
    _sequence_provider(monkeypatch, VALID_RESPONSE)
    out = op.apply(INPUT, dict(ATTRS), _props(seam))
    assert out == [[{"prob": 0.9, "query": json.loads(VALID_RESPONSE)}]]


def test_empty_execution_result_yields_none_prob(
    op: NL2BNOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    seam.query_result = []
    _sequence_provider(monkeypatch, VALID_RESPONSE)
    out = op.apply(INPUT, dict(ATTRS), _props(seam))
    assert out == [[{"prob": None, "query": json.loads(VALID_RESPONSE)}]]


def test_dict_execution_result(
    op: NL2BNOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    seam.query_result = {"probability": 0.5, "explanation": "direct"}
    _sequence_provider(monkeypatch, VALID_RESPONSE)
    out = op.apply(INPUT, dict(ATTRS), _props(seam))
    assert out[0][0]["prob"] == 0.5
    assert out[0][0]["explanation"] == "direct"


# --- correction loop ----------------------------------------------------------------
def test_missing_target_node_triggers_correction(
    op: NL2BNOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sequence_provider(monkeypatch, '{"target_state": "present"}', VALID_RESPONSE)
    out = op.apply(INPUT, dict(ATTRS), _props(seam))
    assert len(litellm.calls) == 2
    correction = _prompt_of(1)
    assert "You previously generated a Bayesian Network query" in correction
    assert "No target_node found in LLM response" in correction
    assert '\\"target_state\\": \\"present\\"' in json.dumps(correction)  # original query shown
    assert out[0][0]["prob"] == 0.42


def test_graph_validation_failure_triggers_correction(
    op: NL2BNOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    bogus = '{"target_node": "bogus", "target_state": "present", "context": {}}'
    _sequence_provider(monkeypatch, bogus, VALID_RESPONSE)
    op.apply(INPUT, dict(ATTRS), _props(seam))
    assert "Target node 'bogus' not found in BN." in _prompt_of(1)


def test_corrections_exhausted_raises(
    op: NL2BNOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sequence_provider(monkeypatch, '{"target_state": "present"}')  # invalid forever
    with pytest.raises(
        ValueError, match="model reply did not match the operator's output format"
    ) as failure:
        op.apply(INPUT, dict(ATTRS), _props(seam))
    assert is_reply_failure(failure.value)
    assert len(litellm.calls) == 3  # initial + max_corrections
    assert seam.calls_to("execute_query") == []


def test_max_corrections_zero_raises_immediately(
    op: NL2BNOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sequence_provider(monkeypatch, '{"target_state": "present"}')
    with pytest.raises(
        ValueError, match="model reply did not match the operator's output format"
    ) as failure:
        op.apply(INPUT, {**ATTRS, "max_corrections": 0}, _props(seam))
    assert is_reply_failure(failure.value)
    assert len(litellm.calls) == 1


def test_unstructured_schema_accepts_any_node_names(
    op: NL2BNOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    seam.schema_result = {"entities": [], "relations": []}
    _sequence_provider(
        monkeypatch, '{"target_node": "anything", "target_state": "whatever", "context": {}}'
    )
    out = op.apply(INPUT, dict(ATTRS), _props(seam))
    assert len(litellm.calls) == 1
    assert out[0][0]["query"]["target_node"] == "anything"


def test_caller_properties_not_mutated_by_correction_flow(
    op: NL2BNOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sequence_provider(monkeypatch, '{"target_state": "present"}', VALID_RESPONSE)
    properties = _props(seam, marker=1)
    op.apply(INPUT, dict(ATTRS), properties)
    assert properties == {"data_registry": seam, "marker": 1}  # no template key leaked


# --- initial-call and correction-call exception boundaries --------------------------
def test_initial_call_failure_recovers_via_correction(
    op: NL2BNOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Three consecutive provider failures exhaust the adapter's retries on the
    # INITIAL call; the failure becomes a validation error and the correction call
    # (which succeeds) recovers the flow.
    _sequence_provider(monkeypatch, VALID_RESPONSE)
    litellm.fail_next.extend([RuntimeError("down")] * 3)
    out = op.apply(INPUT, dict(ATTRS), _props(seam))
    assert out[0][0]["prob"] == 0.42
    correction = _prompt_of(3)  # calls 0-2 were the failed retries
    assert "Service error:" in correction


def test_initial_invalid_json_cast_failure_enters_correction(
    op: NL2BNOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The default output_cast is json: a non-JSON completion fails INSIDE the client
    # call. Upstream's error-wrapping layer converts that to its platform error type,
    # which its catch turns into the correction flow — the port's Exception-wide
    # catch must reproduce that recovery.
    _sequence_provider(monkeypatch, "not a json payload", VALID_RESPONSE)
    out = op.apply(INPUT, dict(ATTRS), _props(seam))
    assert out[0][0]["prob"] == 0.42
    assert "Service error:" in _prompt_of(1)


def test_local_parse_non_decode_error_propagates(
    op: NL2BNOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    class TextBN(NL2BNOperator):
        DEFAULT_PROPERTIES = {**NL2BNOperator.DEFAULT_PROPERTIES, "output_cast": "str"}

    op = TextBN()
    # With output_cast overridden to str, the OPERATOR's own json.loads runs
    # on the raw response; a failure there that is NOT JSONDecodeError (deep nesting
    # => RecursionError) must PROPAGATE — upstream's outer catch sees only its
    # platform error type from the client call, and its inner catch only
    # JSONDecodeError, so a local RecursionError escapes both. Pins the narrow scope.
    deep = "[" * 10_000 + "]" * 10_000
    _sequence_provider(monkeypatch, deep)
    original_loads = json.loads
    parse_attempts: list[str] = []

    def fail_local_parse(value: Any, *args: Any, **kwargs: Any) -> Any:
        if value == deep:
            parse_attempts.append(value)
            raise RecursionError("simulated local JSON parser failure")
        return original_loads(value, *args, **kwargs)

    # Python's JSON nesting limit changes; inject the exact non-decode failure.
    monkeypatch.setattr(json, "loads", fail_local_parse)
    with pytest.raises(RecursionError):
        op.apply(INPUT, dict(ATTRS), _props(seam))
    assert len(parse_attempts) == 1
    assert seam.calls_to("execute_query") == []


def test_correction_call_failure_propagates(
    op: NL2BNOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The initial response is structurally invalid, entering the correction loop;
    # the CORRECTION call's provider failure is NOT caught (upstream leaves it so).
    def fail_from_second(**kwargs: Any) -> Any:
        litellm.calls.append(kwargs)
        if len(litellm.calls) > 1:
            raise RuntimeError("down")

        class _R:
            def model_dump(self) -> dict[str, Any]:
                return {
                    "choices": [
                        {"message": {"role": "assistant", "content": '{"target_state": "x"}'}}
                    ],
                    "usage": {},
                }

        return _R()

    monkeypatch.setattr(litellm, "completion", fail_from_second)
    with pytest.raises(LLMError):
        op.apply(INPUT, dict(ATTRS), _props(seam))
    assert seam.calls_to("execute_query") == []


# --- schema-section helpers ---------------------------------------------------------
def test_extract_nodes_info_variants() -> None:
    assert _extract_nodes_info({"nodes": {}}) == "No nodes found"
    assert _extract_nodes_info({}) == "No nodes found"
    info = _extract_nodes_info({"nodes": {"a": {"states": ["x", "y"]}, "b": {}, "c": "not-a-dict"}})
    assert info == "- a: [x, y]\n- b: [N/A]"  # non-dict node skipped, empty states => N/A


def test_extract_edges_info_variants() -> None:
    assert _extract_edges_info({}) == "No edges found"
    assert _extract_edges_info({"edges": {"a": ["b", "c"]}}) == "- a → b\n- a → c"
    assert _extract_edges_info({"edges": {"a": {"b": 0.5}}}) == "- a → b"  # dict-shaped children


def test_extract_node_descriptions_variants() -> None:
    assert _extract_node_descriptions({}) == "No descriptions available"
    full = _extract_node_descriptions(GRAPH)
    assert full.startswith("Collection: Liver disease network")
    assert "Node descriptions:" in full
    assert "- cirrhosis: Liver cirrhosis\n  - present: Cirrhosis observed" in full
    assert "- absent:" not in full  # empty state descriptions are skipped
    # nodes without a description are skipped entirely
    assert _extract_node_descriptions({"nodes": {"a": {"states": ["x"]}}}) == (
        "No descriptions available"
    )


@pytest.mark.parametrize(
    "query,expected_errors",
    [
        ({"target_node": "cirrhosis", "target_state": "present", "context": {}}, []),
        ({"target_state": "present"}, ["Missing target_node"]),
        ({"target_node": "bogus", "target_state": "x"}, ["Target node 'bogus' not found in BN."]),
        ({"target_node": "cirrhosis"}, ["Missing target_state"]),
        (
            {"target_node": "cirrhosis", "target_state": "maybe"},
            [
                "Target state 'maybe' not valid for node 'cirrhosis'. "
                "Valid states: ['present', 'absent']"
            ],
        ),
        (
            {"target_node": "cirrhosis", "target_state": "present", "context": {"ghost": "yes"}},
            ["Context node 'ghost' not found in BN."],
        ),
        (
            {
                "target_node": "cirrhosis",
                "target_state": "present",
                "context": {"alcoholism": "sometimes"},
            },
            [
                "Context state 'sometimes' not valid for node 'alcoholism'. "
                "Valid states: ['yes', 'no']"
            ],
        ),
    ],
    ids=[
        "valid",
        "no-target-node",
        "bogus-node",
        "no-target-state",
        "bad-state",
        "ghost-context-node",
        "bad-context-state",
    ],
)
def test_validate_bn_query_matrix(query: dict[str, Any], expected_errors: list[str]) -> None:
    assert _validate_bn_query(query, GRAPH) == expected_errors


# --- byte-level prompt pins (the parity surfaces) ---
def test_prompt_template_bytes_pinned() -> None:
    import hashlib

    from blue_data_ops.operators.nl2bn_operator import (
        _CORRECTION_PROMPT,  # pyright: ignore[reportPrivateUsage]
        _PROMPT,  # pyright: ignore[reportPrivateUsage]
    )

    assert (
        hashlib.sha256(_PROMPT.encode()).hexdigest()
        == "ce4c3a5ad22e93d229f30de4ca22977ace65a4881ee2b59aaca565ee904ca21a"
    )
    assert (
        hashlib.sha256(_CORRECTION_PROMPT.encode()).hexdigest()
        == "bb29486ebb3515b91addb7241152249bef8d4eb31ff7e9a3ecf6ce80034c3857"
    )


def test_rendered_prompt_full_equality(
    op: NL2BNOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Full-content equality: the rendered prompt equals the template with exactly
    # these three substitutions, then the adapter's trailing-newline trim.
    import json
    from pathlib import Path

    _sequence_provider(monkeypatch, VALID_RESPONSE)
    op.apply(INPUT, {**ATTRS, "context": "clinical"}, _props(seam))
    content = _prompt_of(0)

    frozen = json.loads(
        (Path(__file__).parents[2] / "fixtures/llm_benign_prompts.json").read_text()
    )
    expected = frozen["nl2bn"]["prompt"]
    assert content == expected
    assert not expected.endswith("\n")


# --- the 16-field defaults block pinned field-by-field ---
def test_default_properties_pinned_field_by_field() -> None:
    from blue_data_ops.operators.nl2bn_operator import (
        _PROMPT,  # pyright: ignore[reportPrivateUsage]
    )

    assert NL2BNOperator.DEFAULT_PROPERTIES == {
        "execute_query": True,
        "openai.api": "ChatCompletion",
        "openai.model": "gpt-6-luna",
        "openai.stream": False,
        "openai.max_tokens": 4096,
        "openai.temperature": 0,
        "input_json": '[{"role": "user"}]',
        "input_context": "$[0]",
        "input_context_field": "content",
        "input_field": "messages",
        "input_template": _PROMPT,
        "output_path": "$.choices[0].message.content",
        "service_prefix": "openai",
        "output_transformations": [
            {
                "transformation": "sub",
                "from": r"(?is)\A```(?:json)?[ \t]*\r?\n(.*)\r?\n```\Z",
                "to": r"\1",
            },
        ],
        "output_strip": True,
        "output_cast": "json",
    }
    assert len(NL2BNOperator.DEFAULT_PROPERTIES) == 16


# --- Validator (upstream: the pure default type gate) ---
VALID_FOR_GATE: dict[str, Any] = {
    "question": "q",
    "source": "s",
    "database": "d",
    "collection": "c",
    "protocol_variant": "pgmpy",
}


@pytest.mark.parametrize(
    "attrs,expected",
    [
        (VALID_FOR_GATE, True),
        ({k: v for k, v in VALID_FOR_GATE.items() if k != "question"}, False),
        ({**VALID_FOR_GATE, "max_corrections": "not-an-int"}, False),
        ({**VALID_FOR_GATE, "question": [1]}, False),
        ({**VALID_FOR_GATE, "explanation": True, "max_num_paths": 10}, True),
    ],
    ids=["valid", "no-question", "junk-max-corrections", "non-str-question", "typed-extras"],
)
def test_validator(op: NL2BNOperator, attrs: dict[str, Any], expected: bool) -> None:
    assert op.validate(INPUT, attrs) is expected


# --- Explainer (custom minimal) ---
def test_explainer(op: NL2BNOperator) -> None:
    exp = op.explain([[{"prob": 0.1}]], INPUT, {"question": "q"})
    assert exp == {"output": [[{"prob": 0.1}]], "attributes": {"question": "q"}}


# --- Interface parity ---
def test_interface(op: NL2BNOperator) -> None:
    assert op.name == "nl2bn"
    assert op.description == (
        "Translates natural language questions into Bayesian Network queries using LLM models"
    )
    expected: dict[str, tuple[str, bool, Any]] = {
        "question": ("str", True, None),
        "source": ("str", True, ""),
        "database": ("str", True, ""),
        "collection": ("str", True, ""),
        "protocol_variant": ("str", True, "pgmpy"),
        "context": ("str", False, ""),
        "schema": ("str", False, ""),
        "explanation": ("bool", False, True),
        "structured_explanation": ("bool", False, False),
        "max_corrections": ("int", False, 2),
        "max_num_paths": ("int", False, 50),
    }
    assert set(op.attributes) == set(expected)
    for attr_name, (attr_type, required, default) in expected.items():
        spec = op.attributes[attr_name]
        assert spec.type == attr_type
        assert spec.required is required
        assert spec.default == default
    assert op.attributes["schema"].description == (
        "JSON string of BN schema (optional - will be fetched automatically if not provided)"
    )
