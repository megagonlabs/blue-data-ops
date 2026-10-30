"""The profile store and the resolver, below the Click layer.

These are the rules the CLI's configuration story rests on: where a value comes from, what a
secret looks like on disk, and what a write is allowed to touch. They are checked here
rather than through commands, because a command test would pass with any of several wrong
answers to "which tier won".
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any, cast

import pytest

from blue_data_ops_cli import configstore
from blue_data_ops_cli.config import CATALOGS
from blue_data_ops_cli.configstore import (
    MASK,
    ConfigResolver,
    ProfileError,
    ProfileStore,
    SettingError,
    Spec,
    base_spec,
    decode,
    display,
    encode,
    load_spec,
)
from blue_data_ops_cli.formats import FORMATS
from blue_data_ops_cli.pipeline import PLANNERS

SPEC_PATH = Path(configstore.__file__).with_name("profile_spec.json")


def cli_spec() -> Spec:
    """The same merge `profile.py` makes: family parameters plus this CLI's own."""
    return base_spec().merged_with(load_spec(SPEC_PATH))


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / ".blue-ops"


@pytest.fixture
def store(home: Path) -> ProfileStore:
    store = ProfileStore(home)
    store.initialize()
    return store


def resolver(store: ProfileStore, profile: str | None = None, **environment: str) -> ConfigResolver:
    return ConfigResolver(cli_spec(), store, profile=profile, environment=environment)


# ----------------------------------------------------------------- the spec --
def test_the_walked_list_is_the_two_parameters_a_first_run_is_asked_for() -> None:
    """Short on purpose: a long walk is an interrogation, and nothing here blocks on one."""
    assert [p.name for p in cli_spec().required()] == ["OPENAI_API_KEY", "BLUE_DATA_LLM_MODEL"]


def test_the_family_parameters_keep_the_family_names_and_casts() -> None:
    spec = base_spec()
    assert spec["OPENAI_API_KEY"].is_secret
    assert spec["BLUE_DATA_LLM_MODEL"].default == "gpt-6-luna"
    assert cli_spec()["BLUE_DATA_OPS_PLANNER_MODEL"].default == "gpt-6-luna"
    assert spec["BLUE_DATA_CLI_FORMAT"].default == "table"
    assert spec["BLUE_DATA_CLI_LOG_LIMIT"].cast == "int"


def test_every_parameter_name_is_uppercase_and_prefixed() -> None:
    """The checklist's naming row, asserted over the whole spec rather than spot-checked."""
    for parameter in cli_spec():
        assert parameter.name == parameter.name.upper(), parameter.name
        assert parameter.name.startswith("BLUE_DATA_") or parameter.name == "OPENAI_API_KEY"


def test_the_registry_parameters_keep_blue_data_s_own_names_and_defaults() -> None:
    """They are read by `blue_data.config`, so a renamed one would reach nothing."""
    spec = cli_spec()
    assert spec["BLUE_DATA_REGISTRY_STORE"].default == "memory"
    for name in (
        "BLUE_DATA_REGISTRY_FILE",
        "BLUE_DATA_REGISTRY_REDIS_URL",
        "BLUE_DATA_REGISTRY_REDIS_NAMESPACE",
        "BLUE_DATA_SOURCES_CONFIG",
    ):
        assert name in spec


def test_an_unknown_parameter_names_itself() -> None:
    with pytest.raises(SettingError, match="unknown configuration parameter: NOT_A_PARAM"):
        cli_spec()["NOT_A_PARAM"]


def test_a_cast_failure_names_the_parameter() -> None:
    with pytest.raises(SettingError, match="BLUE_DATA_OPS_TIMEOUT"):
        cli_spec()["BLUE_DATA_OPS_TIMEOUT"].cast_value("soon")


def test_profile_choices_match_the_command_options() -> None:
    spec = cli_spec()
    assert spec["BLUE_DATA_CLI_FORMAT"].choices == FORMATS
    assert spec["BLUE_DATA_OPS_CATALOG"].choices == CATALOGS
    assert spec["BLUE_DATA_OPS_PLANNER"].choices == PLANNERS
    assert spec["BLUE_DATA_REGISTRY_STORE"].validate_for_storage("REDIS") == "REDIS"


