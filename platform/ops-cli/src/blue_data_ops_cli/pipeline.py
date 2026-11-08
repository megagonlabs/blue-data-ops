"""``blue-ops pipeline`` — compose operators into a graph, keep it, and run it.

A ``DataPipeline`` is a serializable record, which is what makes ``import``, ``export``,
``list``, ``inspect`` and ``remove`` mean here exactly what they mean elsewhere in the
family. ``add`` is not a synonym for ``import``: ``import`` reads a graph someone already
wrote, ``add`` synthesizes one from a planning request. ``run`` is the same verb it is on
``operator``.

**A run never writes to the store.** ``PipelineExecutor.execute()`` records what happened on
the plan it is given: it sets each node's value to the records that passed through it and
each node's status to ``EXECUTED`` or ``FAILED``. Writing that back would put the caller's
records into ``~/.blue-ops`` and would leave a stored plan the executor refuses to start
again, because a node that has already run cannot run twice. So a run loads from disk,
executes an in-memory copy, and writes nothing; ``add`` and ``import`` are the only writers.

Pipelines are stored per profile, under ``<profile>/pipeline/<name>/``, which is the
hierarchy the guide gives for a component's own state.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import click
from blue_data_ops.operators import DataBundle, OperatorRegistry
from blue_data_ops.plan import (
    DataPipeline,
    DataScope,
    DiscoveryQuery,
    NodeType,
    OpenAIPlanGenerator,
    PipelineExecutor,
    PipelinePlanner,
    PipelinePreflight,
    PipelineRun,
    PlanGenerator,
    PlanningRequest,
    PlanRecord,
    RegistryDataContextProvider,
    RulePlanGenerator,
)

from blue_data_ops_cli import config, configstore, formats, records
from blue_data_ops_cli.configstore import ProfileStore
from blue_data_ops_cli.operator import bundle_table, error_payload
from blue_data_ops_cli.profile import profile_store

COMPONENT = "pipeline"
PIPELINE_FILE = "pipeline.json"
PROVENANCE_FILE = "provenance.json"

PLANNERS = ("rule", "openai")

REQUEST_FIELDS = frozenset(
    {
        "goal",
        "discovery_queries",
        "operator_attributes",
        "data_scope",
        "allowed_operator_ids",
        "input_label",
        "output_label",
        "max_discovery_cards",
        "max_candidates",
        "max_steps",
        "max_nodes",
        "max_edges",
    }
)
"""Every field a planning request may carry, which is ``PlanningRequest``'s own list.

