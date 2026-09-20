"""The profile and configuration engine, as a local stand-in for ``blue_data.utils.config``.

Every Blue CLI in the family sits on one shared engine — ``ProfileStore``,
``ConfigResolver``, ``base_spec``, ``load_spec``, ``MASK``, ``encode`` and ``display`` —
imported from ``blue_data.utils.config``. That module is not in the pinned ``blue-data``
release this repository depends on, and reimplementing the family's configuration story per
CLI is how three CLIs end up with three precedence orders. So the names here are the
engine's names, with the behaviour the family's ``profile.py`` depends on, and
``profile.py`` imports them from here. When the shared engine ships, this module is deleted
and the import at the top of ``profile.py`` changes to point at it — that swap is the whole
point of the naming, and anything added here has to keep it possible.

What the engine owns: the parameter spec and its casts, the ``.profiles`` file and the
selections beside and below it, the precedence chain below the command line, and the on-disk
form of a secret. What it does not own: any Click, any output, any of this CLI's own
vocabulary.

**Errors.** Two, and neither is named ``ConfigError``. This CLI reports a configuration
value the *library* refused as ``ERROR: CONFIG``, and a second exception class carrying that
name, reachable from the same handler, is how a handler ends up catching the wrong failure.
Here, :class:`ProfileError` is a profile operation that could not be carried out — no such
profile, one that already exists, a store that cannot be read — and :class:`SettingError` is
a parameter one: an unknown name, or a value that will not cast. The CLI reports both as
``ERROR: PROFILE``.

**Blank values.** A setting that is present but empty is refused at both ends rather than
read as absent. On disk it stores, reports success and is then skipped by every read; in the
environment it wins its tier and then hands the answer down to the profile. Both are the
same silence, and the whole point of a precedence chain is that the tier that answered is
the tier that had something to say.

**Storage.** ``~/.blue-ops`` is created at mode 0700 and every file in it at 0600, because a
profile can hold a provider credential. Every write goes to a temporary file in the same
directory, is flushed and fsynced, and is moved into place with ``os.replace``: a partial
write must never leave a profiles file a later run cannot parse. A complete write must not
either, which is why a value holding a line break is refused rather than stored — the
profiles file is line-oriented, and configparser escapes a newline on the way out but not a
carriage return, so one pasted from a CRLF file came back as a second setting.

Nothing inside the home is reached by name twice. The home is opened once, each directory
below it is opened from the one above with ``O_NOFOLLOW``, and every read, write, creation
and removal is then performed against that descriptor. Checking a path and handing the same
string to the next syscall asks the kernel to look it up again, and a directory swapped for
a link between the two answers is followed — which is why this is a walk rather than a
check. :class:`HomeDir` holds an opened directory and :func:`home_directory` and
:func:`made_directory` are how one is reached. A name below the home may still point
somewhere else below the home; that link is followed by walking to where it lands, not by
handing its own name back.

An existing path whose mode is wider than the above is reported once. The directory is then
left exactly as found; a file is rewritten at 0600 by the next write, because the write goes
through a fresh temporary file and installs its mode with it. Both are said in the warning,
because narrowing a file the user widened on purpose is a surprise worth naming.
"""

from __future__ import annotations

import base64
import binascii
import configparser
import contextlib
import errno
import io
import json
import os
import re
import secrets
import stat
import sys
from collections.abc import Generator, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, cast

__all__ = [
    "DEFAULT_PROFILE",
    "MASK",
    "ConfigResolver",
    "HomeDir",
    "Parameter",
    "ProfileError",
    "ProfileStore",
    "SettingError",
    "Spec",
    "StoreError",
    "base_spec",
    "decode",
    "display",
    "encode",
    "home_directory",
    "load_spec",
    "made_directory",
]

DEFAULT_PROFILE = "default"
"""Created and selected on a first run, and the fallback when a selection disappears."""

MASK = "***"
"""What a secret's value looks like anywhere it is printed."""

_ENCODED_PREFIX = "enc:"
_DIR_MODE = 0o700
_FILE_MODE = 0o600


# ------------------------------------------------------------------ errors --
class StoreError(Exception):
    """Base for the two failures this module reports."""


class ProfileError(StoreError):
    """A profile operation could not be carried out."""


class SettingError(StoreError):
    """A configuration parameter is unknown, or its value will not cast.

    The family engine calls this one ``ConfigError``. Renamed here because this CLI already
    publishes ``ERROR: CONFIG`` for a value the *library* refused, and the two are reachable
    from the same handler.
    """


