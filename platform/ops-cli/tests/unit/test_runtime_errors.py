from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from blue_data_ops.llm.errors import LLMError
from blue_data_ops.operators import Operator, OperatorRegistry
from blue_data_ops.operators import operator as operator_module
from blue_data_ops.operators.types import Attributes, DataBundle, ErrorRecord, Properties
from click.testing import CliRunner

from blue_data_ops_cli import config
from blue_data_ops_cli.commands import cli

_execution_error = cast(
    Callable[[str, Exception], ErrorRecord], getattr(operator_module, "_execution_error")
)


@pytest.mark.parametrize(
    "code",
    [
        "reserved_field",
        "sql_policy_invalid",
        "sql_execution_unavailable",
        "sql_target_denied",
        "sql_query_rejected",
        "sql_execution_failed",
    ],
)
def test_owned_llm_failure_remains_fixed_in_cli_json_and_stderr(
    code: str,
    install_catalog: Callable[[OperatorRegistry | Exception], object],
    runner: CliRunner,
    tmp_path: Path,
) -> None:
    class Failure(Operator):
        name = "failure"

        def apply(
            self,
            input_data: DataBundle,
            attributes: Attributes,
            properties: Properties | None = None,
        ) -> DataBundle:
            raise LLMError("synthetic backend detail", code=code)

    registry = OperatorRegistry()
    registry.register(Failure(), "2.0.0")
    install_catalog(registry)
    path = tmp_path / "input.json"
    path.write_text("[[]]")
    result = runner.invoke(
        cli, ["operator", "run", "failure@2.0.0", "--input-file", str(path), "--format", "json"]
    )
    assert result.exit_code == config.EXIT_EXECUTION
    document = json.loads(result.stdout)
    expected = _execution_error("failure@2.0.0", LLMError("untrusted", code=code))
    assert document["error"]["detail"]["suggestion"] == expected.suggestion
    assert expected.message in document["error"]["message"]
    assert expected.message in result.stderr
    assert "synthetic backend detail" not in result.output
