"""Option translation and the CLI's own vocabulary: errors, tiers, catalogs, progress.

Every mapping between what the user typed and what the library accepts lives here, so a
command module is argument declaration and printing and nothing else.

Four things beyond translation belong here because they are one decision each, and a
decision made twice is a decision that drifts:

*The error vocabulary.* ``ERROR: <CODE> <description>`` on stderr, one line, and an exit
code a script can branch on without parsing the message. The library has four structured
taxonomies and none of them is a CLI code set, so this module declares a closed set of ten
codes, one per failure family, and carries the library's own code in the description and in
the JSON error's ``detail``. Click's parse failures are converted to the same shape by the
group and command classes below, so a caller sees one format whether the CLI refused the
flag or the library refused the value. Under ``--format json`` the same failure is an object
on stdout, from the moment Click has parsed the arguments: the parse itself is the only
thing outside that, because until it finishes there is no ``--format`` to honour.

*The tier a value came from.* The resolver owns environment, profile and default; a command
option sits above all three and never reaches the resolver at all. :class:`Settings` records
both the value and its tier as each option is read, which is what the ``settings`` envelope
publishes and what the table footer prints.

*Which catalog a command reads.* The selection is a four-tier chain of its own, and the
registry it names is built here, so a command asks for a view by name and never constructs
one.

*Where the not-result goes.* Progress, logs and warnings are stderr; stdout carries the
result. :class:`Reporter` is the only thing that writes to stderr during a run, and it stays
quiet under ``--format json`` where a spinner would otherwise be the one thing standing
between a caller and a clean pipe.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import traceback
from collections.abc import Generator, Mapping, Sequence
from importlib import metadata
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, cast

import click
from blue_data_ops import RegistrySeam
from blue_data_ops.operator_skills import OperatorSkillLoadError
from blue_data_ops.operators import (
    DiscoveryError,
    ErrorCategory,
    ErrorRecord,
    OperatorCard,
    OperatorRegistry,
    ResolveError,
    active_registry,
    versioned_registry,
)
from blue_data_ops.plan import PipelineError, PlanningError, PlanningErrorCode
from rich.console import Console

from blue_data_ops_cli import __version__
from blue_data_ops_cli.configstore import ConfigResolver, StoreError
from blue_data_ops_cli.formats import FORMATS, printable
from blue_data_ops_cli.mask import mask

PROGRAM = "blue-ops"
DISTRIBUTION = "blue-data-ops-cli"
CLI_HOME_DEFAULT = "~/.blue-ops"
HOME_VARIABLE = "BLUE_DATA_OPS_HOME"
PROFILE_VARIABLE = "BLUE_DATA_PROFILE"

# --------------------------------------------------------------- exit codes --
# 2 belongs to Click, which uses it for usage errors, so the library families start at 3.
# 0 through 5 carry the meanings the family's other guide-compliant CLI already gave them;
# 6 through 9 are this library's own families and collide with nothing.
EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_USAGE = 2
EXIT_REQUEST = 3
EXIT_CONFIG = 4
EXIT_PROFILE = 4
EXIT_TRANSPORT = 5
EXIT_RESOURCE = 6
EXIT_PLANNING = 7
EXIT_EXECUTION = 8
EXIT_TIMEOUT = 9

INTERNAL = "INTERNAL"
USAGE = "USAGE"
REQUEST = "REQUEST"
CONFIG = "CONFIG"
PROFILE = "PROFILE"
TRANSPORT = "TRANSPORT"
RESOURCE = "RESOURCE"
PLANNING = "PLANNING"
EXECUTION = "EXECUTION"
TIMEOUT = "TIMEOUT"

EXIT_FOR_CODE = {
    INTERNAL: EXIT_INTERNAL,
    USAGE: EXIT_USAGE,
    REQUEST: EXIT_REQUEST,
    # Two codes on one exit status, told apart by the token. CONFIG is a resolved setting
    # the library rejected; PROFILE is a profile operation this CLI rejected. They share a
    # status because a script branching on "your configuration is wrong" wants one branch.
    CONFIG: EXIT_CONFIG,
    PROFILE: EXIT_PROFILE,
    TRANSPORT: EXIT_TRANSPORT,
    RESOURCE: EXIT_RESOURCE,
    PLANNING: EXIT_PLANNING,
    EXECUTION: EXIT_EXECUTION,
    TIMEOUT: EXIT_TIMEOUT,
}

_TRANSPORT_PLANNING_CODES = frozenset(
    {
        PlanningErrorCode.GENERATOR_TIMEOUT,
        PlanningErrorCode.GENERATOR_RATE_LIMITED,
        PlanningErrorCode.GENERATOR_UNAVAILABLE,
    }
)
"""Planning outcomes that describe the provider rather than the plan."""

_CONFIG_PLANNING_CODES = frozenset({PlanningErrorCode.GENERATOR_DEPENDENCY_MISSING})
"""Planning outcomes that describe this installation rather than the plan."""

_CAMEL = re.compile(r"(?<!^)(?=[A-Z])")


def _library_code(error: Exception) -> str:
    """``ResolveError`` as ``RESOLVE_ERROR``.

    The three request-family exceptions carry no code of their own, so the class name is the
    precise thing the CLI can publish, spelled the way the library's own enums are spelled.
    """
    return _CAMEL.sub("_", type(error).__name__).upper()


class CliError(click.ClickException):
    """One line on stderr: ``ERROR: <CODE> <description>``, and an exit code to branch on."""

    def __init__(self, code: str, message: str, detail: dict[str, Any] | None = None) -> None:
        # Masked once, at construction, rather than at each of the two places an error is
        # written. A message is built out of a library message, a provider SDK's exception
        # text and whatever the caller typed, and it leaves here by two doors -- the stderr
        # line and the JSON envelope -- which is one door too many to mask at.
        super().__init__(mask(message))
        self.code = code
        self.detail = _masked_detail(detail)

    @property
    def exit_code(self) -> int:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Click reads this to decide the process status; the code decides it here."""
        return EXIT_FOR_CODE[self.code]

    def format_message(self) -> str:
        return self.message

    def show(self, file: IO[Any] | None = None) -> None:
        # Stripped like any other output, and already masked by the constructor. The message
        # carries a name someone typed and a library message that can quote what a provider
        # returned, and this is the last path that reaches a terminal.
        click.echo(f"ERROR: {self.code} {printable(self.message)}", err=True)

    def envelope(self) -> dict[str, Any]:
        """``detail`` is an object or ``null``, and is always present."""
        return {"error": {"code": self.code, "message": self.message, "detail": self.detail}}


