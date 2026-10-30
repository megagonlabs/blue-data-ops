"""Check that the core wheel contains exactly the package source files."""

from __future__ import annotations

import sys
import tomllib
from collections import Counter
from pathlib import Path, PureWindowsPath
from zipfile import ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "blue_data_ops"
INCLUDED_SUFFIXES = {".py", ".json", ".md"}


def package_file(path: Path) -> bool:
    return path.name == "py.typed" or path.suffix in INCLUDED_SUFFIXES


def canonical_name(info: ZipInfo) -> bool:
    name = info.filename
    path = name[:-1] if info.is_dir() else name
    return (
        not name.startswith("/")
        and not PureWindowsPath(name).drive
        and "\\" not in name
        and all(part not in {"", ".", ".."} for part in path.split("/"))
    )


def parents(names: set[str]) -> set[str]:
    return {name[: index + 1] for name in names for index, char in enumerate(name) if char == "/"}


version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
wheels = list((ROOT / "dist").glob(f"{PACKAGE}-{version}-*.whl"))
if len(wheels) != 1:
    sys.exit(f"expected one {PACKAGE} {version} wheel in dist/, found {len(wheels)}")

source_root = ROOT / "src" / PACKAGE
source_files = {
    f"{PACKAGE}/{path.relative_to(source_root).as_posix()}": path.read_bytes()
    for path in source_root.rglob("*")
    if path.is_file() and package_file(path) and "__pycache__" not in path.parts
}
metadata = f"{PACKAGE}-{version}.dist-info/"
with ZipFile(wheels[0]) as wheel:
    entries = wheel.infolist()
    duplicates = sorted(
        name for name, count in Counter(i.filename for i in entries).items() if count > 1
    )
    if duplicates:
        for name in duplicates:
            print(f"duplicate archive member: {name}", file=sys.stderr)
        sys.exit("wheel archive has duplicate members")
    valid = [info for info in entries if canonical_name(info)]
    wheel_files = {
        info.filename
        for info in valid
        if not info.is_dir() and info.filename.startswith(f"{PACKAGE}/")
    }
    package_parents = parents(set(source_files))
    metadata_parents = parents(
        {
            info.filename
            for info in valid
            if not info.is_dir() and info.filename.startswith(metadata)
        }
    )
    extra_directories = {
        info.filename
        for info in valid
        if info.is_dir()
        and info.filename.startswith(f"{PACKAGE}/")
        and info.filename not in package_parents
    }
    outside = sorted(
        {info.filename for info in entries if not canonical_name(info)}
        | {
            info.filename
            for info in valid
            if not info.filename.startswith(f"{PACKAGE}/")
            and not (
                info.filename.startswith(metadata)
                and (not info.is_dir() or info.filename in metadata_parents)
            )
        }
    )
    changed = sorted(
        name for name in source_files.keys() & wheel_files if wheel.read(name) != source_files[name]
    )

missing = sorted(source_files.keys() - wheel_files)
extra = sorted((wheel_files - source_files.keys()) | extra_directories)
if missing or extra or changed or outside:
    for label, names in (
        ("missing from wheel", missing),
        ("not in source", extra),
        ("different from source", changed),
        ("outside the package", outside),
    ):
        for name in names:
            print(f"{label}: {name}", file=sys.stderr)
    sys.exit("wheel package files differ from src/")

print(f"checked {len(wheel_files)} package files in {wheels[0].name}")
