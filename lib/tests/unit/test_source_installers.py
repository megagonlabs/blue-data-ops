"""Exercise source-installer argument construction without installing packages."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("package", ["lib", "platform/ops-cli", "platform/ops-mcp"])
def test_installer_uses_only_editable_source_candidates(tmp_path: Path, package: str) -> None:
    log = tmp_path / "calls.jsonl"
    source = tmp_path / "selected-blue-data"
    source.mkdir()
    recorder = tmp_path / "python-recorder"
    recorder.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" -S -B "{tmp_path / "record.py"}" "$@"\n',
        encoding="utf-8",
    )
    recorder.chmod(0o700)
    (tmp_path / "record.py").write_text(
        "import json, os, sys\n"
        "with open(os.environ['INSTALLER_TEST_LOG'], 'a') as out:\n"
        "    out.write(json.dumps(sys.argv[1:]) + '\\n')\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(ROOT / package / "scripts/install.sh")],
        env={
            **os.environ,
            "PYTHON": str(recorder),
            "BLUE_DATA_PATH": str(source),
            "INSTALLER_TEST_LOG": str(log),
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    pip_calls = [args for args in calls if args[:3] == ["-m", "pip", "install"]]
    assert len(pip_calls) == {"lib": 2, "platform/ops-cli": 4, "platform/ops-mcp": 5}[package]
    for args in pip_calls:
        assert args[3:4] == ["-e"]
        assert len(args) == 5, args
        assert "--no-deps" not in args
    assert pip_calls[0][-1] == str(source)
    assert pip_calls[1][-1] == str(ROOT / "lib") + "[dev]"
    if package == "platform/ops-mcp":
        assert pip_calls[2][-1] == str(source) + "[server]"
    assert pip_calls[-1][-1] == str(ROOT / package) + "[dev]"


@pytest.mark.parametrize("problem", ["wrong-name", "missing-server"])
def test_source_preflight_rejects_incompatible_layout(tmp_path: Path, problem: str) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "'
        + ("other" if problem == "wrong-name" else "blue-data")
        + '"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            "-B",
            str(ROOT / "lib/scripts/check_blue_data.py"),
            str(tmp_path),
            "--server",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 1
    expected = (
        "does not identify blue-data" if problem == "wrong-name" else "lacks the server extra"
    )
    assert expected in result.stderr