def _masked_detail(detail: dict[str, Any] | None) -> dict[str, Any] | None:
    """Every string in a detail object, masked the way the message already is."""
    if detail is None:
        return None
    return {key: mask(value) if isinstance(value, str) else value for key, value in detail.items()}


def _planning_failure(error: PlanningError) -> CliError:
    record = error.record
    if record.code in _CONFIG_PLANNING_CODES:
        code = CONFIG
    elif record.code in _TRANSPORT_PLANNING_CODES:
        code = TRANSPORT
    else:
        code = PLANNING
    message = f"PlanningError: {record.code.value} ({record.stage.value}): {record.message}"
    if record.suggestion:
        message = f"{message} {record.suggestion}"
    return CliError(
        code,
        message,
        {
            "library_code": record.code.value,
            "category": record.category.value,
            "stage": record.stage.value,
            "retryable": record.retryable,
            "suggestion": record.suggestion,
        },
    )


def failure_for(error: Exception) -> CliError:
    """This CLI's error shape for anything a run raises, wherever it was raised.

    The order matters only where the library's hierarchies overlap: ``PlanningError``,
    ``PipelineError``, ``DiscoveryError`` and ``OperatorSkillLoadError`` are all
    ``ValueError`` subclasses, so each is named rather than caught by a common base.
    """
    if isinstance(error, CliError):
        return error
    if isinstance(error, StoreError):
        return CliError(PROFILE, str(error))
    if isinstance(error, PlanningError):
        return _planning_failure(error)
    if isinstance(error, OperatorSkillLoadError):
        return CliError(
            RESOURCE,
            f"OperatorSkillLoadError: {error.code.value}: {error}",
            {"library_code": error.code.value},
        )
    if isinstance(error, (ResolveError, DiscoveryError, PipelineError)):
        return CliError(
            REQUEST,
            f"{type(error).__name__}: {error}",
            {"library_code": _library_code(error)},
        )
    # Everything this CLI has not classified. Left to the interpreter it printed the whole
    # chain, provider SDK frames included, on a path that has no `--log` to ask for that;
    # the type name says what happened and the traceback stays behind --log.
    return CliError(INTERNAL, f"{type(error).__name__}: {error}")


