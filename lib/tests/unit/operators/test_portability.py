"""Import-boundary checks for package portability.

The package must not import the legacy `blue` package (`import blue` / `from blue…`).
`blue_data` is permitted only for data-touching operators; `blue_data_ops` (self) is
always allowed; relative imports are internal. For `select` (pure compute), not even
`blue_data` is allowed.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import cast

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


_ID_LETTERS = "".join(["D", "C", "K"])
_ID_PATTERN = __import__("re").compile(r"\b[" + _ID_LETTERS + r"]\d{1,3}\b")

_PATH_FRAGMENTS = [
    "".join(["comms", "/", "parallel"]),
    "".join(["tool", "s", "/", "v2-"]),
    "".join(["k0", "_", "oracle"]),
    "".join(["audit", "_", "harness"]),
    "".join(["repo", "-", "org"]),
]
_VOCAB_WORDS = [
    "".join(["auto", "eng"]),
    "".join(["blue", "-", "dev"]),
    "".join(["release", "_", "audit"]),
    "".join(["release", "_", "repair"]),
    "".join(["release", "-", "audit"]),
    "".join(["release", "-", "repair"]),
    "".join(["audit", "-", "state"]),
    "".join(["decision", "-", "state"]),
    "".join(["progress", "-", "state"]),
    "".join(["repair", "-", "state"]),
]


def _scan_prose_text(content: str) -> list[str]:
    """Flag internal decision/checkpoint IDs and repo path/vocabulary leaks in free text."""
    hits: list[str] = []
    for match in _ID_PATTERN.finditer(content):
        hits.append(f"internal decision/checkpoint id: {match.group()}")
    for fragment in _PATH_FRAGMENTS:
        if fragment in content:
            hits.append(f"internal path fragment: {fragment}")
    for word in _VOCAB_WORDS:
        if word in content.lower():
            hits.append(f"internal vocabulary: {word}")
    return hits


def _scan_python_source(content: str, label: str) -> list[str]:
    """Flag leaks in a Python file: IDs only inside comments/docstrings, paths/vocab anywhere."""
    import ast
    import io
    import tokenize

    hits: list[str] = []

    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        raise AssertionError(f"cannot parse {label}: {exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                for match in _ID_PATTERN.finditer(doc):
                    hits.append(f"internal decision/checkpoint id in docstring: {match.group()}")

    try:
        for tok in tokenize.generate_tokens(io.StringIO(content).readline):
            if tok.type == tokenize.COMMENT:
                for match in _ID_PATTERN.finditer(tok.string):
                    hits.append(
                        f"internal decision/checkpoint id in comment at line {tok.start[0]}: "
                        f"{match.group()}"
                    )
    except tokenize.TokenError as exc:
        raise AssertionError(f"cannot tokenize {label}: {exc}") from exc

    for fragment in _PATH_FRAGMENTS:
        if fragment in content:
            hits.append(f"internal path fragment: {fragment}")
    for word in _VOCAB_WORDS:
        if word in content.lower():
            hits.append(f"internal vocabulary: {word}")

    return hits


_ID_PATTERN_CI = __import__("re").compile(_ID_PATTERN.pattern, __import__("re").IGNORECASE)


def _scan_fixture_string_fragments(content: str) -> list[str]:
    """Flag internal path/vocabulary leaks in a fixture string (no ID-pattern check)."""
    hits: list[str] = []
    for fragment in _PATH_FRAGMENTS:
        if fragment in content:
            hits.append(f"internal path fragment: {fragment}")
    for word in _VOCAB_WORDS:
        if word in content.lower():
            hits.append(f"internal vocabulary: {word}")
    return hits


def _scan_json_fixture(content: str, label: str) -> list[str]:
    """Flag checkpoint-derived schema values leaking into a shipped JSON fixture.

    Checkpoint/decision IDs (D/C/K + digits) are only meaningful in a ``schema_version``
    value, so only that key is checked for them, case-insensitively. Every JSON string
    value (regardless of key) is still checked for internal path/vocabulary fragments, so
    ordinary data values stay clean while a leaked schema checkpoint id, including
    lowercase forms, is caught.
    """
    import json

    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"cannot parse fixture {label}: {exc}") from exc

    hits: list[str] = []

    def _walk(node: object, key: str | None) -> None:
        if isinstance(node, dict):
            for child_key, value in cast("dict[str, object]", node).items():
                _walk(value, child_key)
        elif isinstance(node, list):
            for item in cast("list[object]", node):
                _walk(item, key)
        elif isinstance(node, str):
            hits.extend(f"fixture value: {hit}" for hit in _scan_fixture_string_fragments(node))
            if key == "schema_version":
                for match in _ID_PATTERN_CI.finditer(node):
                    hits.append(
                        f"fixture value: internal decision/checkpoint id in schema_version: "
                        f"{match.group()}"
                    )

    _walk(payload, None)
    return hits


def _filename_component_hits(path: Path) -> list[str]:
    """Flag checkpoint-derived components in a scanned file's own name."""
    import re as _re

    hits: list[str] = []
    components = _re.split(r"[^A-Za-z0-9]+", path.stem)
    id_ci_pattern = __import__("re").compile(
        r"^[" + _ID_LETTERS + _ID_LETTERS.lower() + r"]\d{1,3}$"
    )
    for component in components:
        if component and id_ci_pattern.fullmatch(component):
            hits.append(f"checkpoint-derived filename component: {component}")
    return hits


