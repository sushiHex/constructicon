"""Owned joins preserve observations, not just an interrupted boolean."""

import asyncio

import pytest

from constructicon.substrate._lifetime import finish_owned


@pytest.mark.parametrize("fails", [False, True])
@pytest.mark.parametrize("when", ["during", "before"])
async def test_join_retains_original_cancellation_and_cleanup_failure(fails, when):
    release = asyncio.Event()
    error = RuntimeError("owned failure")

    async def work():
        await release.wait()
        if fails:
            raise error
        return 42

    owned = asyncio.create_task(work())

    async def join():
        if when == "before":
            asyncio.current_task().cancel("first cancellation")
        return await finish_owned(owned)

    owner = asyncio.create_task(join())
    await asyncio.sleep(0)
    if when == "during":
        owner.cancel("first cancellation")
    await asyncio.sleep(0)
    owner.cancel("later cancellation")
    await asyncio.sleep(0)
    assert not owner.done() and not owned.done()
    release.set()
    caught = None
    try:
        await owner
    except BaseException as exc:
        caught = exc
    if fails:
        assert isinstance(caught, BaseExceptionGroup)
        assert error in caught.exceptions
        cancellation = caught.exceptions[0]
    else:
        cancellation = caught
    assert isinstance(cancellation, asyncio.CancelledError)
    assert cancellation.args == ("first cancellation",)
    assert owned.done()


async def test_owned_task_cancellation_is_not_a_second_owner_cancellation():
    async def work():
        raise asyncio.CancelledError("owned operation")

    caught = None
    try:
        await finish_owned(asyncio.create_task(work()))
    except BaseException as exc:
        caught = exc
    assert isinstance(caught, asyncio.CancelledError)
    assert caught.args == ("owned operation",)


@pytest.mark.parametrize("delay", [False, True])
async def test_pending_owner_and_owned_cancellation_are_distinct(delay):
    async def work():
        if delay:
            await asyncio.sleep(.001)
        raise asyncio.CancelledError("owned operation")

    async def join():
        asyncio.current_task().cancel("owner")
        await finish_owned(asyncio.create_task(work()))

    caught = None
    try:
        await asyncio.create_task(join())
    except BaseException as exc:
        caught = exc
    assert isinstance(caught, BaseExceptionGroup)
    assert [error.args for error in caught.exceptions] == [("owner",), ("owned operation",)]


async def test_completed_failure_does_not_skip_pending_caller_cancellation():
    error = ValueError("completed failure")

    async def work():
        raise error

    owned = asyncio.create_task(work())
    await asyncio.wait((owned,))

    async def join():
        asyncio.current_task().cancel("owner")
        await finish_owned(owned)

    caught = None
    try:
        await asyncio.create_task(join())
    except BaseException as exc:
        caught = exc
    assert isinstance(caught, BaseExceptionGroup)
    assert caught.exceptions[0].args == ("owner",) and caught.exceptions[1] is error
