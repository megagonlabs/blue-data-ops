"""Regression checks for repository-wide packaging metadata (#89, #90)."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LICENSES = ["LICENSE", "lib/LICENSE", "platform/ops-cli/LICENSE", "platform/ops-mcp/LICENSE"]
PYPROJECTS = ["lib/pyproject.toml", "platform/ops-cli/pyproject.toml", "platform/ops-mcp/pyproject.toml"]


def test_license_copies_have_no_html_entities():
    for name in LICENSES:
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "&#39;" not in text, name
        assert "'AS IS'" in text, name


def test_every_package_declares_family_python_range():
    for name in PYPROJECTS:
        project = tomllib.loads((ROOT / name).read_text(encoding="utf-8"))["project"]
        assert project["requires-python"] == ">=3.12,<3.14", name
        versions = [c for c in project.get("classifiers", []) if c.startswith("Programming Language :: Python :: 3.")]
        assert set(versions) <= {"Programming Language :: Python :: 3.12", "Programming Language :: Python :: 3.13"}, name
