"""Deterministic litellm stand-in for offline tests (never calls a network)."""

from __future__ import annotations

from typing import Any, cast

# Reviewed provider names from LiteLLM 1.98.0. The client checks model prefixes and the
# deployment provider against this list. Tests allow installed names covered by this list
# or the separate 1.102.0 and 1.106.5 additions, then select exactly the installed names.
# Regenerate with:
#
#     python -c "import litellm
#     print(sorted({str(getattr(p, 'value', p)) for p in litellm.provider_list}))"
#
# `get_llm_provider` is deliberately absent. Resolution is behavior rather than data. The
# client still checks model prefixes against the provider names below when the resolver is absent.
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

provider_additions_1102: tuple[str, ...] = (
    "cognition",
    "mongodb",
    "qwen_ai_platform",
    "qwencloud",
    "scx-ai",
    "valkey",
)

# Reviewed additions derived independently from both installed 1.106.5 provider lists.
provider_additions_11065: tuple[str, ...] = (
    "aws_textract",
    "azure_speech",
    "cortecs",
    "edenai",
    "nadir",
    "prism",
    "reka",
    "sail",
    "strands_decider",
    "transcribe",
    "typesafe",
)


calls: list[dict[str, Any]] = []
fail_next: list[Exception] = []  # tests push exceptions to simulate provider failures


class BadRequestError(Exception):
    """A provider rejected a request after LiteLLM sent it."""

    def __init__(self, message: str, *, body: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.body = body


class UnsupportedParamsError(BadRequestError):
    """The provider adapter rejected an explicit generation parameter."""


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
