"""Blue-compatible type, signature, JSON, UUID, and string utilities.

Private operator and metadata helpers delegate here; these modules do not import
``blue``. See ``COMPATIBILITY.md`` for platform-coupled errors and similarity
helpers that remain outside this package.
"""

from __future__ import annotations

from blue_data_ops.utils.json_utils import json_query, json_query_set, merge_json
from blue_data_ops.utils.string_utils import safe_substitute
from blue_data_ops.utils.tool_utils import (
    annotation_to_type_str,
    convert_type_string_to_mcp,
    extract_signature,
)
from blue_data_ops.utils.type_utils import (
    create_pydantic_model,
    string_to_python_type,
    validate_parameter_type,
)
from blue_data_ops.utils.uuid_utils import (
    concat_ids,
    create_uuid,
    extract_name_id,
    extract_prefix,
    extract_sid,
    split_ids,
)

__all__ = [
    "annotation_to_type_str",
    "concat_ids",
    "convert_type_string_to_mcp",
    "create_pydantic_model",
    "create_uuid",
    "extract_name_id",
    "extract_prefix",
    "extract_sid",
    "extract_signature",
    "json_query",
    "json_query_set",
    "merge_json",
    "safe_substitute",
    "split_ids",
    "string_to_python_type",
    "validate_parameter_type",
]