# -------------------------------------------------------------- parameters --
def _cast_bool(name: str, value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise SettingError(f"{name} must be true or false, got {value!r}")


def _cast_int(name: str, value: object) -> int:
    if isinstance(value, bool):
        raise SettingError(f"{name} must be a whole number, got {value!r}")
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except ValueError:
        raise SettingError(f"{name} must be a whole number, got {value!r}") from None


def _cast_float(name: str, value: object) -> float:
    if isinstance(value, bool):
        raise SettingError(f"{name} must be a number, got {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        raise SettingError(f"{name} must be a number, got {value!r}") from None


def _cast_path(name: str, value: object) -> str:
    text = str(value).strip()
    if not text:
        raise SettingError(f"{name} must be a path")
    return str(Path(text).expanduser())


CASTS = ("str", "secret", "int", "float", "bool", "directory", "file")
"""Every cast a spec may declare. An unlisted one is a spec that will not load."""


@dataclass(frozen=True)
class Parameter:
    """One configuration parameter. Its name is also its environment variable's name."""

    name: str
    default: Any = None
    prompt: str = ""
    required: bool = False
    cast: str = "str"
    inherits: tuple[str, ...] = ()

    @property
    def is_secret(self) -> bool:
        return self.cast == "secret"

    def cast_value(self, value: object) -> Any:
        """*value* as this parameter's declared type, or a :class:`SettingError` naming it.

        Accepts a value that is already the right type, because a spec's own default
        arrives from JSON as an ``int`` or a ``bool`` rather than as text.
        """
        if value is None:
            return None
        if self.cast == "int":
            return _cast_int(self.name, value)
        if self.cast == "float":
            return _cast_float(self.name, value)
        if self.cast == "bool":
            return _cast_bool(self.name, value)
        if self.cast in {"directory", "file"}:
            return _cast_path(self.name, value)
        return str(value)


class Spec:
    """The parameters one CLI knows about, in declaration order."""

    def __init__(self, parameters: Iterable[Parameter] = ()) -> None:
        self._parameters: dict[str, Parameter] = {p.name: p for p in parameters}

    def __iter__(self) -> Iterator[Parameter]:
        return iter(self._parameters.values())

    def __len__(self) -> int:
        return len(self._parameters)

    def __contains__(self, name: object) -> bool:
        return name in self._parameters

    def __getitem__(self, name: str) -> Parameter:
        try:
            return self._parameters[name]
        except KeyError:
            raise SettingError(f"unknown configuration parameter: {name}") from None

    def names(self) -> tuple[str, ...]:
        return tuple(self._parameters)

    def required(self) -> list[Parameter]:
        """The parameters ``profile config`` walks with no argument.

        Keeping this list short is the difference between a usable first run and an
        interrogation. Nothing in this CLI blocks on one being unset.
        """
        return [p for p in self._parameters.values() if p.required]

    def with_default(self, name: str, default: Any) -> Spec:
        """This spec with one parameter's default replaced.

        For a default that cannot be written in the spec file because it is computed —
        a path under the CLI home, which the environment can move.
        """
        parameters = [
            replace(p, default=default) if p.name == name else p for p in self._parameters.values()
        ]
        return Spec(parameters)

    def merged_with(self, other: Spec) -> Spec:
        """This spec plus *other*'s parameters; a repeated name takes *other*'s."""
        return Spec([*self._parameters.values(), *other])


def base_spec() -> Spec:
    """The family-wide parameters every Blue CLI declares."""
    return Spec(
        [
            Parameter(
                "OPENAI_API_KEY",
                cast="secret",
                required=True,
                prompt="OpenAI API key (the provider SDK reads it from the environment)",
            ),
            Parameter(
                "BLUE_DATA_LLM_MODEL",
                default="gpt-4o",
                required=True,
                prompt="Model the language-model operators call",
            ),
            Parameter(
                "BLUE_DATA_CLI_FORMAT",
                default="table",
                prompt="Default output format: table, json, or nl",
            ),
            Parameter(
                "BLUE_DATA_CLI_LOG_LIMIT",
                default=80,
                cast="int",
                prompt="Most characters per truncated log line",
            ),
        ]
    )


def load_spec(path: str | os.PathLike[str]) -> Spec:
    """One CLI's own parameters, read from a ``profile_spec.json`` beside its ``profile.py``."""
    body = Path(path).read_text(encoding="utf-8")
    loaded: object = json.loads(body)
    if not isinstance(loaded, dict):
        raise SettingError(f"{path} must hold one JSON object of parameters")
    raw = cast("dict[str, Any]", loaded)
    parameters: list[Parameter] = []
    for name, declared in raw.items():
        if not isinstance(declared, dict):
            raise SettingError(f"{path}: parameter {name} must be a JSON object")
        entry = cast("dict[str, Any]", declared)
        declared_cast = str(entry.get("cast", "str"))
        if declared_cast not in CASTS:
            raise SettingError(f"{path}: parameter {name} declares unknown cast {declared_cast!r}")
        inherits: Any = entry.get("inherits") or ()
        parameters.append(
            Parameter(
                name=str(name),
                default=entry.get("default"),
                prompt=str(entry.get("prompt", "")),
                required=bool(entry.get("required", False)),
                cast=declared_cast,
                inherits=tuple(str(item) for item in inherits),
            )
        )
    return Spec(parameters)


# ------------------------------------------------------------------ secrets --
def encode(value: str) -> str:
    """The form a secret takes on disk.

    Obfuscation, not encryption: anyone who can read the file can decode it, and the file
    mode is the real protection. It exists so a credential is not sitting in plain text in a
    file a screen-share or a backup might expose, which is a different and smaller claim.

    A ``$NAME`` reference is stored as written, because the point of a reference is that the
    value is never in the file at all.
    """
    if value.startswith("$"):
        return value
    return _ENCODED_PREFIX + base64.b64encode(value.encode("utf-8")).decode("ascii")


def decode(raw: str) -> str | None:
    """The usable value behind a stored secret, or None when a reference does not resolve."""
    if raw.startswith("$"):
        return os.environ.get(raw[1:]) or None
    if raw.startswith(_ENCODED_PREFIX):
        try:
            return base64.b64decode(raw[len(_ENCODED_PREFIX) :].encode("ascii")).decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError):
            return None
    return raw


def display(raw: str) -> str:
    """A stored secret as it may be shown: masked, or a reference named but not resolved.

    A reference is named because naming the variable is how the user learns what to export;
    whether it currently resolves is the other half of that answer. A directly stored secret
    shows as the mask and nothing else.
    """
    if raw.startswith("$"):
        return f"{raw} ({'set' if os.environ.get(raw[1:]) else 'unset'})"
    return MASK


# ------------------------------------------------------------------ on disk --
_reported_modes: set[str] = set()


def _report_wide_mode(path: Path, mode: int, intended: int, rewritten: bool = False) -> None:
    """Say once that a path is more readable than this CLI would have made it.

    *mode* comes from the descriptor the caller already holds rather than from the name,
    because the name is the part another process gets to change.

    Never widened to match, and never narrowed in silence. A directory is left exactly as
    found. A file is restored to *intended* by the next write, because the write installs a
    fresh temporary file's mode along with its contents — so the warning says which of the
    two is about to happen rather than making one claim for both.
    """
    if not mode & ~intended & 0o777:
        return
    key = str(path)
    if key in _reported_modes:
        return
    _reported_modes.add(key)
    outcome = f"The next write to it restores {intended:04o}." if rewritten else "Left as found."
    sys.stderr.write(
        f"warning: {path} is mode {mode:04o}; this CLI creates it {intended:04o} because a "
        f"profile can hold a provider credential. {outcome}\n"
    )


@contextlib.contextmanager
def _readable(path: Path, doing: str) -> Generator[None, None, None]:
    """Turn a filesystem refusal into this module's own error.

    A directory where a file belongs, a mode that forbids the read, a full disk: none of
    those are this package's exceptions, and none of them should reach a user as a
    traceback. Every command builds a resolver, so an unreadable store takes the whole tree
    down at once.
    """
    try:
        yield
    except OSError as error:
        raise ProfileError(f"cannot {doing} {path}: {error.strerror or error}") from None


# ---------------------------------------------------------- inside the home --
_CLOSE_ON_EXEC = getattr(os, "O_CLOEXEC", 0)
_OPEN_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _CLOSE_ON_EXEC
_OPEN_FILE = os.O_RDONLY | os.O_NOFOLLOW | _CLOSE_ON_EXEC
_NEW_FILE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | _CLOSE_ON_EXEC

_NOT_OPENED = frozenset({errno.ELOOP, errno.EMLINK, errno.ENOTDIR})
"""What an open with ``O_NOFOLLOW`` reports when the name it was given is a symlink.

Three, because the answer is not portable and none of them means only that. A link opened
with ``O_NOFOLLOW`` is ``ELOOP`` on Linux and ``EMLINK`` on some BSDs, and adding
``O_DIRECTORY`` makes macOS answer ``ENOTDIR`` instead — the link itself is not a
directory, and that check runs first. ``ENOTDIR`` is also what an ordinary file where a
directory belongs reports. So the errno only says to go and ask whether the name is a link;
:func:`_link_target` gives the real answer.
"""

_ABSENT = frozenset({errno.ENOENT, errno.ENOTDIR})
"""What an open reports when the directory asked for is not there, or is not a directory."""

_LINK_BUDGET = 8
"""How many links one lookup may pass through before this CLI stops following them."""


def _contained(candidate: Path, root: Path) -> bool:
    """Whether *candidate*, already resolved, is *root* itself or sits under it."""
    return candidate == root or root in candidate.parents


def _escape_reason(path: Path, landing: Path, root: Path) -> str:
    return (
        f"{path} is a symlink that resolves to {landing}, outside {root}. Refusing to "
        f"follow it: the files here are kept at mode 0600 because they can hold a "
        f"credential, and a write out of the home is one this CLI cannot make that promise "
        f"about."
    )


_CLAIM_PREFIX = ".removing-"
_CLAIM_DIGITS = 12
_CLAIMED_NAME = re.compile(rf"\A{re.escape(_CLAIM_PREFIX)}[0-9a-f]{{{_CLAIM_DIGITS}}}\Z")
"""What a directory claimed for removal is called while it is being removed.

A leading dot and a fixed shape, so a claim is out of the way of anything a caller named.
``pipeline.check_name`` refuses a new name starting with a dot for the same reason.

The shape is not evidence. A name is only what somebody typed, and a version of this CLI
that allowed a leading dot could have stored a pipeline called exactly this, so the sweep
reads the record inside the directory instead of believing its name. The one exception is
an entry of this shape holding nothing at all, where there is no work the name could be
wrong about.
"""

_CLAIM_MARKER = ".claim"
_CLAIM_LIMIT = 256
"""The record a claim carries, written inside the claimed directory.

It holds the claimed name, so the record belongs to the entry it stands in rather than to
any directory it might be copied into. A directory without it is somebody's data, whatever
it is called: only this CLI writes it, and it writes it on an entry it has already taken.
An empty one is the exception, and only because it holds no data to be anybody's.
"""


def _claim_name() -> str:
    return f"{_CLAIM_PREFIX}{secrets.token_hex(_CLAIM_DIGITS // 2)}"


def _is_claimed(name: str) -> bool:
    return _CLAIMED_NAME.match(name) is not None


def _claim_record(claimed: str) -> str:
    return f"{claimed}\n"


def _mark_claim(descriptor: int, claimed: str) -> None:
    """Record inside the open directory that this CLI took it to remove it.

    Written after the claim and before anything is emptied, and flushed with the directory
    entry that carries it, so a run that dies while emptying leaves a directory that says
    what it is rather than one that has to be guessed at from its name.
    """
    with contextlib.suppress(OSError):
        os.unlink(_CLAIM_MARKER, dir_fd=descriptor)
    opened = os.open(_CLAIM_MARKER, _NEW_FILE, _FILE_MODE, dir_fd=descriptor)
    with os.fdopen(opened, "w", encoding="utf-8") as stream:
        stream.write(_claim_record(claimed))
        stream.flush()
        os.fsync(stream.fileno())
    os.fsync(descriptor)


def _claim_told(descriptor: int) -> str | None:
    """What the claim record in the open directory says, or ``None`` where there is none."""
    try:
        opened = os.open(_CLAIM_MARKER, _OPEN_FILE, dir_fd=descriptor)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(opened).st_mode):
            return None
        return os.read(opened, _CLAIM_LIMIT).decode("utf-8", "replace")
    except OSError:
        return None
    finally:
        os.close(opened)


