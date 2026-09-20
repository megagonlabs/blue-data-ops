"""What a discovery result may carry out of the registry.

A registered source keeps its connection settings in the record's ``properties``, and a
connection dict is where blue-data's SQL, graph, Redis and Mongo sources keep a password.
``data_discover`` publishes that map to whoever called it, so these tests hold the line
between the half of a record that answers the search and the half that authenticates to it.

The sentinel below is a literal written here to be recognisable in an assertion. Nothing in
this file reads a credential or sets one.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast

import pytest

blue_data = pytest.importorskip("blue_data")

from blue_data_ops.data import RegistrySeam  # noqa: E402
from blue_data_ops.operators.data_discover_operator import (  # noqa: E402
    MASK,
    DataDiscoverOperator,
)
from tests.doubles.data import RegistrySeamDouble  # noqa: E402

SECRET = "sentinel-value-no-caller-may-see"

INPUT: list[list[dict[str, Any]]] = [[]]

ATTRS: dict[str, Any] = {"search_query": "jobs", "approximate": True, "include_metadata": True}

RECORD: dict[str, Any] = {
    "name": "jobs_db",
    "description": f"job postings. connect with postgresql://reader:{SECRET}@db.internal/jobs",
    "properties": {
        "kind": "sql",
        "connection": {
            "protocol": "sql/mysql",
            "host": "db.internal",
            "port": 3306,
            "database": "jobs",
            "user": SECRET,
            "password": SECRET,
        },
        "uri": f"mongodb://admin:{SECRET}@db.internal:27017",
        "owner_token": SECRET,
        "api_key": SECRET,
        "api-key": SECRET,
        "api.key": SECRET,
        "apiKey": SECRET,
        "client-secret": SECRET,
        "clientSecret": SECRET,
        "Access Token": SECRET,
        "PASS PHRASE": SECRET,
        "dsn": f"postgresql://reports.internal/jobs?user=reader&password={SECRET}",
        "jdbc": f"jdbc:sqlserver://db.internal;user=alice;password={SECRET};",
        "semicolon_dsn": f"postgresql://db/x?x=1;password={SECRET}",
        "encoded_dsn": f"postgresql://reports.internal/jobs?api%5Fkey={SECRET}&sslmode=require",
        "odbc": f"Driver={{ODBC Driver 18}};Server=db.internal;UID=alice;Pwd={{p {SECRET}}}",
        "jdbc_quoted": f'jdbc:sqlserver://db.internal;password="p {SECRET}";encrypt=true',
        "form_encoded_dsn": f"postgresql://db/x?api+key={SECRET}&ssl=1",
        "odbc_escaped": f"Driver=X;Pwd={{alpha}}}} {SECRET}}};Server=db",
        "jdbc_escaped": f'password="alpha"" {SECRET}"',
        "shielded": f'Driver="x;Pwd={SECRET}"',
        "spaced_name": f"Driver=X;api key={SECRET};Server=db",
        "spaced_delimiters": f"Driver=X; Password={SECRET}; Server=db",
        "malformed_uri": "http://[::1",
        "primary_keys": ["id", "posting_id"],
        "foreignKeys": ["dept_id"],
    },
    "metadata": {"owner": "ops", "credentials": {"access_key": SECRET}, "accessToken": SECRET},
}
"""One source record holding the secret in every shape the registry can store it in.

