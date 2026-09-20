"""A sentinel put into every place a string can enter, looked for in every place one leaves.

The entries are a library exception, a value the environment holds, a configuration value
somebody typed, and a profile name. The exits are standard output, standard error, the JSON
error object, the `--log` lines and the traceback a failing logged run prints. No test here
reaches a provider or a data registry: the catalog seam is replaced and the home is a
temporary directory.

Every literal below is a sentinel, not a credential.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from blue_data_ops.operators import ResolveError
from click.testing import CliRunner, Result

from blue_data_ops_cli import config
from blue_data_ops_cli.commands import cli
from blue_data_ops_cli.mask import (
    CREDENTIAL_WORDS,
    MASK,
    SECRET_VARIABLE,
    fold_key,
    is_credential_key,
    mask,
)
from blue_data_ops_cli.profile import cli_spec

STAMPED = "sk-canary-NOTAKEY"
"""A key literal in the shape a provider stamps one with."""

ENVIRONMENT_VALUE = "canary-environment-value"
"""A key with no shape at all, which only the variable holding it identifies."""


def everything_visible(result: Result) -> str:
    """Both streams as one string, because a leak anywhere in them is a leak."""
    return f"{result.stdout}\n{result.stderr}"


# ------------------------------------------------------------- the channels --
@pytest.mark.parametrize("arguments", [[], ["--format", "json"]])
def test_a_library_exception_does_not_carry_a_key_to_any_stream(
    arguments: list[str], runner: CliRunner, install_catalog: Any
) -> None:
    install_catalog(ResolveError(f"authentication failed with api key {STAMPED}"))
    result = runner.invoke(cli, ["metadata", "inspect", *arguments])

    assert result.exit_code == config.EXIT_REQUEST
    assert STAMPED not in everything_visible(result)
    assert MASK in result.stderr


def test_the_json_error_object_is_masked_as_well_as_the_line(
    runner: CliRunner, install_catalog: Any
) -> None:
    """Two doors out of one error, and a consumer reading stdout sees the object."""
    install_catalog(ResolveError(f"authentication failed with api key {STAMPED}"))
    result = runner.invoke(cli, ["metadata", "inspect", "--format", "json"])
    envelope = json.loads(result.stdout)["error"]

    assert STAMPED not in envelope["message"]
    assert MASK in envelope["message"]


def test_the_json_error_detail_is_masked_too(runner: CliRunner) -> None:
    """`detail` is the other half of the object, and it quotes the same text."""
    failure = config.CliError(config.REQUEST, "refused", {"operator_id": STAMPED, "count": 1})
    assert failure.detail is not None
    assert failure.detail["operator_id"] == MASK
    assert failure.detail["count"] == 1


def test_a_traceback_under_log_is_masked(capsys: pytest.CaptureFixture[str]) -> None:
    """The frames quote the exception itself, so masking the reported line is not enough."""
    with pytest.raises(config.CliError):
        with config.reporting("table", log=True):
            raise ResolveError(f"authentication failed with api key {STAMPED}")
    captured = capsys.readouterr().err
    assert "Traceback" in captured
    assert STAMPED not in captured


def test_a_log_line_is_masked(capsys: pytest.CaptureFixture[str]) -> None:
    reporter = config.Reporter("table", log=True, log_limit=200)
    reporter.line(f"calling the provider with api_key={STAMPED}")
    reporter.note(f"resolved to {STAMPED}")
    reporter.warn(f"the registry rejected {STAMPED}")
    captured = capsys.readouterr().err
    assert STAMPED not in captured
    assert captured.count(MASK) == 3


def test_a_log_line_is_masked_before_it_is_truncated() -> None:
    """Cutting a value in half leaves a fragment that matches nothing."""
    text = f"prefix api_key={STAMPED} suffix"
    assert STAMPED[:12] not in config.truncate(mask(text), 40)


def test_a_key_held_in_the_environment_is_masked_whatever_it_looks_like(
    runner: CliRunner, install_catalog: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The realistic case: a provider SDK reads the variable and quotes what it read."""
    monkeypatch.setenv("OPENAI_API_KEY", ENVIRONMENT_VALUE)
    install_catalog(ResolveError(f"{ENVIRONMENT_VALUE} was rejected"))
    result = runner.invoke(cli, ["metadata", "inspect", "--format", "json"])

    assert ENVIRONMENT_VALUE not in everything_visible(result)


