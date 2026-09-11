from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from types import ModuleType

import pytest

from blue_data_ops.operators import versioned_registry
from blue_data_ops.operators.types import ErrorCode, ErrorStage

from ._settings_conformance import (
    EffectiveReadCensus,
    assert_guide_matches_operator,
    effective_read_census,
    source_for_operator,
)


def _guide_for(census: EffectiveReadCensus) -> str:
    lines = [
        "# Synthetic",
        "",
        "## Settings",
        "",
        "| Name | Input | Declared | Effective default | Validation | Kind |",
        "|---|---|---|---|---|---|",
    ]
    lines.extend(
        f"| {row.name} | {row.input} | {row.declared} | {row.effective_default} | "
        f"{row.validation} | {row.kind} |"
        for row in census.expected
    )
    return "\n".join(lines) + "\n"


def _load_module(path: Path, name: str, source: str) -> ModuleType:
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _synthetic_operator(tmp_path: Path, child_body: str) -> object:
    suffix = tmp_path.name.replace("-", "_")
    base_name = f"arbitrary_settings_base_{suffix}"
    base = """
from blue_data_ops.data.provider import resolve_registry
from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.types import AttributeSpec, FunctionResult, ValidationResult


def inherited_helper(attributes, properties):
    properties = properties or {}
    properties.get("helper_only", 11)
    attributes.get("helper_attribute", "helper-default")


class ArbitraryBase(Operator):
    name = "arbitrary_base"
    description = "Synthetic inheritance base"
    attributes = {"required_key": AttributeSpec(type="str", required=True)}
    DEFAULT_PROPERTIES = {}

    def apply(self, input_data, attributes, properties=None):
        return self._execute(input_data, attributes, properties).output_data

    def _execute(self, input_data, attributes, properties=None):
        properties = properties or {}
        attributes.get("inherited_attribute", "fallback")
        properties.get("inherited_limit", 7)
        inherited_helper(attributes, properties)
        resolve_registry(properties)
        return FunctionResult([], {})

    def _validate_input(self, input_data, attributes, properties=None):
        attributes.get("base_validation")
        return ValidationResult(True, None)


class ArbitraryMiddle(ArbitraryBase):
    def _validate_input(self, input_data, attributes, properties=None):
        attributes.get("middle_validation")
        return super()._validate_input(input_data, attributes, properties)
"""
    _load_module(tmp_path / f"{base_name}.py", base_name, base)
    child_name = f"arbitrary_settings_child_{suffix}"
    child = f"""
from {base_name} import ArbitraryMiddle
from blue_data_ops.operators.types import FunctionResult


class ArbitraryOutcomeName(ArbitraryMiddle):
{child_body}
"""
    module = _load_module(tmp_path / f"{child_name}.py", child_name, child)
    return module.ArbitraryOutcomeName()


def _chain_operator(tmp_path: Path, callable_count: int) -> object:
    assert callable_count >= 1
    suffix = tmp_path.name.replace("-", "_")
    module_name = f"arbitrary_settings_chain_{callable_count}_{suffix}"
    helper_count = callable_count - 1
    helpers: list[str] = []
    for index in range(helper_count):
        if index + 1 < helper_count:
            body = f"return helper_{index + 1}(attributes)"
        else:
            body = 'return attributes.get("terminal_setting", 64)'
        helpers.append(f"def helper_{index}(attributes):\n    {body}\n")
    entry = "return helper_0(attributes)" if helpers else "return None"
    source = (
        "\n".join(helpers)
        + f"""
class ArbitraryBoundOperator:
    def apply(self, input_data, attributes, properties=None):
        {entry}
"""
    )
    module = _load_module(tmp_path / f"{module_name}.py", module_name, source)
    return module.ArbitraryBoundOperator()


def _recursive_operator(tmp_path: Path) -> object:
    suffix = tmp_path.name.replace("-", "_")
    module_name = f"arbitrary_settings_recursion_{suffix}"
    source = """
def recursive_helper(attributes):
    attributes.get("recursive_setting", 13)
    return recursive_helper(attributes)


class ArbitraryRecursiveOperator:
    attributes = {}
    DEFAULT_PROPERTIES = {}

    def apply(self, input_data, attributes, properties=None):
        return recursive_helper(attributes)
"""
    module = _load_module(tmp_path / f"{module_name}.py", module_name, source)
    return module.ArbitraryRecursiveOperator()


