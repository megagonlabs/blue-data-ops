from __future__ import annotations

import argparse
import copy
import hashlib
import inspect
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.registry import OperatorCard, OperatorRegistry

LIB_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = LIB_ROOT / "tests" / "fixtures" / "active_operator_reference.json"
SUPPLEMENTAL_EVIDENCE_PATH = (
    LIB_ROOT / "tests" / "fixtures" / "sklearn_estimator_active_reference.json"
)
SUPPLEMENTAL_SOURCE_LOCATOR = "lib/tests/unit/operators/test_sklearn.py"
ACCEPTED_PROJECTION_SHA256 = "5c38499246bc80a503c17545fd37e2203384086b409573fdb3c453cedbffac3c"
# Keep archived evidence intact while binding maintenance changes to exact source.
_CURRENT_IMPLEMENTATION_BINDINGS: dict[str, tuple[str, str]] = {
    "nl2llm@3.0.0": (
        "706001762f6726246ce4e5becb0c2d15b66ced0ab1b1618d72e36de0fd054834",
        "90b1e4b8909537ec253b69851f5e44ed65690d6a55c1dd1ef45a3e249fbd48ee",
    ),
    "nl2bn@3.0.0": (
        "24a13f64ad56a20244426361c7eca61197cfcd009952f58a4eb09e0bb593a19c",
        "bffdf429bd7413b4ebc30b5e77c755f83767daca0e92266ca7c8a76a8a84b0b7",
    ),
}
SUPPLEMENTAL_ACCEPTED_PROJECTION_SHA256 = (
    "09420f91763092548d10b5918b39661ae724189728c8da537ef36810807802c8"
)
SOURCE_INSTRUMENT = {
    "instrument_id": "blue-data-ops-core-3.10-active-reference",
    "document_sha256": "dd8d4a6f0a251597e61bb3fbda867c995a03abf625f670b2ffda2423c83e2f1e",
    "seal_sha256": "63a789e59716b22426db62ed1ee6afb7d060e56cd589a84fe0a24f40216c8e24",
}
SUPPLEMENTAL_SOURCE_INSTRUMENT = {
    "instrument_id": "blue-data-ops-sklearn-estimator-2.0-regression-evidence-r2",
    "evidence_sha256": "855dd26d04cf42daa1c656444618baa35b468fcc1e0d724585177f2a97a988b6",
    "seal_sha256": "55f5e36b126e352c0476c19b23b09be1945eb30da4ca3ffa4aa8aa70c800caa8",
}
CORE_ACTIVE_IDS = (
    "argmax@2.0.0",
    "argmin@2.0.0",
    "avg@3.0.0",
    "classify@3.0.0",
    "cluster@3.0.0",
    "create_database@2.0.0",
    "create_table@2.0.0",
    "data_discover@2.0.0",
    "delete@2.0.0",
    "insert@3.0.0",
    "insert_table@3.0.0",
    "intersect@3.0.0",
    "join@3.0.0",
    "max@3.0.0",
    "min@3.0.0",
    "nl2bn@3.0.0",
    "nl2llm@3.0.0",
    "nl2sql@3.0.0",
    "normalize_text@2.0.0",
    "project@3.0.0",
    "segment_text@2.0.0",
    "select@2.0.0",
    "semantic_extract@3.0.0",
    "semantic_filter@3.0.0",
    "semantic_join@3.0.0",
    "semantic_project@3.0.0",
    "semantic_transform@3.0.0",
    "sum@2.0.0",
    "union@2.0.0",
    "vector_embed@3.0.0",
    "vector_search@3.0.0",
    "vector_similarity@3.0.0",
)
SUPPLEMENTAL_ACTIVE_IDS = ("sklearn_estimator@2.0.0",)
EXPECTED_ACTIVE_IDS = tuple(sorted((*CORE_ACTIVE_IDS, *SUPPLEMENTAL_ACTIVE_IDS)))
TOP_LEVEL_KEYS = {
    "schema_version",
    "source_instrument",
    "conversion",
    "active_ids",
    "rows",
    "projection_seal_sha256",
}
ROW_KEYS = {
    "operator_id",
    "name",
    "version",
    "implementation",
    "evidence",
    "claims",
    "dependency_profile",
    "discriminators",
}
CLAIM_KINDS = ("success", "empty", "invalid", "failure")
CLAIM_TEXT_OVERRIDES = {
    ("classify@3.0.0", "success"): (
        "Decision-tree training uses the first group and predicts across supplied groups."
    ),
    ("classify@3.0.0", "failure"): ("Ragged vectors are contained as EXECUTION_FAILED."),
    ("cluster@3.0.0", "success"): ("K-means produces stable cluster labels as record data."),
    ("cluster@3.0.0", "failure"): ("Ragged vectors are contained as an execution failure."),
    ("create_database@2.0.0", "success"): (
        "Creates a SQLite database while returning the input tensor unchanged."
    ),
    ("create_database@2.0.0", "empty"): (
        "An empty returned tensor can still represent successful database creation."
    ),
    ("create_database@2.0.0", "failure"): (
        "A RegistrySeam failure returns EXECUTION_FAILED rather than a successful result."
    ),
    ("create_table@2.0.0", "success"): (
        "Creates a SQLite table while returning the input tensor unchanged."
    ),
    ("create_table@2.0.0", "empty"): (
        "An empty returned tensor can still represent successful table creation."
    ),
    ("create_table@2.0.0", "failure"): (
        "A RegistrySeam failure returns EXECUTION_FAILED rather than a successful result."
    ),
    ("insert_table@3.0.0", "success"): (
        "Successful SQLite writes preserve all records and set num_rows_insert to the total "
        "inserted by the call."
    ),
    ("insert_table@3.0.0", "failure"): (
        "If a later batch fails a UNIQUE constraint, num_rows_insert is omitted even though "
        "rows committed by an earlier batch remain."
    ),
    ("nl2bn@3.0.0", "empty"): ("A backend result with zero rows is successful-empty."),
    ("select@2.0.0", "failure"): (
        "A lax eps string is contained as VALIDATION_FAILED at VALIDATE."
    ),
    ("vector_search@3.0.0", "success"): ("A declared top_k truncates the sorted hit records."),
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_evidence(
    path: Path = EVIDENCE_PATH,
    *,
    expected_sha256: str | None = ACCEPTED_PROJECTION_SHA256,
) -> dict[str, Any]:
    raw = path.read_bytes()
    if expected_sha256 is not None and _sha256(raw) != expected_sha256:
        raise ValueError(f"active-reference evidence digest mismatch: {path}")
    value: object = json.loads(raw, object_pairs_hook=_unique_object)
    if type(value) is not dict:
        raise ValueError("active-reference evidence must be a JSON object")
    return cast(dict[str, Any], value)


def _document_seal(document: dict[str, Any]) -> str:
    projection = copy.deepcopy(document)
    projection.pop("projection_seal_sha256", None)
    return _sha256(_canonical_bytes(projection))


def _supplemental_source_seal(
    source_instrument: dict[str, str],
    rows: tuple[dict[str, Any], ...],
) -> str:
    lines = [
        source_instrument["instrument_id"],
        f"{source_instrument['evidence_sha256']}  {SUPPLEMENTAL_SOURCE_LOCATOR}",
        *(
            f"{_sha256(_canonical_bytes(row))}  {row['operator_id']}"
            for row in sorted(rows, key=lambda row: row["operator_id"])
        ),
    ]
    return _sha256(("\n".join(lines) + "\n").encode())


def _validate_supplemental_source_instrument(
    rows: tuple[dict[str, Any], ...],
    *,
    source_instrument: dict[str, str] = SUPPLEMENTAL_SOURCE_INSTRUMENT,
) -> None:
    if set(source_instrument) != {
        "instrument_id",
        "evidence_sha256",
        "seal_sha256",
    }:
        raise ValueError("supplemental source instrument fields differ")
    locators = tuple(row["evidence"]["test_locator"]["node"] for row in rows)
    if locators != (SUPPLEMENTAL_SOURCE_LOCATOR,):
        raise ValueError("supplemental source evidence locator mismatch")
    if _supplemental_source_seal(source_instrument, rows) != source_instrument["seal_sha256"]:
        raise ValueError("supplemental source instrument seal mismatch")


def _validate_evidence(
    document: dict[str, Any],
    *,
    expected_active_ids: tuple[str, ...] = CORE_ACTIVE_IDS,
    source_instrument: dict[str, str] = SOURCE_INSTRUMENT,
) -> tuple[dict[str, Any], ...]:
    if set(document) != TOP_LEVEL_KEYS:
        raise ValueError("active-reference top-level keys differ")
    if document.get("schema_version") != 1:
        raise ValueError("active-reference schema_version must be 1")
    if document.get("source_instrument") != source_instrument:
        raise ValueError("active-reference source instrument provenance mismatch")
    raw_conversion = document.get("conversion")
    if type(raw_conversion) is not dict:
        raise ValueError("active-reference conversion provenance is incomplete")
    conversion = cast(dict[str, Any], raw_conversion)
    if set(conversion) != {
        "row_order",
        "identity",
        "result_projection",
        "evidence_schemas",
    }:
        raise ValueError("active-reference conversion provenance is incomplete")
    if any(not conversion[key] for key in conversion):
        raise ValueError("active-reference conversion provenance is empty")
    if _document_seal(document) != document.get("projection_seal_sha256"):
        raise ValueError("active-reference seal mismatch")
    if tuple(document.get("active_ids", ())) != expected_active_ids:
        raise ValueError("active-reference exact ID set or order mismatch")

    raw_rows = document.get("rows")
    if type(raw_rows) is not list:
        raise ValueError("active-reference rows must be objects")
    rows = cast(list[object], raw_rows)
    if any(type(row) is not dict for row in rows):
        raise ValueError("active-reference rows must be objects")
    typed_rows = cast(list[dict[str, Any]], rows)
    row_ids = tuple(row.get("operator_id") for row in typed_rows)
    if len(set(row_ids)) != len(row_ids):
        raise ValueError("active-reference contains duplicate operator rows")
    if row_ids != expected_active_ids:
        raise ValueError("active-reference row set or order mismatch")

    for row in typed_rows:
        if set(row) != ROW_KEYS:
            raise ValueError(f"{row.get('operator_id')}: active-reference row keys differ")
        operator_id = row["operator_id"]
        name, separator, version = operator_id.partition("@")
        if not separator or row["name"] != name or row["version"] != version:
            raise ValueError(f"{operator_id}: name/version provenance mismatch")

        raw_implementation = row.get("implementation")
        if type(raw_implementation) is not dict:
            raise ValueError(f"{operator_id}: implementation provenance is incomplete")
        implementation = cast(dict[str, Any], raw_implementation)
        if set(implementation) != {
            "path",
            "sha256",
            "symbol",
            "module",
        }:
            raise ValueError(f"{operator_id}: implementation provenance is incomplete")
        implementation_path = implementation.get("path")
        if (
            type(implementation_path) is not str
            or not implementation_path
            or Path(implementation_path).is_absolute()
            or ".." in Path(implementation_path).parts
            or not implementation_path.startswith("src/blue_data_ops/operators/")
            or len(str(implementation.get("sha256", ""))) != 64
        ):
            raise ValueError(f"{operator_id}: implementation locator is invalid")

        raw_evidence = row.get("evidence")
        if type(raw_evidence) is not dict:
            raise ValueError(f"{operator_id}: evidence provenance is incomplete")
        evidence = cast(dict[str, Any], raw_evidence)
        if set(evidence) != {
            "source_kind",
            "schema",
            "original_operator_id",
            "test_locator",
        }:
            raise ValueError(f"{operator_id}: evidence provenance is incomplete")
        if evidence.get("original_operator_id") != operator_id:
            raise ValueError(f"{operator_id}: original exact evidence ID mismatch")
        if evidence.get("source_kind") not in {
            "accepted runtime observation",
            "accepted expected case",
        } or evidence.get("schema") not in {"observations", "cases"}:
            raise ValueError(f"{operator_id}: evidence source is invalid")
        if (evidence["source_kind"], evidence["schema"]) not in {
            ("accepted runtime observation", "observations"),
            ("accepted expected case", "cases"),
        }:
            raise ValueError(f"{operator_id}: evidence source/schema mismatch")
        raw_locator = evidence.get("test_locator")
        if type(raw_locator) is not dict:
            raise ValueError(f"{operator_id}: evidence test locator is missing")
        locator = cast(dict[str, Any], raw_locator)
        if set(locator) != {"kind", "node"}:
            raise ValueError(f"{operator_id}: evidence test locator is missing")
        if locator.get("kind") not in {
            "acceptance probe",
            "product regression test",
        } or not locator.get("node"):
            raise ValueError(f"{operator_id}: evidence test locator is missing")

        raw_claims = row.get("claims")
        if type(raw_claims) is not dict:
            raise ValueError(f"{operator_id}: claim inventory differs")
        claims = cast(dict[str, Any], raw_claims)
        if tuple(claims) != CLAIM_KINDS:
            raise ValueError(f"{operator_id}: claim inventory differs")
        supported_case_ids: list[str] = []
        for kind in CLAIM_KINDS:
            raw_claim = claims[kind]
            if type(raw_claim) is not dict:
                raise ValueError(f"{operator_id}: {kind} claim is not an object")
            claim = cast(dict[str, Any], raw_claim)
            if claim.get("status") == "supported":
                if (
                    set(claim) != {"status", "case_id", "summary"}
                    or not claim.get("case_id")
                    or not claim.get("summary")
                ):
                    raise ValueError(f"{operator_id}: supported {kind} claim is incomplete")
                supported_case_ids.append(claim["case_id"])
            elif claim.get("status") in {"not_observed", "not_applicable"}:
                if set(claim) != {"status", "reason"} or not claim.get("reason"):
                    raise ValueError(f"{operator_id}: unsupported {kind} reason is missing")
            else:
                raise ValueError(f"{operator_id}: unknown {kind} claim status")
        if len(set(supported_case_ids)) < 2:
            raise ValueError(f"{operator_id}: fewer than two distinct supported evidence cases")
    return tuple(typed_rows)


def _load_combined_rows(
    evidence_path: Path = EVIDENCE_PATH,
    supplemental_evidence_path: Path = SUPPLEMENTAL_EVIDENCE_PATH,
) -> tuple[dict[str, Any], ...]:
    core = _load_evidence(evidence_path)
    supplemental = _load_evidence(
        supplemental_evidence_path,
        expected_sha256=SUPPLEMENTAL_ACCEPTED_PROJECTION_SHA256,
    )
    core_rows = _validate_evidence(core)
    supplemental_rows = _validate_evidence(
        supplemental,
        expected_active_ids=SUPPLEMENTAL_ACTIVE_IDS,
        source_instrument=SUPPLEMENTAL_SOURCE_INSTRUMENT,
    )
    _validate_supplemental_source_instrument(supplemental_rows)
    rows_by_id = {row["operator_id"]: row for row in (*core_rows, *supplemental_rows)}
    if len(rows_by_id) != len(core_rows) + len(supplemental_rows):
        raise ValueError("active-reference evidence sets overlap")
    if tuple(sorted(rows_by_id)) != EXPECTED_ACTIVE_IDS:
        raise ValueError("combined active-reference exact ID set or order mismatch")
    for operator_id, (
        archived_sha256,
        current_sha256,
    ) in _CURRENT_IMPLEMENTATION_BINDINGS.items():
        row = rows_by_id[operator_id]
        if row["implementation"]["sha256"] != archived_sha256:
            raise ValueError(f"{operator_id}: archived implementation identity mismatch")
        current_row = copy.deepcopy(row)
        current_row["implementation"]["sha256"] = current_sha256
        rows_by_id[operator_id] = current_row
    return tuple(rows_by_id[operator_id] for operator_id in EXPECTED_ACTIVE_IDS)


def _active_registry() -> OperatorRegistry:
    from blue_data_ops.operators import active_registry

    return active_registry()


def _validate_registry(
    registry: OperatorRegistry, rows: tuple[dict[str, Any], ...]
) -> tuple[tuple[OperatorCard, Operator, dict[str, Any]], ...]:
    if tuple(row["operator_id"] for row in rows) != EXPECTED_ACTIVE_IDS:
        raise ValueError("combined active-reference row set or order mismatch")
    cards = tuple(registry.list_cards())
    card_ids = tuple(card.operator_id for card in cards)
    if card_ids != EXPECTED_ACTIVE_IDS:
        raise ValueError(f"active_registry() exact ID set or order mismatch: {card_ids!r}")

    bound: list[tuple[OperatorCard, Operator, dict[str, Any]]] = []
    for card, row in zip(cards, rows, strict=True):
        operator = registry.resolve(card.operator_id)
        implementation = row["implementation"]
        operator_type = type(operator)
        if (
            operator_type.__module__ != implementation["module"]
            or operator_type.__name__ != implementation["symbol"]
        ):
            raise ValueError(f"{card.operator_id}: live implementation identity mismatch")
        source_name = inspect.getsourcefile(operator_type)
        if source_name is None:
            raise ValueError(f"{card.operator_id}: live implementation has no source file")
        source_path = Path(source_name).resolve()
        try:
            relative_source = source_path.relative_to(LIB_ROOT.resolve()).as_posix()
        except ValueError as error:
            raise ValueError(
                f"{card.operator_id}: live implementation is outside the source tree"
            ) from error
        if relative_source != implementation["path"]:
            raise ValueError(f"{card.operator_id}: live implementation path mismatch")
        expected_source_sha256 = implementation["sha256"]
        if _sha256(source_path.read_bytes()) != expected_source_sha256:
            raise ValueError(f"{card.operator_id}: live implementation digest mismatch")
        bound.append((card, operator, row))
    return tuple(bound)


def _display(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _format_reference(markdown: str) -> str:
    command = [
        sys.executable,
        "-m",
        "ruff",
        "format",
        "--preview",
        "--no-cache",
        "--config",
        str(LIB_ROOT / "pyproject.toml"),
        "--stdin-filename",
        str(LIB_ROOT / "OPERATORS.md"),
        "-",
    ]
    result = subprocess.run(
        command,
        input=markdown,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        message = "Ruff could not format OPERATORS.md"
        raise RuntimeError(f"{message}: {detail}" if detail else message)
    return result.stdout


def _claim_text(operator_id: str, kind: str, claim: dict[str, Any]) -> str | None:
    if claim["status"] == "not_observed":
        return None
    if claim["status"] == "not_applicable" and (operator_id, kind) != (
        "sum@2.0.0",
        "empty",
    ):
        return None
    text = CLAIM_TEXT_OVERRIDES.get(
        (operator_id, kind),
        claim.get("summary") or claim["reason"],
    )
    return text


def _render_unformatted_reference(
    registry: OperatorRegistry,
    rows: tuple[dict[str, Any], ...],
) -> str:
    bound = _validate_registry(registry, rows)
    tag_axes: dict[str, set[str]] = defaultdict(set)
    for card, _, _ in bound:
        for tag in card.tags:
            tag_axes[tag.split("-", 1)[0]].add(tag)

    lines = [
        "# Operator reference",
        "",
        "This reference covers the 33 exact cards selected by `active_registry()`. Each outcome",
        "table summarizes the behavior documented for that exact version.",
        "",
        "```python",
        "from blue_data_ops.operators import active_registry",
        "",
        "registry = active_registry()",
        "assert len(registry.list_cards()) == 33",
        "```",
        "",
        "## Tag taxonomy",
        "",
        "This table is derived from the 33 active cards. Built-in tags use five required axes and",
        "one optional axis. A tag states something true in at least one productive public mode.",
        "Tags are flat, exact-match labels with no parent-child relationships.",
        "",
        "| Axis | Meaning | Built-in cardinality | Active values |",
        "|---|---|---|---|",
    ]
    meanings = {
        "domain": ("primary subject area, not the output type", "exactly one"),
        "flow": ("valid role in a pipeline", "one or more"),
        "accepts": ("kind of upstream input accepted", "one or more"),
        "produces": ("result kind or externally visible effect", "one or more"),
        "capability": ("operation family or specific action", "one or more"),
        "requires": (
            "unconditional operator-specific runtime requirement",
            "zero or more",
        ),
    }
    axis_order = [axis for axis in meanings if axis in tag_axes]
    axis_order.extend(sorted(tag_axes.keys() - meanings.keys()))
    for axis in axis_order:
        values = ", ".join(f"`{tag}`" for tag in sorted(tag_axes[axis]))
        meaning, cardinality = meanings.get(axis, ("operator metadata", "custom"))
        lines.append(f"| `{axis}-*` | {meaning} | {cardinality} | {values} |")
    lines.extend(
        [
            "",
            "`accepts-none` means that records are not consumed; callers still pass `input_data`,",
            "such as an empty `[[]]` bundle. A card can carry broad and specific capabilities",
            "together. The `requires-*` axis covers operator-specific requirements, not",
            "package-wide install requirements. The active `domain-plan` value is a retained",
            "compatibility label on `data_discover@2.0.0`; use `capability-metadata-search` or",
            "`produces-metadata` to find its behavior. Its result holds registry identities",
            "and an optional search score; stored metadata remains in the registry.",
            "",
            "`find()` strips surrounding whitespace and lowercases requested filters. A filter",
            "passes shape validation when the result is nonempty, contains no whitespace, and",
            "includes at least one hyphen. It is then matched as a complete tag. Shape validation",
            "does not check taxonomy membership or hyphen position. The filters `domain-`,",
            "`-vector`, and `domain_-vector` are well-formed but match no built-in card.",
            "Malformed filters raise `DiscoveryError`; well-formed absent tags match no cards.",
            "There is no OR or negative-tag syntax. A blank query with tags performs tag-only",
            "discovery; a blank query without tags returns no cards.",
            "",
            "```python",
            "vector_steps = registry.find(",
            '    "",',
            '    tags=["domain-vector", "flow-transform"],',
            ")",
            "assert [card.operator_id for card in vector_steps] == [",
            '    "vector_embed@3.0.0",',
            '    "vector_search@3.0.0",',
            "]",
            "",
            "cards = registry.find(",
            '    "filter",',
            '    tags=["domain-relational", "flow-transform"],',
            ")",
            'assert [card.operator_id for card in cards] == ["select@2.0.0"]',
            "```",
            "",
            "Inspect `card.tags` when composing filters dynamically. Built-in package cards use a",
            "closed vocabulary. `register()` preserves arbitrary custom tags for compatibility.",
            "Filters are normalized as described above, so a custom tag is discoverable only when",
            "its stored value equals the normalized filter.",
            "",
        ]
    )

    for card, operator, row in bound:
        implementation = row["implementation"]
        name, version = card.operator_id.split("@", 1)
        lines.extend(
            [
                f"## `{card.operator_id}`",
                "",
                f"When to invoke: {card.when_to_invoke}",
                "",
                "Tags: " + ", ".join(f"`{tag}`" for tag in card.tags),
                "",
                (
                    f"Guide: [`{card.operator_id}`](src/blue_data_ops/operator_skills/"
                    f"{name}/{version}/Operator.md)"
                ),
                "",
                "| Attribute | Type | Required | Default | Description |",
                "|---|---|---:|---|---|",
            ]
        )
        if operator.attributes:
            for attribute, specification in operator.attributes.items():
                default = _display(specification.default) if specification.has_default else "—"
                description = specification.description.replace("|", "\\|").replace("\n", " ")
                lines.append(
                    f"| `{attribute}` | `{specification.type}` | "
                    f"{'yes' if specification.required else 'no'} | `{default}` | {description} |"
                )
        else:
            lines.append("| _none_ | — | — | — | — |")
        lines.extend(
            [
                "",
                "Exact resolution:",
                "",
                "```python",
                f"operator = registry.resolve({card.operator_id!r})",
                f"assert type(operator).__module__ == {implementation['module']!r}",
                f"assert type(operator).__name__ == {implementation['symbol']!r}",
                "```",
                "",
                "| Outcome | Behavior |",
                "|---|---|",
            ]
        )
        for kind in CLAIM_KINDS:
            text = _claim_text(card.operator_id, kind, row["claims"][kind])
            if text is None:
                continue
            lines.append(f"| {kind.capitalize()} | {text} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_reference(
    registry: OperatorRegistry | None = None,
    *,
    evidence_path: Path = EVIDENCE_PATH,
    supplemental_evidence_path: Path = SUPPLEMENTAL_EVIDENCE_PATH,
) -> str:
    rows = _load_combined_rows(evidence_path, supplemental_evidence_path)
    live_registry = _active_registry() if registry is None else registry
    return _format_reference(_render_unformatted_reference(live_registry, rows))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=LIB_ROOT / "OPERATORS.md")
    args = parser.parse_args()
    expected = render_reference()
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != expected:
            raise SystemExit(f"{args.output} is not current; regenerate it")
        return
    args.output.write_text(expected, encoding="utf-8")


if __name__ == "__main__":
    main()