def test_very_large_numeric_profile_values_report_a_setting_error() -> None:
    huge = 10**1000
    spec = cli_spec()
    with pytest.raises(SettingError, match="must be <= 16384"):
        spec["BLUE_DATA_OPS_PLANNER_MAX_OUTPUT_TOKENS"].validate_for_storage(huge)
    with pytest.raises(SettingError, match="must be a number"):
        spec["BLUE_DATA_OPS_TIMEOUT"].cast_value(huge)
    with pytest.raises(SettingError, match="must be >="):
        configstore.Parameter(name="X", cast="int", minimum=huge).validate_for_storage(1)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('{"X": {"choices": ["ok", 2]}}', "invalid choices"),
        ('{"X": {"choices": ["a", "A"], "case_sensitive": false}}', "repeats a choice"),
        ('{"X": {"cast": "str", "minimum": 0}}', "numeric cast"),
        ('{"X": {"cast": "float", "minimum": 6, "maximum": 5}}', "inverted"),
        ('{"X": {"cast": "float", "exclusive_minimum": true}}', "exclusive minimum"),
        ('{"X": {"default": "bad", "choices": ["ok"]}}', "must be one of"),
    ],
)
def test_invalid_profile_constraints_are_refused(tmp_path: Path, body: str, message: str) -> None:
    path = tmp_path / "spec.json"
    path.write_text(body)
    with pytest.raises(SettingError, match=message):
        load_spec(path)


def test_merging_keeps_both_halves_and_lets_the_cli_win(tmp_path: Path) -> None:
    extra = tmp_path / "spec.json"
    extra.write_text('{"BLUE_DATA_CLI_FORMAT": {"default": "json", "cast": "str"}}')
    merged = base_spec().merged_with(load_spec(extra))
    assert merged["BLUE_DATA_CLI_FORMAT"].default == "json"
    assert "OPENAI_API_KEY" in merged


def test_a_spec_declaring_an_unknown_cast_does_not_load(tmp_path: Path) -> None:
    bad = tmp_path / "spec.json"
    bad.write_text('{"X": {"cast": "colour"}}')
    with pytest.raises(SettingError, match="unknown cast"):
        load_spec(bad)


# -------------------------------------------------------------- the profile --
def test_a_first_run_creates_and_selects_default(home: Path) -> None:
    store = ProfileStore(home)
    store.initialize()
    assert store.list_profiles() == ["default"]
    assert store.selected() == "default"


def test_a_removed_profile_is_not_resurrected(store: ProfileStore) -> None:
    """Keyed on the profiles file, so the next command does not undo the removal."""
    store.add("staging")
    store.remove("default")
    store.initialize()
    assert store.list_profiles() == ["staging"]


def test_adding_a_profile_twice_says_so(store: ProfileStore) -> None:
    store.add("staging")
    with pytest.raises(ProfileError, match="already exists"):
        store.add("staging")


def test_removing_an_absent_profile_says_so(store: ProfileStore) -> None:
    with pytest.raises(ProfileError, match="no such profile"):
        store.remove("ghost")


def test_selecting_an_absent_profile_says_so(store: ProfileStore) -> None:
    with pytest.raises(ProfileError, match="no such profile"):
        store.select("ghost")


def test_remove_touches_only_that_section(store: ProfileStore) -> None:
    store.add("staging")
    store.add("keep")
    store.set_value("keep", "BLUE_DATA_LLM_MODEL", "gpt-4o-mini")
    store.set_value("staging", "BLUE_DATA_LLM_MODEL", "gpt-4")
    store.write_selection("staging", "catalog", "history")
    store.write_selection("keep", "catalog", "active")

    store.remove("staging")

    assert store.list_profiles() == ["default", "keep"]
    assert store.values("keep") == {"BLUE_DATA_LLM_MODEL": "gpt-4o-mini"}
    assert store.read_selection("keep", "catalog") == "active"
    # The removed profile's own directory is left where it is; the command says so.
    assert store.read_selection("staging", "catalog") == "history"
    assert store.selected() == "default"


def test_removing_the_selected_profile_falls_back_to_default(store: ProfileStore) -> None:
    store.add("staging")
    store.select("staging")
    store.remove("staging")
    assert store.selected() == "default"


def test_the_profiles_file_is_ini_with_one_section_per_profile(store: ProfileStore) -> None:
    store.add("staging")
    store.set_value("staging", "BLUE_DATA_LLM_MODEL", "gpt-4o-mini")
    text = (store.home / ".profiles").read_text()
    assert "[staging]" in text
    assert text.index("[staging]") < text.index("gpt-4o-mini")


