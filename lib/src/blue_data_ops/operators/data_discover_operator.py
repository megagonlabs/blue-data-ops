from __future__ import annotations

import logging
import re
import traceback
from typing import Any, ClassVar, cast
from urllib.parse import unquote_plus, urlsplit, urlunsplit

from blue_data_ops.data import RegistrySeam, resolve_registry
from blue_data_ops.operators._discovery import DiscoverySpec
from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.types import (
    Attributes,
    AttributeSpec,
    DataBundle,
    FunctionResult,
    Properties,
    ValidationResult,
)

logger = logging.getLogger(__name__)


class _DataDiscoverFailure(Exception):
    pass


def _construct_scope(
    scope: str | None,
    source: str | None,
    database: str | None,
    collection: str | None,
    concept_type: str,
    auto_construct: bool = True,
) -> str | None:
    """Construct search scope from attributes based on data registry hierarchy."""
    if scope is None:
        # Upstream returns None outright here — source/database/collection do NOT
        # produce a scope unless an explicit scope string is provided (its own TODO
        # notes the ambiguity). Kept as-is.
        return None

    if not auto_construct:
        return scope.rstrip("/") if scope else "/"

    if scope and scope != "/":
        base_scope = scope.rstrip("/")
    else:
        base_scope = "/"
        if source:
            base_scope = f"/source/{source}"
            if database:
                base_scope = f"/source/{source}/database/{database}"
                if collection:
                    base_scope = f"/source/{source}/database/{database}/collection/{collection}"

    scope_parts = base_scope.split("/")
    scope_components: dict[str, str | None] = {
        "source": None,
        "database": None,
        "collection": None,
        "entity": None,
        "relation": None,
        "attribute": None,
    }

    for i, part in enumerate(scope_parts):
        if part in scope_components and i + 1 < len(scope_parts):
            scope_components[part] = scope_parts[i + 1]

    if source:
        scope_components["source"] = source
    if database:
        scope_components["database"] = database
    if collection:
        scope_components["collection"] = collection

    if concept_type == "source":
        return "/"
    elif concept_type == "database":
        if scope_components["source"]:
            return f"/source/{scope_components['source']}"
        return "/"
    elif concept_type == "collection":
        if scope_components["source"] and scope_components["database"]:
            return f"/source/{scope_components['source']}/database/{scope_components['database']}"
        elif scope_components["source"]:
            return f"/source/{scope_components['source']}"
        return "/"
    elif concept_type in ["entity", "relation"]:
        if (
            scope_components["source"]
            and scope_components["database"]
            and scope_components["collection"]
        ):
            return (
                f"/source/{scope_components['source']}/database/{scope_components['database']}"
                f"/collection/{scope_components['collection']}"
            )
        elif scope_components["source"] and scope_components["database"]:
            return f"/source/{scope_components['source']}/database/{scope_components['database']}"
        elif scope_components["source"]:
            return f"/source/{scope_components['source']}"
        return "/"
    elif concept_type == "attribute":
        if (
            scope_components["source"]
            and scope_components["database"]
            and scope_components["collection"]
            and scope_components["entity"]
        ):
            return (
                f"/source/{scope_components['source']}/database/{scope_components['database']}"
                f"/collection/{scope_components['collection']}/entity/{scope_components['entity']}"
            )
        elif (
            scope_components["source"]
            and scope_components["database"]
            and scope_components["collection"]
            and scope_components["relation"]
        ):
            return (
                f"/source/{scope_components['source']}/database/{scope_components['database']}"
                f"/collection/{scope_components['collection']}/relation/{scope_components['relation']}"
            )
        elif (
            scope_components["source"]
            and scope_components["database"]
            and scope_components["collection"]
        ):
            return (
                f"/source/{scope_components['source']}/database/{scope_components['database']}"
                f"/collection/{scope_components['collection']}"
            )
        elif scope_components["source"] and scope_components["database"]:
            return f"/source/{scope_components['source']}/database/{scope_components['database']}"
        elif scope_components["source"]:
            return f"/source/{scope_components['source']}"
        return "/"
    else:
        return base_scope


MASK = "***"
"""What a masked value reads as, spelled the way the rest of the family spells one."""

