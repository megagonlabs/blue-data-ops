from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

POLL_INTERVAL = 0.05
_IDLE = threading.Event()


class ScopeExpired(TimeoutError):
    pass


@dataclass
class ExecutionScope:
    deadline: float | None
    parent: ExecutionScope | None = None
    stop: threading.Event = field(default_factory=threading.Event)

    def check(self) -> None:
        if self.parent is not None:
            self.parent.check()
        if self.stop.is_set() or (self.deadline is not None and time.monotonic() >= self.deadline):
            raise ScopeExpired

    def remaining(self) -> float | None:
        self.check()
        return None if self.deadline is None else max(0.0, self.deadline - time.monotonic())


_CURRENT: ContextVar[ExecutionScope | None] = ContextVar(
    "blue_data_ops_execution_scope", default=None
)


def create(timeout: float | None) -> ExecutionScope:
    parent = _CURRENT.get()
    deadline = None if timeout is None else time.monotonic() + timeout
    if parent is not None and parent.deadline is not None:
        deadline = parent.deadline if deadline is None else min(deadline, parent.deadline)
    return ExecutionScope(deadline, parent)


@contextmanager
def activate(scope: ExecutionScope) -> Generator[None]:
    token = _CURRENT.set(scope)
    try:
        check()
        yield
    finally:
        _CURRENT.reset(token)


def remaining() -> float | None:
    scope = _CURRENT.get()
    return None if scope is None else scope.remaining()


def check() -> None:
    scope = _CURRENT.get()
    if scope is not None:
        scope.check()


def _wait_slice(until: float) -> float:
    scope = _CURRENT.get()
    remaining = None if scope is None else scope.remaining()
    delay = min(POLL_INTERVAL, max(0.0, until - time.monotonic()))
    return delay if remaining is None else min(delay, remaining)


def wait_sync(seconds: float) -> None:
    until = time.monotonic() + seconds
    scope = _CURRENT.get()
    event = _IDLE if scope is None else scope.stop
    while True:
        delay = _wait_slice(until)
        if delay <= 0:
            check()
            return
        event.wait(delay)


async def wait_async(seconds: float) -> None:
    until = time.monotonic() + seconds
    while True:
        delay = _wait_slice(until)
        if delay <= 0:
            check()
            return
        await asyncio.sleep(delay)
