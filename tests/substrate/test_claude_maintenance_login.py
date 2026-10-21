"""Credential-free tests for the attended-login byte conversation only."""

from __future__ import annotations

import asyncio
from dataclasses import asdict

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.substrate.executors import claude_maintenance_login as login


class NativeIO:
    def __init__(self) -> None:
        self.output: asyncio.Queue[bytes] = asyncio.Queue()
        self.writes: list[bytes] = []
        self.closed = False
        self.write_entered = asyncio.Event()
        self.write_release = asyncio.Event()
        self.pause_write = False
        self.active_reads = 0
        self.read_cancelled = False
        self.write_cancelled = False

    async def read(self, maximum: int = 8192) -> bytes:
        assert maximum == 8192
        self.active_reads += 1
        try:
            return await self.output.get()
        except asyncio.CancelledError:
            self.read_cancelled = True
            raise
        finally:
            self.active_reads -= 1

    async def write(self, data: bytes) -> None:
        self.writes.append(data)
        self.write_entered.set()
        try:
            if self.pause_write:
                await self.write_release.wait()
        except asyncio.CancelledError:
            self.write_cancelled = True
            raise

    async def close_stdin(self) -> None:
        self.closed = True


class PrivateIO:
    def __init__(self) -> None:
        self.line: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
        self.output: list[bytes] = []
        self.output_seen = asyncio.Event()
        self.output_release = asyncio.Event()
        self.pause_output = False
        self.invalidated = False
        self.active_reads = 0
        self.read_cancelled = False

    async def read_line(self) -> bytes:
        self.active_reads += 1
        try:
            return await self.line
        except asyncio.CancelledError:
            self.read_cancelled = True
            raise
        finally:
            self.active_reads -= 1

    async def write_stdout(self, data: bytes) -> None:
        self.output.append(data)
        self.output_seen.set()
        if self.pause_output:
            await self.output_release.wait()

    def invalidate(self) -> None:
        self.invalidated = True


def conversation(private: PrivateIO, *, seconds: float = 5) -> login.ClaudeLoginConversation:
    return login.ClaudeLoginConversation(
        private, deadline=asyncio.get_running_loop().time() + seconds,
    )


async def cancel_and_join(task: asyncio.Task[None]) -> None:
    if not task.done():
        task.cancel()
    done, _ = await asyncio.wait({task}, timeout=1)
    assert task in done, "test cleanup must join the callback"
    if not task.cancelled():
        task.exception()  # Consume a refusal without publishing its text.


async def test_prompt_then_one_line_and_native_eof_completes_only_conversation():
    native, private = NativeIO(), PrivateIO()
    callback = conversation(private)
    task = asyncio.create_task(callback(native))
    native.output.put_nowait(b"private vendor prompt")
    forwarded = asyncio.create_task(private.output_seen.wait())
    try:
        done, _ = await asyncio.wait({forwarded}, timeout=0.25)
        assert forwarded in done, "native stdout must reach the private operator"
    finally:
        forwarded.cancel()
        await asyncio.gather(forwarded, return_exceptions=True)
        if not private.output_seen.is_set():
            await cancel_and_join(task)
    assert native.writes == []  # Prompt readiness is an operator procedure, not a parser.
    private.line.set_result(b"opaque response\n")
    await asyncio.wait_for(native.write_entered.wait(), 1)
    native.output.put_nowait(b"private completion")
    native.output.put_nowait(b"")
    await asyncio.wait_for(task, 1)
    assert native.writes == [b"opaque response\n"] and native.closed
    assert private.output == [b"private vendor prompt", b"private completion"]
    assert not private.invalidated and private.active_reads == native.active_reads == 0
    assert asdict(callback.facts) == {
        "lifecycle": login.ClaudeLoginConversationLifecycle.COMPLETED,
        "input_write_attempted": True, "stdin_closed": True,
        "stdout_eof": True, "stdout_bytes": len(b"private vendor promptprivate completion"),
    }


async def test_exact_4096_byte_line_is_one_permitted_opaque_attempt():
    native, private = NativeIO(), PrivateIO()
    callback = conversation(private)
    task = asyncio.create_task(callback(native))
    native.output.put_nowait(b"private prompt")
    await asyncio.wait_for(private.output_seen.wait(), 1)
    line = b"x" * 4095 + b"\n"
    private.line.set_result(line)
    await asyncio.wait_for(native.write_entered.wait(), 1)
    native.output.put_nowait(b"")
    await asyncio.wait_for(task, 1)
    assert native.writes == [line] and callback.facts.input_write_attempted


