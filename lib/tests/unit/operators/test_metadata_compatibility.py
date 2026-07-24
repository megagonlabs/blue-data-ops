from __future__ import annotations

from typing import Any, ClassVar

import pytest

import blue_data_ops
import blue_data_ops.operators.operator as operator_module
from blue_data_ops.operators import (
    AttributeSpec,
    DataDiscoverOperator,
    ErrorCategory,
    ErrorCode,
    ErrorStage,
    NL2LLMOperator,
    Operator,
    OperatorRegistry,
    PlanDiscoverOperator,
    SelectOperator,
)
from blue_data_ops.operators.plan_discover_operator import (
    plan_discover_operator_validator,
)
from blue_data_ops.plan import RefinableOperator
from blue_data_ops.tools import Tool
from blue_data_ops.tools.tool import Tool as ModuleTool
from tests.unit.operators._plan_operator_helpers import operator_ids

DATA = [[{"value": 1}]]


def sample_function(
    input_data: list[list[dict[str, Any]]],
    attributes: dict[str, Any],
    properties: dict[str, Any] | None = None,
) -> list[list[dict[str, Any]]]:
    del attributes, properties
    return input_data


def options_function(
    input_data: list[list[dict[str, Any]]],
    options: dict[str, Any],
    properties: dict[str, Any] | None = None,
) -> list[list[dict[str, Any]]]:
    del options, properties
    return input_data


def custom_validator(
    input_data: list[list[dict[str, Any]]],
    attributes: dict[str, Any],
    properties: dict[str, Any] | None = None,
) -> bool:
    del input_data, properties
    return attributes.get("ok") is True


def custom_explainer(
    output: object,
    input_data: list[list[dict[str, Any]]],
    attributes: dict[str, Any],
) -> dict[str, Any]:
    return {"output": output, "inputs": len(input_data), "attributes": attributes}


