"""Deterministic litellm stand-in for offline tests (never calls a network)."""

from __future__ import annotations

from typing import Any, cast

# LiteLLM 1.98.0's own provider names, copied rather than invented: the client asks LiteLLM
# which first path segments are routes, and under this stub that question has to have the
# real answer or the dispatch gate would be measured against a fiction. Reconciled against
# the installed release by test_the_stubs_provider_names_are_litellms_own. Regenerate with:
#
#     python -c "import litellm
#     print(sorted({str(getattr(p, 'value', p)) for p in litellm.provider_list}))"
#
# `get_llm_provider` is deliberately absent. Resolution is behaviour rather than data, and a
# stand-in for it would be a stand-in for the thing under test; the client falls back to the
# provider names above when LiteLLM will not resolve, and that fallback is what this stub
# exercises.
provider_list: list[str] = [
    "a2a",
    "a2a_agent",
    "ai21",
    "ai21_chat",
    "aiml",
    "aiohttp_openai",
    "amazon_nova",
    "anthropic",
    "anthropic_text",
    "apertis",
    "assemblyai",
    "auto_router",
    "aws_polly",
    "azure",
    "azure_ai",
    "azure_text",
    "baseten",
    "bedrock",
    "bedrock_mantle",
    "black_forest_labs",
    "bytez",
    "cerebras",
    "charity_engine",
    "chatgpt",
    "chutes",
    "clarifai",
    "cloudflare",
    "codestral",
    "cohere",
    "cohere_chat",
    "cometapi",
    "compactifai",
    "cursor",
    "custom",
    "custom_openai",
    "darkbloom",
    "dashscope",
    "databricks",
    "datarobot",
    "deepgram",
    "deepinfra",
    "deepseek",
    "docker_model_runner",
    "dotprompt",
    "elevenlabs",
    "empower",
    "fal_ai",
    "featherless_ai",
    "fireworks_ai",
    "friendliai",
    "galadriel",
    "gdc",
    "gemini",
    "gigachat",
    "github",
    "github_copilot",
    "gradient_ai",
    "groq",
    "helicone",
    "heroku",
    "hosted_vllm",
    "huggingface",
    "humanloop",
    "hyperbolic",
    "inception",
    "infinity",
    "jina_ai",
    "lambda_ai",
    "langflow",
    "langfuse",
    "langgraph",
    "lemonade",
    "libertai",
    "litellm_agent",
    "litellm_proxy",
    "llamafile",
    "lm_studio",
    "manus",
    "maritalk",
    "meta",
    "meta_llama",
    "milvus",
    "minimax",
    "mistral",
    "modelscope",
    "moonshot",
    "morph",
    "nano-gpt",
    "nebius",
    "neosantara",
    "nlp_cloud",
    "novita",
    "nscale",
    "nvidia_nim",
    "nvidia_riva",
    "oci",
    "ollama",
    "ollama_chat",
    "oobabooga",
    "openai",
    "openai_like",
    "openrouter",
    "ovhcloud",
    "parasail",
    "perplexity",
    "petals",
    "pg_vector",
    "pinstripes",
    "poe",
    "predibase",
    "publicai",
    "ragflow",
    "recraft",
    "reducto",
    "replicate",
    "runwayml",
    "s3_vectors",
    "sagemaker",
    "sagemaker_chat",
    "sagemaker_nova",
    "sambanova",
    "sap",
    "scaleway",
    "snowflake",
    "soniox",
    "stability",
    "synthetic",
    "tencent",
    "tensormesh",
    "text-completion-codestral",
    "text-completion-inception",
    "text-completion-openai",
    "together_ai",
    "topaz",
    "triton",
    "v0",
    "vercel_ai_gateway",
    "vertex_ai",
    "vertex_ai_beta",
    "vllm",
    "volcengine",
    "voyage",
    "wandb",
    "watsonx",
    "watsonx_text",
    "xai",
    "xiaomi_mimo",
    "xinference",
    "zai",
]


calls: list[dict[str, Any]] = []
fail_next: list[Exception] = []  # tests push exceptions to simulate provider failures


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def model_dump(self) -> dict[str, Any]:
        return self._payload


def completion(**kwargs: Any) -> _Response:
    calls.append(kwargs)
    if fail_next:
        raise fail_next.pop(0)
    prompt = ""
    messages: list[Any] = kwargs.get("messages") or []
    if messages and isinstance(messages[0], dict):
        first = cast("dict[str, Any]", messages[0])
        prompt = str(first.get("content", ""))
    return _Response(
        {
            "choices": [{"message": {"role": "assistant", "content": f"echo:{prompt}"}}],
            "usage": {"prompt_tokens": len(prompt.split()), "completion_tokens": 3},
            "model": kwargs.get("model"),
        }
    )


def completion_cost(completion_response: Any) -> float:
    return 0.000123


inflight = {"now": 0, "max": 0}


async def acompletion(**kwargs: Any) -> _Response:
    import asyncio

    inflight["now"] += 1
    inflight["max"] = max(inflight["max"], inflight["now"])
    try:
        await asyncio.sleep(0.02)
        return completion(**kwargs)
    finally:
        inflight["now"] -= 1
