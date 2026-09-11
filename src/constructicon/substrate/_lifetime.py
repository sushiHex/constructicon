"""Finish owned work before propagating cancellation; preserve cleanup failure."""

from __future__ import annotations

import asyncio
from typing import TypeVar

_T = TypeVar("_T")


async def finish_owned(task: asyncio.Task[_T]) -> _T:
    interrupted: asyncio.CancelledError | None = None
    while True:
        try:
            # Waiting for completion never propagates the owned task's error
            # or cancellation and never cancels it. This checkpoint also
            # observes a pending caller cancellation when work is already done.
            await asyncio.wait((task,))
        except asyncio.CancelledError as exc:
            interrupted = interrupted or exc
        if task.done():
            break
    try:
        result = task.result()
    except BaseException as exc:
        if interrupted is not None:
            raise BaseExceptionGroup(
                "owned cleanup failed after cancellation", [interrupted, exc],
            ) from None
        raise
    if interrupted is not None:
        raise interrupted
    return result
