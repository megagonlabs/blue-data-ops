"""In-memory doubles for the data seam.

`RegistrySeamDouble` implements the seam's surface and records every call so operator
test suites can assert their boundary interactions offline.
`SQLSourceDouble` stands in for the returned-SQL-source protocol
(`_db_connect → cursor → executemany/commit/rowcount → _db_disconnect`).
"""

from __future__ import annotations

from typing import Any


class CursorDouble:
    def __init__(self) -> None:
        self.executed: list[tuple[str, list[Any]]] = []
        self.rowcount = -1

    def executemany(self, query: str, rows: list[Any]) -> None:
        self.executed.append((query, rows))
        # sqlite3 semantics: rowcount reflects the LAST executemany, not a running total
        self.rowcount = len(rows)


class ConnectionDouble:
    def __init__(self) -> None:
        self.cursor_double = CursorDouble()
        self.commits = 0

    def cursor(self) -> CursorDouble:
        return self.cursor_double

    def commit(self) -> None:
        self.commits += 1


class SQLSourceDouble:
    def __init__(self, name: str, properties: dict[str, Any] | None = None) -> None:
        self.name = name
        self.properties = properties or {}
        self.connections: dict[str, ConnectionDouble] = {}
        self.connect_calls: list[str] = []
        self.disconnects = 0

    def _db_connect(self, database: str) -> ConnectionDouble:
        self.connect_calls.append(database)
        connection = self.connections.get(database)
        if connection is None:
            connection = ConnectionDouble()
            self.connections[database] = connection
        return connection

    def _db_disconnect(self, connection: ConnectionDouble | None) -> None:
        self.disconnects += 1


class RegistrySeamDouble:
    """Call-recording double for the RegistrySeam surface."""

    def __init__(self, source_properties: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.records: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.record_data: dict[tuple[str, str, str, str], Any] = {}
        self.sources: dict[str, Any] = {}
        self._source_properties = source_properties or {}
        # Configurable returns for the query/schema surface (set by tests as needed).
        self.query_result: Any = None
        self.schema_result: Any = {"entities": [], "relations": []}
        # Per-page search results (consumer shape); missing pages return [].
        self.search_pages: dict[int, list[dict[str, Any]]] = {}

    def _log(self, method: str, **kwargs: Any) -> None:
        self.calls.append((method, kwargs))

    def calls_to(self, method: str) -> list[dict[str, Any]]:
        return [kwargs for name, kwargs in self.calls if name == method]

    def create_source_database(
        self,
        source: str,
        database: str,
        properties: dict[str, Any] | None = None,
        overwrite: bool = False,
        rebuild: bool = True,
        recursive: bool = False,
    ) -> None:
        self._log(
            "create_source_database",
            source=source,
            database=database,
            properties=properties,
            overwrite=overwrite,
            rebuild=rebuild,
            recursive=recursive,
        )
        self.records[(database, "database", f"/source/{source}")] = {"name": database}

    def create_source_database_collection_entity(
        self,
        source: str,
        database: str,
        collection: str,
        entity: str,
        properties: dict[str, Any] | None = None,
        creation_properties: dict[str, Any] | None = None,
        overwrite: bool = False,
        rebuild: bool = True,
        recursive: bool = False,
    ) -> None:
        self._log(
            "create_source_database_collection_entity",
            source=source,
            database=database,
            collection=collection,
            entity=entity,
            properties=properties,
            creation_properties=creation_properties,
            overwrite=overwrite,
            rebuild=rebuild,
            recursive=recursive,
        )
        scope = f"/source/{source}/database/{database}/collection/{collection}"
        self.records[(entity, "entity", scope)] = {"name": entity}

    def set_source_database_description(
        self, source: str, database: str, description: str, rebuild: bool = False
    ) -> None:
        self._log(
            "set_source_database_description",
            source=source,
            database=database,
            description=description,
            rebuild=rebuild,
        )

    def set_source_database_collection_entity_description(
        self,
        source: str,
        database: str,
        collection: str,
        entity: str,
        description: str,
        rebuild: bool = False,
    ) -> None:
        self._log(
            "set_source_database_collection_entity_description",
            source=source,
            database=database,
            collection=collection,
            entity=entity,
            description=description,
            rebuild=rebuild,
        )

    def set_record_data(
        self, name: str, type: str, scope: str, key: str, value: Any, rebuild: bool | None = None
    ) -> None:
        self._log(
            "set_record_data",
            name=name,
            type=type,
            scope=scope,
            key=key,
            value=value,
            rebuild=rebuild,
        )
        self.record_data[(name, type, scope, key)] = value

    def get_record(self, name: str, type: str, scope: str) -> dict[str, Any] | None:
        self._log("get_record", name=name, type=type, scope=scope)
        return self.records.get((name, type, scope))

    def get_source_properties(self, source: str) -> dict[str, Any]:
        self._log("get_source_properties", source=source)
        return self._source_properties

    def connect_source(self, source: str) -> Any:
        self._log("connect_source", source=source)
        return self.sources.get(source)

    def register_source(self, source: Any) -> None:
        self._log("register_source", source=source)
        self.sources[source.name] = source

    def execute_query(
        self,
        query: Any,
        source: str,
        database: str | None = None,
        collection: str | None = None,
        optional_properties: dict[str, Any] | None = {},  # noqa: B006 — mirrors the seam default
    ) -> Any:
        self._log(
            "execute_query",
            query=query,
            source=source,
            database=database,
            collection=collection,
            optional_properties=optional_properties,
        )
        return self.query_result

    def search_records(
        self,
        input_query: Any,
        type: str | None = None,
        scope: str | None = None,
        approximate: bool = False,
        hybrid: bool = False,
        page: int = 0,
        page_size: int = 5,
    ) -> list[dict[str, Any]]:
        self._log(
            "search_records",
            input_query=input_query,
            type=type,
            scope=scope,
            approximate=approximate,
            hybrid=hybrid,
            page=page,
            page_size=page_size,
        )
        return self.search_pages.get(page, [])

    def search_records_hierarchical(
        self,
        input_query: Any,
        type: str | None = None,
        scope: str | None = None,
        page: int = 0,
        page_size: int = 5,
    ) -> list[dict[str, Any]]:
        self._log(
            "search_records_hierarchical",
            input_query=input_query,
            type=type,
            scope=scope,
            page=page,
            page_size=page_size,
        )
        return self.search_pages.get(page, [])

    def get_data_source_schema(
        self,
        source: str,
        database: str,
        collection: str,
        protocol: str | None = None,
        format: str = "dict",  # noqa: A002 — mirrors the seam surface
    ) -> Any:
        self._log(
            "get_data_source_schema",
            source=source,
            database=database,
            collection=collection,
            protocol=protocol,
            format=format,
        )
        return self.schema_result
