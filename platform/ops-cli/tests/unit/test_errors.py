"""Errors reach the terminal as one line and an exit code, never as a traceback.

The code vocabulary and the exit table are the contract a script branches on, so every code
is raised here and checked for both halves: the token in the message and the status on the
way out.

The library raises its failures from deep inside an operator or a planner. The seam every
command reads the library through is `config.build_catalog`, so raising from there puts a
library exception into a real command body rather than into a stub of one. `EXECUTION` and
`TIMEOUT` never arrive as exceptions at all: `Operator.run()` returns them in
`ExecMeta.errors`, so they are built by `config.execution_failure` and then raised the way a
command raises them.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from blue_data_ops.operator_skills import OperatorSkillErrorCode, OperatorSkillLoadError
from blue_data_ops.operators import (
    DiscoveryError,
    ErrorCategory,
    ErrorCode,
    ErrorRecord,
    ErrorStage,
    ResolveError,
)
from blue_data_ops.plan import (
    PipelineError,
    PlanningError,
    PlanningErrorCode,
    PlanningErrorRecord,
    PlanningStage,
)
from click.testing import CliRunner

from blue_data_ops_cli import config
from blue_data_ops_cli.commands import cli

INSPECT = ["metadata", "inspect"]


def planning_error(code: PlanningErrorCode, message: str = "planning stopped") -> PlanningError:
    return PlanningError(
        PlanningErrorRecord(
            category=ErrorCategory.FAILED,
            code=code,
            stage=PlanningStage.GENERATION,
            message=message,
            retryable=code is PlanningErrorCode.GENERATOR_RATE_LIMITED,
            suggestion=None,
        )
    )


def error_record(
    category: ErrorCategory = ErrorCategory.FAILED,
    code: ErrorCode = ErrorCode.EXECUTION_FAILED,
) -> ErrorRecord:
    return ErrorRecord(
        category=category,
        code=code,
        operator_id="select@2.0.0",
        stage=ErrorStage.EXECUTE,
        message="the operator could not finish",
        retryable=False,
        suggestion=None,
    )


# ------------------------------------------------------------- the exit map --
def test_the_exit_table_is_the_documented_one() -> None:
    assert config.EXIT_FOR_CODE == {
        "INTERNAL": 1,
        "USAGE": 2,
        "REQUEST": 3,
        "CONFIG": 4,
        "PROFILE": 4,
        "TRANSPORT": 5,
        "RESOURCE": 6,
        "PLANNING": 7,
        "EXECUTION": 8,
        "TIMEOUT": 9,
    }


def test_the_code_vocabulary_is_closed() -> None:
    """Ten codes, one per failure family. A library code is carried in the description."""
    assert len(config.EXIT_FOR_CODE) == 10
    assert set(config.EXIT_FOR_CODE) == {
        config.INTERNAL,
        config.USAGE,
        config.REQUEST,
        config.CONFIG,
        config.PROFILE,
        config.TRANSPORT,
        config.RESOURCE,
        config.PLANNING,
        config.EXECUTION,
        config.TIMEOUT,
    }


# ------------------------------------------------- one code per library family --
@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ResolveError("no card for 'selct@2.0.0'"), config.REQUEST),
        (DiscoveryError("a blank query needs at least one tag"), config.REQUEST),
        (PipelineError("the graph has a cycle"), config.REQUEST),
        (OperatorSkillLoadError(OperatorSkillErrorCode.NOT_AVAILABLE), config.RESOURCE),
        (planning_error(PlanningErrorCode.PLAN_INVALID), config.PLANNING),
        (planning_error(PlanningErrorCode.GENERATOR_TIMEOUT), config.TRANSPORT),
        (planning_error(PlanningErrorCode.GENERATOR_RATE_LIMITED), config.TRANSPORT),
        (planning_error(PlanningErrorCode.GENERATOR_UNAVAILABLE), config.TRANSPORT),
        (planning_error(PlanningErrorCode.GENERATOR_DEPENDENCY_MISSING), config.CONFIG),
        (RuntimeError("something nothing here names"), config.INTERNAL),
    ],
    ids=lambda value: value if isinstance(value, str) else type(value).__name__,
)
def test_every_library_failure_gets_its_code_and_its_exit_status(
    error: Exception, code: str, runner: CliRunner, install_catalog: Any
) -> None:
    install_catalog(error)
    result = runner.invoke(cli, INSPECT)
    assert result.exit_code == config.EXIT_FOR_CODE[code], result.output
    assert f"ERROR: {code} " in result.stderr
    assert "Traceback" not in result.output


def test_a_planning_failure_carries_the_library_code_in_the_description(
    runner: CliRunner, install_catalog: Any
) -> None:
    """The CLI code is stable; the library code is what actually diagnoses the failure."""
    install_catalog(planning_error(PlanningErrorCode.NO_CANDIDATES))
    result = runner.invoke(cli, INSPECT)
    assert "NO_CANDIDATES" in result.stderr
    assert "GENERATION" in result.stderr


def test_a_resource_failure_carries_its_own_code_too(
    runner: CliRunner, install_catalog: Any
) -> None:
    install_catalog(OperatorSkillLoadError(OperatorSkillErrorCode.BINDING_MISMATCH))
    result = runner.invoke(cli, INSPECT)
    assert result.exit_code == config.EXIT_RESOURCE
    assert "BINDING_MISMATCH" in result.stderr


@pytest.mark.parametrize(
    ("category", "code", "expected"),
    [
        (ErrorCategory.FAILED, ErrorCode.EXECUTION_FAILED, config.EXECUTION),
        (ErrorCategory.TIMEOUT, ErrorCode.OPERATOR_TIMEOUT, config.TIMEOUT),
    ],
    ids=["failed", "timeout"],
)
def test_a_failure_returned_as_data_gets_its_code_and_its_exit_status(
    category: ErrorCategory, code: ErrorCode, expected: str
) -> None:
    """`Operator.run()` returns its failures instead of raising, so the exception boundary
    never sees them and something has to classify them explicitly."""
    failure = config.execution_failure([error_record(category, code)])
    assert failure is not None
    assert failure.code == expected
    assert failure.exit_code == config.EXIT_FOR_CODE[expected]
    assert code.value in failure.message
    assert failure.detail is not None
    assert failure.detail["operator_id"] == "select@2.0.0"


def test_a_recoverable_record_is_not_a_failed_run() -> None:
    """The operator worked around something and the output beside it is usable."""
    assert config.execution_failure([error_record(ErrorCategory.RECOVERABLE)]) is None
    assert config.execution_failure([]) is None


def test_an_execution_failure_reaches_the_terminal_in_the_standard_shape(
    runner: CliRunner, install_catalog: Any
) -> None:
    failure = config.execution_failure([error_record()])
    assert failure is not None
    install_catalog(failure)
    result = runner.invoke(cli, INSPECT)
    assert result.exit_code == config.EXIT_EXECUTION
    assert "ERROR: EXECUTION " in result.stderr


# ------------------------------------------------------------- the reporting --
def test_an_error_line_cannot_drive_the_terminal(runner: CliRunner) -> None:
    """The message carries a name someone typed and a library message quoting an operator."""
    result = runner.invoke(cli, ["profile", "inspect", "ev\x1b[2J\x1b[31m!"])
    assert result.exit_code == config.EXIT_PROFILE
    assert "\x1b" not in result.stderr


def test_config_and_profile_share_a_status_and_are_told_apart_by_the_token(
    runner: CliRunner, install_catalog: Any
) -> None:
    install_catalog(planning_error(PlanningErrorCode.GENERATOR_DEPENDENCY_MISSING))
    library = runner.invoke(cli, INSPECT)
    local = runner.invoke(cli, ["profile", "config", "NOT_A_PARAM", "x"])

    assert library.exit_code == local.exit_code == 4
    assert "ERROR: CONFIG" in library.stderr
    assert "ERROR: PROFILE" in local.stderr


def test_an_error_goes_to_stderr_and_leaves_stdout_empty(
    runner: CliRunner, install_catalog: Any
) -> None:
    install_catalog(ResolveError("no card for 'selct@2.0.0'"))
    result = runner.invoke(cli, INSPECT)
    assert result.stdout == ""
    assert "no card for" in result.stderr


def test_an_error_is_one_line(runner: CliRunner, install_catalog: Any) -> None:
    install_catalog(ResolveError("no card for 'selct@2.0.0'"))
    result = runner.invoke(cli, INSPECT)
    assert len([line for line in result.stderr.splitlines() if line.strip()]) == 1


def test_a_traceback_is_printed_under_log_and_not_without_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(config.CliError):
        with config.reporting("table", log=False):
            raise ResolveError("no card for 'selct@2.0.0'")
    assert "Traceback" not in capsys.readouterr().err

    with pytest.raises(config.CliError):
        with config.reporting("table", log=True):
            raise ResolveError("no card for 'selct@2.0.0'")
    assert "Traceback" in capsys.readouterr().err


# ---------------------------------------------------------- the json shape --
def test_an_error_after_the_body_starts_is_also_an_object_on_stdout(
    runner: CliRunner, install_catalog: Any
) -> None:
    install_catalog(ResolveError("no card for 'selct@2.0.0'"))
    result = runner.invoke(cli, [*INSPECT, "--format", "json"])
    assert result.exit_code == config.EXIT_REQUEST
    assert json.loads(result.stdout) == {
        "error": {
            "code": "REQUEST",
            "message": "ResolveError: no card for 'selct@2.0.0'",
            "detail": {"library_code": "RESOLVE_ERROR"},
        }
    }
    assert "ERROR: REQUEST" in result.stderr


def test_the_detail_key_is_always_present_even_when_it_is_null(
    runner: CliRunner, install_catalog: Any
) -> None:
    """A reader branches on what `detail` says rather than on whether it arrived."""
    install_catalog(RuntimeError("something nothing here names"))
    result = runner.invoke(cli, [*INSPECT, "--format", "json"])
    published = json.loads(result.stdout)
    assert published["error"]["detail"] is None


def test_a_planning_detail_carries_the_record_fields(
    runner: CliRunner, install_catalog: Any
) -> None:
    install_catalog(planning_error(PlanningErrorCode.GENERATOR_RATE_LIMITED))
    result = runner.invoke(cli, [*INSPECT, "--format", "json"])
    detail = json.loads(result.stdout)["error"]["detail"]
    assert detail["library_code"] == "GENERATOR_RATE_LIMITED"
    assert detail["stage"] == "GENERATION"
    assert detail["category"] == "FAILED"
    assert detail["retryable"] is True


def test_a_parse_failure_stays_plain_text_because_the_format_is_not_known_yet(
    runner: CliRunner,
) -> None:
    """Click refuses the flag before any command body runs, so there is no format to honour."""
    result = runner.invoke(cli, [*INSPECT, "--nope", "--format", "json"])
    assert result.exit_code == config.EXIT_USAGE
    assert result.stdout == ""
    assert "ERROR: USAGE" in result.stderr


@pytest.mark.parametrize(
    "command",
    [
        ["--profile", "nope", "metadata", "inspect"],
        ["--profile", "nope", "profile", "list"],
        ["--profile", "nope", "profile", "inspect"],
    ],
    ids=lambda value: value[3],
)
def test_a_startup_failure_is_an_object_too(command: list[str], runner: CliRunner) -> None:
    """The root callback refuses the profile before Click has parsed `--format`.

    It used to report that itself, in plain text, so the one failure a caller is most
    likely to hit under `--format json` was the one that arrived as prose on stderr.
    """
    result = runner.invoke(cli, [*command, "--format", "json"])
    assert result.exit_code == config.EXIT_PROFILE
    assert json.loads(result.stdout)["error"]["code"] == "PROFILE"
    assert "ERROR: PROFILE" in result.stderr


def test_a_setting_read_while_the_result_is_built_is_an_object_too(runner: CliRunner) -> None:
    """A cast failure on a parameter a command reads is inside the error contract, not outside."""
    result = runner.invoke(
        cli,
        ["profile", "inspect", "--format", "json"],
        env={"BLUE_DATA_OPS_TIMEOUT": "soon"},
    )
    assert result.exit_code == config.EXIT_PROFILE
    assert json.loads(result.stdout) == {
        "error": {
            "code": "PROFILE",
            "message": "BLUE_DATA_OPS_TIMEOUT must be a number, got 'soon'",
            "detail": None,
        }
    }


def test_the_log_limit_reports_a_bad_value_as_a_profile_error() -> None:
    """Read to build the reporter, before the reporting context exists, so it carries its
    own handler. Checked here because no command in this package takes `--log` yet."""
    from blue_data_ops_cli.configstore import ConfigResolver, ProfileStore
    from blue_data_ops_cli.profile import cli_spec

    store = ProfileStore("/nonexistent-home-for-a-spec-only-resolver")
    resolver = ConfigResolver(cli_spec(), store, profile="default", environment={})
    assert config.resolve_log_limit(resolver, None) == 80
    assert config.resolve_log_limit(resolver, 0) == 0

    bad = ConfigResolver(
        cli_spec(), store, profile="default", environment={"BLUE_DATA_CLI_LOG_LIMIT": "bad"}
    )
    with pytest.raises(config.CliError) as raised:
        config.resolve_log_limit(bad, None)
    assert raised.value.code == config.PROFILE


def test_a_configured_format_that_is_not_a_format_is_reported_as_text(runner: CliRunner) -> None:
    """The residue of the boundary: the failure is the lookup that would name the format.

    With `--format json` on the command line there is no lookup and no failure; without one
    there is nothing left to publish in, so this reports as text and says why in the message.
    """
    result = runner.invoke(cli, INSPECT, env={"BLUE_DATA_CLI_FORMAT": "nonsense"})
    assert result.exit_code == config.EXIT_PROFILE
    assert result.stdout == ""
    assert "BLUE_DATA_CLI_FORMAT is 'nonsense'" in result.stderr


# ----------------------------------------------------- corrective guidance --
def test_an_unknown_option_suggests_what_to_try(runner: CliRunner) -> None:
    result = runner.invoke(cli, [*INSPECT, "--nope"])
    assert result.exit_code == config.EXIT_USAGE
    assert "--help" in result.stderr


def test_an_unknown_command_is_a_usage_error(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["metadata", "describe"])
    assert result.exit_code == config.EXIT_USAGE
    assert "ERROR: USAGE" in result.stderr


def test_a_missing_argument_is_a_usage_error(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["profile", "add"])
    assert result.exit_code == config.EXIT_USAGE
    assert "ERROR: USAGE" in result.stderr


def test_every_refusal_names_the_command_or_the_parameter_that_corrects_it(
    runner: CliRunner,
) -> None:
    """Row 49's testable half: a message that says only what failed is half an answer."""
    for command, expected in (
        (["profile", "select", "ghost"], "profile list"),
        (["profile", "remove", "ghost", "--confirm"], "profile list"),
        (["profile", "config", "OPENAI_API_KEY", "x"], "profile config"),
        (["--profile", "ghost", "profile", "list"], "profile add ghost"),
    ):
        result = runner.invoke(cli, command)
        assert expected in result.stderr, command


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("request failed", "request failed. Check the requested setting."),
        ("request failed.", "request failed. Check the requested setting."),
        ("request failed!", "request failed! Check the requested setting."),
        ("request failed?", "request failed? Check the requested setting."),
    ],
)
@pytest.mark.parametrize("surface", ["operator", "planner"])
def test_suggestions_start_a_separate_sentence(message: str, expected: str, surface: str) -> None:
    suggestion = "Check the requested setting."
    if surface == "operator":
        record = error_record()._replace(message=message, suggestion=suggestion)
        failure = config.execution_failure([record])
        assert failure is not None
    else:
        error = planning_error(PlanningErrorCode.PLAN_INVALID, message)
        error = PlanningError(error.record._replace(suggestion=suggestion))
        failure = config.failure_for(error)
    assert failure.message.endswith(expected)
    assert failure.detail is not None and failure.detail["suggestion"] == suggestion