def test_join_raw_fallback_does_not_make_structured_calls_optional() -> None:
    operator = versioned_registry().resolve("join@3.0.0")
    input_data = [[{"key": 1}], [{"key": 1}]]

    assert operator.apply(input_data, {}) == []
    assert operator.invoke(input_data, {}) is None
    output, output_attributes, meta = operator.run(input_data, {})
    assert output == [[]]
    assert output_attributes == {}
    assert len(meta.errors) == 1
    assert meta.errors[0].code is ErrorCode.INVALID_INPUT
    assert meta.errors[0].stage is ErrorStage.VALIDATE


def test_inherited_execution_super_chain_and_helpers_are_acquired(tmp_path: Path) -> None:
    operator = _synthetic_operator(
        tmp_path,
        """    def _validate_input(self, input_data, attributes, properties=None):
        attributes.get("child_validation")
        return super()._validate_input(input_data, attributes, properties)
""",
    )
    census = effective_read_census(operator)
    identities = {(row.name, row.input) for row in census.expected}
    assert {
        ("base_validation", "attributes"),
        ("child_validation", "attributes"),
        ("data_registry", "properties"),
        ("data_registry.name", "properties"),
        ("helper_attribute", "attributes"),
        ("helper_only", "properties"),
        ("inherited_attribute", "attributes"),
        ("inherited_limit", "properties"),
        ("middle_validation", "attributes"),
        ("platform.name", "properties"),
    } <= identities

    source = source_for_operator(operator)
    symbols = [unit.symbol for unit in source.provenance]
    assert len(symbols) == len(set(symbols))
    assert any(symbol.endswith("ArbitraryBase._execute") for symbol in symbols)
    assert any(symbol.endswith("ArbitraryMiddle._validate_input") for symbol in symbols)
    assert any(symbol.endswith("inherited_helper") for symbol in symbols)


def test_source_acquisition_accepts_exactly_64_callables(tmp_path: Path) -> None:
    source = source_for_operator(_chain_operator(tmp_path, 64))
    assert len(source.provenance) == 65  # primary module plus 64 callable units


def test_source_acquisition_rejects_the_65th_callable(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="source acquisition exceeded its bound"):
        source_for_operator(_chain_operator(tmp_path, 65))


def test_recursive_helper_is_acquired_once(tmp_path: Path) -> None:
    operator = _recursive_operator(tmp_path)
    source = source_for_operator(operator)
    recursive_units = [
        unit for unit in source.provenance if unit.symbol.endswith("recursive_helper")
    ]
    assert len(recursive_units) == 1
    rows = {(row.name, row.input) for row in effective_read_census(operator).expected}
    assert ("recursive_setting", "attributes") in rows


def test_literal_empty_mapping_fallback_supplies_default(tmp_path: Path) -> None:
    operator = _synthetic_operator(
        tmp_path,
        """    def _execute(self, input_data, attributes, properties=None):
        (properties or {}).get("fallback_limit", 32)
        (properties or {"unsupported_limit": 64}).get("unsupported_limit", 64)
        return FunctionResult([], {})
""",
    )
    rows = {(row.name, row.input): row for row in effective_read_census(operator).expected}
    assert rows[("fallback_limit", "properties")].effective_default == "32"
    assert ("unsupported_limit", "properties") not in rows


def test_shadowed_execution_settings_are_not_acquired(tmp_path: Path) -> None:
    operator = _synthetic_operator(
        tmp_path,
        """    def _execute(self, input_data, attributes, properties=None):
        properties = properties or {}
        properties.get("live_override", 5)
        return FunctionResult([], {})
""",
    )
    identities = {(row.name, row.input) for row in effective_read_census(operator).expected}
    assert ("live_override", "properties") in identities
    assert ("inherited_limit", "properties") not in identities
    assert ("helper_only", "properties") not in identities


def test_explicit_super_execution_keeps_both_effective_paths(tmp_path: Path) -> None:
    operator = _synthetic_operator(
        tmp_path,
        """    def _execute(self, input_data, attributes, properties=None):
        properties = properties or {}
        properties.get("child_limit", 3)
        return super()._execute(input_data, attributes, properties)
""",
    )
    identities = {(row.name, row.input) for row in effective_read_census(operator).expected}
    assert ("child_limit", "properties") in identities
    assert ("inherited_limit", "properties") in identities


def test_dynamic_operator_dispatch_fails_closed(tmp_path: Path) -> None:
    operator = _synthetic_operator(
        tmp_path,
        """    def _execute(self, input_data, attributes, properties=None):
        handler = getattr(self, "runtime_selected_handler")
        return handler(input_data, attributes, properties)
""",
    )
    with pytest.raises(AssertionError, match="unsupported dynamic operator dispatch"):
        source_for_operator(operator)


