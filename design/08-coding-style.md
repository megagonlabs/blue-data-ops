# blue-data-ops — Coding Style

The conventions a change to this repository is expected to follow, and which of them a tool checks.

## Tooling

| Concern | Tool | Config |
|---|---|---|
| Formatting | `ruff format` | `[tool.ruff]` in [`lib/pyproject.toml`](../lib/pyproject.toml), [`platform/ops-mcp/pyproject.toml`](../platform/ops-mcp/pyproject.toml), and [`platform/ops-cli/pyproject.toml`](../platform/ops-cli/pyproject.toml) |
| Linting and import order | `ruff check` | `[tool.ruff.lint]` in the same three files |
| Type checking | `pyright` in strict mode | `[tool.pyright]` in the same three files |
| Lint scope outside the packages | `ruff check` from the repository root | [`ruff.toml`](../ruff.toml) |

Each package configures its own rule set. The root [`ruff.toml`](../ruff.toml) adds no rules: it extends `lib/pyproject.toml` and sets `src` so that trees outside a package, chiefly `examples/`, are linted under the same configuration and `blue_data_ops` still resolves as first-party.
Test and build configuration lives in those three `pyproject.toml` files and is covered in [11-testing-strategy.md](11-testing-strategy.md) and [12-deployment-ops.md](12-deployment-ops.md).
[05-software-stack.md](05-software-stack.md) lists these same tools as part of the stack inventory, alongside where each is declared; this page owns what they enforce.

### `pyproject.toml` configuration

This is the block from [`lib/pyproject.toml`](../lib/pyproject.toml):

```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP"]

[tool.pyright]
pythonVersion = "3.12"
typeCheckingMode = "strict"
venvPath = "."
venv = ".venv"
extraPaths = ["src", "tests/stubs"]
```

The four selected rule families are pycodestyle (`E`), pyflakes (`F`), isort (`I`), and pyupgrade (`UP`).
Source formatting uses Ruff's defaults and the configured line length. The operator-reference
generator adds `--preview` when it formats `OPERATORS.md` because Ruff's Markdown formatter requires
preview mode.
`extraPaths` lets Pyright resolve the deterministic stubs that stand in for the optional heavy dependencies; [11-testing-strategy.md](11-testing-strategy.md) owns how pytest reaches the same modules.
[`platform/ops-mcp/pyproject.toml`](../platform/ops-mcp/pyproject.toml) and [`platform/ops-cli/pyproject.toml`](../platform/ops-cli/pyproject.toml) repeat the same settings; neither carries the core's stub path, and both put `../../lib/src` on `extraPaths` so the checker sees the library's real types instead of treating every import from it as unknown.

`venvPath = "."` and `venv = ".venv"` point Pyright at a `.venv` beside the `pyproject.toml` it is reading, so run it from the package directory whose environment has that package's dependencies installed.

### Per-file rule exceptions

Only `lib/pyproject.toml` carries any, and each one states its reason in the file:

| Rule | Files | Reason |
|---|---|---|
| `UP042` | `operator_skills/loader.py`, `operators/types.py`, `plan/context.py` | The public error enums keep their established `str, Enum` representation, which is part of the serialized vocabulary |
| `E501` | the eight `nl2*` and `semantic_*` operator modules | Their prompt templates are protocol text whose exact bytes reach a provider request; the line limit still applies everywhere else |

### What runs, and when

Nothing runs these automatically.
The repository has no CI configuration and no `.github/` directory, so `ruff format`, `ruff check`, `pyright`, and `pytest` are run by hand from `lib/`, from `platform/ops-mcp/`, and from `platform/ops-cli/` before a change is committed:

```bash
cd lib
ruff format .
ruff check .
pyright
python -m pytest
```

---

## Type Hints

The supported interpreters are Python 3.12 and 3.13, and each package states the floor three times: `requires-python = ">=3.12,<3.14"`, Ruff's `target-version = "py312"`, and Pyright's `pythonVersion = "3.12"`.
For the core package, `lib/tests/unit/test_readme_usage.py` reads all three values from `lib/pyproject.toml` and fails if they diverge.

Pyright strict is the real standard here, and it is stricter than a convention: every parameter and every return is annotated, private functions included, and an unannotated signature is an error rather than a style note.
Every distribution ships a `py.typed` marker, so a consumer gets those annotations.

