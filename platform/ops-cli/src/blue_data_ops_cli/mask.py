"""One notion of a credential, for every surface that hands a caller text it did not write.

The core library returns errors as data and raises them as exceptions, and both carry text
from further down: a provider SDK's message reaching ``ErrorRecord.message`` through
``EXECUTION_FAILED``, an attribute value quoted back in a refusal, a traceback under
``--log``. A provider SDK is free to put a request header or a fragment of a key into an
exception message, and this CLI cannot know in advance which one will.

**Where this applies.** Text this CLI writes *about* a run: the ``ERROR:`` line, the JSON
error object, every ``--log`` line, the traceback ``--log`` prints, and the ``settings``
envelope's masked entries.

**Where it deliberately does not.** The records an operator returns and the attributes
beside them. A record value that happens to look like a token is the output that was asked
for, and masking it would be the CLI corrupting the thing it was told to compute. The line
is whether the text is being narrated or returned.

**What counts as a credential** is settled four ways, strongest first. An exact value the
environment holds under a name that says credential catches key material of any shape,
including a provider's whose spelling nobody here has seen. The other three are shape: a
labelled assignment, a key literal a provider stamps with its own prefix, and an opaque run
long enough that nothing else is spelled that way.
"""

from __future__ import annotations

import os
import re

__all__ = [
    "CREDENTIAL_WORDS",
    "MASK",
    "SECRET_VARIABLE",
    "fold_key",
    "is_credential_key",
    "mask",
]

MASK = "***"
"""What a masked span reads as, spelled the way the profile store already spells one."""

_SHORTEST_SECRET = 8
"""Shorter than this, an environment value is not treated as key material.

A variable holding ``1`` or ``true`` would otherwise blank out every digit and every such
word in the sentence, which is a worse message and not a safer one.
"""

SECRET_VARIABLE = re.compile(
    r"(?:^|_)(?:API_?KEY|ACCESS_?KEY|SECRET_?KEY|PRIVATE_?KEY|SECRET|TOKEN"
    r"|PASSWORD|PASSWD|PASSPHRASE|CREDENTIALS?|AUTH|AUTHORIZATION)(?:_|$)",
    re.IGNORECASE,
)
"""Which environment variable holds key material, read off the name.

The profile spec settles the same question by declaration — a parameter whose cast is
``secret`` — and the two answers have to agree, because a parameter declared secret here and
unrecognised there would be masked in ``profile inspect`` and printed in an error message.
``test_secret_canary`` holds them together.

Bare ``KEY`` is left out. Operator attributes are named ``key``, ``argmax_key``, ``sum_key``
and so on throughout this library, and treating those as key material would mask an ordinary
column name everywhere it appeared.

``PWD`` is left out too, and it is the one word this list and :data:`CREDENTIAL_WORDS`
disagree about. ``Pwd=`` is how an ODBC connection string spells a password, so a key called
``pwd`` on the command line is refused; but ``PWD`` in the environment is the shell's
working directory, and reading it as key material would replace the path in every message
that names one.
"""

_HUMP = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
"""Where one word ends and the next begins inside a run of letters with no separator.

Two boundaries, because a name spells them two ways: ``clientSecret`` changes case going up,
and ``AWSSecretKey`` changes going down into the last capital of a run. ``oauth2Token`` is
the first one again, which is why a digit counts as the end of a word.
"""

_NOT_A_WORD = re.compile(r"[^A-Za-z0-9]+")


def fold_key(name: str) -> str:
    """*name* as lower-case words joined by ``_``, whatever it was spelled with.

    ``clientSecret``, ``client-secret``, ``Client Secret`` and ``client.secret`` are one
    name written four ways, and a credential vocabulary that reads only the fourth answers
    for one of them. So the spelling is folded first — camel humps into separators, then
    every separator into ``_`` — and the vocabulary is applied once to the result.
    """
    return _NOT_A_WORD.sub("_", _HUMP.sub("_", name)).strip("_").lower()


CREDENTIAL_WORDS = (
    "apikey",
    "api_key",
    "accesskey",
    "access_key",
    "secretkey",
    "secret_key",
    "privatekey",
    "private_key",
    "secret",
    "token",
    "password",
    "passwd",
    "pwd",
    "passphrase",
    "pass_phrase",
    "credential",
    "credentials",
    "auth",
    "authorization",
)
"""Every word that makes a command-line key a credential key, and nothing else.

Read against a folded name, so an entry matches a whole word between ``_`` boundaries:
``secret`` answers for ``clientSecret``, ``secret_key`` and ``Client Secret``, and does not
answer for ``secretariat``. Both ``apikey`` and ``api_key`` are listed because folding
leaves ``apiKey`` as ``api_key`` and ``APIKEY`` as ``apikey``.

The set is closed rather than open-ended, and what is left out of it is as deliberate as
what is in.

*In, and why.* ``password``, ``passwd``, ``pwd``, ``passphrase`` and ``pass_phrase`` are
spellings of one thing and of nothing else: ``Pwd=`` is how an ODBC connection string writes
a password, and the last is there because folding leaves ``passPhrase`` as two words.
``secret``, ``token`` and ``credential`` are the generic words a settings object reaches for.
``api_key``, ``access_key``, ``secret_key`` and ``private_key`` are the qualified spellings,
which fold to a word plus ``key``. ``auth`` and ``authorization`` name a header value or a
bearer token, and nothing else in this library is called either.

*Out, and why.* ``key``, ``keys``, ``foreign_keys``, ``partition_key`` and ``argmax_key``
are operator attribute names throughout this library. ``host``, ``port``, ``database`` and
``dsn`` are connection settings and none of them is secret. ``user``, ``username`` and
``login`` are the interesting ones: an account name is not key material, and a data source
is ordinarily configured with one on the command line.

Those last three are where this list parts from the one the library's discovery operator
uses to **mask** a discovered registry value, and it parts on purpose. Masking costs nothing
when the guess is wrong — a username comes out as ``***`` in one message. Refusing costs the
caller the command they typed. So a name that is ordinary somewhere has to stay usable here
even where it is worth hiding there.

Discovery folds a key the same way this module does, and keeps its own list for that reason.
One folding rule used by both, with a list on each side, is the shape this wants; the change
reaches across both packages and has not been made. Until it is, the folding is written
twice and nothing checks that the two stay the same.
"""