An unknown field is refused rather than dropped. A request is hand-written JSON, and a
misspelled bound that is silently ignored plans against a limit the author did not set.
"""


def build_openai_client() -> Any:
    """The client the provider-backed planner calls, or ``None`` to let it build its own.

    A seam rather than a constant: it is the one place in this CLI that would reach a
    provider, so it is the one place a test replaces to prove that nothing does.
    """
    return None


# ------------------------------------------------------------------ storage --
def check_name(name: str) -> str:
    """A name a pipeline is about to be stored under, which is a directory name.

    One rule stricter than :func:`check_stored_name`: a new pipeline cannot be called
    something beginning with a dot, because that is where the store keeps its own entries
    while it is removing one. The rule is about what may be created rather than about what
    may be reached — a pipeline stored under such a name by a version that allowed it is
    still listed, shown and removed by name.
    """
    cleaned = check_stored_name(name)
    if cleaned.startswith("."):
        raise config.CliError(
            config.USAGE,
            f"pipeline name {name!r} cannot start with a dot: the store keeps its own "
            f"entries under names that begin with one while it removes a pipeline. One "
            f"already stored under such a name still works; it just cannot be a new one",
        )
    return cleaned


def check_stored_name(name: str) -> str:
    """A name that is already a directory in the store, checked before it is joined on.

    Everything a pipeline name cannot be under any version of this CLI: blank, padded, a
    directory reference, or holding a separator. A leading dot is not on that list, so a
    pipeline stored before the store reserved one stays reachable instead of becoming a
    directory the caller can see and no command will touch.
    """
    cleaned = name.strip()
    if not cleaned:
        raise config.CliError(config.USAGE, "a pipeline name cannot be blank")
    unsafe = cleaned != name or any(character in name for character in "/\\\n\r")
    if unsafe or cleaned in {".", ".."}:
        raise config.CliError(
            config.USAGE,
            f"pipeline name {name!r} cannot hold slashes, newlines or padding, and cannot "
            f"be `.` or `..`, which are directory references rather than names",
        )
    return cleaned


class PipelineStore:
    """``<profile>/pipeline/<name>/`` — one directory per stored pipeline.

    **Nothing here is reached by name twice.** A stored pipeline is two files this CLI
    created under a directory this CLI created, and the promise the package makes about
    them — 0700 on the directories, 0600 on the files, nothing written outside
    ``~/.blue-ops`` — only holds while ``<profile>/pipeline`` really is a directory there.
    Checking that it is and then opening a path through it asks the kernel to resolve the
    name a second time, and a link put in its place between the two answers is followed;
    ``O_NOFOLLOW`` does not help, because it answers for the last component and the
    component that matters is a directory three levels up.

    So the store opens the CLI home, walks down to the directory it needs with
    :func:`configstore.home_directory` or :func:`configstore.made_directory`, and reads,
    writes, creates and removes against the descriptor that walk returned. The window
    between a check and a use is not narrowed, it is gone: after the walk there is no name
    left to swap.

    The write repeats the profile store's rule rather than calling it: a same-directory
    temporary file at mode 0600, flushed and renamed, so an interrupted write leaves the
    previous record intact instead of half of the new one. That rule lives on
    :class:`configstore.HomeDir` with the descriptor it needs, and both stores use it.
    """

    def __init__(self, store: ProfileStore, profile: str) -> None:
        self._home = store.home
        self._root = store.profile_dir(profile) / COMPONENT
        self._below = (profile, COMPONENT)
        self.profile = profile

    def directory(self, name: str) -> Path:
        """Where a stored pipeline is spelled, for a message. Not how it is reached."""
        return self._root / check_stored_name(name)

    def names(self) -> list[str]:
        with configstore.home_directory(self._home, self._below) as component:
            if component is None:
                return []
            component.finish_removals()
            entries = component.entries()
        found: list[str] = []
        for entry in entries:
            with configstore.home_directory(self._home, (*self._below, entry)) as stored:
                if stored is not None and stored.holds(PIPELINE_FILE):
                    found.append(entry)
        return sorted(found)

    def exists(self, name: str) -> bool:
        with configstore.home_directory(self._home, self._at(name)) as stored:
            return stored is not None and stored.holds(PIPELINE_FILE)

    def read(self, name: str) -> PlanRecord:
        """The stored record, parsed fresh on every call so no two readers share one."""
        label = f"{name}'s stored pipeline"
        document: PlanRecord = records.decode_json(self.read_text(name), label)
        return document

    def read_text(self, name: str) -> str:
        label = f"{name}'s stored pipeline"
        text = self._read(name, PIPELINE_FILE, label)
        if text is None:
            raise config.CliError(
                config.REQUEST,
                f"no stored pipeline named {name!r} in profile {self.profile}. Run "
                f"`{config.PROGRAM} pipeline list` to see them.",
            )
        return text

    def provenance(self, name: str) -> dict[str, Any]:
        label = f"{name}'s provenance"
        text = self._read(name, PROVENANCE_FILE, label)
        if text is None:
            return {}
        document = records.decode_json(text, label)
        return cast("dict[str, Any]", document) if isinstance(document, dict) else {}

    def write(self, name: str, record: PlanRecord, provenance: dict[str, Any]) -> None:
        check_name(name)
        try:
            with configstore.made_directory(self._home, self._at(name)) as stored:
                stored.write(PIPELINE_FILE, _as_json(record))
                stored.write(PROVENANCE_FILE, _as_json(provenance))
        except OSError as error:
            raise config.CliError(
                config.REQUEST, f"cannot write {self.directory(name)}: {error.strerror or error}"
            ) from None

    def remove(self, name: str) -> None:
        try:
            with configstore.home_directory(self._home, self._below) as component:
                if component is None:
                    return
                component.finish_removals()
                component.remove_tree(check_stored_name(name))
        except OSError as error:
            raise config.CliError(
                config.REQUEST, f"cannot remove {self.directory(name)}: {error.strerror or error}"
            ) from None

    # -- internals --
    def _at(self, name: str) -> tuple[str, ...]:
        """The components of one stored pipeline's directory, below the CLI home."""
        return (*self._below, check_stored_name(name))

    def _read(self, name: str, filename: str, label: str) -> str | None:
        """*filename*'s text from a stored pipeline, or ``None`` where it is not there."""
        try:
            with configstore.home_directory(self._home, self._at(name)) as stored:
                return None if stored is None else stored.read(filename)
        except OSError as error:
            raise config.CliError(
                config.REQUEST, f"{label} could not be read: {error.strerror or error}"
            ) from None


