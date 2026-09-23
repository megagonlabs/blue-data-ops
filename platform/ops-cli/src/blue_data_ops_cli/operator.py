"""``blue-ops operator`` — the repository's primary resource: find one, read it, run it.

An operator is addressed by a pinned id, ``name@<major>.<minor>.<patch>``. A bare name is
accepted as well and resolved through the library's own lookup, and the id it resolved to is
reported back, because a run that silently chose a version is a run nobody can reproduce.
In a catalog holding more than one version of that name the bare form is refused instead,
with the versions listed: picking the highest would be a guess dressed as a resolution.

``run`` is the one verb here outside the guide's list. It means "apply a transformation to
supplied records and return the result", which no standard verb covers; ``query`` means
"retrieve from a store" everywhere else in the family, and reusing it would put one word on
two behaviours. The README argues it again where a user reads it.
"""

from __future__ import annotations

import time
from typing import Any

import click
from blue_data_ops.operators import DataBundle, ExecMeta, OperatorCard

from blue_data_ops_cli import config, formats, records
from blue_data_ops_cli.catalog import announce_resolution, axis_of, resolve_card, taxonomy
from blue_data_ops_cli.resource import resource_group

ACCEPTS_NONE = "accepts-none"
"""The tag that says an operator consumes no upstream records.

The library is explicit that this does not make ``input_data`` optional: the caller passes
an empty bundle. So the CLI passes ``[[]]`` rather than asking someone to write a file
containing it.
"""

DISCOVERY_LIMIT = 20
"""``DiscoveryQuery.limit``'s own default, so the two cannot drift."""


def domain_of(card: OperatorCard) -> str:
    return next((tag for tag in card.tags if axis_of(tag) == "domain"), "")


def card_row(card: OperatorCard) -> dict[str, Any]:
    return {
        "Operator id": card.operator_id,
        "Name": card.name,
        "Version": card.version,
        "Domain": domain_of(card),
        "Description": card.description,
    }


def card_payload(card: OperatorCard) -> dict[str, Any]:
    return {
        "operator_id": card.operator_id,
        "name": card.name,
        "version": card.version,
        "domain": domain_of(card),
        "description": card.description,
    }


CARD_COLUMNS = ("Operator id", "Name", "Version", "Domain", "Description")


def error_payload(meta: ExecMeta) -> list[dict[str, Any]]:
    return [
        {
            "category": record.category.value,
            "code": record.code.value,
            "operator_id": record.operator_id,
            "stage": record.stage.value,
            "message": record.message,
            "retryable": record.retryable,
            "suggestion": record.suggestion,
        }
        for record in meta.errors
    ]


def bundle_table(bundle: DataBundle) -> tuple[tuple[str, ...], list[dict[str, Any]]]:
    """A record bundle as one table: the group index, then every key any record carries.

    Columns are collected in first-seen order rather than sorted, so a record's own key
    order survives into the table it is printed as.
    """
    columns: list[str] = ["group"]
    rows: list[dict[str, Any]] = []
    for index, group in enumerate(bundle):
        for record in group:
            for key in record:
                if key not in columns:
                    columns.append(key)
            rows.append({"group": index, **record})
    return tuple(columns), rows


@click.group("operator", cls=config.Group)
def operator_group() -> None:
    """Find, describe and run operators."""


operator_group.add_command(resource_group)


@operator_group.command("list")
@config.catalog_option
@config.format_option
@click.pass_obj
def operator_list(obj: dict[str, Any], catalog_name: str | None, output_format: str | None) -> None:
    """List every operator in the selected catalog.

    \b
    blue-ops operator list
    blue-ops operator list --catalog history --format json
    """
    published = config.Output(output_format)
    with config.reporting(published):
        resolver = config.start(obj)
        fmt = published.resolve(resolver)
        catalog = config.resolve_catalog(resolver, catalog_name)
        cards = config.build_catalog(catalog).list_cards()
        result = formats.tabular(
            CARD_COLUMNS,
            [card_row(card) for card in cards],
            {
                "operators": [card_payload(card) for card in cards],
                "catalog": catalog,
                "count": len(cards),
            },
            sentences=(f"The {catalog} catalog holds {len(cards)} operator card(s).",),
            empty=f"(no cards in the {catalog} catalog)",
        )
    formats.render(result, fmt)


