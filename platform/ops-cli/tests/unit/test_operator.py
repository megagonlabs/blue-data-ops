"""Finding an operator, reading it, and running it.

The two things worth pinning here are the ones a user gets wrong and the ones that would
leak. A reference is either a pinned id or a bare name, and the bare form has to say what it
became or a run cannot be reproduced. `--attribute` and `--property` are the only channels
where the caller names both sides, so a key that reads as a credential is refused before the
value is used — and a key that merely contains the word `key`, which is half the attribute
names in this library, is not.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

import pytest
from blue_data_ops.operators import (
    Attributes,
    AttributeSpec,
    DataBundle,
    Operator,
    OperatorRegistry,
    Properties,
)
from click.testing import CliRunner

from blue_data_ops_cli import config
from blue_data_ops_cli.commands import cli

ACTIVE_CARDS = 33
HISTORY_CARDS = 87
ORDERS: DataBundle = [[{"total": 120.0}, {"total": 215.0}, {"total": 50.0}]]


class Echo(Operator):
    """A double with an ordinary `key` attribute and no dependency on anything."""

    name: ClassVar[str] = "echo"
    description: ClassVar[str] = "Return the records it was given"
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "key": AttributeSpec(type="str", description="An ordinary key name", default="value"),
        "partition_key": AttributeSpec(type="str", description="Another one", default="group"),
        "value": AttributeSpec(type="Any", description="Anything at all", default=None),
    }

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        del properties
        return [
            [{**record, "seen": attributes.get("value")} for record in group]
            for group in input_data
        ]


class Broken(Operator):
    """A double that fails the way an operator fails: inside `run`, as a record."""

    name: ClassVar[str] = "broken"
    description: ClassVar[str] = "Always fails"

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        del input_data, attributes, properties
        raise RuntimeError("the operator could not finish")


def doubles() -> OperatorRegistry:
    registry = OperatorRegistry()
    registry.register(Echo(), "1.0.0", ("domain-text", "accepts-none", "produces-data"))
    registry.register(Broken(), "1.0.0", ("domain-text", "accepts-data", "produces-data"))
    return registry


def written(path: Path, payload: Any) -> str:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def body(output: str) -> dict[str, Any]:
    return json.loads(output)


# ------------------------------------------------------------------- list --
def test_list_returns_every_card_in_the_selected_catalog(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["operator", "list", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert body(result.stdout)["count"] == ACTIVE_CARDS
    assert body(result.stdout)["catalog"] == "active"


def test_list_reads_the_catalog_the_option_names(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["operator", "list", "--catalog", "history", "--format", "json"])
    assert body(result.stdout)["count"] == HISTORY_CARDS


def test_a_listed_card_carries_its_id_name_version_and_domain(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["operator", "list", "--format", "json"])
    cards = body(result.stdout)["operators"]
    card = next(entry for entry in cards if entry["operator_id"] == "select@2.0.0")
    assert card == {
        "operator_id": "select@2.0.0",
        "name": "select",
        "version": "2.0.0",
        "domain": "domain-relational",
        "description": card["description"],
    }


# ----------------------------------------------------------------- search --
def test_search_scores_text_against_the_card(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["operator", "search", "average", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert "avg@3.0.0" in [entry["operator_id"] for entry in body(result.stdout)["operators"]]


def test_search_filters_by_tag(runner: CliRunner) -> None:
    result = runner.invoke(
        cli, ["operator", "search", "", "--tag", "requires-vector", "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    found = body(result.stdout)
    assert found["count"] > 0
    assert found["tags"] == ["requires-vector"]


def test_search_truncates_to_the_limit(runner: CliRunner) -> None:
    result = runner.invoke(
        cli,
        ["operator", "search", "", "--tag", "produces-data", "--limit", "2", "--format", "json"],
    )
    assert body(result.stdout)["count"] == 2


def test_a_blank_query_with_no_tag_is_refused_with_the_reason(runner: CliRunner) -> None:
    """The library returns nothing for this by rule, and an empty table would hide that."""
    result = runner.invoke(cli, ["operator", "search", ""])
    assert result.exit_code == config.EXIT_REQUEST
    assert "blank query needs at least one tag" in result.stderr


def test_a_malformed_tag_is_the_librarys_own_refusal(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["operator", "search", "", "--tag", "nohyphen"])
    assert result.exit_code == config.EXIT_REQUEST
    assert "DiscoveryError" in result.stderr


def test_a_limit_below_one_is_a_usage_error(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["operator", "search", "average", "--limit", "0"])
    assert result.exit_code == config.EXIT_USAGE


# ---------------------------------------------------------------- inspect --
def test_inspect_publishes_the_schema_under_the_family_word(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["operator", "inspect", "select@2.0.0", "--format", "json"])
    assert result.exit_code == 0, result.output
    schema = body(result.stdout)["operator"]["schema"]
    assert schema["operand_key"]["required"] is True
    assert schema["eps"]["has_default"] is True


def test_inspect_groups_the_cards_tags_by_axis(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["operator", "inspect", "select@2.0.0", "--format", "json"])
    assert body(result.stdout)["operator"]["tags"]["domain"] == ["domain-relational"]


def test_a_bare_name_resolves_and_says_what_it_became(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["operator", "inspect", "avg", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert body(result.stdout)["operator"]["operator_id"] == "avg@3.0.0"


def test_the_resolution_is_reported_on_standard_error_under_a_human_format(
    runner: CliRunner,
) -> None:
    result = runner.invoke(cli, ["operator", "inspect", "avg"])
    assert result.exit_code == 0, result.output
    assert "avg resolved to avg@3.0.0" in result.stderr


def test_a_bare_name_is_refused_where_the_catalog_holds_several_versions(
    runner: CliRunner,
) -> None:
    """Picking the highest would be a guess dressed as a resolution."""
    result = runner.invoke(cli, ["operator", "inspect", "avg", "--catalog", "history"])
    assert result.exit_code == config.EXIT_REQUEST
    assert "ambiguous" in result.stderr
    assert "avg@3.0.0" in result.stderr
    assert "avg@1.0.0" in result.stderr


def test_an_unknown_id_names_the_command_that_finds_the_right_one(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["operator", "inspect", "selct@2.0.0"])
    assert result.exit_code == config.EXIT_REQUEST
    assert "operator search selct" in result.stderr


# -------------------------------------------------------------------- run --
def test_run_passes_the_bundle_through_and_reports_what_came_back(
    runner: CliRunner, tmp_path: Path
) -> None:
    result = runner.invoke(
        cli,
        [
            "operator",
            "run",
            "select@2.0.0",
            "--input-file",
            written(tmp_path / "orders.json", ORDERS),
            "--attribute",
            "operand_key=total",
            "--attribute",
            "operand=>",
            "--attribute",
            "operand_val=100",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    found = body(result.stdout)
    assert found["result"]["output_data"] == [[{"total": 120.0}, {"total": 215.0}]]
    assert found["operator_id"] == "select@2.0.0"
    assert found["errors"] == []


def test_run_reads_the_bundle_from_standard_input(runner: CliRunner) -> None:
    result = runner.invoke(
        cli,
        [
            "operator",
            "run",
            "select@2.0.0",
            "--input-file",
            "-",
            "--attribute",
            "operand_key=total",
            "--attribute",
            "operand=>",
            "--attribute",
            "operand_val=100",
            "--format",
            "json",
        ],
        input=json.dumps(ORDERS),
    )
    assert result.exit_code == 0, result.output
    assert body(result.stdout)["result"]["output_data"] == [[{"total": 120.0}, {"total": 215.0}]]


@pytest.mark.parametrize(
    ("written_value", "read_back"),
    [("5", 5), ("5.5", 5.5), ("true", True), ("total", "total"), ('"5"', "5"), ("[1,2]", [1, 2])],
)
def test_a_value_is_json_where_it_parses_and_text_where_it_does_not(
    written_value: str, read_back: Any, runner: CliRunner, install_catalog: Any
) -> None:
    """`--attribute limit=5` has to mean the number and `key=total` has to mean the word."""
    install_catalog(doubles())
    result = runner.invoke(
        cli,
        [
            "operator",
            "run",
            "echo@1.0.0",
            "--input-file",
            "-",
            "--attribute",
            f"value={written_value}",
            "--format",
            "json",
        ],
        input=json.dumps([[{"n": 1}]]),
    )
    assert result.exit_code == 0, result.output
    assert body(result.stdout)["result"]["output_data"] == [[{"n": 1, "seen": read_back}]]


def test_an_operator_that_consumes_nothing_is_given_an_empty_bundle(
    runner: CliRunner, install_catalog: Any
) -> None:
    """The library says `accepts-none` does not make the argument optional, so the CLI
    supplies the bundle rather than asking for a file holding `[[]]`."""
    install_catalog(doubles())
    result = runner.invoke(cli, ["operator", "run", "echo@1.0.0", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert body(result.stdout)["result"]["output_data"] == [[]]


def test_an_operator_that_consumes_records_says_so_when_the_file_is_missing(
    runner: CliRunner, install_catalog: Any
) -> None:
    install_catalog(doubles())
    result = runner.invoke(cli, ["operator", "run", "broken@1.0.0"])
    assert result.exit_code == config.EXIT_USAGE
    assert "--input-file is required" in result.stderr


def test_the_file_is_applied_first_and_the_options_override_one_key(
    runner: CliRunner, tmp_path: Path, install_catalog: Any
) -> None:
    install_catalog(doubles())
    result = runner.invoke(
        cli,
        [
            "operator",
            "run",
            "echo@1.0.0",
            "--input-file",
            written(tmp_path / "in.json", [[{"n": 1}]]),
            "--attributes-file",
            written(tmp_path / "attrs.json", {"value": "from-file", "key": "kept"}),
            "--attribute",
            "value=from-option",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert body(result.stdout)["result"]["output_data"] == [[{"n": 1, "seen": "from-option"}]]


def test_a_bundle_that_is_not_groups_of_records_is_refused(
    runner: CliRunner, tmp_path: Path
) -> None:
    path = written(tmp_path / "bad.json", {"a": 1})
    result = runner.invoke(cli, ["operator", "run", "select@2.0.0", "--input-file", path])
    assert result.exit_code == config.EXIT_REQUEST
    assert "list of record groups" in result.stderr


@pytest.mark.parametrize("option", ["--attribute", "--property"])
@pytest.mark.parametrize(
    "key",
    [
        "api_key",
        "openai.api_key",
        "auth_token",
        "client-secret",
        "PASSWORD",
        "clientSecret",
        "accessToken",
        "pwd",
        "passphrase",
        "auth",
    ],
)
def test_a_credential_shaped_key_is_refused_before_it_is_used(
    option: str, key: str, runner: CliRunner, install_catalog: Any
) -> None:
    """The value is in argv and in shell history before this CLI can reach it."""
    install_catalog(doubles())
    result = runner.invoke(cli, ["operator", "run", "echo@1.0.0", option, f"{key}=whatever"])
    assert result.exit_code == config.EXIT_USAGE
    assert "profile config OPENAI_API_KEY" in result.stderr
    assert "whatever" not in result.stderr


@pytest.mark.parametrize("option", ["--attribute", "--property"])
@pytest.mark.parametrize(
    ("written_value", "reported_at"),
    [
        ('{"password": "SENTINEL"}', "outer.password"),
        ('{"nested": {"api_key": "SENTINEL"}}', "outer.nested.api_key"),
        ('[{"client-secret": "SENTINEL"}]', "outer[0].client-secret"),
        ('{"a": [{"b": {"auth_token": "SENTINEL"}}]}', "outer.a[0].b.auth_token"),
        ('{"a": {"b": {"c": {"credentials": "SENTINEL"}}}}', "outer.a.b.c.credentials"),
    ],
)
def test_a_credential_shaped_key_inside_the_value_is_refused_too(
    option: str, written_value: str, reported_at: str, runner: CliRunner, install_catalog: Any
) -> None:
    """A nested key is in argv exactly as much as an outer one.

    `--attribute properties={...}` is how database settings are passed, so the value is a
    place a credential lands by habit rather than by trickery.
    """
    install_catalog(doubles())
    result = runner.invoke(cli, ["operator", "run", "echo@1.0.0", option, f"outer={written_value}"])
    assert result.exit_code == config.EXIT_USAGE
    assert reported_at in result.stderr
    assert "profile config OPENAI_API_KEY" in result.stderr
    assert "SENTINEL" not in result.output


@pytest.mark.parametrize("option", ["--attribute", "--property"])
@pytest.mark.parametrize(
    ("written_value", "reported_at"),
    [
        ('{"clientSecret": "SENTINEL"}', "outer.clientSecret"),
        ('{"accessToken": "SENTINEL"}', "outer.accessToken"),
        ('{"connection": {"clientSecret": "SENTINEL"}}', "outer.connection.clientSecret"),
        ('[{"accessToken": "SENTINEL"}]', "outer[0].accessToken"),
        ('{"a": [{"refreshToken": "SENTINEL"}]}', "outer.a[0].refreshToken"),
        ('{"a": {"b": [{"AWSSecretAccessKey": "SENTINEL"}]}}', "outer.a.b[0].AWSSecretAccessKey"),
        ('{"servers": [{"Client Secret": "SENTINEL"}]}', "outer.servers[0].Client Secret"),
    ],
)
def test_a_camel_cased_credential_key_is_refused_at_any_depth(
    option: str, written_value: str, reported_at: str, runner: CliRunner, install_catalog: Any
) -> None:
    """`clientSecret` is the same key as `client_secret`, and a settings object spells it
    either way depending on whose JSON it came out of."""
    install_catalog(doubles())
    result = runner.invoke(cli, ["operator", "run", "echo@1.0.0", option, f"outer={written_value}"])
    assert result.exit_code == config.EXIT_USAGE
    assert reported_at in result.stderr
    assert "profile config OPENAI_API_KEY" in result.stderr
    assert "SENTINEL" not in result.output


@pytest.mark.parametrize("option", ["--attribute", "--property"])
@pytest.mark.parametrize(
    ("written_value", "reported_at"),
    [
        ('{"pwd": "SENTINEL"}', "outer.pwd"),
        ('{"passphrase": "SENTINEL"}', "outer.passphrase"),
        ('{"auth": "SENTINEL"}', "outer.auth"),
        ('{"connection": {"Pwd": "SENTINEL"}}', "outer.connection.Pwd"),
        ('{"connection": {"passPhrase": "SENTINEL"}}', "outer.connection.passPhrase"),
        ('{"headers": {"Auth": "SENTINEL"}}', "outer.headers.Auth"),
        ('[{"pwd": "SENTINEL"}]', "outer[0].pwd"),
        ('[{"passphrase": "SENTINEL"}]', "outer[0].passphrase"),
        ('{"servers": [{"auth": "SENTINEL"}]}', "outer.servers[0].auth"),
    ],
)
def test_a_short_credential_name_is_refused_at_any_depth(
    option: str, written_value: str, reported_at: str, runner: CliRunner, install_catalog: Any
) -> None:
    """`Pwd=` is how an ODBC connection string spells a password, and a connection string is
    exactly the sort of thing `--property properties={...}` carries."""
    install_catalog(doubles())
    result = runner.invoke(cli, ["operator", "run", "echo@1.0.0", option, f"outer={written_value}"])
    assert result.exit_code == config.EXIT_USAGE
    assert reported_at in result.stderr
    assert "profile config OPENAI_API_KEY" in result.stderr
    assert "SENTINEL" not in result.output


@pytest.mark.parametrize(
    "key", ["key", "partition_key", "keys", "user", "username", "login", "host", "database"]
)
def test_an_ordinary_attribute_name_is_not_refused(
    key: str, runner: CliRunner, install_catalog: Any
) -> None:
    """Half the attribute names in this library end in `key`, and a data source is
    configured with an account name and a host on the command line every day."""
    install_catalog(doubles())
    result = runner.invoke(cli, ["operator", "run", "echo@1.0.0", "--attribute", f"{key}=total"])
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize(
    "written_value",
    [
        '{"key": "total", "argmax_key": "n"}',
        '{"partition": {"sum_key": "total", "partition_key": "region"}}',
        '[{"key": "a"}, {"key": "b"}]',
        '{"schema": {"foreignKeys": ["orders.id"]}}',
        '[{"foreignKeys": [{"partition_key": "day"}]}]',
    ],
)
def test_an_ordinary_name_nested_in_a_value_is_not_refused(
    written_value: str, runner: CliRunner, install_catalog: Any
) -> None:
    """The exclusions that make the outer refusal usable have to hold at depth as well,
    or a grouping operator's own attributes become unpassable."""
    install_catalog(doubles())
    result = runner.invoke(
        cli, ["operator", "run", "echo@1.0.0", "--attribute", f"value={written_value}"]
    )
    assert result.exit_code == 0, result.output


