"""Finish owned work before propagating cancellation; preserve cleanup failure."""

from __future__ import annotations

import asyncio
from typing import TypeVar

_T = TypeVar("_T")


async def finish_owned(task: asyncio.Task[_T]) -> _T:
    owner = asyncio.current_task()
    assert owner is not None
    cancellations = owner.cancelling()
    interrupted: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            if not task.cancelled() or owner.cancelling() > cancellations:
                interrupted = interrupted or exc
                cancellations = owner.cancelling()
        except BaseException:
            break  # Retrieve the owned failure once, retaining cancellation too.
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
