"""Skip absent integrations without hiding broken installed packages."""

from __future__ import annotations

import sys
from importlib import import_module
from importlib.machinery import PathFinder
from pathlib import Path

import pytest


def real_litellm_paths() -> list[str]:
    """Exclude this suite's stub, including aliases of its directory."""
    stub = (Path(__file__).parent / "stubs").resolve()
    return [str(Path(path).resolve()) for path in sys.path if Path(path).resolve() != stub]


def require_optional(module: str) -> None:
    if module == "litellm":
        # The real integration tests import LiteLLM in their existing subprocesses.
        # Finding its file here must neither import it nor accept the loaded stub.
        if PathFinder.find_spec(module, real_litellm_paths()) is not None:
            return
    else:
        try:
            import_module(module)
        except ModuleNotFoundError as error:
            if error.name is None or not (
                module == error.name or module.startswith(error.name + ".")
            ):
                raise
        else:
            return
    pytest.skip(f"optional integration {module} is not installed", allow_module_level=True)
