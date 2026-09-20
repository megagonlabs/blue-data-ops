from __future__ import annotations

import copy
import inspect
from typing import Annotated, Any

from blue_data_ops.operators import ErrorCategory, ErrorCode, ErrorStage, Operator
from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema

InputData = list[list[dict[str, Any]]]
Attributes = dict[str, Any]
Properties = dict[str, Any]

INPUT_DATA_DESCRIPTION = (
    "Record groups to operate on: a list of groups, each a list of record objects. Most tools "
    "take one group; the set, join, and similarity tools take two or more."
)
ATTRIBUTES_DESCRIPTION = (
    "Operator arguments for this tool. The published keys are the operator's declared "
    "attributes; an unlisted key is accepted and ignored."
)
# `data_registry` is deliberately absent from the list below. Core reads that key only when
# its value is a live `RegistrySeam` or `DataRegistry` instance, which is a Python object and
# not something a JSON request can carry: core's `resolve_registry` falls through every
# JSON-representable value to the two naming keys. Advertising it here told a remote client
# to send a string or an object, and what it got back was the tool's contained empty result
# with no explanation. Object injection is real and stays documented in the package README as
# what it is, an in-process Python API.
PROPERTIES_DESCRIPTION = (
    "Execution and backend settings for this call, or null. Recognized keys are "
    "`execution.timeout_seconds`; `algorithm`, which selects the estimator for `ops_classify`, "
    "`ops_cluster`, and `ops_sklearn_estimator`; `platform.name` together with "
    "`data_registry.name`, which the registry-backed tools need to resolve a registry at all; "
    "`service_prefix`; and the two provider namespaces, `openai.*` and `llm.*`, both of which "
    "are closed sets. `openai.*` accepts the generation parameters and nothing else: the "
    "provider, endpoint, project, tenant, region and credential are the deployment's, not the "
    "caller's, and a property naming one of them is refused rather than ignored. `model` picks "
    "a model within the deployment's provider; a provider-qualified name such as "
    "`vertex_ai/gemini-2.5-pro` is refused, and a deployment may narrow the set further."
)

# Core's own type parser lowercases the spelling and falls back to `Any` for a name it does
# not know, so this map holds exactly the names it recognizes. A spelling missing from here
# publishes no `type` rather than one narrower than core enforces. Two attributes land there:
# `select.operand_val`, declared `Any`, and `semantic_filter.return_idx`, whose core type
# string reads `boolean`, which core resolves to `Any` rather than to bool.
_JSON_SCALAR_TYPES: dict[str, str] = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "dict": "object",
    "list": "array",
    "none": "null",
}

# Value sets core's own validator closes: a value outside the tuple is rejected at VALIDATE
# and never reaches the operator body. A set core only documents in prose, or coerces, or
# silently falls back on, stays open here, because publishing an enum for one of those would
# refuse a call core accepts. `select.operand` is the near miss — its validator guards on
# truthiness, so the empty string passes validation and then matches no record.
ATTRIBUTE_ENUMS: dict[tuple[str, str], tuple[str, ...]] = {
    ("data_discover", "concept_type"): (
        "source",
        "database",
        "collection",
        "entity",
        "relation",
        "attribute",
    ),
    ("intersect", "match_option"): ("key_match", "seq_match"),
    ("join", "join_type"): ("inner", "left", "right", "outer"),
    ("join", "keep_keys"): ("left", "both"),
    ("normalize_text", "normalize_unicode"): ("NFC", "NFKC", "NFD", "NFKD"),
    ("segment_text", "split_strategy"): ("sentence", "paragraph", "token", "word", "heading"),
    ("semantic_join", "join_type"): ("inner", "left", "right", "outer"),
    ("semantic_join", "keep_keys"): ("left", "both"),
    ("union", "match_option"): ("key_match", "seq_match"),
    ("vector_embed", "on_missing_fields"): ("raise", "use_empty"),
    ("vector_search", "metric"): ("cosine", "dot", "l2"),
    ("vector_search", "on_missing_embedding"): ("embed_missing", "raise"),
    ("vector_search", "on_missing_fields"): ("raise", "use_empty"),
    ("vector_similarity", "comparison_mode"): ("cartesian", "pairwise"),
    ("vector_similarity", "metric"): ("cosine", "dot", "l2"),
    ("vector_similarity", "on_missing_embedding"): ("raise", "embed_missing"),
    ("vector_similarity", "on_missing_fields"): ("raise", "use_empty"),
}


class ErrorRecordModel(BaseModel):
    """One canonical operator error projected onto the wire with the frozen error vocabulary."""

    model_config = ConfigDict(extra="forbid")

    category: ErrorCategory
    code: ErrorCode
    operator_id: str
    stage: ErrorStage
    message: str
    retryable: bool
    suggestion: str | None