def test_old_subclass_only_source_omits_a_live_inherited_setting(tmp_path: Path) -> None:
    operator = _synthetic_operator(
        tmp_path,
        """    def _validate_input(self, input_data, attributes, properties=None):
        return super()._validate_input(input_data, attributes, properties)
""",
    )
    primary_path = inspect.getsourcefile(type(operator))
    assert primary_path is not None
    old_census = effective_read_census(
        operator,
        source=Path(primary_path).read_text(encoding="utf-8"),
    )
    assert not any(row.name == "inherited_limit" for row in old_census.expected)
    with pytest.raises(AssertionError, match="Settings mismatch"):
        assert_guide_matches_operator(_guide_for(old_census), operator)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("name", "changed_limit"),
        ("input", "attributes"),
        ("declared", "yes"),
        ("effective_default", "8"),
        ("validation", "runtime-check"),
        ("kind", "structured"),
    ),
)
def test_each_inherited_setting_field_is_live(tmp_path: Path, field: str, replacement: str) -> None:
    operator = _synthetic_operator(
        tmp_path,
        """    def _validate_input(self, input_data, attributes, properties=None):
        return super()._validate_input(input_data, attributes, properties)
""",
    )
    guide = _guide_for(effective_read_census(operator))
    row = "| inherited_limit | properties | no | 7 | none | scalar |"
    values = ["inherited_limit", "properties", "no", "7", "none", "scalar"]
    values[
        ("name", "input", "declared", "effective_default", "validation", "kind").index(field)
    ] = replacement
    mutated = "| " + " | ".join(values) + " |"
    with pytest.raises(AssertionError):
        assert_guide_matches_operator(guide.replace(row, mutated), operator)


@pytest.mark.parametrize("mutation", ("missing", "duplicate"))
def test_inherited_setting_missing_and_duplicate_rows_fail(tmp_path: Path, mutation: str) -> None:
    operator = _synthetic_operator(
        tmp_path,
        """    def _validate_input(self, input_data, attributes, properties=None):
        return super()._validate_input(input_data, attributes, properties)
""",
    )
    guide = _guide_for(effective_read_census(operator))
    row = "| inherited_limit | properties | no | 7 | none | scalar |"
    guide = guide.replace(row, "" if mutation == "missing" else row + "\n" + row)
    with pytest.raises(AssertionError):
        assert_guide_matches_operator(guide, operator)


def test_actual_sql_inherited_sources_restore_prompt_registry_and_provider_rows() -> None:
    operator = versioned_registry().resolve("nl2sql@3.0.0")
    rows = {(row.name, row.input): row for row in effective_read_census(operator).expected}
    force_prefixes = rows[("force_query_prefixes", "attributes")]
    assert (
        force_prefixes.declared,
        force_prefixes.effective_default,
        force_prefixes.validation,
        force_prefixes.kind,
    ) == ("no", '"SELECT"', "none", "scalar")
    for name in ("data_registry", "data_registry.name", "platform.name"):
        assert rows[(name, "properties")].validation == "helper:resolve_registry"
    assert rows[("llm_client", "properties")].validation == "helper:resolve_llm_client"
    assert rows[("llm.*", "properties:llm.*")].kind == "namespace"


def test_another_new_inheritance_shape_acquires_the_effective_base_body() -> None:
    operator = versioned_registry().resolve("classify@3.0.0")
    source = source_for_operator(operator)
    symbols = {unit.symbol for unit in source.provenance}
    assert any(symbol.endswith("ClassifyOperator._execute") for symbol in symbols)
    rows = {(row.name, row.input): row for row in effective_read_census(operator).expected}
    assert rows[("algorithm", "properties")].effective_default == '"decision_tree"'


@pytest.mark.parametrize(
    ("expression", "effective_default", "kind"),
    (
        ('attributes.get("synthetic_setting", [])', "[]", "structured"),
        ('attributes.get("synthetic_setting", {})', "{}", "structured"),
        ('attributes.get("synthetic_setting", 7)', "7", "scalar"),
        ('attributes.get("synthetic_setting")', "none", "scalar"),
        ('attributes.get("synthetic_setting", object())', "source-dependent", "scalar"),
        ('"synthetic_setting" in attributes', "none", "presence"),
    ),
)
def test_undeclared_attribute_kind_follows_literal_default(
    tmp_path: Path,
    expression: str,
    effective_default: str,
    kind: str,
) -> None:
    operator = _synthetic_operator(
        tmp_path,
        f"""    def _execute(self, input_data, attributes, properties=None):
        {expression}
        return FunctionResult([], {{}})
""",
    )
    rows = {(row.name, row.input): row for row in effective_read_census(operator).expected}
    row = rows[("synthetic_setting", "attributes")]
    assert (row.declared, row.effective_default, row.validation, row.kind) == (
        "no",
        effective_default,
        "none",
        kind,
    )
