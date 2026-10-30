# blue-data-ops — Data Model

Every structure this package reads, returns, or serializes, and the rules each one is checked against.

There is no database here and no schema migration.
The package holds five families of structure:

| Family | What it describes | Defined in |
|---|---|---|
| Operator data | the records an operator consumes and produces | `operators/types.py` |
| The call contract | the attributes and properties one call takes, and the result it returns | `operators/types.py`, `operators/_metadata.py` |
| Catalog metadata | an operator's discovery-facing card and the registry views over it | `operators/registry.py`, `operators/_discovery.py` |
| Resource packages | the per-operator Markdown shipped as package data, and the index and manifests that bind it | `operator_skills/` |
| Plan and planning records | a serializable pipeline, a planning request, and the schema snapshot a generator may be given | `plan/` |

The package validates and serializes these structures but does not persist them.

---

## 1. Operator Data: Records, Groups, and Bundles

Operator input and output use one shape at three levels.

| Alias | Type | Meaning |
|---|---|---|
| `Record` | `dict[str, Any]` | one JSON-like object |
| `Data` | `list[Record]` | one group of records |
| `DataBundle` | `list[Data]` | the argument and return shape: a list of record groups |

A bundle's outer list is how a multi-input operator receives its inputs.
A join reads group 0 and group 1; an aggregate reads group 0 and ignores the rest.
There are no named ports.

```python
[
    [{"name": "a", "score": 3}, {"name": "b", "score": 9}],   # group 0
    [{"name": "b", "region": "west"}],                         # group 1
]
```

Record values are whatever the caller puts there.
Nothing in the package coerces or reshapes a record on the way in, and nothing requires that records within a group share keys.
Operators that need a numeric value coerce it at the point of use and skip what will not convert.

The shipped per-operator guides sometimes call a bundle a *tensor*. It is the same `list[list[dict]]`.

### 1.1 The empty forms

The three empty forms have distinct meanings.

| Value | Meaning |
|---|---|
| `[[]]` | one empty group. The normalized successful-empty result, reported with `is_empty=True`. |
| `[[{}]]` | one group holding one record with no keys. Non-empty data. |
| `[]` | no groups at all. Accepted as input; `run()` never returns it, because normalization rewrites it to `[[]]`. |

An operator that consumes nothing still takes the argument.
The convention is `[[]]`, and the `accepts-none` discovery tag records that the records are unread without making the parameter optional.

### 1.2 Structural validation

`run()` accepts any bundle and lets the operator judge the contents.
The 21 `@3.0.0` operators add one structural check ahead of their own validation: input that is not a list of lists of dictionaries is rejected with `INVALID_INPUT` and the suggestion `supply a list of record groups`.
The `@2.0.0` implementations do not perform that check, so a malformed bundle reaches the transform and is contained as `EXECUTION_FAILED`.

---

## 2. The Call Contract

A call takes a bundle, an attributes mapping, and an optional properties mapping.
Attributes are the operator's arguments.
Properties are execution settings.

### 2.1 Declared attributes

Each operator class declares its attributes as a class variable mapping names to `AttributeSpec`, an immutable dataclass.

| Field | Type | Meaning |
|---|---|---|
| `type` | `str` | a type string such as `"str"`, `"int"`, `"list[str]"`, `"str \| dict"` |
| `description` | `str` | one line, surfaced to discovery and to the protocol schema |
| `required` | `bool` | whether the caller must supply it |
| `default` | `Any` | the declared default, or `None` when none is declared |
| `has_default` | `bool` | whether a default was declared at all |
| `materialize_default` | `bool` | whether `run()` writes the default into the call attributes when the caller omits it |

`has_default` exists because `default=None` is a legitimate default and cannot be distinguished from "no default" by the value alone.
The constructor takes the module-level sentinel `ABSENT` as its own default and sets `has_default` from whether it was replaced.

`materialize_default` is false for a declaration whose absence and whose default value behave differently inside the transform.
Such an attribute publishes no default to the protocol schema either.

### 2.2 The live definition view

The class-level declaration is projected at construction into a per-instance mapping of plain dictionaries, stored at `properties["attributes"]`.
This is the Blue-compatible metadata view, and it is mutable.