# A registered source keeps its connection settings in `properties`, and blue-data's
# own sources put a password in there: the SQL, graph and Redis sources all default
# `password`, and the Mongo source builds `protocol://username:password@host:port`
# from `username` and `password`. A discovery result is the useful half of that map —
# protocol, host, port, database — so the secret-shaped entries are masked and the
# rest is returned as it stands.
#
# Nothing constrains how a registrar spells a key, so the name is folded to one
# spelling before it is matched: `api-key`, `api.key`, `API KEY` and `apiKey` are the
# same setting and a rule that recognised only `api_key` masked one of the four.
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_SEPARATORS = re.compile(r"[^a-z0-9]+")


def _fold(name: str) -> str:
    """`api-key`, `api.key`, `API KEY`, `apiKey` and `APIKey` all fold to `api_key`."""
    return _SEPARATORS.sub("_", _CAMEL_BOUNDARY.sub("_", name).lower()).strip("_")


# `uid` is here rather than in the shape below because it is a whole name and not a
# fragment: ODBC spells the account name `UID` and its password `PWD`, and a rule that
# masked one of that pair and published the other would be masking the spelling rather
# than the setting. `uuid` and `guid` fold to themselves and are untouched.
_SECRET_NAMES = frozenset({"user", "user_name", "username", "login", "uid"})
# `pass_?phrase` rather than `passphrase`: a name is folded before it is matched, so the
# spelled-out `PASS PHRASE` arrives as `pass_phrase` and the undivided spelling did not
# reach it. The guide has listed `PASS PHRASE` as a covered spelling since the census was
# written; it was the one name in that list nothing masked.
_SECRET_SHAPE = re.compile(
    r"(?:^|_)(?:password|passwd|pwd|pass_?phrase|secret|token|credential|credentials"
    r"|auth|authorization|api_?key|apikey|access_?key|secret_?key|private_?key)(?:_|$)"
)
# Bare `key` is deliberately absent: `misc` carries primary and foreign keys, and a
# column name masked here would hide the shape of the data a caller came to discover.
# Folding does not change that — `foreignKeys` reads as `foreign_keys` and stays open.


def _is_secret_name(name: str) -> bool:
    folded = _fold(name)
    return folded in _SECRET_NAMES or bool(_SECRET_SHAPE.search(folded))


_URI = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://[^\s\"'<>]+")
"""A URI anywhere in a string, including one written into a sentence."""

_USERINFO = re.compile(r"(//)([^/@\s]+)(@)")
"""The `//user:pw@` half of an authority, found by shape when the parser cannot run."""

# A parameter name, written the way a connection string writes one. A query encodes a
# space as `%20` and, form-encoded, as `+`, so `api%5Fkey` and `api+key` are the setting
# spelled `api_key`. The captured name is decoded before it is classified.
_NAME_SOURCE = r"(?:[A-Za-z]|%[0-9A-Fa-f]{2})[A-Za-z0-9._%+\-]*"

# A value, read through whatever closes it. ODBC braces a value containing a delimiter and
# JDBC quotes one, and both escape their closing character by doubling it: `}}` inside
# braces and `""` inside quotes are literals, so a value runs past a doubled closer and
# ends at a single one. Stopping at the first closing character ended the value early and
# published its tail.
#
# The three escaping forms are possessive, so a value that never closes fails outright
# instead of backtracking onto the first closer it passed — which would publish the tail
# again by another route. It falls to the opener-with-no-closer form below.
#
# An opener with no closer runs to the end of the line rather than to the next delimiter.
# A value whose quoting is already broken cannot be read reliably to any earlier point, so
# what follows it is password material until something says otherwise, and `Pwd={p;secret`
# published `secret` while the rule stopped at the `;`. Only a credential's value is
# consumed, so the run can no longer hide a pair written after it under another name. It
# costs the tail of a malformed connection string: `Pwd={p q;Server=db` loses `Server=db`,
# which is a host rather than a way in.
_VALUE_SOURCE = (
    r"\{(?:[^}]|\}\})*+\}"
    r'|"(?:[^"]|"")*+"'
    r"|'(?:[^']|'')*+'"
    r"|\{.*"
    r'|".*'
    r"|'.*"
    r"|[^;&\s]*"
)

