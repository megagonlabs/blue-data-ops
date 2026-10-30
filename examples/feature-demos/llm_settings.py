from __future__ import annotations

from typing import Any

from blue_data_ops.llm import LLMClient
from blue_data_ops.operators import active_registry
from blue_data_ops.plan import DataPipeline, PipelineExecutor


class RecordingClient(LLMClient):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def execute_api_call(
        self,
        input: Any,
        properties: dict[str, Any] | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> Any:
        del input, additional_data
        self.calls.append(dict(properties or {}))
        return [{"name": "example"}]


def pipeline(pipeline_properties: dict[str, Any], node_properties: dict[str, Any]) -> DataPipeline:
    plan = DataPipeline(label="LLM settings", properties=pipeline_properties)
    source = plan.define_input("records")
    generate = plan.define_operator(
        "nl2llm@3.0.0",
        attributes={"query": "Return one example product."},
        properties=node_properties,
    )
    result = plan.define_output("result")
    plan.set_plan_input(source)
    plan.set_plan_output(result)
    plan.connect_nodes(source, generate)
    plan.connect_nodes(generate, result)
    return plan


def report(label: str, properties: dict[str, Any]) -> None:
    effort = properties.get("llm.reasoning_effort")
    print(
        f"{label}: model={properties['llm.model']}, "
        f"effort={'cleared' if effort is None else effort}"
    )


def main() -> None:
    registry = active_registry()
    client = RecordingClient()
    operator = registry.resolve("nl2llm@3.0.0")
    _, _, meta = operator.run(
        [[]],
        {"query": "Return one example product."},
        {
            "llm_client": client,
            "llm.model": "direct-model",
            "llm.reasoning_effort": "low",
        },
    )
    assert not meta.errors
    report("direct", client.calls[-1])

    executor = PipelineExecutor(registry)
    invocation = {
        "llm_client": client,
        "llm.model": "call-model",
        "llm.reasoning_effort": "high",
    }
    cases: tuple[tuple[str, dict[str, Any], dict[str, Any]], ...] = (
        ("invocation", {}, {}),
        (
            "pipeline",
            {"llm.model": "pipeline-model", "llm.reasoning_effort": "medium"},
            {},
        ),
        (
            "operator",
            {"llm.model": "pipeline-model", "llm.reasoning_effort": "medium"},
            {"llm.model": "node-model", "llm.reasoning_effort": None},
        ),
    )
    for label, stored, node in cases:
        run = executor.execute(pipeline(stored, node), [[]], invocation)
        assert run.succeeded
        report(label, client.calls[-1])


if __name__ == "__main__":
    main()