@operator_group.command("search")
@click.argument("query")
@click.option(
    "--tag",
    "tags",
    multiple=True,
    help="Require this tag. Repeatable, and every one given must be present. Tags are "
    "domain-*, flow-*, accepts-*, produces-*, capability-* and requires-*; "
    "`blue-ops catalog inspect` lists the values this catalog actually carries.",
)
@click.option(
    "--limit",
    type=int,
    default=DISCOVERY_LIMIT,
    show_default=True,
    help="Most cards to return.",
)
@config.catalog_option
@config.format_option
@click.pass_obj
def operator_search(
    obj: dict[str, Any],
    query: str,
    tags: tuple[str, ...],
    limit: int,
    catalog_name: str | None,
    output_format: str | None,
) -> None:
    """Search operator cards by text, by tag, or by both.

    QUERY is matched against the name, the tags, the invocation guidance and the
    description. It may be empty when at least one tag is given.

    \b
    blue-ops operator search average
    blue-ops operator search "" --tag domain-vector --format json
    """
    published = config.Output(output_format)
    with config.reporting(published):
        resolver = config.start(obj)
        fmt = published.resolve(resolver)
        catalog = config.resolve_catalog(resolver, catalog_name)
        if not query.strip() and not tags:
            # The library returns nothing for this, by rule rather than by accident, and
            # printing an empty table would report "found nothing" for a search that was
            # never run.
            raise config.CliError(
                config.REQUEST,
                "a blank query needs at least one tag: text scoring has nothing to score "
                "and tag-only discovery has nothing to filter on. Run "
                f"`{config.PROGRAM} catalog inspect` for the tags this catalog carries.",
            )
        if limit < 1:
            raise config.CliError(config.USAGE, f"--limit must be at least 1, not {limit}")
        registry = config.build_catalog(catalog)
        found = registry.find(query, list(tags) or None)
        cards = found[:limit]
        result = formats.tabular(
            CARD_COLUMNS,
            [card_row(card) for card in cards],
            {
                "operators": [card_payload(card) for card in cards],
                "catalog": catalog,
                "query": query,
                "tags": list(tags),
                "limit": limit,
                "count": len(cards),
            },
            sentences=(f"{len(cards)} of {len(found)} matching card(s) in the {catalog} catalog.",),
            empty=f"(nothing matched in the {catalog} catalog)",
        )
    formats.render(result, fmt)


@operator_group.command("inspect")
@click.argument("operator_id")
@config.catalog_option
@config.format_option
@click.pass_obj
def operator_inspect(
    obj: dict[str, Any],
    operator_id: str,
    catalog_name: str | None,
    output_format: str | None,
) -> None:
    """Print one operator's card, its tags by axis, and its attribute schema.

    OPERATOR_ID is a pinned id such as select@2.0.0, or a bare name where the catalog
    holds one version of it. The attribute schema is here rather than under a schema
    component: it describes this operator and nothing else.

    \b
    blue-ops operator inspect select@2.0.0
    blue-ops operator inspect avg --format json
    """
    published = config.Output(output_format)
    with config.reporting(published):
        resolver = config.start(obj)
        fmt = published.resolve(resolver)
        catalog = config.resolve_catalog(resolver, catalog_name)
        registry = config.build_catalog(catalog)
        card = resolve_card(registry, operator_id, catalog)
        announce_resolution(config.Reporter(fmt), operator_id, card)
        operator = registry.resolve(card.operator_id)
        schema = {
            name: {
                "type": definition.get("type"),
                "description": definition.get("description", ""),
                "required": bool(definition.get("required", False)),
                "default": definition.get("default"),
                "has_default": "default" in definition,
                "hidden": bool(definition.get("hidden", False)),
            }
            for name, definition in operator.get_attributes().items()
        }
        rows = [
            {
                "Attribute": name,
                "Type": entry["type"],
                "Required": "yes" if entry["required"] else "",
                "Default": entry["default"] if entry["has_default"] else "",
                "Description": entry["description"],
            }
            for name, entry in schema.items()
        ]
        tags = taxonomy([card])
        notes = [card.description]
        if card.when_to_invoke:
            notes.append(f"when to invoke: {card.when_to_invoke}")
        notes.extend(f"{axis}: {', '.join(values)}" for axis, values in tags.items())
        if card.deprecated:
            notes.append("This card is deprecated and is not planning authority.")
        result = formats.tabular(
            ("Attribute", "Type", "Required", "Default", "Description"),
            rows,
            {
                "operator": {**card_payload(card), "tags": tags, "schema": schema},
                "catalog": catalog,
            },
            sentences=(
                f"{card.operator_id} is {card.description}",
                f"It declares {len(schema)} attribute(s).",
            ),
            notes=tuple(notes),
            title=card.operator_id,
            empty=f"({card.operator_id} declares no attributes)",
        )
    formats.render(result, fmt)