def _report_unrecorded_claim(path: Path) -> None:
    sys.stderr.write(
        f"warning: {path} is named like a removal this CLI left unfinished but holds no "
        f"record of one, so it is left exactly as it is. A pipeline stored under that name "
        f"is still listed and can still be removed by name; anything else is yours to "
        f"delete.\n"
    )


def _still_the_same(directory: int, name: str, opened: int, shown: Path) -> None:
    """Refuse to go on unless *name* still holds the directory *opened* refers to.

    ``rmdir`` takes a name, and there is no call that takes a descriptor instead, so the
    last step of a removal is the one step that cannot be bound to the directory the rest
    of it worked on. Comparing the entry against the open descriptor turns a directory that
    took the name in the meantime into a refusal rather than into a deletion.
    """
    held = os.fstat(opened)
    try:
        entry = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except OSError:
        raise ProfileError(f"{shown} went away while it was being emptied") from None
    if (entry.st_dev, entry.st_ino) != (held.st_dev, held.st_ino):
        raise ProfileError(
            f"{shown} was replaced while it was being emptied, so whatever stands there now "
            f"is not what was asked for. Nothing further is removed."
        )


def _mode_of(descriptor: int) -> int:
    return stat.S_IMODE(os.fstat(descriptor).st_mode)


def _link_target(descriptor: int, name: str) -> str | None:
    """What the link called *name* holds, or ``None`` where *name* is not a link."""
    try:
        return os.readlink(name, dir_fd=descriptor)
    except OSError:
        return None


