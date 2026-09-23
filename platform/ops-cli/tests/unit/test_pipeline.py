"""Storing a pipeline, reading it back, and running it without disturbing what is stored.

The rule this file exists for is the last one. `PipelineExecutor.execute()` records what
happened on the plan it is handed: after a run the nodes hold the records that passed
through them. Writing that back would put a caller's data into the CLI's home and leave a
stored plan the executor refuses to start again, so the store is hashed either side of a run.

Nothing here reaches a provider. The one command that could is given a client that returns a
prepared response, and the request carries no credential of any kind.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from blue_data_ops.operators import OperatorRegistry
from blue_data_ops.plan import DataPipeline
from click.testing import CliRunner

from blue_data_ops_cli import config, configstore, pipeline
from blue_data_ops_cli.commands import cli

MARKER = configstore._CLAIM_MARKER  # pyright: ignore[reportPrivateUsage]
"""What a claimed entry carries to say it is one. Named here so the tests read the same
record the store writes rather than a copy of it that can drift."""

ORDERS: list[list[dict[str, Any]]] = [[{"total": 120.0}, {"total": 215.0}, {"total": 50.0}]]

REQUEST: dict[str, Any] = {
    "goal": "average total of orders above 100",
    "discovery_queries": [
        {"text": "filter", "tags": ["capability-filter"]},
        {"text": "average", "tags": ["capability-average"]},
    ],
    "operator_attributes": {
        "select": {"operand_key": "total", "operand": ">", "operand_val": 100},
        "avg": {"avg_key": "total", "output_key": "average_total"},
    },
}


def written(path: Path, payload: Any) -> str:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def body(output: str) -> dict[str, Any]:
    return json.loads(output)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def request_file(tmp_path: Path) -> str:
    return written(tmp_path / "request.json", REQUEST)


@pytest.fixture
def orders_file(tmp_path: Path) -> str:
    return written(tmp_path / "orders.json", ORDERS)


@pytest.fixture
def stored(runner: CliRunner, request_file: str, cli_home: Path) -> Path:
    """One planned pipeline named `nightly`, and the path its record lives at."""
    result = runner.invoke(cli, ["pipeline", "add", "nightly", "--request-file", request_file])
    assert result.exit_code == 0, result.output
    return cli_home / "default" / "pipeline" / "nightly" / "pipeline.json"


# ------------------------------------------------------------------- add --
def test_add_plans_a_pipeline_and_stores_it(runner: CliRunner, stored: Path) -> None:
    assert stored.is_file()
    record = json.loads(stored.read_text(encoding="utf-8"))
    assert record["type"] == "DATA_PIPELINE"
    assert len(record["nodes"]) == 4


def test_add_records_where_the_pipeline_came_from(runner: CliRunner, stored: Path) -> None:
    provenance = json.loads((stored.parent / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["origin"] == "plan"
    assert provenance["planner"] == "rule"
    assert provenance["catalog"] == "active"
    assert provenance["goal"] == REQUEST["goal"]


def test_the_stored_files_are_readable_only_by_their_owner(stored: Path) -> None:
    assert stat.S_IMODE(stored.stat().st_mode) == 0o600
    assert stat.S_IMODE(stored.parent.stat().st_mode) == 0o700


def test_the_goal_option_replaces_the_one_in_the_file(
    runner: CliRunner, request_file: str, cli_home: Path
) -> None:
    result = runner.invoke(
        cli,
        [
            "pipeline",
            "add",
            "nightly",
            "--request-file",
            request_file,
            "--goal",
            "average total of orders above 200",
        ],
    )
    assert result.exit_code == 0, result.output
    provenance = json.loads(
        (cli_home / "default" / "pipeline" / "nightly" / "provenance.json").read_text("utf-8")
    )
    assert provenance["goal"] == "average total of orders above 200"


def test_replacing_a_stored_pipeline_asks_first(
    runner: CliRunner, stored: Path, request_file: str
) -> None:
    before = digest(stored)
    result = runner.invoke(cli, ["pipeline", "add", "nightly", "--request-file", request_file])
    assert result.exit_code == config.EXIT_USAGE
    assert "--confirm" in result.stderr
    assert digest(stored) == before


def test_declining_the_replacement_leaves_the_stored_one_alone(
    runner: CliRunner, stored: Path, request_file: str
) -> None:
    before = digest(stored)
    result = runner.invoke(
        cli, ["pipeline", "add", "nightly", "--request-file", request_file], input="n\n"
    )
    assert result.exit_code == 0, result.output
    assert digest(stored) == before


def test_a_request_field_a_planning_request_does_not_have_is_refused(
    runner: CliRunner, tmp_path: Path
) -> None:
    """A misspelled bound that is quietly ignored plans against a limit nobody set."""
    path = written(tmp_path / "request.json", {**REQUEST, "max_step": 4})
    result = runner.invoke(cli, ["pipeline", "add", "nightly", "--request-file", path])
    assert result.exit_code == config.EXIT_REQUEST
    assert "max_step" in result.stderr


@pytest.mark.parametrize("name", ["../escape", ".", "..", ".hidden", ".removing-0123456789ab"])
def test_a_name_that_would_escape_or_shadow_the_store_is_refused(
    name: str, runner: CliRunner, request_file: str
) -> None:
    """A pipeline name is a directory name, and the store keeps its own entries under names
    starting with a dot — an interrupted removal leaves one, and it is cleared on sight."""
    result = runner.invoke(cli, ["pipeline", "add", name, "--request-file", request_file])
    assert result.exit_code == config.EXIT_USAGE


# --------------------------------------------------------------- planners --
def test_the_rule_planner_has_no_snapshot_to_disclose(runner: CliRunner, request_file: str) -> None:
    result = runner.invoke(
        cli, ["pipeline", "add", "nightly", "--request-file", request_file, "--send-data-context"]
    )
    assert result.exit_code == config.EXIT_USAGE
    assert "--planner openai" in result.stderr


def test_the_provider_planner_needs_the_requests_own_allowlist(
    runner: CliRunner, request_file: str
) -> None:
    """The allowlist is an authorization boundary, so the CLI does not supply one."""
    result = runner.invoke(
        cli,
        ["pipeline", "add", "nightly", "--request-file", request_file, "--planner", "openai"],
    )
    assert result.exit_code == config.EXIT_REQUEST
    assert "allowed_operator_ids" in result.stderr


def fake_client(payload: dict[str, Any]) -> Any:
    """The narrow surface the library's adapter touches, and a log of what it was sent."""

    class Client:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def with_options(self, **kwargs: Any) -> Any:
            return self

        @property
        def responses(self) -> Any:
            return self

        def create(self, **kwargs: Any) -> Any:
            self.calls.append(kwargs)
            part = SimpleNamespace(type="output_text", text=json.dumps(payload))
            return SimpleNamespace(status="completed", output=[SimpleNamespace(content=[part])])

    return Client()