_CREDENTIAL_KEY = re.compile(rf"(?:^|_)(?:{'|'.join(CREDENTIAL_WORDS)})(?:$|_)")
"""The vocabulary as one pattern, built from the list so the two cannot drift apart."""


def is_credential_key(name: str) -> bool:
    """Whether an attribute or property *key* is one whose value would be a credential.

    ``--attribute`` and ``--property`` are the CLI's only unbounded input channels, and a
    key this answers for is refused rather than carried, because a value passed there is in
    argv and in shell history before this module can reach it.

    Bare ``key`` is not in :data:`CREDENTIAL_WORDS`, so ``key``, ``argmax_key``, ``sum_key``,
    ``partition_key`` and ``foreignKeys`` are ordinary attribute names at any depth —
    they are named throughout this library, and refusing them would refuse an ordinary
    operator call.
    """
    return bool(_CREDENTIAL_KEY.search(fold_key(name)))


_LABELLED = re.compile(
    r"""(?ix)
    (                                           # kept: the label and its separator
      \b (?: x- )?
      (?: api[-_]?key | access[-_]?token | refresh[-_]?token | auth[-_]?token
        | token | secret | password | passwd | credential | authorization )
      \b \s* [=:] \s* (?: bearer \s+ | basic \s+ )? ["']?
    )
    ( [^\s"',;)\]}]{4,} )                       # masked: the value it introduces
    """
)

_CARRIED = re.compile(r"(?i)\b(bearer|basic)\s+([A-Za-z0-9._~+/=-]{6,})")
"""A carried credential with no label in front of it, as an HTTP header quotes one."""

_STAMPED = re.compile(
    r"""(?x)
    \b (?:
        sk-(?: proj- | ant- )? [A-Za-z0-9_-]{6,}     # OpenAI, Anthropic
      | sk_(?: live | test )_ [A-Za-z0-9]{6,}
      | gh[pousr]_ [A-Za-z0-9]{10,}
      | glpat- [A-Za-z0-9_-]{10,}
      | xox[baprs]- [A-Za-z0-9-]{10,}
      | AIza [0-9A-Za-z_-]{10,}
      | AKIA [0-9A-Z]{10,}
      | hf_ [A-Za-z0-9]{10,}
      | ya29\. [A-Za-z0-9_-]{10,}
      | eyJ [A-Za-z0-9_-]{6,} \. [A-Za-z0-9_-]{6,} \. [A-Za-z0-9_-]{4,}
    )
    """
)
"""Key literals a provider stamps with its own prefix.

A floor rather than a census: the planner and the semantic operators reach whatever provider
LiteLLM or the OpenAI SDK is pointed at, and a prefix nobody has written down here is what
the environment rule and the opaque run below are for.
"""

_OPAQUE_RUN = re.compile(r"[A-Za-z0-9_-]{28,}")
"""A candidate unbroken run. Twenty-eight is under the shortest opaque key in common use —
a thirty-two character hex key — and over anything a sentence spells in one word.

The class stops at ``.`` and ``/`` so that a path, which is neither short nor a credential,
is measured one segment at a time.
"""


def _is_key_material(run: str) -> bool:
    """Whether a run that long reads as generated key material rather than as a name.

    A generated key is either heavy with digits or mixes cases. A long identifier a message
    quotes — an operator id, a temporary directory named after the test that made it — is
    neither, and masking one would edit a message this CLI is trying to hand over whole.
    """
    digits = sum(1 for character in run if character.isdigit())
    if digits >= 4:
        return True
    return digits >= 1 and any(c.islower() for c in run) and any(c.isupper() for c in run)


def _environment_secrets() -> list[str]:
    """Every value the environment holds under a name that says credential, longest first.

    Read on each call rather than cached at import: the root callback writes a profile's
    resolved values into the environment while the command runs, and a snapshot taken
    earlier would not hold the key the run is actually using. Longest first, so a value that
    is a substring of another does not cut it in half and leave the tail behind.
    """
    found = [
        value
        for name, value in os.environ.items()
        if len(value) >= _SHORTEST_SECRET and SECRET_VARIABLE.search(name)
    ]
    return sorted(found, key=len, reverse=True)


def mask(text: str) -> str:
    """*text* with anything that could be a credential replaced by :data:`MASK`."""
    for value in _environment_secrets():
        text = text.replace(value, MASK)
    text = _LABELLED.sub(lambda found: found.group(1) + MASK, text)
    text = _CARRIED.sub(lambda found: f"{found.group(1)} {MASK}", text)
    text = _STAMPED.sub(MASK, text)
    return _OPAQUE_RUN.sub(
        lambda found: MASK if _is_key_material(found.group()) else found.group(), text
    )
