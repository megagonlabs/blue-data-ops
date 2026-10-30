"""Dollar-placeholder substitution.

``safe_substitute`` applies one dollar-placeholder pass and preserves inserted
data and line endings. Unknown names and Jinja syntax remain literal.

The remaining ``blue.utils.string_utils`` helpers (``camel_case``,
``remove_non_alphanumeric``, the web-safe base64 pair) are intentionally omitted:
they are outside the migrated operator closure and the base64 pair would add a new
``pydash`` dependency that this package does not otherwise need.
"""

from __future__ import annotations

from blue_data_ops.llm.templating import safe_substitute

__all__ = ["safe_substitute"]
