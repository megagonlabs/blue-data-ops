from __future__ import annotations

import importlib
import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from blue_data_ops.data import RegistrySeam
from blue_data_ops.llm import LLMClient, LLMError
from blue_data_ops.operators import versioned_registry
from blue_data_ops.plan import DataPipeline
from click.testing import CliRunner

from blue_data_ops_cli import config
from blue_data_ops_cli.commands import cli

PROVIDER = "SYNTHETIC_PRIVATE_BN_SUMMARY_PROVIDER"
SOURCE = "SYNTHETIC_PRIVATE_BN_SUMMARY_SOURCE"
INPUT = "SYNTHETIC_PRIVATE_BN_SUMMARY_INPUT"


class Client(LLMClient):
    def __init__(self, code: str, malformed: bool) -> None:
        self.code = code
        self.malformed = malformed
        self.calls = 0
        self.feedback: list[dict[str, Any]] = []

    def execute_api_call(
        self,
        input: Any,
        properties: dict[str, Any] | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> Any:
        self.calls += 1
        if additional_data is not None:
            self.feedback.append(additional_data)
        if self.malformed and self.calls > 1:
            return {"target_state": "yes"}
        raise LLMError(PROVIDER, code=self.code, provider_error=PROVIDER, retryable=False)


@pytest.mark.parametrize("version", ["1.0.0", "2.0.0", "3.0.0"])
@pytest.mark.parametrize("format_name", ["json", "table", "nl"])
@pytest.mark.parametrize("with_log", [False, True])
@pytest.mark.parametrize("kind", ["credentials", "settings", "reply"])
def test_bn_pipeline_summary_and_stderr_exclude_private_backend_details(
    version: str,
    format_name: str,
    with_log: bool,
    kind: str,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    catalog = versioned_registry()
    memory = importlib.import_module("blue_data.source.json.memory_json_source").MemoryJSONSource
    registry_class = importlib.import_module("blue_data.registry.data_registry").DataRegistry
    registry = registry_class(store=memory(), rebuild=False)
    registry.register_source(memory(SOURCE))
    seam = RegistrySeam(registry)
    client = Client(
        "unsupported_parameter" if kind == "settings" else "provider_credentials", kind == "reply"
    )
    message = {
        "credentials": "model provider rejected its credentials",
        "settings": "model rejected a requested generation setting",
        "reply": "model reply did not match the operator's output format",
    }[kind]
    attrs = {
        "source": SOURCE,
        "database": "db",
        "collection": "public",
        "protocol_variant": "pgmpy",
        "question": "synthetic",
        "schema": "synthetic schema",
        "max_corrections": 2 if kind == "reply" else 0,
    }
    plan = DataPipeline(id="bn-summary")
    entry = plan.define_input("input")
    step = plan.define_operator("nl2bn@" + version, label="step", attributes=attrs)
    output = plan.define_output("output")
    plan.set_plan_input(entry)
    plan.set_plan_output(output)
    plan.connect_nodes(entry, step)
    plan.connect_nodes(step, output)
    (tmp_path / "plan.json").write_text(json.dumps(plan.to_dict()))
    (tmp_path / "input.json").write_text(json.dumps([[{"private": INPUT}]]))
    runner = CliRunner()
    caplog.set_level(logging.DEBUG)
    caplog.clear()
    with (
        patch.object(config, "build_catalog", return_value=catalog),
        patch.object(config, "build_registry_seam", return_value=seam),
        patch.object(LLMClient, "execute_api_call", client.execute_api_call),
    ):
        imported = runner.invoke(
            cli,
            [
                "pipeline",
                "import",
                "bn-summary",
                "--pipeline-file",
                str(tmp_path / "plan.json"),
                "--format",
                "json",
            ],
        )
        assert imported.exit_code == 0
        args = [
            "pipeline",
            "run",
            "bn-summary",
            "--input-file",
            str(tmp_path / "input.json"),
            "--format",
            format_name,
        ]
        if with_log:
            args.append("--log")
        result = runner.invoke(cli, args)
    assert result.exit_code == 8
    assert message in result.output
    assert client.calls == (3 if kind == "reply" else 1)
    for marker in (PROVIDER, SOURCE, INPUT):
        assert marker not in result.stdout + result.stderr
        assert marker not in caplog.text
        assert marker not in json.dumps(client.feedback)
