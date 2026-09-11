from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from blue_data_ops.operators import versioned_registry

LIB_ROOT = Path(__file__).resolve().parents[1]
OUTCOMES_PATH = LIB_ROOT / "tests" / "fixtures" / "v2_operator_outcomes.json"
DEPRECATION_NOTICE = (
    "**Deprecated in 2.8.0; removed in 3.0.0.** Both registered versions carry the lifecycle "
    "flag, and calls emit a `BlueDataOpsDeprecationWarning`. See "
    "[COMPATIBILITY.md](COMPATIBILITY.md#deprecated-in-280)."
)


def _display(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _case_summary(case: dict[str, Any] | None) -> str:
    if case is None:
        return "No separate fixture case."
    parts: list[str] = []
    if case.get("is_empty") is True:
        parts.append("successful empty result")
    if "code" in case:
        parts.append(f"`{case['code']}` at `{case['stage']}`")
    if "suggestion_substr" in case:
        parts.append(f"validation suggestion contains `{case['suggestion_substr']}`")
    if "expected_output" in case and case["expected_output"] is not None:
        parts.append(f"output `{_display(case['expected_output'])}`")
    if not parts:
        parts.append(case.get("note", "fixture-backed case"))
    return "; ".join(parts) + "."


def _format_reference(markdown: str) -> str:
    command = [
        sys.executable,
        "-m",
        "ruff",
        "format",
        "--no-cache",
        "--config",
        str(LIB_ROOT / "pyproject.toml"),
        "--stdin-filename",
        str(LIB_ROOT / "OPERATORS.md"),
        "-",
    ]
    try:
        result = subprocess.run(
            command,
            input=markdown,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise RuntimeError("Could not run Ruff to format OPERATORS.md") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        message = "Ruff could not format OPERATORS.md"
        raise RuntimeError(f"{message}: {detail}" if detail else message)
    return result.stdout


def _render_unformatted_reference() -> str:
    outcomes = json.loads(OUTCOMES_PATH.read_text(encoding="utf-8"))
    by_id = {row["operator_id"]: row for row in outcomes["rows"]}
    registry = versioned_registry()
    cards = sorted(
        (card for card in registry.list_cards() if card.version == "2.0.0"),
        key=lambda card: card.name,
    )
    card_ids = {card.operator_id for card in cards}
    if set(by_id) != card_ids:
        missing = sorted(card_ids - set(by_id))
        stale = sorted(set(by_id) - card_ids)
        raise ValueError(f"outcome fixture/card mismatch: missing={missing}, stale={stale}")
    tag_axes: dict[str, set[str]] = defaultdict(set)
    for card in cards:
        for tag in card.tags:
            tag_axes[tag.split("-", 1)[0]].add(tag)

    lines = [
        "# Operator reference",
        "",
        "This reference covers the live `@2.0.0` cards in `versioned_registry()` and their",
        "fixture-backed outcomes. The snippets assume this registry:",
        "",
        "```python",
        "from blue_data_ops.operators import versioned_registry",
        "",
        "registry = versioned_registry()",
        "```",
        "",
        "Each snippet sets `properties = None` when no dependency is needed. Profiles `seam` and",
        "`seam_sql` require a registry seam; `llm` and `llm_refine` require a model client;",
        "`llm_seam` requires both. The runnable examples show those injections.",
        "",
        "## Tag taxonomy",
        "",
        "Tags are exact metadata, not free-text synonyms. A `find()` call with more than one tag",
        "uses AND semantics. Free-text scoring ranks only the cards that pass the tag filter.",
        "",
        "| Axis | Meaning | Values |",
        "|---|---|---|",
    ]
    meanings = {
        "capability": "operation performed",
        "domain": "data or reasoning family",
        "flow": "position in a pipeline",
        "accepts": "input shape",
        "produces": "output or side effect",
        "requires": "runtime dependency or integration",
    }
    axis_order = [axis for axis in meanings if axis in tag_axes]
    axis_order.extend(sorted(tag_axes.keys() - meanings.keys()))
    for axis in axis_order:
        values = ", ".join(f"`{tag}`" for tag in sorted(tag_axes[axis]))
        meaning = meanings.get(axis, "operator metadata")
        lines.append(f"| `{axis}-*` | {meaning} | {values} |")
    lines.extend(
        [
            "",
            "```python",
            "cards = registry.find(",
            '    "filter",',
            '    tags=["domain-relational", "flow-transform"],',
            ")",
            "```",
            "",
        ]
    )
    for card in cards:
        operator = registry.resolve(card.operator_id)
        outcome = by_id[card.operator_id]
        success = outcome["cases"]["success"]
        lines.extend(
            [
                f"## `{card.operator_id}`",
                "",
            ]
        )
        if card.deprecated:
            lines.extend([DEPRECATION_NOTICE, ""])
        lines.extend(
            [
                card.description,
                "",
                f"When to invoke: {card.when_to_invoke}",
                "",
                "Tags: " + ", ".join(f"`{tag}`" for tag in card.tags),
                "",
                "| Attribute | Type | Required | Default | Description |",
                "|---|---|---:|---|---|",
            ]
        )
        if operator.attributes:
            for name, spec in operator.attributes.items():
                default = _display(spec.default) if spec.has_default else "—"
                description = spec.description.replace("|", "\\|").replace("\n", " ")
                lines.append(
                    f"| `{name}` | `{spec.type}` | {'yes' if spec.required else 'no'} | "
                    f"`{default}` | {description} |"
                )
        else:
            lines.append("| _none_ | — | — | — | — |")
        lines.extend(
            [
                "",
                "Fixture-backed call:",
                "",
                "```python",
                "input_data = " + repr(success["input"]),
                "attributes = " + repr(success["attributes"]),
                "properties = None  # inject the fixture profile's dependency here when required",
                "output_data, output_attributes, meta = "
                + f"registry.resolve({card.operator_id!r}).run(",
                "    input_data, attributes, properties",
                ")",
                "```",
                "",
                "The fixture profile is `"
                + success.get("profile", "none")
                + "`; non-`none` profiles use deterministic test doubles for the dependencies "
                "named by the profile.",
                "",
                "- Empty: " + _case_summary(outcome["cases"].get("empty")),
                "- Invalid: " + _case_summary(outcome["cases"].get("invalid")),
                "- Failure: " + _case_summary(outcome["cases"].get("failure")),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_reference() -> str:
    return _format_reference(_render_unformatted_reference())


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
