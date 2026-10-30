from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, cast

from blue_data_ops.data.sql_errors import query_schema_failure
from blue_data_ops.data.sql_types import is_data_registry, sql_source_base
from blue_data_ops.llm.errors import LLMError, sql_schema_failure

SQL_REGISTRY_SELECTORS = frozenset({"data_registry", "platform.name", "data_registry.name"})
SQL_CALLER_POLICY_VALIDATION = {
    "execute_query": "boolean-host-capability",
    "validate_query_prefixes": "ascii-select-list",
    "read_only_executor": "reserved",
    **{key: "denied-for-execution" for key in SQL_REGISTRY_SELECTORS},
}
_MESSAGES = {
    "sql_policy_invalid": "invalid SQL execution policy",
    "sql_execution_unavailable": "read-only SQL execution is not configured",
    "sql_target_denied": "SQL target is outside the configured execution scope",
    "sql_query_rejected": "generated SQL does not satisfy the read-only query contract",
    "sql_execution_failed": "read-only SQL execution failed",
    "sql_schema_failed": "generated SQL failed against the approved schema",
}
_BACKENDS = {
    "blue_data.source.sql.sqlite.sqlite_sql_source": "SQLiteDBSource",
    "blue_data.source.sql.postgres.postgres_sql_source": "PostgresDBSource",
    "blue_data.source.sql.mysql.mysql_sql_source": "MySQLDBSource",
}
_GUARDED_METHODS = frozenset(
    {
        "execute_query",
        "_set_read_only",
        "_db_connect",
        "_db_disconnect",
        "_is_multi_statement",
        "_is_read_only_error",
        "_read_only_authorizer",
    }
)


def sql_error(code: str) -> LLMError:
    if code == "sql_schema_failed":
        return sql_schema_failure()
    return LLMError(_MESSAGES[code], code=code, retryable=False)


def _validate_source(source: Any) -> None:
    base: Any = sql_source_base()
    cls = cast(Any, type(source))
    name = _BACKENDS.get(cls.__module__)
    module = sys.modules.get(cls.__module__)
    hook = cls.__dict__.get("_set_read_only")
    if (
        name is None
        or module is None
        or cls is not getattr(module, name, None)
        or not issubclass(cls, base)
        or not callable(hook)
        or hook is base._set_read_only
        or cls.execute_query is not base.execute_query
        or _GUARDED_METHODS.intersection(cast(dict[str, Any], vars(source)))
    ):
        raise sql_error("sql_execution_unavailable")


@dataclass(frozen=True, init=False)
class ReadOnlySQLExecutor:
    """Bind registered sources and exact (source, database, collection) targets.

    Configure this in trusted host code with an existing DataRegistry. The adapter
    supports the inspected blue-data SQL guards only. Connections open before the
    guard runs; use pre-existing targets and constrained database principals.
    """

    _registry: Any
    _bindings: tuple[tuple[tuple[str, str, str], Any], ...]

    def __init__(self, registry: Any, targets: frozenset[tuple[str, str, str]]) -> None:
        if not is_data_registry(registry) or type(targets) is not frozenset or not targets:
            raise sql_error("sql_policy_invalid")
        bindings: list[tuple[tuple[str, str, str], Any]] = []
        for target in targets:
            if (
                type(target) is not tuple
                or len(target) != 3
                or any(type(part) is not str or not part or "*" in part for part in target)
            ):
                raise sql_error("sql_policy_invalid")
            source = registry.get_source(target[0])
            if source is None:
                raise sql_error("sql_target_denied")
            _validate_source(source)
            bindings.append((target, source))
        object.__setattr__(self, "_registry", registry)
        object.__setattr__(self, "_bindings", tuple(bindings))

    def _source(self, target: tuple[str, str, str]) -> Any:
        for bound, source in self._bindings:
            if target == bound:
                if self._registry.get_source(target[0]) is not source:
                    raise sql_error("sql_target_denied")
                _validate_source(source)
                return source
        raise sql_error("sql_target_denied")

    def preflight(self, target: tuple[str, str, str]) -> None:
        """Validate the binding without connecting or reading schema."""
        self._source(target)

    def get_schema(self, target: tuple[str, str, str]) -> Any:
        self.preflight(target)
        try:
            return self._registry.get_data_source_schema(*target)
        except Exception:
            raise sql_error("sql_execution_failed") from None

    def execute(self, query: str, target: tuple[str, str, str]) -> Any:
        source = self._source(target)
        try:
            return source.execute_query(
                query,
                database=target[1],
                collection=target[2],
                optional_properties={"commit": False},
            )
        except Exception as error:
            code = "sql_schema_failed" if query_schema_failure(error) else "sql_execution_failed"
        raise sql_error(code) from None