async def test_native_eof_before_line_cancels_operator_read_without_write():
    native, private = NativeIO(), PrivateIO()
    callback = conversation(private)
    task = asyncio.create_task(callback(native))
    native.output.put_nowait(b"")
    with pytest.raises(login.LoginConversationRefused):
        await asyncio.wait_for(task, 1)
    assert native.writes == [] and not native.closed
    assert private.read_cancelled and private.active_reads == native.active_reads == 0
    assert callback.facts.stdout_eof and not callback.facts.input_write_attempted


async def test_eof_and_line_ready_together_prioritize_eof():
    native, private = NativeIO(), PrivateIO()
    private.line.set_result(b"opaque\n")
    native.output.put_nowait(b"")
    callback = conversation(private)
    with pytest.raises(login.LoginConversationRefused):
        await callback(native)
    assert native.writes == [] and callback.facts.stdout_eof


async def test_eof_during_uncertain_write_cancels_and_never_retries():
    native, private = NativeIO(), PrivateIO()
    native.pause_write = True
    callback = conversation(private)
    task = asyncio.create_task(callback(native))
    private.line.set_result(b"opaque\n")
    await asyncio.wait_for(native.write_entered.wait(), 1)
    native.output.put_nowait(b"")
    with pytest.raises(login.LoginConversationRefused):
        await asyncio.wait_for(task, 1)
    assert native.writes == [b"opaque\n"] and native.write_cancelled
    assert not native.closed and callback.facts.input_write_attempted
    assert callback.facts.stdout_eof and native.active_reads == private.active_reads == 0


async def test_scheduled_write_audits_already_completed_stdout_eof_before_spend():
    native, private = NativeIO(), PrivateIO()
    callback = conversation(private)
    callback._state = login.ClaudeLoginConversationLifecycle.RUNNING
    pump = asyncio.create_task(asyncio.sleep(0))
    await pump
    with pytest.raises(login.LoginConversationRefused):
        await callback._write_line(native, b"opaque\n", pump)
    assert native.writes == [] and not callback.facts.input_write_attempted


async def test_eof_scheduled_between_precheck_and_write_task_wins_in_full_callback():
    native, private = NativeIO(), PrivateIO()

    class OrderedConversation(login.ClaudeLoginConversation):
        def _own(self, coroutine):
            if len(self._tasks) == 2:  # Just before the one write task is scheduled.
                native.output.put_nowait(b"")
            return super()._own(coroutine)

    callback = OrderedConversation(private, deadline=asyncio.get_running_loop().time() + 5)
    private.line.set_result(b"opaque\n")
    with pytest.raises(login.LoginConversationRefused):
        await asyncio.wait_for(callback(native), 1)
    assert callback.facts.stdout_eof and not callback.facts.input_write_attempted
    assert native.writes == [] and native.active_reads == private.active_reads == 0


@pytest.mark.parametrize("line", [b"", b"partial", b"two\nlines\n", b"x" * 4096 + b"\n",
                                       bytearray(b"opaque\n")])
async def test_malicious_or_unbounded_operator_line_is_refused_before_write(line):
    native, private = NativeIO(), PrivateIO()
    private.line.set_result(line)
    callback = conversation(private)
    task = asyncio.create_task(callback(native))
    try:
        done, _ = await asyncio.wait({task}, timeout=0.25)
        assert task in done, "invalid operator input must refuse without a native wait"
        assert native.writes == [] and not callback.facts.input_write_attempted
        with pytest.raises(login.LoginConversationRefused):
            await task
    finally:
        await cancel_and_join(task)


@pytest.mark.parametrize("chunk", [bytearray(b"bad"), b"x" * 8193])
async def test_malicious_native_chunk_refuses_before_private_forward(chunk):
    native, private = NativeIO(), PrivateIO()
    native.output.put_nowait(chunk)
    callback = conversation(private)
    task = asyncio.create_task(callback(native))
    try:
        done, _ = await asyncio.wait({task}, timeout=0.25)
        assert private.output == [] and native.writes == []
        assert task in done, "invalid native chunks must refuse promptly"
        with pytest.raises(login.LoginConversationRefused):
            await task
    finally:
        await cancel_and_join(task)


async def test_cumulative_stdout_ceiling_binds_on_next_byte():
    native, private = NativeIO(), PrivateIO()
    native.output.put_nowait(b"x" * 8192)
    callback = conversation(private)
    task = asyncio.create_task(callback(native))
    for _ in range(31):
        native.output.put_nowait(b"x" * 8192)
    native.output.put_nowait(b"x")
    try:
        done, _ = await asyncio.wait({task}, timeout=0.25)
        assert task in done, "the extra byte must terminate the conversation promptly"
        assert sum(map(len, private.output)) == 256 * 1024
        assert callback.facts.stdout_bytes == 256 * 1024
        with pytest.raises(login.LoginConversationRefused):
            await task
    finally:
        await cancel_and_join(task)


