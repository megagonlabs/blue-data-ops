"""``blue-ops metadata`` — what is installed, and which catalog it is pointed at.

The family uses ``metadata inspect`` for the identity and version of what a CLI is sitting
on. Here that is the four distributions in play, the interpreter, which optional extras
resolve, and the catalog a command would read if it ran now. Nothing here contacts anything:
an extra is reported present when its module can be located, not by importing it, so asking
what is installed never pays for loading a model runtime.
"""

from __future__ import annotations

import importlib.util
import platform
from importlib import metadata as distributions
from typing import Any

import click

from blue_data_ops_cli import config, formats

CORE_DISTRIBUTION = "blue-data-ops"
MCP_DISTRIBUTION = "blue-data-ops-mcp"
DATA_DISTRIBUTION = "blue-data"

EXTRA_MODULES: dict[str, tuple[str, ...]] = {
    "ml": ("numpy", "sklearn"),
    "vector": ("numpy", "sentence_transformers"),
    "llm": ("litellm", "tenacity", "diskcache", "jinja2"),
    "openai": ("openai",),
}
"""What each declared extra puts on the path, by import name rather than by package name."""

NOT_INSTALLED = "(not installed)"


def distribution_version(name: str) -> str | None:
    try:
        return distributions.version(name)
    except distributions.PackageNotFoundError:
        return None


def module_present(name: str) -> bool:
    """Whether *name* can be located, without importing it.

    ``find_spec`` imports a parent package but not the module itself, and every name here is
    top-level, so nothing is imported at all.
    """
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def installed_extras() -> dict[str, bool]:
    return {
        extra: all(module_present(module) for module in modules)
        for extra, modules in EXTRA_MODULES.items()
    }


@click.group("metadata", cls=config.Group)
def metadata_group() -> None:
    """Inspect what is installed."""


@metadata_group.command("inspect")
@config.catalog_option
@config.format_option
@click.pass_obj
def metadata_inspect(
    obj: dict[str, Any], catalog_name: str | None, output_format: str | None
) -> None:
    """Print the installed versions, the extras that resolve, and the selected catalog.

    \b
    blue-ops metadata inspect
    blue-ops metadata inspect --format json
    """
    published = config.Output(output_format)
    with config.reporting(published):
        resolver = config.start(obj)
        fmt = published.resolve(resolver)
        catalog = config.resolve_catalog(resolver, catalog_name)
        registry = config.build_catalog(catalog)
        cards = len(registry.list_cards())
        extras = installed_extras()
        core = distribution_version(CORE_DISTRIBUTION)
        mcp = distribution_version(MCP_DISTRIBUTION)
        data = distribution_version(DATA_DISTRIBUTION)

        payload: dict[str, Any] = {
            config.DISTRIBUTION: config.cli_version(),
            CORE_DISTRIBUTION: core,
            MCP_DISTRIBUTION: mcp,
            DATA_DISTRIBUTION: data,
            "python": platform.python_version(),
            "extras": extras,
            "catalog": catalog,
            "cards": cards,
        }
        present = sorted(name for name, found in extras.items() if found)
        rows = {
            config.DISTRIBUTION: config.cli_version(),
            CORE_DISTRIBUTION: core or NOT_INSTALLED,
            MCP_DISTRIBUTION: mcp or NOT_INSTALLED,
            DATA_DISTRIBUTION: data or NOT_INSTALLED,
            "python": platform.python_version(),
            "extras": ", ".join(present) or "(none)",
            "catalog": catalog,
            "cards": cards,
        }
        result = formats.key_value(
            rows,
            payload={"metadata": payload},
            sentences=(
                f"{config.DISTRIBUTION} {config.cli_version()} on "
                f"{CORE_DISTRIBUTION} {core or NOT_INSTALLED}, Python "
                f"{platform.python_version()}.",
                f"The {catalog} catalog holds {cards} card(s).",
                f"Extras present: {', '.join(present) or 'none'}.",
            ),
            title="metadata",
        )
    formats.render(result, fmt)
