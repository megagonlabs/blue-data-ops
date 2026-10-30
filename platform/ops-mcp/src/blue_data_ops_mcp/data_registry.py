from __future__ import annotations

import asyncio
import contextvars
import functools
from collections.abc import Callable
from typing import Any, cast

from blue_data.registry.data_registry import (  # pyright: ignore[reportMissingTypeStubs]
    DataRegistry,
)
from blue_data_ops.data.config import build_environment_registry
from blue_data_ops.data.errors import RegistryFailure, RegistryReason
from blue_data_ops.data.registry_seam import RegistrySeam
from blue_data_ops.operators._execution_fallback import run_body
from blue_data_ops.operators.operator import (
    Operator,
    _execution_error,  # pyright: ignore[reportPrivateUsage]
    _InvalidTimeout,  # pyright: ignore[reportPrivateUsage]
    _timeout_seconds,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.types import (
    ErrorCategory,
    ErrorCode,
    ErrorRecord,
    ErrorStage,
    ExecMeta,
)

_DEADLINE = "execution.timeout_seconds"


def failure_result(operator: Operator, error: BaseException) -> Any:
    return [[]], {}, ExecMeta(False, [_execution_error(operator.operator_id, error)], [], {})


def timeout_result(operator: Operator) -> Any:
    """The record core's own deadline returns, so a caller cannot tell the two apart."""
    error = ErrorRecord(
        category=ErrorCategory.TIMEOUT,
        code=ErrorCode.OPERATOR_TIMEOUT,
        operator_id=operator.operator_id,
        stage=ErrorStage.EXECUTE,
        message="operator timed out",
        retryable=False,
        suggestion=None,
    )
    return [[]], {}, ExecMeta(False, [error], [], {})


def _start_worker(work: Callable[[], Any]) -> asyncio.Future[Any]:
    # What asyncio.to_thread does, minus the task: a plain future is never cancelled by
    # loop shutdown, so it cannot report done while its thread is still running.
    loop = asyncio.get_running_loop()
    context = contextvars.copy_context()
    return loop.run_in_executor(None, functools.partial(context.run, work))


class DeploymentRegistry:
    def __init__(self, data_registry: RegistrySeam | DataRegistry | None = None) -> None:
        candidate = cast(object, data_registry)
        if candidate is not None and not isinstance(candidate, (RegistrySeam, DataRegistry)):
            raise TypeError("data_registry must be a RegistrySeam or DataRegistry")
        self.seam = (
            RegistrySeam(data_registry)
            if isinstance(data_registry, DataRegistry)
            else data_registry
        )
        self.state = "READY" if self.seam is not None else "UNINITIALIZED"
        self._admission = asyncio.Lock()
        self._workers: set[asyncio.Task[Any]] = set()
        # Workers whose caller has gone, by deadline or cancellation. Each one holds
        # admission until its thread really finishes, and this set keeps it alive.
        self._draining: set[asyncio.Future[Any]] = set()

    def _resolve(self) -> RegistrySeam:
        if self.state == "UNINITIALIZED":
            try:
                self.seam = build_environment_registry(require_configuration=True)
                self.state = "MISSING" if self.seam is None else "READY"
            except Exception:
                self.state = "FAILED"
        if self.state == "MISSING":
            raise RegistryFailure(RegistryReason.NOT_CONFIGURED)
        if self.state == "FAILED":
            raise RegistryFailure(RegistryReason.CONFIGURATION_FAILED)
        assert self.seam is not None
        return self.seam

    async def run(
        self,
        operator: Operator,
        input_data: Any,
        attributes: dict[str, Any],
        properties: dict[str, Any] | None,
        *,
        bound_execution: bool = False,
    ) -> Any:
        await self._admission.acquire()
        # The task owns admission after scheduling. Shielding keeps it running when the
        # client stops awaiting the result.
        task = asyncio.create_task(
            self._run_admitted(operator, input_data, attributes, properties, bound_execution)
        )
        self._workers.add(task)
        task.add_done_callback(self._workers.discard)
        return await asyncio.shield(task)

    async def _run_admitted(
        self,
        operator: Operator,
        input_data: Any,
        attributes: dict[str, Any],
        properties: dict[str, Any] | None,
        bound_execution: bool,
    ) -> Any:
        handed_off = False

        async def in_worker(work: Callable[[], Any], timeout: float | None) -> Any:
            """Run work in a thread; return its outcome, or None once it has been handed off."""
            nonlocal handed_off
            worker = _start_worker(work)
            try:
                await asyncio.wait({worker}, timeout=timeout)
            finally:
                if not worker.done():
                    # The deadline expired or this task was cancelled. Admission moves
                    # to the worker before its callback is registered.
                    handed_off = True
                    self._drain(worker)
                elif not worker.cancelled():
                    worker.exception()  # retrieved here too if this task was cancelled
            if handed_off:
                return None
            # Done, even if the wait also reported expiry: a finished worker's result or
            # exception is the answer. A TimeoutError it raised is its own, not a deadline.
            return worker.result()

        try:
            if not bound_execution and self.state in {"MISSING", "FAILED"}:
                reason = (
                    RegistryReason.NOT_CONFIGURED
                    if self.state == "MISSING"
                    else RegistryReason.CONFIGURATION_FAILED
                )
                return failure_result(operator, RegistryFailure(reason))

            call_properties = dict(properties or {})
            if not bound_execution:
                # Initial construction stays outside the deadline.
                def resolve() -> RegistrySeam | RegistryFailure:
                    try:
                        return self._resolve()
                    except RegistryFailure as error:
                        return error

                seam = await in_worker(resolve, None)
                if handed_off:
                    return None
                if isinstance(seam, RegistryFailure):
                    return failure_result(operator, seam)
                for key in ("data_registry", "platform.name", "data_registry.name"):
                    call_properties.pop(key, None)
                call_properties["data_registry"] = seam

            try:
                timeout = _timeout_seconds(call_properties)
            except _InvalidTimeout:
                # Leave the value in place: core reports its own validation error.
                timeout = None
            else:
                # This lane owns a valid deadline, so core must not start a second worker.
                call_properties.pop(_DEADLINE, None)

            result = await in_worker(
                lambda: run_body(operator, input_data, attributes, call_properties), timeout
            )
            return timeout_result(operator) if handed_off else result
        finally:
            if not handed_off:
                self._admission.release()

    def _drain(self, worker: asyncio.Future[Any]) -> None:
        self._draining.add(worker)
        worker.add_done_callback(self._finish_drain)

    def _finish_drain(self, worker: asyncio.Future[Any]) -> None:
        try:
            if not worker.cancelled():
                # Retrieve a late failure so it is not reported as never retrieved.
                worker.exception()
        finally:
            self._draining.discard(worker)
            self._admission.release()