def _landing(path: Path, root: Path, name: str, target: str, links: int) -> tuple[str, ...]:
    """Where the link called *name* lands, as the components below the home.

    Those components are what the caller walks next. Reading the link and then handing its
    own name back to the kernel would be the two lookups this module exists to avoid, so a
    link inside the home is followed by walking to where it lands rather than through it.
    """
    shown = path / name
    if links >= _LINK_BUDGET:
        raise ProfileError(f"{shown} leads through more links than this CLI will follow")
    written = Path(target)
    lands = (written if written.is_absolute() else path / written).resolve()
    if not _contained(lands, root):
        raise ProfileError(_escape_reason(shown, lands, root))
    below = lands.relative_to(root).parts
    if not below:
        raise ProfileError(f"{shown} is a symlink to the CLI home itself")
    return below


class HomeDir:
    """One directory inside the CLI home, held open rather than named a second time.

    A path is a request to look a name up *now*. Asking whether
    ``~/.blue-ops/default/pipeline`` is a real directory inside the home and then handing
    the same string to ``os.open`` asks twice, and between the two answers another process
    can put a symlink where the directory was. No amount of checking closes that, because
    the check is not what gets attacked — the second lookup is. ``O_NOFOLLOW`` does not
    close it either: it answers for the last component of a path and says nothing about the
    directories above it.

    So the home is opened once, each directory below it is opened from the one above, and
    every read, write, creation and removal afterwards is performed against the descriptor.
    A descriptor holds the directory it opened. Renaming that directory, or putting a link
    where its name was, changes nothing about what the descriptor refers to, because the
    name is no longer being used.

    A name inside the home may still point at another place inside the home — the rule is
    the boundary, not the spelling. A link is not followed by handing its own name back to
    the kernel: the link is read, where it lands is held to the boundary, and that place is
    then reached by walking from the home again, so every descriptor comes from the same
    component-by-component walk either way.
    """

    def __init__(self, descriptor: int, path: Path, home: Path, root: Path) -> None:
        self.descriptor = descriptor
        self.path = path
        """Where this directory is spelled, for a message. Never used to reach it again."""
        self.home = home
        self.root = root

    # -- reading --
    def entries(self) -> list[str]:
        """Every name this directory holds."""
        return os.listdir(self.descriptor)

    def holds(self, name: str) -> bool:
        """Whether *name* is a regular file in this directory."""
        try:
            info = os.stat(name, dir_fd=self.descriptor, follow_symlinks=False)
        except OSError:
            return False
        return stat.S_ISREG(info.st_mode)

    def read(self, name: str) -> str | None:
        """*name*'s text, or ``None`` where this directory does not hold it."""
        opened = self._open(name, 0)
        if opened is None:
            return None
        descriptor, shown = opened
        with os.fdopen(descriptor, encoding="utf-8") as stream:
            _report_wide_mode(shown, _mode_of(stream.fileno()), _FILE_MODE, rewritten=True)
            return stream.read()

    def _open(self, name: str, links: int) -> tuple[int, Path] | None:
        try:
            return os.open(name, _OPEN_FILE, dir_fd=self.descriptor), self.path / name
        except FileNotFoundError:
            return None
        except OSError as error:
            target = _link_target(self.descriptor, name) if error.errno in _NOT_OPENED else None
            if target is None:
                raise
        below = _landing(self.path, self.root, name, target, links)
        with home_directory(self.home, below[:-1]) as directory:
            if directory is None:
                return None
            return directory._open(below[-1], links + 1)

    # -- writing --
    def write(self, name: str, text: str) -> None:
        """Replace *name*'s contents here, or leave them exactly as they were.

        The text goes to a temporary file in this same directory, is flushed and fsynced,
        and takes the name in one step, so an interrupted write cannot leave a file the
        next run refuses to parse. Both halves go through this directory's descriptor, and
        ``os.replace`` moves a name inside the directory it was handed rather than
        following what the name currently points at.

        What it does not promise is that a write which returned has reached the disk. The
        contents are flushed and the entry naming them is not, so a power loss straight
        afterwards leaves either the old file or the new one, never a torn one. A removal
        does flush its entry, because the half-finished state there is somebody's pipeline
        partly gone under the name they still trust, and a setting that reverted is only a
        setting that reverted.
        """
        temporary = f"{name}.{secrets.token_hex(6)}.tmp"
        descriptor = os.open(temporary, _NEW_FILE, _FILE_MODE, dir_fd=self.descriptor)
        try:
            # Set rather than left to the open, which applies the ambient umask to it.
            os.fchmod(descriptor, _FILE_MODE)
            stream = os.fdopen(descriptor, "w", encoding="utf-8")
        except BaseException:
            os.close(descriptor)
            self._discard(temporary)
            raise
        try:
            with stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, name, src_dir_fd=self.descriptor, dst_dir_fd=self.descriptor)
        except BaseException:
            self._discard(temporary)
            raise

    def _discard(self, name: str) -> None:
        with contextlib.suppress(OSError):
            os.unlink(name, dir_fd=self.descriptor)

    # -- removing --
    def remove_tree(self, name: str) -> None:
        """Delete the directory *name* holds, and everything under it.

        *name* is claimed before anything is opened: one ``rename`` inside this directory
        moves it to a private name, and everything after that works on the private name.
        Emptying a directory takes as long as it takes, and the entry that was emptied has
        to be the entry that is then removed — a name still in use is a name that can be
        given to another directory while the first one is being emptied, and ``rmdir``
        would delete the second. The claim is one syscall with nothing looked up before it,
        so there is no gap between deciding which entry to take and taking it.

        A link at the root of the removal is refused rather than followed: following it
        would empty a directory somewhere else and leave the link standing. That answer is
        given before the claim, so an ordinary link is not moved in order to be refused.

        The rename is flushed before anything below is unlinked. It changed *this*
        directory's namespace, and flushing the claimed directory does not flush the entry
        that names it, so a power loss with the rename still in memory and the first
        unlinks already on disk can bring back the caller's own name over contents that
        are half gone. That is worse than either whole answer, and the entry that has to
        be on disk first is the one whose namespace moved.

        The claimed directory then records that it was claimed, before a single entry is
        unlinked. Nothing is emptied until that record is on disk, so an interrupted
        removal leaves a directory that says what it is; one that cannot record it is put
        back under the name it came from and left alone.
        """
        if _link_target(self.descriptor, name) is not None:
            raise ProfileError(self._link_at_the_root(name))
        claimed = _claim_name()
        os.rename(name, claimed, src_dir_fd=self.descriptor, dst_dir_fd=self.descriptor)
        try:
            os.fsync(self.descriptor)
        except OSError as error:
            self._put_back(claimed, name)
            raise ProfileError(
                f"{self.path / name} could not be claimed for removal "
                f"({error.strerror or error}), so nothing was removed."
            ) from None
        try:
            descriptor = os.open(claimed, _OPEN_DIRECTORY, dir_fd=self.descriptor)
        except OSError as error:
            # Claimed between the answer above and the rename, so put it back untouched.
            self._put_back(claimed, name)
            if error.errno in _NOT_OPENED:
                raise ProfileError(self._link_at_the_root(name)) from None
            raise
        try:
            _mark_claim(descriptor, claimed)
        except OSError as error:
            os.close(descriptor)
            self._put_back(claimed, name)
            raise ProfileError(
                f"{self.path / name} could not be marked for removal "
                f"({error.strerror or error}), so nothing was removed."
            ) from None
        self._empty_and_remove(descriptor, claimed, self.path / name)

    def _put_back(self, claimed: str, name: str) -> None:
        with contextlib.suppress(OSError):
            os.rename(claimed, name, src_dir_fd=self.descriptor, dst_dir_fd=self.descriptor)

    def finish_removals(self) -> None:
        """Finish a removal an earlier run did not reach the end of.

        A run that dies after the claim and before the last ``rmdir`` leaves a directory
        under the private name and nothing under the one the caller asked about, so the
        pipeline is already gone as far as any command can tell and what is left is its
        contents taking up space under a name nothing reaches. The next command that opens
        this directory finishes it rather than listing it or leaving it to accumulate.

        What it finishes is decided by the record inside the entry, never by its name. A
        version of this CLI that allowed a leading dot could have stored a pipeline called
        exactly what a claim is called, and deleting it because it is spelled that way
        would take somebody's work on a command that only meant to read. An entry without
        the record is left where it is and said out loud instead. A leftover that cannot be
        removed is left alone too: the command the caller actually ran is not worth failing
        over it.

        One shape is swept without the record: a claim-shaped directory holding nothing at
        all. That is what the last step leaves if a run dies between dropping the record
        and the ``rmdir`` it was dropped for, and it is the only leftover that cannot be
        anybody's work, because there is nothing in it to be anybody's. Warning about it
        on every command until somebody deletes it by hand costs more than the entry is
        worth. An entry holding anything, and an entry that is not a directory, still need
        the record.
        """
        for name in sorted(os.listdir(self.descriptor)):
            if not _is_claimed(name):
                continue
            shown = self.path / name
            descriptor = self._opened_claim(name)
            if descriptor is None:
                _report_unrecorded_claim(shown)
                continue
            if _claim_told(descriptor) != _claim_record(name):
                self._sweep_unrecorded(descriptor, name, shown)
                continue
            with contextlib.suppress(OSError, ProfileError):
                self._empty_and_remove(descriptor, name, shown)

    def _opened_claim(self, claimed: str) -> int | None:
        """The open directory under *claimed*, or ``None`` where it holds something else.

        A claim is always made by renaming a directory, so an entry under that name which
        is not one — a file, a link, nothing at all — is somebody's, however it got there.
        """
        try:
            return os.open(claimed, _OPEN_DIRECTORY, dir_fd=self.descriptor)
        except OSError:
            return None

    def _sweep_unrecorded(self, descriptor: int, claimed: str, shown: Path) -> None:
        """Remove the open directory if it holds nothing, and report it otherwise."""
        try:
            if not self._removed_if_empty(descriptor, claimed, shown):
                _report_unrecorded_claim(shown)
        finally:
            os.close(descriptor)

    def _removed_if_empty(self, descriptor: int, claimed: str, shown: Path) -> bool:
        """Whether the open directory held nothing and was removed.

        The emptiness is the kernel's answer and not this call's: ``rmdir`` refuses a
        directory that gained an entry after the listing, so a file arriving in between
        stops the removal rather than being taken with it. The name is checked against the
        open directory first, as it is everywhere else here, so a directory that took the
        name is not the one removed. Nothing below is opened, unlinked or read on the way.
        """
        try:
            if os.listdir(descriptor):
                return False
            _still_the_same(self.descriptor, claimed, descriptor, shown)
            os.rmdir(claimed, dir_fd=self.descriptor)
            os.fsync(self.descriptor)
        except (OSError, ProfileError):
            return False
        return True

    def _empty_and_remove(self, descriptor: int, claimed: str, shown: Path) -> None:
        """Empty the open directory, check the name still holds it, and remove it.

        The claim record goes last, immediately before the ``rmdir`` that the empty
        directory is now ready for, and goes back if that ``rmdir`` does not happen — so a
        removal that fails at its final step stays a removal the next command finishes.

        The ``rmdir`` is flushed before the call returns, so a removal reported as done is
        done: the entry does not come back after a power loss. The record's own unlink is
        deliberately not flushed ahead of it — a recovery that brings the entry back is
        better off bringing the record with it, and an entry that comes back without one
        comes back empty, which the next command clears.
        """
        try:
            _empty(descriptor, shown, keep=_CLAIM_MARKER)
            _still_the_same(self.descriptor, claimed, descriptor, shown)
            _drop_claim(descriptor)
            try:
                os.rmdir(claimed, dir_fd=self.descriptor)
            except OSError:
                with contextlib.suppress(OSError):
                    _mark_claim(descriptor, claimed)
                raise
            try:
                os.fsync(self.descriptor)
            except OSError as error:
                raise ProfileError(
                    f"{shown} was removed, but this CLI could not confirm the removal "
                    f"reached the disk ({error.strerror or error}). A power loss now could "
                    f"leave an empty directory behind, which the next command clears."
                ) from None
        finally:
            os.close(descriptor)

    def _link_at_the_root(self, name: str) -> str:
        return (
            f"{self.path / name} is a symlink. Removing it would empty the directory "
            f"it points at rather than this one, so it is left alone."
        )


