from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

MARKER = "SYNTHETIC_PRIVATE_PROVIDER_PROVENANCE"


@pytest.mark.parametrize(
    "case",
    [
        "chains",
        "mapper",
        "retries",
        "surfaces-negative",
        "surfaces-positive",
        "http-429",
        "http-503",
        "http-connect",
        "http-timeout",
        "http-parse-key",
        "http-parse-type",
        "http-parse-value",
    ],
)
def test_provider_provenance(case: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLUE_DATA_OPS_HOME", str(tmp_path / "profiles"))
    result = subprocess.run(
        [sys.executable, *(["-S"] if sys.flags.no_site else []), "-B", __file__, case],
        env={**os.environ, "BLUE_DATA_OPS_HOME": str(tmp_path / "profiles")},
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def modules() -> tuple[Any, Any, Any]:
    import httpx
    import litellm
    import openai

    assert litellm.__file__ and "site-packages/litellm/" in litellm.__file__
    cast(Any, litellm).suppress_debug_info = True
    return litellm, openai, httpx


def wrapped(name: str, cause: BaseException | None = None) -> Exception:
    lite, _, _ = modules()
    error = getattr(lite, name)(message=MARKER, model="gpt-4o", llm_provider="openai")
    error.__cause__ = cause
    return error


def owned(error: Exception) -> Any:
    from blue_data_ops.llm import client

    _provider_error = cast(Any, client)._provider_error
    lite, _, _ = modules()
    return _provider_error(error, lite.UnsupportedParamsError, lite.BadRequestError)


def record(error: Exception) -> Any:
    from blue_data_ops.operators import operator

    _execution_error = cast(Any, operator)._execution_error
    return _execution_error("probe@3.0.0", owned(error))


def check(error: Exception, code: str = "provider_error") -> None:
    value = owned(error)
    assert value.code == code, (type(error), value.code, code)
    public = record(error)
    assert public.retryable is (
        code
        in {
            "provider_connection",
            "provider_timeout",
            "provider_rate_limit",
            "provider_unavailable",
        }
    )
    assert MARKER not in str(public)
    assert public.code == "EXECUTION_FAILED" and public.stage == "EXECUTE"


def chain_cases() -> None:
    lite, sdk, http = modules()
    request = http.Request("POST", "https://provider.invalid")
    net = http.ConnectError(MARKER, request=request)
    timeout = http.ReadTimeout(MARKER, request=request)
    sdk_connection = sdk.APIConnectionError(request=request)
    sdk_connection.__cause__ = net
    check(wrapped("APIConnectionError", sdk_connection), "provider_connection")
    check(wrapped("Timeout", timeout), "provider_timeout")
    for name in ("APIConnectionError", "Timeout", "RateLimitError", "ServiceUnavailableError"):
        check(wrapped(name))
        for local in (KeyError(MARKER), TypeError(MARKER), ValueError(MARKER)):
            middle = sdk.APIConnectionError(request=request)
            middle.__cause__ = local
            check(wrapped(name, middle))
    for local in (
        http.LocalProtocolError(MARKER),
        http.UnsupportedProtocol(MARKER),
        http.TransportError(MARKER),
        RuntimeError(MARKER),
    ):
        local.__cause__ = net
        check(wrapped("APIConnectionError", local))
    check(wrapped("Timeout", net))
    check(wrapped("APIConnectionError", timeout))
    check(wrapped("RateLimitError", net))
    for status in (429, 500, 502, 503, 504, 400, 501):
        origin = sdk.APIStatusError(
            MARKER,
            response=http.Response(status, request=request),
            body={"private": MARKER},
        )
        for name in ("RateLimitError", "ServiceUnavailableError"):
            expected = "provider_error"
            if name == "RateLimitError" and status == 429:
                expected = "provider_rate_limit"
            if name == "ServiceUnavailableError" and status in {500, 502, 503, 504}:
                expected = "provider_unavailable"
            check(wrapped(name, origin), expected)
    from importlib import import_module

    OpenAIError = cast(Any, import_module("litellm.llms.openai.common_utils")).OpenAIError

    synthetic = OpenAIError(status_code=503, message=MARKER)
    check(wrapped("ServiceUnavailableError", synthetic))
    synthetic.__cause__ = KeyError(MARKER)
    check(wrapped("ServiceUnavailableError", synthetic))
    first = wrapped("APIConnectionError")
    first.__cause__ = first
    check(first)
    second = wrapped("APIConnectionError", first)
    first.__cause__ = second
    check(second)
    for wrappers, expected in ((7, "provider_connection"), (8, "provider_error")):
        node: Exception = net
        for _ in range(wrappers):
            node = wrapped("APIConnectionError", node)
        check(node, expected)
    effective = wrapped("APIConnectionError", net)
    effective.__context__ = ValueError(MARKER)
    check(effective, "provider_connection")
    context = wrapped("APIConnectionError")
    context.__context__ = net
    context.__suppress_context__ = False
    check(context, "provider_connection")
    context.__suppress_context__ = True
    check(context)
    net.__cause__ = KeyError(MARKER)
    check(wrapped("APIConnectionError", net), "provider_connection")

    class Spoof(Exception):
        @cast(Any, property)
        def __class__(self) -> type:
            return lite.APIConnectionError

    fake = Spoof(MARKER)
    fake.__cause__ = net
    check(fake)
    fake_name = type("APIConnectionError", (Exception,), {"__module__": "litellm.exceptions"})
    check(fake_name(MARKER))

    class Hostile(lite.APIConnectionError):
        def __getattribute__(self, name: str) -> Any:
            if name in {"__cause__", "__context__", "__suppress_context__", "status_code"}:
                raise AssertionError("subclass accessor read")
            return cast(object, super()).__getattribute__(name)

    hostile = Hostile(message=MARKER, model="gpt-4o", llm_provider="openai")
    hostile.__cause__ = net
    check(hostile, "provider_connection")

    class HostileStatus(sdk.APIStatusError):
        @property
        def response(self) -> Any:
            raise AssertionError("response descriptor read")

        @response.setter
        def response(self, value: Any) -> None:
            self.__dict__["response"] = value

    origin = HostileStatus(MARKER, response=http.Response(503, request=request), body=None)
    check(wrapped("ServiceUnavailableError", origin), "provider_unavailable")
    origin.__dict__["response"] = type("Response", (), {"status_code": 503})()
    check(wrapped("ServiceUnavailableError", origin))
    check(sdk.APIConnectionError(request=request))
    check(timeout)
    check(sdk.RateLimitError(MARKER, response=http.Response(429, request=request), body=None))

    class HostileString(lite.APIConnectionError):
        def __str__(self) -> str:
            raise TypeError(MARKER)

    from blue_data_ops.operators import Operator

    hostile_string = HostileString(message=MARKER, model="gpt-4o", llm_provider="openai")

    class ConversionFailure(Operator):
        name = "provider_conversion_failure"
        description = "Provider conversion test."
        attributes = {}

        def apply(self, input_data: Any, attributes: Any, properties: Any = None) -> Any:
            raise owned(hostile_string)

    _, _, meta = ConversionFailure().run([[]], {})
    assert meta.errors[0].message == "operator execution failed"
    assert MARKER not in str(meta)


def mapper_cases() -> None:
    from importlib import import_module

    exception_type = cast(
        Any, import_module("litellm.litellm_core_utils.exception_mapping_utils")
    ).exception_type

    for error in (
        KeyError(MARKER),
        ValueError("Request timed out " + MARKER),
        ValueError("rate limit " + MARKER),
    ):
        for active in (False, True):

            def mapped() -> Exception:
                try:
                    exception_type(
                        model="gpt-4o",
                        custom_llm_provider="openai",
                        original_exception=error,
                        completion_kwargs={},
                        extra_kwargs={},
                    )
                except Exception as result:
                    return result
                raise AssertionError("mapper returned")

            if active:
                try:
                    raise error
                except Exception:
                    result = mapped()
            else:
                result = mapped()
            check(result)


def stack_error(case: str) -> Exception:
    lite, sdk, http = modules()
    from unittest.mock import patch

    calls: list[str] = []

    def handler(request: Any) -> Any:
        calls.append("http")
        assert not request.headers.get("Authorization")
        if case == "connect":
            raise http.ConnectError(MARKER, request=request)
        if case == "timeout":
            raise http.ReadTimeout(MARKER, request=request)
        if case in {"429", "503"}:
            return http.Response(int(case), json={"error": {"message": MARKER}}, request=request)
        return http.Response(200, json={"choices": [], "model": "gpt-4o"}, request=request)

    # The credential callback returns no key; MockTransport handles every request in memory.
    with http.Client(transport=http.MockTransport(handler)) as transport:
        with sdk.OpenAI(
            api_key=lambda: "",
            default_headers={"Authorization": ""},
            http_client=transport,
            max_retries=0,
        ) as client:
            from contextlib import ExitStack

            with ExitStack() as patches:
                if case.startswith("parse-"):
                    errors = {
                        "parse-key": KeyError,
                        "parse-type": TypeError,
                        "parse-value": ValueError,
                    }
                    from importlib import import_module

                    parser = import_module("litellm.llms.openai.openai")
                    patches.enter_context(
                        patch.object(
                            parser,
                            "convert_to_model_response_object",
                            side_effect=errors[case](MARKER),
                        )
                    )
                try:
                    lite.completion(
                        model="gpt-4o",
                        messages=[{"role": "user", "content": "ordinary"}],
                        custom_llm_provider="openai",
                        client=client,
                        num_retries=0,
                    )
                except Exception as error:
                    assert calls == ["http"], calls
                    return error
    raise AssertionError("mocked failure succeeded")


def retry_cases() -> None:
    from unittest.mock import patch

    from blue_data_ops.llm import LLMClient
    from blue_data_ops.llm.errors import LLMError

    lite, _, _ = modules()
    for name in ("APIConnectionError", "Timeout", "RateLimitError", "ServiceUnavailableError"):
        with patch.object(lite, "completion", side_effect=wrapped(name, KeyError(MARKER))) as call:
            with pytest.raises(LLMError) as captured:
                cast(Any, LLMClient("openai"))._call_provider({"model": "gpt-4o"})
            assert call.call_count == 3
            assert captured.value.retryable is True
            assert captured.value.code == "provider_error"
        from blue_data_ops.operators import active_registry

        operator = active_registry().resolve("semantic_filter@3.0.0")
        with patch.object(lite, "completion", side_effect=wrapped(name, KeyError(MARKER))) as call:
            _, _, meta = operator.run(
                [[{"value": MARKER}]],
                {"filter_conditions": {"value": "keep"}},
                {"llm_client": LLMClient("openai"), "llm.model": "gpt-4o"},
            )
            assert call.call_count == 3
            assert meta.errors[0].message == "model provider request failed"
            assert meta.errors[0].retryable is False
            assert MARKER not in str(meta)


async def surface_cases(positive: bool) -> None:
    from tempfile import TemporaryDirectory
    from unittest.mock import patch

    from blue_data_ops_cli import config
    from blue_data_ops_cli.commands import cli
    from blue_data_ops_mcp.server import create_server
    from click.testing import CliRunner
    from mcp.shared.memory import create_connected_server_and_client_session

    from blue_data_ops.operators import Operator, OperatorRegistry
    from blue_data_ops.plan import DataPipeline, PipelineExecutor

    error = owned(stack_error("429" if positive else "parse-key"))

    class Failure(Operator):
        name = "provider_provenance"
        description = "Provider diagnostic test."
        attributes = {}

        def apply(self, input_data: Any, attributes: Any, properties: Any = None) -> Any:
            raise error

    logs = io.StringIO()
    log_handler = logging.StreamHandler(logs)
    logger = logging.getLogger()
    logger.addHandler(log_handler)
    operator = Failure()
    registry = OperatorRegistry()
    registry.register(operator, "2.0.0")
    _, _, meta = operator.run([[{"private": MARKER}]], {})
    expected = meta.errors[0]._asdict()
    assert expected["retryable"] is positive
    assert expected["message"] == (
        "model provider rate limit reached" if positive else "model provider request failed"
    )
    assert expected["code"] == "EXECUTION_FAILED" and expected["stage"] == "EXECUTE"
    assert expected["category"] == "FAILED"
    plan = DataPipeline(id="provider-provenance")
    entry = plan.define_input("input")
    step = plan.define_operator(operator.operator_id, label="step", attributes={})
    output = plan.define_output("output")
    plan.set_plan_input(entry)
    plan.set_plan_output(output)
    plan.connect_nodes(entry, step)
    plan.connect_nodes(step, output)
    spec = json.loads(json.dumps(plan.to_dict()))
    run = PipelineExecutor(registry).execute(plan, [[{"private": MARKER}]])
    assert run.node_runs[0].exec_meta.errors[0]._asdict() == expected
    assert MARKER not in str(meta) + str(run.node_runs[0].exec_meta)
    with TemporaryDirectory() as folder:
        path = Path(folder)
        input_file = path / "input.json"
        input_file.write_text(json.dumps([[{"private": MARKER}]]))
        plan_file = path / "plan.json"
        plan_file.write_text(json.dumps(spec))
        with patch.object(config, "build_catalog", return_value=registry):
            runner = CliRunner()
            pipeline_name = "provider-positive" if positive else "provider-negative"
            imported = runner.invoke(
                cli,
                [
                    "pipeline",
                    "import",
                    pipeline_name,
                    "--pipeline-file",
                    str(plan_file),
                    "--format",
                    "json",
                ],
            )
            assert imported.exit_code == 0, imported.output
            surfaces = (("operator", operator.operator_id), ("pipeline", pipeline_name))
            for component, identity in surfaces:
                result = runner.invoke(
                    cli,
                    [
                        component,
                        "run",
                        identity,
                        "--input-file",
                        str(input_file),
                        "--format",
                        "json",
                        "--log",
                    ],
                )
                assert result.exit_code == 8, result.output
                detail = json.loads(result.stdout)["error"]["detail"]
                assert detail["retryable"] is positive
                assert detail["library_code"] == "EXECUTION_FAILED"
                assert detail["stage"] == "EXECUTE"
                assert MARKER not in result.stdout + result.stderr
                assert folder not in result.stdout + result.stderr
    server = create_server(registry=registry, operator_ids=(operator.operator_id,))
    async with create_connected_server_and_client_session(server) as client:
        wire = await client.call_tool(
            "ops_provider_provenance",
            {"input_data": [[{"private": MARKER}]]},
        )
    assert wire.isError is False
    assert cast(dict[str, Any], wire.structuredContent)["exec_meta"]["errors"][0] == expected
    assert MARKER not in wire.model_dump_json()
    logger.removeHandler(log_handler)
    assert MARKER not in logs.getvalue()


if __name__ == "__main__":
    case = sys.argv[1]
    if case == "chains":
        chain_cases()
    elif case == "mapper":
        mapper_cases()
    elif case == "retries":
        retry_cases()
    elif case.startswith("surfaces-"):
        asyncio.run(surface_cases(case == "surfaces-positive"))
    else:
        expected = {
            "http-429": "provider_rate_limit",
            "http-503": "provider_unavailable",
            "http-connect": "provider_error",
            "http-timeout": "provider_timeout",
        }.get(case, "provider_error")
        check(stack_error(case.removeprefix("http-")), expected)