@operator_group.command("run")
@click.argument("operator_id")
@click.option(
    "--input-file",
    type=click.Path(exists=True, dir_okay=False, allow_dash=True, path_type=str),
    default=None,
    help="JSON file holding the record groups to run on; - reads standard input. "
    "Required unless the operator consumes no records.",
)
@click.option(
    "--attribute",
    "attributes",
    multiple=True,
    metavar="KEY=VALUE",
    help="One operator attribute. Repeatable. The value is read as JSON and falls back "
    "to the literal text.",
)
@click.option(
    "--attributes-file",
    type=click.Path(exists=True, dir_okay=False, path_type=str),
    default=None,
    help="JSON object of attributes, applied before the per-key options.",
)
@click.option(
    "--property",
    "properties",
    multiple=True,
    metavar="KEY=VALUE",
    help="One call property, such as openai.temperature=0. Repeatable, same value rules.",
)
@click.option(
    "--properties-file",
    type=click.Path(exists=True, dir_okay=False, path_type=str),
    default=None,
    help="JSON object of call properties, applied before the per-key options.",
)
@click.option(
    "--timeout",
    type=float,
    default=None,
    show_default="the profile's BLUE_DATA_OPS_TIMEOUT, else none",
    help="Seconds this operator may take before the run is abandoned.",
)
@click.option(
    "--model",
    default=None,
    show_default="the profile's BLUE_DATA_LLM_MODEL, else gpt-4o",
    help="Model the language-model operators call.",
)
@click.option(
    "--reasoning-effort",
    default=None,
    help="Reasoning effort for this call. Omit it for models without this setting.",
)
@config.catalog_option
@config.format_option
@config.log_options
@click.pass_obj
def operator_run(
    obj: dict[str, Any],
    operator_id: str,
    input_file: str | None,
    attributes: tuple[str, ...],
    attributes_file: str | None,
    properties: tuple[str, ...],
    properties_file: str | None,
    timeout: float | None,
    model: str | None,
    reasoning_effort: str | None,
    catalog_name: str | None,
    output_format: str | None,
    log: bool,
    log_limit: int | None,
) -> None:
    """Run one operator over a record bundle and print what it returned.

    A bundle is list[list[dict]]: groups of records. An operator tagged accepts-none
    consumes no records, and the CLI passes it an empty bundle, so --input-file is
    required only for the rest.

    \b
    blue-ops operator run select@2.0.0 --input-file orders.json \\
      --attribute operand_key=total --attribute operand=">" --attribute operand_val=100
    blue-ops operator run data_discover --format json
    """
    published = config.Output(output_format)
    with config.reporting(published, log=log):
        resolver = config.start(obj)
        fmt = published.resolve(resolver)
        reporter = config.Reporter(fmt, log, config.resolve_log_limit(resolver, log_limit))
        catalog = config.resolve_catalog(resolver, catalog_name)
        registry = config.build_catalog(catalog)
        card = resolve_card(registry, operator_id, catalog)
        announce_resolution(reporter, operator_id, card)
        operator = registry.resolve(card.operator_id)

        call_attributes = records.merged(
            attributes_file, attributes, "--attribute", "--attributes-file"
        )
        call_properties = records.merged(
            properties_file, properties, "--property", "--properties-file"
        )
        settings = config.Settings(resolver)
        applied_timeout = settings.take(
            "execution.timeout_seconds",
            timeout if timeout is not None else call_properties.get("execution.timeout_seconds"),
            "BLUE_DATA_OPS_TIMEOUT",
        )
        if applied_timeout is not None:
            call_properties["execution.timeout_seconds"] = applied_timeout
        if model is not None:
            call_properties.pop("llm.model", None)
            applied_model = settings.take("openai.model", model, "BLUE_DATA_LLM_MODEL")
            if applied_model is not None:
                call_properties["openai.model"] = applied_model
        elif "llm.model" in call_properties:
            call_properties.pop("openai.model", None)
            neutral_model = call_properties["llm.model"]
            settings.take("llm.model", neutral_model)
        else:
            applied_model = settings.take(
                "openai.model",
                call_properties.get("openai.model"),
                "BLUE_DATA_LLM_MODEL",
            )
            if applied_model is not None:
                call_properties["openai.model"] = applied_model
        if reasoning_effort is not None:
            applied_effort = settings.take("llm.reasoning_effort", reasoning_effort)
            call_properties["llm.reasoning_effort"] = applied_effort
        elif "llm.reasoning_effort" in call_properties:
            neutral_effort = call_properties["llm.reasoning_effort"]
            settings.take("llm.reasoning_effort", neutral_effort)

        if config.requires_data_registry(card):
            # Built only for a card that says it needs one. The library would otherwise
            # construct a per-call in-memory registry and drop it when the process ends,
            # which for a CLI means creating a database and immediately losing it.
            call_properties["data_registry"] = config.build_registry_seam()
            if config.registry_is_ephemeral():
                reporter.warn(
                    "BLUE_DATA_REGISTRY_STORE is memory, so this registry lives only for "
                    "this command and anything written to it is gone when it ends."
                )

        bundle: DataBundle
        if input_file is not None:
            bundle = records.load_bundle(input_file)
        elif ACCEPTS_NONE in card.tags:
            bundle = [[]]
        else:
            raise config.CliError(
                config.USAGE,
                f"{card.operator_id} consumes records, so --input-file is required. It "
                f"holds a JSON list of record groups; pass - to read one on standard input.",
            )

        started = time.monotonic()
        with reporter.status(f"Running {card.operator_id}…"):
            output_data, output_attributes, meta = operator.run(
                bundle, call_attributes, call_properties
            )
        elapsed = round(time.monotonic() - started, 3)

        for line in meta.logs:
            reporter.line(line)
        for key, value in meta.traces.items():
            reporter.line(f"{key}: {value}")

        for notice in config.recoverable_notices(meta.errors):
            reporter.warn(notice)

        failure = config.execution_failure(meta.errors)
        if failure is not None:
            raise config.CliError(
                failure.code,
                failure.message,
                {**(failure.detail or {}), "elapsed_seconds": elapsed},
            )

        columns, rows = bundle_table(output_data)
        notes = [settings.footer()]
        if output_attributes:
            notes.append(f"output attributes: {formats.cell(output_attributes)}")
        result = formats.tabular(
            columns,
            rows,
            {
                "result": {
                    "output_data": output_data,
                    "output_attributes": output_attributes,
                },
                "operator_id": card.operator_id,
                "is_empty": meta.is_empty,
                "errors": error_payload(meta),
                "traces": meta.traces,
                "elapsed_seconds": elapsed,
                "settings": settings.envelope(),
            },
            sentences=(
                f"{card.operator_id} returned {sum(len(group) for group in output_data)} "
                f"record(s) in {len(output_data)} group(s) in {elapsed}s.",
                f"It reported {len(meta.errors)} recoverable issue(s).",
            ),
            notes=tuple(notes),
            title=card.operator_id,
            empty=f"(no records — {card.operator_id} returned an empty bundle)",
        )
    formats.render(result, fmt)