def _shipped_portability_paths(lib_root: Path) -> tuple[Path, ...]:
    """Return every release path owned by the portability scan."""

    core_src = lib_root / "src" / "blue_data_ops"
    core_tests = lib_root / "tests"
    mcp_root = lib_root.parent / "platform" / "mcp"
    mcp_src = mcp_root / "src"
    mcp_tests = mcp_root / "tests"
    required_directories = (
        core_src,
        core_tests,
        lib_root / "examples",
        lib_root / "scripts",
        mcp_src,
        mcp_tests,
    )
    required_files = (
        lib_root / "pyproject.toml",
        lib_root / "README.md",
        lib_root / "COMPATIBILITY.md",
        lib_root / "MANIFEST.in",
        lib_root / "OPERATORS.md",
        mcp_root / "pyproject.toml",
        mcp_root / "README.md",
    )
    for path in required_directories:
        assert path.is_dir(), f"expected shipped portability directory is missing: {path}"
    for path in required_files:
        assert path.is_file(), f"expected shipped portability file is missing: {path}"

    paths = set(required_files)
    for root in (
        core_src,
        core_tests,
        lib_root / "examples",
        lib_root / "scripts",
        mcp_src,
        mcp_tests,
    ):
        paths.update(
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix in {".py", ".json", ".md"}
        )
    return tuple(sorted(paths))


def _scan_shipped_portability(lib_root: Path) -> dict[str, list[str]]:
    violations: dict[str, list[str]] = {}
    for path in _shipped_portability_paths(lib_root):
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise AssertionError(f"cannot read {path}: {exc}") from exc
        if path.suffix == ".py":
            hits = _scan_python_source(content, str(path))
        elif path.suffix == ".json":
            hits = _scan_json_fixture(content, str(path))
        else:
            hits = _scan_prose_text(content)
        hits.extend(_filename_component_hits(path))
        if hits:
            violations[str(path)] = hits
    return violations


def test_no_internal_checkpoint_leaks_in_shipped_sources() -> None:
    """Scan core and MCP source, resources, metadata, docs, and tests."""

    lib_root = Path(PACKAGE_DIR).parents[1]
    violations = _scan_shipped_portability(lib_root)
    assert not violations, f"internal process tokens leaked in shipped sources: {violations}"


def _minimal_release_tree(root: Path) -> Path:
    lib_root = root / "lib"
    mcp_root = root / "platform" / "mcp"
    for directory in (
        lib_root / "src" / "blue_data_ops",
        lib_root / "tests",
        lib_root / "examples",
        lib_root / "scripts",
        mcp_root / "src" / "blue_data_ops_mcp",
        mcp_root / "tests",
    ):
        directory.mkdir(parents=True)
    for path in (
        lib_root / "pyproject.toml",
        lib_root / "README.md",
        lib_root / "COMPATIBILITY.md",
        lib_root / "MANIFEST.in",
        lib_root / "OPERATORS.md",
        mcp_root / "pyproject.toml",
        mcp_root / "README.md",
    ):
        path.write_text("ordinary package text\n", encoding="utf-8")
    return lib_root