def _drop_claim(descriptor: int) -> None:
    with contextlib.suppress(OSError):
        os.unlink(_CLAIM_MARKER, dir_fd=descriptor)


def _empty(descriptor: int, shown: Path, keep: str | None = None) -> None:
    """Unlink everything the open directory holds, depth first and by descriptor.

    A link met on the way down is unlinked rather than descended into, which is the one
    thing a name-based walk cannot promise. A directory is emptied through its own
    descriptor and then removed by name, and the name is checked against that descriptor
    first, so an entry that changed while it was being emptied stops the removal instead
    of sending it at whatever now answers to the name.

    *keep* is the claim record at the top of a removal, which is left until the directory
    is otherwise empty so that a run dying part way through leaves one that still says what
    it is. It is a file this CLI wrote moments earlier and nothing below the top level is
    ever kept.
    """
    for name in os.listdir(descriptor):
        if name == keep:
            continue
        try:
            child = os.open(name, _OPEN_DIRECTORY, dir_fd=descriptor)
        except OSError as error:
            if error.errno not in _NOT_OPENED:
                raise
            os.unlink(name, dir_fd=descriptor)
            continue
        try:
            _empty(child, shown / name)
            _still_the_same(descriptor, name, child, shown / name)
        finally:
            os.close(child)
        os.rmdir(name, dir_fd=descriptor)


