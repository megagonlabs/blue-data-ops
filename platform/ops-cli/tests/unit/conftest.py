"""Fixtures for the CLI tests.

Two boundaries are doubled and nothing else. The CLI home, because these tests write
profiles: every run is pointed at a temporary directory, the environment is cleared of the
variables the CLI reads, and a guard fails the run if the real ``~/.blue-ops`` appears or
disappears. And the catalog, because that is the one seam every command reads the library
through, so a test can hand a command a prepared registry or a prepared failure without
reaching any operator.

Nothing here contacts a provider or a data registry. No test writes a credential anywhere:
the values set by ``test_secret_canary`` are sentinels shaped like key material.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from inspect import signature
from pathlib import Path
from typing import Any

import pytest
from blue_data_ops.operators import OperatorRegistry
from click.testing import CliRunner

from blue_data_ops_cli import config


@pytest.fixture(autouse=True)
def cli_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the CLI at a throwaway home and clear the variables it reads."""
    home = tmp_path / ".blue-ops"
    for name in list(os.environ):
        if name.startswith("BLUE_DATA_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv(config.HOME_VARIABLE, str(home))
    return home


@pytest.fixture(autouse=True)
def never_the_real_home(cli_home: Path) -> Iterator[None]:
    """A test that writes to the developer's own profiles is a test that has to fail."""
    real = Path(config.CLI_HOME_DEFAULT).expanduser()
    before = real.exists()
    yield
    assert real.exists() == before, f"a test created or removed {real}"


@pytest.fixture
def swap_when_opened(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Arrange for a swap to happen once, just before a matching file is opened.

    The gap these tests are about is not a link that is already in place when a command
    starts — that one any check catches. It is a link that appears *while* the command
    runs, after the boundary has been decided and before the name is used again. Firing on
    `os.open` puts it exactly there, and puts it there for a store that opens a whole path
    and for one that opens a name against a directory it already holds, so the same test
    reads on both.
    """

    def arrange(basename: str, swap: Callable[[], None], creating: bool = False) -> None:
        real: Any = os.open
        fired = False

        def opening(path: Any, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
            nonlocal fired
            named = str(path).split("/")[-1]
            if not fired and named.startswith(basename) and bool(flags & os.O_CREAT) == creating:
                fired = True
                swap()
            return int(real(path, flags, mode, dir_fd=dir_fd))

        monkeypatch.setattr(os, "open", opening)

    return arrange


@pytest.fixture
def creations_under(monkeypatch: pytest.MonkeyPatch) -> Callable[[Path], list[str]]:
    """Collect every file created at a path that resolves under a given directory.

    Asked of the creation rather than of the directory afterwards, because a write that
    lands outside the home and is then cleaned up has still put the content there.
    """

    def watching(directory: Path) -> list[str]:
        landed: list[str] = []
        real: Any = os.open

        def opening(path: Any, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
            if flags & os.O_CREAT and dir_fd is None:
                where = Path(str(path)).parent.resolve()
                if where == directory or directory in where.parents:
                    landed.append(str(path))
            return int(real(path, flags, mode, dir_fd=dir_fd))

        monkeypatch.setattr(os, "open", opening)
        return landed

    return watching


@pytest.fixture
def runner() -> CliRunner:
    options: dict[str, Any] = {}
    if "mix_stderr" in signature(CliRunner).parameters:
        options["mix_stderr"] = False
    return CliRunner(**options)


@pytest.fixture
def install_catalog(monkeypatch: pytest.MonkeyPatch) -> Callable[[Any], Any]:
    """Replace the catalog seam with a prepared registry, or with a prepared failure.

    ``config.build_catalog`` is the single point every command reads the operator library
    through, so installing a registry here covers every one of them, and installing an
    exception raises it from inside a real command body rather than from a stub of one.
    """

    def install(outcome: OperatorRegistry | Exception) -> Any:
        def build(name: str) -> OperatorRegistry:
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        monkeypatch.setattr(config, "build_catalog", build)
        return outcome

    return install


@pytest.fixture
def install_registry_seam(monkeypatch: pytest.MonkeyPatch) -> Callable[[Any], Any]:
    """Replace the ``blue-data`` registry seam, so no test builds a real registry."""

    def install(seam: Any) -> Any:
        def build() -> Any:
            if isinstance(seam, Exception):
                raise seam
            return seam

        monkeypatch.setattr(config, "build_registry_seam", build)
        return seam

    return install