def recoverable_notices(errors: Sequence[ErrorRecord]) -> list[str]:
    """One line per record the run worked around, for standard error.

    ``execution_failure`` drops ``RECOVERABLE`` records because they do not move the exit
    code, and that is right. Dropping them from the output as well is not: under ``table``
    the caller then sees an empty bundle, exit 0, and no reason for either, while the same
    run under ``json`` carries the record and its suggestion. A record the run worked
    around is a warning, and warnings go to standard error like every other one.
    """
    lines: list[str] = []
    for record in errors:
        if record.category is not ErrorCategory.RECOVERABLE:
            continue
        line = (
            f"{record.code.value} ({record.stage.value}) in {record.operator_id}: {record.message}"
        )
        if record.suggestion:
            line = f"{line} {record.suggestion}"
        lines.append(line)
    return lines


def execution_failure(errors: Sequence[ErrorRecord]) -> CliError | None:
    """The CLI error for a run whose failure came back as data rather than as an exception.

    ``Operator.run()`` returns its failures in ``ExecMeta.errors`` instead of raising, so the
    boundary that classifies exceptions never sees them. A ``RECOVERABLE`` record is not a
    failed run: the operator reported something it worked around, and the output beside it
    is usable, so it does not move the exit code.
    """
    failed = [record for record in errors if record.category is not ErrorCategory.RECOVERABLE]
    if not failed:
        return None
    first = failed[0]
    code = TIMEOUT if first.category is ErrorCategory.TIMEOUT else EXECUTION
    message = f"{first.code.value} ({first.stage.value}) in {first.operator_id}: {first.message}"
    if first.suggestion:
        message = f"{message} {first.suggestion}"
    return CliError(
        code,
        message,
        {
            "library_code": first.code.value,
            "category": first.category.value,
            "operator_id": first.operator_id,
            "stage": first.stage.value,
            "retryable": first.retryable,
            "suggestion": first.suggestion,
        },
    )


def as_usage(error: click.UsageError, hint: str = "") -> CliError:
    """A Click parse failure in this CLI's own error shape.

    This is the one failure outside the JSON error contract, and the boundary is the parse
    itself: until Click has read the arguments there is no ``--format`` to honour, so a
    parse failure is always plain text on stderr and always exit 2. Everything the CLI does
    after that — including the root callback's own work, which :func:`start` re-raises from
    inside the command body — is published in the requested format. A machine consumer
    wanting structured errors for bad flags validates its own flags; a CLI cannot do that
    for them without reimplementing Click's parser.
    """
    where = f" Try '{error.ctx.command_path} --help'." if error.ctx is not None else ""
    return CliError(USAGE, f"{error.format_message()}{hint}{where}")


class Command(click.Command):
    """A command whose parse failures speak the same error vocabulary as everything else."""

    def make_context(
        self,
        info_name: str | None,
        args: list[str],
        parent: click.Context | None = None,
        **extra: Any,
    ) -> click.Context:
        try:
            return super().make_context(info_name, args, parent, **extra)
        except click.UsageError as error:
            raise as_usage(error, self.usage_hint(error)) from None

    def usage_hint(self, error: click.UsageError) -> str:
        """Extra guidance for a parse failure. Empty unless a subclass knows better."""
        return ""