```python
{
    "max_key": {
        "type": "str",
        "description": "The key to find the maximum value for",
        "required": True,
        "hidden": False,
    },
    "output_key": {
        "type": "str",
        "description": "The key name for the result max value",
        "required": False,
        "hidden": False,
        "default": "max",
    },
}
```

`hidden` appears only in the live view; there is no `hidden` field on `AttributeSpec`.
The `default` key is present only when one was declared.
`update_attributes`, `set_attribute_description`, `set_attribute_required`, and `set_attribute_hidden` edit this view and regenerate the signature; the immutable projection is rebuilt from it on the next call.
A caller that edits the live view changes what the operator validates against.

The same definitions are copied into the signature dictionary under `parameters.attributes.properties`, with each `type` string converted to its MCP form — `"str"` becomes `{"type": "string"}`.
The signature is read through `get_signature()` and follows the platform's own extraction rules.

### 2.3 Properties

Properties are a flat `dict[str, Any]`.
Cross-cutting settings use a dotted namespace; operator-specific settings do not.

Every operator initializes these:

| Key | Default | Read by |
|---|---|---|
| `tool_type` | `"operator"` | the `is_operator` and `get_tool_type` classifiers |
| `validate_input` | `True` | retained platform-compatible metadata |
| `validate_output` | `True` | retained platform-compatible metadata |
| `validation_error_handling` | `"fail"` | the default attribute validator, on a validator exception |
| `max_records` | `None` | retained platform-compatible metadata |
| `timeout` | `300` | retained platform-compatible metadata; it does **not** set the deadline |
| `error_handling` | `"skip"` | retained platform-compatible metadata |
| `log_processing_stats` | `True` | retained platform-compatible metadata |
| `attributes` | `{}`, then the live definitions | validation, default materialization, signature generation |
| `hyperparameters` | `{}` | operator-specific tuning, read per operator |
| `signature` | generated | `get_signature()` and the parameter accessors |

The runtime reads these across operators:

| Key | Type | Effect |
|---|---|---|
| `execution.timeout_seconds` | finite number greater than zero | the per-call deadline. A Boolean or a non-finite value is `INVALID_INPUT` at `VALIDATE`. |
| `data_registry` | `RegistrySeam` or a raw `DataRegistry` | an injected registry; a raw one is wrapped |
| `platform.name`, `data_registry.name` | `str` | the two construction keys used when nothing is injected |
| `llm_client` | `LLMClient` | an injected client, so a call reuses one instead of constructing per call |
| `llm.cache`, `llm.cache_dir`, `llm.max_parallel`, `llm.rate_limit` | client controls | response caching, bounded concurrency, and rate limiting |
| `openai.model` | `str` | the model for an LLM operator; the class default is `gpt-6-luna` |
| `algorithm` | `str` | the estimator or clustering algorithm for the ML operators |

A class may pin its own defaults through a class-level `PROPERTIES` mapping, deep-copied into each instance.
Operator-specific keys are listed per operator in [`../lib/OPERATORS.md`](../lib/OPERATORS.md) and in each operator's shipped resource guide.

### 2.4 Result types

Two named tuples cross the internal hooks.

| Type | Fields | Returned by |
|---|---|---|
| `ValidationResult` | `ok: bool`, `reason: str \| None` | the internal validation hook |
| `FunctionResult` | `output_data: DataBundle`, `output_attributes: Attributes` | the internal execution hook |

A rejected `ValidationResult` must carry a non-empty `reason`, which becomes the error record's `suggestion`.
A rejection with no reason is itself an error: `VALIDATION_RESULT_INVALID`.

`run()` checks the exact type of both.
A look-alike tuple with the right shape is `VALIDATION_RESULT_INVALID` or `EXECUTION_RESULT_INVALID` instead of being unpacked.

### 2.5 output_data against output_attributes

`run()` returns a three-tuple, and the first two carry different kinds of thing.

| Position | Name | Holds |
|---|---|---|
| 0 | `output_data` | the records. Normalized: an all-empty bundle becomes `[[]]`. |
| 1 | `output_attributes` | scalar facts about the call that are not records |
| 2 | `exec_meta` | execution metadata; see section 3 |

The separation exists so that a count or a diagnostic can never collide with a data key, and so that adding one to an operator never changes the shape of its records.
Result attributes are deep-copied per call, so two calls never share a mapping.

