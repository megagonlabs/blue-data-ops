from __future__ import annotations

from typing import Any, cast

from blue_data_ops.operators.types import Attributes, Properties
from blue_data_ops.plan import DataPipeline, Node, PlanRecord

_CREATE_DATABASE = "create_database@1.0.0"
_CREATE_TABLE = "create_table@1.0.0"
_DATA_DISCOVER = "data_discover@1.0.0"
_INSERT_TABLE = "insert_table@1.0.0"
_NL2QUERY_ROUTER = "nl2query_router@1.0.0"
_NL2SQL = "nl2sql@1.0.0"


def build_multipart_pipelines(
    plans: Any,
    serialize: Any,
    properties: Properties | None,
) -> list[PlanRecord]:
    """Build the shared multipart-query graph used by both plan operators."""
    pipelines: list[PlanRecord] = []

    for plan in cast(list[list[dict[str, Any]]], plans):
        pipeline = DataPipeline(properties=properties)
        ctes = plan
        failed = False

        input_node = pipeline.define_input(value=None)
        output_node = pipeline.define_output(properties={})
        pipeline.set_plan_input(input_node)
        pipeline.set_plan_output(output_node)

        cte_start_nodes: dict[Any, Node] = {}
        cte_end_nodes: dict[Any, Node] = {}
        dependents: set[Any] = set()

        db_name = "db_" + pipeline.get_id()
        create_database_node = pipeline.define_operator(
            _CREATE_DATABASE,
            attributes={"source": "internal", "database": db_name},
            properties={},
        )
        pipeline.connect_nodes(input_node, create_database_node)
        cte_root_node = create_database_node

        for cte in ctes:
            description = cte["description"] if "description" in cte else None
            sql = cte["sql"] if "sql" in cte else None
            table = cte["table"] if "table" in cte else None
            columns = cte["columns"] if "columns" in cte else None
            dependency = cte["dependency"] if "dependency" in cte else None
            generality = cte["generality"] if "generality" in cte else 0

            if (
                description is None
                or sql is None
                or table is None
                or columns is None
                or dependency is None
            ):
                failed = True
                break

            dependency = cast(list[Any], dependency)

            if len(dependency) > 0:
                create_table_node = pipeline.define_operator(
                    _CREATE_TABLE,
                    attributes={
                        "source": "internal",
                        "database": db_name,
                        "table": table,
                        "columns": columns,
                    },
                    properties={},
                )
                attr_names = [column["name"] for column in columns]
                nl2sql_node = pipeline.define_operator(
                    _NL2SQL,
                    attributes={
                        "question": description,
                        "protocol": "sqlite",
                        "source": "internal",
                        "database": db_name,
                        "collection": "public",
                        "attr_names": attr_names,
                        "execute_query": True,
                    },
                    properties={},
                )
                insert_table_node = pipeline.define_operator(
                    _INSERT_TABLE,
                    attributes={"source": "internal", "database": db_name, "table": table},
                    properties={},
                )
                start_node = create_table_node
                end_node = insert_table_node
                pipeline.connect_nodes(create_table_node, nl2sql_node)
                pipeline.connect_nodes(nl2sql_node, insert_table_node)
            else:
                data_discovery_attributes: Attributes = {
                    "search_query": description,
                    "approximate": True,
                    "concept_type": "source",
                    "limit": 1,
                    "filter_names": ["internal"],
                    "use_hierarchical_search": False,
                }
                if generality >= 5:
                    data_discovery_attributes["search_query"] = "general knowledge"
                data_discovery_node = pipeline.define_operator(
                    _DATA_DISCOVER,
                    attributes=data_discovery_attributes,
                    properties={},
                )
                create_table_node = pipeline.define_operator(
                    _CREATE_TABLE,
                    attributes={
                        "source": "internal",
                        "database": db_name,
                        "table": table,
                        "columns": columns,
                    },
                    properties={},
                )
                nl2query_router_node = pipeline.define_operator(
                    _NL2QUERY_ROUTER,
                    attributes={
                        "search_query": description,
                        "execute_query": True,
                        "columns": columns,
                    },
                    properties={},
                )
                insert_table_node = pipeline.define_operator(
                    _INSERT_TABLE,
                    attributes={"source": "internal", "database": db_name, "table": table},
                    properties={},
                )
                start_node = data_discovery_node
                end_node = insert_table_node
                pipeline.connect_nodes(data_discovery_node, create_table_node)
                pipeline.connect_nodes(create_table_node, nl2query_router_node)
                pipeline.connect_nodes(nl2query_router_node, insert_table_node)

            dependents.add(table)
            cte_start_nodes[table] = start_node
            cte_end_nodes[table] = end_node
            for dependency_name in dependency:
                dependents.remove(dependency_name)

        if failed:
            continue

        if serialize:
            last_end_node = cte_root_node
            cte_queue: list[Any] = []
            cte_dict: dict[Any, dict[str, Any]] = {}
            for cte in ctes:
                table = cte["table"] if "table" in cte else None
                cte_queue.append(table)
                cte_dict[table] = cte

            processed_ctes: list[Any] = []
            while len(cte_queue) > 0:
                table = cte_queue.pop(0)
                cte = cte_dict[table]
                dependency = cast(list[Any], cte["dependency"] if "dependency" in cte else [])
                dependent = False
                for dependency_name in dependency:
                    if dependency_name not in processed_ctes:
                        dependent = True
                if dependent:
                    cte_queue.append(table)

                start_node = cte_start_nodes[table]
                end_node = cte_end_nodes[table]
                pipeline.connect_nodes(last_end_node, start_node)
                last_end_node = end_node
                processed_ctes.append(table)

            pipeline.connect_nodes(last_end_node, output_node)
        else:
            for cte in ctes:
                table = cte["table"] if "table" in cte else None
                dependency = cast(list[Any], cte["dependency"] if "dependency" in cte else [])
                start_node = cte_start_nodes[table]

                if len(dependency) == 0:
                    pipeline.connect_nodes(cte_root_node, start_node)
                else:
                    for dependency_name in dependency:
                        if dependency_name in cte_end_nodes:
                            pipeline.connect_nodes(
                                cte_end_nodes[dependency_name],
                                start_node,
                            )
                        else:
                            failed = True
                            break

                for dependent_name in dependents:
                    pipeline.connect_nodes(cte_end_nodes[dependent_name], output_node)

        pipelines.append(pipeline.to_dict())

    return pipelines


__all__ = ["build_multipart_pipelines"]
