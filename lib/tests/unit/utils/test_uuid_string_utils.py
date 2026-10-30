"""Blue-compatible UUID, canonical-id, and string-substitution behavior.

Canonical ids use Blue's ``Separator.ID = ":"``. ``safe_substitute`` is re-exported
from ``llm.templating`` under the Blue-compatible import path.
"""

from __future__ import annotations

from blue_data_ops.llm import templating as templating_module
from blue_data_ops.utils.string_utils import safe_substitute
from blue_data_ops.utils.uuid_utils import (
    concat_ids,
    create_uuid,
    extract_name_id,
    extract_prefix,
    extract_sid,
    split_ids,
)


# --- uuid_utils --------------------------------------------------------------------
def test_create_uuid_is_short_lowercase_hex() -> None:
    generated = create_uuid()
    assert isinstance(generated, str)
    assert 1 <= len(generated) <= 8
    assert all(char in "0123456789abcdef" for char in generated)
    assert create_uuid() != generated  # distinct per call


def test_canonical_id_helpers_use_colon_separator() -> None:
    assert concat_ids("agent", "a1b2", "c3d4") == "agent:a1b2:c3d4"
    assert split_ids("agent:a1b2:c3d4") == ["agent", "a1b2", "c3d4"]
    assert extract_name_id("agent:a1b2:c3d4") == ["a1b2", "c3d4"]
    assert extract_sid("agent:a1b2:c3d4") == "a1b2:c3d4"
    assert extract_prefix("p:agent:a1b2:c3d4") == "p:agent"
    assert extract_prefix("a1b2:c3d4") is None  # fewer than three components


# --- string_utils.safe_substitute --------------------------------------------------
SUBST_CASES: list[tuple[str, dict[str, str], str]] = [
    ("$a", {"a": "x"}, "x"),
    ("$a", {"a": "$b", "b": "done"}, "$b"),  # inserted data is literal
    ("{{ a }}", {"a": "jx"}, "{{ a }}"),
    ("$missing stays", {}, "$missing stays"),
    ("{{ missing }} stays", {}, "{{ missing }} stays"),
    ("$a and {{ b }}", {"a": "1", "b": "2"}, "1 and {{ b }}"),
    ("plain", {}, "plain"),
]


def test_safe_substitute_is_one_pass() -> None:
    for template, mappings, expected in SUBST_CASES:
        assert safe_substitute(template, **mappings) == expected


def test_safe_substitute_is_one_shared_implementation() -> None:
    assert safe_substitute is templating_module.safe_substitute
