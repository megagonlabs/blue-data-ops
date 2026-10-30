from __future__ import annotations

import logging
from typing import Any

import pytest

import blue_data_ops.operators.operator as operator_module
import blue_data_ops.utils.type_utils as type_module

CANARY = "CANARY_PRIVATE_REGISTRY_CONTEXT"


def _assert_safe_logs(caplog: pytest.LogCaptureFixture) -> None:
    assert caplog.records
    assert CANARY not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    assert all(record.levelno == logging.DEBUG for record in caplog.records)


def test_attribute_validation_failure_logs_omit_names_and_exception_data(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    def fail_type(_value: Any, _expected_type: str) -> bool:
        raise RuntimeError(CANARY)

    monkeypatch.setattr(operator_module, "validate_parameter_type", fail_type)
    for mode, expected in (("log", False), ("skip", True), ("other", True)):
        properties = {
            "attributes": {CANARY: {"type": "int"}},
            "validation_error_handling": mode,
        }
        caplog.clear()
        assert operator_module.default_attributes_validator({CANARY: 1}, properties) is expected
        if mode != "log":
            _assert_safe_logs(caplog)


def test_type_validation_logs_omit_specifications_and_exception_data(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    for error_type in (ValueError, RuntimeError):

        def fail_parser(_specification: Any) -> Any:
            raise error_type(CANARY)

        monkeypatch.setattr(type_module, "string_to_python_type", fail_parser)
        caplog.clear()
        if error_type is ValueError:
            assert type_module.validate_parameter_type(1, CANARY) is False
        else:
            with pytest.raises(RuntimeError, match="Parameter type validation system error"):
                type_module.validate_parameter_type(1, CANARY)
        _assert_safe_logs(caplog)
