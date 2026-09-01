from __future__ import annotations

from tempfile import TemporaryDirectory

from _sqlite_demo import build_demo_registry

from blue_data_ops import CreateDatabaseOperator, DataDiscoverOperator, InsertTableOperator


def main() -> None:
    with TemporaryDirectory(prefix="blue-data-ops-") as directory:
        seam = build_demo_registry(directory)
        rows = seam.execute_query(
            "SELECT id, region, total FROM orders ORDER BY id",
            "demo_sqlite",
            "shop",
            "public",
        )
        assert len(rows) == 10

        _, _, create_meta = CreateDatabaseOperator().run(
            [[]],
            {"source": "demo_sqlite", "database": "scratch"},
            {"data_registry": seam},
        )

        inserted, _, insert_meta = InsertTableOperator().run(
            [[{"id": 11, "region": "north", "total": 275.0}]],
            {"source": "demo_sqlite", "database": "shop", "table": "orders"},
            {"data_registry": seam},
        )
        discovered, _, discover_meta = DataDiscoverOperator().run(
            [[]],
            {
                "search_query": "orders",
                "approximate": False,
                "concept_type": "entity",
            },
            {"data_registry": seam},
        )

        assert inserted == [[{"id": 11, "region": "north", "total": 275.0}]]
        assert create_meta.errors == []
        assert insert_meta.errors == []
        assert discover_meta.errors == []
        assert any(record["name"] == "orders" for record in discovered[0])
        print("rows before insert:", len(rows))
        print("registry match:", discovered[0][0]["name"])


if __name__ == "__main__":
    main()