def _as_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, default=str) + "\n"


def store_for(obj: dict[str, Any], resolver_profile: str) -> PipelineStore:
    return PipelineStore(profile_store(obj["home"]), resolver_profile)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ---------------------------------------------------------- planning request --
def _string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise config.CliError(config.REQUEST, f"{field} must be a string")
    return value


def _integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise config.CliError(config.REQUEST, f"{field} must be a whole number")
    return value


def _strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise config.CliError(config.REQUEST, f"{field} must be a list of strings")
    return tuple(_string(item, field) for item in cast("list[object]", value))


def _discovery_queries(value: object) -> tuple[DiscoveryQuery, ...]:
    if not isinstance(value, list) or not value:
        raise config.CliError(
            config.REQUEST,
            'discovery_queries must be a nonempty list of {"text": ..., "tags": [...], '
            '"limit": N} objects',
        )
    queries: list[DiscoveryQuery] = []
    for entry in cast("list[object]", value):
        if not isinstance(entry, dict):
            raise config.CliError(config.REQUEST, "each discovery query must be an object")
        query = cast("dict[str, object]", entry)
        queries.append(
            DiscoveryQuery(
                text=_string(query.get("text", ""), "discovery query text"),
                tags=_strings(query.get("tags", []), "discovery query tags"),
                limit=_integer(query.get("limit", 20), "discovery query limit"),
            )
        )
    return tuple(queries)


def _data_scope(value: object) -> DataScope | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise config.CliError(config.REQUEST, "data_scope must be an object")
    scope = cast("dict[str, object]", value)
    return DataScope(
        source=_string(scope.get("source", ""), "data_scope source"),
        database=_string(scope.get("database", ""), "data_scope database"),
        collection=_string(scope.get("collection", ""), "data_scope collection"),
        entities=_strings(scope.get("entities", []), "data_scope entities"),
    )


def _operator_attributes(value: object) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise config.CliError(config.REQUEST, "operator_attributes must be an object")
    parsed: dict[str, dict[str, Any]] = {}
    for name, attributes in cast("dict[str, object]", value).items():
        if not isinstance(attributes, dict):
            raise config.CliError(
                config.REQUEST, f"operator_attributes.{name} must be an object of attributes"
            )
        parsed[name] = dict(cast("dict[str, Any]", attributes))
    return parsed


def planning_request(document: object, goal: str | None) -> PlanningRequest:
    """A ``PlanningRequest`` from the JSON ``--request-file`` holds.

    The request is a nested object — queries with their own tags and bounds, per-operator
    attributes, an optional data scope, an allowlist and five numeric limits — so it arrives
    as a document rather than as a mini-language spread across argv. ``--goal`` overrides
    the one field a caller changes between otherwise identical runs.
    """
    if not isinstance(document, dict):
        raise config.CliError(config.REQUEST, "--request-file must hold a JSON object")
    request = cast("dict[str, object]", document)
    unknown = sorted(set(request) - REQUEST_FIELDS)
    if unknown:
        raise config.CliError(
            config.REQUEST,
            f"--request-file has field(s) a planning request does not have: "
            f"{', '.join(unknown)}. The fields are {', '.join(sorted(REQUEST_FIELDS))}.",
        )
    bounds = {
        name: _integer(request[name], name)
        for name in (
            "max_discovery_cards",
            "max_candidates",
            "max_steps",
            "max_nodes",
            "max_edges",
        )
        if name in request
    }
    return PlanningRequest(
        goal=goal if goal is not None else _string(request.get("goal", ""), "goal"),
        discovery_queries=_discovery_queries(request.get("discovery_queries")),
        operator_attributes=_operator_attributes(request.get("operator_attributes", {})),
        data_scope=_data_scope(request.get("data_scope")),
        allowed_operator_ids=_strings(
            request.get("allowed_operator_ids", []), "allowed_operator_ids"
        ),
        input_label=_string(request.get("input_label", "input"), "input_label"),
        output_label=_string(request.get("output_label", "output"), "output_label"),
        **bounds,
    )


