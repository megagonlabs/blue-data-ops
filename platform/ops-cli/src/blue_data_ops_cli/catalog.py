"""``blue-ops catalog`` — which view of the operator registry a command reads.

The library keeps three registries over the same operators. This CLI exposes two of them
as catalogs: ``active``, the reviewed cards with one version per name, and ``history``,
every retained version. The third, the raw registry, is not a catalog here; ``--catalog
raw`` is refused with the reason rather than with an unknown-value message, and
:mod:`blue_data_ops_cli.config` owns that refusal so every command carrying ``--catalog``
gives the same answer.

A catalog is selected once and every later command reads it. The selection is written to
``<profile>/.selected.catalog`` and sits under ``BLUE_DATA_OPS_CATALOG`` in the precedence
chain, because the parameter is reachable from the environment and a file on disk is not.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import click
from blue_data_ops.operators import OperatorCard, OperatorRegistry

from blue_data_ops_cli import config, formats
from blue_data_ops_cli.configstore import StoreError
from blue_data_ops_cli.profile import profile_store

TAG_AXES = ("domain", "flow", "accepts", "produces", "capability", "requires")
"""The library's six tag axes, in the order its own documentation lists them.

Every built-in tag is ``<axis>-<value>``, so the axis is the part before the first hyphen.
A tag whose prefix is none of these is reported under :data:`OTHER_AXIS` rather than
dropped: the taxonomy is what a caller reads to build a ``--tag`` filter, and a value that
is present but unlisted would be a filter that works and is undiscoverable.
"""

OTHER_AXIS = "other"

PLANNING = {
    "active": "yes",
    "history": "by allowlist",
}
"""Whether a view's cards may be used as planning authority.