_NAME = re.compile(rf"({_NAME_SOURCE})=")
"""The name half of one pair, through the `=`."""

_VALUE = re.compile(_VALUE_SOURCE)
"""The value half, read from the character after the `=`."""

# The name half of a pair as the check and the run scanner read it, rather than as the
# grammar above writes one. Whitespace is inside a name and not a boundary: OLE DB spells
# keywords `Data Source` and `Initial Catalog`, so the complete name of `api key=…` is
# `api key`, which folds to the setting `api_key`. A line break is still a boundary —
# no connection keyword spans one.
_PUBLISHED_NAME_SOURCE = r"""[^;&?/="'{},\n\r]+"""

_PUBLISHED_NAME = re.compile(rf"({_PUBLISHED_NAME_SOURCE})=")
"""One published pair's name, through the `=`, whitespace and all."""

_RUN_PAIR = re.compile(rf"(?P<name>{_PUBLISHED_NAME_SOURCE})=(?:{_VALUE_SOURCE})")
"""One pair, name and value, as a run of parameters is walked."""

_RUN_JOIN = re.compile(r"[ \t]*[;&][ \t]*")
"""What joins one parameter to the next, with the whitespace a formatted string writes."""

# Which keywords say that a run of parameters is a connection. A connection string names
# what it reaches as well as who reaches it, and the first half is the half a sentence has
# no reason to write: `Driver`, `Server`, `Data Source`, `Initial Catalog`, `encrypt`. The
# credential half is deliberately absent — `token` and `authorization` are exactly what a
# schema documents, so they cannot be the evidence that the run around them is a
# connection. `schema` is absent for the same reason and it is not a near miss:
# `OAuth schema: token=required` folds to `oauth_schema_token`, so admitting `schema` would
# turn the one sentence this narrowing exists to protect into a connection string.
_CONNECTION_KEYWORD = re.compile(
    r"(?:^|_)(?:driver|server|data_?source|initial_?catalog|catalog|provider|database"
    r"|dbname|host|hostname|port|dsn|service_?name|network_?library|packet_?size"
    r"|connect(?:ion)?_?timeout|application_?name|encrypt|trusted_?connection"
    r"|integrated_?security|persist_?security_?info|ssl_?mode|charset)(?:_|$)"
)


def _names_a_connection(name: str) -> bool:
    """Whether one parameter name says what is being connected to rather than who by."""
    return bool(_CONNECTION_KEYWORD.search(_fold(unquote_plus(name.strip()))))


def _first_character(text: str, start: int) -> int:
    """Where a name actually begins, past the whitespace a delimiter left in front of it."""
    while start < len(text) and text[start].isspace():
        start += 1
    return start


def _connection_parameters(text: str) -> frozenset[int]:
    """Where every parameter of a connection run in *text* begins.

    A description holds both, and they are punctuated identically.
    `Driver=X; Password=p; Server=db` is a connection written the way Microsoft documents
    the format, with a space after each `;`, and
    `OAuth schema: token=required; authorization=optional` is a sentence about a schema.
    Adjacency cannot tell them apart, because both write `; `, and requiring adjacency
    published the first one. Adjacency is kept as one signal among several rather than
    dropped, because the tight spelling `Driver=X;Pwd=p` is a connection string and a
    sentence does not write one.

    So the run is identified by what it holds. A run is a maximal sequence of `name=value`
    pairs joined by a delimiter and whatever whitespace surrounds it, and it counts as a
    connection when a delimiter opens it, or when it joins two or more parameters and
    either a bare delimiter joins two of them or one of them names a connection structure
    rather than a credential. The bare-delimiter clause is the rule this replaced, kept so
    that nothing the narrower rule masked is published now: widening it to tolerate
    whitespace adds cases and removes none. A lone assignment in the middle of a sentence
    is still never a connection run, which is the fail-open this field took deliberately.

    What comes back is where each parameter starts, not the span the run covers, because a
    name reads back across whatever is in front of it. In
    `Driver=X; Pwd=p; Server=db. OAuth schema: token=required` the complete name before
    `required` is `db. OAuth schema: token`: it folds to something the census reads as a
    credential and it begins inside the connection string without being a parameter of it.
    A pair belongs to the run when it begins where a parameter begins.
    """
    grouped: list[list[re.Match[str]]] = []
    joined_bare: list[bool] = []
    for pair in _RUN_PAIR.finditer(text):
        join = _RUN_JOIN.fullmatch(text, grouped[-1][-1].end(), pair.start()) if grouped else None
        if join is None:
            grouped.append([pair])
            joined_bare.append(False)
        else:
            grouped[-1].append(pair)
            # A name absorbs the whitespace in front of it, so the join alone does not say
            # whether the delimiter was bare: `; Pwd` leaves `;` as the join and ` Pwd` as
            # the name. Both halves have to be tight.
            bare = len(join.group()) == 1 and not pair.group("name")[:1].isspace()
            joined_bare[-1] = joined_bare[-1] or bare

    parameters: set[int] = set()
    for run, bare in zip(grouped, joined_bare, strict=True):
        start = run[0].start()
        opened = start > 0 and text[start - 1] in "?;&" and not text[start].isspace()
        names_a_connection = any(_names_a_connection(pair.group("name")) for pair in run)
        if opened or (len(run) > 1 and (bare or names_a_connection)):
            parameters.update(_first_character(text, pair.start()) for pair in run)
    return frozenset(parameters)