class _Walk:
    """The descriptors one lookup opened, closed together when it is done with them."""

    def __init__(self, home: Path) -> None:
        self.home = home.expanduser()
        self.root = self.home.resolve()
        self.opened: list[int] = []

    def anchor(self, create: bool) -> int:
        """The home itself, opened by the name it was configured with.

        The one name this CLI does follow. It is where the user pointed the store, a home
        under a linked temporary directory is ordinary, and there is no descriptor above it
        to open it from.
        """
        fresh = create and not self.home.exists()
        if fresh:
            self.home.mkdir(_DIR_MODE, parents=True, exist_ok=True)
        descriptor = os.open(str(self.home), os.O_RDONLY | os.O_DIRECTORY | _CLOSE_ON_EXEC)
        self.opened.append(descriptor)
        if fresh:
            os.fchmod(descriptor, _DIR_MODE)
        elif create:
            _report_wide_mode(self.home, _mode_of(descriptor), _DIR_MODE)
        return descriptor

    def keep(self, descriptor: int) -> int:
        self.opened.append(descriptor)
        return descriptor

    def back_to_anchor(self) -> int:
        """Drop everything opened below the home and start the walk again from it."""
        for descriptor in reversed(self.opened[1:]):
            os.close(descriptor)
        del self.opened[1:]
        return self.opened[0]

    def close(self) -> None:
        for descriptor in reversed(self.opened):
            os.close(descriptor)
        self.opened.clear()


@contextlib.contextmanager
def _walked(home: Path, below: Sequence[str], create: bool) -> Generator[HomeDir | None]:
    walk = _Walk(home)
    try:
        try:
            current = walk.anchor(create)
        except FileNotFoundError:
            yield None
            return
        walked = walk.home
        pending = list(below)
        links = 0
        while pending:
            name = pending.pop(0)
            here = walked / name
            try:
                child = walk.keep(os.open(name, _OPEN_DIRECTORY, dir_fd=current))
            except OSError as error:
                target = _link_target(current, name) if error.errno in _NOT_OPENED else None
                if target is not None:
                    pending = [*_landing(walked, walk.root, name, target, links), *pending]
                    links += 1
                    current, walked = walk.back_to_anchor(), walk.root
                    continue
                if error.errno in _ABSENT and not create:
                    yield None
                    return
                if not isinstance(error, FileNotFoundError):
                    raise
                with contextlib.suppress(FileExistsError):
                    os.mkdir(name, _DIR_MODE, dir_fd=current)
                child = walk.keep(os.open(name, _OPEN_DIRECTORY, dir_fd=current))
                # Passed to `mkdir` so the directory is never wider than this even for an
                # instant, and set again because `mkdir` applies the ambient umask to it.
                os.fchmod(child, _DIR_MODE)
                current, walked = child, here
                continue
            if create:
                _report_wide_mode(here, _mode_of(child), _DIR_MODE)
            current, walked = child, here
        yield HomeDir(current, walked, walk.home, walk.root)
    finally:
        walk.close()


@contextlib.contextmanager
def home_directory(home: Path, below: Sequence[str] = ()) -> Generator[HomeDir | None]:
    """``<home>/<below>`` held open, or ``None`` where no such directory is there.

    Each component is opened from the one above with ``O_NOFOLLOW``, so a name below the
    home is looked up once and used through the descriptor that lookup returned. A read
    never creates anything, which is why a missing directory is an answer here rather than
    a failure.
    """
    with _walked(home, below, create=False) as directory:
        yield directory


@contextlib.contextmanager
def made_directory(home: Path, below: Sequence[str] = ()) -> Generator[HomeDir]:
    """``<home>/<below>`` held open, with each missing component created at 0700.

    The same walk as :func:`home_directory`, for the writers. A component is created
    through the descriptor of the directory above it, so a name that appears between the
    creation and the write is a name nothing here goes back to.
    """
    with _walked(home, below, create=True) as directory:
        if directory is None:  # pragma: no cover - a creating walk reaches a directory or raises
            raise ProfileError(f"{home} could not be opened")
        yield directory


class _Ini(configparser.RawConfigParser):
    """Case-preserving and interpolation-free.

    Parameter names are upper case and *are* environment variable names, which the default
    ``optionxform`` would fold to lower case; and a stored value may contain a ``%``, which
    the interpolating parser would try to expand.
    """

    def optionxform(self, optionstr: str) -> str:
        return optionstr