class Group(click.Group):
    """The same, for a group and for the subcommands and subgroups it creates."""

    command_class = Command
    # `type` means "the class of the group this was created from", so every level down the
    # tree keeps the error shape without being told to.
    group_class = type

    def make_context(
        self,
        info_name: str | None,
        args: list[str],
        parent: click.Context | None = None,
        **extra: Any,
    ) -> click.Context:
        try:
            return super().make_context(info_name, args, parent, **extra)
        except click.UsageError as error:
            raise as_usage(error) from None

    def invoke(self, ctx: click.Context) -> Any:
        try:
            return super().invoke(ctx)
        except click.UsageError as error:
            raise as_usage(error) from None


class Output:
    """The format an error is published in, which the run refines as it learns it.

    A command knows three things about its format at three different moments: what
    ``--format`` said, which Click has parsed before the body starts; what the profile's
    ``BLUE_DATA_CLI_FORMAT`` says, which needs the store read; and nothing at all, if
    reading the store is what failed. Holding it in one mutable object is what lets the
    prologue publish a failure in the best format known when it happens rather than in the
    one it was going to use.
    """

    def __init__(self, requested: str | None = None) -> None:
        self.requested = requested
        self.value = requested or "table"

    def resolve(self, resolver: ConfigResolver) -> str:
        """Settle on the profile's default where no flag was given, and record it."""
        self.value = resolve_format(resolver, self.requested)
        return self.value


def start(obj: Mapping[str, Any]) -> ConfigResolver:
    """Raise what the root callback could not, and hand over the resolver it built.

    The callback runs before Click has parsed the subcommand's arguments, so a failure
    reported from there has no ``--format`` to honour. It holds the failure instead, and
    every command raises it here — first thing, inside the reporting context — where the
    requested format is known.
    """
    failure = obj.get("failure")
    if isinstance(failure, CliError):
        raise failure
    return cast("ConfigResolver", obj["config"])


@contextlib.contextmanager
def reporting(fmt: str | Output, log: bool = False) -> Generator[None, None, None]:
    """Turn what a command body raises into this CLI's error contract.

    Under ``--format json`` the error is also written to stdout as
    ``{"error": {"code": ..., "message": ..., "detail": ...}}``, so a machine consumer
    reading stdout gets an object either way. Click prints the stderr line regardless.
    """
    published = fmt if isinstance(fmt, Output) else Output(fmt)
    try:
        yield
    except CliError as error:
        if log:
            _trace()
        _publish(published.value, error)
        raise
    except (click.Abort, click.exceptions.Exit, click.ClickException):
        # Click's own control flow: an abort, an early exit, and a parse failure the group
        # converts to this CLI's shape one level up. None of them is a failure to report.
        raise
    except Exception as error:
        failure = failure_for(error)
        if log:
            _trace()
        _publish(published.value, failure)
        raise failure from None


def _trace() -> None:
    """The failing traceback on stderr, masked.

    Formatted and then written rather than handed to ``traceback.print_exc``, which writes
    straight to the stream: these frames quote a provider SDK's own exception, and this is
    the one output path where nothing else stands between that text and the terminal.
    """
    if sys.exc_info()[0] is None:
        return
    click.echo(mask(traceback.format_exc()), err=True, nl=False)


def _publish(fmt: str, error: CliError) -> None:
    if fmt == "json":
        click.echo(json.dumps(error.envelope(), indent=2))


# ---------------------------------------------------------------- the tiers --
class Settings:
    """What this invocation resolved and passed to the library, and where each came from.

    Its scope is exactly that, and no more. It is **not** a report of the library's
    effective configuration: an operator resolves defaults, attributes and call properties
    in its own order, and claiming to report that would be claiming knowledge the CLI does
    not have. What the CLI knows is what it was given and what it passed on.

    Keys are the library's own dotted property names, so the same spelling appears in the
    CLI, in the profile file and in the MCP schema.
    """

    def __init__(self, resolver: ConfigResolver) -> None:
        self._resolver = resolver
        self.applied: dict[str, Any] = {}
        self.source: dict[str, str] = {}

    def take(self, key: str, option: Any, parameter: str | None = None) -> Any:
        """The winning value for *key*, recorded with its tier.

        A command option wins outright, because it never reaches the resolver: that is the
        top of the precedence chain and the reason ``profile inspect`` cannot report a
        ``flag`` tier. A property this invocation did not set is recorded nowhere.
        """
        if option is not None:
            self.applied[key] = option
            self.source[key] = "flag"
            return option
        if parameter is None:
            return None
        found = self._resolver.resolve(parameter)
        if found.value is None:
            return None
        self.applied[key] = found.value
        self.source[key] = found.source
        return found.value

    def envelope(self) -> dict[str, Any]:
        return {
            "applied": {key: _published(key, value) for key, value in self.applied.items()},
            "source": dict(self.source),
        }

    def footer(self) -> str:
        pairs = ", ".join(
            f"{key}={_published(key, self.applied[key])} ({self.source[key]})"
            for key in sorted(self.applied)
        )
        return f"settings: {pairs}" if pairs else "settings: (none)"