def _in_a_connection_run(parameters: frozenset[int], text: str, start: int) -> bool:
    """Whether a name beginning at *start* is a parameter of a connection run."""
    return _first_character(text, start) in parameters


def _redact_assignments(text: str, *, in_prose: bool = False) -> str:
    """Mask every `name=value` in *text* whose name reads as a credential.

    A connection string writes its parameters with `&`, with `;`, or with no URI around
    them at all: `?user=reader&password=pw` in a DSN query,
    `jdbc:sqlserver://host;user=alice;password=pw;` in a JDBC authority, and a bare
    settings line stored under `dsn` all put the same pair in the same shape. Matching the
    pair rather than the delimiter reaches all three, and nothing that is not a pair moves.

    Only a credential's value is consumed. A pair under any other name is stepped over at
    its `=` and its value is scanned like the rest of the string, because a quoted or
    braced value is the one shape that can hold a delimiter: skipping over one under
    `Driver=` would let `Driver="x;Pwd=p"` carry a password out whole.

    *in_prose* narrows the rule for a field holding a sentence rather than a setting, to
    the connection runs inside it. See `_connection_parameters`.
    """
    masked: list[str] = []
    cursor = 0
    parameters = _connection_parameters(text) if in_prose else frozenset[int]()
    for name in _NAME.finditer(text):
        if name.start() < cursor:
            continue  # inside a value already consumed under a credential name
        if not _is_secret_name(unquote_plus(name.group(1))):
            continue
        value = _VALUE.match(text, name.end())
        end = value.end() if value else name.end()
        if in_prose and not _in_a_connection_run(parameters, text, name.start()):
            continue
        masked.append(text[cursor : name.start()])
        masked.append(f"{name.group(1)}={MASK}")
        cursor = end
    masked.append(text[cursor:])
    return "".join(masked)


# The check below reads a name the grammar above might not. It deliberately does not share
# `_NAME_SOURCE`: a check that inherits the parser's blind spots is not a check. Anything
# up to the `=` that is not a delimiter is a candidate name, and `unquote_plus` and the
# fold decide what it is — so an encoding nobody has met yet reaches the same vocabulary.
# `_PUBLISHED_NAME` is defined with the run scanner above, because the two have to agree
# about where a name starts.

_SEGMENT_END = re.compile(r"[;&]")
_PROSE_SEGMENT_END = re.compile(r"[;&\s]")


