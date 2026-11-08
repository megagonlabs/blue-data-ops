"""Check the SDK policy after composing core and adapter extras."""

from __future__ import annotations

import tomllib
from collections.abc import Set
from pathlib import Path

import pytest
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[3]
CORE = tomllib.loads((ROOT / "lib/pyproject.toml").read_text())["project"]
CLI = tomllib.loads((ROOT / "platform/ops-cli/pyproject.toml").read_text())["project"]


def requirements_for(extras: Set[str]) -> list[Requirement]:
    declared = list(CORE["dependencies"])
    for extra in extras:
        declared.extend(CORE["optional-dependencies"][extra])
    return [Requirement(value) for value in declared]


@pytest.mark.parametrize("extras", [{"llm"}, {"openai"}, {"dev"}, {"llm", "openai"}])
def test_composed_extras_constrain_the_planner_sdk(extras: set[str]) -> None:
    requirements = requirements_for(extras)
    sdk = [req for req in requirements if req.name == "openai"]
    assert sdk
    for version, admitted in [
        ("2.20.0", False),
        ("2.54.0", True),
        ("2.99.0", True),
        ("3.0.0", False),
        ("3.45.0", False),
        ("3.46.0", False),
    ]:
        assert all(req.specifier.contains(version) for req in sdk) is admitted
    if "llm" in extras:
        adapter = next(req for req in requirements if req.name == "litellm")
        assert adapter.specifier.contains("1.108.0")


def test_cli_core_extra_composition_inherits_sdk_policy() -> None:
    core = next(
        Requirement(value)
        for value in CLI["dependencies"]
        if Requirement(value).name == CORE["name"]
    )
    assert core.specifier.contains(CORE["version"])
    requirements = requirements_for(core.extras)
    sdk = [req for req in requirements if req.name == "openai"]
    assert sdk
    assert all(req.specifier.contains("2.54.0") for req in sdk)
    assert not all(req.specifier.contains("3.46.0") for req in sdk)


def test_base_does_not_directly_require_provider_libraries() -> None:
    assert {req.name for req in requirements_for(set())}.isdisjoint({"openai", "litellm"})