MASKED_SETTINGS = frozenset({"openai.model"})
"""Applied settings whose value is masked wherever the envelope is published.

The model name only. It is the setting a deployment is most likely to paste a credential
into by accident, and it is echoed back in the default table footer, which is the most
visible line this CLI prints. Nothing else is masked, because the rule reads shape and a
path is high-entropy by construction: masking a file path would turn an ordinary directory
into ``***``, which is the footer failing at the one thing it is for.
"""


def _published(key: str, value: Any) -> Any:
    """One applied value as it may leave.

    Masked where the envelope is published rather than where the value is taken, so what
    reaches the library stays exactly what the caller asked for.
    """
    return mask(value) if key in MASKED_SETTINGS and isinstance(value, str) else value


# -------------------------------------------------------------- the streams --
def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(limit - 3, 0)] + "..."


class Reporter:
    """Everything that is not the result: the spinner, the log lines, the warnings.

    All of it on stderr, so every format is safe to pipe. The spinner is suppressed outright
    under ``json`` rather than left to Rich's own terminal detection, because a detection
    that guesses wrong corrupts the one format whose whole point is that it does not have
    to be parsed out of a terminal transcript.
    """

    def __init__(self, fmt: str = "table", log: bool = False, log_limit: int = 80) -> None:
        self.console = Console(stderr=True, markup=False, highlight=False)
        self.machine_readable = fmt == "json"
        self.log = log
        self.log_limit = log_limit

    def status(self, label: str) -> Any:
        if self.machine_readable or not self.console.is_terminal:
            return contextlib.nullcontext()
        return self.console.status(label)

    def line(self, text: str) -> None:
        """One step of this run, under ``--log``."""
        if self.log:
            # Stripped and masked like any other cell. A log line carries what the user typed
            # and what the library reported, and it is the one output path that would
            # otherwise reach a terminal unsanitised. Masked before the truncation, not
            # after: cutting a value in half leaves a fragment that matches nothing.
            self.console.print(
                printable(truncate(mask(text), self.log_limit)), style="dim", soft_wrap=True
            )

    def note(self, text: str) -> None:
        """A resolution note: which id a bare name resolved to, which registry was built."""
        self.console.print(printable(mask(text)), style="dim", soft_wrap=True)

    def warn(self, text: str) -> None:
        self.console.print(printable(mask(text)), style="yellow", soft_wrap=True)


# ------------------------------------------------------------ shared options --
def format_option(command: Any) -> Any:
    """``--format``, declared once rather than on every command that returns a result.

    Every one of them carries it and every one of them accepts all three values. Declaring
    the option per command is how a CLI ends up with a format one command has never heard of.
    """
    return click.option(
        "--format",
        "output_format",
        type=click.Choice(FORMATS),
        default=None,
        show_default="the profile's BLUE_DATA_CLI_FORMAT, else table",
        help="Output format.",
    )(command)


CATALOGS = ("active", "history")
"""The two views this CLI exposes. ``raw`` is deliberately not one of them; see below."""

_RAW_REFUSAL = (
    "the raw view is not exposed: its cards carry no tags and no when_to_invoke, and core "
    "3.x rejects every one of them as planning authority. Use 'active' for the reviewed "
    "cards, or 'history' for every retained version."
)


if TYPE_CHECKING:
    # Click made `Choice` generic after 8.1, and the floor declared here is 8.0, so the
    # parameter is written for the checker while the runtime base stays unsubscripted.
    _ChoiceBase = click.Choice[str]