def plan_generator(
    planner: str,
    request: PlanningRequest,
    registry: OperatorRegistry,
    settings: config.Settings,
    model: str | None,
    send_data_context: bool,
) -> PlanGenerator:
    """The generator behind ``--planner``, with what it was configured with recorded.

    The provider-backed one is given the request's own allowlist. That list is an
    authorization boundary rather than a filter — a card is described to a model only
    because the request named it — so the CLI does not supply one of its own when the
    request left it empty.
    """
    if planner == "rule":
        if send_data_context:
            raise config.CliError(
                config.USAGE,
                "--send-data-context discloses a schema snapshot to a model, and the rule "
                "planner calls none. Drop the flag, or pass --planner openai.",
            )
        return RulePlanGenerator()
    if not request.allowed_operator_ids:
        raise config.CliError(
            config.REQUEST,
            "--planner openai needs allowed_operator_ids in the request file: the "
            "allowlist is what a card has to be on before it is described to a model, and "
            "an empty one authorizes nothing.",
        )
    chosen_model = settings.take("planner.model", model, "BLUE_DATA_OPS_PLANNER_MODEL")
    timeout = settings.take("planner.timeout_seconds", None, "BLUE_DATA_OPS_PLANNER_TIMEOUT")
    tokens = settings.take(
        "planner.max_output_tokens", None, "BLUE_DATA_OPS_PLANNER_MAX_OUTPUT_TOKENS"
    )
    return OpenAIPlanGenerator(
        str(chosen_model),
        registry=registry,
        allowed_operator_ids=request.allowed_operator_ids,
        client=build_openai_client(),
        send_data_context=send_data_context,
        timeout_seconds=float(cast("float", timeout)),
        max_output_tokens=int(cast("int", tokens)),
    )


# ---------------------------------------------------------------- execution --
def load_plan(record: PlanRecord) -> DataPipeline:
    """A ``DataPipeline`` from a stored record, with a malformed one reported as a request.

    The library raises a bare exception for a record that fails its shape check, which the
    CLI would otherwise publish as an internal failure. The record here came from a file
    somebody wrote, so it is a request that was wrong.
    """
    try:
        return DataPipeline.from_dict(record)
    except config.CliError:
        raise
    except Exception as error:
        raise config.CliError(
            config.REQUEST,
            f"this is not a serialized pipeline: {error}. A pipeline record carries an id, "
            f"a type, its nodes and its declared input and output.",
        ) from None


def operator_nodes(plan: DataPipeline, preflight: PipelinePreflight) -> list[tuple[str, str]]:
    """Each operator node paired with the id it resolves to.

    ``node_order`` carries the input and output nodes as well; ``operator_ids`` does not,
    and is in the same order, so the two line up only once those two are dropped.
    """
    nodes = plan.get_nodes()
    operator_ids = [
        node_id
        for node_id in preflight.node_order
        if nodes.get(node_id, {}).get("type") == str(NodeType.OPERATOR)
    ]
    return list(zip(operator_ids, preflight.operator_ids))


def registry_properties(
    operator_ids: tuple[str, ...],
    registry: OperatorRegistry,
    reporter: config.Reporter,
) -> dict[str, Any]:
    """The ``data_registry`` seam, built only where a node in this graph needs one."""
    cards = [registry.get_card(operator_id) for operator_id in operator_ids]
    needed = [card for card in cards if card is not None and config.requires_data_registry(card)]
    if not needed:
        return {}
    if config.registry_is_ephemeral():
        reporter.warn(
            "BLUE_DATA_REGISTRY_STORE is memory, so this registry lives only for this "
            "command and anything written to it is gone when it ends."
        )
    return {"data_registry": config.build_registry_seam()}


def node_run_payload(run: PipelineRun) -> list[dict[str, Any]]:
    return [
        {
            "node_id": node.node_id,
            "operator_id": node.operator_id,
            "status": str(node.status),
            "is_empty": node.exec_meta.is_empty,
            "errors": error_payload(node.exec_meta),
        }
        for node in run.node_runs
    ]


# ------------------------------------------------------------------ commands --
@click.group("pipeline", cls=config.Group)
def pipeline_group() -> None:
    """Plan, store, inspect and run operator pipelines."""