Nothing constrains how a registrar spells a key or writes a connection string, so the
record carries the same setting under a separator, a dot, a space and a camel hump, and
carries a credential in both halves of a URI, behind both parameter delimiters, and in a
URI the parser cannot read at all. Two of those spellings put a space where a name or a
delimiter is: OLE DB allows one inside a keyword, and Microsoft's own documented format
writes one after every `;`.
"""


class _Seam(RegistrySeamDouble, RegistrySeam):
    """The recording double, typed as a RegistrySeam so injection resolves it."""


@pytest.fixture
def seam() -> _Seam:
    recording = _Seam()
    recording.search_pages = {
        0: [
            {
                "name": "jobs_db",
                "type": "source",
                "scope": "/",
                "id": "/source/jobs_db",
                "score": 0.1,
            }
        ]
    }
    recording.records[("jobs_db", "source", "/")] = RECORD
    return recording


def _discover(seam: _Seam, **overrides: Any) -> dict[str, Any]:
    output = DataDiscoverOperator().apply(INPUT, {**ATTRS, **overrides}, {"data_registry": seam})
    return output[0][0]


# --- the secret half -----------------------------------------------------------------
def test_a_stored_connection_password_does_not_come_back(seam: _Seam) -> None:
    connection = _discover(seam)["properties"]["connection"]
    assert connection["password"] == MASK
    assert connection["user"] == MASK


def test_a_credentialed_connection_uri_keeps_its_host_and_loses_its_pair(seam: _Seam) -> None:
    assert _discover(seam)["properties"]["uri"] == f"mongodb://{MASK}:{MASK}@db.internal:27017"


def test_a_credential_in_a_uri_query_parameter_is_masked(seam: _Seam) -> None:
    """A DSN carries the same pair in its query half, where no userinfo rule reaches it."""
    assert (
        _discover(seam)["properties"]["dsn"]
        == f"postgresql://reports.internal/jobs?user={MASK}&password={MASK}"
    )


@pytest.mark.parametrize(
    "spelling",
    [
        "api-key",
        "api.key",
        "apiKey",
        "client-secret",
        "clientSecret",
        "Access Token",
        "PASS PHRASE",
    ],
)
def test_a_credential_name_is_masked_however_it_is_spelled(seam: _Seam, spelling: str) -> None:
    """Nothing makes a registrar write `api_key`. A rule that reads only that spelling
    publishes the same credential under any of the others."""
    assert _discover(seam)["properties"][spelling] == MASK


def test_a_jdbc_connection_string_loses_its_credential(seam: _Seam) -> None:
    """The SQL Server shape: parameters in the authority, delimited with semicolons.

    Neither half of the old rule reached it. There is no userinfo, and a query parser that
    splits on `&` sees one parameter named `db.internal;user` and stops there.
    """
    assert (
        _discover(seam)["properties"]["jdbc"]
        == f"jdbc:sqlserver://db.internal;user={MASK};password={MASK};"
    )


def test_a_semicolon_delimited_query_loses_its_credential(seam: _Seam) -> None:
    """The same delimiter in the query half, which some drivers accept alongside `&`."""
    assert (
        _discover(seam)["properties"]["semicolon_dsn"] == f"postgresql://db/x?x=1;password={MASK}"
    )


def test_a_percent_encoded_parameter_name_is_still_a_credential_name(seam: _Seam) -> None:
    """`api%5Fkey` and `api_key` are the same parameter, and a query may write either.

    The name is decoded before it is classified. Decoding it afterwards, which is what the
    rule used to do, never reached this one: `%` stopped the name match short and the pair
    went out whole.
    """
    assert (
        _discover(seam)["properties"]["encoded_dsn"]
        == f"postgresql://reports.internal/jobs?api%5Fkey={MASK}&sslmode=require"
    )


def test_an_odbc_braced_value_loses_all_of_itself(seam: _Seam) -> None:
    """ODBC braces a value that contains a space, and brackets the account name as `UID`.

    A value read to the first space masked one word and published the rest of the password
    along with everything after it on the line.
    """
    assert (
        _discover(seam)["properties"]["odbc"]
        == f"Driver={{ODBC Driver 18}};Server=db.internal;UID={MASK};Pwd={MASK}"
    )


def test_a_jdbc_quoted_value_loses_all_of_itself(seam: _Seam) -> None:
    """JDBC quotes what ODBC braces, and the same half-masking followed."""
    assert (
        _discover(seam)["properties"]["jdbc_quoted"]
        == f"jdbc:sqlserver://db.internal;password={MASK};encrypt=true"
    )


def test_a_form_encoded_parameter_name_is_still_a_credential_name(seam: _Seam) -> None:
    """`+` is the form-encoded spelling of a space, so `api+key` is `api key` is `api_key`.

    Percent-encoding was already decoded before the name was classified; `+` was excluded
    from the name altogether, so the pair never matched and the parameter went out whole.
    """
    assert (
        _discover(seam)["properties"]["form_encoded_dsn"]
        == f"postgresql://db/x?api+key={MASK}&ssl=1"
    )


def test_a_doubled_brace_does_not_end_an_odbc_value(seam: _Seam) -> None:
    """ODBC escapes a brace inside a braced value by doubling it.

    Reading `}}` as the closer ended the value in the middle of the password and published
    everything after it, which is the whole tail of the connection string.
    """
    assert _discover(seam)["properties"]["odbc_escaped"] == f"Driver=X;Pwd={MASK};Server=db"


def test_a_doubled_quote_does_not_end_a_jdbc_value(seam: _Seam) -> None:
    """JDBC escapes a quote the same way, and the same tail was published."""
    assert _discover(seam)["properties"]["jdbc_escaped"] == f"password={MASK}"


def test_a_spaced_credential_name_is_still_a_credential_name(seam: _Seam) -> None:
    """OLE DB allows a space inside a keyword, so `api key` is the setting `api_key`.

    Folding has read that spelling since the census was written, and the check that reads
    the published result did not: it stopped a name at whitespace, so the complete name it
    classified was `key`, which is a column and not a credential. It now reads the whole
    name and trims, decodes and folds it.
    """
    assert _discover(seam)["properties"]["spaced_name"] == f"Driver=X;api key={MASK};Server=db"


def test_a_value_that_is_not_a_credential_does_not_shield_one(seam: _Seam) -> None:
    """A quoted value is the one shape that can hold a delimiter, so it can hold a pair.

    `Driver=` is not a credential name and its value is not masked, but nothing says the
    text inside it is safe: a rule that stepped over the whole quoted value published the
    password written inside it. Only a credential's value is consumed; everything else is
    scanned through.
    """
    assert _discover(seam)["properties"]["shielded"] == f'Driver="x;Pwd={MASK}'


@pytest.mark.parametrize(
    "stored, expected",
    [
        # An opener with no closer runs to the end of the line. A value whose quoting is
        # broken cannot be read reliably to any earlier point, so the tail goes with it —
        # `Server=db` is a host, and losing it costs less than publishing the rest of a
        # password.
        ("Driver=X;Pwd={p q;Server=db", f"Driver=X;Pwd={MASK}"),
        ('Driver=X;Pwd="p q;Server=db', f"Driver=X;Pwd={MASK}"),
        ("Driver=X;Pwd='p q;Server=db", f"Driver=X;Pwd={MASK}"),
        # A braced value that is not a credential is returned byte for byte.
        ("Driver={ODBC Driver 18};Server=db", "Driver={ODBC Driver 18};Server=db"),
        # Both delimiters, both spellings of the account name. `p q` is one value with a
        # space in it as far as anyone can tell, so all of it goes.
        ("uid=alice&pwd=p q", f"uid={MASK}&pwd={MASK}"),
    ],
)
def test_a_connection_string_value_ends_where_it_ends(
    seam: _Seam, stored: str, expected: str
) -> None:
    seam.records[("jobs_db", "source", "/")] = {
        **RECORD,
        "properties": {**RECORD["properties"], "dsn": stored},
    }
    assert _discover(seam)["properties"]["dsn"] == expected


def test_a_secret_stored_beside_the_connection_is_masked_too(seam: _Seam) -> None:
    properties = _discover(seam)["properties"]
    assert properties["owner_token"] == MASK
    assert properties["api_key"] == MASK


def test_a_description_is_redacted_on_the_same_terms(seam: _Seam) -> None:
    """A widening: a description used to be published exactly as a registrar wrote it.

    It is prose meant for a person, and nothing stops that person writing a connection
    string into it. A credential there reaches whoever can call the operator exactly as one
    in `properties` does, so it goes through the same redaction as every other stored
    string rather than being the one field that does not.
    """
    description = _discover(seam)["description"]
    assert SECRET not in description
    assert description == f"job postings. connect with postgresql://{MASK}:{MASK}@db.internal/jobs"


def test_a_connection_string_in_a_description_is_redacted_too(seam: _Seam) -> None:
    """A connection does not have to be a URI to be one. The ODBC spelling reaches the same
    database and carries the same password, and a run of parameters is what says so."""
    prose = f"use Driver={{ODBC Driver 18}};Server=db;UID=sa;PWD={SECRET} to connect"
    seam.records[("jobs_db", "source", "/")] = {**RECORD, "description": prose}
    assert (
        _discover(seam)["description"]
        == f"use Driver={{ODBC Driver 18}};Server=db;UID={MASK};PWD={MASK} to connect"
    )


def test_a_connection_string_formatted_with_spaces_loses_its_credential(seam: _Seam) -> None:
    """Microsoft's documented basic format writes a space after every `;`.

    A description used to be scanned for parameters that touched their delimiter, so the
    formatted spelling of the same connection string published its password. The rule now
    reads the run: `Driver` and `Server` say the run reaches a database, and the pair
    between them is a credential of that connection however it is spaced.
    """
    prose = f"connect with Driver=X; Password={SECRET}; Server=db"
    seam.records[("jobs_db", "source", "/")] = {**RECORD, "description": prose}
    assert _discover(seam)["description"] == f"connect with Driver=X; Password={MASK}; Server=db"


def test_a_description_documenting_a_schema_keeps_its_values(seam: _Seam) -> None:
    """Prose writes `name=value` for reasons other than connecting to something.

    `token=required` documents a field of a schema, and a caller that loses it loses the
    answer it came to discovery for. It is also punctuated exactly like the connection
    string in the test above — two pairs joined by `; ` — so nothing about the spacing can
    separate them. What separates them is what the run names: a connection says where it
    connects as well as who it connects as, and this one names neither. `schema` is
    deliberately not a connection keyword, because `OAuth schema: token` folds to
    `oauth_schema_token` and would make this sentence a connection string.
    """
    prose = "OAuth schema: token=required; authorization=optional (neither is a credential)."
    seam.records[("jobs_db", "source", "/")] = {**RECORD, "description": prose}
    assert _discover(seam)["description"] == prose


def test_a_lone_assignment_in_a_description_is_left_alone(seam: _Seam) -> None:
    """What narrowing the rule costs, pinned rather than left to be discovered.

    A single assignment is never a connection run — a connection names what it reaches as
    well as who reaches it, and one pair cannot do both — so a credential written into a
    sentence that way is returned as written. A description holding an actual connection —
    a URI, or a run of parameters that names one — is still redacted, and those are the
    shapes a pasted connection has.
    """
    prose = "the reader account is password=ask-the-ops-team"
    seam.records[("jobs_db", "source", "/")] = {**RECORD, "description": prose}
    assert _discover(seam)["description"] == prose


def test_a_description_carrying_no_connection_is_returned_as_written(seam: _Seam) -> None:
    """Redaction is a safety transform, not an edit: prose with no connection in it comes
    back byte for byte. Prose holding one does not, and neither does a URI whose query
    happens to name an account."""
    prose = "Job postings, refreshed nightly at 02:00 UTC. Owner: the ops team (x=1 rows)."
    seam.records[("jobs_db", "source", "/")] = {**RECORD, "description": prose}
    assert _discover(seam)["description"] == prose


def test_metadata_is_redacted_on_the_same_terms(seam: _Seam) -> None:
    metadata = _discover(seam)["metadata"]
    assert metadata["credentials"] == MASK
    assert metadata["accessToken"] == MASK


def test_the_registry_record_itself_is_not_edited(seam: _Seam) -> None:
    """Redaction happens on the way out; the registry keeps what it was given."""
    _discover(seam)
    assert RECORD["properties"]["connection"]["password"] == SECRET


# --- the useful half -----------------------------------------------------------------
def test_the_rest_of_a_connection_still_answers_the_search(seam: _Seam) -> None:
    connection = _discover(seam)["properties"]["connection"]
    assert connection["protocol"] == "sql/mysql"
    assert connection["host"] == "db.internal"
    assert connection["port"] == 3306
    assert connection["database"] == "jobs"


def test_a_column_named_for_a_key_is_not_a_credential(seam: _Seam) -> None:
    """`misc` carries primary and foreign keys, so a bare `key` is not a secret shape.

    Folding a name before matching it does not change that: `foreignKeys` reads as
    `foreign_keys` and stays in the clear, the same as `primary_keys` always has.
    """
    properties = _discover(seam)["properties"]
    assert properties["primary_keys"] == ["id", "posting_id"]
    assert properties["foreignKeys"] == ["dept_id"]
    assert properties["kind"] == "sql"


# --- the whole result ----------------------------------------------------------------
# The tests above name the fields, and a list of fields is only ever right about the
# surface it was written against. This one enumerates the surface instead: every string a
# result publishes has to be masked or to be named below with a reason, so a field added
# to a record later lands on one side of the line or fails here.


def published_strings(node: object, path: str = "") -> Iterator[tuple[str, str]]:
    """Every string in *node*, each with a path naming its field rather than its value."""
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, list):
        for item in cast("list[object]", node):
            yield from published_strings(item, f"{path}[]")
    elif isinstance(node, dict):
        for key, value in cast("dict[str, object]", node).items():
            yield f"{path}{{}}", key
            yield from published_strings(value, f"{path}.{key}" if path else key)


UNMASKED: dict[str, str] = {
    "data_discover{}": "the result's own field names, written as literals in the operator.",
    "data_discover.type": "the concept type the caller asked to search for.",
    "data_discover.name": "the record's registered name, which is the answer to the search.",
    "data_discover.id": "the registry path to the record, built from names already published.",
    "data_discover.scope": "the registry scope the search ran in, supplied by the caller.",
    "data_discover.properties{}": "property names. A name is the shape of the record; the "
    "secret is the value under it, and `api_key` here names a masked one.",
    "data_discover.properties.kind": "how the source stores its data.",
    "data_discover.properties.connection{}": "connection field names, on the same terms.",
    "data_discover.properties.connection.protocol": "which driver reaches the source.",
    "data_discover.properties.connection.host": "where the source is, which is not how to "
    "get into it.",
    "data_discover.properties.connection.database": "which database on that host holds the "
    "records.",
    "data_discover.properties.malformed_uri": "text that looks like a URI and is not one. "
    "It carries no credential, and redaction leaves what it cannot parse alone rather than "
    "failing over it.",
    "data_discover.properties.primary_keys[]": "column names. A key here is a column.",
    "data_discover.properties.foreignKeys[]": "column names again, spelled the other way. "
    "Folding a name does not turn a column into a credential.",
    "data_discover.metadata{}": "metadata field names, on the same terms as properties.",
    "data_discover.metadata.owner": "who registered the record.",
}
"""Every string a result publishes in the clear, and why each one has to stay.