else:
    _ChoiceBase = click.Choice


class CatalogChoice(_ChoiceBase):
    """``--catalog``'s type, with a real answer for the view that is not offered.

    ``raw`` is a name a reader of the library's own documentation will try, and Click's
    unknown-value message would send them looking for a typo instead of telling them the
    view exists and why it is not here.
    """

    def __init__(self) -> None:
        super().__init__(CATALOGS)

    def convert(self, value: Any, param: click.Parameter | None, ctx: click.Context | None) -> str:
        if isinstance(value, str) and value.strip().lower() == "raw":
            self.fail(_RAW_REFUSAL, param, ctx)
        return str(super().convert(value, param, ctx))


def catalog_option(command: Any) -> Any:
    """``--catalog``, declared once, on every command that reads the operator catalog."""
    return click.option(
        "--catalog",
        "catalog_name",
        type=CatalogChoice(),
        default=None,
        show_default="the profile's selection, else active",
        help="Catalog view to read.",
    )(command)


def log_options(command: Any) -> Any:
    """``--log`` and ``--log-limit``, which are never useful one without the other."""
    command = click.option(
        "--log-limit",
        "log_limit",
        type=int,
        default=None,
        show_default="the profile's BLUE_DATA_CLI_LOG_LIMIT, else 80",
        help="Most characters per log line.",
    )(command)
    return click.option(
        "--log",
        "log",
        is_flag=True,
        default=False,
        help="Write each step of the run to standard error, and a traceback if it fails.",
    )(command)


def confirm_option(command: Any) -> Any:
    """``--confirm``, the same flag with the same meaning on every destructive command."""
    return click.option(
        "--confirm",
        is_flag=True,
        default=False,
        help="Skip the confirmation prompt.",
    )(command)


# ----------------------------------------------------------- the resolutions --
def resolve_format(resolver: ConfigResolver, option: str | None) -> str:
    """The flag, else the profile's ``BLUE_DATA_CLI_FORMAT``, else ``table``."""
    if option:
        return option
    configured = _resolved(resolver, "BLUE_DATA_CLI_FORMAT")
    if not configured:
        return "table"
    if configured not in FORMATS:
        raise CliError(
            PROFILE,
            f"BLUE_DATA_CLI_FORMAT is {configured!r}; expected one of {', '.join(FORMATS)}",
        )
    return str(configured)


def resolve_log_limit(resolver: ConfigResolver, option: int | None) -> int:
    """The flag, else the profile's ``BLUE_DATA_CLI_LOG_LIMIT``, else 80.

    ``is None`` rather than a truth test: a configured ``0`` is a limit of zero, and reading
    it as "unset" would give the same value two meanings depending on which tier supplied it.
    """
    if option is not None:
        return option
    configured = _resolved(resolver, "BLUE_DATA_CLI_LOG_LIMIT")
    return 80 if configured is None else int(configured)


def resolve_catalog(resolver: ConfigResolver, option: str | None) -> str:
    """``--catalog`` > ``BLUE_DATA_OPS_CATALOG`` > the profile's selection > ``active``.

    The stored selection sits below the parameter rather than beside it, because the
    parameter is reachable from the environment and the selection is not, and the chain has
    to keep the environment above the profile wherever both can answer.
    """
    if option:
        return option
    resolved = resolver.resolve("BLUE_DATA_OPS_CATALOG")
    if resolved.source != "default":
        return _checked_catalog(resolved.value, "BLUE_DATA_OPS_CATALOG")
    try:
        selected = resolver.store.read_selection(resolver.profile, "catalog")
    except StoreError as error:
        raise CliError(PROFILE, str(error)) from None
    if selected:
        return _checked_catalog(selected, f"{resolver.profile}/.selected.catalog")
    return _checked_catalog(resolved.value, "BLUE_DATA_OPS_CATALOG")


def _checked_catalog(value: Any, where: str) -> str:
    name = str(value).strip()
    if name.lower() == "raw":
        raise CliError(CONFIG, f"{where} names the raw view, and {_RAW_REFUSAL}")
    if name not in CATALOGS:
        raise CliError(
            CONFIG,
            f"{where} is {name!r}; expected one of {', '.join(CATALOGS)}",
        )
    return name