def test_a_failure_this_cli_never_classified_is_masked_too(
    runner: CliRunner, install_catalog: Any
) -> None:
    """An unclassified exception used to reach the terminal as an interpreter traceback."""
    install_catalog(RuntimeError(f"request failed: api_key={STAMPED}"))
    result = runner.invoke(cli, ["metadata", "inspect"])

    assert result.exit_code == config.EXIT_INTERNAL
    assert f"ERROR: {config.INTERNAL} " in result.stderr
    assert STAMPED not in everything_visible(result)
    assert "Traceback" not in everything_visible(result)


def test_a_refused_configuration_value_is_masked_where_it_is_set(runner: CliRunner) -> None:
    """A value typed under the wrong parameter is still the value somebody typed."""
    result = runner.invoke(cli, ["profile", "config", "BLUE_DATA_CLI_LOG_LIMIT", STAMPED])

    assert result.exit_code == config.EXIT_PROFILE
    assert STAMPED not in everything_visible(result)


def test_a_refused_configuration_value_is_masked_where_it_is_read(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read back a command later, by a path that runs before the error context exists."""
    monkeypatch.setenv("BLUE_DATA_OPS_TIMEOUT", STAMPED)
    result = runner.invoke(cli, ["profile", "inspect"])

    assert result.exit_code == config.EXIT_PROFILE
    assert STAMPED not in everything_visible(result)


# ---------------------------------------------------------- profile inspect --
def test_a_stored_secret_is_never_shown_by_inspect(runner: CliRunner) -> None:
    runner.invoke(cli, ["profile", "config", "OPENAI_API_KEY"], input=f"{STAMPED}\n")
    for arguments in ([], ["--format", "json"], ["--format", "nl"]):
        result = runner.invoke(cli, ["profile", "inspect", *arguments])
        assert STAMPED not in everything_visible(result), arguments
    assert MASK in runner.invoke(cli, ["profile", "inspect"]).stdout


def test_an_exported_secret_is_never_shown_by_inspect(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", ENVIRONMENT_VALUE)
    result = runner.invoke(cli, ["profile", "inspect", "--format", "json"])
    assert ENVIRONMENT_VALUE not in everything_visible(result)
    assert json.loads(result.stdout)["parameters"]["OPENAI_API_KEY"]["value"] == MASK


# ------------------------------------------------------------ the settings --
def test_the_model_setting_is_masked_wherever_the_envelope_is_published() -> None:
    """A deployment that pastes a credential into the model name gets it back in the footer."""
    from blue_data_ops_cli.configstore import ConfigResolver, ProfileStore

    resolver = ConfigResolver(cli_spec(), ProfileStore("/nonexistent"), "default", environment={})
    settings = config.Settings(resolver)
    settings.take("openai.model", STAMPED)
    settings.take("execution.timeout_seconds", 30.0)

    assert settings.envelope()["applied"]["openai.model"] == MASK
    assert settings.envelope()["applied"]["execution.timeout_seconds"] == 30.0
    assert STAMPED not in settings.footer()
    # What reaches the library is what the caller asked for; only the publication is masked.
    assert settings.applied["openai.model"] == STAMPED


def test_an_ordinary_model_name_is_not_masked() -> None:
    from blue_data_ops_cli.configstore import ConfigResolver, ProfileStore

    resolver = ConfigResolver(cli_spec(), ProfileStore("/nonexistent"), "default", environment={})
    settings = config.Settings(resolver)
    settings.take("openai.model", "gpt-4o-2024-08-06")
    assert "gpt-4o-2024-08-06" in settings.footer()


# --------------------------------------------------------------- the rules --
def test_the_masking_rule_agrees_with_the_parameters_this_cli_calls_secret() -> None:
    """One notion of a secret, held together across two ways of deciding it.

    The profile engine decides by declaration — a parameter whose cast is `secret` — and the
    mask decides by the shape of the variable's name. A parameter declared secret here and
    unrecognised there would be masked in `profile inspect` and printed in an error message.
    """
    secrets = [param.name for param in cli_spec() if param.is_secret]
    assert secrets
    for name in secrets:
        assert SECRET_VARIABLE.search(name), name


@pytest.mark.parametrize(
    "key",
    [
        "api_key",
        "openai.api_key",
        "OPENAI_API_KEY",
        "auth-token",
        "password",
        "secret",
        "my.token",
        "clientSecret",
        "accessToken",
        "refreshToken",
        "apiKey",
        "AWSSecretAccessKey",
        "oauth2Token",
        "Client Secret",
        "pwd",
        "Pwd",
        "passphrase",
        "passPhrase",
        "auth",
        "X-Auth",
        "db.pwd",
    ],
)
def test_a_credential_shaped_key_is_recognised(key: str) -> None:
    """`--attribute` and `--property` are refused on these, before the value reaches argv."""
    assert is_credential_key(key), key


@pytest.mark.parametrize(
    "key",
    [
        "key",
        "argmax_key",
        "sum_key",
        "partition_key",
        "name",
        "foreignKeys",
        "keystore",
        "user",
        "username",
        "login",
        "host",
        "port",
        "database",
        "dsn",
        "authority",
        "passing",
    ],
)
def test_an_ordinary_attribute_key_is_not_a_credential(key: str) -> None:
    """Operator attributes are named `key` throughout this library, and a column name
    treated as key material would refuse an ordinary operator call.

    `user`, `username` and `login` are the deliberate ones: discovery masks them on the way
    out, and refusing them here would refuse an ordinary data-source configuration.
    """
    assert not is_credential_key(key), key


def test_every_word_in_the_vocabulary_answers_for_a_key() -> None:
    """The list is the whole answer, so a word it claims that the guard does not recognise
    would be a promise the documentation makes and the code does not keep."""
    for word in CREDENTIAL_WORDS:
        assert is_credential_key(word), word
        assert is_credential_key(f"openai.{word}"), word
        assert is_credential_key(f"{word}_value"), word


@pytest.mark.parametrize(
    ("written", "folded"),
    [
        ("clientSecret", "client_secret"),
        ("client-secret", "client_secret"),
        ("Client Secret", "client_secret"),
        ("openai.api_key", "openai_api_key"),
        ("AWSAccessKeyId", "aws_access_key_id"),
        ("foreignKeys", "foreign_keys"),
    ],
)
def test_one_name_spelled_several_ways_folds_to_one(written: str, folded: str) -> None:
    """The vocabulary is read once, against the folded name, so it answers for every
    spelling rather than for the one it happens to be written in."""
    assert fold_key(written) == folded


@pytest.mark.parametrize(
    "text",
    [
        "Bearer abcdefghijklmnop",
        "api_key=abcd1234efgh",
        "sk-proj-abcdefghij",
        "ghp_abcdefghijklmnop",
        "AKIAABCDEFGHIJKL",
    ],
)
def test_key_shaped_text_is_masked(text: str) -> None:
    assert MASK in mask(text)


@pytest.mark.parametrize(
    "text",
    ["select@2.0.0", "the active catalog holds 33 cards", "gpt-4o", "requires-data-registry"],
)
def test_ordinary_text_survives_the_mask(text: str) -> None:
    """Masking reads shape, so an operator id or a tag costs nothing."""
    assert mask(text) == text