Two operators populate it today, both on their `@3.0.0` path: `avg` reports `num_values_used`, and `insert_table` reports `num_rows_insert` when the row count is knowable.
Every other operator returns `{}`.
A caller should read a key's absence as unknown rather than zero.

---

## 3. Execution Metadata

### 3.1 ExecMeta

Every `run()` call returns one `ExecMeta`, successful or not.

| Field | Type | Meaning |
|---|---|---|
| `is_empty` | `bool` | the result normalized to `[[]]` from an all-empty bundle. True only on a successful empty result. |
| `errors` | `list[ErrorRecord]` | empty on success. At most one record per call today. |
| `logs` | `list[str]` | operator log lines; empty in the shipped operators |
| `traces` | `dict[str, Any]` | optional measurements; see 3.4 |

A failed call returns `[[]]`, `{}`, and `is_empty=False` with a record.
A successful empty call returns `[[]]`, `{}`, and `is_empty=True` with no record.
The two are distinguished by `is_empty`, not by the data.

### 3.2 ErrorRecord

| Field | Type | Meaning |
|---|---|---|
| `category` | `ErrorCategory` | how bad it is |
| `code` | `ErrorCode` | what happened |
| `operator_id` | `str` | the exact operator, pinned. An unregistered instance reports `name@2.0.0`. |
| `stage` | `ErrorStage` | where in the boundary it happened |
| `message` | `str` | a fixed short phrase, not interpolated from caller or provider text |
| `retryable` | `bool` | Fixed advice from an owned reason, or an intentional custom author; it does not add retries |
| `suggestion` | `str \| None` | the corrective hint, where one exists |

