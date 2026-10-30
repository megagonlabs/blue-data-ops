"""Check that the blue_data_ops_cli wheel contains exactly the declared package files.

The declared files are every ``.py`` module under ``src/blue_data_ops_cli`` plus the names
listed for it under ``[tool.setuptools.package-data]``. Every wheel member under the package
is compared, whatever its suffix, and anything outside the package and the current
``.dist-info`` directory is refused, as is a name the archive holds more than once.
"""

from __future__ import annotations

import sys
import tomllib
from collections import Counter
from pathlib import Path, PureWindowsPath
from zipfile import ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "blue_data_ops_cli"


def canonical_name(info: ZipInfo) -> bool:
    name = info.filename
    path = name[:-1] if info.is_dir() else name
    return (
        not name.startswith("/")
        and not PureWindowsPath(name).drive
        and "\\" not in name
        and all(part not in {"", ".", ".."} for part in path.split("/"))
    )


project = tomllib.loads((ROOT / "pyproject.toml").read_text())
version = project["project"]["version"]
setuptools = project.get("tool", {}).get("setuptools", {})
declared_data = setuptools.get("package-data", {}).get(PACKAGE, [])
if any(set(name) & set("*?[") for name in declared_data):
    sys.exit(f"package-data for {PACKAGE} must list file names, not patterns")

wheels = list((ROOT / "dist").glob(f"{PACKAGE}-{version}-*.whl"))
if len(wheels) != 1:
    sys.exit(f"expected one {PACKAGE} {version} wheel in dist/, found {len(wheels)}")

source_root = ROOT / "src" / PACKAGE
source_files = {
    f"{PACKAGE}/{path.relative_to(source_root).as_posix()}": path.read_bytes()
    for path in source_root.rglob("*.py")
    if path.is_file() and "__pycache__" not in path.parts
}
for name in declared_data:
    path = source_root / name
    if not path.is_file():
        sys.exit(f"declared package data is missing from src/: {PACKAGE}/{name}")
    source_files[f"{PACKAGE}/{name}"] = path.read_bytes()

metadata = f"{PACKAGE}-{version}.dist-info/"
with ZipFile(wheels[0]) as wheel:
    # Read the raw entry list first: a name stored twice would collapse in a set.
    names = [info.filename for info in wheel.infolist()]
    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    if duplicates:
        for name in duplicates:
            print(f"duplicate archive member: {name}", file=sys.stderr)
        sys.exit("wheel archive has duplicate members")
    invalid = {info.filename for info in wheel.infolist() if not canonical_name(info)}
    package_members = {
        name for name in names if name not in invalid and name.startswith(f"{PACKAGE}/")
    }
    outside = sorted(
        name
        for name in names
        if name in invalid or (name not in package_members and not name.startswith(metadata))
    )
    changed = sorted(
        name
        for name in source_files.keys() & package_members
        if wheel.read(name) != source_files[name]
    )

missing = sorted(source_files.keys() - package_members)
extra = sorted(package_members - source_files.keys())
if missing or extra or changed or outside:
    for label, members in (
        ("missing from wheel", missing),
        ("not in source", extra),
        ("different from source", changed),
        ("outside the package", outside),
    ):
        for name in members:
            print(f"{label}: {name}", file=sys.stderr)
    sys.exit("wheel package files differ from src/")

print(f"checked {len(package_members)} package files in {wheels[0].name}")