async def test_external_cancel_joins_blocked_private_output_and_line():
    native, private = NativeIO(), PrivateIO()
    private.pause_output = True
    callback = conversation(private)
    task = asyncio.create_task(callback(native))
    native.output.put_nowait(b"private prompt")
    await asyncio.wait_for(private.output_seen.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert private.invalidated and private.read_cancelled
    assert private.active_reads == native.active_reads == 0
    assert callback.facts.lifecycle is login.ClaudeLoginConversationLifecycle.REFUSED


async def test_cancel_waits_for_owned_reader_cleanup_without_new_io_deadline():
    class SlowCancelPrivate(PrivateIO):
        def __init__(self) -> None:
            super().__init__()
            self.cancel_entered = asyncio.Event()
            self.release = asyncio.Event()
            self.read_finished = asyncio.Event()

        async def read_line(self) -> bytes:
            self.active_reads += 1
            try:
                return await self.line
            except asyncio.CancelledError:
                self.read_cancelled = True
                self.cancel_entered.set()
                await self.release.wait()
                raise
            finally:
                self.active_reads -= 1
                self.read_finished.set()

    native, private = NativeIO(), SlowCancelPrivate()
    callback = conversation(private)
    task = asyncio.create_task(callback(native))
    for _ in range(100):
        if native.active_reads and private.active_reads:
            break
        await asyncio.sleep(0)
    try:
        task.cancel("first external cancellation")
        entered = asyncio.create_task(private.cancel_entered.wait())
        try:
            done, _ = await asyncio.wait({entered}, timeout=0.25)
            assert entered in done, "owned reader must receive cancellation"
        finally:
            entered.cancel()
            await asyncio.gather(entered, return_exceptions=True)
        assert not task.done() and private.active_reads == 1
        task.cancel("second external cancellation during join")
        private.release.set()
        with pytest.raises(asyncio.CancelledError) as caught:
            await task
        assert str(caught.value) == "first external cancellation"
        assert private.invalidated and private.active_reads == native.active_reads == 0
    finally:
        private.release.set()
        for child in callback._tasks:
            if not child.done():
                child.cancel()
        await cancel_and_join(task)
        finished = asyncio.create_task(private.read_finished.wait())
        try:
            done, _ = await asyncio.wait({finished}, timeout=1)
            assert finished in done, "test cleanup must join the private reader"
        finally:
            finished.cancel()
            await asyncio.gather(finished, return_exceptions=True)


async def test_reentry_wakes_silent_owner_and_later_reentry_does_not_cancel_unrelated_work():
    native, private = NativeIO(), PrivateIO()
    callback = conversation(private)
    first = asyncio.create_task(callback(native))
    for _ in range(100):
        if native.active_reads and private.active_reads:
            break
        await asyncio.sleep(0)
    assert native.active_reads == private.active_reads == 1
    try:
        with pytest.raises(ContractViolation):
            await callback(NativeIO())
        done, _ = await asyncio.wait({first}, timeout=0.25)
        assert first in done, "reentry must wake the active owner promptly"
        with pytest.raises(asyncio.CancelledError):
            await first
        assert native.active_reads == private.active_reads == 0
        with pytest.raises(ContractViolation):
            await callback(NativeIO())
    finally:
        await cancel_and_join(first)


async def test_reentry_after_completion_does_not_cancel_owner_later_work():
    native, private = NativeIO(), PrivateIO()
    completed = asyncio.Event()
    release = asyncio.Event()
    callback = conversation(private)

    async def owner() -> None:
        await callback(native)
        completed.set()
        await release.wait()

    task = asyncio.create_task(owner())
    private.line.set_result(b"opaque\n")
    await asyncio.wait_for(native.write_entered.wait(), 1)
    native.output.put_nowait(b"")
    await asyncio.wait_for(completed.wait(), 1)
    assert callback.facts.lifecycle is login.ClaudeLoginConversationLifecycle.COMPLETED
    with pytest.raises(ContractViolation):
        await callback(NativeIO())
    assert not task.done() and not task.cancelling()
    release.set()
    await asyncio.wait_for(task, 1)


async def test_deadline_refuses_but_finishes_owned_cleanup():
    native, private = NativeIO(), PrivateIO()
    callback = conversation(private, seconds=0.01)
    with pytest.raises(TimeoutError):
        await callback(native)
    assert private.invalidated and private.active_reads == native.active_reads == 0
    assert callback.facts.lifecycle is login.ClaudeLoginConversationLifecycle.REFUSED


async def test_deadline_must_fit_the_single_fixed_lifetime():
    private = PrivateIO()
    now = asyncio.get_running_loop().time()
    for deadline in (now, now + 600.001, float("inf"), float("nan"), True):
        with pytest.raises(ValueError):
            login.ClaudeLoginConversation(private, deadline=deadline)


@pytest.mark.parametrize("failure", ["input", "output", "write", "close"])
async def test_private_or_native_failure_uses_fixed_refusal_and_joins(failure):
    class FailedNative(NativeIO):
        async def write(self, data: bytes) -> None:
            if failure == "write":
                raise RuntimeError("private native bytes")
            await super().write(data)

        async def close_stdin(self) -> None:
            if failure == "close":
                raise RuntimeError("private native bytes")
            await super().close_stdin()

    class FailedPrivate(PrivateIO):
        async def read_line(self) -> bytes:
            if failure == "input":
                raise RuntimeError("private operator bytes")
            return await super().read_line()

        async def write_stdout(self, data: bytes) -> None:
            if failure == "output":
                raise RuntimeError("private native bytes")
            await super().write_stdout(data)

    native, private = FailedNative(), FailedPrivate()
    if failure == "output":
        native.output.put_nowait(b"private vendor bytes")
    elif failure != "input":
        private.line.set_result(b"opaque\n")
    callback = conversation(private)
    with pytest.raises(login.LoginConversationRefused) as caught:
        await asyncio.wait_for(callback(native), 1)
    assert str(caught.value) == "Claude login conversation refused"
    assert callback.facts.lifecycle is login.ClaudeLoginConversationLifecycle.REFUSED
    assert private.invalidated and native.active_reads == private.active_reads == 0


async def test_failing_private_invalidation_cannot_publish_exception_text():
    class FailedInvalidate(PrivateIO):
        def invalidate(self) -> None:
            raise RuntimeError("private operator bytes")

    native, private = NativeIO(), FailedInvalidate()
    native.output.put_nowait(b"")
    callback = conversation(private)
    with pytest.raises(login.LoginConversationRefused) as caught:
        await callback(native)
    assert str(caught.value) == "Claude login conversation refused"
    assert caught.value.__cause__ is None
    assert native.active_reads == private.active_reads == 0


async def test_cancellation_and_private_invalidation_failure_keep_both_static_facts():
    class FailedInvalidate(PrivateIO):
        def invalidate(self) -> None:
            raise RuntimeError("private operator bytes")

    native, private = NativeIO(), FailedInvalidate()
    callback = conversation(private)
    task = asyncio.create_task(callback(native))
    for _ in range(100):
        if native.active_reads and private.active_reads:
            break
        await asyncio.sleep(0)
    task.cancel("external cancellation")
    try:
        done, _ = await asyncio.wait({task}, timeout=0.25)
        assert task in done, "cancellation and cleanup must finish promptly"
        caught: BaseException | None = None
        try:
            await task
        except BaseException as error:
            caught = error
        assert type(caught) is BaseExceptionGroup
        assert str(caught).startswith("Claude login cleanup refused")
        assert len(caught.exceptions) == 2
        assert type(caught.exceptions[0]) is asyncio.CancelledError
        assert str(caught.exceptions[0]) == "external cancellation"
        assert type(caught.exceptions[1]) is login.LoginConversationRefused
        assert "private operator bytes" not in repr(caught)
        assert native.active_reads == private.active_reads == 0
    finally:
        await cancel_and_join(task)


def test_facts_reject_unbounded_or_coerced_public_fields():
    fields = dict(lifecycle=login.ClaudeLoginConversationLifecycle.REFUSED,
                  input_write_attempted=False, stdin_closed=False,
                  stdout_eof=False, stdout_bytes=0)
    for key, bad in (("lifecycle", "completed"), ("input_write_attempted", 1),
                     ("stdin_closed", 1), ("stdout_eof", 1),
                     ("stdout_bytes", 256 * 1024 + 1)):
        with pytest.raises(ValueError):
            login.ClaudeLoginConversationFacts(**{**fields, key: bad})
    with pytest.raises(ValueError):
        login.ClaudeLoginConversationFacts(**{
            **fields, "lifecycle": login.ClaudeLoginConversationLifecycle.COMPLETED,
        })