Planning admits the active selection on its own. A retained version from ``history`` is
admitted only when the planning request names it in ``allowed_operator_ids``.
"""


def axis_of(tag: str) -> str:
    prefix = tag.partition("-")[0]
    return prefix if prefix in TAG_AXES else OTHER_AXIS


def taxonomy(cards: list[OperatorCard]) -> dict[str, list[str]]:
    """Every tag present in *cards*, grouped by axis and sorted within it."""
    grouped: dict[str, set[str]] = {}
    for card in cards:
        for tag in card.tags:
            grouped.setdefault(axis_of(tag), set()).add(tag)
    order = (*TAG_AXES, OTHER_AXIS)
    return {axis: sorted(grouped[axis]) for axis in order if axis in grouped}


def summary(name: str, registry: OperatorRegistry) -> dict[str, Any]:
    cards = registry.list_cards()
    return {
        "name": name,
        "cards": len(cards),
        "operators": len({card.name for card in cards}),
        "planning": PLANNING.get(name, "no"),
    }


def resolve_card(registry: OperatorRegistry, reference: str, catalog: str) -> OperatorCard:
    """The card *reference* names, whether it is a pinned id or a bare name."""
    if "@" in reference:
        card = registry.get_card(reference)
        if card is None:
            raise config.CliError(
                config.REQUEST,
                f"no card for {reference!r} in the {catalog} catalog. Run "
                f"`{config.PROGRAM} operator search {reference.partition('@')[0]}` to see "
                f"what is there.",
                {"library_code": "RESOLVE_ERROR", "operator_id": reference, "catalog": catalog},
            )
        return card

    versions = [card for card in registry.list_cards() if card.name == reference]
    if not versions:
        raise config.CliError(
            config.REQUEST,
            f"no operator named {reference!r} in the {catalog} catalog. Run "
            f"`{config.PROGRAM} operator search {reference}` to see what is there.",
            {"library_code": "RESOLVE_ERROR", "operator_id": reference, "catalog": catalog},
        )
    if len(versions) > 1:
        available = ", ".join(card.operator_id for card in versions)
        raise config.CliError(
            config.REQUEST,
            f"{reference!r} is ambiguous in the {catalog} catalog, which holds "
            f"{len(versions)} versions of it: {available}. Name the one you want.",
            {"library_code": "RESOLVE_ERROR", "operator_id": reference, "catalog": catalog},
        )
    found = registry.find_latest(reference)
    if found is None:  # pragma: no cover - list_cards and find_latest read the same map
        raise config.CliError(config.REQUEST, f"no operator named {reference!r}")
    return found


def announce_resolution(reporter: config.Reporter, reference: str, card: OperatorCard) -> None:
    """Say which id a bare name became, on stderr, where it cannot corrupt a result."""
    if reference != card.operator_id:
        reporter.note(f"{reference} resolved to {card.operator_id}")


@click.group("catalog", cls=config.Group)
def catalog_group() -> None:
    """Select and inspect operator catalogs."""


@catalog_group.command("list")
@config.format_option
@click.pass_obj
def catalog_list(obj: dict[str, Any], output_format: str | None) -> None:
    """List the catalogs this CLI exposes, with the size of each.

    \b
    blue-ops catalog list
    blue-ops catalog list --format json
    """
    published = config.Output(output_format)
    with config.reporting(published):
        resolver = config.start(obj)
        fmt = published.resolve(resolver)
        selected = config.resolve_catalog(resolver, None)
        rows = [summary(name, config.build_catalog(name)) for name in config.CATALOGS]
        table = [
            {
                "Catalog": row["name"],
                "Selected": "*" if row["name"] == selected else "",
                "Cards": row["cards"],
                "Operators": row["operators"],
                "Planning": row["planning"],
            }
            for row in rows
        ]
        result = formats.tabular(
            ("Catalog", "Selected", "Cards", "Operators", "Planning"),
            table,
            {"catalogs": rows, "selected": selected},
            sentences=(
                " ".join(
                    f"{row['name']} holds {row['cards']} card(s) over "
                    f"{row['operators']} operator name(s)."
                    for row in rows
                ),
                f"The selected catalog is {selected}.",
            ),
            notes=(
                "Planning admits the active selection on its own; a retained version is "
                "admitted only when a planning request names it.",
            ),
        )
    formats.render(result, fmt)


@catalog_group.command("inspect")
@click.argument("name", required=False, type=config.CatalogChoice())
@config.format_option
@click.pass_obj
def catalog_inspect(obj: dict[str, Any], name: str | None, output_format: str | None) -> None:
    """Print one catalog's size, its version spread, and the tags its cards carry.

    NAME is active|history and defaults to the selected catalog. The tags listed are
    exactly the values a tag filter accepts against this catalog.

    \b
    blue-ops catalog inspect
    blue-ops catalog inspect history --format json
    """
    published = config.Output(output_format)
    with config.reporting(published):
        resolver = config.start(obj)
        fmt = published.resolve(resolver)
        selected = config.resolve_catalog(resolver, None)
        target = name or selected
        registry = config.build_catalog(target)
        cards = registry.list_cards()
        versions = dict(sorted(Counter(card.version for card in cards).items()))
        tags = taxonomy(cards)
        payload = {
            **summary(target, registry),
            "versions": versions,
            "tags": tags,
        }
        rows = [
            {"Axis": axis, "Tags": len(values), "Values": ", ".join(values)}
            for axis, values in tags.items()
        ]
        spread = ", ".join(f"{version} ({count})" for version, count in versions.items())
        result = formats.tabular(
            ("Axis", "Tags", "Values"),
            rows,
            {"catalog": payload, "selected": selected},
            sentences=(
                f"The {target} catalog holds {payload['cards']} card(s) over "
                f"{payload['operators']} operator name(s).",
                f"Versions: {spread or 'none'}.",
                f"Tags: {sum(len(values) for values in tags.values())} across "
                f"{len(tags)} axis/axes.",
            ),
            notes=(
                f"{payload['cards']} card(s), {payload['operators']} operator name(s).",
                f"versions: {spread or 'none'}",
            ),
            title=f"catalog: {target}",
            empty="(no tags on any card in this catalog)",
        )
    formats.render(result, fmt)


@catalog_group.command("select")
@click.argument("name", type=config.CatalogChoice())
@click.pass_obj
def catalog_select(obj: dict[str, Any], name: str) -> None:
    """Set the catalog every later command reads.

    NAME is active|history. The selection is stored per profile, and both the
    catalog option and BLUE_DATA_OPS_CATALOG still override it for one command.

    \b
    blue-ops catalog select history
    """
    with config.reporting("table"):
        resolver = config.start(obj)
        store = profile_store(obj["home"])
        try:
            store.write_selection(resolver.profile, "catalog", name)
        except StoreError as error:
            raise config.CliError(config.PROFILE, str(error)) from None
        profile = resolver.profile
    formats.console().print(f"Selected catalog: {name} (profile {profile})", style="bold")