class ProfileStore:
    """The ``.profiles`` file, the selection beside it, and each profile's own directory."""

    def __init__(self, home: str | os.PathLike[str]) -> None:
        self.home = Path(home).expanduser()

    @property
    def profiles_path(self) -> Path:
        return self.home / ".profiles"

    @property
    def selection_path(self) -> Path:
        return self.home / ".selected.profile"

    # -- lifecycle --
    def initialize(self) -> None:
        """Create and select ``default`` on a first run.

        Keyed on the profiles file, so a profile removed on purpose is not resurrected by
        the next command.
        """
        if self._profiles_text() is not None:
            return
        self.add(DEFAULT_PROFILE)
        self.select(DEFAULT_PROFILE)

    # -- reading --
    def list_profiles(self) -> list[str]:
        return self._read().sections()

    def exists(self, name: str) -> bool:
        return self._read().has_section(name)

    def values(self, name: str) -> dict[str, str]:
        ini = self._read()
        if not ini.has_section(name):
            return {}
        return dict(ini.items(name))

    def selected(self) -> str:
        written = self._selection_text()
        name = DEFAULT_PROFILE if written is None else written.strip() or DEFAULT_PROFILE
        # Validated on the way out as well as on the way in: the file is editable by hand,
        # and this name is joined onto the home to reach the profile's own directory.
        self._check_name(name)
        return name

    # -- writing --
    def add(self, name: str) -> None:
        self._check_name(name)
        ini = self._read()
        if ini.has_section(name):
            raise ProfileError(f"profile {name!r} already exists")
        ini.add_section(name)
        self._write(ini)

    def remove(self, name: str) -> None:
        """Delete *name*'s section and nothing else, leaving the selection valid.

        Not that profile's own directory, not another profile's section, and not the
        selection file unless it pointed here — in which case it moves to a profile that
        exists: ``default`` where that survives, otherwise the first one left.

        Which is also why the last profile cannot go. ``default`` was removable while the
        selection fell back to it unconditionally, so removing it left the store reporting
        a selected profile that was not in the list, and every later run resolving against
        a section that was not there. The store holds at least one profile and the
        selection names one of them; that pair is the invariant, and it is cheaper to keep
        than to check for everywhere it would otherwise have to be.
        """
        ini = self._read()
        if not ini.has_section(name):
            raise ProfileError(f"no such profile: {name!r}")
        remaining = [section for section in ini.sections() if section != name]
        if not remaining:
            raise ProfileError(
                f"{name!r} is the only profile, and the selection has to name one that "
                f"exists. Add another profile first, or delete the profiles file to start "
                f"over."
            )
        ini.remove_section(name)
        self._write(ini)
        if self._selection_text() is not None and self.selected() == name:
            self._write_selection(DEFAULT_PROFILE if DEFAULT_PROFILE in remaining else remaining[0])

    def select(self, name: str) -> None:
        if not self.exists(name):
            raise ProfileError(f"no such profile: {name!r}")
        self._write_selection(name)

    def set_value(self, profile: str, name: str, value: str, create: bool = False) -> None:
        """Store one value, in one write.

        *create* adds a missing section as part of that same write. Adding it separately
        first meant a value the file cannot hold was refused with the profile already
        created and empty, so a command that rejected its argument had still changed the
        store.
        """
        self._check_value(name, value)
        ini = self._read()
        if not ini.has_section(profile):
            if not create:
                raise ProfileError(f"no such profile: {profile!r}")
            self._check_name(profile)
            ini.add_section(profile)
        ini.set(profile, name, value)
        self._write(ini)

    # -- the profile's own directory --
    def profile_dir(self, profile: str) -> Path:
        """``~/.blue-ops/<profile>/``, where a per-profile selection or resource lives.

        Not created here, and not how anything reaches it. A read must not make a
        directory, and a writer opens the home and walks down to this one instead of
        handing the path back to the kernel.
        """
        self._check_name(profile)
        return self.home / profile

    def read_selection(self, profile: str, resource: str) -> str | None:
        """``<profile>/.selected.<resource>``, or None where nothing has been selected."""
        path = self._selection_file(profile, resource)
        with _readable(path, "read"), home_directory(self.home, (profile,)) as directory:
            written = None if directory is None else directory.read(path.name)
        return None if written is None else written.strip() or None

    def write_selection(self, profile: str, resource: str, value: str) -> None:
        """Record *value* as this profile's selected *resource*, at mode 0600."""
        path = self._selection_file(profile, resource)
        with _readable(path, "write"), made_directory(self.home, (profile,)) as directory:
            directory.write(path.name, value)

    def _selection_file(self, profile: str, resource: str) -> Path:
        if not resource or not resource.isidentifier():
            raise ProfileError(f"{resource!r} is not a resource name")
        return self.profile_dir(profile) / f".selected.{resource}"

    # -- internals --
    @staticmethod
    def _check_value(name: str, value: str) -> None:
        """Refuse a value the profiles file cannot hold without changing meaning.

        configparser escapes a newline on the way out, by indenting the continuation, and
        does not escape a carriage return; reading the file back translates that return into
        a line break at top level. A value pasted from a CRLF file therefore came back as a
        second setting, and one shaped like INI came back as a second *profile*. A blank
        value is refused for a quieter reason: it stores, reports success, and is then
        skipped by every read, so it silently unsets whatever was there.
        """
        if any(character in value for character in "\r\n"):
            raise SettingError(
                f"{name} cannot hold a line break: the profiles file is line-oriented, and a "
                f"value containing one would be read back as a separate setting"
            )
        if not value.strip():
            raise SettingError(
                f"{name} cannot be set to a blank value: it would be stored and then ignored "
                f"by every read. Edit the profiles file by hand to remove a setting."
            )

    @staticmethod
    def _check_name(name: str) -> None:
        if not name.strip():
            raise ProfileError("a profile name cannot be blank")
        if name != name.strip() or any(c in name for c in "[]\n\r/\\"):
            raise ProfileError(
                f"profile name {name!r} cannot hold brackets, slashes, newlines or padding"
            )
        if name in {".", ".."}:
            raise ProfileError(f"profile name {name!r} is a directory reference")
        if name.upper() == "DEFAULT":
            # configparser's own reserved section name, whose keys leak into every other one.
            if name != DEFAULT_PROFILE:
                raise ProfileError(f"profile name {name!r} is reserved; use 'default'")

    # -- the two files at the top of the home --
    # Each one is read and written through a descriptor for the home itself, so the name
    # is looked up once and the operation happens against what that lookup returned.
    def _profiles_text(self) -> str | None:
        path = self.profiles_path
        with _readable(path, "read"), home_directory(self.home) as directory:
            return None if directory is None else directory.read(path.name)

    def _selection_text(self) -> str | None:
        path = self.selection_path
        with _readable(path, "read"), home_directory(self.home) as directory:
            return None if directory is None else directory.read(path.name)

    def _read(self) -> _Ini:
        ini = _Ini()
        body = self._profiles_text()
        if body is None:
            return ini
        path = self.profiles_path
        try:
            ini.read_string(body, source=str(path))
        except (configparser.Error, UnicodeDecodeError) as error:
            raise ProfileError(f"{path} cannot be read as a profiles file: {error}") from None
        return ini

    def _write(self, ini: _Ini) -> None:
        buffer = io.StringIO()
        ini.write(buffer)
        path = self.profiles_path
        with _readable(path, "write"), made_directory(self.home) as directory:
            directory.write(path.name, buffer.getvalue())

    def _write_selection(self, name: str) -> None:
        path = self.selection_path
        with _readable(path, "write"), made_directory(self.home) as directory:
            directory.write(path.name, name)