def _resolved(resolver: ConfigResolver, parameter: str) -> Any:
    """One parameter, with a cast failure reported rather than raised as a traceback.

    These are read before the reporting context exists, because they decide what that
    context is, so they carry their own handler.
    """
    try:
        return resolver.get(parameter)
    except StoreError as error:
        raise CliError(PROFILE, str(error)) from None


# ----------------------------------------------------------------- the home --
def cli_home() -> str:
    """Where this CLI keeps its own state: the profiles, the selections, the pipelines.

    Deliberately not a profile parameter — it is the directory the profiles themselves are
    read from, so it can only come from the environment.
    """
    configured = os.environ.get(HOME_VARIABLE)
    if configured is not None and not configured.strip():
        # `Path("")` is the working directory, so an empty export quietly moved the whole
        # profile store to wherever the command was run from and wrote a `.profiles` there.
        raise CliError(
            PROFILE,
            f"{HOME_VARIABLE} is exported with an empty value, which would put the profile "
            f"store in the working directory. Unset it, or give it a path.",
        )
    return str(Path(configured or CLI_HOME_DEFAULT).expanduser())


def cli_version() -> str:
    """The version ``--version`` prints.

    The installed distribution is the truth where there is one. A source checkout has no
    distribution to ask and the package literal is what the build reads, so the two agree by
    construction, and a test pins both against ``pyproject.toml``.
    """
    try:
        return metadata.version(DISTRIBUTION)
    except metadata.PackageNotFoundError:
        return __version__


# -------------------------------------------------------------- the catalog --
def build_catalog(name: str) -> OperatorRegistry:
    """The registry behind a catalog view name.

    Tests replace this to hand a command a small registry, which is the only seam they need.
    """
    if name == "history":
        return versioned_registry()
    if name == "active":
        return active_registry()
    raise CliError(CONFIG, f"unknown catalog {name!r}; expected one of {', '.join(CATALOGS)}")


DATA_REGISTRY_TAG = "requires-data-registry"
"""The tag that says an operator reaches the ``blue-data`` registry to do its work."""


def requires_data_registry(card: OperatorCard) -> bool:
    return DATA_REGISTRY_TAG in card.tags


def registry_backend() -> str:
    """Which ``blue-data`` backend ``BLUE_DATA_REGISTRY_STORE`` currently names."""
    return (os.environ.get("BLUE_DATA_REGISTRY_STORE") or "memory").strip().lower()


def registry_is_ephemeral() -> bool:
    """Whether anything written to the registry dies with the process.

    The in-memory backend is the default, and for a CLI it means ``create_database`` creates
    a database and then loses it. Worth one line on stderr rather than a surprise.
    """
    return registry_backend() == "memory"


def build_registry_seam() -> RegistrySeam:
    """The ``blue-data`` registry this CLI hands to an operator that needs one.

    Built from the same environment ``blue-data``'s own CLI reads, through the same five
    ``blue_data.config`` helpers, so the same variables produce the same registry in both.
    The library's own ``resolve_registry`` would otherwise construct a per-call in-memory
    registry from two naming keys and discard it when the process exits, which is useless
    here.

    Construction is lazy and tag-driven: nothing calls this until a resolved card carries
    ``requires-data-registry``. ``blue-data`` ships no ``py.typed``, so the five imports are
    untyped at this boundary and stop here rather than in every caller.
    """
    from blue_data.config import (  # pyright: ignore[reportMissingTypeStubs]
        build_enricher,
        build_hybrid_config,  # pyright: ignore[reportUnknownVariableType]
        build_store,
        get_vector_dim,
        load_sources,  # pyright: ignore[reportUnknownVariableType]
    )
    from blue_data.registry.data_registry import (  # pyright: ignore[reportMissingTypeStubs]
        DataRegistry,
    )

    registry: Any = DataRegistry(
        store=build_store(),
        metadata_enricher=build_enricher(),
        hybrid_config=build_hybrid_config(),
        vector_dim=get_vector_dim(),
    )
    load_sources(registry)
    return RegistrySeam(registry)
