"""Finish owned work before propagating cancellation; preserve cleanup failure."""

from __future__ import annotations

import asyncio
from typing import TypeVar

_T = TypeVar("_T")


async def finish_owned(task: asyncio.Task[_T]) -> _T:
    interrupted = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            interrupted = True
    result = task.result()
    if interrupted:
        raise asyncio.CancelledError
    return result