@pipeline_group.command("add")
@click.argument("name")
@click.option(
    "--request-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, allow_dash=True, path_type=str),
    help="JSON planning request: the goal, the discovery queries, the per-operator "
    "attributes, and the bounds. - reads standard input.",
)
@click.option("--goal", default=None, help="Replace the goal the request file carries.")
@click.option(
    "--planner",
    type=click.Choice(PLANNERS),
    default=None,
    show_default="the profile's BLUE_DATA_OPS_PLANNER, else rule",
    help="rule uses the shipped templates; openai calls a model and needs the OpenAI SDK.",
)
@click.option(
    "--model",
    default=None,
    show_default="the profile's BLUE_DATA_OPS_PLANNER_MODEL, else gpt-6-luna",
    help="Model the openai planner calls.",
)
@click.option(
    "--send-data-context",
    is_flag=True,
    default=False,
    help="Disclose the request's schema snapshot to the planning model. Off by default.",
)
@config.confirm_option
@config.catalog_option
@config.format_option
@config.log_options
@click.pass_obj
def pipeline_add(
    obj: dict[str, Any],
    name: str,
    request_file: str,
    goal: str | None,
    planner: str | None,
    model: str | None,
    send_data_context: bool,
    confirm: bool,
    catalog_name: str | None,
    output_format: str | None,
    log: bool,
    log_limit: int | None,
) -> None:
    """Plan a pipeline from a request and store it under NAME.

    This is not `pipeline import`: import reads a graph that already exists, add
    synthesizes one from a goal and a set of discovery queries.

    \b
    blue-ops pipeline add nightly --request-file request.json
    blue-ops pipeline add nightly --request-file request.json --goal "average order total"
    """
    published = config.Output(output_format)
    with config.reporting(published, log=log):
        resolver = config.start(obj)
        fmt = published.resolve(resolver)
        reporter = config.Reporter(fmt, log, config.resolve_log_limit(resolver, log_limit))
        catalog = config.resolve_catalog(resolver, catalog_name)
        store = store_for(obj, resolver.profile)
        check_name(name)
        if store.exists(name) and not records.confirm(
            f"Replace the stored pipeline {name!r} in profile {resolver.profile}?",
            confirm,
            "Pass --confirm to replace it.",
        ):
            reporter.note(f"Kept {name}.")
            return

        settings = config.Settings(resolver)
        chosen = str(settings.take("planner", planner, "BLUE_DATA_OPS_PLANNER"))
        if chosen not in PLANNERS:
            raise config.CliError(
                config.CONFIG,
                f"BLUE_DATA_OPS_PLANNER is {chosen!r}; expected one of {', '.join(PLANNERS)}",
            )
        request = planning_request(records.load_json(request_file, "--request-file"), goal)
        registry = config.build_catalog(catalog)
        generator = plan_generator(chosen, request, registry, settings, model, send_data_context)
        provider = None
        if request.data_scope is not None:
            provider = RegistryDataContextProvider(config.build_registry_seam())

        reporter.line(f"planning {name} with the {chosen} planner against the {catalog} catalog")
        with reporter.status(f"Planning {name}…"):
            result = PipelinePlanner(registry, generator, data_context_provider=provider).plan(
                request
            )

        record = result.pipeline.to_dict()
        provenance = {
            "origin": "plan",
            "created": now(),
            "planner": chosen,
            "catalog": catalog,
            "goal": request.goal,
        }
        store.write(name, record, provenance)
        operator_ids = list(result.preflight.operator_ids)
        rows = [
            {"Node": node_id, "Operator": operator_id}
            for node_id, operator_id in operator_nodes(result.pipeline, result.preflight)
        ]
        result_view = formats.tabular(
            ("Node", "Operator"),
            rows,
            {
                "pipeline": record,
                "name": name,
                "provenance": provenance,
                "planning": {
                    "discovered": list(result.discovery.operator_ids),
                    "candidates": len(result.candidates),
                    "operator_ids": operator_ids,
                    "node_order": list(result.preflight.node_order),
                },
                "settings": settings.envelope(),
            },
            sentences=(
                f"Planned {name} with {len(operator_ids)} operator step(s): "
                f"{', '.join(operator_ids) or 'none'}.",
                f"Stored in profile {resolver.profile}.",
            ),
            notes=(f"stored as {name} in profile {resolver.profile}", settings.footer()),
            title=f"pipeline: {name}",
            empty="(the plan has no operator nodes)",
        )
    formats.render(result_view, fmt)