@pytest.mark.parametrize(
    ("relative_path", "content"),
    [
        (
            "lib/src/blue_data_ops/operator_skills/guide.md",
            "see decision " + "D" + "39\n",
        ),
        (
            "lib/src/blue_data_ops/operator_skills/manifest.json",
            '{"schema_version": "' + "k" + '3-review"}\n',
        ),
        ("lib/OPERATORS.md", "see decision " + "D" + "39\n"),
        ("lib/MANIFEST.in", "# see decision " + "D" + "39\n"),
        ("lib/examples/example.py", "# see decision " + "D" + "39\n"),
        ("lib/examples/coverage.json", '{"schema_version": "' + "k" + '3-review"}\n'),
        ("lib/scripts/check.py", "# see decision " + "D" + "39\n"),
        ("platform/mcp/README.md", "see decision " + "D" + "39\n"),
        ("platform/mcp/pyproject.toml", "# see decision " + "D" + "39\n"),
        (
            "platform/mcp/src/blue_data_ops_mcp/leak.py",
            "# see decision " + "D" + "39\n",
        ),
        (
            "platform/mcp/tests/leak.py",
            "# see decision " + "D" + "39\n",
        ),
    ],
    ids=[
        "core-markdown",
        "core-json",
        "operator-reference",
        "source-manifest",
        "example-python",
        "example-json",
        "script-python",
        "mcp-readme",
        "mcp-metadata",
        "mcp-source",
        "mcp-test",
    ],
)
def test_shipped_portability_scanner_reaches_new_release_paths(
    tmp_path: Path,
    relative_path: str,
    content: str,
) -> None:
    lib_root = _minimal_release_tree(tmp_path)
    target = tmp_path / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    violations = _scan_shipped_portability(lib_root)

    assert str(target) in violations


def test_shipped_portability_scanner_refuses_a_file_in_place_of_a_required_root(
    tmp_path: Path,
) -> None:
    lib_root = _minimal_release_tree(tmp_path)
    mcp_tests = tmp_path / "platform" / "mcp" / "tests"
    mcp_tests.rmdir()
    mcp_tests.write_text("ordinary package text\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="expected shipped portability directory is missing"):
        _scan_shipped_portability(lib_root)


def test_shipped_portability_scanner_allows_ordinary_product_terms(tmp_path: Path) -> None:
    lib_root = _minimal_release_tree(tmp_path)
    resources = lib_root / "src" / "blue_data_ops" / "operator_skills"
    resources.mkdir(parents=True)
    (resources / "guide.md").write_text(
        "An operator returns candidate plans for an internal source.\n",
        encoding="utf-8",
    )
    (resources / "manifest.json").write_text(
        '{"schema_version": "2.0.0", "source": "internal", "kind": "candidate"}\n',
        encoding="utf-8",
    )

    assert _scan_shipped_portability(lib_root) == {}


def test_checkpoint_leak_scanner_is_mutation_sensitive() -> None:
    """Prove the scanner actually detects leaks rather than passing vacuously."""
    decision_reference = "see the " + "D" + "39" + " decision review"
    comment_source = f"# {decision_reference}\nx = 1\n"
    comment_hits = _scan_python_source(comment_source, "mutated-comment.py")
    assert any("comment" in hit for hit in comment_hits), (
        "scanner failed to catch a constructed decision id inside a comment"
    )

    internal_path = "".join(["comms", "/", "parallel"])
    path_source = f"NOTE = {internal_path!r}\n"
    path_hits = _scan_python_source(path_source, "mutated-path.py")
    assert any("path fragment" in hit for hit in path_hits), (
        "scanner failed to catch an internal path leaked into ordinary source"
    )

    ordinary_source = "RECORDS = {'K5': 'REC2'}\n"
    ordinary_hits = _scan_python_source(ordinary_source, "ordinary-data.py")
    assert not ordinary_hits, (
        f"scanner incorrectly flagged ordinary quoted K5/REC2 data: {ordinary_hits}"
    )

    lowercase_checkpoint = "k3-outcome-closure/1"
    schema_version_leak = '{"schema_version": "' + lowercase_checkpoint + '"}'
    schema_version_hits = _scan_json_fixture(schema_version_leak, "mutated-schema-version.json")
    assert any("schema_version" in hit for hit in schema_version_hits), (
        "scanner failed to catch a lowercase checkpoint id in a schema_version fixture value"
    )

    ordinary_json = '{"K5": "REC2"}'
    ordinary_json_hits = _scan_json_fixture(ordinary_json, "ordinary-fixture.json")
    assert not ordinary_json_hits, (
        f"scanner incorrectly flagged ordinary K5/REC2 JSON data: {ordinary_json_hits}"
    )

    assert _filename_component_hits(Path("test_v3_d37_migration.py"))
