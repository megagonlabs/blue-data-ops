"""The ``blue-ops`` command tree.

Components in the family's ``<cli> <component> {<subcomponent>} <action> <parameters>``
shape. Nothing is reachable at the top level except a component group, so every action is
read the same way: the component says what is being acted on and the action says what is
being done to it.

Precedence, for every setting the profile spec declares a parameter for: **command option,
then environment variable, then profile, then built-in default.** The bottom three belong to
the resolver, which the root callback builds and exports into the environment before any
command runs; a command option sits on top and never reaches the resolver at all. The
catalog selection follows the same order, with the profile's ``.selected.catalog`` sitting
under ``BLUE_DATA_OPS_CATALOG``.

A flag the spec has no parameter for is read from the command line and nowhere else. That is
deliberate rather than an omission: a setting that describes one request, such as an
operator attribute or a search limit, would apply itself to the next unrelated request if it
were left in a profile.

This module declares the tree and the root options. What an option means to the library is
in :mod:`blue_data_ops_cli.config`; what a result looks like in each format is in
:mod:`blue_data_ops_cli.formats`.
"""

from __future__ import annotations

from typing import Any

import click

from blue_data_ops_cli import config
from blue_data_ops_cli.catalog import catalog_group
from blue_data_ops_cli.configstore import ConfigResolver
from blue_data_ops_cli.metadata import metadata_group
from blue_data_ops_cli.operator import operator_group
from blue_data_ops_cli.pipeline import pipeline_group
from blue_data_ops_cli.profile import profile_group, profile_store, resolver_for


# ------------------------------------------------------------------ #
# Root                                                                #
# ------------------------------------------------------------------ #
@click.group(cls=config.Group, context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(
    version=config.cli_version(), prog_name=config.PROGRAM, message="%(prog)s %(version)s"
)
@click.option(
    "--profile",
    "profile_name",
    envvar=config.PROFILE_VARIABLE,
    default=None,
    help=f"Configuration profile. Overrides {config.PROFILE_VARIABLE}. "
    f"Defaults to the selection in {config.CLI_HOME_DEFAULT}/.selected.profile.",
)
@click.pass_context
def cli(ctx: click.Context, profile_name: str | None) -> None:
    """blue-ops — run and inspect the Blue Data operator library from a shell.

    Configuration lives in profiles: `blue-ops profile config` to set values,
    `blue-ops profile inspect` to see them and where each came from. Every setting
    `profile inspect` lists is read from the command option first, then the environment,
    then the profile, then the built-in default. A flag with no parameter there is read
    from the command line and nowhere else.
    """
    home = ""
    resolver: ConfigResolver | None = None
    failure: config.CliError | None = None

    # Anything this callback refuses is held rather than raised. Click has not parsed the
    # subcommand's arguments yet, so a failure reported from here could only ever be plain
    # text; `config.start` raises it as the command body's first act, where `--format` is
    # known and a JSON consumer gets an object like any other failure.
    try:
        home = config.cli_home()

        # A fresh install gets its `default` profile here rather than being told to run
        # `profile add` before anything works. Keyed on the profiles file, so a profile
        # removed on purpose is not resurrected on the next command.
        store = profile_store(home)
        store.initialize()

        # A blank name is refused before the existence check, which reads it as "none
        # given" and falls through to the selected profile: `--profile ''` then ran under a
        # profile the caller did not name, which is a silent substitution.
        if profile_name is not None and not profile_name.strip():
            raise config.CliError(
                config.USAGE,
                f"--profile needs a profile name. Run `{config.PROGRAM} profile list` to see them.",
            )

        # A named profile that does not exist is refused rather than run as an empty one.
        # The whole point of putting a setting in a profile is that it applies, and a
        # misspelled name would silently drop every one of them.
        if profile_name and not store.exists(profile_name):
            raise config.CliError(
                config.PROFILE,
                f"no such profile: {profile_name!r}. Run `{config.PROGRAM} profile list` to "
                f"see them, or `{config.PROGRAM} profile add {profile_name}` to make it.",
            )

        # Apply the profile before anything else runs: resolved values are written into the
        # environment, which is where the provider SDK and `blue_data.config` read their
        # configuration from and the only way a profile can reach either.
        resolver = resolver_for(home, profile_name)
        # Undone when the command finishes, and registered before the export rather than
        # after it: an export that fails halfway has still written part of what it resolved.
        ctx.call_on_close(resolver.restore)
        resolver.export()
    except (click.Abort, click.exceptions.Exit):
        raise
    except Exception as error:
        failure = config.failure_for(error)

    ctx.obj = {
        "home": home,
        "profile": resolver.profile if resolver is not None else (profile_name or ""),
        "config": resolver,
        "failure": failure,
    }


# Components. Each one is a group in its own module, registered here and nowhere else, so
# the tree is readable in one place and a new component is one import and one line.
cli.add_command(profile_group)
cli.add_command(catalog_group)
cli.add_command(operator_group)
cli.add_command(pipeline_group)
cli.add_command(metadata_group)


def main() -> Any:
    """The console entry point's callable, for anything that imports rather than installs."""
    return cli()
