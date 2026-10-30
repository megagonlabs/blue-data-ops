"""The two unbounded input channels: record bundles, and ``KEY=VALUE`` attributes.

Everything a caller hands this CLI that is not a name or a closed set arrives here. A
record bundle comes from a file or from standard input; operator attributes and call
properties come from a JSON file, from repeated ``KEY=VALUE`` options, or from both.

Two rules are worth stating where they are implemented.

*A key that names a credential is refused, at every depth.* ``--attribute`` and
``--property`` are the only places in this CLI where a caller chooses both the name and the
value, and both land in argv and in shell history before any code here can reach them.
Masking cannot help after that, so the key is refused instead, naming the command that
stores a secret properly. The value is structured — ``--attribute properties={...}`` is an
ordinary way to pass database settings — and a credential one level down is in argv exactly
as much as one at the top, so the refusal walks the decoded objects and arrays rather than
stopping at the outer key. Each key is folded before it is read — camel humps and separators
alike become word boundaries — because ``clientSecret`` and ``client_secret`` are one name
written twice and a settings object is as likely to spell it either way. The vocabulary
deliberately does not hold bare ``key``, so ``argmax_key``, ``partition_key`` and
``foreignKeys`` pass at any depth; they are ordinary attribute names throughout the library.

A refusal names the key and where it sits, and never the value. Repeating the value would
put the credential on stderr and into whatever collects it, which is the thing being
prevented.

*A value is JSON, and a bare word is a string.* ``--attribute limit=5`` has to mean the
number and ``--attribute key=total`` has to mean the word, so the value is parsed as JSON
and falls back to itself when that fails. A caller who wants the string ``"5"`` writes
``--attribute value='"5"'``.

The merge order is the file first, then the per-key options, so one option overrides one
key of a file rather than replacing the file.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import click
from blue_data_ops.operators import DataBundle

from blue_data_ops_cli import config
from blue_data_ops_cli.mask import is_credential_key

STDIN = "-"
"""The path that means standard input, which Click spells the same way."""


def read_text(path: str, label: str) -> str:
    """The file's text, or standard input where *path* is ``-``."""
    if path == STDIN:
        # `sys.stdin` rather than `click.get_text_stream`, which Click deprecated and removes
        # in 9.0. This package declares `click>=8.0`, so that release resolves.
        return sys.stdin.read()
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise config.CliError(config.REQUEST, f"{label} could not be read: {error}") from None


def decode_json(text: str, label: str) -> Any:
    """One JSON document, with a parse failure reported as a bad request rather than raised.

    Separate from :func:`load_json` so that a caller which has to open the file itself — the
    pipeline store opens its own, refusing to follow a link — still reports a malformed
    document in the same words.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise config.CliError(
            config.REQUEST, f"{label} is not valid JSON: {error.msg} at line {error.lineno}"
        ) from None


def load_json(path: str, label: str) -> Any:
    """One JSON document from a file or from standard input."""
    return decode_json(read_text(path, label), label)


def load_mapping(path: str, label: str) -> dict[str, Any]:
    """A JSON object, refused when the document is anything else."""
    document: object = load_json(path, label)
    if not isinstance(document, dict):
        raise config.CliError(
            config.REQUEST,
            f"{label} must hold a JSON object of name/value pairs, not {type(document).__name__}",
        )
    return {str(key): value for key, value in cast("dict[Any, Any]", document).items()}


def _is_bundle(value: object) -> bool:
    """Whether *value* is ``list[list[dict]]`` all the way down."""
    if not isinstance(value, list):
        return False
    for group in cast("list[object]", value):
        if not isinstance(group, list):
            return False
        if any(not isinstance(record, dict) for record in cast("list[object]", group)):
            return False
    return True


def load_bundle(path: str, label: str = "--input-file") -> DataBundle:
    """A record bundle: ``list[list[dict]]``, which is what every operator consumes.

    The shape is checked here rather than left to the operator, because the operator
    reports a malformed bundle as an execution failure and this is a request that was wrong
    before anything ran.
    """
    document: object = load_json(path, label)
    if not _is_bundle(document):
        raise config.CliError(
            config.REQUEST,
            f"{label} must hold a list of record groups, written as [[{{...}}]]. "
            f"An operator consumes groups of records, so the outer list is the groups and "
            f"the inner list is the records in one group.",
        )
    groups = cast("list[list[dict[str, Any]]]", document)
    return [[dict(record) for record in group] for group in groups]


def _value_of(raw: str) -> Any:
    """JSON where it parses, the literal string where it does not."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _credential_key_at(value: object, path: str) -> str | None:
    """Where the first credential-shaped key sits inside *value*, or ``None``.

    Only keys are read. The walk descends through decoded objects and arrays, so a key one
    level down is answered exactly like one at the top, and it reports a path rather than a
    bare name so a refusal can say where to look without quoting what was held there.
    """
    if isinstance(value, dict):
        for name, held in cast("dict[Any, Any]", value).items():
            here = f"{path}.{name}"
            if is_credential_key(str(name)):
                return here
            found = _credential_key_at(held, here)
            if found is not None:
                return found
    elif isinstance(value, list):
        for index, held in enumerate(cast("list[Any]", value)):
            found = _credential_key_at(held, f"{path}[{index}]")
            if found is not None:
                return found
    return None


def _credential_refusal(option: str, key: str, path: str | None) -> str:
    """Why the key is refused and what to do instead, without repeating what it held."""
    where = "" if path is None else f" The key is {path}, inside the value {key} decoded to."
    return (
        f"{option} {key}=... would put a credential in argv and in this shell's history."
        f"{where} Store it once with `{config.PROGRAM} profile config OPENAI_API_KEY`, "
        f"which prompts with the input hidden, and the run reads it from there."
    )


def parse_pairs(pairs: Sequence[str], option: str) -> dict[str, Any]:
    """``KEY=VALUE`` options as a mapping, with a credential-shaped key refused at any depth."""
    parsed: dict[str, Any] = {}
    for pair in pairs:
        key, separator, raw = pair.partition("=")
        name = key.strip()
        if not separator or not name:
            raise config.CliError(
                config.USAGE,
                f"{option} takes KEY=VALUE, and {pair!r} has no key. "
                f"For example: {option} limit=5.",
            )
        if is_credential_key(name):
            raise config.CliError(config.USAGE, _credential_refusal(option, name, None))
        value = _value_of(raw)
        nested = _credential_key_at(value, name)
        if nested is not None:
            raise config.CliError(config.USAGE, _credential_refusal(option, name, nested))
        parsed[name] = value
    return parsed


def merged(path: str | None, pairs: Sequence[str], option: str, label: str) -> dict[str, Any]:
    """The file's object, then the per-key options on top of it."""
    values: dict[str, Any] = {} if path is None else load_mapping(path, label)
    values.update(parse_pairs(pairs, option))
    return values


def confirm(question: str, skip: bool, remedy: str) -> bool:
    """Ask before something irreversible, and say so when there is nobody to ask.

    ``False`` means the caller answered no, which is not a failure: the question was asked
    and it was answered. With no terminal behind standard input the command refuses rather
    than blocking on a prompt nothing will ever answer.
    """
    if skip:
        return True
    try:
        return click.confirm(question, err=True)
    except click.Abort:
        raise config.CliError(
            config.USAGE, f"there is nothing to read an answer from. {remedy}"
        ) from None
