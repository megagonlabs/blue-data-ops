"""Representative outcomes for the 32 retained v2 operators.

Expectations come from ``tests/fixtures/v2_operator_outcomes.json``. Deterministic
doubles replace external services, not operator bodies.
"""

from __future__ import annotations

import copy
import json
import threading
import time
from pathlib import Path
from typing import Any, cast

import pytest

from blue_data_ops import ErrorCode, ErrorStage, ExecMeta
from blue_data_ops.llm import LLMClient
from blue_data_ops.operators import Operator, versioned_registry
from blue_data_ops.operators.types import Attributes, DataBundle
from blue_data_ops.plan import pipeline as pipeline_module
from tests.unit.operators._outcome_test_helpers import (
    RecordingSeam,
    ScriptedClient,
    SQLSourceDouble,
    assert_contained_failure,
    assert_recoverable_invalid,
    assert_successful_empty,
    assert_timeout,
    first_error,
    id_sequence,
)

_LIB = Path(__file__).resolve().parents[3]
_FIXTURE_PATH = _LIB / "tests/fixtures/v2_operator_outcomes.json"

_CODE = {code.name: code for code in ErrorCode}
_STAGE = {stage.name: stage for stage in ErrorStage}


def _reconstruct(obj: Any) -> Any:
    """Rebuild tuples marked as ``{"__tuple__": [...]}`` (json erases tuple type)."""
    if isinstance(obj, dict):
        mapping = cast("dict[str, Any]", obj)
        if "__tuple__" in mapping and len(mapping) == 1:
            return tuple(_reconstruct(item) for item in cast("list[Any]", mapping["__tuple__"]))
        return {key: _reconstruct(value) for key, value in mapping.items()}
    if isinstance(obj, list):
        return [_reconstruct(item) for item in cast("list[Any]", obj)]
    return obj


# Expectations load from the checked-in fixture so mutation controls exercise the assertions.
_FIXTURE: dict[str, Any] = _reconstruct(json.loads(_FIXTURE_PATH.read_text()))
_ROWS: dict[str, dict[str, Any]] = {row["name"]: row for row in _FIXTURE["rows"]}
_NAMES: list[str] = sorted(name for name, row in _ROWS.items() if not row["is_refinable"])


# --------------------------------------------------------------------------------------------------
# Boundary doubles keyed by profile. Nothing here replaces an operator body.
# --------------------------------------------------------------------------------------------------
class _Boundary:
    def __init__(
        self,
        properties: dict[str, Any] | None,
        client: ScriptedClient | None = None,
        seam: RecordingSeam | None = None,
    ) -> None:
        self.properties = properties
        self.client = client
        self.seam = seam

    def no_boundary_calls(self) -> bool:
        if self.client is not None and self.client.calls:
            return False
        if self.seam is not None and self.seam.calls:
            return False
        return True