def custom_refiner(
    input_data: list[list[dict[str, Any]]],
    attributes: dict[str, Any],
    properties: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    del properties
    return [{"groups": len(input_data), "attributes": attributes}]


class ProbeOperator(Operator):
    name = "metadata_probe"
    description = "metadata probe"
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "alpha": AttributeSpec(
            "int",
            description="class alpha",
            required=True,
            default=1,
        ),
        "optional": AttributeSpec("list[int]", default=[1]),
    }
    PROPERTIES = {
        "class_only": "class",
        "shared": "class",
        "timeout": 222,
        "hyperparameters": {"hp_class": {"value": 1}},
    }

    def apply(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
        del attributes, properties
        return input_data


class ProbeRefiner(RefinableOperator):
    name = "metadata_refiner"
    description = "metadata refiner"
    attributes = {"alpha": AttributeSpec("int", required=True)}

    def apply(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
        del attributes, properties
        return input_data

    def refiner(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        del input_data, attributes, properties
        return []


class CopyBomb:
    def __deepcopy__(self, memo: dict[int, object]) -> object:
        del memo
        raise RuntimeError("private default payload")


class BrokenDefaultProbe(ProbeOperator):
    attributes = {"bad": AttributeSpec("str", default=CopyBomb())}


def test_public_tool_imports_and_direct_constructor_fields() -> None:
    assert blue_data_ops.Tool is Tool is ModuleTool
    tool_properties = {"nested": {"value": [1]}}
    tool = Tool(
        "direct",
        sample_function,
        description="description",
        properties=tool_properties,
        validator=custom_validator,
        explainer=custom_explainer,
    )
    assert tool.name == "direct"
    assert tool.description == "description"
    assert tool.function is sample_function
    assert tool.validator is custom_validator
    assert tool.explainer is custom_explainer
    assert tool.properties is not tool_properties
    assert tool.properties["nested"] is tool_properties["nested"]

    operator = ProbeOperator(
        "direct-operator",
        function=sample_function,
        description="operator description",
        validator=custom_validator,
        explainer=custom_explainer,
        refiner=custom_refiner,
    )
    assert operator.name == "direct-operator"
    assert operator.description == "operator description"
    assert operator.function is sample_function
    assert operator.validator is custom_validator
    assert operator.explainer is custom_explainer
    assert getattr(operator, "refiner") is custom_refiner


def test_blue_stored_defaults_merge_order_and_per_instance_class_state() -> None:
    first = ProbeOperator()
    second = ProbeOperator()
    assert first.properties["tool_type"] == "operator"
    assert first.properties["validate_input"] is True
    assert first.properties["validate_output"] is True
    assert first.properties["validation_error_handling"] == "fail"
    assert first.properties["max_records"] is None
    assert first.properties["timeout"] == 222
    assert first.properties["error_handling"] == "skip"
    assert first.properties["log_processing_stats"] is True
    assert first.properties["refine"] is False
    assert first.properties["class_only"] == "class"
    assert first.get_attributes() is not second.get_attributes()
    assert first.get_hyperparameters() is not second.get_hyperparameters()

    constructor_attributes = {
        "alpha": {
            "type": "int",
            "description": "constructor alpha",
            "required": False,
            "default": 2,
        }
    }
    constructor_hyperparameters = {"hp": {"value": [2]}}
    properties = {
        "shared": "constructor",
        "timeout": 111,
        "attributes": constructor_attributes,
        "hyperparameters": constructor_hyperparameters,
        "signature": {"discarded": True},
    }
    instance = ProbeOperator(properties=properties)
    assert instance.properties["shared"] == "constructor"
    assert instance.properties["timeout"] == 111
    assert instance.properties["class_only"] == "class"
    assert instance.get_attributes() is constructor_attributes
    assert instance.get_hyperparameters() is constructor_hyperparameters
    assert instance.get_signature() is not properties["signature"]


def test_all_tool_methods_keep_live_identity_and_missing_behavior() -> None:
    tool = Tool("tool", sample_function)
    copied = tool.get_properties()
    assert copied == tool.properties
    assert copied is not tool.properties
    assert copied["signature"] is tool.properties["signature"]

    head = {"new": {"nested": {"values": [1]}}}
    merged = tool.get_properties(head)
    assert merged["new"] is not head["new"]
    assert merged["new"]["nested"] is not head["new"]["nested"]
    assert merged["new"]["nested"]["values"] is head["new"]["nested"]["values"]

    parameters = tool.get_parameters()
    assert parameters is not None
    assert parameters is tool.get_signature()["parameters"]
    parameter = tool.get_parameter("attributes")
    assert parameter is not None
    assert parameter is parameters["attributes"]
    assert tool.get_parameter_type("attributes") == "object"
    assert tool.set_parameter_description("attributes", "attrs") is parameter
    assert tool.set_parameter_required("attributes", False) is parameter
    assert tool.set_parameter_hidden("attributes", True) is parameter
    assert tool.is_parameter_required("attributes") is False
    assert tool.is_parameter_hidden("attributes") is True
    returns = tool.get_returns()
    assert returns is not None
    assert returns is tool.get_signature()["returns"]
    assert tool.get_returns_type() == "array"
    assert tool.set_returns_description("rows") is returns

    assert tool.get_parameter("missing") is None
    assert tool.get_parameter_type("missing") is None
    assert tool.set_parameter_description("missing", "x") is None
    assert tool.set_parameter_required("missing", True) is None
    assert tool.set_parameter_hidden("missing", True) is None
    assert tool.is_parameter_required("missing") is None
    assert tool.is_parameter_hidden("missing") is None
    tool.get_signature().clear()
    assert tool.get_parameters() is None
    assert tool.get_returns() is None
    assert tool.get_returns_type() is None
    assert tool.set_returns_description("x") is None


def test_operator_methods_alias_updates_and_signature_regeneration() -> None:
    constructor_attributes = {
        "alpha": {
            "type": "int",
            "description": "constructor alpha",
            "required": False,
            "hidden": False,
            "default": 2,
        }
    }
    constructor_hyperparameters = {"hp": {"value": [1]}}
    operator = ProbeOperator(
        function=sample_function,
        properties={
            "attributes": constructor_attributes,
            "hyperparameters": constructor_hyperparameters,
        },
    )
    assert operator.get_attributes() is constructor_attributes
    assert operator.get_hyperparameters() is constructor_hyperparameters
    assert operator.get_attribute("alpha") is constructor_attributes["alpha"]
    assert operator.get_attribute_type("alpha") == "int"
    assert operator.get_attribute_description("alpha") == "constructor alpha"

    signature = operator.get_signature()
    parameter = operator.get_parameter("attributes")
    returns = operator.get_returns()
    assert parameter is not None
    assert returns is not None
    assert parameter["properties"] is not constructor_attributes
    alpha = operator.get_attribute("alpha")
    assert alpha is not None
    alpha["description"] = "direct"
    assert parameter["properties"]["alpha"]["description"] == "constructor alpha"
    operator.set_parameter_description("attributes", "manual")
    operator.set_returns_description("manual")
    assert operator.set_attribute_description("alpha", "setter") is None
    assert operator.get_signature() is not signature
    assert operator.get_parameter("attributes") is not parameter
    assert operator.get_returns() is not returns
    refreshed_parameter = operator.get_parameter("attributes")
    refreshed_returns = operator.get_returns()
    assert refreshed_parameter is not None
    assert refreshed_returns is not None
    assert "description" not in refreshed_parameter
    assert "description" not in refreshed_returns
    assert refreshed_parameter["properties"]["alpha"]["description"] == "setter"
    assert operator.set_attribute_required("alpha", True) is None
    assert operator.is_attribute_required("alpha") is True
    assert operator.set_attribute_hidden("alpha", True) is None
    assert operator.is_attribute_hidden("alpha") is True

    attr_update = {"delta": {"type": "dict", "description": "delta"}}
    hp_update = {"new": {"value": [1]}}
    assert operator.update_attributes(attr_update) is None
    assert operator.update_hyperparameters(hp_update) is None
    attr_update["delta"]["description"] = "caller change"
    hp_update["new"]["value"].append(2)
    assert operator.get_attribute_description("delta") == "caller change"
    assert operator.get_hyperparameters()["new"] == {"value": [1, 2]}
    refreshed_parameter = operator.get_parameter("attributes")
    assert refreshed_parameter is not None
    assert refreshed_parameter["properties"]["delta"]["description"] == "delta"

    assert operator.get_attribute("missing") is None
    assert operator.get_attribute_type("missing") is None
    assert operator.get_attribute_description("missing") is None
    unchanged = operator.get_signature()
    assert operator.set_attribute_description("missing", "x") is None
    assert operator.set_attribute_required("missing", True) is None
    assert operator.set_attribute_hidden("missing", True) is None
    assert operator.is_attribute_required("missing") is None
    assert operator.is_attribute_hidden("missing") is None
    assert operator.get_signature() is unchanged
    assert operator.update_attributes(None) is None
    assert operator.update_hyperparameters(None) is None
    assert Operator.is_operator(operator) is True
    assert Operator.is_operator(object()) is False
    assert Operator.get_tool_type(operator) == "operator"
    assert Operator.get_tool_type(object()) == "function"


def test_signature_parameter_coupling_and_falsy_default_quirk() -> None:
    attributes = {
        "number": {"type": "int", "description": "number", "required": True},
        "text": {"type": "str", "description": "text", "required": False},
    }
    named = ProbeOperator(function=sample_function, properties={"attributes": attributes})
    control = ProbeOperator(function=options_function, properties={"attributes": attributes})
    named_attributes = named.get_parameter("attributes")
    control_options = control.get_parameter("options")
    assert named_attributes is not None
    assert control_options is not None
    assert named_attributes["properties"]["number"]["type"] == {"type": "number"}
    assert named_attributes["properties"]["text"]["type"] == {"type": "string"}
    assert control_options["properties"] == {}
    assert control.get_parameter("attributes") is None

    def false_defaults(
        zero: int = 0,
        false: bool = False,
        empty_string: str = "",
        empty_list: list[Any] = [],  # noqa: B006 - compatibility fixture
        empty_dict: dict[str, Any] = {},  # noqa: B006 - compatibility fixture
        none_value: object = None,
        truthy: int = 2,
    ) -> int:
        del zero, false, empty_string, empty_list, empty_dict, none_value
        return truthy

    parameters = Tool("defaults", false_defaults).get_parameters()
    assert parameters is not None
    for name in [
        "zero",
        "false",
        "empty_string",
        "empty_list",
        "empty_dict",
        "none_value",
    ]:
        assert parameters[name]["required"] is True
        assert "default" not in parameters[name]
    assert parameters["truthy"]["required"] is False
    assert parameters["truthy"]["default"] == 2


def test_default_helpers_and_validation_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    assert operator_module.default_operator_function(DATA, {}) == []
    assert operator_module.default_operator_refiner(DATA, {}) == []
    assert operator_module.default_operator_validator(DATA, {}) is True
    explanation = operator_module.default_operator_explainer(DATA, DATA, {"x": 1})
    assert sorted(explanation) == [
        "attributes",
        "num_input_data",
        "num_input_records",
        "num_input_records_per_data",
        "num_output_data",
        "num_output_records",
        "output",
        "transformation_ratio",
    ]

    def fail_type(value: Any, expected_type: str) -> bool:
        del value, expected_type
        raise RuntimeError("type failure")

    monkeypatch.setattr(operator_module, "validate_parameter_type", fail_type)
    for mode, expected in [("log", False), ("skip", True), ("other", True)]:
        properties = {
            "attributes": {"x": {"type": "int", "required": True}},
            "validation_error_handling": mode,
        }
        assert operator_module.default_attributes_validator({"x": 1}, properties) is expected
        assert operator_module.default_operator_validator(DATA, {"x": 1}, properties) is expected
    fail_properties = {
        "attributes": {"x": {"type": "int", "required": True}},
        "validation_error_handling": "fail",
    }
    with pytest.raises(RuntimeError, match="type failure"):
        operator_module.default_attributes_validator({"x": 1}, fail_properties)
    assert operator_module.default_operator_validator(DATA, {"x": 1}, fail_properties) is False


def test_version_bindings_share_one_live_metadata_state() -> None:
    registry = OperatorRegistry()
    target = ProbeOperator()
    first = registry.register(target, "1.0.0")
    second = registry.register(target, "2.0.0")
    v1 = registry.resolve(first.operator_id)
    v2 = registry.resolve(second.operator_id)
    assert v1 is target
    assert v2 is not target
    assert v2.properties is v1.properties
    assert v2.get_attributes() is v1.get_attributes()
    assert v2.attributes is v1.attributes
    v2.set_attribute_description("alpha", "shared")
    assert v1.get_attribute_description("alpha") == "shared"
    assert v1.attributes["alpha"].description == "shared"
    assert v1.operator_id == "metadata_probe@1.0.0"
    assert v2.operator_id == "metadata_probe@2.0.0"


def test_plan_discover_bindings_validate_one_live_metadata_state() -> None:
    discovery = OperatorRegistry()
    selectable = SelectOperator()
    discovery.register(selectable, "1.0.0", tags=("starter",))
    discovery.register(selectable, "2.0.0", tags=("starter",))
    registrations = OperatorRegistry()
    target = PlanDiscoverOperator(discovery)
    registrations.register(target, "1.0.0")
    registrations.register(target, "2.0.0")
    v1 = registrations.resolve("plan_discover@1.0.0")
    v2 = registrations.resolve("plan_discover@2.0.0")
    assert isinstance(v1, RefinableOperator)
    assert isinstance(v2, RefinableOperator)
    base = {
        "task": "starter",
        "data": "rows",
        "approximate": True,
        "search_query": "starter",
    }

    v2.update_attributes(
        {
            "live_edit": {
                "type": "str",
                "description": "required after registration",
                "required": True,
            }
        }
    )
    runtime_properties = {
        "caller": "runtime",
        "attributes": {"live_edit": {"type": "str", "required": False}},
    }
    for resolved in (v1, v2):
        assert resolved.validator is not None
        assert resolved.validate([[]], base, runtime_properties) is False
        assert resolved.validator([[]], base, runtime_properties) is False
        plans, meta = resolved.refine([[]], base, runtime_properties)
        assert plans == []
        assert meta.errors[0].category is ErrorCategory.RECOVERABLE
        assert meta.errors[0].code is ErrorCode.INVALID_INPUT
        assert meta.errors[0].stage is ErrorStage.VALIDATE
        assert meta.errors[0].operator_id == resolved.operator_id

        valid = {**base, "live_edit": "value"}
        assert resolved.validate([[]], valid, runtime_properties) is True
        assert resolved.validator([[]], valid, runtime_properties) is True
        plans, meta = resolved.refine([[]], valid, runtime_properties)
        assert len(plans) == 1
        assert meta.errors == []
        version = resolved.operator_id.rpartition("@")[2]
        assert operator_ids(plans[0].to_dict()) == [f"select@{version}"]

    v1.update_attributes(
        {
            "live_edit": {
                "type": "int",
                "description": "type changed through v1",
                "required": True,
            }
        }
    )
    for resolved in (v1, v2):
        assert resolved.validator is not None
        wrong_type = {**base, "live_edit": "wrong"}
        assert resolved.validate([[]], wrong_type) is False
        assert resolved.validator([[]], wrong_type) is False
        plans, meta = resolved.refine([[]], wrong_type)
        assert plans == []
        assert meta.errors[0].operator_id == resolved.operator_id
        assert resolved.validate([[]], {**base, "live_edit": 1}) is True
        plans, meta = resolved.refine([[]], {**base, "live_edit": 1})
        assert len(plans) == 1
        assert meta.errors == []
        version = resolved.operator_id.rpartition("@")[2]
        assert operator_ids(plans[0].to_dict()) == [f"select@{version}"]


def test_plan_discover_standalone_validator_uses_supplied_properties_only() -> None:
    attributes = {
        "task": "starter",
        "data": "rows",
        "approximate": True,
        "search_query": "starter",
    }
    properties = {
        "attributes": {"extra": {"type": "str", "required": True}},
        "validation_error_handling": "fail",
    }
    assert plan_discover_operator_validator([[]], attributes) is True
    assert plan_discover_operator_validator([[]], attributes, properties) is False
    assert (
        plan_discover_operator_validator(
            [[]],
            {**attributes, "extra": "value"},
            properties,
        )
        is True
    )


def test_malformed_live_schema_is_contained_only_on_canonical_boundaries() -> None:
    operator = ProbeOperator()
    operator.get_attributes()["alpha"] = "broken"  # type: ignore[assignment]
    assert operator.apply(DATA, {}) == DATA
    assert operator.validate(DATA, {}) is False
    assert operator.invoke(DATA, {}) is None
    output, output_attributes, meta = operator.run(DATA, {})
    assert output == [[]]
    assert output_attributes == {}
    assert meta.errors[0].category is ErrorCategory.FAILED
    assert meta.errors[0].code is ErrorCode.VALIDATION_FAILED
    assert meta.errors[0].stage is ErrorStage.VALIDATE
    assert "broken" not in meta.errors[0].message

    refinable = ProbeRefiner()
    refinable.get_attributes()["alpha"] = "broken"  # type: ignore[assignment]
    assert refinable.refiner(DATA, {}) == []
    plans, refine_meta = refinable.refine(DATA, {})
    assert plans == []
    assert refine_meta.errors[0].category is ErrorCategory.FAILED
    assert refine_meta.errors[0].code is ErrorCode.VALIDATION_FAILED
    assert refine_meta.errors[0].stage is ErrorStage.VALIDATE


def test_hostile_default_remains_a_defaults_failure_not_a_projection_failure() -> None:
    operator = BrokenDefaultProbe()
    output, output_attributes, meta = operator.run([[]], {})
    assert output == [[]]
    assert output_attributes == {}
    assert meta.errors[0].category is ErrorCategory.FAILED
    assert meta.errors[0].code is ErrorCode.DEFAULTS_FAILED
    assert meta.errors[0].stage is ErrorStage.DEFAULTS


@pytest.mark.parametrize(
    ("operator", "attributes"),
    [
        (
            SelectOperator(),
            {"operand_key": "value", "operand": "eq", "operand_val": 1},
        ),
        (NL2LLMOperator(), {"query": ""}),
        (
            DataDiscoverOperator(),
            {"search_query": "jobs", "approximate": True},
        ),
        (PlanDiscoverOperator(), {}),
    ],
)
def test_legal_metadata_edits_do_not_change_raw_or_canonical_results(
    operator: Operator,
    attributes: dict[str, Any],
) -> None:
    raw_before = operator.apply(DATA, attributes)
    normalized_before = operator.run(DATA, attributes)
    first_name = next(iter(operator.get_attributes()), None)
    if first_name is not None:
        operator.set_attribute_description(first_name, "updated documentation")
    raw_after = operator.apply(DATA, attributes)
    normalized_after = operator.run(DATA, attributes)
    assert raw_after == raw_before
    assert normalized_after == normalized_before