# --------------------------------------------------------------- resolution --
@dataclass(frozen=True)
class Resolved:
    """One parameter's winning value and the tier it came from."""

    value: Any
    source: str
    raw: str | None = field(default=None)


ENVIRONMENT = "environment"
DEFAULTED = "default"
UNSET = "unset"


def _refuse_blank_environment(spec: Spec, environment: Mapping[str, str]) -> None:
    """Refuse a parameter exported with nothing in it.

    A precedence chain answers with the first tier that has a value, and a variable exported
    as ``''`` is a tier that has one. Reading it as unset drops the setting to the profile
    without saying so — the same silence the store already refuses at write time, where a
    blank value stores, reports success, and is then ignored by every read. An empty export
    is a state a shell produces easily and never means "use the profile's", so it is
    answered rather than guessed at.
    """
    blank = [p.name for p in spec if p.name in environment and not environment[p.name].strip()]
    if not blank:
        return
    raise SettingError(
        f"exported with an empty value: {', '.join(blank)}. An empty export is not an unset "
        f"one, and reading it as unset would silently hand the setting to the profile. "
        f"Unset the variable, or give it a value."
    )


class ConfigResolver:
    """Environment, then profile, then the spec's default. The command line is above all three.

    A flag never reaches here: the CLI applies it on top of what this returns, which is why
    :meth:`source_of` can report ``environment``, ``profile:<name>`` or ``default`` but
    never ``flag``.

    The environment is snapshotted at construction, before :meth:`export` writes anything
    into it. Resolving against the live environment after an export would attribute a
    profile's own values to the environment tier — the resolver reporting on the exports it
    just made. A second resolver built later in the same run (``profile inspect NAME`` for a
    profile that is not the selected one) is handed the first one's snapshot for the same
    reason.
    """

    def __init__(
        self,
        spec: Spec,
        store: ProfileStore,
        profile: str | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._spec = spec
        self._store = store
        self.profile = profile or store.selected()
        self.environment: Mapping[str, str] = dict(
            environment if environment is not None else os.environ
        )
        _refuse_blank_environment(self._spec, self.environment)
        self._overwritten: dict[str, str | None] = {}
        self._values = store.values(self.profile)

    @property
    def spec(self) -> Spec:
        return self._spec

    @property
    def store(self) -> ProfileStore:
        return self._store

    def profile_values(self) -> dict[str, str]:
        """The profile's stored values, in the form they take on disk."""
        return dict(self._values)

    def resolve(self, name: str) -> Resolved:
        parameter = self._spec[name]
        found = self._lookup(parameter, seen=set())
        if found is not None:
            raw, source = found
            value = decode(raw) if parameter.is_secret else parameter.cast_value(raw)
            return Resolved(value=value, source=source, raw=raw)
        if parameter.default is not None:
            return Resolved(value=parameter.cast_value(parameter.default), source=DEFAULTED)
        return Resolved(value=None, source=UNSET)

    def get(self, name: str) -> Any:
        return self.resolve(name).value

    def source_of(self, name: str) -> str:
        return self.resolve(name).source

    def export(self) -> None:
        """Write the resolved values into ``os.environ``.

        That is where the provider SDK, ``blue_data.config`` and any remaining ``envvar=``
        option already read their configuration from, so exporting is how a profile reaches
        them at all. A variable the caller set themselves is left alone: the environment
        already outranks the profile, and overwriting it here would invert that.
        """
        for parameter in self._spec:
            if parameter.name in self.environment:
                # Already set by the caller, and the environment outranks the profile.
                continue
            value = self.get(parameter.name)
            if value is None:
                continue
            self._overwritten.setdefault(parameter.name, os.environ.get(parameter.name))
            os.environ[parameter.name] = str(value)

    def restore(self) -> None:
        """Put ``os.environ`` back the way :meth:`export` found it.

        One CLI run is one process, so in normal use this runs as the process is ending and
        changes nothing. It matters where several invocations share an interpreter — a test
        harness, or anything embedding the CLI — because a resolver built by the second one
        would otherwise find the first one's exports in ``os.environ`` and report a
        profile's own values as environment values.
        """
        for name, previous in self._overwritten.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous
        self._overwritten.clear()

    def _lookup(self, parameter: Parameter, seen: set[str]) -> tuple[str, str] | None:
        """The first raw value for *parameter* or anything it inherits from, with its tier.

        Presence, not truth: a variable exported with nothing in it is refused at
        construction, so by here "set" and "has something in it" are the same question.
        """
        if parameter.name in seen:
            return None
        seen.add(parameter.name)
        if parameter.name in self.environment:
            return self.environment[parameter.name], ENVIRONMENT
        stored = self._values.get(parameter.name)
        if stored is not None and stored != "":
            return stored, f"profile:{self.profile}"
        for inherited in parameter.inherits:
            if inherited not in self._spec:
                continue
            found = self._lookup(self._spec[inherited], seen)
            if found is not None:
                return found
        return None
