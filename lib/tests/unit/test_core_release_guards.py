"""Exercise wheel names, directory records and the core build/publish boundary in scratch."""

from __future__ import annotations

import shutil
from pathlib import Path
from zipfile import ZipFile

import pytest

from tests.unit import test_adapter_release_guards as adapter
from tests.unit import test_release_scripts as release


def _project(tmp_path: Path) -> tuple[Path, str, str]:
    project, package, version = release.project(tmp_path, "lib")
    shutil.copyfile(release.ROOT / "lib/scripts/build.sh", project / "scripts/build.sh")
    return project, package, version


def _good(package: str, version: str) -> list[tuple[str, bytes]]:
    return [
        *release.SOURCE_FILES.items(),
        (f"{package}-{version}.dist-info/METADATA", b"synthetic metadata\n"),
    ]


@pytest.mark.parametrize(
    ("name", "label"),
    [
        ("{p}/plan/refiner.pyc", "not in source"),
        ("{p}/notes.txt", "not in source"),
        ("{p}/native.so", "not in source"),
        ("{p}/data.bin", "not in source"),
        ("stray_module.py", "outside the package"),
        ("Blue_Data_Ops/stray.py", "outside the package"),
        ("{p}-{v}.data/stray.py", "outside the package"),
        ("{p}-0.0.0.dist-info/METADATA", "outside the package"),
        ("{p}/plan/retired/", "not in source"),
        ("empty/", "outside the package"),
        ("{p}-{v}.dist-info/empty/", "outside the package"),
    ],
)
def test_core_refuses_undeclared_members(tmp_path: Path, name: str, label: str) -> None:
    project, package, version = _project(tmp_path)
    name = name.format(p=package, v=version)
    adapter.wheel(project, package, version, [*_good(package, version), (name, b"")])
    result = adapter.check(project)
    assert result.returncode != 0
    assert f"{label}: {name}\n" in result.stderr
    assert "wheel package files differ from src/" in result.stderr


@pytest.mark.parametrize("component", ["lib", *sorted(adapter.ADAPTERS)])
@pytest.mark.parametrize(
    "name",
    [
        "{p}/../stray.py",
        "{p}-{v}.dist-info/../stray.py",
        "{p}-{v}.dist-info/./METADATA",
        "{p}-{v}.dist-info//METADATA",
        "{p}/./module.py",
        "{p}//module.py",
        "/absolute.py",
        "C:relative.py",
        "C:/absolute.py",
        "{p}-{v}.dist-info\\stray.py",
        "{p}-{v}.dist-info/../",
        "{p}-{v}.dist-info//",
        "{p}//",
    ],
)
def test_all_checkers_reject_noncanonical_names(tmp_path: Path, component: str, name: str) -> None:
    if component == "lib":
        project, package, version = _project(tmp_path)
        good = _good(package, version)
    else:
        project, package, version = adapter.project(tmp_path, component)
        good = adapter.good(package, version)
    name = name.format(p=package, v=version)
    adapter.wheel(project, package, version, [*good, (name, b"")])
    result = adapter.check(project)
    assert result.returncode != 0
    assert f"outside the package: {name}\n" in result.stderr
    assert "wheel package files differ from src/" in result.stderr


@pytest.mark.parametrize(
    "name", ["{p}/__init__.py", "{p}-{v}.dist-info/METADATA", "{p}/", "{p}-{v}.dist-info/"]
)
def test_core_refuses_duplicates_before_directory_exemption(tmp_path: Path, name: str) -> None:
    project, package, version = _project(tmp_path)
    name = name.format(p=package, v=version)
    members = _good(package, version)
    members += [(name, b"")] * (1 if not name.endswith("/") else 2)
    adapter.wheel(project, package, version, members)
    result = adapter.check(project)
    assert result.returncode != 0
    assert f"duplicate archive member: {name}\n" in result.stderr
    assert "wheel archive has duplicate members" in result.stderr


def test_core_accepts_only_parent_directories_and_counts_files(tmp_path: Path) -> None:
    project, package, version = _project(tmp_path)
    metadata = f"{package}-{version}.dist-info/"
    members = _good(package, version) + [
        (f"{package}/", b""),
        (f"{package}/plan/", b""),
        (f"{package}/plan/_schemas/", b""),
        (metadata, b""),
        (metadata + "licenses/", b""),
        (metadata + "licenses/LICENSE", b"synthetic license\n"),
    ]
    # Generated files in src/ must not authorize new wheel members.
    cache = project / "src" / package / "__pycache__"
    cache.mkdir()
    (cache / "generated.py").write_text("VALUE = 2\n")
    adapter.wheel(project, package, version, members)
    result = adapter.check(project)
    assert result.returncode == 0, result.stderr
    assert f"checked {len(release.SOURCE_FILES)} package files" in result.stdout
    adapter.wheel(
        project,
        package,
        version,
        [*members, (f"{package}/__pycache__/generated.py", b"VALUE = 2\n")],
    )
    result = adapter.check(project)
    assert result.returncode != 0
    assert f"not in source: {package}/__pycache__/generated.py" in result.stderr


def test_core_publish_refuses_bytecode_before_twine(tmp_path: Path) -> None:
    project, package, version = _project(tmp_path)
    adapter.wheel(
        project,
        package,
        version,
        [*_good(package, version), (f"{package}/plan/refiner.pyc", b"synthetic")],
    )
    adapter.sdist(project, package, version)
    result, calls = adapter.script(project, tmp_path, "publish.sh")
    assert result.returncode != 0
    assert f"not in source: {package}/plan/refiner.pyc" in result.stderr
    assert calls == []


def test_core_build_cleans_before_backend_and_checks_afterward(tmp_path: Path) -> None:
    project, package, version = _project(tmp_path)
    stale = project / "build/lib" / package / "plan/refiner.pyc"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"synthetic")
    (project / "dist/old.whl").write_bytes(b"old")
    (project / "keep.egg-info").mkdir()
    adapter.tools(tmp_path)
    (tmp_path / "fake_build.py").write_text(
        "from pathlib import Path\n"
        "assert not Path('build').exists()\n"
        "assert not Path('dist').exists()\n"
        "assert Path('keep.egg-info').is_dir()\n" + adapter.FAKE_BUILD
    )
    result, calls = adapter.script(project, tmp_path, "build.sh")
    assert result.returncode == 0, result.stderr
    assert calls == []
    assert not stale.exists()
    assert f"checked {len(release.SOURCE_FILES)} package files" in result.stdout
    assert sorted(p.name for p in (project / "dist").iterdir()) == sorted(
        [
            f"{package}-{version}-py3-none-any.whl",
            f"{package}-{version}.tar.gz",
        ]
    )
    with ZipFile(project / "dist" / f"{package}-{version}-py3-none-any.whl") as wheel:
        assert f"{package}/plan/refiner.pyc" not in wheel.namelist()
    build = (project / "scripts/build.sh").read_text()
    assert build.index("rm -rf -- build dist") < build.index("python -m build")
    assert build.index("python -m build") < build.index("python scripts/check_wheel_contents.py")
    (tmp_path / "fake_build.py").write_text(
        adapter.FAKE_BUILD
        + "with ZipFile(f'dist/{name}-{version}-py3-none-any.whl', 'a') as wheel:\n"
        "    wheel.writestr(f'{name}/plan/refiner.pyc', b'synthetic')\n"
    )
    result, calls = adapter.script(project, tmp_path, "build.sh")
    assert result.returncode != 0
    assert f"not in source: {package}/plan/refiner.pyc" in result.stderr
    assert calls == []
