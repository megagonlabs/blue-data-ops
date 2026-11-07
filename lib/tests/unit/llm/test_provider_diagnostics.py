from __future__ import annotations

import builtins
import importlib
import json
import subprocess
import sys
from typing import Any

import pytest

from blue_data_ops.llm.client import _provider_error  # pyright: ignore[reportPrivateUsage]
from blue_data_ops.operators import Operator
from blue_data_ops.operators.types import Attributes, DataBundle, Properties

MARKER = "SYNTHETIC_PRIVATE_PROVIDER_DETAIL"


class Raising(Operator):
    name = "provider_diagnostic"
    description = "Local genuine provider exception fixture."
    attributes = {}

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    def apply(
        self, input_data: DataBundle, attributes: Attributes, properties: Properties | None = None
    ) -> DataBundle:
        raise self.error


def _attach_retry_evidence(error: Any, name: str) -> None:
    import httpx
    import openai

    if name == "APIConnectionError":
        error.__cause__ = httpx.ConnectError(MARKER)
    elif name == "Timeout":
        error.__cause__ = httpx.ReadTimeout(MARKER)
    elif name in {"RateLimitError", "ServiceUnavailableError", "InternalServerError"}:
        status = 429 if name == "RateLimitError" else 503
        response = httpx.Response(status, request=httpx.Request("POST", "https://unit.invalid"))
        cls = openai.RateLimitError if status == 429 else openai.InternalServerError
        error.__cause__ = cls(MARKER, response=response, body=None)


@pytest.mark.parametrize(
    "name,message,retryable",
    [
        ("ContextWindowExceededError", "model request exceeds the context window", False),
        ("ContentPolicyViolationError", "model provider refused the request content", False),
        ("RateLimitError", "model provider rate limit reached", True),
        ("Timeout", "model provider timed out", True),
        ("APIConnectionError", "model provider connection failed", True),
        ("ServiceUnavailableError", "model provider is temporarily unavailable", True),
        ("InternalServerError", "model provider is temporarily unavailable", True),
    ],
)
def test_genuine_loaded_provider(name: str, message: str, retryable: bool) -> None:
    if __name__ != "__main__":
        from tests.optional_integrations import require_optional

        require_optional("litellm")
        result = subprocess.run(
            [sys.executable, "-B", __file__, "genuine", name, message, str(retryable)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return
    module = importlib.import_module("litellm")
    assert module.__file__ and "site-packages/litellm/" in module.__file__
    cls: Any = vars(module)[name]
    error = cls(message=MARKER, model="synthetic", llm_provider="openai")
    _attach_retry_evidence(error, name)
    owned = _provider_error(error, module.UnsupportedParamsError, module.BadRequestError)
    record = Raising(owned).run([[]], {})[2].errors[0]
    assert record.message == message and record.retryable is retryable
    assert record.suggestion and MARKER not in json.dumps(record._asdict())


@pytest.mark.parametrize("status", [400, 401, 404, 429, 500])
def test_foreign_status_lookalike_generic(status: int) -> None:
    if __name__ != "__main__":
        from tests.optional_integrations import require_optional

        require_optional("litellm")
        result = subprocess.run(
            [sys.executable, "-B", __file__, "foreign", str(status)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return
    module = importlib.import_module("litellm")
    cls = type("RateLimitError", (Exception,), {"__module__": "litellm", "status_code": status})
    owned = _provider_error(cls(MARKER), module.UnsupportedParamsError, module.BadRequestError)
    record = Raising(owned).run([[]], {})[2].errors[0]
    assert record.message == "model provider request failed"
    assert record.retryable is False


def test_unrelated_failure_does_not_import_optional_classifiers() -> None:
    if __name__ != "__main__":
        result = subprocess.run(
            [sys.executable, "-B", __file__, "sentinel"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return
    prefixes = ("litellm", "psycopg2", "mysql.connector")
    for name in list(sys.modules):
        if any(name == p or name.startswith(p + ".") for p in prefixes):
            del sys.modules[name]
    original = builtins.__import__
    seen: list[str] = []

    def guarded(name: str, *args: Any, **kwargs: Any) -> Any:
        if any(name == p or name.startswith(p + ".") for p in prefixes):
            seen.append(name)
            raise AssertionError("diagnostic classifier attempted optional import")
        return original(name, *args, **kwargs)

    builtins.__import__ = guarded
    try:
        record = Raising(ValueError(MARKER)).run([[]], {})[2].errors[0]
        assert record.message == "operator execution failed" and not seen
    finally:
        builtins.__import__ = original


if __name__ == "__main__":
    if sys.argv[1] == "genuine":
        test_genuine_loaded_provider(sys.argv[2], sys.argv[3], sys.argv[4] == "True")
    elif sys.argv[1] == "sentinel":
        test_unrelated_failure_does_not_import_optional_classifiers()
    else:
        test_foreign_status_lookalike_generic(int(sys.argv[2]))