Field names are the shape of the record, and a caller that cannot read the shape cannot use
what it discovered. The rest names or locates the source: a host and a port say where a
service is, which is not the same as what gets anyone into it.
"""


def test_every_string_a_result_publishes_is_masked_or_has_a_written_reason(seam: _Seam) -> None:
    published = published_strings(_discover(seam), "data_discover")
    open_paths = {path for path, value in published if MASK not in value}
    # Equality both ways: an unlisted path is a string published in the clear that nobody
    # decided about, and a listed path that no longer appears is a reason for a rule that
    # is no longer there.
    assert open_paths == set(UNMASKED)


# --- the post-condition, over shapes nobody wrote down -------------------------------
# The tests above name a shape each. A list of shapes is only ever right about the shapes
# somebody thought of, and every leak this operator has had was a shape nobody had. So the
# next one is generated rather than named: the property is that a credential written under
# a credential name never comes back, whatever syntax it is wrapped in.


CREDENTIAL_NAMES = [
    "password",
    "passwd",
    "Pwd",
    "PWD",
    "passphrase",
    "secret",
    "api_key",
    "api-key",
    "api.key",
    "apiKey",
    "access_key",
    "private-key",
    "client-secret",
    "clientSecret",
    "token",
    "auth",
    "authorization",
    "credentials",
    "uid",
    "UID",
    "user",
    "username",
    "login",
    # the same names as a query writes them
    "api%5Fkey",
    "pass%77ord",
    "client%2Dsecret",
    "api+key",
    "access+key",
    # the same names with the space left in, which is how OLE DB writes a keyword
    "api key",
    "API KEY",
    "Access Token",
    "PASS PHRASE",
    "client secret",
    "private key",
    "api%20key",
]
"""Every spelling of a credential name: separators, camel humps, encodings and spaces.

