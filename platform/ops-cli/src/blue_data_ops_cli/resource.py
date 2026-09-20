"""``blue-ops operator resource`` — the reviewed package that ships beside an operator.

This is the guide's ``{<subcomponent>}`` slot, and it is a subcomponent rather than a
component because a resource package has no identity of its own: it is addressed by the
operator id it belongs to, and it exists only where that operator exists. So it is reachable
as ``operator resource <action>`` and nowhere else.

``export`` carries no ``--format``. An export emits the artifact as it is — here, the
package Markdown — and re-encoding it as a table or a sentence would not be an export. The
same rule governs ``pipeline export``, which emits its serialized record as JSON.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
from blue_data_ops.operator_skills import OperatorSkillLoader

from blue_data_ops_cli import config, formats, records
from blue_data_ops_cli.catalog import announce_resolution, resolve_card

LEVELS = ("2", "3")
"""The levels a package declares.

Level 2 is the guide, level 3 adds the worked examples. The library defines a level 4 as
well and no package in this release declares one, so asking for it would be a refusal
discovered at runtime; the closed set says so in ``--help`` instead.
"""


@click.group("resource", cls=config.Group)
def resource_group() -> None:
    """Read the resource package that ships with an operator."""


@resource_group.command("list")
@config.catalog_option
@config.format_option
@click.pass_obj
def resource_list(obj: dict[str, Any], catalog_name: str | None, output_format: str | None) -> None:
    """List the operators in this catalog that ship a resource package.

    \b
    blue-ops operator resource list
    blue-ops operator resource list --format json
    """
    published = config.Output(output_format)
    with config.reporting(published):
        resolver = config.start(obj)
        fmt = published.resolve(resolver)
        catalog = config.resolve_catalog(resolver, catalog_name)
        registry = config.build_catalog(catalog)
        available = OperatorSkillLoader(registry).available_operator_ids()
        cards = [card for card in registry.list_cards() if card.operator_id in available]
        rows = [
            {"Operator id": card.operator_id, "Name": card.name, "Version": card.version}
            for card in cards
        ]
        result = formats.tabular(
            ("Operator id", "Name", "Version"),
            rows,
            {
                "operators": [row["Operator id"] for row in rows],
                "catalog": catalog,
                "count": len(rows),
            },
            sentences=(
                f"{len(rows)} of {len(registry.list_cards())} card(s) in the {catalog} "
                f"catalog ship a resource package.",
            ),
            empty=f"(no resource packages in the {catalog} catalog)",
        )
    formats.render(result, fmt)


@resource_group.command("inspect")
@click.argument("operator_id")
@config.catalog_option
@config.format_option
@click.pass_obj
def resource_inspect(
    obj: dict[str, Any],
    operator_id: str,
    catalog_name: str | None,
    output_format: str | None,
) -> None:
    """Print what one operator's package declares, without reading the package itself.

    OPERATOR_ID is a pinned id such as select@2.0.0, or a bare name where the catalog
    holds one version of it.

    \b
    blue-ops operator resource inspect select@2.0.0
    blue-ops operator resource inspect avg --format json
    """
    published = config.Output(output_format)
    with config.reporting(published):
        resolver = config.start(obj)
        fmt = published.resolve(resolver)
        catalog = config.resolve_catalog(resolver, catalog_name)
        registry = config.build_catalog(catalog)
        card = resolve_card(registry, operator_id, catalog)
        announce_resolution(config.Reporter(fmt), operator_id, card)
        descriptor = OperatorSkillLoader(registry).describe(card.operator_id)
        kinds = list(descriptor.declared_kinds)
        levels = [str(level) for level in descriptor.declared_levels]
        rows = {
            "operator_id": descriptor.card.operator_id,
            "name": descriptor.card.name,
            "version": descriptor.card.version,
            "kinds": ", ".join(kinds) or "(none)",
            "levels": ", ".join(levels) or "(none)",
        }
        result = formats.key_value(
            rows,
            payload={
                "resource": {
                    "operator_id": descriptor.card.operator_id,
                    "name": descriptor.card.name,
                    "version": descriptor.card.version,
                    "declared_kinds": kinds,
                    "declared_levels": list(descriptor.declared_levels),
                },
                "catalog": catalog,
            },
            sentences=(
                f"{descriptor.card.operator_id} declares {len(kinds)} resource(s): "
                f"{', '.join(kinds) or 'none'}.",
                f"Levels available: {', '.join(levels) or 'none'}.",
            ),
            title=f"resource: {descriptor.card.operator_id}",
        )
    formats.render(result, fmt)


@resource_group.command("export")
@click.argument("operator_id")
@click.option(
    "--level",
    type=click.Choice(LEVELS),
    default=LEVELS[0],
    show_default=True,
    help="2 is the guide; 3 adds the worked examples.",
)
@click.option(
    "--output-file",
    type=click.Path(dir_okay=False, writable=True, path_type=str),
    default=None,
    help="Write the package here instead of to standard output.",
)
@config.confirm_option
@config.catalog_option
@click.pass_obj
def resource_export(
    obj: dict[str, Any],
    operator_id: str,
    level: str,
    output_file: str | None,
    confirm: bool,
    catalog_name: str | None,
) -> None:
    """Write one operator's package out as it is written.

    OPERATOR_ID is a pinned id such as select@2.0.0, or a bare name where the catalog
    holds one version of it. There is no format option here: an export emits the
    artifact, and re-encoding Markdown as a table would not be one.

    \b
    blue-ops operator resource export select@2.0.0
    blue-ops operator resource export select@2.0.0 --level 3 --output-file select.md
    """
    with config.reporting("table"):
        resolver = config.start(obj)
        catalog = config.resolve_catalog(resolver, catalog_name)
        registry = config.build_catalog(catalog)
        card = resolve_card(registry, operator_id, catalog)
        reporter = config.Reporter()
        announce_resolution(reporter, operator_id, card)
        view = OperatorSkillLoader(registry).load(card.operator_id, int(level))
        parts = [text for text in (view.guide, view.examples, view.history) if text]
        text = "\n\n".join(parts)

        if output_file is None:
            click.echo(text)
            return
        target = Path(output_file)
        if target.exists() and not records.confirm(
            f"Overwrite {target}?", confirm, "Pass --confirm to overwrite it."
        ):
            reporter.note(f"Kept {target}.")
            return
        try:
            target.write_text(text, encoding="utf-8")
        except OSError as error:
            raise config.CliError(
                config.REQUEST, f"--output-file could not be written: {error}"
            ) from None
    reporter.note(f"Wrote {len(text)} character(s) of {card.operator_id} to {target}.")