def test_parameter_names_keep_their_case_on_disk(store: ProfileStore) -> None:
    """The parameter name is the environment variable name; lower-casing it breaks both."""
    store.set_value("default", "BLUE_DATA_LLM_MODEL", "gpt-4")
    assert "BLUE_DATA_LLM_MODEL" in (store.home / ".profiles").read_text()
    assert store.values("default") == {"BLUE_DATA_LLM_MODEL": "gpt-4"}


def test_a_value_holding_a_percent_survives_the_round_trip(store: ProfileStore) -> None:
    store.set_value("default", "BLUE_DATA_LLM_MODEL", "gpt-100%")
    assert store.values("default")["BLUE_DATA_LLM_MODEL"] == "gpt-100%"


# -------------------------------------------------------------- the storage --
def test_the_home_directory_is_private(home: Path) -> None:
    ProfileStore(home).initialize()
    assert stat.S_IMODE(home.stat().st_mode) == 0o700


def test_every_file_written_is_private(store: ProfileStore) -> None:
    store.set_value("default", "BLUE_DATA_LLM_MODEL", "gpt-4")
    assert stat.S_IMODE((store.home / ".profiles").stat().st_mode) == 0o600
    assert stat.S_IMODE((store.home / ".selected.profile").stat().st_mode) == 0o600


def test_a_profile_directory_and_its_selection_are_private_too(store: ProfileStore) -> None:
    """The second tier of the storage hierarchy, created on demand by the write."""
    store.write_selection("default", "catalog", "history")
    directory = store.profile_dir("default")
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE((directory / ".selected.catalog").stat().st_mode) == 0o600


def test_reading_a_selection_that_was_never_written_creates_nothing(store: ProfileStore) -> None:
    assert store.read_selection("default", "catalog") is None
    assert not store.profile_dir("default").exists()


def test_a_selection_round_trips(store: ProfileStore) -> None:
    store.write_selection("default", "catalog", "history")
    assert store.read_selection("default", "catalog") == "history"
    store.write_selection("default", "catalog", "active")
    assert store.read_selection("default", "catalog") == "active"


def test_a_write_leaves_no_temporary_file_behind(store: ProfileStore) -> None:
    store.set_value("default", "BLUE_DATA_LLM_MODEL", "gpt-4")
    assert sorted(p.name for p in store.home.iterdir()) == [".profiles", ".selected.profile"]


