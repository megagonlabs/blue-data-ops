from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.optional_integrations import require_optional


def test_litellm_stub_does_not_count_as_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = Path(__file__).resolve().parents[1] / "stubs"
    monkeypatch.setattr(sys, "path", [str(stub), str(stub / ".." / "stubs")])
    with pytest.raises(pytest.skip.Exception, match="litellm is not installed"):
        require_optional("litellm")


@pytest.mark.parametrize("body", ["", "raise ImportError('broken installed LiteLLM')"])
def test_litellm_availability_does_not_import_the_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str
) -> None:
    package = tmp_path / "litellm"
    package.mkdir()
    (package / "__init__.py").write_text(body + "\nraise AssertionError('must not import')\n")
    monkeypatch.setattr(sys, "path", [str(tmp_path)])
    require_optional("litellm")
