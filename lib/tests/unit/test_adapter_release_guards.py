"""The CLI and MCP adapters refuse a contaminated wheel at build and before upload.

Every case runs on a scratch copy of the adapter's real scripts and ``pyproject.toml``, with
a fake build backend and a fake twine that only records its arguments. Nothing here builds
from, cleans or publishes the real tree.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tomllib
import warnings
from pathlib import Path
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[3]
ADAPTERS = {
    "platform/ops-cli": "blue_data_ops_cli",
    "platform/ops-mcp": "blue_data_ops_mcp",
}

# A fake `python -m build`: like setuptools, it copies src/ into build/lib and packages
# whatever build/lib then holds, so a stale module left there reaches the wheel.
FAKE_BUILD = r"""
import shutil, sys, tarfile, tomllib
from pathlib import Path
from zipfile import ZipFile
project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
name, version = project["name"].replace("-", "_"), project["version"]
shutil.copytree(Path("src") / name, Path("build/lib") / name, dirs_exist_ok=True)
Path("dist").mkdir(exist_ok=True)
with ZipFile(f"dist/{name}-{version}-py3-none-any.whl", "w") as wheel:
    for path in sorted(Path("build/lib").rglob("*")):
        if path.is_file():
            wheel.write(path, path.relative_to("build/lib").as_posix())
    wheel.writestr(f"{name}-{version}.dist-info/METADATA", "synthetic test metadata\n")
with tarfile.open(f"dist/{name}-{version}.tar.gz", "w:gz") as sdist:
    sdist.add("pyproject.toml", f"{name}-{version}/pyproject.toml")