class ExecMetaModel(BaseModel):
    """Execution metadata carried alongside every canonical result."""

    model_config = ConfigDict(extra="forbid")

    is_empty: bool
    errors: list[ErrorRecordModel]
    logs: list[str]
    traces: dict[str, Any]


class RunResult(BaseModel):
    """The structured envelope for a primary tool: canonical ``run()`` projected once."""

    model_config = ConfigDict(extra="forbid")

    output_data: InputData
    output_attributes: dict[str, Any]
    exec_meta: ExecMetaModel


def _split_members(inner: str) -> list[str]:
    """Split a comma-separated type argument list, respecting nested brackets."""
    members: list[str] = []
    current = ""
    depth = 0
    for character in inner:
        if character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
        elif character == "," and depth == 0:
            members.append(current.strip())
            current = ""
            continue
        current += character
    if current.strip():
        members.append(current.strip())
    return members


def json_type_fragment(core_type: str) -> dict[str, Any]:
    """Translate one core attribute type string into a JSON Schema type fragment.

    Returns ``{"type": ...}``, ``{"anyOf": [...]}``, or an empty dict when no faithful
    translation exists. The empty dict is the honest answer for a spelling core itself
    resolves to ``Any``.
    """
    text = core_type.strip()
    lowered = text.lower()
    if not lowered:
        return {}
    if lowered.startswith("list[") and lowered.endswith("]"):
        items = json_type_fragment(text[5:-1])
        return {"type": "array", "items": items} if items else {"type": "array"}
    if lowered.startswith("dict[") and lowered.endswith("]"):
        members = _split_members(text[5:-1])
        if len(members) == 2 and json_type_fragment(members[0]) == {"type": "string"}:
            values = json_type_fragment(members[1])
            if values:
                return {"type": "object", "additionalProperties": values}
        return {"type": "object"}
    if lowered.startswith("union[") and lowered.endswith("]"):
        members = _split_members(text[6:-1])
    elif "|" in text:
        members = [part.strip() for part in text.split("|")]
    else:
        scalar = _JSON_SCALAR_TYPES.get(lowered)
        return {"type": scalar} if scalar else {}
    fragments = [json_type_fragment(member) for member in members]
    if not fragments or not all(fragments):
        return {}
    return {"anyOf": fragments}


def attributes_json_schema(operator: Operator) -> dict[str, Any]:
    """Publish what core declares about each attribute, omitting defaults appropriately.

    Every attribute keeps its description and gains its core type wherever that type is
    expressible in JSON Schema. A closed value set publishes as an ``enum`` only when core's
    validator rejects everything outside it and the operator's own default is a member; the
    second condition keeps a caller-registered operator that reuses a logical name from
    inheriting another operator's set.

    A default is published only for an optional attribute that both declares one and
    materializes it (``materialize_default`` true). Required attributes and the seven
    ``materialize_default=False`` declarations publish no default, matching the v2 canonical
    materialization boundary. Published defaults are deep copies, never aliases of core state.

    ``required`` names the attributes core declares required. Core rejects a call that omits
    one at VALIDATE, so withholding them advertised a wider contract than the operator has.
    """
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, spec in operator.attributes.items():
        entry: dict[str, Any] = {"description": spec.description}
        entry.update(json_type_fragment(spec.type))
        allowed = ATTRIBUTE_ENUMS.get((operator.name, name))
        if allowed is not None and (not spec.has_default or spec.default in allowed):
            entry["enum"] = list(allowed)
        if not spec.required and spec.has_default and spec.materialize_default:
            entry["default"] = copy.deepcopy(spec.default)
        properties[name] = entry
        if spec.required:
            required.append(name)
    schema: dict[str, Any] = {
        "type": "object",
        "description": ATTRIBUTES_DESCRIPTION,
        "properties": properties,
        "additionalProperties": True,
    }
    if required:
        schema["required"] = required
    return schema


def handler_signature(
    operator: Operator,
    return_annotation: type[BaseModel],
) -> inspect.Signature:
    """Build the tool handler signature: the open container arguments plus a structured return."""
    input_data_annotation = Annotated[
        InputData,
        Field(description=INPUT_DATA_DESCRIPTION),
    ]
    attributes_annotation = Annotated[
        Attributes,
        WithJsonSchema(attributes_json_schema(operator)),
    ]
    properties_annotation = Annotated[
        Properties | None,
        Field(description=PROPERTIES_DESCRIPTION),
    ]
    return inspect.Signature(
        parameters=[
            inspect.Parameter(
                "input_data",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=input_data_annotation,
            ),
            inspect.Parameter(
                "attributes",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=attributes_annotation,
                default={},
            ),
            inspect.Parameter(
                "properties",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=properties_annotation,
                default=None,
            ),
        ],
        return_annotation=return_annotation,
    )
