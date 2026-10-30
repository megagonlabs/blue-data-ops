from __future__ import annotations

import base64
import csv
import hashlib
import importlib.util
import io
import zipfile
from pathlib import Path
from types import ModuleType

import pytest
from packaging.requirements import Requirement

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_constraints_are_explicit_and_python315_only() -> None:
    constraints = [
        Requirement(line)
        for line in (SCRIPTS / "python315-constraints.txt").read_text().splitlines()
        if line and not line.startswith("#")
    ]
    assert {r.name: str(r.specifier) for r in constraints} == {
        "litellm": "==1.106.5+blue.1",
        "fastuuid": "==0.14.0+blue.1",
    }
    for r in constraints:
        assert r.marker is not None
        assert r.marker.evaluate({"python_version": "3.15"})
        assert not r.marker.evaluate({"python_version": "3.12"})


def test_patch_rejects_unverified_input(tmp_path: Path) -> None:
    patch = load("patch-litellm-python315-wheel")
    source = tmp_path / "litellm-1.106.5-cp310-abi3-macosx_11_0_arm64.whl"
    source.write_bytes(b"unverified")
    with pytest.raises(ValueError, match="checksum-verified"):
        patch.transform(source, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_patch_preserves_native_and_license_and_rebuilds_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch = load("patch-litellm-python315-wheel")
    source = tmp_path / "litellm-1.106.5-cp310-abi3-macosx_11_0_arm64.whl"
    info = "litellm-1.106.5.dist-info/"
    with zipfile.ZipFile(source, "w") as wheel:
        wheel.writestr(patch.CONFIG, b"def check():\n" + patch.OLD_IMPORTS)
        wheel.writestr(
            info + "METADATA",
            "Metadata-Version: 2.1\nName: litellm\nVersion: 1.106.5\n"
            "Requires-Python: >=3.10, <3.15\n\n",
        )
        wheel.writestr(info + "LICENSE", b"upstream license")
        wheel.writestr("litellm/native.abi3.so", b"native bytes")
        wheel.writestr(info + "RECORD", "")
    monkeypatch.setitem(
        patch.UPSTREAM_SHA256,
        "macosx_11_0_arm64",
        hashlib.sha256(source.read_bytes()).hexdigest(),
    )
    target = patch.transform(source, tmp_path / "out")
    with zipfile.ZipFile(target) as wheel:
        new_info = "litellm-" + patch.VERSION + ".dist-info/"
        assert wheel.read("litellm/native.abi3.so") == b"native bytes"
        assert wheel.read(new_info + "LICENSE") == b"upstream license"
        assert patch.NEW_IMPORTS in wheel.read(patch.CONFIG)
        assert b"Requires-Python: >=3.15, <3.16" in wheel.read(new_info + "METADATA")
        for name, digest, size in csv.reader(io.StringIO(wheel.read(new_info + "RECORD").decode())):
            if not digest:
                assert name == new_info + "RECORD"
                continue
            data = wheel.read(name)
            assert int(size) == len(data)
            encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
            assert digest == "sha256=" + encoded.decode()
    with pytest.raises(FileExistsError):
        patch.transform(source, tmp_path / "out")


def test_fastuuid_rejects_unverified_source(tmp_path: Path) -> None:
    build = load("build-python315-wheel")
    source = tmp_path / "source.tar.gz"
    source.write_bytes(b"unverified")
    with pytest.raises(ValueError, match="checksum"):
        build.prepare(source, tmp_path / "work")
    assert not (tmp_path / "work").exists()
