from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest

from blue_data_ops.operators import versioned_registry
from tests.installed.operator_skill_release_gate import check_release

from ._settings_conformance import expected_skill_package_ids


def _metadata(name: str, version: str, requirements: tuple[str, ...] = ()) -> bytes:
    lines = [f"Name: {name}", f"Version: {version}"]
    lines.extend(f"Requires-Dist: {requirement}" for requirement in requirements)
    return ("\n".join(lines) + "\n\n").encode()


def _core_wheel(
    path: Path,
    *,
    operator_ids: tuple[str, ...] = ("synthetic@2.0.0",),
    omit_examples: bool = False,
    symlink_examples: bool = False,
) -> None:
    prefix = "blue_data_ops/operator_skills"
    guide = b"# Synthetic\n"
    examples = b"```python\nassert True\n```\n"
    packages: dict[str, str] = {}
    for operator_id in operator_ids:
        name, version = operator_id.split("@", 1)
        packages[operator_id] = f"{name}/{version}/manifest.json"
    index = {
        "format": "blue-data-ops/operator-skill-index@1",
        "packages": packages,
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "blue_data_ops-2.8.0.dist-info/METADATA", _metadata("blue-data-ops", "2.8.0")
        )
        archive.writestr(f"{prefix}/_index.json", json.dumps(index))
        for position, operator_id in enumerate(operator_ids):
            name, version = operator_id.split("@", 1)
            manifest = {
                "format": "blue-data-ops/operator-skill@1",
                "operator_id": operator_id,
                "resources": {
                    "guide": {
                        "path": "Operator.md",
                        "sha256": hashlib.sha256(guide).hexdigest(),
                    },
                    "examples": {
                        "path": "examples.md",
                        "sha256": hashlib.sha256(examples).hexdigest(),
                    },
                },
            }
            archive.writestr(f"{prefix}/{name}/{version}/manifest.json", json.dumps(manifest))
            archive.writestr(f"{prefix}/{name}/{version}/Operator.md", guide)
            if omit_examples:
                continue
            examples_path = f"{prefix}/{name}/{version}/examples.md"
            if symlink_examples and position == 0:
                member = zipfile.ZipInfo(examples_path)
                member.create_system = 3
                member.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(member, examples)
            else:
                archive.writestr(examples_path, examples)


def _mcp_wheel(path: Path, pin: str) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "blue_data_ops_mcp-0.10.0.dist-info/METADATA",
            _metadata("blue-data-ops-mcp", "0.10.0", (pin,)),
        )


def test_release_gate_binds_wheels_resources_and_exact_core_pin(tmp_path: Path) -> None:
    core = tmp_path / "core.whl"
    mcp = tmp_path / "mcp.whl"
    _core_wheel(core)
    _mcp_wheel(mcp, "blue-data-ops==2.8.0")

    assert check_release(
        core,
        mcp,
        expected_core_version="2.8.0",
        expected_mcp_version="0.10.0",
        expected_operator_ids=("synthetic@2.0.0",),
    ) == ("synthetic@2.0.0",)


@pytest.mark.parametrize("mutation", ("wrong-pin", "missing-resource", "symlink-resource"))
def test_release_gate_mutations_turn_the_instrument_red(tmp_path: Path, mutation: str) -> None:
    core = tmp_path / "core.whl"
    mcp = tmp_path / "mcp.whl"
    _core_wheel(
        core,
        omit_examples=mutation == "missing-resource",
        symlink_examples=mutation == "symlink-resource",
    )
    _mcp_wheel(mcp, "blue-data-ops==2.6.0" if mutation == "wrong-pin" else "blue-data-ops==2.8.0")

    with pytest.raises((AssertionError, KeyError)):
        check_release(
            core,
            mcp,
            expected_core_version="2.8.0",
            expected_mcp_version="0.10.0",
            expected_operator_ids=("synthetic@2.0.0",),
        )


def test_release_gate_rejects_a_self_consistent_package_omission(tmp_path: Path) -> None:
    core = tmp_path / "core.whl"
    mcp = tmp_path / "mcp.whl"
    expected = ("alpha@2.0.0", "beta@2.0.0")
    _core_wheel(core, operator_ids=expected[:1])
    _mcp_wheel(mcp, "blue-data-ops==2.8.0")

    with pytest.raises(AssertionError):
        check_release(
            core,
            mcp,
            expected_core_version="2.8.0",
            expected_mcp_version="0.10.0",
            expected_operator_ids=expected,
        )


def test_release_gate_accepts_the_runtime_derived_package_set(
    tmp_path: Path,
) -> None:
    core = tmp_path / "core.whl"
    mcp = tmp_path / "mcp.whl"
    expected = expected_skill_package_ids(versioned_registry())
    _core_wheel(core, operator_ids=expected)
    _mcp_wheel(mcp, "blue-data-ops==2.8.0")

    assert (
        check_release(
            core,
            mcp,
            expected_core_version="2.8.0",
            expected_mcp_version="0.10.0",
            expected_operator_ids=expected,
        )
        == expected
    )