@pipeline_group.command("import")
@click.argument("name")
@click.option(
    "--pipeline-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, allow_dash=True, path_type=str),
    help="JSON file holding a serialized pipeline; - reads standard input.",
)
@config.confirm_option
@config.catalog_option
@config.format_option
@click.pass_obj
def pipeline_import(
    obj: dict[str, Any],
    name: str,
    pipeline_file: str,
    confirm: bool,
    catalog_name: str | None,
    output_format: str | None,
) -> None:
    """Store a serialized pipeline under NAME, after checking that it can run.

    This is not `pipeline add`: import reads a graph that already exists.

    \b
    blue-ops pipeline import nightly --pipeline-file nightly.json
    """
    published = config.Output(output_format)
    with config.reporting(published):
        resolver = config.start(obj)
        fmt = published.resolve(resolver)
        catalog = config.resolve_catalog(resolver, catalog_name)
        store = store_for(obj, resolver.profile)
        check_name(name)
        if store.exists(name) and not records.confirm(
            f"Replace the stored pipeline {name!r} in profile {resolver.profile}?",
            confirm,
            "Pass --confirm to replace it.",
        ):
            config.Reporter(fmt).note(f"Kept {name}.")
            return
        document = records.load_json(pipeline_file, "--pipeline-file")
        if not isinstance(document, dict):
            raise config.CliError(config.REQUEST, "--pipeline-file must hold a JSON object")
        plan = load_plan(cast("PlanRecord", document))
        registry = config.build_catalog(catalog)
        preflight = PipelineExecutor(registry).preflight(plan)
        record = plan.to_dict()
        provenance = {
            "origin": "import",
            "created": now(),
            "planner": None,
            "catalog": catalog,
            "goal": None,
        }
        store.write(name, record, provenance)
        rows = [
            {"Node": node_id, "Operator": operator_id}
            for node_id, operator_id in operator_nodes(plan, preflight)
        ]
        result = formats.tabular(
            ("Node", "Operator"),
            rows,
            {
                "pipeline": record,
                "name": name,
                "preflight": {
                    "node_order": list(preflight.node_order),
                    "operator_ids": list(preflight.operator_ids),
                },
            },
            sentences=(
                f"Imported {name} with {len(preflight.operator_ids)} operator step(s).",
                f"Stored in profile {resolver.profile}.",
            ),
            notes=(f"stored as {name} in profile {resolver.profile}",),
            title=f"pipeline: {name}",
            empty="(the pipeline has no operator nodes)",
        )
    formats.render(result, fmt)


@pipeline_group.command("export")
@click.argument("name")
@click.option(
    "--output-file",
    type=click.Path(dir_okay=False, writable=True, path_type=str),
    default=None,
    help="Write the record here instead of to standard output.",
)
@config.confirm_option
@click.pass_obj
def pipeline_export(obj: dict[str, Any], name: str, output_file: str | None, confirm: bool) -> None:
    """Write a stored pipeline out as the JSON record it is.

    There is no format option here: an export emits the artifact, and a pipeline's
    artifact is its serialized record.

    \b
    blue-ops pipeline export nightly
    blue-ops pipeline export nightly --output-file nightly.json
    """
    with config.reporting("table"):
        resolver = config.start(obj)
        store = store_for(obj, resolver.profile)
        text = store.read_text(name)
        reporter = config.Reporter()
        if output_file is None:
            click.echo(text.rstrip("\n"))
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
    reporter.note(f"Wrote {name} to {target}.")


@pipeline_group.command("list")
@config.format_option
@click.pass_obj
def pipeline_list(obj: dict[str, Any], output_format: str | None) -> None:
    """List the pipelines stored in this profile.

    \b
    blue-ops pipeline list
    blue-ops pipeline list --format json
    """
    published = config.Output(output_format)
    with config.reporting(published):
        resolver = config.start(obj)
        fmt = published.resolve(resolver)
        store = store_for(obj, resolver.profile)
        entries: list[dict[str, Any]] = []
        for name in store.names():
            record = store.read(name)
            provenance = store.provenance(name)
            nodes = cast("dict[str, Any] | None", record.get("nodes"))
            entries.append(
                {
                    "name": name,
                    "label": record.get("label"),
                    "nodes": len(nodes) if isinstance(nodes, dict) else 0,
                    "origin": provenance.get("origin"),
                    "created": provenance.get("created"),
                }
            )
        rows = [
            {
                "Pipeline": entry["name"],
                "Label": entry["label"] or "",
                "Nodes": entry["nodes"],
                "Origin": entry["origin"] or "",
                "Created": entry["created"] or "",
            }
            for entry in entries
        ]
        result = formats.tabular(
            ("Pipeline", "Label", "Nodes", "Origin", "Created"),
            rows,
            {"pipelines": entries, "profile": resolver.profile, "count": len(entries)},
            sentences=(
                f"Profile {resolver.profile} holds {len(entries)} stored pipeline(s)"
                f"{': ' + ', '.join(entry['name'] for entry in entries) if entries else ''}.",
            ),
            empty=(
                f"(no stored pipelines in profile {resolver.profile} — run "
                f"`{config.PROGRAM} pipeline add NAME --request-file PATH`)"
            ),
        )
    formats.render(result, fmt)