"""


def _sources(package: str) -> dict[str, bytes]:
    files = {f"{package}/__init__.py": b"VALUE = 1\n", f"{package}/py.typed": b""}
    if package == "blue_data_ops_cli":
        files[f"{package}/profile_spec.json"] = b'{"profiles": []}\n'
    return files


def _project(tmp_path: Path, component: str) -> tuple[Path, str, str]:
    original = ROOT / component
    project = tmp_path / component
    (project / "scripts").mkdir(parents=True)
    for script in ("build.sh", "publish.sh", "check_wheel_contents.py"):
        shutil.copyfile(original / "scripts" / script, project / "scripts" / script)
    shutil.copyfile(original / "pyproject.toml", project / "pyproject.toml")
    metadata = tomllib.loads((project / "pyproject.toml").read_text())["project"]
    package = ADAPTERS[component]
    for member, contents in _sources(package).items():
        path = project / "src" / member
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
    (project / "dist").mkdir()
    return project, package, str(metadata["version"])


def _wheel(project: Path, package: str, version: str, members: list[tuple[str, bytes]]) -> Path:
    path = project / "dist" / f"{package}-{version}-py3-none-any.whl"
    path.unlink(missing_ok=True)
    with warnings.catch_warnings():
        # ZipFile warns about, but writes, a duplicate name; some cases need exactly that.
        warnings.simplefilter("ignore", UserWarning)
        with ZipFile(path, "w") as wheel:
            for name, contents in members:
                wheel.writestr(name, contents)
    return path


def _good(package: str, version: str) -> list[tuple[str, bytes]]:
    return [
        *_sources(package).items(),
        (f"{package}-{version}.dist-info/METADATA", b"synthetic test metadata\n"),
    ]


def _sdist(project: Path, package: str, version: str) -> Path:
    path = project / "dist" / f"{package}-{version}.tar.gz"
    path.write_bytes(b"synthetic test sdist")
    return path


def _tools(tmp_path: Path) -> Path:
    bin_path = tmp_path / "bin"
    if bin_path.exists():
        return bin_path
    bin_path.mkdir()
    (tmp_path / "fake_build.py").write_text(FAKE_BUILD)
    python = bin_path / "python"
    python.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-m" ] && [ "$2" = "build" ]; then\n'
        f'  exec "{sys.executable}" "{tmp_path / "fake_build.py"}"\n'
        "fi\n"
        f'exec "{sys.executable}" "$@"\n'
    )
    python.chmod(0o755)
    twine = bin_path / "twine"
    twine.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        'with open(os.environ["FAKE_TWINE_LOG"], "a") as log:\n'
        "    log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
    )
    twine.chmod(0o755)
    return bin_path


def _script(
    project: Path, tmp_path: Path, script: str
) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    bin_path = _tools(tmp_path)
    log = tmp_path / "twine-calls.jsonl"
    log.unlink(missing_ok=True)
    result = subprocess.run(
        ["/bin/bash", str(project / "scripts" / script)],
        env={
            "PATH": f"{bin_path}{os.pathsep}/usr/bin:/bin",
            "FAKE_TWINE_LOG": str(log),
            "TWINE_REPOSITORY_URL": "https://packages.example.invalid/repository/test/",
        },
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result, calls


def _check(project: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(project / "scripts/check_wheel_contents.py")],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )


@pytest.mark.parametrize("component", sorted(ADAPTERS))
def test_the_checker_accepts_the_declared_package_files(tmp_path: Path, component: str) -> None:
    project, package, version = _project(tmp_path, component)
    _wheel(project, package, version, _good(package, version))
    result = _check(project)
    assert result.returncode == 0, result.stderr
    assert f"checked {len(_sources(package))} package files" in result.stdout


@pytest.mark.parametrize("component", sorted(ADAPTERS))
@pytest.mark.parametrize(
    ("case", "diagnostic", "summary"),
    [
        ("retired-module", "not in source: {p}/retired_module.py", "differ from src/"),
        ("unexpected-suffix", "not in source: {p}/notes.txt", "differ from src/"),
        ("unexpected-data", "not in source: {p}/data/blob.bin", "differ from src/"),
        ("missing", "missing from wheel: {p}/py.typed", "differ from src/"),
        ("changed", "different from source: {p}/__init__.py", "differ from src/"),
        ("outside", "outside the package: stray_module.py", "differ from src/"),
        ("duplicate-package", "duplicate archive member: {p}/__init__.py", "duplicate members"),
        (
            "duplicate-metadata",
            "duplicate archive member: {p}-{v}.dist-info/METADATA",
            "duplicate members",
        ),
    ],
)
def test_the_checker_rejects_every_package_difference(
    tmp_path: Path, component: str, case: str, diagnostic: str, summary: str
) -> None:
    project, package, version = _project(tmp_path, component)
    members = _good(package, version)
    if case == "retired-module":
        members.append((f"{package}/retired_module.py", b"obsolete = True\n"))
    elif case == "unexpected-suffix":
        members.append((f"{package}/notes.txt", b"stale\n"))
    elif case == "unexpected-data":
        members.append((f"{package}/data/blob.bin", b"\0"))
    elif case == "missing":
        members = [m for m in members if m[0] != f"{package}/py.typed"]
    elif case == "changed":
        members = [(n, b"VALUE = 0\n" if n.endswith("__init__.py") else c) for n, c in members]
    elif case == "outside":
        members.append(("stray_module.py", b"x = 1\n"))
    elif case == "duplicate-package":
        members.append((f"{package}/__init__.py", b"VALUE = 1\n"))
    else:
        members.append((f"{package}-{version}.dist-info/METADATA", b"second copy\n"))
    _wheel(project, package, version, members)
    result = _check(project)
    assert result.returncode != 0, case
    assert diagnostic.format(p=package, v=version) in result.stderr, (case, result.stderr)
    assert summary in result.stderr, case


@pytest.mark.parametrize("component", sorted(ADAPTERS))
def test_the_checker_needs_exactly_one_current_wheel(tmp_path: Path, component: str) -> None:
    project, package, version = _project(tmp_path, component)
    result = _check(project)
    assert result.returncode != 0
    assert f"expected one {package} {version} wheel in dist/, found 0" in result.stderr


@pytest.mark.parametrize("component", sorted(ADAPTERS))
def test_publish_rejects_a_contaminated_current_wheel_before_twine(
    tmp_path: Path, component: str
) -> None:
    project, package, version = _project(tmp_path, component)
    _wheel(
        project,
        package,
        version,
        [*_good(package, version), (f"{package}/retired_module.py", b"obsolete = True\n")],
    )
    _sdist(project, package, version)
    result, calls = _script(project, tmp_path, "publish.sh")
    assert result.returncode != 0
    assert f"not in source: {package}/retired_module.py" in result.stderr
    assert calls == []


@pytest.mark.parametrize("component", sorted(ADAPTERS))
def test_publish_checks_then_uploads_the_exact_current_pair(tmp_path: Path, component: str) -> None:
    project, package, version = _project(tmp_path, component)
    wheel = _wheel(project, package, version, _good(package, version)).relative_to(project)
    sdist = _sdist(project, package, version).relative_to(project)
    (project / "dist" / f"{package}-0.0.0-py3-none-any.whl").write_bytes(b"older")
    (project / "dist" / "unrelated-1.0.0.tar.gz").write_bytes(b"unrelated")
    result, calls = _script(project, tmp_path, "publish.sh")
    assert result.returncode == 0, result.stderr
    assert calls == [
        ["check", str(sdist), str(wheel)],
        [
            "upload",
            "--repository-url",
            "https://packages.example.invalid/repository/test/",
            str(sdist),
            str(wheel),
        ],
    ]


@pytest.mark.parametrize("component", sorted(ADAPTERS))
def test_build_starts_fresh_and_drops_stale_build_and_dist_state(
    tmp_path: Path, component: str
) -> None:
    project, package, version = _project(tmp_path, component)
    stale = project / "build/lib" / package / "retired_module.py"
    stale.parent.mkdir(parents=True)
    stale.write_text("obsolete = True\n")
    (project / "dist" / f"{package}-0.9.0-py3-none-any.whl").write_bytes(b"older")
    result, calls = _script(project, tmp_path, "build.sh")
    assert result.returncode == 0, result.stderr
    assert calls == []
    assert not stale.exists()
    assert sorted(path.name for path in (project / "dist").iterdir()) == sorted(
        [f"{package}-{version}-py3-none-any.whl", f"{package}-{version}.tar.gz"]
    )
    with ZipFile(project / "dist" / f"{package}-{version}-py3-none-any.whl") as wheel:
        assert f"{package}/retired_module.py" not in wheel.namelist()
    assert f"checked {len(_sources(package))} package files" in result.stdout


@pytest.mark.parametrize("component", sorted(ADAPTERS))
def test_build_fails_when_the_built_wheel_is_contaminated(tmp_path: Path, component: str) -> None:
    project, package, _version = _project(tmp_path, component)
    # A backend that leaves a module in the wheel that src/ does not have.
    _tools(tmp_path)
    (tmp_path / "fake_build.py").write_text(
        FAKE_BUILD
        + "with ZipFile(f'dist/{name}-{version}-py3-none-any.whl', 'a') as wheel:\n"
        + "    wheel.writestr(f'{name}/retired_module.py', 'obsolete = True\\n')\n"
    )
    result, _ = _script(project, tmp_path, "build.sh")
    assert result.returncode != 0
    assert f"not in source: {package}/retired_module.py" in result.stderr


@pytest.mark.parametrize("component", sorted(ADAPTERS))
def test_the_source_distribution_carries_the_checker(component: str) -> None:
    manifest = (ROOT / component / "MANIFEST.in").read_text().splitlines()
    assert "recursive-include scripts *.py" in manifest
    assert "recursive-include scripts *.sh" in manifest
    build = (ROOT / component / "scripts/build.sh").read_text()
    publish = (ROOT / component / "scripts/publish.sh").read_text()
    assert "rm -rf -- build dist" in build
    assert build.index("rm -rf -- build dist") < build.index("python -m build")
    assert build.index("python -m build") < build.index("python scripts/check_wheel_contents.py")
    assert publish.index("TWINE_REPOSITORY_URL:?") < publish.index("Expected one wheel")
    assert publish.index("Expected one wheel") < publish.index(
        "python scripts/check_wheel_contents.py"
    )
    assert publish.index("python scripts/check_wheel_contents.py") < publish.index("twine check")
    assert publish.index("twine check") < publish.index("twine upload")


def test_the_adapter_checkers_differ_only_in_their_package() -> None:
    cli = (ROOT / "platform/ops-cli/scripts/check_wheel_contents.py").read_text()
    mcp = (ROOT / "platform/ops-mcp/scripts/check_wheel_contents.py").read_text()
    assert cli.replace("blue_data_ops_cli", "PACKAGE") == mcp.replace(
        "blue_data_ops_mcp", "PACKAGE"
    )


def test_the_checker_reads_the_declared_package_data() -> None:
    for component, package in ADAPTERS.items():
        declared = tomllib.loads((ROOT / component / "pyproject.toml").read_text())["tool"][
            "setuptools"
        ]["package-data"][package]
        source = ROOT / component / "src" / package
        assert all((source / name).is_file() for name in declared), component
        non_code = sorted(
            path.relative_to(source).as_posix()
            for path in source.rglob("*")
            if path.is_file() and path.suffix != ".py" and "__pycache__" not in path.parts
        )
        assert non_code == sorted(declared), component


# Shared helpers for the core and adapter packaging tests.
project = _project
wheel = _wheel
good = _good
sdist = _sdist
tools = _tools
script = _script
check = _check