Every module that declares an annotation opens with `from __future__ import annotations` as its first statement.
The three modules without it are two `__init__.py` re-export shims and `plan/_schemas/__init__.py`, a packaged-resource marker — none of which declares an annotation of its own.

The `UP` rules enforce current syntax, so use `X | None` rather than `Optional[X]` and builtin generics rather than their `typing` equivalents:

```python
# correct
def apply(
    self,
    input_data: DataBundle,
    attributes: Attributes,
    properties: Properties | None = None,
) -> DataBundle: ...

# incorrect
from typing import Any, Dict, List, Optional

def apply(
    self,
    input_data: List[List[Dict[str, Any]]],
    attributes: Dict[str, Any],
    properties: Optional[Dict[str, Any]] = None,
) -> List[List[Dict[str, Any]]]: ...
```

`lib/src/blue_data_ops/utils/type_utils.py` is the one module that deliberately goes the other way.
It must hand back the same `typing` objects Blue's own type parser returns, because a caller compares the returned object rather than the string that produced it, so it imports `Dict`, `List`, `Optional`, and `Union` and suppresses `UP006`, `UP007`, `UP035`, and `UP045` on the lines that use them.

Shape choices that recur:

| Need | Form |
|---|---|
| Names for the data shapes | Type aliases in `operators/types.py`: `Record`, `Data`, `DataBundle`, `Attributes`, `Properties` |
| A fixed result record | `NamedTuple`, so it unpacks positionally and stays immutable: `FunctionResult`, `ExecMeta`, `ErrorRecord`, `ValidationResult` |
| Declarative metadata | `@dataclass(frozen=True)`: `OperatorCard`, `AttributeSpec`, `DiscoverySpec` |
| Class-level declarations on an operator | `ClassVar`, so Pyright does not read them as instance fields: `name`, `description`, `attributes` |
| A caller-supplied collaborator | `Protocol` or an `ABC` with `@abstractmethod`, never a duck-typed `Any` |

At an untyped third-party boundary, narrow the value with `cast()` rather than widening the surrounding code to `Any`.
Where a type error cannot be removed, suppress it on the one line and name the rule: `# pyright: ignore[reportPrivateUsage]`, not a file-level blanket.
Lint suppressions follow the same shape and add the reason: `# noqa: UP006 - Blue identity`.

---

## Naming

| Construct | Convention | Example |
|---|---|---|
| Operator classes | PascalCase with an `Operator` suffix; acronyms stay uppercase | `SelectOperator`, `NL2SQLOperator` |
| Outcome subclasses | the same name with `Outcome` before the suffix | `AvgOutcomeOperator` |
| Operator modules | `<logical name>_operator.py`, matching the class's `name` | `select_operator.py` holds `name = "select"` |
| Outcome modules | `_<logical name>_outcome.py` | `_avg_outcome.py` |
| Exact operator IDs | `name@<MAJOR.MINOR.PATCH>`, always fully pinned | `avg@3.0.0` |
| Functions and methods | snake_case | `active_registry`, `apply_defaults` |
| Module-level constants | UPPER_SNAKE_CASE | `ACTIVE_OPERATOR_IDS`, `INDEX_BYTE_LIMIT` |
| Type aliases | PascalCase, defined beside the types they name | `Record`, `DataBundle`, `PlanRecord` |
| Private names | one leading `_`, on modules, classes, functions, and aliases alike | `_coercion.py`, `_JoinKey`, `_evaluate_condition` |
| Pipeline string constants | a `Constant` subclass carrying UPPER_SNAKE class attributes | `Status.EXECUTED`, `NodeType.OPERATOR` |
| Module loggers | a module-level `logger` from `logging.getLogger(__name__)` | `logger = logging.getLogger(__name__)` |
| Packages and modules | lowercase with underscores, never hyphens | `operator_skills/`, `registry_seam.py` |
| Keys in the `properties` mapping | a dotted lowercase namespace | `execution.timeout_seconds`, `openai.model` |
| Test modules | `test_<subject>.py`; shared test helpers take the `_` prefix | `test_registry.py`, `_semantic_test_helpers.py` |

Double-underscore name mangling appears nowhere in any of the three packages.
A single `_` marks everything private, at every level, and a module with a leading underscore is an implementation detail that the package `__init__` does not re-export.

