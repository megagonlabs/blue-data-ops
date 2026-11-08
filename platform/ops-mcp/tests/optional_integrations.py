"""Skip absent integrations without hiding broken installed packages."""

from __future__ import annotations

from importlib import import_module

import pytest


def require_optional(module: str) -> None:
    try:
        import_module(module)
    except ModuleNotFoundError as error:
        if error.name is None or not (module == error.name or module.startswith(error.name + ".")):
            raise
        pytest.skip(f"optional integration {module} is not installed", allow_module_level=True)