A space is the dimension this corpus did not generate for four revisions, and a raw
`api key=` inside a string was published the whole time — the corpus passed because it had
never written one. A space is ordinary rather than exotic: OLE DB allows one inside a
keyword, the guide has listed `PASS PHRASE` as a covered spelling since the census was
written, and `%20` and `+` are how a query encodes the same character.
"""

UNDELIMITED_BODIES = [
    SECRET,
    f"{SECRET}=x",
    f"alpha}}{SECRET}",
    f'alpha"{SECRET}',
]
"""A password an unquoted value can hold: no character that ends one."""

DELIMITED_BODIES = [f"alpha {SECRET}", f"alpha;{SECRET}", f"alpha&{SECRET}"]
"""A password only an enclosed value can hold.

An unquoted `;` or `&` or space ends a value — that is why ODBC braces one and JDBC quotes
one — so a credential written after an unquoted delimiter is a parameter of its own and
not part of the password. These bodies are generated only inside something that opens.
"""


def enclosures(body: str) -> list[str]:
    """One value, written the way each connection-string syntax encloses one."""
    return [
        "{" + body + "}",
        '"' + body + '"',
        "'" + body + "'",
        "{" + body,  # an opener with no closer
        '"' + body,
        "'" + body,
        "{a}}" + body + "}",  # ODBC escapes a brace by doubling it
        '"a""' + body + '"',  # JDBC escapes a quote the same way
        "{a}}" + body,  # and neither has to close
        '"a""' + body,
    ]


def wrappings(body: str) -> list[str]:
    return [body, *enclosures(body)]


def contexts(pair: str) -> list[str]:
    """One pair, in each place a registrar can put one, spaced as each of them is spaced.

    The last three are the same connection strings with the whitespace Microsoft's
    documented format writes: `keyword1=value; keyword2=value`. A delimiter that a space
    separates from the name behind it is the shape the run rule used to miss.
    """
    return [
        pair,
        f"Driver=X;{pair};Server=db",
        f"postgresql://db/x?{pair}&ssl=1",
        f"jdbc:sqlserver://db.internal;{pair};encrypt=true",
        f'Driver="q";{pair}',
        f"Driver={{ODBC Driver 18}};{pair}",
        f"Driver=X; {pair}; Server=db",
        f"jdbc:sqlserver://db.internal; {pair}; encrypt=true",
        f"Driver=X ; {pair} ; Server=db",
    ]


def generated_values() -> list[str]:
    """Every value a credential can be written as, wrapped every way a syntax wraps one."""
    values = [value for body in UNDELIMITED_BODIES for value in wrappings(body)]
    values += [value for body in DELIMITED_BODIES for value in enclosures(body)]
    return values


def generated_connection_strings() -> list[str]:
    return [
        stored
        for name in CREDENTIAL_NAMES
        for value in generated_values()
        for stored in contexts(f"{name}={value}")
    ]


def test_no_generated_connection_string_publishes_its_credential(seam: _Seam) -> None:
    """The property the grammar has been approximating for four revisions.

    A credential assigned to a credential name does not come back, in any wrapping, in any
    context, whether the wrapping closes or not. What makes this hold is not that the
    grammar reads every shape below — it does not — but that the redaction is checked
    after the fact: a value that is not exactly the mask is refused whatever produced it.
    """
    generated = generated_connection_strings()
    stored = {f"case_{index}": value for index, value in enumerate(generated)}
    seam.records[("jobs_db", "source", "/")] = {**RECORD, "properties": stored}

    published = _discover(seam)["properties"]
    leaked = sorted(key for key, value in published.items() if SECRET in value)

    assert not leaked, f"{len(leaked)} of {len(generated)} published the credential: {leaked[:5]}"


BENIGN_NAMES = [
    "Driver",
    "Data Source",
    "Initial Catalog",
    "Extended Properties",
    "Application Name",
    "Persist Security Info",
]
"""Connection-string keywords nobody masks, including the spaced ones OLE DB defines.