`message` is deliberately fixed.
Built-in diagnostics do not interpolate caller values, provider exception text, response bodies or credentials. `OperatorExecutionError` deliberately publishes validated author-selected constants; its constructor cannot determine whether an author supplied dynamic private text. See [the trusted-author contract](../docs/extending.md#intentional-public-execution-diagnostics).

### 3.3 The closed error vocabulary

Three categories:

| Category | Meaning |
|---|---|
| `RECOVERABLE` | the caller can fix the call and try again |
| `FAILED` | the call cannot succeed as written |
| `TIMEOUT` | the deadline expired |

Five stages, in the order the boundary runs them:

| Stage | What runs there |
|---|---|
| `DEFAULTS` | declared optional defaults are materialized into the call attributes |
| `VALIDATE` | the validation hook runs and its result is type-checked |
| `EXECUTE` | the transform runs |
| `NORMALIZE` | the result is type-checked and empty output is normalized |
| `REFINE` | retained so a stored 2.x record still decodes; 3.0 produces no record at this stage |

Nine codes:

| Code | Category | Stage | Raised when |
|---|---|---|---|
| `DEFAULTS_FAILED` | `FAILED` | `DEFAULTS` | default materialization raised |
| `INVALID_INPUT` | `RECOVERABLE` | `VALIDATE` | validation rejected the call, or the timeout setting is unusable |
| `VALIDATION_FAILED` | `FAILED` | `VALIDATE` | the validator itself raised, or the attribute projection could not be rebuilt |
| `VALIDATION_RESULT_INVALID` | `FAILED` | `VALIDATE` | the validator returned something that is not a usable `ValidationResult` |
| `EXECUTION_FAILED` | `FAILED` or `RECOVERABLE` | `EXECUTE` | the transform raised, or returned `None`. A missing LLM extra is the recoverable case. |
| `EXECUTION_RESULT_INVALID` | `FAILED` | `NORMALIZE` | the transform returned something that is not a usable `FunctionResult` |
| `REFINEMENT_FAILED` | — | `REFINE` | retained for decoding; unused in 3.0 |
| `REFINEMENT_RESULT_INVALID` | — | `REFINE` | retained for decoding; unused in 3.0 |
| `OPERATOR_TIMEOUT` | `TIMEOUT` | `EXECUTE` | the per-call deadline expired |

`EXECUTION_FAILED` is the one code that appears under two categories.
A `ModuleNotFoundError` naming `litellm`, `diskcache`, or `jinja2` is reported as `RECOVERABLE` with an install suggestion, because installing the extra fixes it.
Everything else at that stage is `FAILED`.

### 3.4 Traces

`traces` is an open mapping.
The 21 `@3.0.0` operators may add three keys:

| Key | Shape | When |
|---|---|---|
| `input_shape` | `{"groups": int, "rows_per_group": list[int]}` | the input bundle was structurally valid; captured before validation |
| `output_shape` | the same shape | the call succeeded and normalized |
| `elapsed_ms` | finite, non-negative `float` | the clock read successfully, measured around the whole call |

The counts are taken at capture time and do not change if the caller mutates its data afterwards.
A missing key means unavailable, not zero.
`nl2llm@3.0.0` may additionally report a finite non-negative `cost` in USD with `cost_basis="estimated"` after exactly one priced provider attempt; a proven local cache hit reports `cost=0.0`, and retries, failures, unknown prices, and injected clients omit both keys.

---

## 4. Catalog Metadata

### 4.1 OperatorCard

A card is the discovery-facing record of one exact operator.
It is an immutable dataclass and its `operator_id` is always pinned.

| Field | Type | Meaning |
|---|---|---|
| `operator_id` | `str` | `name@<MAJOR.MINOR.PATCH>` |
| `name` | `str` | the logical operator name, such as `select` |
| `version` | `str` | the three-part version, validated as semver at registration |
| `description` | `str` | copied from the operator class |
| `tags` | `tuple[str, ...]` | ordered discovery tags; see 4.3 |
| `when_to_invoke` | `str` | one sentence of invocation guidance |
| `deprecated` | `bool` | lifecycle flag. No card in 3.0 sets it. |

```python
OperatorCard(
    operator_id="normalize_text@2.0.0",
    name="normalize_text",
    version="2.0.0",
    description=(
        "Normalize raw text into a stable canonical form for downstream extraction "
        "and segmentation."
    ),
    tags=(
        "domain-text",
        "flow-transform",
        "accepts-data",
        "produces-data",
        "capability-normalization",
    ),
    when_to_invoke=(
        "Use when text needs canonical Unicode, whitespace, case, or recognized-date "
        "normalization before later text work."
    ),
    deprecated=False,
)
```

Provenance is not a card field.
Whether a card came from the package factory, and whether it carries planning authority, is tracked privately on the registry that built it, so nothing serializes it and no caller can supply it.

### 4.2 The three registry views

Each factory returns a fresh `OperatorRegistry` holding separate operator instances.

| Factory | Cards | Metadata on the cards | Use |
|---|---|---|---|
| `default_registry(**versions)` | 33, all at `@1.0.0` unless overridden per name | empty `tags`, empty `when_to_invoke` | the raw compatibility view |
| `active_registry()` | 33, one exact version per operator: 12 at `@2.0.0` and 21 at `@3.0.0` | validated discovery metadata | ordinary discovery and execution |
| `versioned_registry()` | 87: 33 at `@1.0.0`, 33 at `@2.0.0`, 21 at `@3.0.0` | validated discovery metadata | migration code that needs retained history |

A `default_registry` keyword override pins one name to another version after semver validation; an unknown name is ignored.
For the 21 names that have an outcome implementation, only an exact `"3.0.0"` override selects it.

The 12 operators whose active version is `@2.0.0` are `argmax`, `argmin`, `create_database`, `create_table`, `data_discover`, `delete`, `normalize_text`, `segment_text`, `select`, `sklearn_estimator`, `sum`, and `union`.
The other 21 are active at `@3.0.0`.

### 4.3 The discovery tag vocabulary

Built-in cards carry tags on six namespaces, always in this order:

| Namespace | Cardinality on a built-in | What it states |
|---|---|---|
| `domain-*` | exactly one | the primary subject area, not the output type |
| `flow-*` | one or more | valid role in a pipeline |
| `accepts-*` | one or more | the kind of upstream input consumed |
| `produces-*` | one or more | the result kind or externally visible effect |
| `capability-*` | one or more | the operation family or a specific action |
| `requires-*` | zero or more | an unconditional operator-specific runtime requirement |

Values are flat labels, not a hierarchy, and a card may carry both a broad and a specific capability.
68 values are declared across the six closed sets, and 59 are carried by a card today.
Tags on a built-in must be lowercase, hyphenated, unique, and sorted by namespace order then lexicographically, and every value must be in its namespace's closed set.
A built-in that violates any of this raises `DiscoveryError` during the validation pre-pass, before any card is registered, so no partial catalog exists.
Custom registrations through the public `register()` keep arbitrary tags and are not validated.

The full value list and each active card's tags are in [`../lib/OPERATORS.md`](../lib/OPERATORS.md).

---

## 5. Resource Packages

Per-operator guidance ships as Markdown package data keyed by exact operator ID.
There are 54 packages: 33 at `@2.0.0` and 21 at `@3.0.0`.

### 5.1 Layout

```
operator_skills/
  _index.json                  # pinned id -> manifest path
  max/
    2.0.0/
      manifest.json            # digest per resource file
      Operator.md
      examples.md
    3.0.0/
      manifest.json
      Operator.md
      examples.md
```

Five resource kinds are recognized, each bound to one exact filename:

| Kind | File | Required |
|---|---|---|
| `guide` | `Operator.md` | yes, in every manifest |
| `examples` | `examples.md` | no |
| `optimization` | `optimization.md` | no |
| `issues` | `issues.md` | no |
| `history` | `history.md` | no |

Every shipped package declares `guide` and `examples`.
None declares `history`, so every package reports levels 2 and 3 and no package supports level 4.

### 5.2 The index document

```json
{
  "format": "blue-data-ops/operator-skill-index@1",
  "packages": {
    "max@2.0.0": "max/2.0.0/manifest.json",
    "max@3.0.0": "max/3.0.0/manifest.json"
  }
}
```

The two keys are exact and exhaustive: any other top-level key, or a different `format`, invalidates the document.
Every `packages` key must be a pinned ID, and its value must be exactly `<name>/<version>/manifest.json` derived from that key.
The index is closed rather than best-effort — one malformed row makes every index-backed call raise `MANIFEST_INVALID`, including calls for operators whose own rows are intact.

### 5.3 The manifest document

```json
{
  "format": "blue-data-ops/operator-skill@1",
  "operator_id": "max@3.0.0",
  "resources": {
    "guide": {
      "path": "Operator.md",
      "sha256": "0c88957ce6129801f56a9167d5c94fef0418236a1f9e959a953f786a5e46a883"
    },
    "examples": {
      "path": "examples.md",
      "sha256": "11541045fb377b9b514cfb239f40b1adcea660f0ac6f42ac666427eb9b2a5c7f"
    }
  }
}
```

The three top-level keys are exact and exhaustive.
`operator_id` must equal the ID the caller asked for, or the call is `BINDING_MISMATCH`.
Each resource entry carries exactly `path` and `sha256`; `path` must be the filename that kind is bound to, and `sha256` must be 64 lowercase hex characters and must match the file read from disk.

### 5.4 Bounds

Checked before any text is decoded or returned:

| Bound | Value |
|---|---|
| index bytes | 4096 |
| manifest bytes | 4096 |
| resource bytes | 16384 |
| JSON nesting depth | 4 |

The reader also rejects an absolute path, a `.` or `..` path segment, a symlink at any level of the walk, a non-regular file, and duplicate JSON keys.

### 5.5 What a load returns

| Type | Fields |
|---|---|
| `OperatorSkillDescriptor` | `card`, `declared_kinds`, `declared_levels` |
| `OperatorSkillView` | `card`, `requested_level`, `loaded_kinds`, `io`, `guide`, `examples`, `history` |
| `OperatorIOSchema` | `input_shape`, `output_shape`, `attributes` |
| `OperatorResource` | `operator_id`, `kind`, `text`, `sha256` |

Levels are cumulative: 2 loads `guide`, 3 adds `examples`, 4 adds `history`.
`OperatorIOSchema` reports `input_shape` and `output_shape` as the literal string `"List[List[Dict]]"` and carries a detached deep copy of the operator's live attribute projection, so a view never aliases registry state.

---

## 6. The Pipeline Record

A `DataPipeline` is a live record that serializes to JSON through `to_dict()` and rebuilds through `from_dict()`.
Four record levels stack, each adding keys:

| Level | Adds |
|---|---|
| base | `id`, `label`, `type`, `properties` |
| graph | `nodes`, `map` |
| entity graph | `entities` |
| data pipeline | `provenance`, `input`, `output`, `attributes` |

`map` indexes labels to IDs, so a labelled node or entity is reachable by name.
`from_dict()` requires `id` and `type` and fills the rest with empty defaults, which is what lets a hand-written record parse.

### 6.1 Node records

| Key | Type | Meaning |
|---|---|---|
| `id` | `str` | generated short hex, unique within the record |
| `label` | `str \| None` | optional name, indexed in `map` |
| `type` | `str` | `INPUT`, `OUTPUT`, or `OPERATOR` |
| `prev`, `next` | `list[str]` | reciprocal edge lists |
| `properties` | `dict` | per-node settings, merged last into the operator call |
| `values` | `dict` | values by provenance path |
| `statuses` | `dict` | statuses by provenance path |
| `value` | `Any` | the current value, set on input and output nodes at definition |
| `provenance` | `str` | the dotted path of the plan that owns the node |
| `<entity type>` | `str` | the linked entity's ID, keyed by entity type, so an operator node carries `"OPERATOR": "<id>"` |

Edges are reciprocal and the executor checks that both sides agree: a `prev` entry whose counterpart has no matching `next` is a `PipelineError`, as are a duplicate edge, a dangling reference, and an unsupported node type.

### 6.2 Operator entity records

An operator node links to an entity that holds the call:

| Key | Type | Meaning |
|---|---|---|
| `id`, `label`, `type`, `properties` | | the base fields; `type` is `OPERATOR` |
| `nodes` | `list[str]` | the node IDs that link to this entity |
| `operator_id` | `str` | the pinned `name@<MAJOR.MINOR.PATCH>` |
| `attributes` | `dict` | the call attributes |

`operator_id` must be pinned.
`define_operator` and `create_operator` reject a bare name, a deployment route such as `/server/<server>/operator/<name>`, and anything else that does not match `name@<MAJOR.MINOR.PATCH>`.

### 6.3 A complete record

Three nodes and one operator entity, as `to_dict()` returns it.
Node IDs are generated, so two structurally identical plans carry different IDs.

```json
{
  "id": "1b8edd9c",
  "label": "demo",
  "type": "DATA_PIPELINE",
  "nodes": {
    "e0983f53": {
      "id": "e0983f53", "label": "records", "type": "INPUT",
      "prev": [], "next": ["bd2fe6b6"],
      "properties": {}, "values": {}, "statuses": {},
      "value": null, "provenance": "$.1b8edd9c"
    },
    "bd2fe6b6": {
      "id": "bd2fe6b6", "label": null, "type": "OPERATOR",
      "prev": ["e0983f53"], "next": ["32fb2ff1"],
      "properties": {}, "values": {}, "statuses": {},
      "OPERATOR": "7b67d9e3", "provenance": "$.1b8edd9c"
    },
    "32fb2ff1": {
      "id": "32fb2ff1", "label": "selected", "type": "OUTPUT",
      "prev": ["bd2fe6b6"], "next": [],
      "properties": {}, "values": {}, "statuses": {},
      "value": null, "provenance": "$.1b8edd9c"
    }
  },
  "map": {"records": "e0983f53", "selected": "32fb2ff1"},
  "entities": {
    "OPERATOR": {
      "7b67d9e3": {
        "id": "7b67d9e3", "label": null, "type": "OPERATOR",
        "properties": {}, "nodes": ["bd2fe6b6"],
        "operator_id": "select@2.0.0",
        "attributes": {"operand_key": "score", "operand": ">", "operand_val": 5}
      }
    }
  },
  "properties": {},
  "provenance": "$",
  "input": "e0983f53",
  "output": "32fb2ff1",
  "attributes": {}
}
```

### 6.4 Node status

Seven status values are defined: `INITED`, `REFINING`, `REFINED`, `EXECUTING`, `EXECUTED`, `PLANNED`, and `FAILED`.
The executor sets `EXECUTING`, `EXECUTED`, and `FAILED`.
A node already carrying `EXECUTING`, `EXECUTED`, or `FAILED` is refused at preflight, because a record cannot be replayed in place.

### 6.5 Execution records

Execution returns immutable dataclasses rather than mutating a caller structure.

| Type | Fields |
|---|---|
| `PipelinePreflight` | `node_order`, `operator_ids` |
| `NodeRun` | `node_id`, `operator_id`, `status`, `output_data`, `output_attributes`, `exec_meta` |
| `PipelineRun` | `output_data`, `node_runs`, `failed_node_id`, and the derived `succeeded` |

`node_runs` holds one entry per completed operator node, in execution order.
Input and output nodes do not produce one.
On failure, `output_data` is `[[]]` and `failed_node_id` names the first node that failed.

---

## 7. Planning Records

### 7.1 Request

| Type | Fields |
|---|---|
| `DiscoveryQuery` | `text`, `tags`, `limit` |
| `PlanningRequest` | `goal`, `discovery_queries`, `operator_attributes`, `data_scope`, `allowed_operator_ids`, `input_label`, `output_label`, and five bounds |

Both validate in `__post_init__` and raise `PlanningError` with code `INVALID_REQUEST` rather than constructing something malformed.
A query needs text or tags and a positive limit; a request needs a non-empty goal, at least one query, and positive bounds.
The five bounds default to 40 discovery cards, 8 drafts, 16 steps, 18 nodes, and 17 edges.

### 7.2 Draft

| Type | Fields |
|---|---|
| `PlanStep` | `step_id`, `operator_id`, `attributes`, `depends_on`, `label` |
| `PlanDraft` | `steps`, `label` |

A draft is a flat list of steps with dependency edges by step ID.
Compilation turns it into a `DataPipeline`: one node per step, one input node, one output node, and the dependency edges as reciprocal node edges.

### 7.3 Result

| Type | Fields |
|---|---|
| `DiscoverySnapshot` | `cards`, with the derived `operator_ids` and a `one(name)` accessor |
| `PlanningResult` | `request`, `discovery`, `candidates`, `selected`, `pipeline`, `preflight`, `data_context` |
| `PlannerRun` | `planning`, `execution` |

`PlanningResult.request` is a deep copy taken after every check has passed, so the record reports the request the plan was actually built from.

### 7.4 The generator wire schema

`plan/_schemas/plan-candidates.schema.json` is a strict JSON Schema shipped as package data and sent to the provider verbatim.
It is a package rather than a bare data directory so `importlib.resources` reads it the same way from a source tree, a source distribution, and a wheel.

The document forbids additional properties at every level and bounds every array:

| Path | Constraint |
|---|---|
| `candidates` | exactly one item |
| `candidates[].label` | string or null |
| `candidates[].steps` | 1 to 16 items |
| `steps[]` | `step_id`, `operator_id`, `attributes_json`, `depends_on`, `label`, all required |
| `steps[].attributes_json` | a string, not an object |
| `steps[].depends_on` | 0 to 15 strings |

`attributes_json` is a string because a strict schema cannot describe an open object, and attributes are open by design.
The decoder parses it and checks the result against the caller's own supplied attributes, which the model cannot drop or overwrite.

### 7.5 Scope and schema snapshot

| Type | Fields |
|---|---|
| `DataScope` | `source`, `database`, `collection`, `entities` |
| `DataContextSnapshot` | `scope`, `resolved_entities`, `payload` |

`DataScope` requires all three address parts to be non-empty, rejects duplicate entity names, and canonicalizes a non-empty `entities` tuple into sorted order.
An empty tuple means the whole collection subject to the bounds; a non-empty tuple is an exact projection, and it is planning context rather than SQL authorization.

A snapshot serializes as `blue-data-ops/data-context@1`:

```json
{
  "format": "blue-data-ops/data-context@1",
  "scope": {"source": "demo_sqlite", "database": "main", "collection": "public", "entities": []},
  "resolved_entities": ["orders"],
  "protocol": "sqlite",
  "schema": {
    "entities": [
      {
        "name": "orders",
        "description": "customer orders",
        "attributes": [
          {"name": "id", "type": "INTEGER"},
          {"name": "notes", "type": null},
          {"name": "total", "type": "REAL"}
        ]
      }
    ]
  },
  "provenance": {
    "provider": "blue-data-registry",
    "source_properties_method": "get_source_properties",
    "entity_method": "list_collection_entities",
    "attribute_method": "list_entity_attributes",
    "raw_rows": 0
  },
  "limits": {
    "max_entities": 32,
    "max_attributes_per_entity": 64,
    "max_total_attributes": 512,
    "max_description_chars": 512,
    "max_name_or_type_codepoints": 128,
    "max_serialized_bytes": 131072,
    "max_raw_rows": 0
  }
}
```

The payload's four keys — `protocol`, `schema`, `provenance`, and `limits` — are exact and exhaustive.
Entity and attribute names must be unique and sorted.
An attribute whose declared type the registry does not know is `null` rather than a substituted default.
`provenance.raw_rows` must be exactly `0`, and `provenance.provider` must be a non-empty string; a payload failing either is rejected.

A snapshot is validated against the bounds its own `limits` block declares, and the serialized-byte bound is measured on the canonical serialization of the whole document.
A snapshot that exists therefore already satisfies every limit it reports.
`entities` in the scope, when non-empty, must equal `resolved_entities` exactly.

Relations are not read at all.
`max_raw_rows` and `max_name_or_type_codepoints` are fixed rather than adapter arguments: the first is a guarantee, and the second describes the wire representation of a name.

### 7.6 PlanningErrorRecord

| Field | Type |
|---|---|
| `category` | `ErrorCategory`, the same enum operators use |
| `code` | `PlanningErrorCode`, 29 values |
| `stage` | `PlanningStage`: `VALIDATION`, `DISCOVERY`, `DATA_CONTEXT`, `GENERATION`, `SELECTION`, `COMPILATION`, `PREFLIGHT` |
| `message` | `str` |
| `retryable` | `bool` |
| `suggestion` | `str \| None` |

The record carries the same fields as an operator `ErrorRecord` apart from `operator_id`, which planning has no value for, and its `stage` is a planning stage rather than an execution stage.
It arrives on a raised `PlanningError` as `error.record`, because planning produces either a compiled pipeline or nothing, so there is no partial result to attach it to.

---

## 8. Data Flow

Component-level flow belongs to [04-detailed-architecture.md](04-detailed-architecture.md), which is the source of truth for how the packages call each other.
What follows is the record-level view: which structure becomes which.

One operator call, end to end:

```
attributes ──► declared defaults materialized ──► validation ──► transform ──► normalization
input_data ─────────────────────────────────────────────────────►
properties ─► deadline resolved ─────────────────────────────────►
                                    │              │              │
                                    └──────────────┴──────────────┴──► (output_data, output_attributes, exec_meta)
```

A failure at any stage short-circuits to `([[]], {}, exec_meta)` with one record naming that stage.

One pipeline execution:

```
input bundle ──► input node value
                      │
                      ▼
          for each operator node in topological order:
              aggregate predecessor values into one bundle
              resolve the pinned operator id
              run() ──► node value, node status, NodeRun
              stop at the first record in exec_meta.errors
                      │
                      ▼
          aggregate predecessors of the output node ──► PipelineRun.output_data
```

Predecessor aggregation extends one bundle with each predecessor's groups in predecessor order, which is how a two-input operator receives group 0 and group 1.

Properties merge in a fixed order at each node, later winning: the plan's own `properties`, then the properties passed to `execute()`, then the operator entity's `properties`.

Execution mutates node values and statuses on the plan it was handed.
`PipelinePlanner.execute()` round-trips the compiled pipeline through `to_dict()` and `from_dict()` first, so the planning result's own record stays as it was compiled.

---

## 9. Persistence

Nothing in this package owns storage.

| Structure | How it persists |
|---|---|
| Operator data | the caller's. Registry-backed operators write through the `blue-data` seam. |
| `DataPipeline` | `to_dict()` to JSON, `from_dict()` back. The caller chooses where. |
| Plan state propagation | an optional injected `sync_backend` callback taking `(path, key, value)`. The default is no callback and no propagation. |
| `OperatorRegistry` | in process only, for the lifetime of the object. Nothing is written or cached to disk. |
| Resource packages | read-only package data inside the distribution. No cache, so consecutive calls reread the index. |
| LLM responses | optional on-disk cache under `llm.cache_dir`, enabled by `llm.cache`, default `.llm_cache`. |
| Fitted ML models | not persisted. `sklearn_estimator` trains one in-memory estimator per call and discards it. |

`to_dict()` returns the live record rather than a copy, so a caller that needs an independent snapshot round-trips it through `from_dict()`.
