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

    with pytest.raises(asyncio.CancelledError) as caught:
        await finish_owned(asyncio.create_task(work()))
    assert caught.value.args == ("owned operation",)
