from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).parents[3]
CORE_SOURCE = PACKAGE_ROOT / "src" / "blue_data_ops"
MCP_SOURCE = PACKAGE_ROOT.parent / "platform" / "mcp" / "src"
SKILL_SOURCE = CORE_SOURCE / "operator_skills"
DISCLOSURE_RUNNER = PACKAGE_ROOT / "tests" / "installed" / "operator_skill_disclosure.py"
CORE_SOURCE_FILE_FLOOR = 73
MCP_SOURCE_FILE_FLOOR = 4
RESOURCE_TEXT_FLOOR = 18


def _imports_operator_skills(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            hits.extend(alias.name for alias in node.names if "operator_skills" in alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and "operator_skills" in node.module:
                hits.append(node.module)
        elif isinstance(node, ast.Call) and node.args:
            function_name = ""
            if isinstance(node.func, ast.Name):
                function_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                function_name = node.func.attr
            if function_name in {"__import__", "find_spec", "import_module"}:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    if "operator_skills" in first.value:
                        hits.append(first.value)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "operator_skills" in node.value:
                hits.append(node.value)
    return hits


def _runtime_source_paths() -> tuple[Path, ...]:
    assert CORE_SOURCE.is_dir()
    assert MCP_SOURCE.is_dir()
    core_paths = tuple(
        path for path in CORE_SOURCE.rglob("*.py") if not path.is_relative_to(SKILL_SOURCE)
    )
    mcp_paths = tuple(MCP_SOURCE.rglob("*.py"))
    assert len(core_paths) >= CORE_SOURCE_FILE_FLOOR
    assert len(mcp_paths) >= MCP_SOURCE_FILE_FLOOR
    return core_paths + mcp_paths


def _disclosure_environment(source_root: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, (str(source_root), os.environ.get("PYTHONPATH")))
    )
    return environment


def test_no_source_outside_the_loader_namespace_imports_operator_skills() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _runtime_source_paths():
        hits = _imports_operator_skills(path)
        if hits:
            offenders[str(path)] = hits
    assert offenders == {}


def test_resource_text_is_not_embedded_in_other_runtime_source() -> None:
    runtime_sources = "\n".join(
        path.read_text(encoding="utf-8") for path in _runtime_source_paths()
    )
    resources = tuple(SKILL_SOURCE.glob("*/*/*.md"))
    assert len(resources) >= RESOURCE_TEXT_FLOOR
    for resource in resources:
        text = resource.read_text(encoding="utf-8")
        assert text not in runtime_sources


def test_filesystem_audit_hook_has_positive_and_negative_controls() -> None:
    environment = _disclosure_environment(PACKAGE_ROOT / "src")
    positive = subprocess.run(
        [sys.executable, str(DISCLOSURE_RUNNER), "positive"],
        cwd=PACKAGE_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    negative = subprocess.run(
        [sys.executable, str(DISCLOSURE_RUNNER), "negative"],
        cwd=PACKAGE_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert '"events": ["_index.json"]' in positive.stdout
    assert '"events": []' in negative.stdout


def test_filesystem_audit_hook_observes_import_time_resource_reads(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    copied_package = source_root / "blue_data_ops"
    shutil.copytree(CORE_SOURCE, copied_package)
    initializer = copied_package / "operator_skills" / "__init__.py"
    with initializer.open("a", encoding="utf-8") as stream:
        stream.write(
            "\nfrom pathlib import Path as _Path\n"
            "_Path(__file__).with_name('_index.json').read_bytes()\n"
        )

    result = subprocess.run(
        [sys.executable, str(DISCLOSURE_RUNNER), "negative"],
        cwd=tmp_path,
        env=_disclosure_environment(source_root),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "implicit operator skill reads: ['_index.json']" in result.stderr


def test_disclosure_census_refuses_a_missing_mcp_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys.modules[__name__], "MCP_SOURCE", Path("missing-mcp-source"))
    with pytest.raises(AssertionError):
        _runtime_source_paths()