class _RaisingSeam(RecordingSeam):
    """A data-registry seam whose search surface raises, to force a contained failure."""

    def search_records(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        raise RuntimeError("private registry payload")

    def search_records_hierarchical(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        raise RuntimeError("private registry payload")


def _responses(config: dict[str, Any]) -> list[Any]:
    out: list[Any] = []
    for item in config.get("responses", []):
        if item == "__RAISE__:provider":
            out.append(RuntimeError("private provider payload"))
        else:
            out.append(item)
    return out


def _make_seam(config: dict[str, Any]) -> RecordingSeam:
    seam = RecordingSeam()
    seam_config = config.get("seam", config)
    if "schema_result" in seam_config:
        seam.schema_result = seam_config["schema_result"]
    if "query_result" in seam_config:
        seam.query_result = seam_config["query_result"]
    pages = seam_config.get("search_pages")
    if pages:
        seam.search_pages = {int(page): rows for page, rows in pages.items()}
    return seam


def _build_boundary(
    profile: str, config: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> _Boundary:
    if profile in ("none", "seam_missing"):
        return _Boundary({})
    if profile == "llm":
        client = ScriptedClient(_responses(config))
        return _Boundary({"llm_client": client}, client=client)
    if profile == "llm_refine":
        client = ScriptedClient(_responses(config))
        monkeypatch.setattr(pipeline_module, "_new_id", id_sequence())
        return _Boundary({"llm_client": client}, client=client)
    if profile in ("llm_seam",):
        client = ScriptedClient(_responses(config))
        seam = _make_seam(config)
        return _Boundary({"llm_client": client, "data_registry": seam}, client=client, seam=seam)
    if profile == "seam_missing_llm":
        client = ScriptedClient(_responses(config))
        return _Boundary({"llm_client": client}, client=client)
    if profile == "seam":
        seam = _make_seam(config)
        return _Boundary({"data_registry": seam}, seam=seam)
    if profile == "seam_sql":
        seam = RecordingSeam()
        seam.sources["src"] = SQLSourceDouble("src")
        return _Boundary({"data_registry": seam}, seam=seam)
    if profile == "seam_raises":
        seam = _RaisingSeam()
        return _Boundary({"data_registry": seam}, seam=seam)
    if profile in ("plan", "plan_discover"):
        monkeypatch.setattr(pipeline_module, "_new_id", id_sequence())
        return _Boundary({})
    raise AssertionError(f"unknown profile {profile!r}")


def _v2(name: str) -> Operator:
    return versioned_registry().resolve(f"{name}@2.0.0")


def _v1(name: str) -> Operator:
    return versioned_registry().resolve(f"{name}@1.0.0")


def _case(name: str, key: str) -> dict[str, Any]:
    return cast("dict[str, Any]", _ROWS[name]["cases"][key])


def _assert_side_effects(name: str, case: dict[str, Any], boundary: _Boundary) -> None:
    """Assert the exact durable side-effect calls a case claims (registry calls or SQL commits)."""
    expected_calls = case.get("expected_seam_calls")
    if expected_calls is not None:
        assert boundary.seam is not None, f"{name}: side-effect check needs a seam"
        for method, count in expected_calls.items():
            actual = len(boundary.seam.calls_to(method))
            assert actual == count, f"{name}: {method} called {actual}x, expected {count}"
    commits = case.get("expected_sql_commits")
    if commits is not None:
        assert boundary.seam is not None
        source = boundary.seam.sources.get("src")
        total = sum(c.commits for c in source.connections.values()) if source is not None else 0
        assert total == commits, f"{name}: {total} SQL commits, expected {commits}"


def _invoke_raw(
    operator: Operator,
    check: dict[str, Any],
    input_data: DataBundle,
    attrs: Attributes,
    properties: dict[str, Any] | None,
) -> Any:
    method = check["method"]
    if method == "apply":
        return operator.apply(input_data, attrs, properties)
    if method == "validate":
        if check.get("with_properties"):
            return operator.validate(input_data, attrs, properties)
        return operator.validate(input_data, attrs)
    raise AssertionError(f"unknown raw method {method!r}")


def _spy_body(operator: Operator, monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Count real _execute entries by wrapping, without replacing the operator body."""
    counter = {"n": 0}
    attr = "_execute"
    original: Any = getattr(operator, attr)

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        counter["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(operator, attr, wrapper)
    return counter


# --------------------------------------------------------------------------------------------------
# Structural and mutation controls
# --------------------------------------------------------------------------------------------------
def test_exactly_the_32_retained_versioned_names() -> None:
    registry_names = sorted(
        {c.operator_id.split("@")[0] for c in versioned_registry().list_cards()}
    )
    assert registry_names == _NAMES
    assert len(_NAMES) == 32
    assert _FIXTURE["operator_count"] == 36


def test_fixture_is_canonical_json_with_expected_structure() -> None:
    checked_in = _FIXTURE_PATH.read_text()
    parsed = json.loads(checked_in)
    rendered = json.dumps(parsed, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    assert rendered == checked_in, "fixture is not canonically formatted"
    assert parsed["operator_count"] == 36
    assert set(parsed) >= {"operator_count", "source_manifest", "rows"}
    assert set(parsed["source_manifest"]) >= {"files", "aggregate_sha256"}
    assert {row["name"] for row in parsed["rows"]} == set(_ROWS)
    assert set(_NAMES) < set(_ROWS)


def test_source_manifest_matches_current_sources() -> None:
    import hashlib

    src = _LIB / "src/blue_data_ops/operators"
    recomputed = {
        name: hashlib.sha256((src / f"{name}_operator.py").read_bytes()).hexdigest()
        for name in _NAMES
    }
    expected_files = _FIXTURE["source_manifest"]["files"]
    assert recomputed == {name: expected_files[name] for name in _NAMES}
    row_manifest = {name: _ROWS[name]["source_sha256"] for name in _NAMES}
    assert row_manifest == recomputed


@pytest.mark.parametrize("name", _NAMES)
def test_selected_version_identity(name: str) -> None:
    assert _v2(name).operator_id == f"{name}@2.0.0"
    assert _v1(name).operator_id == f"{name}@1.0.0"


# --------------------------------------------------------------------------------------------------
# Per-operator outcome execution
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", _NAMES)
def test_success(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _case(name, "success")
    boundary = _build_boundary(case.get("profile", "none"), case.get("config", {}), monkeypatch)
    operator = _v2(name)

    caller_attrs = copy.deepcopy(case["attributes"])
    out, out_attrs, meta = operator.run(
        copy.deepcopy(case["input"]), caller_attrs, boundary.properties
    )
    assert meta.errors == [], f"{name}: unexpected {meta.errors}"
    assert isinstance(out_attrs, dict)
    assert out_attrs is not caller_attrs, (
        f"{name}: output_attributes must not alias the caller dict"
    )
    _assert_side_effects(name, case, boundary)
    if case.get("is_empty"):
        assert_successful_empty((out, out_attrs, meta))
        return
    assert meta.is_empty is False
    if case.get("expected_output") is not None:
        assert out == case["expected_output"], f"{name}: {out!r}"
    if case.get("assert_nonempty"):
        assert any(group for group in out), f"{name}: expected a non-empty group, got {out!r}"
    if case.get("assert_fidelity"):
        raw = operator.apply(
            copy.deepcopy(case["input"]), copy.deepcopy(case["attributes"]), boundary.properties
        )
        assert out == raw, f"{name}: run output diverged from the raw body"


@pytest.mark.parametrize("name", _NAMES)
def test_successful_empty_or_no_result(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _case(name, "empty")
    boundary = _build_boundary(case.get("profile", "none"), case.get("config", {}), monkeypatch)
    operator = _v2(name)

    out, out_attrs, meta = operator.run(
        copy.deepcopy(case["input"]), copy.deepcopy(case["attributes"]), boundary.properties
    )
    assert meta.errors == []
    _assert_side_effects(name, case, boundary)
    if case.get("no_empty_path"):
        # A total operator with no successful-empty path: the no-result assertion is a non-empty,
        # error-free result (documented in the fixture's semantic_note).
        assert meta.is_empty is False
        assert any(group for group in out), f"{name}: {out!r}"
    elif case.get("is_empty", True):
        assert_successful_empty((out, out_attrs, meta))
    else:
        assert meta.is_empty is False, f"{name}: neutral row must not be flagged empty"
        assert out == case["expected_output"], f"{name}: {out!r}"


@pytest.mark.parametrize("name", _NAMES)
def test_recoverable_invalid_input(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _case(name, "invalid")
    boundary = _build_boundary(case.get("profile", "none"), case.get("config", {}), monkeypatch)
    operator = _v2(name)
    op_id = f"{name}@2.0.0"
    body_calls = _spy_body(operator, monkeypatch)

    _, _, meta = operator.run(
        copy.deepcopy(case["input"]), copy.deepcopy(case["attributes"]), boundary.properties
    )
    error = assert_recoverable_invalid(meta, op_id)
    assert case["suggestion_substr"] in (error.suggestion or ""), (
        f"{name}: {error.suggestion!r} lacks {case['suggestion_substr']!r}"
    )
    assert boundary.no_boundary_calls(), f"{name}: invalid input must not call a body/seam"
    assert body_calls["n"] == 0, f"{name}: recoverable-invalid must not enter the real body"


@pytest.mark.parametrize("name", [n for n in _NAMES if _ROWS[n]["cases"].get("failure")])
def test_contained_failure(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _case(name, "failure")
    boundary = _build_boundary(case.get("profile", "none"), case.get("config", {}), monkeypatch)
    operator = _v2(name)
    op_id = f"{name}@2.0.0"
    code = _CODE[case["code"]]
    stage = _STAGE[case["stage"]]

    out, out_attrs, meta = operator.run(
        copy.deepcopy(case["input"]), copy.deepcopy(case["attributes"]), boundary.properties
    )
    assert out == [[]]
    assert out_attrs == {}
    assert_contained_failure(meta, op_id, code, stage)


@pytest.mark.parametrize("name", _NAMES)
def test_raw_v1_divergence(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # Execute the row's raw v1 claim through apply() or validate() and check its concrete result.
    check = _case(name, "raw_v1")
    assert isinstance(check.get("note"), str) and check["note"]
    if "from_case" in check:
        source = _case(name, check["from_case"])
        input_data = copy.deepcopy(source["input"])
        attrs = copy.deepcopy(source["attributes"])
        profile = check.get("profile", source.get("profile", "none"))
        config = check.get("config", source.get("config", {}))
    else:
        input_data = copy.deepcopy(check["input"])
        attrs = copy.deepcopy(check["attributes"])
        profile = check.get("profile", "none")
        config = check.get("config", {})
    boundary = _build_boundary(profile, config, monkeypatch)
    operator = _v2(name)

    if check.get("expected_raises"):
        with pytest.raises(Exception):  # noqa: B017 — the raw body's own exception type varies
            _invoke_raw(operator, check, input_data, attrs, boundary.properties)
    elif "expected_bool" in check:
        result = _invoke_raw(operator, check, input_data, attrs, boundary.properties)
        assert result is check["expected_bool"], f"{name}: raw validate = {result!r}"
    else:
        result = _invoke_raw(operator, check, input_data, attrs, boundary.properties)
        assert result == check["expected"], f"{name}: raw {check['method']} = {result!r}"


@pytest.mark.parametrize("name", _NAMES)
def test_selected_error_identity(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # The recoverable-invalid edge suppresses the body, so it exercises the selected-version error
    # identity without a provider call: v1 carries name@1.0.0, v2 carries name@2.0.0.
    case = _case(name, "invalid")
    for version, expected in (("1.0.0", f"{name}@1.0.0"), ("2.0.0", f"{name}@2.0.0")):
        boundary = _build_boundary(case.get("profile", "none"), case.get("config", {}), monkeypatch)
        operator = versioned_registry().resolve(f"{name}@{version}")
        _, _, meta = operator.run(
            copy.deepcopy(case["input"]), copy.deepcopy(case["attributes"]), boundary.properties
        )
        assert first_error(meta).operator_id == expected


@pytest.mark.parametrize("name", _NAMES)
def test_result_containers_are_fresh(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # Two independent calls must not share output-attribute, ExecMeta, or ErrorRecord containers, so
    # an aliasing regression cannot pass while this suite is green.
    # The empty edge covers the successful result boundary (no provider call).
    # The invalid edge covers the error path.
    def _run(case: dict[str, Any]) -> tuple[Any, ExecMeta]:
        boundary = _build_boundary(case.get("profile", "none"), case.get("config", {}), monkeypatch)
        operator = _v2(name)
        out_attrs, meta = operator.run(
            copy.deepcopy(case["input"]), copy.deepcopy(case["attributes"]), boundary.properties
        )[1:]
        return out_attrs, meta

    empty = _case(name, "empty")
    a_attrs, a_meta = _run(empty)
    b_attrs, b_meta = _run(empty)
    assert a_attrs is not b_attrs
    assert a_meta.errors is not b_meta.errors
    assert a_meta.logs is not b_meta.logs
    assert a_meta.traces is not b_meta.traces

    invalid = _case(name, "invalid")
    _, c_meta = _run(invalid)
    _, d_meta = _run(invalid)
    assert c_meta.errors is not d_meta.errors
    assert c_meta.errors[0] is not d_meta.errors[0], f"{name}: ErrorRecord container reused"


# --------------------------------------------------------------------------------------------------
# Timeout representatives by operator family
# --------------------------------------------------------------------------------------------------
class _SlowValue:
    """A field value whose real numeric coercion blocks, so the pure body times out mid-run."""

    def __init__(self, started: threading.Event, finished: threading.Event) -> None:
        self._started = started
        self._finished = finished
        self.calls = 0

    def __int__(self) -> int:
        self.calls += 1
        self._started.set()
        time.sleep(0.2)
        self._finished.set()
        return 0

    def __float__(self) -> float:
        return float(self.__int__())


class _SlowClient(LLMClient):
    def __init__(self, started: threading.Event, finished: threading.Event) -> None:
        self.started = started
        self.finished = finished
        self.calls = 0

    def execute_api_call(
        self,
        input: Any,
        properties: Any = None,
        additional_data: Any = None,  # noqa: A002
    ) -> Any:
        self.calls += 1
        self.started.set()
        time.sleep(0.2)
        self.finished.set()
        return [{"x": 1}]


class _SlowSeam(RecordingSeam):
    def __init__(self, started: threading.Event, finished: threading.Event) -> None:
        super().__init__()
        self.started = started
        self.finished = finished
        self.hits = 0

    def search_records_hierarchical(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        self.hits += 1
        self.started.set()
        time.sleep(0.2)
        self.finished.set()
        return []


def test_timeout_pure_family() -> None:
    started, finished = threading.Event(), threading.Event()
    slow = _SlowValue(started, finished)
    operator = _v2("sum")
    out, out_attrs, meta = operator.run(
        [[{"value": slow}]],
        {"sum_key": "value"},
        {"execution.timeout_seconds": 0.02},
    )
    assert out == [[]]
    assert out_attrs == {}
    assert_timeout(meta, "sum@2.0.0", ErrorStage.EXECUTE)
    assert started.wait(timeout=1.0), "the real pure body must have started once"
    assert finished.wait(timeout=1.0), "the late result completes but is discarded"
    assert slow.calls == 1, "the real numeric coercion is entered exactly once"


def test_timeout_llm_family() -> None:
    started, finished = threading.Event(), threading.Event()
    client = _SlowClient(started, finished)
    operator = _v2("nl2llm")
    _, _, meta = operator.run(
        [[]], {"query": "list roles"}, {"llm_client": client, "execution.timeout_seconds": 0.02}
    )
    assert_timeout(meta, "nl2llm@2.0.0", ErrorStage.EXECUTE)
    assert started.wait(timeout=1.0)
    assert client.calls == 1, "the real provider boundary is entered exactly once"
    assert finished.wait(timeout=1.0)


def test_timeout_data_registry_family() -> None:
    started, finished = threading.Event(), threading.Event()
    seam = _SlowSeam(started, finished)
    operator = _v2("data_discover")
    _, _, meta = operator.run(
        [[]],
        {"search_query": "orders", "approximate": False},
        {"data_registry": seam, "execution.timeout_seconds": 0.02},
    )
    assert_timeout(meta, "data_discover@2.0.0", ErrorStage.EXECUTE)
    assert started.wait(timeout=1.0)
    assert finished.wait(timeout=1.0)
    assert seam.hits == 1, "the real registry search is entered exactly once"