def _refuse_a_published_credential(text: str, *, in_prose: bool = False) -> str:
    """Mask any credential still assigned to something other than the mask.

    This is a post-condition rather than another parsing rule, and it is here because
    every leak this operator has had was the same sentence: the scanner stopped before the
    value did and published the remainder. Adding the next shape to the grammar fixes the
    shape that was reported; checking the output fixes the ones that were not.

    The rule is one sentence. If a credential name is assigned a segment that is not
    exactly the mask, the whole segment goes. A shape the grammar cannot read therefore
    fails closed, where before it failed open, and the grammar's completeness stops being
    what the guarantee rests on.

    A segment ends at `;` or `&`, and in prose also at whitespace, because a sentence ends
    a connection string where a connection string does not. It ends no earlier than the
    value does: a delimiter inside something that opens is data rather than a boundary, so
    the segment runs past the enclosure first and looks for its end after it. Reading the
    delimiter alone cut `api key={alpha;<secret>}` at the brace and published the rest.

    A name is trimmed, decoded and folded, so `api key`, ` api+key` and `API%20KEY` are one
    setting. In prose the check only looks at pairs inside a connection run — a lone
    `token=required` documents a field and is not a credential assignment to refuse.
    """
    refused: list[str] = []
    cursor = 0
    ends = _PROSE_SEGMENT_END if in_prose else _SEGMENT_END
    parameters = _connection_parameters(text) if in_prose else frozenset[int]()
    for name in _PUBLISHED_NAME.finditer(text):
        if name.start() < cursor:
            continue
        if not _is_secret_name(unquote_plus(name.group(1).strip())):
            continue
        value = _VALUE.match(text, name.end())
        stop = ends.search(text, value.end() if value else name.end())
        end = stop.start() if stop else len(text)
        if text[name.end() : end] == MASK:
            continue
        if in_prose and not _in_a_connection_run(parameters, text, name.start()):
            continue
        refused.append(text[cursor : name.start()])
        refused.append(f"{name.group(1)}={MASK}")
        cursor = end
    refused.append(text[cursor:])
    return "".join(refused)


def _redact_uri(uri: str) -> str:
    """Mask the userinfo and the credential-bearing parameters of one URI.

    A DSN carries its secret in either half — `postgresql://user:pw@host/db` and
    `postgresql://host/db?password=pw` are the same connection written two ways — so the
    URI is taken apart by its own grammar rather than matched as a shape. Parameters are
    masked in the query, in the authority and in the path, because a JDBC URL keeps them
    in the last two. Everything that is not masked is returned exactly as it arrived.
    """
    try:
        parts = urlsplit(uri)
    except ValueError:
        # `http://[::1` matches the URI shape and `urlsplit` rejects it. Redaction is a
        # safety transform over whatever a registrar stored, so a parse it cannot do falls
        # back to the shape rule it replaced rather than raising: the caller is a search
        # result, and an exception here would lose the record instead of the credential.
        return _USERINFO.sub(lambda match: f"{match.group(1)}{MASK}{match.group(3)}", uri)

    netloc = parts.netloc
    if "@" in netloc:
        userinfo, _, host = netloc.rpartition("@")
        netloc = f"{MASK}:{MASK}@{host}" if ":" in userinfo else f"{MASK}@{host}"
    netloc = _redact_assignments(netloc)
    path = _redact_assignments(parts.path)
    query = _redact_assignments(parts.query)

    if (netloc, path, query) == (parts.netloc, parts.path, parts.query):
        return uri
    return urlunsplit((parts.scheme, netloc, path, query, parts.fragment))


def _redact_string(text: str, *, in_prose: bool = False) -> str:
    """Redact one published string. Nothing it is given makes it raise.

    The assignment pass runs over the whole string first, because it is the only one that
    reads a value as the thing that closes it: `_URI` matches a URI by shape and a shape
    has to stop somewhere, so a quoted or braced value containing a space or a quote ends
    the match in the middle of the credential. Masking the pair before the URI is found
    means the URI pass never sees a half of one.

    The URI pass then takes what is left apart by its own grammar, which is what reaches a
    credential written as `//user:pw@` rather than as a pair. It runs on a prose field on
    the same terms as on any other, because a URI is a connection however it is written.

    The post-condition runs last and checks the result rather than the input. See
    `_refuse_a_published_credential`.
    """
    text = _redact_assignments(text, in_prose=in_prose)
    try:
        text = _URI.sub(lambda match: _redact_uri(match.group(0)), text)
    except Exception:
        # Totality is the point: a malformed URI in one field of one record must not turn
        # a search that should return that record into an empty result. The assignment
        # pass above has already run on the unparsed text.
        pass
    return _refuse_a_published_credential(text, in_prose=in_prose)