def test_the_provider_planner_runs_against_an_injected_client(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cli_home: Path
) -> None:
    """No network and no credential: the client is handed in and returns a fixed plan."""
    candidate: dict[str, Any] = {
        "candidates": [
            {
                "label": "orders-plan",
                "steps": [
                    {
                        "step_id": "filter",
                        "operator_id": "select@2.0.0",
                        "attributes_json": json.dumps(REQUEST["operator_attributes"]["select"]),
                        "depends_on": [],
                        "label": "filter",
                    },
                    {
                        "step_id": "average",
                        "operator_id": "avg@3.0.0",
                        "attributes_json": json.dumps(REQUEST["operator_attributes"]["avg"]),
                        "depends_on": ["filter"],
                        "label": "average",
                    },
                ],
            }
        ]
    }
    client = fake_client(candidate)
    monkeypatch.setattr(pipeline, "build_openai_client", lambda: client)
    path = written(
        tmp_path / "request.json",
        {**REQUEST, "allowed_operator_ids": ["select@2.0.0", "avg@3.0.0"]},
    )
    result = runner.invoke(
        cli,
        [
            "pipeline",
            "add",
            "planned",
            "--request-file",
            path,
            "--planner",
            "openai",
            "--model",
            "gpt-4o",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert body(result.stdout)["planning"]["operator_ids"] == ["select@2.0.0", "avg@3.0.0"]
    assert (cli_home / "default" / "pipeline" / "planned" / "pipeline.json").is_file()
    assert len(client.calls) == 1
    assert client.calls[0]["model"] == "gpt-4o"
    assert "OPENAI_API_KEY" not in json.dumps(client.calls[0])


def test_a_planner_name_the_cli_does_not_have_names_the_parameter(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["pipeline", "list"], env={"BLUE_DATA_OPS_PLANNER": "guesswork"})
    assert result.exit_code == 0, "an unused planner setting blocks nothing"


# ---------------------------------------------------------------- import --
def test_import_preflights_and_stores(runner: CliRunner, stored: Path, tmp_path: Path) -> None:
    exported = tmp_path / "nightly.json"
    exported.write_text(stored.read_text(encoding="utf-8"), encoding="utf-8")
    result = runner.invoke(
        cli, ["pipeline", "import", "copy", "--pipeline-file", str(exported), "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    assert body(result.stdout)["preflight"]["operator_ids"] == ["select@2.0.0", "avg@3.0.0"]


def test_a_document_that_is_not_a_pipeline_is_a_request_error(
    runner: CliRunner, tmp_path: Path
) -> None:
    path = written(tmp_path / "not.json", {"nodes": {}})
    result = runner.invoke(cli, ["pipeline", "import", "copy", "--pipeline-file", path])
    assert result.exit_code == config.EXIT_REQUEST
    assert "not a serialized pipeline" in result.stderr


def test_a_graph_the_executor_cannot_run_is_refused_at_import(
    runner: CliRunner, tmp_path: Path
) -> None:
    path = written(tmp_path / "empty.json", {"id": "x", "type": "DATA_PIPELINE", "nodes": {}})
    result = runner.invoke(cli, ["pipeline", "import", "copy", "--pipeline-file", path])
    assert result.exit_code == config.EXIT_REQUEST
    assert "PipelineError" in result.stderr


# ---------------------------------------------------------------- export --
def test_export_emits_the_stored_record(runner: CliRunner, stored: Path) -> None:
    result = runner.invoke(cli, ["pipeline", "export", "nightly"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == json.loads(stored.read_text(encoding="utf-8"))


def test_export_writes_a_file_and_asks_before_replacing_one(
    runner: CliRunner, stored: Path, tmp_path: Path
) -> None:
    target = tmp_path / "out.json"
    assert (
        runner.invoke(
            cli, ["pipeline", "export", "nightly", "--output-file", str(target)]
        ).exit_code
        == 0
    )
    assert json.loads(target.read_text(encoding="utf-8"))["type"] == "DATA_PIPELINE"
    again = runner.invoke(cli, ["pipeline", "export", "nightly", "--output-file", str(target)])
    assert again.exit_code == config.EXIT_USAGE


def test_export_has_no_format_option() -> None:
    import click

    group = cli.commands["pipeline"]
    assert isinstance(group, click.Group)
    export = group.commands["export"]
    assert not any("--format" in parameter.opts for parameter in export.params)


# ------------------------------------------------------- list and inspect --
def test_list_reports_the_stored_pipelines_of_this_profile(runner: CliRunner, stored: Path) -> None:
    result = runner.invoke(cli, ["pipeline", "list", "--format", "json"])
    assert result.exit_code == 0, result.output
    found = body(result.stdout)
    assert found["count"] == 1
    assert found["pipelines"][0]["name"] == "nightly"
    assert found["pipelines"][0]["origin"] == "plan"
    assert found["profile"] == "default"


def test_list_is_empty_and_says_what_to_run(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["pipeline", "list"])
    assert result.exit_code == 0, result.output
    assert "pipeline add" in result.stdout


def test_inspect_reports_the_nodes_in_the_order_they_would_run(
    runner: CliRunner, stored: Path
) -> None:
    result = runner.invoke(cli, ["pipeline", "inspect", "nightly", "--format", "json"])
    assert result.exit_code == 0, result.output
    found = body(result.stdout)
    assert found["preflight"]["operator_ids"] == ["select@2.0.0", "avg@3.0.0"]
    assert [node["type"] for node in found["pipeline"]["nodes"]] == [
        "INPUT",
        "OPERATOR",
        "OPERATOR",
        "OUTPUT",
    ]
    assert found["provenance"]["origin"] == "plan"


def test_a_name_that_is_not_stored_names_the_command_that_lists_them(
    runner: CliRunner,
) -> None:
    result = runner.invoke(cli, ["pipeline", "inspect", "missing"])
    assert result.exit_code == config.EXIT_REQUEST
    assert "pipeline list" in result.stderr


# ---------------------------------------------------------------- remove --
def test_remove_deletes_one_pipeline_and_nothing_beside_it(
    runner: CliRunner, stored: Path, request_file: str
) -> None:
    assert (
        runner.invoke(cli, ["pipeline", "add", "other", "--request-file", request_file]).exit_code
        == 0
    )
    assert runner.invoke(cli, ["pipeline", "remove", "nightly", "--confirm"]).exit_code == 0
    assert not stored.parent.exists()
    assert (stored.parent.parent / "other" / "pipeline.json").is_file()


def test_remove_asks_first_and_refuses_when_there_is_nobody_to_ask(
    runner: CliRunner, stored: Path
) -> None:
    result = runner.invoke(cli, ["pipeline", "remove", "nightly"])
    assert result.exit_code == config.EXIT_USAGE
    assert "--confirm" in result.stderr
    assert stored.is_file()


def test_declining_the_removal_is_not_a_failure(runner: CliRunner, stored: Path) -> None:
    result = runner.invoke(cli, ["pipeline", "remove", "nightly"], input="n\n")
    assert result.exit_code == 0, result.output
    assert stored.is_file()


# ------------------------------------------------------------------- run --
def test_run_executes_the_stored_pipeline(
    runner: CliRunner, stored: Path, orders_file: str
) -> None:
    result = runner.invoke(
        cli, ["pipeline", "run", "nightly", "--input-file", orders_file, "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    found = body(result.stdout)
    assert found["result"]["output_data"] == [[{"average_total": 167.5}]]
    assert found["succeeded"] is True
    assert found["failed_node_id"] is None
    assert [node["operator_id"] for node in found["node_runs"]] == ["select@2.0.0", "avg@3.0.0"]


def test_a_run_never_writes_to_the_store(runner: CliRunner, stored: Path, orders_file: str) -> None:
    """Execution writes each node's value and status onto the plan it is handed. The copy
    that runs is in memory; a run that wrote it back would persist the caller's records."""
    before = digest(stored)
    assert (
        runner.invoke(cli, ["pipeline", "run", "nightly", "--input-file", orders_file]).exit_code
        == 0
    )
    assert digest(stored) == before
    assert "120.0" not in stored.read_text(encoding="utf-8")


def test_the_same_pipeline_runs_twice(runner: CliRunner, stored: Path, orders_file: str) -> None:
    """A node that has already started cannot start again, so a run that wrote its statuses
    back would leave a stored pipeline that runs exactly once."""
    for _ in range(2):
        result = runner.invoke(
            cli, ["pipeline", "run", "nightly", "--input-file", orders_file, "--format", "json"]
        )
        assert result.exit_code == 0, result.output
        assert body(result.stdout)["result"]["output_data"] == [[{"average_total": 167.5}]]


@pytest.fixture
def failing(runner: CliRunner, tmp_path: Path, install_catalog: Any, cli_home: Path) -> Path:
    """A stored two-step graph whose second step always fails, over doubles.

    Hand-built rather than planned: the shipped rule produces a graph that works, and what
    has to be exercised here is a node that does not.
    """
    from test_operator import Broken, Echo

    registry = OperatorRegistry()
    registry.register(Echo(), "1.0.0", ("domain-text", "accepts-data", "produces-data"))
    registry.register(Broken(), "1.0.0", ("domain-text", "accepts-data", "produces-data"))
    install_catalog(registry)

    plan = DataPipeline(label="failing")
    entry = plan.define_input(label="input")
    first = plan.define_operator("echo@1.0.0", label="echo")
    second = plan.define_operator("broken@1.0.0", label="broken")
    leaving = plan.define_output(label="output")
    entry.connect_to(first)
    first.connect_to(second)
    second.connect_to(leaving)
    plan.set_plan_input(entry)
    plan.set_plan_output(leaving)

    path = written(tmp_path / "failing.json", plan.to_dict())
    result = runner.invoke(cli, ["pipeline", "import", "failing", "--pipeline-file", path])
    assert result.exit_code == 0, result.output
    return cli_home / "default" / "pipeline" / "failing" / "pipeline.json"


def test_a_failing_node_exits_execution_and_still_reports_what_ran(
    runner: CliRunner, failing: Path, orders_file: str
) -> None:
    """Partial success: the exit code reflects the failure and the work that did happen is
    still visible, on standard error and in the failure's own detail."""
    result = runner.invoke(
        cli, ["pipeline", "run", "failing", "--input-file", orders_file, "--format", "json"]
    )
    assert result.exit_code == config.EXIT_EXECUTION
    error = body(result.stdout)["error"]
    assert error["code"] == "EXECUTION"
    assert error["detail"]["failed_node_id"]
    assert [node["status"] for node in error["detail"]["node_runs"]] == ["EXECUTED", "FAILED"]
    assert "EXECUTED" in result.stderr


def test_a_failed_run_leaves_the_store_untouched(
    runner: CliRunner, failing: Path, orders_file: str
) -> None:
    before = digest(failing)
    assert (
        runner.invoke(cli, ["pipeline", "run", "failing", "--input-file", orders_file]).exit_code
        == config.EXIT_EXECUTION
    )
    assert digest(failing) == before


def test_run_reads_the_bundle_from_standard_input(runner: CliRunner, stored: Path) -> None:
    result = runner.invoke(
        cli,
        ["pipeline", "run", "nightly", "--input-file", "-", "--format", "json"],
        input=json.dumps(ORDERS),
    )
    assert result.exit_code == 0, result.output
    assert body(result.stdout)["result"]["output_data"] == [[{"average_total": 167.5}]]


def test_run_reports_the_settings_it_applied(
    runner: CliRunner, stored: Path, orders_file: str
) -> None:
    result = runner.invoke(
        cli,
        [
            "pipeline",
            "run",
            "nightly",
            "--input-file",
            orders_file,
            "--model",
            "gpt-5-mini",
            "--reasoning-effort",
            "medium",
            "--format",
            "json",
        ],
    )
    settings = body(result.stdout)["settings"]
    assert settings["scope"] == "invocation_defaults"
    assert settings["source"]["openai.model"] == "flag"
    assert settings["applied"]["openai.model"] == "gpt-5-mini"
    assert settings["source"]["llm.reasoning_effort"] == "flag"
    assert settings["applied"]["llm.reasoning_effort"] == "medium"

    human = runner.invoke(
        cli,
        [
            "pipeline",
            "run",
            "nightly",
            "--input-file",
            orders_file,
            "--model",
            "gpt-5-mini",
            "--reasoning-effort",
            "medium",
        ],
    )
    assert human.exit_code == 0, human.output
    assert "invocation defaults:" in human.stdout
    assert "openai.model=gpt-5-mini (flag)" in human.stdout
    assert "llm.reasoning_effort=medium (flag)" in human.stdout
    assert "settings:" not in human.stdout


def test_pipelines_belong_to_the_profile_that_stored_them(runner: CliRunner, stored: Path) -> None:
    assert runner.invoke(cli, ["profile", "add", "staging"]).exit_code == 0
    result = runner.invoke(cli, ["--profile", "staging", "pipeline", "list", "--format", "json"])
    assert body(result.stdout)["count"] == 0


# ------------------------------------------------------------ the boundary --
# `<profile>/pipeline` is a directory this CLI creates, and a link in its place sends every
# file below it somewhere the package promises nothing about. The link is above the paths the
# store handles, so a check on the last component of each of them sees nothing wrong.


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    """A writable directory that is not under the CLI home."""
    target = tmp_path / "outside"
    target.mkdir()
    return target


def _link_the_component(cli_home: Path, outside: Path, profile: str = "default") -> None:
    (cli_home / profile).mkdir(parents=True, exist_ok=True)
    (cli_home / profile / "pipeline").symlink_to(outside)


def test_add_refuses_a_component_directory_that_links_out_of_the_home(
    runner: CliRunner, request_file: str, cli_home: Path, outside: Path
) -> None:
    _link_the_component(cli_home, outside)
    result = runner.invoke(cli, ["pipeline", "add", "nightly", "--request-file", request_file])
    assert result.exit_code == config.EXIT_PROFILE
    assert "outside" in result.stderr
    assert list(outside.iterdir()) == []


def test_import_refuses_a_component_directory_that_links_out_of_the_home(
    runner: CliRunner, stored: Path, cli_home: Path, outside: Path, tmp_path: Path
) -> None:
    exported = tmp_path / "nightly.json"
    exported.write_text(stored.read_text(encoding="utf-8"), encoding="utf-8")
    for entry in (cli_home / "default" / "pipeline").iterdir():
        shutil.rmtree(entry)
    (cli_home / "default" / "pipeline").rmdir()
    (cli_home / "default" / "pipeline").symlink_to(outside)
    result = runner.invoke(cli, ["pipeline", "import", "copy", "--pipeline-file", str(exported)])
    assert result.exit_code == config.EXIT_PROFILE
    assert list(outside.iterdir()) == []


def test_remove_refuses_a_component_directory_that_links_out_of_the_home(
    runner: CliRunner, cli_home: Path, outside: Path
) -> None:
    """The file to delete is real and inside the link; the link is what makes it not ours."""
    (outside / "nightly").mkdir()
    (outside / "nightly" / "pipeline.json").write_text("{}", encoding="utf-8")
    _link_the_component(cli_home, outside)
    result = runner.invoke(cli, ["pipeline", "remove", "nightly", "--confirm"])
    assert result.exit_code == config.EXIT_PROFILE
    assert (outside / "nightly" / "pipeline.json").is_file()


def test_a_stored_pipeline_behind_a_linked_component_is_not_read(
    runner: CliRunner, cli_home: Path, outside: Path
) -> None:
    (outside / "nightly").mkdir()
    (outside / "nightly" / "pipeline.json").write_text("{}", encoding="utf-8")
    _link_the_component(cli_home, outside)
    assert runner.invoke(cli, ["pipeline", "list"]).exit_code == config.EXIT_PROFILE
    assert runner.invoke(cli, ["pipeline", "inspect", "nightly"]).exit_code == config.EXIT_PROFILE
    assert runner.invoke(cli, ["pipeline", "export", "nightly"]).exit_code == config.EXIT_PROFILE


def test_a_link_deeper_than_the_component_is_refused_too(
    runner: CliRunner, request_file: str, cli_home: Path, outside: Path
) -> None:
    """One level further down, to show the walk is not counting directories."""
    (cli_home / "default" / "pipeline").mkdir(parents=True)
    (cli_home / "default" / "pipeline" / "nightly").symlink_to(outside)
    result = runner.invoke(cli, ["pipeline", "add", "nightly", "--request-file", request_file])
    assert result.exit_code == config.EXIT_PROFILE
    assert list(outside.iterdir()) == []


def test_the_profiles_directory_itself_may_not_link_out_either(
    runner: CliRunner, request_file: str, cli_home: Path, outside: Path
) -> None:
    """The outermost directory the store owns, two levels above the files it writes."""
    cli_home.mkdir(parents=True, exist_ok=True)
    (cli_home / "default").symlink_to(outside)
    result = runner.invoke(cli, ["pipeline", "add", "nightly", "--request-file", request_file])
    assert result.exit_code == config.EXIT_PROFILE
    assert list(outside.iterdir()) == []


def test_removing_a_stored_pipeline_that_is_itself_a_link_is_refused(
    runner: CliRunner, cli_home: Path
) -> None:
    """Following it would empty the directory it points at and leave the link standing."""
    shared = cli_home / "shared"
    shared.mkdir(parents=True)
    (shared / "pipeline.json").write_text("{}", encoding="utf-8")
    (cli_home / "default" / "pipeline").mkdir(parents=True)
    (cli_home / "default" / "pipeline" / "nightly").symlink_to(shared)

    result = runner.invoke(cli, ["pipeline", "remove", "nightly", "--confirm"])

    assert result.exit_code == config.EXIT_PROFILE
    assert "symlink" in result.stderr
    assert (shared / "pipeline.json").is_file()


def test_a_component_directory_linked_within_the_home_is_fine(
    runner: CliRunner, request_file: str, cli_home: Path
) -> None:
    """The rule is the boundary, not the spelling: a link that stays inside is still inside."""
    elsewhere = cli_home / "shared-pipelines"
    elsewhere.mkdir(parents=True)
    (cli_home / "default").mkdir(parents=True, exist_ok=True)
    (cli_home / "default" / "pipeline").symlink_to(elsewhere)
    result = runner.invoke(cli, ["pipeline", "add", "nightly", "--request-file", request_file])
    assert result.exit_code == 0, result.output
    assert (elsewhere / "nightly" / "pipeline.json").is_file()


# ---------------------------------------------- the boundary, under a swap --
# The tests above put the link in place before the command runs. These put it there while
# the command is running, between the moment the store decided the directory was inside the
# home and the moment it uses it — which is where a boundary that works by checking a path
# and then naming it again has nothing to say. The component directory is renamed rather
# than deleted, so a descriptor already holding it still reaches the real files and the test
# can tell which of the two the command read or wrote.


def _swap_the_component(cli_home: Path, outside: Path, profile: str = "default") -> None:
    component = cli_home / profile / "pipeline"
    component.rename(cli_home / profile / "pipeline.moved")
    component.symlink_to(outside)


def test_a_component_swapped_during_a_read_does_not_redirect_it(
    runner: CliRunner,
    stored: Path,
    cli_home: Path,
    outside: Path,
    swap_when_opened: Any,
) -> None:
    """Swap the ancestor between the containment check and the open, and read the real record."""
    (outside / "nightly").mkdir()
    (outside / "nightly" / "pipeline.json").write_text('{"label": "OUTSIDE"}', encoding="utf-8")
    swap_when_opened("pipeline.json", lambda: _swap_the_component(cli_home, outside))

    result = runner.invoke(cli, ["pipeline", "export", "nightly"])

    assert result.exit_code == 0, result.output
    assert "OUTSIDE" not in result.output


@pytest.fixture
def created_outside(creations_under: Any, outside: Path) -> list[str]:
    return cast("list[str]", creations_under(outside))


def test_a_component_swapped_during_a_write_does_not_redirect_it(
    runner: CliRunner,
    request_file: str,
    cli_home: Path,
    outside: Path,
    created_outside: list[str],
    swap_when_opened: Any,
) -> None:
    (cli_home / "default" / "pipeline").mkdir(parents=True)
    (outside / "nightly").mkdir()
    swap_when_opened("pipeline.json", lambda: _swap_the_component(cli_home, outside), creating=True)

    runner.invoke(cli, ["pipeline", "add", "nightly", "--request-file", request_file])

    assert created_outside == []
    assert list((outside / "nightly").iterdir()) == []


# ------------------------------------------ removal, against a moving name --
# rmdir takes a name and there is no call that takes a descriptor instead, so the last step
# of a removal is the one step that cannot be performed on the directory the rest of it
# worked on. The store claims the entry first, with one rename to a private name, and checks
# that name still holds the emptied directory before removing it.


def test_a_directory_that_takes_the_name_during_a_removal_is_not_the_one_deleted(
    runner: CliRunner, stored: Path, cli_home: Path, swap_when_opened: Any
) -> None:
    """The removal deletes the directory it was given, not the name it was given.

    An unrelated directory is moved onto that name while the removal is under way. It is a
    real directory holding real work, and the removal has no business touching it.
    """
    component = cli_home / "default" / "pipeline"
    substitute = component / "replacement"
    substitute.mkdir()
    standing = substitute.stat().st_ino
    asked_for = (component / "nightly").stat().st_ino

    def take_the_name() -> None:
        if (component / "nightly").exists():
            (component / "nightly").rename(component / "nightly.moved")
        substitute.rename(component / "nightly")

    swap_when_opened("pipeline.json", take_the_name)

    result = runner.invoke(cli, ["pipeline", "remove", "nightly", "--confirm"])

    assert result.exit_code == 0, result.output
    left = {entry.stat().st_ino for entry in component.iterdir()}
    assert standing in left, "an unrelated directory was deleted"
    assert asked_for not in left, "the directory that was asked for is still there"


def test_a_directory_swapped_for_the_emptied_one_stops_the_removal(
    runner: CliRunner, stored: Path, cli_home: Path, swap_when_opened: Any
) -> None:
    """The claimed entry is checked against the open directory before it is removed."""
    component = cli_home / "default" / "pipeline"
    substitute = component / "replacement"
    substitute.mkdir()
    standing = substitute.stat().st_ino

    def swap_the_claimed_entry() -> None:
        claimed = next(entry for entry in component.iterdir() if entry.name != "replacement")
        claimed.rename(component / "held")
        substitute.rename(claimed)

    swap_when_opened("pipeline.json", swap_the_claimed_entry)

    result = runner.invoke(cli, ["pipeline", "remove", "nightly", "--confirm"])

    assert result.exit_code == config.EXIT_PROFILE
    assert "replaced while it was being emptied" in result.stderr
    assert standing in {entry.stat().st_ino for entry in component.iterdir()}


def test_no_removal_acts_on_the_entry_the_caller_named(
    runner: CliRunner, stored: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rule itself, rather than one race against it.

    Holding the parent directory open settles which directory an entry is looked up in.
    It does not settle what the entry holds: a name the caller typed is a name another
    directory can be given while this one is being emptied, and rmdir takes a name. So the
    entry is taken first, with one rename, and every call after that works on a name this
    run invented.
    """
    acted_on: list[str] = []
    real: Any = os.rmdir

    def watching(path: Any, *, dir_fd: int | None = None) -> None:
        acted_on.append(str(path))
        real(path, dir_fd=dir_fd)

    monkeypatch.setattr(os, "rmdir", watching)

    result = runner.invoke(cli, ["pipeline", "remove", "nightly", "--confirm"])

    assert result.exit_code == 0, result.output
    assert acted_on, "nothing was removed"
    assert "nightly" not in acted_on


def test_a_removal_that_stops_part_way_is_finished_by_the_next_command(
    runner: CliRunner, stored: Path, cli_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run that dies part way through leaves the directory under a name no command reaches.

    The pipeline is gone as far as `list`, `export` and `run` are concerned, and what is
    left is disk space under an entry nothing will ever ask for, so the next command that
    opens the store clears it instead of listing it or leaving it to pile up.
    """
    component = cli_home / "default" / "pipeline"
    real: Any = os.rmdir

    def stopping(path: Any, *, dir_fd: int | None = None) -> None:
        raise OSError(errno.EIO, "stopped")

    monkeypatch.setattr(os, "rmdir", stopping)
    stopped = runner.invoke(cli, ["pipeline", "remove", "nightly", "--confirm"])
    monkeypatch.setattr(os, "rmdir", real)

    assert stopped.exit_code == config.EXIT_REQUEST
    assert not (component / "nightly").exists()
    left = list(component.iterdir())
    assert left != [], "nothing was left to recover from"
    assert (left[0] / MARKER).is_file(), "the leftover does not say what it is"

    listed = runner.invoke(cli, ["pipeline", "list"])

    assert listed.exit_code == 0, listed.output
    assert "nightly" not in listed.output
    assert list(component.iterdir()) == []


# ------------------------------------- a name this version did not invent --
# The entry a removal stands under is spelled the way a pipeline name used to be allowed to
# be spelled, so the spelling says nothing about who wrote it. What the store sweeps is
# decided by the record it writes inside an entry it has taken, and an entry without that
# record is somebody's pipeline until proven otherwise.

TAKEN = ".removing-deadbeefcafe"
"""A name this store gives its own entries, and one an earlier version let a caller pick."""


def test_a_pipeline_stored_under_a_name_the_store_reserves_survives_a_listing(
    runner: CliRunner, stored: Path, cli_home: Path
) -> None:
    """`list` reads, and reading does not delete a complete stored pipeline.

    A version that allowed a leading dot could store this name, and upgrading does not make
    that directory the store's own bookkeeping. It is listed, shown, exported and removed
    like any other; the only thing it cannot be is the name of a new one.
    """
    component = cli_home / "default" / "pipeline"
    taken = component / TAKEN
    (component / "nightly").rename(taken)
    before = digest(taken / "pipeline.json")

    listed = runner.invoke(cli, ["pipeline", "list"])

    assert listed.exit_code == 0, listed.output
    assert (taken / "pipeline.json").is_file(), "a read deleted a stored pipeline"
    assert digest(taken / "pipeline.json") == before
    assert TAKEN in listed.output
    assert "holds no record" in listed.stderr

    shown = runner.invoke(cli, ["pipeline", "inspect", TAKEN])
    assert shown.exit_code == 0, shown.output
    assert digest(taken / "pipeline.json") == before

    exported = runner.invoke(cli, ["pipeline", "export", TAKEN])
    assert exported.exit_code == 0, exported.output
    assert body(exported.output)["type"] == "DATA_PIPELINE"

    removed = runner.invoke(cli, ["pipeline", "remove", TAKEN, "--confirm"])
    assert removed.exit_code == 0, removed.output
    assert list(component.iterdir()) == []


@pytest.mark.parametrize("name", [".hidden", TAKEN])
def test_a_name_the_store_reserves_cannot_be_given_to_a_new_pipeline(
    name: str, runner: CliRunner, tmp_path: Path
) -> None:
    """Refused where a pipeline is created, which is the only place the rule belongs."""
    path = written(tmp_path / "graph.json", {"type": "DATA_PIPELINE", "nodes": {}})
    result = runner.invoke(cli, ["pipeline", "import", name, "--pipeline-file", path])

    assert result.exit_code == config.EXIT_USAGE
    assert "cannot start with a dot" in result.stderr


@pytest.mark.parametrize(
    "spelling",
    [".removing-0123456789ab", MARKER, "nightly.0123456789ab.tmp", "pipeline.json"],
)
def test_the_store_never_deletes_an_entry_for_being_spelled_like_its_own(
    spelling: str, runner: CliRunner, stored: Path, cli_home: Path
) -> None:
    """The rule behind the one collision, rather than the collision.

    Every name this store gives something of its own is a name a caller could already have
    given a pipeline, because the rules about what a name may be have not been the same in
    every version. So no entry is deleted for how it is spelled; what the store sweeps, it
    sweeps because it recorded the claim inside it.
    """
    component = cli_home / "default" / "pipeline"
    taken = component / spelling
    (component / "nightly").rename(taken)
    before = digest(taken / "pipeline.json")

    listed = runner.invoke(cli, ["pipeline", "list", "--format", "json"])

    assert listed.exit_code == 0, listed.output
    assert digest(taken / "pipeline.json") == before
    assert [entry["name"] for entry in body(listed.stdout)["pipelines"]] == [spelling]


def test_a_removal_that_cannot_record_its_claim_leaves_the_pipeline_where_it_was(
    runner: CliRunner, stored: Path, cli_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing is emptied until the entry says it is being emptied.

    A directory taken for removal that cannot carry that record would be indistinguishable
    from a stored pipeline if the run died next, so it goes back under the name it came
    from and the command fails instead.
    """
    component = cli_home / "default" / "pipeline"
    before = digest(stored)
    real: Any = os.open

    def refusing(path: Any, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        if str(path) == MARKER:
            raise OSError(errno.EROFS, "no room for the record")
        return int(real(path, flags, mode, dir_fd=dir_fd))

    monkeypatch.setattr(os, "open", refusing)
    result = runner.invoke(cli, ["pipeline", "remove", "nightly", "--confirm"])
    monkeypatch.setattr(os, "open", real)

    assert result.exit_code == config.EXIT_PROFILE
    assert "could not be marked for removal" in result.stderr
    assert [entry.name for entry in component.iterdir()] == ["nightly"]
    assert digest(stored) == before


# ----------------------------------- what has to be on disk before what --
# Renaming an entry changes the namespace of the directory that holds it, and flushing the
# renamed directory does not flush the entry naming it. A removal that started unlinking
# before the rename was on disk could come back, after a power loss, as the caller's own
# name over contents that are half gone. So the claim is flushed first, and the rmdir that
# finishes the job is flushed before the command says it is done.
#
# Power loss is not something a test can stage. What these pin is the order of the calls
# that make the ordering true, which is the part this package controls.


def calls_during_a_removal(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """Every rename, flush and deletion of an entry, in the order they were made.

    Each is recorded with the directory it acted in, so a flush can be matched against the
    rename that needs it rather than against any flush that happened to come later.
    """
    seen: list[tuple[str, Any]] = []
    rename: Any = os.rename
    fsync: Any = os.fsync
    unlink: Any = os.unlink
    rmdir: Any = os.rmdir

    def renaming(src: Any, dst: Any, *, src_dir_fd: Any = None, dst_dir_fd: Any = None) -> None:
        seen.append(("rename", dst_dir_fd))
        rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    def flushing(descriptor: int) -> None:
        seen.append(("fsync", descriptor))
        fsync(descriptor)

    def unlinking(path: Any, *, dir_fd: Any = None) -> None:
        unlink(path, dir_fd=dir_fd)
        seen.append(("unlink", dir_fd))

    def removing(path: Any, *, dir_fd: Any = None) -> None:
        rmdir(path, dir_fd=dir_fd)
        seen.append(("rmdir", dir_fd))

    monkeypatch.setattr(os, "rename", renaming)
    monkeypatch.setattr(os, "fsync", flushing)
    monkeypatch.setattr(os, "unlink", unlinking)
    monkeypatch.setattr(os, "rmdir", removing)
    return seen


def test_the_claim_is_on_disk_before_anything_is_unlinked(
    runner: CliRunner, stored: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rename that takes the entry is flushed before the first deletion."""
    seen = calls_during_a_removal(monkeypatch)

    result = runner.invoke(cli, ["pipeline", "remove", "nightly", "--confirm"])

    assert result.exit_code == 0, result.output
    claim = next(index for index, (call, _) in enumerate(seen) if call == "rename")
    component = seen[claim][1]
    after = seen[claim + 1 :]
    deleted = next(index for index, (call, _) in enumerate(after) if call in {"unlink", "rmdir"})
    flushed = [index for index, entry in enumerate(after) if entry == ("fsync", component)]
    assert flushed, "the directory the claim renamed in was never flushed"
    assert flushed[0] < deleted, "something was deleted before the claim reached the disk"


def test_a_finished_removal_is_on_disk_before_the_command_returns(
    runner: CliRunner, stored: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The last rmdir is flushed, so a removal reported as done does not come back."""
    seen = calls_during_a_removal(monkeypatch)

    result = runner.invoke(cli, ["pipeline", "remove", "nightly", "--confirm"])

    assert result.exit_code == 0, result.output
    last = [index for index, (call, _) in enumerate(seen) if call == "rmdir"][-1]
    component = seen[last][1]
    assert ("fsync", component) in seen[last + 1 :], "the finished removal was never flushed"


def test_a_claim_that_cannot_be_flushed_leaves_the_pipeline_where_it_was(
    runner: CliRunner, stored: Path, cli_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing is emptied on the strength of a rename the disk did not take.

    The flush is the step that makes the claim real, so a removal that cannot make it goes
    back under the name it came from, exactly as one that cannot write its record does.
    """
    component = cli_home / "default" / "pipeline"
    before = digest(stored)
    taken: list[Any] = []
    rename: Any = os.rename
    fsync: Any = os.fsync

    def renaming(src: Any, dst: Any, *, src_dir_fd: Any = None, dst_dir_fd: Any = None) -> None:
        taken.append(dst_dir_fd)
        rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    def refusing(descriptor: int) -> None:
        if taken and descriptor == taken[0]:
            raise OSError(errno.EIO, "the disk did not take it")
        fsync(descriptor)

    monkeypatch.setattr(os, "rename", renaming)
    monkeypatch.setattr(os, "fsync", refusing)
    result = runner.invoke(cli, ["pipeline", "remove", "nightly", "--confirm"])

    assert result.exit_code == config.EXIT_PROFILE
    assert "could not be claimed for removal" in result.stderr
    assert [entry.name for entry in component.iterdir()] == ["nightly"]
    assert digest(stored) == before


# ------------------------------------------- a leftover with nothing in it --
# A run that dies between dropping the record and the rmdir it was dropped for leaves a
# claim-shaped directory holding nothing and saying nothing. It was warned about on every
# command until somebody deleted it by hand, which is a poor resting state for a tool
# somebody uses daily. An empty directory holds no work, so this one is cleared.


def test_an_empty_leftover_with_no_record_is_cleared_rather_than_warned_about(
    runner: CliRunner, stored: Path, cli_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one entry whose name decides its fate, because there is nothing else to decide on.

    The state is reached the way a real one is: a removal is stopped at its final rmdir,
    and the record it wrote back is then removed, which is what the run dying a moment
    earlier would have left.
    """
    component = cli_home / "default" / "pipeline"
    real: Any = os.rmdir

    def stopping(path: Any, *, dir_fd: int | None = None) -> None:
        raise OSError(errno.EIO, "stopped")

    monkeypatch.setattr(os, "rmdir", stopping)
    stopped = runner.invoke(cli, ["pipeline", "remove", "nightly", "--confirm"])
    monkeypatch.setattr(os, "rmdir", real)

    assert stopped.exit_code == config.EXIT_REQUEST
    left = next(entry for entry in component.iterdir())
    (left / MARKER).unlink()
    assert list(left.iterdir()) == [], "the leftover was not empty"

    listed = runner.invoke(cli, ["pipeline", "list"])

    assert listed.exit_code == 0, listed.output
    assert list(component.iterdir()) == [], "the empty leftover is still there"
    assert "holds no record" not in listed.stderr


def test_an_unrecorded_leftover_holding_anything_is_still_left_alone(
    runner: CliRunner, stored: Path, cli_home: Path
) -> None:
    """One file in it is enough, and it does not have to look like a pipeline.

    The sweep is not being taught to judge what is inside a directory. It removes an entry
    that holds nothing, and everything else still needs this store's own record.
    """
    component = cli_home / "default" / "pipeline"
    leftover = component / TAKEN
    leftover.mkdir()
    (leftover / "notes.txt").write_text("mine", encoding="utf-8")

    listed = runner.invoke(cli, ["pipeline", "list"])

    assert listed.exit_code == 0, listed.output
    assert (leftover / "notes.txt").read_text(encoding="utf-8") == "mine"
    assert "holds no record" in listed.stderr


@pytest.mark.parametrize("spelling", [MARKER, "nightly", ".hidden"])
def test_an_empty_directory_the_store_did_not_name_is_left_alone(
    spelling: str, runner: CliRunner, stored: Path, cli_home: Path
) -> None:
    """Emptiness alone is not the rule: the name has to be one only a claim is given."""
    component = cli_home / "default" / "pipeline"
    (component / "nightly").rename(component / "kept")
    (component / spelling).mkdir()

    listed = runner.invoke(cli, ["pipeline", "list"])

    assert listed.exit_code == 0, listed.output
    assert (component / spelling).is_dir(), "an empty directory was swept for being empty"


# ------------------------------------------- the boundary, as a discipline --
_ACTING = (
    "open",
    "mkdir",
    "unlink",
    "rmdir",
    "rename",
    "replace",
    "chmod",
    "truncate",
)
"""The calls that read or change something, as opposed to those that only report."""


def _names_below(spelled: str, home: Path) -> bool:
    return spelled.startswith(f"{home}/")


@pytest.fixture
def named_paths(monkeypatch: pytest.MonkeyPatch, cli_home: Path) -> list[str]:
    """Every acting call that names a path below the CLI home instead of using a descriptor."""
    seen: list[str] = []

    def watch(call: str) -> None:
        real: Any = getattr(os, call)

        def watching(*arguments: Any, **keywords: Any) -> Any:
            if keywords.get("dir_fd") is None and keywords.get("src_dir_fd") is None:
                for argument in arguments[:1]:
                    if isinstance(argument, str | Path) and _names_below(str(argument), cli_home):
                        seen.append(f"os.{call}({argument})")
            return real(*arguments, **keywords)

        monkeypatch.setattr(os, call, watching)

    for call in _ACTING:
        watch(call)
    return seen


@pytest.mark.parametrize(
    "command",
    [
        ["pipeline", "add", "second", "--request-file", "{request}"],
        ["pipeline", "import", "copy", "--pipeline-file", "{exported}"],
        ["pipeline", "remove", "nightly", "--confirm"],
        ["pipeline", "export", "nightly"],
        ["pipeline", "inspect", "nightly"],
        ["pipeline", "list"],
        ["profile", "config", "BLUE_DATA_LLM_MODEL", "gpt-4o-mini"],
        ["catalog", "select", "history"],
    ],
)
def test_no_operation_names_a_path_below_the_home(
    command: list[str],
    runner: CliRunner,
    stored: Path,
    request_file: str,
    tmp_path: Path,
    named_paths: list[str],
) -> None:
    """The discipline itself, rather than one race against it.

    A path below the home that reaches a syscall is a name the kernel resolves again, and a
    name resolved again is a name that can be swapped first. After the home is opened there
    should be none: everything below it goes through the descriptor the walk returned.
    """
    exported = tmp_path / "exported.json"
    exported.write_text(stored.read_text(encoding="utf-8"), encoding="utf-8")
    filled = [part.format(request=request_file, exported=str(exported)) for part in command]

    result = runner.invoke(cli, filled)

    assert result.exit_code == 0, result.output
    assert named_paths == []