@pipeline_group.command("inspect")
@click.argument("name")
@config.catalog_option
@config.format_option
@click.pass_obj
def pipeline_inspect(
    obj: dict[str, Any], name: str, catalog_name: str | None, output_format: str | None
) -> None:
    """Print a stored pipeline's nodes in the order it would run them.

    \b
    blue-ops pipeline inspect nightly
    blue-ops pipeline inspect nightly --format json
    """
    published = config.Output(output_format)
    with config.reporting(published):
        resolver = config.start(obj)
        fmt = published.resolve(resolver)
        catalog = config.resolve_catalog(resolver, catalog_name)
        store = store_for(obj, resolver.profile)
        record = store.read(name)
        provenance = store.provenance(name)
        plan = load_plan(record)
        registry = config.build_catalog(catalog)
        preflight = PipelineExecutor(registry).preflight(plan)
        nodes = plan.get_nodes()
        operators = dict(operator_nodes(plan, preflight))
        entries: list[dict[str, Any]] = []
        for node_id in preflight.node_order:
            node: PlanRecord = nodes.get(node_id, {})
            entries.append(
                {
                    "node_id": node_id,
                    "type": node.get("type"),
                    "label": node.get("label"),
                    "operator_id": operators.get(node_id),
                    "next": list(cast("list[str]", node.get("next", []))),
                }
            )
        rows = [
            {
                "Node": entry["node_id"],
                "Type": entry["type"],
                "Label": entry["label"] or "",
                "Operator": entry["operator_id"] or "",
                "Feeds": ", ".join(entry["next"]),
            }
            for entry in entries
        ]
        result = formats.tabular(
            ("Node", "Type", "Label", "Operator", "Feeds"),
            rows,
            {
                "pipeline": {"nodes": entries},
                "name": name,
                "provenance": provenance,
                "preflight": {
                    "node_order": list(preflight.node_order),
                    "operator_ids": list(preflight.operator_ids),
                },
            },
            sentences=(
                f"{name} runs {len(preflight.operator_ids)} operator(s) over "
                f"{len(entries)} node(s): {', '.join(preflight.operator_ids) or 'none'}.",
                f"It was {provenance.get('origin') or 'stored'} on "
                f"{provenance.get('created') or 'an unrecorded date'}.",
            ),
            title=f"pipeline: {name}",
            empty=f"({name} has no nodes)",
        )
    formats.render(result, fmt)


@pipeline_group.command("remove")
@click.argument("name")
@config.confirm_option
@click.pass_obj
def pipeline_remove(obj: dict[str, Any], name: str, confirm: bool) -> None:
    """Delete one stored pipeline.

    Only that pipeline's directory goes: not another pipeline, not the profile, and not
    the catalog selection beside it.

    \b
    blue-ops pipeline remove nightly --confirm
    """
    with config.reporting("table"):
        resolver = config.start(obj)
        store = store_for(obj, resolver.profile)
        reporter = config.Reporter()
        if not store.exists(name):
            raise config.CliError(
                config.REQUEST,
                f"no stored pipeline named {name!r} in profile {resolver.profile}. Run "
                f"`{config.PROGRAM} pipeline list` to see them.",
            )
        if not records.confirm(
            f"Remove the stored pipeline {name!r} from profile {resolver.profile}?",
            confirm,
            f"Pass --confirm to remove {name!r} without asking.",
        ):
            reporter.note(f"Kept {name}.")
            return
        store.remove(name)
    formats.console().print(f"Removed pipeline: {name}", style="bold")