def _redact(value: Any, *, in_prose: bool = False) -> Any:
    """Copy *value* with secret-shaped entries masked, leaving everything else alone."""
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in cast("dict[str, Any]", value).items():
            name = str(key)
            # Decoded before it is matched, exactly as the two string parsers decode a name
            # they find in a connection string. A stored settings key can arrive
            # percent-encoded from whatever wrote it, and `api%5Fkey` folds to `api_5_fkey`
            # undecoded, which matches nothing and publishes the value.
            if _is_secret_name(unquote_plus(name)):
                redacted[name] = MASK
            else:
                redacted[name] = _redact(item, in_prose=in_prose)
        return redacted
    if isinstance(value, list):
        return [_redact(item, in_prose=in_prose) for item in cast("list[Any]", value)]
    if isinstance(value, str):
        return _redact_string(value, in_prose=in_prose)
    return value


def _transform_result(
    result: dict[str, Any],
    concept_type: str,
    registry: RegistrySeam,
    include_metadata: bool,
) -> dict[str, Any]:
    """Transform a search result into the expected format."""
    transformed_result: dict[str, Any] = {
        "type": concept_type,
        "name": result["name"],
        "id": result["id"],
        "scope": result["scope"],
    }
    if "score" in result:
        transformed_result["score"] = float(result["score"])

    full_record = registry.get_record(result["name"], concept_type, result["scope"])
    if full_record:
        # A description is prose a registrar wrote for a person, and nothing stops that
        # person writing a connection string into it: a credential there reaches whoever
        # can call this operator exactly as one in `properties` does. It goes through the
        # same redaction, narrowed to what reads as a connection rather than as a
        # sentence — a URI, and a parameter in a run of them. A lone `name=value` in prose
        # documents a field rather than authenticating to one, and is left alone.
        transformed_result["description"] = _redact(
            full_record.get("description", ""), in_prose=True
        )
        transformed_result["properties"] = _redact(full_record.get("properties", {}))
        if include_metadata:
            transformed_result["metadata"] = _redact(full_record.get("metadata", {}))
    else:
        transformed_result["description"] = ""
        transformed_result["properties"] = {}

    return transformed_result


