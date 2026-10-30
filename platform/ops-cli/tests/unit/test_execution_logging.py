from __future__ import annotations

import io
import logging
from typing import ClassVar

import pytest
from blue_data_ops.operators import Attributes, DataBundle, Operator, Properties

from blue_data_ops_cli import config


def test_execution_logs_use_only_masked_stderr_when_requested(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    canary = "CANARY_PRIVATE_REGISTRY_CONTEXT"
    monkeypatch.setenv("OPENAI_API_KEY", canary)
    root = logging.getLogger()
    child = logging.getLogger("blue_data_ops.execution_logging_test")
    raw_stream = io.StringIO()
    previous_root = [logging.StreamHandler(raw_stream)]
    previous_child = [logging.StreamHandler(raw_stream)]
    previous_fallback = logging.StreamHandler(raw_stream)
    monkeypatch.setattr(root, "handlers", previous_root)
    monkeypatch.setattr(root, "level", logging.WARNING)
    monkeypatch.setattr(child, "handlers", previous_child)
    monkeypatch.setattr(child, "propagate", False)
    monkeypatch.setattr(child, "level", logging.WARNING)
    monkeypatch.setattr(logging, "lastResort", previous_fallback)
    for enabled in (False, True):
        with config.execution_logging(config.Reporter("json", log=enabled, log_limit=5000)):
            root.error("root rejected %s", canary)
            try:
                raise RuntimeError(canary)
            except RuntimeError:
                child.exception("library operation failed")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert canary not in captured.err
        assert raw_stream.getvalue() == ""
        if enabled:
            assert "***" in captured.err
            assert "Traceback" in captured.err
        else:
            assert captured.err == ""
        assert root.handlers is previous_root
        assert child.handlers is previous_child
        assert child.propagate is False
        assert root.level == child.level == logging.WARNING
        assert logging.lastResort is previous_fallback


def test_execution_logging_restores_handlers_after_an_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = logging.getLogger()
    child = logging.getLogger("blue_data_ops.execution_logging_failure_test")
    previous_root = [logging.NullHandler()]
    previous_child = [logging.NullHandler()]
    previous_fallback = logging.NullHandler()
    monkeypatch.setattr(root, "handlers", previous_root)
    monkeypatch.setattr(child, "handlers", previous_child)
    monkeypatch.setattr(child, "propagate", False)
    monkeypatch.setattr(logging, "lastResort", previous_fallback)
    with pytest.raises(RuntimeError, match="execution failed"):
        with config.execution_logging(config.Reporter("json")):
            raise RuntimeError("execution failed")
    assert root.handlers is previous_root
    assert child.handlers is previous_child
    assert child.propagate is False
    assert logging.lastResort is previous_fallback


def test_broken_log_output_preserves_operator_results_and_logging_state(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    canary = "CANARY_PRIVATE_REGISTRY_CONTEXT"
    root = logging.getLogger()
    child = logging.getLogger("blue_data_ops.execution_logging_broken_output_test")
    raw_stream = io.StringIO()
    previous_root = [logging.StreamHandler(raw_stream)]
    previous_child = [logging.StreamHandler(raw_stream)]
    previous_fallback = logging.StreamHandler(raw_stream)
    monkeypatch.setattr(root, "handlers", previous_root)
    monkeypatch.setattr(child, "handlers", previous_child)
    monkeypatch.setattr(child, "propagate", False)
    monkeypatch.setattr(child, "level", logging.WARNING)
    monkeypatch.setattr(logging, "lastResort", previous_fallback)

    class UnformattableDiagnostic:
        def __str__(self) -> str:
            raise ValueError(canary)

    class LoggingOperator(Operator):
        name: ClassVar[str] = "logging_output_test"

        def apply(
            self,
            input_data: DataBundle,
            attributes: Attributes,
            properties: Properties | None = None,
        ) -> DataBundle:
            del properties
            try:
                raise RuntimeError(canary)
            except RuntimeError:
                diagnostic = UnformattableDiagnostic() if attributes["unformattable"] else canary
                child.exception("library diagnostic: %s", diagnostic)
            return input_data

    for error_type in (BrokenPipeError, RuntimeError):
        for unformattable in (False, True):
            reporter = config.Reporter("json", log=True)

            def fail_write(_text: str) -> None:
                raise error_type(canary)

            monkeypatch.setattr(reporter, "line", fail_write)
            with config.execution_logging(reporter):
                output, _, meta = LoggingOperator().run(
                    [[{"value": 1}]], {"unformattable": unformattable}
                )
            assert output == [[{"value": 1}]]
            assert meta.errors == []
            captured = capsys.readouterr()
            assert captured.out == captured.err == ""
            assert raw_stream.getvalue() == ""
            assert root.handlers is previous_root
            assert child.handlers is previous_child
            assert child.propagate is False
            assert logging.lastResort is previous_fallback
