from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[3]
COMPONENTS = ("lib", "platform/ops-cli", "platform/ops-mcp")
SOURCE_FILES = {
    "blue_data_ops/__init__.py": b"VALUE = 1\n",
    "blue_data_ops/py.typed": b"",
    "blue_data_ops/plan/_schemas/plan.json": b'{"type": "object"}\n',
    "blue_data_ops/operator_skills/example/2.0.0/README.md": b"# Example\n",
}

ADAPTER_SOURCE_FILES = {
    "blue_data_ops_cli": {
        "blue_data_ops_cli/__init__.py": b"VALUE = 1\n",
        "blue_data_ops_cli/py.typed": b"",
        "blue_data_ops_cli/profile_spec.json": b'{"profiles": []}\n',
    },
    "blue_data_ops_mcp": {
        "blue_data_ops_mcp/__init__.py": b"VALUE = 1\n",
        "blue_data_ops_mcp/py.typed": b"",
    },
}


def _source_files(name: str) -> dict[str, bytes]:
    return SOURCE_FILES if name == "blue_data_ops" else ADAPTER_SOURCE_FILES[name]


def _project(tmp_path: Path, component: str) -> tuple[Path, str, str]:
    original = ROOT / component
    project = tmp_path / component
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    shutil.copyfile(original / "scripts/publish.sh", scripts / "publish.sh")
    metadata = tomllib.loads((original / "pyproject.toml").read_text())["project"]
    name, version = str(metadata["name"]), str(metadata["version"])
    if component == "lib":
        (project / "pyproject.toml").write_text(
            f'[project]\nname = "{name}"\nversion = "{version}"\n'
        )
    else:
        # Adapter checkers read the declared package data from the real project file.
        shutil.copyfile(original / "pyproject.toml", project / "pyproject.toml")
    (project / "dist").mkdir()
    shutil.copyfile(
        original / "scripts/check_wheel_contents.py", scripts / "check_wheel_contents.py"
    )
    for member, contents in _source_files(name.replace("-", "_")).items():
        source = project / "src" / member
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(contents)
    return project, name.replace("-", "_"), version


def _wheel(project: Path, name: str, version: str, files: dict[str, bytes]) -> Path:
    wheel_path = project / "dist" / f"{name}-{version}-py3-none-any.whl"
    with ZipFile(wheel_path, "w") as wheel:
        for member, contents in files.items():
            wheel.writestr(member, contents)
        wheel.writestr(f"{name}-{version}.dist-info/METADATA", "synthetic test metadata\n")
    return wheel_path


def _artifacts(project: Path, name: str, version: str) -> tuple[str, str]:
    wheel = _wheel(project, name, version, _source_files(name))
    sdist = project / "dist" / f"{name}-{version}.tar.gz"
    sdist.write_bytes(b"synthetic test sdist")
    return str(sdist.relative_to(project)), str(wheel.relative_to(project))


def _publish(
    project: Path, tmp_path: Path, *, destination: bool = True, check_fails: bool = False
) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    bin_path = tmp_path / "bin"
    bin_path.mkdir(exist_ok=True)
    python = bin_path / "python"
    if not python.exists():
        python.symlink_to(sys.executable)
    log = tmp_path / "twine-calls.jsonl"
    log.unlink(missing_ok=True)
    twine = bin_path / "twine"
    twine.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        'with open(os.environ["FAKE_TWINE_LOG"], "a") as log:\n'
        "    log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        'if sys.argv[1] == "check" and os.environ.get("FAKE_CHECK_FAIL") == "1":\n'
        "    sys.exit(1)\n"
    )
    twine.chmod(0o755)
    environment = {
        "PATH": f"{bin_path}{os.pathsep}/usr/bin:/bin",
        "FAKE_TWINE_LOG": str(log),
        "FAKE_CHECK_FAIL": "1" if check_fails else "0",
    }
    if destination:
        environment["TWINE_REPOSITORY_URL"] = "https://packages.example.invalid/repository/test/"
    result = subprocess.run(
        ["/bin/bash", str(project / "scripts/publish.sh")],
        env=environment,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    calls: list[list[str]] = (
        [json.loads(line) for line in log.read_text().splitlines()] if (log.exists()) else []
    )
    return result, calls


def _check_wheel(project: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(project / "scripts/check_wheel_contents.py")],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )


def test_publish_requires_explicit_destination_before_twine(tmp_path: Path) -> None:
    for component in COMPONENTS:
        project, name, version = _project(tmp_path, component)
        _artifacts(project, name, version)
        result, calls = _publish(project, tmp_path, destination=False)
        assert result.returncode != 0, component
        assert "TWINE_REPOSITORY_URL" in result.stderr, component
        assert calls == [], component


def test_publish_refuses_stale_missing_or_ambiguous_artifacts(tmp_path: Path) -> None:
    for case in ("stale", "missing-sdist", "multiple-wheels"):
        for component in COMPONENTS:
            case_path = tmp_path / case
            project, name, version = _project(case_path, component)
            if case == "stale":
                _artifacts(project, name, "0.0.0")
            else:
                sdist, wheel = _artifacts(project, name, version)
                if case == "missing-sdist":
                    (project / sdist).unlink()
                else:
                    shutil.copyfile(
                        project / wheel,
                        project / "dist" / f"{name}-{version}-py311-none-any.whl",
                    )
            result, calls = _publish(project, case_path)
            assert result.returncode != 0, (case, component)
            assert "Expected one wheel and one sdist" in result.stderr, (case, component)
            assert calls == [], (case, component)


def test_publish_checks_and_uploads_only_current_pair(tmp_path: Path) -> None:
    for component in COMPONENTS:
        project, name, version = _project(tmp_path, component)
        sdist, wheel = _artifacts(project, name, version)
        _artifacts(project, name, "0.0.0")
        (project / "dist" / "unrelated-1.0.0.tar.gz").write_bytes(b"stale unrelated artifact")
        result, calls = _publish(project, tmp_path)
        assert result.returncode == 0, (component, result.stderr)
        assert calls == [
            ["check", sdist, wheel],
            [
                "upload",
                "--repository-url",
                "https://packages.example.invalid/repository/test/",
                sdist,
                wheel,
            ],
        ], component


def test_publish_stops_when_twine_check_fails(tmp_path: Path) -> None:
    for component in COMPONENTS:
        project, name, version = _project(tmp_path, component)
        sdist, wheel = _artifacts(project, name, version)
        result, calls = _publish(project, tmp_path, check_fails=True)
        assert result.returncode != 0, component
        assert calls == [["check", sdist, wheel]], component


def test_wheel_checker_accepts_matching_package_files(tmp_path: Path) -> None:
    project, name, version = _project(tmp_path, "lib")
    _artifacts(project, name, version)
    result = _check_wheel(project)
    assert result.returncode == 0, result.stderr
    assert f"checked {len(SOURCE_FILES)} package files" in result.stdout


def test_wheel_checker_rejects_missing_extra_and_stale_package_files(tmp_path: Path) -> None:
    for case, diagnostic in (
        ("missing", "missing from wheel"),
        ("extra", "not in source"),
        ("stale", "different from source"),
    ):
        project, name, version = _project(tmp_path / case, "lib")
        files = SOURCE_FILES.copy()
        if case == "missing":
            del files["blue_data_ops/py.typed"]
        elif case == "extra":
            files["blue_data_ops/deleted_module.py"] = b"obsolete = True\n"
        else:
            files["blue_data_ops/__init__.py"] = b"VALUE = 0\n"
        _wheel(project, name, version, files)
        result = _check_wheel(project)
        assert result.returncode != 0, case
        assert diagnostic in result.stderr, case
        assert "wheel package files differ from src/" in result.stderr, case


def test_core_publish_rejects_stale_wheel_before_twine(tmp_path: Path) -> None:
    project, name, version = _project(tmp_path, "lib")
    _artifacts(project, name, version)
    files = SOURCE_FILES | {"blue_data_ops/deleted_module.py": b"obsolete = True\n"}
    _wheel(project, name, version, files)
    result, calls = _publish(project, tmp_path)
    assert result.returncode != 0
    assert "not in source: blue_data_ops/deleted_module.py" in result.stderr
    assert calls == []


project = _project
