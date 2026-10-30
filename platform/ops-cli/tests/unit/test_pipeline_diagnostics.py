from __future__ import annotations

import json
from pathlib import Path

import pytest
from blue_data_ops.operators import versioned_registry
from blue_data_ops.plan import DataPipeline, PipelineExecutor
from click.testing import CliRunner

from blue_data_ops_cli.commands import cli


def plan() -> DataPipeline:
    value = DataPipeline(id="diagnostic")
    entry = value.define_input("input")
    step = value.define_operator(
        "select@2.0.0",
        label="step",
        attributes={"operand_key": "id", "operand": "??", "operand_val": 1},
    )
    out = value.define_output("output")
    value.set_plan_input(entry)
    value.set_plan_output(out)
    value.connect_nodes(entry, step)
    value.connect_nodes(step, out)
    return value


@pytest.mark.parametrize("format_name", ["json", "table", "nl"])
@pytest.mark.parametrize("with_log", [False, True])
def test_stopped_recoverable_node_has_summary(
    tmp_path: Path,
    format_name: str,
    with_log: bool,
) -> None:
    run = PipelineExecutor(versioned_registry()).execute(plan(), [[{"id": 1}]])
    expected = run.node_runs[0].exec_meta.errors[0]
    assert expected.category == "RECOVERABLE"
    pipeline_file = tmp_path / "plan.json"
    pipeline_file.write_text(json.dumps(plan().to_dict()))
    input_file = tmp_path / "input.json"
    input_file.write_text('[[{"id": 1}]]')
    runner = CliRunner()
    imported = runner.invoke(
        cli,
        [
            "pipeline",
            "import",
            "diagnostic",
            "--pipeline-file",
            str(pipeline_file),
            "--format",
            "json",
        ],
    )
    assert imported.exit_code == 0, imported.output
    args = [
        "pipeline",
        "run",
        "diagnostic",
        "--input-file",
        str(input_file),
        "--format",
        format_name,
    ]
    if with_log:
        args.append("--log")
    result = runner.invoke(cli, args)
    assert result.exit_code == 8, result.output
    assert "without an error record" not in result.output
    assert expected.message in result.output
    if format_name == "json":
        document = json.loads(result.stdout)
        assert expected.message in document["error"]["message"]
        assert document["error"]["detail"]["suggestion"] == expected.suggestion