Reading a name across a space is what closes the `api key` leak, and the same widening is
what could swallow `Data Source` or `Persist Security Info` into something that folds to a
credential. These are generated under every wrapping and every context the corpus above
uses, and every one has to come back byte for byte.
"""


def test_the_generated_corpus_is_not_passing_by_masking_everything(seam: _Seam) -> None:
    """A guard on the guard: the same shapes under a name nobody masks come back whole."""
    benign = {
        f"case_{index}": stored
        for index, stored in enumerate(
            value
            for name in BENIGN_NAMES
            for body in ["alpha", "alpha beta", "alpha;beta"]
            for wrapped in wrappings(body)
            for value in contexts(f"{name}={wrapped}")
        )
    }
    seam.records[("jobs_db", "source", "/")] = {**RECORD, "properties": benign}

    published = _discover(seam)["properties"]
    assert published == benign


# --- the same property, in the field that holds a sentence ---------------------------
# The corpus above is stored under `properties`, where the whole rule applies. A
# description gets a narrower one, and the narrowing is where the last two leaks were: a
# connection string formatted the way Microsoft documents it, with a space after each `;`,
# was read as prose and published. So the same pairs are generated a second time inside a
# sentence, and the sentence that must survive is generated beside them.


def prose_contexts(pair: str) -> list[str]:
    """One pair pasted into a sentence, spaced the way each source spaces it."""
    return [
        f"connect with Driver=X;{pair};Server=db to reach it",
        f"connect with Driver=X; {pair}; Server=db to reach it",
        f"connect with Driver=X ; {pair} ; Server=db to reach it",
        f"see https://db.internal/x?{pair}&ssl=1 for details",
    ]


def generated_descriptions() -> list[str]:
    return [
        prose
        for name in CREDENTIAL_NAMES
        for value in generated_values()
        for prose in prose_contexts(f"{name}={value}")
    ]


def generated_schema_sentences() -> list[str]:
    """The negative control, written out in every spelling of a credential name.

    `token=required; authorization=optional` is punctuated exactly like the connection
    strings above and has to come back untouched, so the rule that separates them is
    measured against every name the vocabulary knows rather than against one.
    """
    return [
        f"OAuth schema: {name}=required; authorization=optional (neither is a credential)."
        for name in CREDENTIAL_NAMES
    ]


def _describe(seam: _Seam, descriptions: list[str]) -> list[str]:
    """One record per description, all of them answered by one `apply`."""
    names = [f"case_{index}" for index in range(len(descriptions))]
    seam.search_pages = {
        0: [
            {"name": name, "type": "source", "scope": "/", "id": f"/source/{name}", "score": 0.1}
            for name in names
        ]
    }
    for name, prose in zip(names, descriptions, strict=True):
        seam.records[(name, "source", "/")] = {
            "name": name,
            "description": prose,
            "properties": {},
            "metadata": {},
        }
    output = DataDiscoverOperator().apply(INPUT, ATTRS, {"data_registry": seam})
    return [result["description"] for result in output[0]]


def test_no_generated_description_publishes_its_credential(seam: _Seam) -> None:
    """A connection pasted into prose loses its credential however the paste is spaced."""
    generated = generated_descriptions()
    leaked = [prose for prose in _describe(seam, generated) if SECRET in prose]
    assert not leaked, f"{len(leaked)} of {len(generated)} published the credential: {leaked[:3]}"


def generated_mixed_sentences() -> list[tuple[str, str]]:
    """A connection string and a documented schema in one description, and what it becomes.

    The sharpest statement of the rule, because both halves are in one field: the pairs
    inside the connection run lose their values and the sentence after it keeps its own,
    including the `token=required` that is spelled identically to a credential.
    """
    return [
        (
            f"connect with Driver=X; {name}={SECRET}; Server=db."
            " OAuth schema: token=required; authorization=optional.",
            f"connect with Driver=X; {name}={MASK}; Server=db."
            " OAuth schema: token=required; authorization=optional.",
        )
        for name in CREDENTIAL_NAMES
    ]


def test_a_sentence_after_a_connection_string_keeps_its_documented_values(
    seam: _Seam,
) -> None:
    """A name reads back across whatever is in front of it, and that is a sentence here.

    The complete name before `required` is `db. OAuth schema: token`, which folds to
    something the census reads as a credential and which starts inside the connection run
    and ends outside it. The pair has to be wholly inside a run to be masked, or a
    connection string pasted above a documented schema takes the schema with it.
    """
    stored = [prose for prose, _ in generated_mixed_sentences()]
    assert _describe(seam, stored) == [expected for _, expected in generated_mixed_sentences()]


def test_no_generated_schema_sentence_loses_a_documented_value(seam: _Seam) -> None:
    """The guard on that guard: a documented schema is returned byte for byte.

    This is the half that makes the rule worth having. The same punctuation has to leak
    nothing in a connection string and lose nothing in a sentence, and a rule that cannot
    separate them is either publishing credentials or destroying the answer a caller came
    to discovery for.
    """
    sentences = generated_schema_sentences()
    assert _describe(seam, sentences) == sentences


# --- redaction is total --------------------------------------------------------------
# Redaction runs over whatever a registrar stored, and a safety transform that can fail is
# a denial of service on the thing it protects: `data_discover` swallows any exception from
# its search to `[[]]`, so one unparseable string in one field of one record used to turn a
# search that should return that record into an empty result.

MALFORMED_URIS = [
    "http://[::1",
    "http://[::1]:port/db",
    "https://[",
    f"http://admin:{SECRET}@[::1",
    f"postgresql://[::1;password={SECRET}",
]


@pytest.mark.parametrize("stored", MALFORMED_URIS)
def test_a_malformed_uri_does_not_take_the_record_with_it(seam: _Seam, stored: str) -> None:
    seam.records[("jobs_db", "source", "/")] = {
        **RECORD,
        "properties": {**RECORD["properties"], "uri": stored},
    }
    result = _discover(seam)
    assert result["name"] == "jobs_db"  # the record came back, which is the whole point
    assert SECRET not in result["properties"]["uri"]


def test_a_malformed_uri_is_the_only_thing_the_fallback_gives_up_on(seam: _Seam) -> None:
    """The fallback is conservative, not destructive: text that carries no credential is
    returned as it was stored, and the rest of the record is redacted as usual."""
    seam.records[("jobs_db", "source", "/")] = {
        **RECORD,
        "properties": {**RECORD["properties"], "uri": "http://[::1"},
    }
    properties = _discover(seam)["properties"]
    assert properties["uri"] == "http://[::1"
    assert properties["connection"]["password"] == MASK


# A stored settings key arrives however whatever registered the source wrote it, and a
# writer that percent-encodes its map keys is not a strange one. The two string parsers
# have always decoded a name before matching it; the map did not, so `api%5Fkey` folded to
# `api_5_fkey`, matched nothing, and published its value.
ENCODED_CREDENTIAL_NAMES = [
    "api%5Fkey",
    "api+key",
    "pass%20phrase",
    "client%2Dsecret",
    "PASS%5FPHRASE",
]


@pytest.mark.parametrize("spelling", ENCODED_CREDENTIAL_NAMES)
def test_an_encoded_settings_key_is_masked_like_its_plain_spelling(
    seam: _Seam, spelling: str
) -> None:
    seam.records[("jobs_db", "source", "/")] = {
        **RECORD,
        "properties": {**RECORD["properties"], "connection": {"host": "db", spelling: SECRET}},
    }
    connection = _discover(seam)["properties"]["connection"]
    assert connection[spelling] == MASK
    assert connection["host"] == "db"


# The benign half of the same rule. Decoding must not turn an ordinary name into a secret
# one: these fold to themselves and to nothing in the secret shape.
ENCODED_ORDINARY_NAMES = ["misc%5Fnotes", "foreign%2Dkeys", "row%5Fcount", "primary+key"]


@pytest.mark.parametrize("spelling", ENCODED_ORDINARY_NAMES)
def test_an_encoded_ordinary_key_keeps_its_value(seam: _Seam, spelling: str) -> None:
    seam.records[("jobs_db", "source", "/")] = {
        **RECORD,
        "properties": {**RECORD["properties"], "connection": {"host": "db", spelling: "plain"}},
    }
    assert _discover(seam)["properties"]["connection"][spelling] == "plain"
