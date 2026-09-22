from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any

from _sqlite_demo import build_demo_registry

from blue_data_ops.llm import LLMClient
from blue_data_ops.operators import OperatorEmbeddingIndex, active_registry
from blue_data_ops.plan import (
    DataScope,
    DiscoveryQuery,
    OpenAIPlanGenerator,
    PipelinePlanner,
    PlannerRun,
    PlanningRequest,
    RegistryDataContextProvider,
)

DEFAULT_QUESTION = "How many orders are there?"
QUERY_OPERATOR_TAGS = ("domain-query-compound", "flow-head")


class OpenAIEmbedder:
    """Batch adapter for the embedding interface used by operator discovery."""

    def __init__(self, client: Any, model: str) -> None:
        self.space_id = f"openai:{model}"
        self.provider_calls = 0
        self._client = client
        self._model = model
        self._cache: dict[tuple[str, ...], tuple[tuple[float, ...], ...]] = {}

    def __call__(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        cached = self._cache.get(texts)
        if cached is not None:
            return cached

        response = self._client.embeddings.create(
            model=self._model,
            input=list(texts),
            encoding_format="float",
        )
        items = sorted(response.data, key=lambda item: item.index)
        vectors = tuple(tuple(float(value) for value in item.embedding) for item in items)
        self._cache[texts] = vectors
        self.provider_calls += 1
        return vectors


@dataclass(frozen=True)
class ExampleRun:
    planner_run: PlannerRun
    tag_operator_ids: tuple[str, ...]
    embedding_operator_ids: tuple[str, ...]
    model_candidate_operator_ids: tuple[str, ...]
    embedding_provider_calls: int


def _resolve_openai_client(client: Any | None) -> Any:
    if client is not None:
        return client
    try:
        import openai
    except ModuleNotFoundError:
        raise SystemExit("Install blue-data-ops[openai] before running this example.") from None
    return openai.OpenAI()


def run_example(
    question: str,
    *,
    directory: str,
    planner_model: str,
    embedding_model: str,
    nl2sql_model: str,
    openai_client: Any | None = None,
    nl2sql_client: LLMClient | None = None,
) -> ExampleRun:
    registry = active_registry()
    active_cards = tuple(registry.list_cards())
    active_ids = tuple(card.operator_id for card in active_cards)
    client = _resolve_openai_client(openai_client)
    embedder = OpenAIEmbedder(client, embedding_model)
    embedding_index = OperatorEmbeddingIndex.build(registry, embedder)

    tag_cards = embedding_index.find("", tags=QUERY_OPERATOR_TAGS)
    embedding_cards = embedding_index.find(question)

    seam = build_demo_registry(directory)
    scope = DataScope("demo_sqlite", "shop", "public")
    request = PlanningRequest(
        goal=question,
        discovery_queries=(
            DiscoveryQuery("", tags=QUERY_OPERATOR_TAGS, limit=len(active_ids)),
            DiscoveryQuery(question, limit=len(active_ids)),
        ),
        # These are trusted execution constraints if the model chooses NL2SQL. They do
        # not select it: every active operator remains allowed and discovery supplies
        # the model-visible candidates below.
        operator_attributes={
            "nl2sql": {
                "question": question,
                "source": scope.source,
                "protocol": "sqlite",
                "database": scope.database,
                "collection": scope.collection,
            }
        },
        data_scope=scope,
        allowed_operator_ids=active_ids,
        input_label="request",
        output_label="answer",
        max_discovery_cards=len(active_ids),
    )
    generator = OpenAIPlanGenerator(
        planner_model,
        registry=registry,
        allowed_operator_ids=active_ids,
        client=client,
        send_data_context=True,
    )
    planner = PipelinePlanner(
        registry,
        generator,
        data_context_provider=RegistryDataContextProvider(seam),
        embedding_index=embedding_index,
    )
    properties: dict[str, Any] = {
        "data_registry": seam,
        "execute_query": True,
        "validate_query_prefixes": ["SELECT"],
        "openai.model": nl2sql_model,
    }
    if nl2sql_client is not None:
        properties["llm_client"] = nl2sql_client

    planner_run = planner.run(request, [[]], properties)
    model_candidates = tuple(
        card.operator_id
        for card in planner_run.planning.discovery.cards
        if "produces-side-effect" not in card.tags
    )
    return ExampleRun(
        planner_run=planner_run,
        tag_operator_ids=tuple(card.operator_id for card in tag_cards),
        embedding_operator_ids=tuple(card.operator_id for card in embedding_cards),
        model_candidate_operator_ids=model_candidates,
        embedding_provider_calls=embedder.provider_calls,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Discover the active operator catalog, ask an LLM to plan, and execute "
            "the selected NL2SQL plan against a temporary SQLite database."
        )
    )
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--planner-model", default="gpt-4o")
    parser.add_argument("--embedding-model", default="text-embedding-3-small")
    parser.add_argument("--nl2sql-model", default="gpt-4o-mini")
    args = parser.parse_args()

    if "OPENAI_API_KEY" not in os.environ:
        raise SystemExit("Set OPENAI_API_KEY before running this live-provider example.")

    started = perf_counter()
    with TemporaryDirectory(prefix="blue-data-ops-") as directory:
        result = run_example(
            args.question,
            directory=directory,
            planner_model=args.planner_model,
            embedding_model=args.embedding_model,
            nl2sql_model=args.nl2sql_model,
        )
    run = result.planner_run
    elapsed_ms = (perf_counter() - started) * 1000
    selected_operator_ids = tuple(step.operator_id for step in run.planning.selected.steps)
    summary = {
        "question": args.question,
        "models": {
            "embedding": args.embedding_model,
            "planner": args.planner_model,
            "nl2sql": args.nl2sql_model,
        },
        "active_operator_ids": list(run.planning.request.allowed_operator_ids),
        "tag_discovery_operator_ids": list(result.tag_operator_ids),
        "embedding_ranking_operator_ids": list(result.embedding_operator_ids),
        "combined_discovery_operator_ids": list(run.planning.discovery.operator_ids),
        "model_candidate_operator_ids": list(result.model_candidate_operator_ids),
        "selected_steps": [
            {
                "step_id": step.step_id,
                "operator_id": step.operator_id,
                "depends_on": list(step.depends_on),
                "attributes": dict(step.attributes),
            }
            for step in run.planning.selected.steps
        ],
        "preflight_operator_ids": list(run.planning.preflight.operator_ids),
        "succeeded": run.execution.succeeded,
        "output_data": run.execution.output_data,
        "embedding_provider_calls": result.embedding_provider_calls,
        "provider_call_stages": [
            "embed active operator documents",
            "embed the user question",
            "generate the pipeline plan",
            "generate SQL inside NL2SQL",
        ],
        "elapsed_ms": round(elapsed_ms, 1),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    if "nl2sql@3.0.0" not in selected_operator_ids or not run.execution.succeeded:
        raise SystemExit("The planner did not produce a successful NL2SQL plan for this question.")


if __name__ == "__main__":
    main()