The reverse does not hold: a name without an underscore is not automatically public.
`__all__` is the export surface, and several plainly named helpers — `apply_defaults`, `is_builtin_card` — are package-internal despite it.
When in doubt, check the `__init__.py`.

---

## Imports

- Absolute imports only inside the source packages.
  There are no relative imports under `lib/src/`, `platform/ops-mcp/src/`, or `platform/ops-cli/src/`.
  Test modules do use them, for sibling helpers within one test directory.
- `from __future__ import annotations` first, then stdlib, third-party, and first-party groups separated by blank lines.
  Ruff's `I` rules enforce the grouping and the ordering inside each group.
- No wildcard imports anywhere.
- `__all__` on every package `__init__.py` that exports a name, and on the individual modules whose export list is the point rather than an implementation detail.
  `plan/_schemas/__init__.py` is a packaged-resource marker with nothing to export and carries none.

```python
from __future__ import annotations

from typing import Any, ClassVar

from blue_data_ops.operators._discovery import DiscoverySpec
from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.types import Attributes, AttributeSpec, DataBundle, FunctionResult
```

Which group a name falls into depends on which package is importing it.
Inside `lib/`, `blue_data_ops` is first-party; inside `platform/ops-mcp/` it is an installed dependency and sorts with `mcp` and `pydantic`, while `blue_data_ops_mcp` is the first-party group, and `platform/ops-cli/` does the same with `click` and `rich`.

An optional heavy dependency is never imported at module scope.
`numpy`, `scikit-learn`, `sentence-transformers`, `litellm`, and the OpenAI SDK are reached through `importlib.import_module` inside the function that first needs one, which is why the package imports cleanly with no extra installed and why a missing extra becomes an error record rather than an `ImportError` at import time.

---

## Docstrings

One sentence, on one line, ending in a period.
Classes carry them most often, functions carry them when the name alone leaves the contract unclear, and a method implementing a documented base method inherits that contract and stays silent.

The mood follows what the thing is.
A function or a method reads as an instruction to the code — "Return one live attribute definition, if present." — while an exception class or a record type reads as a description of a state: "A pinned operator reference could not be resolved (recoverable)."

There are no `Args:`, `Returns:`, or `Raises:` sections in any of the three packages.
The signature carries the types and strict type checking keeps it complete, so a parameter list in prose would only be a second copy that can drift.
A docstring grows a second paragraph when it has to state something the signature cannot: an invariant, a lifetime, or a boundary the reader would otherwise have to discover.

```python
class ResolveError(Exception):
    """A pinned operator reference could not be resolved (recoverable)."""


def resolve_llm_client(
    properties: dict[str, Any] | None, provider: LLMClientProvider | None = None
) -> LLMClient:
    """Resolve an injected or provider-owned client, otherwise construct a fresh one.

    The default lifetime is one client per invocation, never a module-level
    singleton. An invalid injected value falls through to the next resolution path.
    """
```

Module docstrings are the exception rather than the rule, reserved for a module whose job is not obvious from its path.
Every module under `utils/` has one, because "utilities" says nothing on its own.

Docstrings mark inline code with reST double backticks and comments use single backticks; no tool checks either, so match the file you are editing.

---

## Comments

Write a comment when the *why* is not recoverable from the code: a constraint imposed from outside, an invariant a later reader could break without noticing, or a behavior kept on purpose because something downstream depends on it.
Never restate what the line does.
Most modules in this package carry no comments at all, and `select_operator.py` is a fair example — a complete operator, and nothing in it needed explaining.

```python
# correct — states the constraint that forces a late import
def _embedder_constructor() -> Callable[[str], _Embedder]:
    # The vector extra is optional; resolve it only when an embedding path is reached.
    module = import_module("sentence_transformers")
    return cast(Callable[[str], _Embedder], getattr(module, "SentenceTransformer"))


# incorrect — restates the code
def _embedder_constructor() -> Callable[[str], _Embedder]:
    # import sentence_transformers and return its SentenceTransformer class
    module = import_module("sentence_transformers")
    return cast(Callable[[str], _Embedder], getattr(module, "SentenceTransformer"))
```

Two comment shapes recur and are worth keeping.
A note at the top of a module or class states the boundary the whole file sits on, such as the one in `operators/registry.py` recording that resolution is strict and discovery is loose on purpose.
A banner separates the regions of a long class where the split is not visible from the method names, as in `llm/client.py`, which marks off its synchronous surface, its asynchronous surface, and its internals.

