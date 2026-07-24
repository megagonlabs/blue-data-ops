"""Compatibility tests for NL-to-SQL execution.

The suite uses deterministic LLM and registry doubles to cover prompt bytes,
required attributes, schema lookup, query validation, and registry execution.
"""

from __future__ import annotations

import json
from typing import Any

import litellm  # the deterministic stub
import pytest

blue_data = pytest.importorskip("blue_data")

from blue_data_ops.data import RegistrySeam  # noqa: E402
from blue_data_ops.llm import LLMError  # noqa: E402
from blue_data_ops.operators.nl2sql_operator import NL2SQLOperator  # noqa: E402
from tests.doubles.data import RegistrySeamDouble  # noqa: E402

INPUT: list[list[dict[str, Any]]] = [[]]

ATTRS: dict[str, Any] = {
    "question": "what is the most frequently advertised manager role?",
    "source": "pg",
    "protocol": "postgres",
    "database": "postgres",
    "collection": "public",
}

SQL_RESPONSE = json.dumps(
    {
        "question": "what is the most frequently advertised manager role?",
        "query": "SELECT role FROM jobs GROUP BY role ORDER BY COUNT(*) DESC LIMIT 1",
    }
)


class _RecordingSeam(RegistrySeamDouble, RegistrySeam):
    """The recording double, typed as a RegistrySeam so injection resolves it."""


@pytest.fixture(autouse=True)
def _reset_fake() -> None:  # pyright: ignore[reportUnusedFunction] — autouse
    litellm.calls.clear()
    litellm.fail_next.clear()


@pytest.fixture
def op() -> NL2SQLOperator:
    return NL2SQLOperator()


@pytest.fixture
def seam() -> _RecordingSeam:
    recording = _RecordingSeam()
    recording.schema_result = {"entities": [{"name": "jobs"}], "relations": []}
    recording.query_result = [{"role": "manager"}]
    return recording


def _props(seam: RegistrySeam, **extra: Any) -> dict[str, Any]:
    return {"data_registry": seam, **extra}


