"""Small in-process background runner for console jobs."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from typing import Any


_ACTIVE_JOBS: dict[str, int] = {}
_CANCEL_REQUESTS: set[str] = set()
_LOCK = threading.Lock()


class JobCancelled(Exception):
    """Raised when a console job receives a user cancellation request."""


@contextmanager
def active_job(job_id: str) -> Iterator[None]:
    with _LOCK:
        _ACTIVE_JOBS[job_id] = _ACTIVE_JOBS.get(job_id, 0) + 1
    try:
        yield
    finally:
        _release_active_job(job_id)


def start_async_job(
    job_id: str,
    worker: Callable[[str], Awaitable[Any]],
    on_error: Callable[[str, Exception], None] | None = None,
) -> bool:
    with _LOCK:
        if job_id in _ACTIVE_JOBS:
            return False
        _CANCEL_REQUESTS.discard(job_id)
        _ACTIVE_JOBS[job_id] = 1

    def run() -> None:
        try:
            asyncio.run(worker(job_id))
        except Exception as exc:
            print(f"Background console job {job_id} failed: {exc}")
            if on_error:
                on_error(job_id, exc)
        finally:
            _release_active_job(job_id)

    thread = threading.Thread(target=run, name=f"console-job-{job_id}", daemon=True)
    thread.start()
    return True


def is_active(job_id: str) -> bool:
    with _LOCK:
        return job_id in _ACTIVE_JOBS


def request_cancel(job_id: str) -> bool:
    with _LOCK:
        if job_id not in _ACTIVE_JOBS:
            return False
        _CANCEL_REQUESTS.add(job_id)
        return True


def cancel_requested(job_id: str) -> bool:
    with _LOCK:
        return job_id in _CANCEL_REQUESTS


def raise_if_cancelled(job_id: str) -> None:
    if cancel_requested(job_id):
        raise JobCancelled("任务已取消")


def _release_active_job(job_id: str) -> None:
    with _LOCK:
        count = _ACTIVE_JOBS.get(job_id, 0) - 1
        if count > 0:
            _ACTIVE_JOBS[job_id] = count
        else:
            _ACTIVE_JOBS.pop(job_id, None)
            _CANCEL_REQUESTS.discard(job_id)