@pipeline_group.command("run")
@click.argument("name")
@click.option(
    "--input-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, allow_dash=True, path_type=str),
    help="JSON file holding the record groups to run on; - reads standard input.",
)
@click.option(
    "--model",
    default=None,
    show_default="the profile's BLUE_DATA_LLM_MODEL, else gpt-6-luna",
    help="Default model for language-model operator nodes in this run.",
)
@click.option(
    "--reasoning-effort",
    default=None,
    help="Default reasoning effort for language-model operator nodes in this run.",
)
@config.catalog_option
@config.format_option
@config.log_options
@click.pass_obj
def pipeline_run(
    obj: dict[str, Any],
    name: str,
    input_file: str,
    model: str | None,
    reasoning_effort: str | None,
    catalog_name: str | None,
    output_format: str | None,
    log: bool,
    log_limit: int | None,
) -> None:
    """Run a stored pipeline over a record bundle.

    The stored record is never rewritten. Execution records what happened on the plan it
    is handed, so the copy that runs is in memory and the one on disk is left as it was.

    \b
    blue-ops pipeline run nightly --input-file orders.json
    blue-ops pipeline run nightly --input-file - --format json
    """
    published = config.Output(output_format)
    with config.reporting(published, log=log):
        resolver = config.start(obj)
        fmt = published.resolve(resolver)
        reporter = config.Reporter(fmt, log, config.resolve_log_limit(resolver, log_limit))
        catalog = config.resolve_catalog(resolver, catalog_name)
        store = store_for(obj, resolver.profile)
        registry = config.build_catalog(catalog)

        # Parsed from the file on this call and handed straight to the executor, which
        # writes each node's value and status onto it. Nothing here writes it back.
        plan = load_plan(store.read(name))
        preflight = PipelineExecutor(registry).preflight(plan)
        uses_llm = any(
            config.requires_llm(card)
            for operator_id in preflight.operator_ids
            if (card := registry.get_card(operator_id)) is not None
        )
        if not uses_llm and (model is not None or reasoning_effort is not None):
            raise config.CliError(
                config.USAGE,
                f"{name} has no language-model operator for --model or --reasoning-effort.",
            )
        bundle: DataBundle = records.load_bundle(input_file)

        settings = config.Settings(resolver)
        properties: dict[str, Any] = {}
        timeout = settings.take("execution.timeout_seconds", None, "BLUE_DATA_OPS_TIMEOUT")
        if timeout is not None:
            properties["execution.timeout_seconds"] = timeout
        if uses_llm:
            applied_model = settings.take("openai.model", model, "BLUE_DATA_LLM_MODEL")
            if applied_model is not None:
                properties["openai.model"] = applied_model
            applied_effort = settings.take("llm.reasoning_effort", reasoning_effort)
            if applied_effort is not None:
                properties["llm.reasoning_effort"] = applied_effort
        properties.update(registry_properties(preflight.operator_ids, registry, reporter))

        started = time.monotonic()
        with config.execution_logging(reporter), reporter.status(f"Running {name}…"):
            run = PipelineExecutor(registry).execute(plan, bundle, properties)
        elapsed = round(time.monotonic() - started, 3)

        for node in run.node_runs:
            for line in node.exec_meta.logs:
                reporter.line(f"{node.node_id}: {line}")
            for key, value in node.exec_meta.traces.items():
                reporter.line(f"{node.node_id} {key}: {value}")
            for notice in config.recoverable_notices(node.exec_meta.errors):
                reporter.warn(f"{node.node_id}: {notice}")

        node_runs = node_run_payload(run)
        if not run.succeeded:
            # The work that did happen goes to standard error, so it is visible in every
            # format while standard output still carries one object and nothing else, and
            # into the failure's detail, so a machine consumer gets it too.
            for node in run.node_runs:
                reporter.note(f"{node.node_id} ({node.operator_id}): {node.status}")
            detail: dict[str, Any] = {
                "name": name,
                "failed_node_id": run.failed_node_id,
                "node_runs": node_runs,
                "elapsed_seconds": elapsed,
            }
            failed = next(
                (node for node in run.node_runs if node.node_id == run.failed_node_id), None
            )
            failure = config.execution_failure(
                failed.exec_meta.errors if failed else [], stopped_pipeline=True
            )
            if failure is None:
                raise config.CliError(
                    config.EXECUTION,
                    f"{name} stopped at node {run.failed_node_id!r} without an error "
                    f"record. Run it again with --log for the steps it did take.",
                    detail,
                )
            raise config.CliError(
                failure.code, failure.message, {**(failure.detail or {}), **detail}
            )

        columns, rows = bundle_table(run.output_data)
        result = formats.tabular(
            columns,
            rows,
            {
                "result": {"output_data": run.output_data},
                "name": name,
                "succeeded": run.succeeded,
                "failed_node_id": run.failed_node_id,
                "node_runs": node_runs,
                "elapsed_seconds": elapsed,
                "settings": {
                    **settings.envelope(),
                    "scope": "invocation_defaults",
                },
            },
            sentences=(
                f"{name} ran {len(run.node_runs)} node(s) in {elapsed}s and returned "
                f"{sum(len(group) for group in run.output_data)} record(s).",
            ),
            notes=(settings.footer().replace("settings:", "invocation defaults:", 1),),
            title=f"pipeline: {name}",
            empty=f"(no records — {name} returned an empty bundle)",
        )
    formats.render(result, fmt)