A suppression is a comment too, and it names the rule plus the reason rather than standing alone:

```python
from typing import Any, Dict, List, Optional, Union  # noqa: UP035 - Blue return-object identity
```

---

## Error Handling

Two vocabularies live side by side, and which one applies depends on whether there is a result to attach a failure to.

### Contained errors

`Operator.run()` is total.
Every stage — default materialization, validation, execution, normalization, and the wrapper deadline — is wrapped, and a failure comes back as output `[[]]` plus an `ErrorRecord` inside `ExecMeta.errors`.
The record carries a category, a code, the exact operator ID, the stage, a message, a retryability flag, and an optional suggestion.
`validate()` is total in the same way and returns `False` rather than raising.

The broad `except Exception` at each of those stages is deliberate, and it is the one place in the package where catching broadly is correct.
`run()` exists so that a caller can hold an operator it did not write and still get a result triple back; an exception escaping it would defeat the contract.
Outside that boundary, catch the specific type.

### Raised errors

`apply()` and `invoke()` keep the raw pre-2.0 behavior and let exceptions propagate, which is what makes them useful for a caller that wants a traceback rather than a record.
Planning raises as well: `PipelinePlanner` has no partial pipeline to hang a record on, so `PlanningError` carries the structured record on the exception itself.
That asymmetry is intentional and documented in [01-overview.md](01-overview.md).

The public exception classes:

| Exception | Defined in | Covers |
|---|---|---|
| `ResolveError` | `operators/registry.py` | a pinned operator ID that does not resolve |
| `UpgradeError` | `operators/registry.py` | a legacy reference that cannot be upgraded to a pinned ID |
| `DiscoveryError` | `operators/_discovery.py` | a built-in discovery record that violates the closed metadata contract |
| `EmbeddingDiscoveryError` | `operators/embedding_discovery.py` | a failed embedding index build or query, with a stable public reason |
| `OperatorSkillLoadError` | `operator_skills/loader.py` | a resource package that fails one of its load-boundary checks; the specific reason is an `OperatorSkillErrorCode` on the exception |
| `PlanningError` | `plan/context.py` | a planning failure, carrying a structured record on the exception |
| `PipelineError` | `plan/executor.py` | a pipeline that cannot be executed safely |
| `LLMError` | `llm/errors.py` | an LLM transport failure or a rejected adapter configuration |
| `OperatorError`, `OperatorValidationError` | `operators/types.py` | exported for callers and subclasses; the package itself raises neither today |

There is no single root above these.
`OperatorError` is the declared base for the operator errors, and the rest derive from `Exception`, `ValueError`, or another stdlib type directly, so a caller catches the specific class or the stdlib base it was chosen for.
`EmbeddingDiscoveryError` inherits from both `DiscoveryError` and `OperatorError`, so either handler catches it.

`PlanningError` is never constructed at a raise site.
`plan/context.py` defines `planning_error()` and a helper per failure mode that returns the exception already carrying its stage, code, category, retryability, and suggestion, so a raise site reads `raise invalid_request("planning request is malformed")`.
That keeps the whole code vocabulary in one file and makes a raise with no code hard to write by accident.
`planning_error()` and `invalid_request()` carry no leading underscore because `plan/planner.py` imports them across a module boundary, even though neither appears in the `blue_data_ops.plan` export list.
The module records that reasoning in a comment directly above them, which is the shape a naming exception should take.

Inside an operator body, a failure that has to travel a few frames before it becomes a record uses a private per-module signal — `_SklearnEstimatorFailure`, `_CreateTableFailure`, and their peers.
These are never exported and never reach a caller; they exist so that the conversion to an `ErrorRecord` happens in one place at the boundary rather than at every raise site.

Two parts of the error vocabulary are kept for compatibility rather than for current use.
`ErrorStage.REFINE` and the `REFINEMENT_FAILED` and `REFINEMENT_RESULT_INVALID` codes stay in the enums although 3.0 removed the refinement seam, so a record produced by an earlier release still parses.
`BlueDataOpsDeprecationWarning` stays importable for the same reason, and 3.0 emits none.
[`lib/COMPATIBILITY.md`](../lib/COMPATIBILITY.md) is the source of truth for that boundary.