def _content_provider(monkeypatch: pytest.MonkeyPatch, content: str) -> None:
    def fake(**kwargs: Any) -> Any:
        litellm.calls.append(kwargs)
        if litellm.fail_next:
            raise litellm.fail_next.pop(0)

        class _R:
            def model_dump(self) -> dict[str, Any]:
                return {
                    "choices": [{"message": {"role": "assistant", "content": content}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                }

        return _R()

    monkeypatch.setattr(litellm, "completion", fake)


def _prompt() -> str:
    return str(litellm.calls[-1]["messages"][0]["content"])


# --- blank question returns [[]] without external calls ------------------------------
@pytest.mark.parametrize("question", ["", "   "])
def test_blank_question_returns_empty(
    op: NL2SQLOperator, seam: _RecordingSeam, question: str
) -> None:
    assert op.apply(INPUT, {**ATTRS, "question": question}, _props(seam)) == [[]]
    assert litellm.calls == []
    assert seam.calls == []


# --- required protocol, database, and collection attributes -------------------------
@pytest.mark.parametrize(
    "overrides",
    [{"protocol": ""}, {"database": ""}, {"collection": ""}],
    ids=["protocol", "database", "collection"],
)
def test_missing_required_raises(
    op: NL2SQLOperator, seam: _RecordingSeam, overrides: dict[str, Any]
) -> None:
    with pytest.raises(ValueError, match="Protocol, database, and collection are required"):
        op.apply(INPUT, {**ATTRS, **overrides}, _props(seam))


def test_empty_source_is_not_required(
    op: NL2SQLOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Upstream's requirements check omits `source` despite the declared schema;
    # the flow proceeds and the registry is asked about the empty source name.
    _content_provider(monkeypatch, SQL_RESPONSE)
    out = op.apply(INPUT, {**ATTRS, "source": ""}, _props(seam))
    [schema_call] = seam.calls_to("get_data_source_schema")
    assert schema_call["source"] == ""
    assert out == [[{"role": "manager"}]]


def test_unsupported_protocol(op: NL2SQLOperator, seam: _RecordingSeam) -> None:
    with pytest.raises(
        ValueError,
        match="Unsupported protocol: oracle. Supported protocols are: postgres, mysql, sqlite",
    ):
        op.apply(INPUT, {**ATTRS, "protocol": "oracle"}, _props(seam))


# --- no registry returns [[]] --------------------------------------------------------
@pytest.mark.parametrize("properties", [None, {}, {"unrelated": 1}])
def test_no_registry_returns_empty(op: NL2SQLOperator, properties: dict[str, Any] | None) -> None:
    assert op.apply(INPUT, dict(ATTRS), properties) == [[]]
    assert litellm.calls == []


# --- registry schema lookup ignores the schema attribute ----------------------------
def test_schema_fetched_and_provided_schema_ignored(
    op: NL2SQLOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    _content_provider(monkeypatch, SQL_RESPONSE)
    op.apply(INPUT, {**ATTRS, "schema": '{"custom": true}'}, _props(seam))
    [schema_call] = seam.calls_to("get_data_source_schema")
    assert schema_call == {
        "source": "pg",
        "database": "postgres",
        "collection": "public",
        "protocol": None,
        "format": "dict",
    }
    content = _prompt()
    assert "custom" not in content  # the attribute never reaches the prompt
    assert json.dumps(seam.schema_result, indent=2) in content


def test_non_dict_schema_stringified(
    op: NL2SQLOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    seam.schema_result = "entity jobs(role text)"
    _content_provider(monkeypatch, SQL_RESPONSE)
    op.apply(INPUT, dict(ATTRS), _props(seam))
    assert "entity jobs(role text)" in _prompt()


# --- prompt construction ------------------------------------------------------------
def test_attr_names_section_exact(
    op: NL2SQLOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    _content_provider(monkeypatch, SQL_RESPONSE)
    op.apply(INPUT, {**ATTRS, "attr_names": ["name", "salary"]}, _props(seam))
    assert (
        "## Target Field Names (SELECT AS):\n"
        "Please use the following field names as column aliases if it's not same with "
        "the column names. Use 'AS' keyword if needed to alias columns:\nname, salary\n"
    ) in _prompt()


def test_empty_attr_names_no_section(
    op: NL2SQLOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    _content_provider(monkeypatch, SQL_RESPONSE)
    op.apply(INPUT, dict(ATTRS), _props(seam))
    assert "## Target Field Names" not in _prompt()


@pytest.mark.parametrize(
    "case_insensitive,expected",
    [(True, "case-insensitive matching"), (False, "case-sensitive matching")],
    ids=["insensitive", "sensitive"],
)
def test_sensitivity_substitution(
    op: NL2SQLOperator,
    seam: _RecordingSeam,
    monkeypatch: pytest.MonkeyPatch,
    case_insensitive: bool,
    expected: str,
) -> None:
    _content_provider(monkeypatch, SQL_RESPONSE)
    op.apply(INPUT, {**ATTRS, "case_insensitive": case_insensitive}, _props(seam))
    assert expected in _prompt()


def test_undeclared_force_query_prefixes_reaches_prompt(
    op: NL2SQLOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Upstream reads this attribute without declaring it in the schema; it flows to
    # the template as-is.
    _content_provider(monkeypatch, SQL_RESPONSE)
    op.apply(INPUT, {**ATTRS, "force_query_prefixes": "SELECT, WITH"}, _props(seam))
    assert "start with any of the following prefixes: SELECT, WITH" in _prompt()


def test_rendered_prompt_full_equality(
    op: NL2SQLOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    from string import Template

    from jinja2 import BaseLoader, Environment

    from blue_data_ops.operators.nl2sql_operator import (
        _PROMPT,  # pyright: ignore[reportPrivateUsage]
    )

    _content_provider(monkeypatch, SQL_RESPONSE)
    op.apply(
        INPUT,
        {**ATTRS, "context": "job postings", "additional_requirements": "- Limit to 10 rows."},
        _props(seam),
    )
    templated = Template(_PROMPT).safe_substitute(
        question=ATTRS["question"],
        schema=json.dumps(seam.schema_result, indent=2),
        protocol="postgres",
        sensitivity="insensitive",
        force_query_prefixes="SELECT",
        additional_requirements="- Limit to 10 rows.",
        context="job postings",
        attr_names_section="",
    )
    expected = Environment(loader=BaseLoader()).from_string(templated).render()
    assert _prompt() == expected
    assert not _prompt().endswith("\n")


# --- response parsing ---------------------------------------------------------------
def test_execute_path_call_shape_and_output(
    op: NL2SQLOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    _content_provider(monkeypatch, SQL_RESPONSE)
    out = op.apply(INPUT, dict(ATTRS), _props(seam))
    assert out == [[{"role": "manager"}]]
    [execute_call] = seam.calls_to("execute_query")
    assert execute_call == {
        "query": "SELECT role FROM jobs GROUP BY role ORDER BY COUNT(*) DESC LIMIT 1",
        "source": "pg",
        "database": "postgres",
        "collection": "public",
        "optional_properties": {},  # the facade's default; upstream passes nothing here
    }


def test_execute_disabled_returns_sql_only(
    op: NL2SQLOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    _content_provider(monkeypatch, SQL_RESPONSE)
    out = op.apply(INPUT, dict(ATTRS), _props(seam, execute_query=False))
    assert out == [[{"sql": "SELECT role FROM jobs GROUP BY role ORDER BY COUNT(*) DESC LIMIT 1"}]]
    assert seam.calls_to("execute_query") == []


@pytest.mark.parametrize(
    "content",
    [json.dumps({"question": "q"}), json.dumps({"question": "q", "query": ""})],
    ids=["no-query-key", "empty-query"],
)
def test_missing_query_raises(
    op: NL2SQLOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    _content_provider(monkeypatch, content)
    with pytest.raises(ValueError, match="No query found in LLM response"):
        op.apply(INPUT, dict(ATTRS), _props(seam))


def test_invalid_json_str_response_raises(
    op: NL2SQLOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    # With output_cast overridden to str the operator's own json.loads runs and
    # converts the decode failure to upstream's ValueError message.
    _content_provider(monkeypatch, "not json")
    with pytest.raises(ValueError, match="Invalid JSON response from LLM"):
        op.apply(INPUT, dict(ATTRS), _props(seam, **{"output_cast": "str"}))


def test_non_dict_response_raises(
    op: NL2SQLOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    _content_provider(monkeypatch, "[1, 2]")  # json-cast yields a list
    with pytest.raises(ValueError, match=r"Invalid response from LLM: \[1, 2\]"):
        op.apply(INPUT, dict(ATTRS), _props(seam))


# --- query-prefix validation --------------------------------------------------------
def test_non_select_query_rejected(
    op: NL2SQLOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    _content_provider(monkeypatch, json.dumps({"query": "DROP TABLE jobs"}))
    with pytest.raises(ValueError, match="Invalid query prefix: DROP TABLE jobs"):
        op.apply(INPUT, dict(ATTRS), _props(seam))
    assert seam.calls_to("execute_query") == []


def test_prefix_check_is_case_insensitive(
    op: NL2SQLOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    _content_provider(monkeypatch, json.dumps({"query": "select role from jobs"}))
    out = op.apply(INPUT, dict(ATTRS), _props(seam))
    assert out == [[{"role": "manager"}]]


def test_custom_validate_query_prefixes(
    op: NL2SQLOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    _content_provider(monkeypatch, json.dumps({"query": "WITH c AS (SELECT 1) SELECT * FROM c"}))
    out = op.apply(INPUT, dict(ATTRS), _props(seam, **{"validate_query_prefixes": ["WITH"]}))
    assert out == [[{"role": "manager"}]]


# --- provider errors propagate ------------------------------------------------------
def test_provider_error_propagates(op: NL2SQLOperator, seam: _RecordingSeam) -> None:
    litellm.fail_next.extend([RuntimeError("down")] * 3)
    with pytest.raises(LLMError):
        op.apply(INPUT, dict(ATTRS), _props(seam))
    assert seam.calls_to("execute_query") == []


# --- execution-result formatting ----------------------------------------------------
_RESULT_SHAPES: list[tuple[Any, Any]] = [
    ({"n": 1}, [[{"n": 1}]]),
    ([], [[]]),
    (None, [[]]),
    ([[{"n": 1}]], [[{"n": 1}]]),
]


@pytest.mark.parametrize(
    "query_result,expected", _RESULT_SHAPES, ids=["dict", "empty", "none", "nested"]
)
def test_execution_result_shapes(
    op: NL2SQLOperator,
    seam: _RecordingSeam,
    monkeypatch: pytest.MonkeyPatch,
    query_result: Any,
    expected: Any,
) -> None:
    seam.query_result = query_result
    _content_provider(monkeypatch, SQL_RESPONSE)
    assert op.apply(INPUT, dict(ATTRS), _props(seam)) == expected


def test_inner_non_dict_result_returns_none_quirk(
    op: NL2SQLOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The formatter's case-4 fallthrough (pinned upstream quirk) surfaces here as a
    # None operator return.
    seam.query_result = [["not-a-dict"]]
    _content_provider(monkeypatch, SQL_RESPONSE)
    assert op.apply(INPUT, dict(ATTRS), _props(seam)) is None


# --- provider defaults and caller overrides -----------------------------------------
def test_defaults_reach_provider(
    op: NL2SQLOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    _content_provider(monkeypatch, SQL_RESPONSE)
    op.apply(INPUT, dict(ATTRS), _props(seam))
    call = litellm.calls[-1]
    assert call["model"] == "gpt-4o"
    assert call["max_tokens"] == 512  # nl2sql's own budget, distinct from the 4096 ops
    assert call["temperature"] == 0
    assert "api" not in call and "service_url" not in call


def test_caller_properties_override_defaults(
    op: NL2SQLOperator, seam: _RecordingSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    _content_provider(monkeypatch, SQL_RESPONSE)
    op.apply(INPUT, dict(ATTRS), _props(seam, **{"openai.model": "gpt-4o-mini"}))
    assert litellm.calls[-1]["model"] == "gpt-4o-mini"


# --- byte-level prompt pin (the parity surface) ---
def test_prompt_template_bytes_pinned() -> None:
    import hashlib

    from blue_data_ops.operators.nl2sql_operator import (
        _PROMPT,  # pyright: ignore[reportPrivateUsage]
    )

    assert (
        hashlib.sha256(_PROMPT.encode()).hexdigest()
        == "81381b8d834209ef293e9610a1024863c8abc0973298fb435b1702ef8ef39612"
    )


# --- the 17-field defaults block pinned field-by-field ---
def test_default_properties_pinned_field_by_field() -> None:
    from blue_data_ops.operators.nl2sql_operator import (
        _PROMPT,  # pyright: ignore[reportPrivateUsage]
    )

    assert NL2SQLOperator.DEFAULT_PROPERTIES == {
        "execute_query": True,
        "validate_query_prefixes": ["SELECT"],
        "openai.api": "ChatCompletion",
        "openai.model": "gpt-4o",
        "openai.stream": False,
        "openai.max_tokens": 512,
        "openai.temperature": 0,
        "input_json": '[{"role": "user"}]',
        "input_context": "$[0]",
        "input_context_field": "content",
        "input_field": "messages",
        "input_template": _PROMPT,
        "output_path": "$.choices[0].message.content",
        "service_prefix": "openai",
        "output_transformations": [
            {"transformation": "replace", "from": "```", "to": ""},
            {"transformation": "replace", "from": "json", "to": ""},
        ],
        "output_strip": True,
        "output_cast": "json",
    }
    assert len(NL2SQLOperator.DEFAULT_PROPERTIES) == 17


# --- Validator (upstream: the pure default type gate) ---
@pytest.mark.parametrize(
    "attrs,expected",
    [
        (ATTRS, True),
        ({k: v for k, v in ATTRS.items() if k != "question"}, False),
        ({**ATTRS, "attr_names": "not-a-list"}, False),
        ({**ATTRS, "attr_names": ["a", "b"]}, True),
        ({**ATTRS, "question": 123}, False),
    ],
    ids=["valid", "no-question", "attr-names-not-list", "attr-names-ok", "non-str-question"],
)
def test_validator(op: NL2SQLOperator, attrs: dict[str, Any], expected: bool) -> None:
    assert op.validate(INPUT, attrs) is expected


# --- Explainer (custom minimal) ---
def test_explainer(op: NL2SQLOperator) -> None:
    exp = op.explain([[{"a": 1}]], INPUT, {"question": "q"})
    assert exp == {"output": [[{"a": 1}]], "attributes": {"question": "q"}}


# --- Interface parity ---
def test_interface(op: NL2SQLOperator) -> None:
    assert op.name == "nl2sql"
    assert op.description == (
        "Translates natural language questions into SQL queries using LLM models"
    )
    expected: dict[str, tuple[str, bool, Any]] = {
        "source": ("str", True, ""),
        "question": ("str", True, None),
        "protocol": ("str", True, "postgres"),
        "database": ("str", True, ""),
        "collection": ("str", True, ""),
        "case_insensitive": ("bool", False, True),
        "additional_requirements": ("str", False, ""),
        "context": ("str", False, ""),
        "schema": ("str", False, ""),
        "attr_names": ("list[str]", False, []),
    }
    assert set(op.attributes) == set(expected)
    for attr_name, (attr_type, required, default) in expected.items():
        spec = op.attributes[attr_name]
        assert spec.type == attr_type
        assert spec.required is required
        assert spec.default == default
    assert op.attributes["schema"].description == (
        "JSON string of database schema (optional - will be fetched automatically if not provided)"
    )
