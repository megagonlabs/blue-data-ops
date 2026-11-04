from __future__ import annotations

from collections.abc import Callable, Generator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event, Thread, current_thread
from time import monotonic
from typing import Any

import pytest

from blue_data_ops import _execution_scope as scope


@contextmanager
def blocked_worker(monkeypatch: pytest.MonkeyPatch) -> Generator[Callable[[], None], None, None]:
    entered = Event()
    release = Event()
    workers: list[Thread] = []
    original_submit = ThreadPoolExecutor.submit
    original_create = scope.create
    pending: list[tuple[scope.ExecutionScope, float]] = []

    def create_after_entry(timeout: float | None) -> scope.ExecutionScope:
        current = original_create(None)
        if timeout is not None:
            pending.append((current, timeout))
        return current

    def submit_after_entry[T](
        executor: ThreadPoolExecutor,
        fn: Callable[..., T],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future[T]:
        future = original_submit(executor, fn, *args, **kwargs)
        assert entered.wait(timeout=5), "timeout worker did not enter the body"
        for current, timeout in pending:
            current.deadline = monotonic() + timeout
        return future

    def body() -> None:
        workers.append(current_thread())
        entered.set()
        assert release.wait(timeout=5), "timeout worker was not released"

    # Start both deadlines after body entry; queue expiry has separate coverage.
    with monkeypatch.context() as scoped:
        scoped.setattr(scope, "create", create_after_entry)
        scoped.setattr(ThreadPoolExecutor, "submit", submit_after_entry)
        try:
            yield body
        finally:
            release.set()
            for worker in workers:
                worker.join(timeout=5)
                assert not worker.is_alive(), "timeout worker did not finish"
