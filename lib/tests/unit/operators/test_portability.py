"""Import-boundary checks for package portability.

The package must not import the legacy `blue` package (`import blue` / `from blue…`).
`blue_data` is permitted only for data-touching operators; `blue_data_ops` (self) is
always allowed; relative imports are internal. For `select` (pure compute), not even
`blue_data` is allowed.
"""

from __future__ import annotations

import ast
import os

import pytest

import blue_data_ops

PACKAGE_DIR = os.path.dirname(os.path.abspath(blue_data_ops.__file__))


def _iter_py_files(root: str) -> list[str]:
    paths: list[str] = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith(".py"):
                paths.append(os.path.join(dirpath, name))
    return paths


def _absolute_import_roots(path: str) -> set[str]:
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_no_legacy_blue_imports() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _iter_py_files(PACKAGE_DIR):
        roots = _absolute_import_roots(path)
        if "blue" in roots:
            offenders[os.path.relpath(path, PACKAGE_DIR)] = sorted(roots)
    assert not offenders, f"legacy blue imports leaked into the package: {offenders}"


def test_blue_data_only_inside_data_boundary() -> None:
    # blue_data_ops/data/ is the ONE place allowed to import blue_data; any other
    # module importing it breaches the seam boundary.
    offenders: list[str] = []
    for path in _iter_py_files(PACKAGE_DIR):
        relative = os.path.relpath(path, PACKAGE_DIR)
        if "blue_data" in _absolute_import_roots(path) and not relative.startswith("data" + os.sep):
            offenders.append(relative)
    assert not offenders, f"blue_data imported outside the data/ boundary: {offenders}"


def test_select_is_pure_compute() -> None:
    select_path = os.path.join(PACKAGE_DIR, "operators", "select_operator.py")
    forbidden = _absolute_import_roots(select_path) & {"blue", "blue_data"}
    assert not forbidden, f"select_operator.py must be pure-compute; found: {sorted(forbidden)}"


def test_project_is_pure_compute() -> None:
    project_path = os.path.join(PACKAGE_DIR, "operators", "project_operator.py")
    forbidden = _absolute_import_roots(project_path) & {"blue", "blue_data"}
    assert not forbidden, f"project_operator.py must be pure-compute; found: {sorted(forbidden)}"


@pytest.mark.parametrize(
    "module_name", ["join_operator", "union_operator", "intersect_operator", "_record_matching"]
)
def test_relational_modules_are_pure_compute(module_name: str) -> None:
    module_path = os.path.join(PACKAGE_DIR, "operators", f"{module_name}.py")
    forbidden = _absolute_import_roots(module_path) & {"blue", "blue_data"}
    assert not forbidden, f"{module_name}.py must be pure-compute: {sorted(forbidden)}"


@pytest.mark.parametrize(
    "module_name",
    ["delete_operator", "insert_operator", "normalize_text_operator", "segment_text_operator"],
)
def test_pure_b_modules_are_pure_compute(module_name: str) -> None:
    module_path = os.path.join(PACKAGE_DIR, "operators", f"{module_name}.py")
    forbidden = _absolute_import_roots(module_path) & {"blue", "blue_data"}
    assert not forbidden, f"{module_name}.py must be pure-compute: {sorted(forbidden)}"


@pytest.mark.parametrize(
    "module_name",
    [
        "classify_operator",
        "cluster_operator",
        "vector_embed_operator",
        "vector_search_operator",
        "vector_similarity_operator",
    ],
)
def test_heavy_modules_remain_blue_independent(module_name: str) -> None:
    module_path = os.path.join(PACKAGE_DIR, "operators", f"{module_name}.py")
    forbidden = _absolute_import_roots(module_path) & {"blue", "blue_data"}
    assert not forbidden, f"{module_name}.py must remain portable: {sorted(forbidden)}"


@pytest.mark.parametrize(
    "module_name",
    [
        "semantic_extract_operator",
        "semantic_filter_operator",
        "semantic_join_operator",
        "semantic_project_operator",
        "semantic_transform_operator",
    ],
)
def test_semantic_modules_remain_blue_independent(module_name: str) -> None:
    module_path = os.path.join(PACKAGE_DIR, "operators", f"{module_name}.py")
    forbidden = _absolute_import_roots(module_path) & {"blue", "blue_data"}
    assert not forbidden, f"{module_name}.py must remain portable: {sorted(forbidden)}"


def test_llm_deps_only_inside_llm_boundary() -> None:
    # blue_data_ops/llm/ is the ONE place allowed to import litellm/tenacity/diskcache.
    offenders: list[str] = []
    for path in _iter_py_files(PACKAGE_DIR):
        relative = os.path.relpath(path, PACKAGE_DIR)
        roots = _absolute_import_roots(path)
        if roots & {"litellm", "tenacity", "diskcache"} and not relative.startswith("llm" + os.sep):
            offenders.append(relative)
    assert not offenders, f"llm deps imported outside the llm/ boundary: {offenders}"