def test_a_pair_with_no_key_names_the_form_it_wanted(
    runner: CliRunner, install_catalog: Any
) -> None:
    install_catalog(doubles())
    result = runner.invoke(cli, ["operator", "run", "echo@1.0.0", "--attribute", "novalue"])
    assert result.exit_code == config.EXIT_USAGE
    assert "KEY=VALUE" in result.stderr


def test_a_failed_run_exits_execution_and_carries_the_library_code(
    runner: CliRunner, tmp_path: Path, install_catalog: Any
) -> None:
    install_catalog(doubles())
    result = runner.invoke(
        cli,
        [
            "operator",
            "run",
            "broken@1.0.0",
            "--input-file",
            written(tmp_path / "in.json", [[{"n": 1}]]),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == config.EXIT_EXECUTION
    assert body(result.stdout)["error"]["code"] == "EXECUTION"
    assert body(result.stdout)["error"]["detail"]["library_code"] == "EXECUTION_FAILED"


def test_the_applied_settings_are_published_with_the_tier_each_came_from(
    runner: CliRunner, tmp_path: Path
) -> None:
    result = runner.invoke(
        cli,
        [
            "operator",
            "run",
            "select@2.0.0",
            "--input-file",
            written(tmp_path / "orders.json", ORDERS),
            "--attribute",
            "operand_key=total",
            "--attribute",
            "operand=>",
            "--attribute",
            "operand_val=100",
            "--timeout",
            "5",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    settings = body(result.stdout)["settings"]
    assert settings["applied"]["execution.timeout_seconds"] == 5.0
    assert settings["source"]["execution.timeout_seconds"] == "flag"
    assert settings["source"]["openai.model"] == "default"


def test_the_table_footer_names_the_same_settings(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(
        cli,
        [
            "operator",
            "run",
            "select@2.0.0",
            "--input-file",
            written(tmp_path / "o.json", ORDERS),
            "--attribute",
            "operand_key=total",
            "--attribute",
            "operand=>",
            "--attribute",
            "operand_val=100",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "settings: openai.model=gpt-4o (default)" in result.stdout


def test_a_card_that_does_not_ask_for_a_data_registry_never_builds_one(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, install_catalog: Any
) -> None:
    built: list[str] = []

    def build() -> Any:
        built.append("seam")
        raise AssertionError("no card in this run needs a data registry")

    monkeypatch.setattr(config, "build_registry_seam", build)
    install_catalog(doubles())
    result = runner.invoke(
        cli, ["operator", "run", "echo@1.0.0", "--input-file", "-"], input=json.dumps([[{"n": 1}]])
    )
    assert result.exit_code == 0, result.output
    assert built == []


def test_a_tagged_card_is_handed_the_seam_and_warned_about_a_memory_backend(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, install_catalog: Any
) -> None:
    """The library would otherwise build a registry per call and drop it at exit."""
    seam = object()
    monkeypatch.setattr(config, "build_registry_seam", lambda: seam)
    registry = doubles()
    registry.register(Echo(), "2.0.0", ("domain-text", "accepts-none", config.DATA_REGISTRY_TAG))
    install_catalog(registry)
    result = runner.invoke(cli, ["operator", "run", "echo@2.0.0"])
    assert result.exit_code == 0, result.output
    assert "BLUE_DATA_REGISTRY_STORE is memory" in result.stderr


def test_a_worked_around_failure_is_reported_on_standard_error(
    runner: CliRunner, tmp_path: Path
) -> None:
    """A ``RECOVERABLE`` record does not move the exit code, and it used to reach no stream
    at all under a human format: an empty bundle, exit 0, and no reason for either, while
    the same run under ``json`` carried the record and its suggestion."""
    result = runner.invoke(
        cli,
        [
            "operator",
            "run",
            "select@2.0.0",
            "--input-file",
            written(tmp_path / "orders.json", ORDERS),
            "--attribute",
            "operand_ke=total",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "INVALID_INPUT" in result.stderr
    assert "select@2.0.0" in result.stderr
    assert "supply a supported operand" in result.stderr


def test_the_worked_around_failure_is_the_same_record_json_publishes(
    runner: CliRunner, tmp_path: Path
) -> None:
    result = runner.invoke(
        cli,
        [
            "operator",
            "run",
            "select@2.0.0",
            "--input-file",
            written(tmp_path / "orders.json", ORDERS),
            "--attribute",
            "operand_ke=total",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    records = body(result.stdout)["errors"]
    assert [record["category"] for record in records] == ["RECOVERABLE"]
    assert records[0]["code"] in result.stderr
    assert records[0]["message"] in result.stderr
