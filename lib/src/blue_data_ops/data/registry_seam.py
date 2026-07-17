from __future__ import annotations

from typing import Any, cast

from blue_data.registry.data_registry import (  # pyright: ignore[reportMissingTypeStubs]
    DataRegistry,  # blue-data ships no py.typed
)
from blue_data.source.source import (  # pyright: ignore[reportMissingTypeStubs]
    DataSource,  # blue-data ships no py.typed
)


class RegistrySeam:
    """Compatibility facade over a blue-data DataRegistry."""

    # blue-data create methods have no per-call rebuild flag, so the seam consumes it
    # and preserves the requested indexing behavior through _emulate_rebuild.

    def __init__(self, registry: DataRegistry) -> None:
        self._registry = registry
        # The one untyped-library boundary (blue-data has no py.typed): delegate
        # through Any so unknown member types stop here, not in every caller.
        self._delegate: Any = registry

    def create_source_database(
        self,
        source: str,
        database: str,
        properties: dict[str, Any] | None = None,
        overwrite: bool = False,
        rebuild: bool = True,
        recursive: bool = False,
    ) -> Any:
        result = self._delegate.create_source_database(
            source, database, properties=properties, overwrite=overwrite, recursive=recursive
        )
        self._emulate_rebuild(rebuild)
        return result

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
    ) -> Any:
        result = self._delegate.create_source_database_collection_entity(
            source,
            database,
            collection,
            entity,
            properties=properties,
            creation_properties=creation_properties,
            overwrite=overwrite,
            recursive=recursive,
        )
        self._emulate_rebuild(rebuild)
        return result

    def set_source_database_description(
        self, source: str, database: str, description: str, rebuild: bool = False
    ) -> Any:
        return self._delegate.set_source_database_description(
            source, database, description, rebuild=rebuild
        )

    def set_source_database_collection_entity_description(
        self,
        source: str,
        database: str,
        collection: str,
        entity: str,
        description: str,
        rebuild: bool = False,
    ) -> Any:
        return self._delegate.set_source_database_collection_entity_description(
            source, database, collection, entity, description, rebuild=rebuild
        )

    def set_record_data(
        self,
        name: str,
        type: str,
        scope: str,
        key: str,
        value: Any,
        rebuild: bool | None = None,
    ) -> Any:
        return self._delegate.set_record_data(
            name, type, scope=scope, key=key, value=value, rebuild=rebuild
        )

    def get_record(self, name: str, type: str, scope: str) -> Any:
        return self._delegate.get_record(name, type, scope=scope)

    def get_source_properties(self, source: str) -> Any:
        return self._delegate.get_source_properties(source)

    def connect_source(self, source: str) -> Any:
        return self._delegate.connect_source(source)

    def register_source(self, source: DataSource) -> None:
        self._delegate.register_source(source)

    def execute_query(
        self,
        query: Any,
        source: str,
        database: str | None = None,
        collection: str | None = None,
        optional_properties: dict[str, Any] | None = {},  # noqa: B006 — public compatibility default
    ) -> Any:
        # The facade accepts (query, source, ...) while blue-data accepts
        # (source, query, ...). Keyword delegation prevents a positional swap;
        # blue-data normalizes falsy optional_properties to an empty mapping.
        return self._delegate.execute_query(
            source=source,
            query=query,
            database=database,
            collection=collection,
            optional_properties=optional_properties,
        )

    def get_data_source_schema(
        self,
        source: str,
        database: str,
        collection: str,
        protocol: str | None = None,
        format: str = "dict",  # noqa: A002 — public compatibility parameter name
    ) -> Any:
        # The facade keeps the caller-supplied `protocol` parameter for signature
        # compatibility but does not forward it: the wrapped registry derives the
        # protocol from the source's own connection properties, so the parameter
        # has no delegate-side counterpart.
        del protocol
        return self._delegate.get_data_source_schema(
            source=source,
            database=database,
            collection=collection,
            format=format,
        )

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
        # The facade keeps approximate/hybrid for signature compatibility; the
        # original consumer-side registry accepts them and never reads them (its own
        # docstring marks them not currently used), and the wrapped registry's
        # engine has no such parameters.
        del approximate, hybrid
        results = self._delegate.search_records(
            input_query, type=type, scope=scope, page=page, page_size=page_size
        )
        return [_normalize_search_result(raw) for raw in results]

    def search_records_hierarchical(
        self,
        input_query: Any,
        type: str | None = None,
        scope: str | None = None,
        page: int = 0,
        page_size: int = 5,
    ) -> list[dict[str, Any]]:
        results = self._delegate.search_records_hierarchical(
            input_query, type=type, scope=scope, page=page, page_size=page_size
        )
        return [_normalize_search_result(raw) for raw in results]

    def _emulate_rebuild(self, rebuild: bool) -> None:
        # When the wrapped registry's instance policy disables rebuilds, a true
        # per-call flag still requests immediate indexing.
        instance_rebuild = getattr(self._registry, "_rebuild", False)
        if rebuild and not instance_rebuild:
            self._delegate.build_index()


# The wrapped registry's keyword engine scores a name hit 10 and a description hit 5;
# 15 is its maximum possible raw score.
_KEYWORD_MAX_SCORE = 15.0


def _normalize_search_result(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a delegate search result to the consumer's flat search shape.

    The delegate returns one of two shapes, both ordered goodness-DESCENDING:
    the flat variant ({...record fields..., "_score": combined in [0, 1]}) from the
    hybrid engine, and the wrapped variant ({"record": {...}, "score": int}) from
    the keyword fallback. The consumer contract is a flat record with an INVERTED
    score (lower = better, ascending order — the same inversion the original
    registry applies to the same score combination): flat => 1 - _score (a missing
    _score counts as 0, the worst); wrapped => 1 - min(1, score / 15) with 15 the
    keyword engine's maximum. Normalization preserves list order, which is exactly
    consumer-ascending. Delegate records carry no id field; the id is derived with
    the delegate's own hierarchy-node convention "{scope}/{type}/{name}".
    """
    if isinstance(raw.get("record"), dict) and "score" in raw:
        record = cast("dict[str, Any]", raw["record"])
        score = 1.0 - min(1.0, float(raw.get("score", 0.0)) / _KEYWORD_MAX_SCORE)
    else:
        record = {key: value for key, value in raw.items() if not key.startswith("_")}
        score = 1.0 - float(raw.get("_score", 0.0))
    normalized: dict[str, Any] = {
        "name": record.get("name", ""),
        "type": record.get("type", ""),
        "scope": record.get("scope", "/"),
        "id": f"{record.get('scope', '/')}/{record.get('type', '')}/{record.get('name', '')}",
        "score": score,
    }
    if "description" in record:
        normalized["description"] = record["description"]
    return normalized
