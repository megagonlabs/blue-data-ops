from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import litellm
import pytest

from blue_data_ops.llm import LLMClient
from blue_data_ops.operators import SemanticJoinOperator
from tests.unit.llm.test_client import OP_PROPS


@pytest.mark.parametrize("rate,retry", [(1, False), (2, False), (0, False), (2, True)])
def test_three_batch_join_paces_and_retries(
    rate: int, retry: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    starts: list[float] = []

    def completion(**kwargs: Any) -> dict[str, Any]:
        starts.append(time.monotonic())
        if retry and len(starts) == 2:
            raise RuntimeError("synthetic transient failure")
        time.sleep(0.02)
        prompt = " ".join(m["content"] for m in kwargs["messages"])
        size = len(re.findall(r"Pair \d+:", prompt))
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({f"pair_{i}": True for i in range(1, size + 1)})
                    }
                }
            ]
        }

    monkeypatch.setattr(litellm, "completion", completion)

    def cost(**kwargs: Any) -> float:
        return 0.0

    monkeypatch.setattr(litellm, "completion_cost", cost)
    started = time.monotonic()
    out, _, meta = SemanticJoinOperator().run(
        [[{"name": v} for v in "abc"], [{"name": v} for v in "ABC"]],
        {
            "left_fields": ["name"],
            "right_fields": ["name"],
            "join_predicate": "same name",
            "batch_size": 3,
            "estimate_cost": False,
        },
        {"llm.model": "gpt-4o-mini", "llm.rate_limit": rate, "execution.timeout_seconds": 5},
    )
    assert not meta.errors
    assert len(out[0]) == 9 and len(starts) == 3 + retry
    elapsed = time.monotonic() - started
    if rate:
        assert all(b - a >= 1 / rate - 0.005 for a, b in zip(starts, starts[1:]))
        assert elapsed >= (len(starts) - 1) / rate
    else:
        assert elapsed < 1


def test_async_pacing_keeps_heartbeat_running(monkeypatch: pytest.MonkeyPatch) -> None:
    starts: list[float] = []
    ticks: list[float] = []

    async def provider(**kwargs: Any) -> Any:
        starts.append(time.monotonic())
        await asyncio.sleep(0.01)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(litellm, "acompletion", provider)

    async def exercise() -> None:
        stop = asyncio.Event()

        async def heartbeat() -> None:
            while not stop.is_set():
                ticks.append(time.monotonic())
                await asyncio.sleep(0.02)

        client = LLMClient("test", {**OP_PROPS, "llm.rate_limit": 2})
        beat = asyncio.create_task(heartbeat())
        try:
            for _ in range(3):
                assert await client.aexecute_api_call({}) == "ok"
        finally:
            stop.set()
            await beat

    asyncio.run(exercise())
    assert len(starts) == 3 and len(ticks) > 20
    assert all(b - a >= 0.495 for a, b in zip(starts, starts[1:]))
    assert max(b - a for a, b in zip(ticks, ticks[1:])) < 0.15