def test_a_failed_write_leaves_the_previous_contents_intact(
    store: ProfileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole reason the write is atomic: a half-written profiles file is unreadable."""
    store.set_value("default", "BLUE_DATA_LLM_MODEL", "gpt-4")
    before = (store.home / ".profiles").read_text()

    def explode(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(configstore.os, "replace", explode)
    with pytest.raises(ProfileError, match="disk full"):
        store.set_value("default", "BLUE_DATA_LLM_MODEL", "gpt-4o-mini")

    assert (store.home / ".profiles").read_text() == before
    assert sorted(p.name for p in store.home.iterdir()) == [".profiles", ".selected.profile"]


def test_a_store_that_cannot_be_read_is_an_error_rather_than_a_traceback(home: Path) -> None:
    """Every command builds a resolver, so an unreadable store takes the whole tree down."""
    home.mkdir(parents=True)
    (home / ".profiles").mkdir()
    with pytest.raises(ProfileError, match="cannot read"):
        ProfileStore(home).list_profiles()


def test_a_selection_that_cannot_be_read_is_an_error_too(home: Path) -> None:
    home.mkdir(parents=True)
    (home / ".selected.profile").mkdir()
    with pytest.raises(ProfileError, match="cannot read"):
        ProfileStore(home).selected()


def test_a_home_that_cannot_be_written_is_an_error_too(tmp_path: Path) -> None:
    read_only = tmp_path / "read-only"
    read_only.mkdir(mode=0o500)
    with pytest.raises(ProfileError):
        ProfileStore(read_only / "home").initialize()


@pytest.mark.parametrize("value", ["a\rb", "a\nb", "a\r[injected]\rOPENAI_API_KEY = x"])
def test_a_value_holding_a_line_break_is_refused(store: ProfileStore, value: str) -> None:
    """configparser escapes a newline on the way out and not a carriage return.

    A value pasted from a CRLF file came back as a separate setting, and one shaped like INI
    came back as a separate profile — from a write that reported success.
    """
    with pytest.raises(SettingError, match="line break"):
        store.set_value("default", "BLUE_DATA_LLM_MODEL", value)
    assert "injected" not in (store.home / ".profiles").read_text()


def test_a_blank_value_is_refused_rather_than_stored_and_ignored(store: ProfileStore) -> None:
    store.set_value("default", "BLUE_DATA_LLM_MODEL", "gpt-4o-mini")
    with pytest.raises(SettingError, match="blank"):
        store.set_value("default", "BLUE_DATA_LLM_MODEL", "  ")
    assert store.values("default")["BLUE_DATA_LLM_MODEL"] == "gpt-4o-mini"


def test_a_wider_existing_home_is_reported_once_and_left_alone(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home.mkdir(parents=True)
    os.chmod(home, 0o755)
    configstore._reported_modes.clear()  # pyright: ignore[reportPrivateUsage]

    store = ProfileStore(home)
    store.initialize()
    store.add("staging")

    assert stat.S_IMODE(home.stat().st_mode) == 0o755
    assert capsys.readouterr().err.count(str(home)) == 1


def test_a_symlink_out_of_the_home_is_refused_rather_than_followed(
    home: Path, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "stolen").write_text("[default]\n")
    home.mkdir(parents=True)
    (home / ".profiles").symlink_to(elsewhere / "stolen")

    with pytest.raises(ProfileError, match="symlink"):
        ProfileStore(home).list_profiles()


def test_a_symlink_inside_the_home_is_fine(home: Path) -> None:
    home.mkdir(parents=True)
    (home / "real").write_text("[default]\n")
    (home / ".profiles").symlink_to(home / "real")
    assert ProfileStore(home).list_profiles() == ["default"]


def test_a_directory_above_the_file_may_not_link_out_of_the_home(
    home: Path, tmp_path: Path
) -> None:
    """The file is not a link; the directory holding it is.

    Checking the last component of a path answers nothing about the directories above it,
    and a component directory is where a link does the most.
    """
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    home.mkdir(parents=True)
    (home / "staging").symlink_to(elsewhere)

    with pytest.raises(ProfileError, match="outside"):
        ProfileStore(home).write_selection("staging", "catalog", "active")
    assert list(elsewhere.iterdir()) == []


def test_a_read_through_a_linked_directory_is_refused_too(home: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / ".selected.catalog").write_text("history", encoding="utf-8")
    home.mkdir(parents=True)
    (home / "staging").symlink_to(elsewhere)

    with pytest.raises(ProfileError, match="outside"):
        ProfileStore(home).read_selection("staging", "catalog")


# The four tests above put the link in place before the store runs. These two put it there
# while it is running, after the boundary has been decided and before the name is used — the
# gap a check cannot close, because the check is not what gets attacked. The profile
# directory is renamed rather than deleted, so a descriptor already holding it still reaches
# the real files and the test can tell which of the two the store read or wrote.


def _swap_the_profile_directory(home: Path, elsewhere: Path, profile: str = "staging") -> None:
    directory = home / profile
    directory.rename(home / f"{profile}.moved")
    directory.symlink_to(elsewhere)


def test_a_profile_directory_swapped_during_a_write_does_not_redirect_it(
    home: Path, tmp_path: Path, creations_under: Any, swap_when_opened: Any
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (home / "staging").mkdir(parents=True)
    landed = cast("list[str]", creations_under(elsewhere))
    swap_when_opened(
        ".selected.catalog",
        lambda: _swap_the_profile_directory(home, elsewhere),
        creating=True,
    )

    ProfileStore(home).write_selection("staging", "catalog", "active")

    assert landed == []
    assert list(elsewhere.iterdir()) == []


def test_a_profile_directory_swapped_during_a_read_is_not_followed(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The swap goes where the window is: the last thing the store does before taking the
    bytes. That used to be after the boundary was decided and before the file was opened;
    now the file is already open and the name it was opened by no longer matters."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / ".selected.catalog").write_text("OUTSIDE", encoding="utf-8")
    (home / "staging").mkdir(parents=True)
    (home / "staging" / ".selected.catalog").write_text("history", encoding="utf-8")

    real: Any = configstore._report_wide_mode  # pyright: ignore[reportPrivateUsage]
    swapped = False

    def reporting(*arguments: Any, **keywords: Any) -> None:
        nonlocal swapped
        if not swapped and str(arguments[0]).endswith(".selected.catalog"):
            swapped = True
            _swap_the_profile_directory(home, elsewhere)
        real(*arguments, **keywords)

    monkeypatch.setattr(configstore, "_report_wide_mode", reporting)

    assert ProfileStore(home).read_selection("staging", "catalog") == "history"


@pytest.mark.parametrize("name", ["bad/name", "bad\\name", "..", "."])
def test_a_profile_name_that_could_be_a_path_is_refused(home: Path, name: str) -> None:
    """A name is an INI section *and* a directory under the home, so it has to be neither
    a separator nor a directory reference."""
    store = ProfileStore(home)
    store.initialize()
    with pytest.raises(ProfileError):
        store.add(name)
    with pytest.raises(ProfileError):
        store.profile_dir(name)


def test_a_hand_edited_selection_naming_a_path_is_refused(home: Path) -> None:
    """The selection file is editable by hand, and its contents are joined onto the home."""
    store = ProfileStore(home)
    store.initialize()
    (home / ".selected.profile").write_text("../escape")
    with pytest.raises(ProfileError):
        store.selected()


# --------------------------------------------------------------- the secret --
def test_a_secret_is_not_stored_in_plain_text(store: ProfileStore) -> None:
    store.set_value("default", "OPENAI_API_KEY", encode("typed-at-the-prompt"))
    stored = (store.home / ".profiles").read_text()
    assert "typed-at-the-prompt" not in stored
    assert "enc:" in stored
    assert decode(store.values("default")["OPENAI_API_KEY"]) == "typed-at-the-prompt"


def test_a_reference_is_stored_as_written_and_resolved_at_use(
    store: ProfileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.set_value("default", "OPENAI_API_KEY", encode("$MY_KEY"))
    assert store.values("default")["OPENAI_API_KEY"] == "$MY_KEY"
    monkeypatch.delenv("MY_KEY", raising=False)
    assert decode("$MY_KEY") is None
    monkeypatch.setenv("MY_KEY", "exported-not-stored")
    assert decode("$MY_KEY") == "exported-not-stored"


def test_display_masks_a_stored_secret_and_names_a_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert display(encode("typed-at-the-prompt")) == MASK
    monkeypatch.delenv("MY_KEY", raising=False)
    assert display("$MY_KEY") == "$MY_KEY (unset)"
    monkeypatch.setenv("MY_KEY", "anything")
    assert display("$MY_KEY") == "$MY_KEY (set)"


# ------------------------------------------------------------- the resolver --
def test_the_environment_outranks_the_profile(store: ProfileStore) -> None:
    store.set_value("default", "BLUE_DATA_LLM_MODEL", "from-profile")
    config = resolver(store, BLUE_DATA_LLM_MODEL="from-environment")
    assert config.get("BLUE_DATA_LLM_MODEL") == "from-environment"
    assert config.source_of("BLUE_DATA_LLM_MODEL") == "environment"


@pytest.mark.parametrize("exported", ["", "   "])
def test_an_empty_export_is_refused_rather_than_read_as_unset(
    store: ProfileStore, exported: str
) -> None:
    """It used to win its tier and then hand the answer down to the profile in silence.

    Which is the same defect the store already refuses at write time: the tier that
    answered has to be the tier that had something to say.
    """
    store.set_value("default", "BLUE_DATA_LLM_MODEL", "profile-model")
    with pytest.raises(SettingError, match="BLUE_DATA_LLM_MODEL"):
        resolver(store, BLUE_DATA_LLM_MODEL=exported)


def test_an_empty_export_is_refused_by_name_even_where_it_was_the_only_tier(
    store: ProfileStore,
) -> None:
    """No profile value to fall through to, and still refused: the export is the mistake."""
    with pytest.raises(SettingError, match="BLUE_DATA_OPS_TIMEOUT"):
        resolver(store, BLUE_DATA_OPS_TIMEOUT="")


def test_the_profile_outranks_the_default(store: ProfileStore) -> None:
    store.set_value("default", "BLUE_DATA_LLM_MODEL", "from-profile")
    config = resolver(store)
    assert config.get("BLUE_DATA_LLM_MODEL") == "from-profile"
    assert config.source_of("BLUE_DATA_LLM_MODEL") == "profile:default"


def test_the_default_is_the_last_tier(store: ProfileStore) -> None:
    config = resolver(store)
    assert config.get("BLUE_DATA_LLM_MODEL") == "gpt-6-luna"
    assert config.source_of("BLUE_DATA_LLM_MODEL") == "default"


def test_a_parameter_with_no_default_reports_unset(store: ProfileStore) -> None:
    config = resolver(store)
    assert config.get("BLUE_DATA_OPS_TIMEOUT") is None
    assert config.source_of("BLUE_DATA_OPS_TIMEOUT") == "unset"


def test_a_resolved_value_arrives_cast(store: ProfileStore) -> None:
    store.set_value("default", "BLUE_DATA_OPS_TIMEOUT", "1.5")
    store.set_value("default", "BLUE_DATA_OPS_PLANNER_MAX_OUTPUT_TOKENS", "256")
    config = resolver(store)
    assert config.get("BLUE_DATA_OPS_TIMEOUT") == 1.5
    assert config.get("BLUE_DATA_OPS_PLANNER_MAX_OUTPUT_TOKENS") == 256


def test_export_writes_the_resolved_values_into_the_environment(
    store: ProfileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.set_value("default", "BLUE_DATA_REGISTRY_STORE", "file")
    monkeypatch.delenv("BLUE_DATA_REGISTRY_STORE", raising=False)
    ConfigResolver(cli_spec(), store, environment={}).export()
    assert os.environ["BLUE_DATA_REGISTRY_STORE"] == "file"


def test_export_does_not_overwrite_what_the_caller_set(
    store: ProfileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.set_value("default", "BLUE_DATA_LLM_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("BLUE_DATA_LLM_MODEL", "chosen-by-hand")
    ConfigResolver(cli_spec(), store).export()
    assert os.environ["BLUE_DATA_LLM_MODEL"] == "chosen-by-hand"


def test_an_export_is_undone_when_it_is_restored(
    store: ProfileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One run is one process, but a test harness is not, and the tiers have to survive it."""
    store.set_value("default", "BLUE_DATA_LLM_MODEL", "gpt-4o-mini")
    monkeypatch.delenv("BLUE_DATA_LLM_MODEL", raising=False)
    config = ConfigResolver(cli_spec(), store)
    config.export()
    assert os.environ["BLUE_DATA_LLM_MODEL"] == "gpt-4o-mini"
    config.restore()
    assert "BLUE_DATA_LLM_MODEL" not in os.environ


def test_restoring_puts_back_what_the_caller_had(
    store: ProfileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BLUE_DATA_CLI_LOG_LIMIT", "120")
    config = ConfigResolver(cli_spec(), store)
    config.export()
    config.restore()
    assert os.environ["BLUE_DATA_CLI_LOG_LIMIT"] == "120"


def test_a_resolver_reports_the_tier_that_won_rather_than_its_own_exports(
    store: ProfileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The snapshot is the whole point: after `export`, the live environment holds the
    profile's own values, and resolving against it would call them environment values."""
    store.set_value("default", "BLUE_DATA_LLM_MODEL", "gpt-4o-mini")
    monkeypatch.delenv("BLUE_DATA_LLM_MODEL", raising=False)
    config = ConfigResolver(cli_spec(), store)
    config.export()
    assert config.source_of("BLUE_DATA_LLM_MODEL") == "profile:default"


def test_a_secret_resolves_through_its_reference(
    store: ProfileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.set_value("default", "OPENAI_API_KEY", encode("$MY_KEY"))
    monkeypatch.setenv("MY_KEY", "exported-not-stored")
    assert resolver(store).get("OPENAI_API_KEY") == "exported-not-stored"


def test_an_inherited_parameter_is_tried_before_the_default(store: ProfileStore) -> None:
    spec = Spec(
        [
            configstore.Parameter("BLUE_DATA_LLM_MODEL", default="gpt-4o"),
            configstore.Parameter(
                "BLUE_DATA_OPS_PLANNER_MODEL",
                inherits=("BLUE_DATA_LLM_MODEL",),
            ),
        ]
    )
    store.set_value("default", "BLUE_DATA_LLM_MODEL", "gpt-4o-mini")
    config = ConfigResolver(spec, store, environment={})
    assert config.get("BLUE_DATA_OPS_PLANNER_MODEL") == "gpt-4o-mini"