class DataDiscoverOperator(Operator):
    """Discover registry records through hierarchical or regular search."""

    # Faithful to Blue source's data_discover operator: any search failure is logged
    # and swallowed to [[]] (by upstream design); scope=None (the default) is passed
    # through as None regardless of source/database/collection; the threshold keeps
    # score <= threshold (lower = better); progressive pagination walks pages until
    # a score exceeds the threshold. The explainer reports "within scope 'None'"
    # for the default scope — upstream-identical.

    name: ClassVar[str] = "data_discover"
    description: ClassVar[str] = "Discovers data sources using the data registry"
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "search_query": AttributeSpec(
            type="str",
            description="Text to search for in source names and descriptions",
            required=True,
            default="",
        ),
        "approximate": AttributeSpec(
            type="bool",
            description="Whether to use approximate (vector) search",
            required=True,
            default=True,
        ),
        "hybrid": AttributeSpec(
            type="bool", description="Whether to use hybrid search (text + vector)", default=False
        ),
        "limit": AttributeSpec(
            type="int", description="Max number of results to return (-1, unlimited)", default=-1
        ),
        "page": AttributeSpec(type="int", description="Page number for pagination", default=0),
        "page_size": AttributeSpec(
            type="int",
            description="Number of results per page (default: 10, max: 100)",
            default=10,
        ),
        "include_metadata": AttributeSpec(
            type="bool",
            description=(
                "Whether to include metadata in results (description and properties "
                "always included)"
            ),
            default=False,
        ),
        "threshold": AttributeSpec(
            type="float",
            description=(
                "Similarity threshold for filtering results (0.0-1.0, lower = more "
                "similar, only applies to approximate/hybrid search)"
            ),
            default=0.5,
        ),
        "progressive_pagination": AttributeSpec(
            type="bool",
            description=(
                "Whether to use progressive pagination for approximate/hybrid search "
                "(searches all pages until threshold exceeded)"
            ),
            default=False,
        ),
        "concept_type": AttributeSpec(
            type="str",
            description=(
                "Record type to search for (e.g., 'source', 'database', 'collection', "
                "'entity', 'attribute', 'relation')"
            ),
            default="source",
        ),
        "use_hierarchical_search": AttributeSpec(
            type="bool",
            description="Whether to use hierarchical search or regular search",
            default=True,
        ),
        "scope": AttributeSpec(
            type="str",
            description=(
                "Base search scope. When omitted, source, database, and collection do not "
                "construct one"
            ),
            default=None,
            materialize_default=False,
        ),
        "source": AttributeSpec(
            type="str",
            description=(
                "Source component. Refines an explicit scope only; it does not construct one "
                "when scope is omitted"
            ),
            default=None,
            materialize_default=False,
        ),
        "database": AttributeSpec(
            type="str",
            description=(
                "Database component; requires source. Refines an explicit scope only; it does not "
                "construct one when scope is omitted"
            ),
            default=None,
            materialize_default=False,
        ),
        "collection": AttributeSpec(
            type="str",
            description=(
                "Collection component; requires source and database. Refines an explicit scope "
                "only; it does not construct one when scope is omitted"
            ),
            default=None,
            materialize_default=False,
        ),
        "auto_construct_scope": AttributeSpec(
            type="bool",
            description=(
                "Rebuild an explicit scope from source, database, and collection when true; "
                "use that scope unchanged when false. Has no effect when scope is omitted"
            ),
            default=True,
        ),
        "filter_names": AttributeSpec(
            type="list",
            description="Filter out results with matching names in the filter list",
            default=[],
        ),
    }

    DEFAULT_PROPERTIES: ClassVar[dict[str, Any]] = {}

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        try:
            return self._execute(input_data, attributes, properties).output_data
        except _DataDiscoverFailure:
            return [[]]

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        search_query = cast(str, attributes.get("search_query", ""))
        approximate = attributes.get("approximate", True)
        hybrid = attributes.get("hybrid", False)
        limit = cast(int, attributes.get("limit", -1))
        page = cast(int, attributes.get("page", 0))
        page_size = cast(int, attributes.get("page_size", 10))
        include_metadata = cast(bool, attributes.get("include_metadata", False))
        threshold = cast(float, attributes.get("threshold", 0.5))
        progressive_pagination = attributes.get("progressive_pagination", False)
        concept_type = cast(str, attributes.get("concept_type", "source"))
        use_hierarchical_search = attributes.get("use_hierarchical_search", True)
        scope = cast("str | None", attributes.get("scope", None))
        source = cast("str | None", attributes.get("source", None))
        database = cast("str | None", attributes.get("database", None))
        collection = cast("str | None", attributes.get("collection", None))
        auto_construct_scope = cast(bool, attributes.get("auto_construct_scope", True))
        filter_names = cast("list[str]", attributes.get("filter_names", []))

        search_scope = _construct_scope(
            scope, source, database, collection, concept_type, auto_construct_scope
        )

        registry = resolve_registry(properties)
        if not registry:
            logger.error("Error: Data registry not found")
            raise _DataDiscoverFailure

        results: list[dict[str, Any]] = []

        try:
            use_simple_pagination = (not approximate and not hybrid) or not progressive_pagination

            if use_simple_pagination:
                if use_hierarchical_search:
                    search_results = registry.search_records_hierarchical(
                        search_query,
                        type=concept_type,
                        scope=search_scope,
                        page=page,
                        page_size=page_size,
                    )
                else:
                    search_results = registry.search_records(
                        search_query,
                        type=concept_type,
                        scope=search_scope,
                        approximate=cast(bool, approximate),
                        hybrid=cast(bool, hybrid),
                        page=page,
                        page_size=page_size,
                    )

                for result in search_results:
                    if result["name"] in filter_names:
                        continue

                    transformed_result = _transform_result(
                        result, concept_type, registry, include_metadata
                    )

                    if (approximate or hybrid) and "score" in result:
                        score = float(result["score"])
                        if score <= threshold:
                            results.append(transformed_result)
                    else:
                        results.append(transformed_result)
            else:
                current_page = page

                while True:
                    if use_hierarchical_search:
                        search_results = registry.search_records_hierarchical(
                            search_query,
                            type=concept_type,
                            scope=search_scope,
                            page=current_page,
                            page_size=page_size,
                        )
                    else:
                        search_results = registry.search_records(
                            search_query,
                            type=concept_type,
                            scope=search_scope,
                            approximate=cast(bool, approximate),
                            hybrid=cast(bool, hybrid),
                            page=current_page,
                            page_size=page_size,
                        )

                    if len(search_results) == 0:
                        break

                    for result in search_results:
                        if result["name"] in filter_names:
                            continue

                        score = float(result["score"])
                        if score <= threshold:
                            transformed_result = _transform_result(
                                result, concept_type, registry, include_metadata
                            )
                            results.append(transformed_result)
                        else:
                            break

                    if len(search_results) > 0:
                        last_score = float(search_results[-1]["score"])
                        if last_score > threshold:
                            break

                    current_page += 1

        except Exception as error:
            # Upstream design: any search failure is logged and swallowed to [[]].
            logger.error(traceback.format_exc())
            raise _DataDiscoverFailure from error

        if limit >= 0:
            return FunctionResult([results[:limit]], {})
        else:
            return FunctionResult([results], {})

    def validate(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> bool:
        result = self._validate_input(input_data, attributes, properties)
        return type(result) is ValidationResult and result.ok is True

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        suggestion = "supply a valid search query, pagination, threshold, scope, and concept type"
        # Upstream wraps its base-validator call defensively; kept, though the base
        # gate is total.
        try:
            if not super().validate(input_data, attributes, properties):
                return ValidationResult(False, suggestion)
        except Exception:
            return ValidationResult(False, suggestion)

        search_query = cast(str, attributes.get("search_query", ""))
        page = cast(int, attributes.get("page", 0))
        page_size = cast(int, attributes.get("page_size", 10))
        threshold = cast(float, attributes.get("threshold", 0.5))
        source = attributes.get("source", None)
        database = attributes.get("database", None)
        collection = attributes.get("collection", None)

        if not search_query or not search_query.strip():
            return ValidationResult(False, suggestion)
        if page < 0 or page_size <= 0:
            return ValidationResult(False, suggestion)
        if threshold < 0 or threshold > 1:
            return ValidationResult(False, suggestion)

        if database and not source:
            return ValidationResult(False, suggestion)
        if collection and (not source or not database):
            return ValidationResult(False, suggestion)

        concept_type = attributes.get("concept_type", "source")
        valid_concept_types = [
            "source",
            "database",
            "collection",
            "entity",
            "relation",
            "attribute",
        ]
        if concept_type not in valid_concept_types:
            return ValidationResult(False, suggestion)

        return ValidationResult(True, None)

    def explain(
        self,
        output: DataBundle,
        input_data: DataBundle,
        attributes: Attributes,
    ) -> dict[str, Any]:
        concept_type = attributes.get("concept_type", "source")
        use_hierarchical = attributes.get("use_hierarchical_search", True)
        search_method = "hierarchical" if use_hierarchical else "regular"

        scope = cast("str | None", attributes.get("scope", None))
        source = cast("str | None", attributes.get("source", None))
        database = cast("str | None", attributes.get("database", None))
        collection = cast("str | None", attributes.get("collection", None))
        auto_construct_scope = cast(bool, attributes.get("auto_construct_scope", True))
        search_scope = _construct_scope(
            scope, source, database, collection, cast(str, concept_type), auto_construct_scope
        )

        # Upstream compares against "/" only, so the default None scope renders as
        # "within scope 'None'" — kept.
        scope_info = f" within scope '{search_scope}'" if search_scope != "/" else ""

        return {
            "output": output,
            "input_data": input_data,
            "attributes": attributes,
            "explanation": (
                f"Data discover operator searched for {concept_type} entities using "
                f"{search_method} search with query '{attributes.get('search_query', '')}'"
                f"{scope_info} and returned "
                f"{len(output[0]) if output and len(output) > 0 else 0} results."
            ),
        }


DISCOVERY = DiscoverySpec(
    when_to_invoke=(
        "Use when data sources, databases, collections, or entities must be found through "
        "registry search."
    ),
    tags=(
        "domain-plan",
        "flow-head",
        "accepts-none",
        "produces-metadata",
        "capability-discovery",
        "capability-metadata-search",
        "requires-data-registry",
    ),
)
