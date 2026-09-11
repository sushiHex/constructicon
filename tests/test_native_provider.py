"""The same endpoint law on loopback and directly on the mounted socket."""

import array
import asyncio
import json
import os
import socket
import sys
import tempfile
from contextlib import suppress
from pathlib import Path

import pytest

from tests.native_provider import provider_peer
from tests.substrate import _provider_transport as transport


@pytest.fixture(params=["tcp", "unix"])
def address(request):
    if request.param == "tcp":
        yield None
    else:
        if sys.platform != "linux":
            pytest.skip("Unix ancillary/leaf proofs require Linux")
        with tempfile.TemporaryDirectory(prefix="m8-peer-") as root:
            yield Path(root) / "peer"


async def connect(peer):
    sock = socket.socket(peer.listener.family)
    sock.setblocking(False)
    await asyncio.get_running_loop().sock_connect(sock, peer.listener.getsockname())
    return sock


def request_bytes(body=None, headers=b""):
    body = json.dumps({"model": "probe-model"} if body is None else body).encode()
    return (b"POST /v1/responses HTTP/1.1\r\n" + headers
            + f"Content-Length: {len(body)}\r\n\r\n".encode() + body)


async def transact(peer, raw):
    with await connect(peer) as sock:
        await asyncio.get_running_loop().sock_sendall(sock, raw)
        sock.shutdown(socket.SHUT_WR)
        output = bytearray()
        with suppress(ConnectionError):
            while data := await transport.receive(sock):
                output.extend(data)
        return bytes(output)


async def test_two_requests_share_the_script_and_spend_admission(address):
    async with provider_peer("test_tool", {"data": "inert"}, path=address) as peer:
        first = await transact(peer, request_bytes())
        second = await transact(peer, request_bytes())
    assert b'"type": "function_call"' in first
    assert b"fixture complete" in second
    assert len(peer.requests) == peer.budget.connections == 2
    assert peer.budget.total == 2 * len(request_bytes()) + len(first) + len(second)
    assert not peer.failures and not peer.active
    assert all(task.done() for task in peer.handlers)


@pytest.mark.parametrize("raw,reason", [
    (b"", "incomplete headers"),
    (b"POST /v1/responses HTTP/1.1\r\nContent-Length: 9\r\n\r\n{}", "incomplete body"),
    (request_bytes(headers=b"Authorization: fake\r\n"), "authentication"),
    (request_bytes(headers=b"Transfer-Encoding: chunked\r\n"), "transfer encoding"),
    (request_bytes(headers=b"Content-Length: 1\r\n"), "ambiguous header"),
    (request_bytes({"model": "wrong"}), "unexpected model"),
    (b"GET / HTTP/1.1\r\nContent-Length: 2\r\n\r\n{}", "request target"),
    (b"POST /v1/responses HTTP/1.1\r\nContent-Length: 1048577\r\n\r\n", "body bound"),
    (request_bytes().replace(b"Length: 24", b"Length: +24"), "malformed content length"),
    (request_bytes().replace(b"Length: 24", b"Length: 2_4"), "malformed content length"),
])
async def test_malformed_direct_connections_spend_allowance_and_close(address, raw, reason):
    async with provider_peer(path=address) as peer:
        assert await transact(peer, raw) == b""
        await asyncio.wait_for(peer.stopped.wait(), 2)
    assert peer.budget.connections == 1
    assert any(reason in failure for failure in peer.failures)
    assert peer.listener.fileno() == -1 and not peer.active


async def test_third_connection_is_refused_before_reading_headers(address):
    deadline = asyncio.get_running_loop().time() + .5
    async with provider_peer(path=address, deadline=deadline) as peer:
        await transact(peer, request_bytes())
        await transact(peer, request_bytes())
        with await connect(peer) as third:
            assert await transport.receive(third) == b""
    assert len(peer.requests) == 2 and peer.budget.connections == 3
    assert any("connection bound" in item for item in peer.failures)


async def test_concurrent_incomplete_connection_closes_the_listener(address):
    deadline = asyncio.get_running_loop().time() + .5
    async with provider_peer(path=address, deadline=deadline) as peer:
        with await connect(peer) as first:
            async with asyncio.timeout(2):
                while not peer.active:
                    await asyncio.sleep(0)
            with await connect(peer) as second:
                assert await transport.receive(second) == b""
            assert await transport.receive(first) == b""
    assert peer.budget.connections == 2 and not peer.requests
    assert any("concurrent" in item for item in peer.failures)
    assert not peer.active and all(task.done() for task in peer.handlers)


async def test_deadline_includes_idle_setup_and_does_not_renew(address):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + .2
    async with provider_peer(path=address, deadline=deadline) as peer:
        await asyncio.sleep(.1)
        with await connect(peer) as sock:
            assert await asyncio.wait_for(transport.receive(sock), 1) == b""
        await asyncio.wait_for(peer.stopped.wait(), 1)
    assert loop.time() < deadline + .5
    assert peer.failures and not peer.active


async def test_header_and_aggregate_bounds_are_endpoint_owned(address, monkeypatch):
    # Small limits test the same predicates without filling a runner's buffers.
    monkeypatch.setattr(transport, "TOTAL", 100)
    async with provider_peer(path=address) as peer:
        assert await transact(peer, request_bytes()) == b""
    assert any("aggregate byte bound" in item for item in peer.failures)
    assert peer.budget.total > 100


async def test_pipelined_bytes_after_a_large_body_are_not_dropped(address):
    async with provider_peer(path=address) as peer:
        raw = request_bytes({"model": "probe-model", "padding": "x" * 16000})
        await transact(peer, raw + request_bytes())
    assert any("trailing request bytes" in item for item in peer.failures)


@pytest.mark.parametrize("prompt", [None, "wrong", "controlled"])
async def test_model_match_does_not_substitute_for_the_controlled_scenario(address, prompt):
    body = {"model": "probe-model"}
    if prompt is not None:
        body["input"] = [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}]
    async with provider_peer(path=address, scenario="controlled") as peer:
        response = await transact(peer, request_bytes(body))
    if prompt == "controlled":
        assert b"response.completed" in response and not peer.failures
    else:
        assert not response
        assert any("unexpected scenario" in failure for failure in peer.failures)


async def test_failed_bind_and_replaced_path_never_remove_another_resource(address):
    if address is None:
        pytest.skip("pathname ownership is Unix-specific")
    address.write_text("existing resource")
    with pytest.raises(OSError):
        async with provider_peer(path=address):
            pytest.fail("existing path was accepted")
    assert address.read_text() == "existing resource"
    address.unlink()
    async with provider_peer(path=address) as peer:
        address.unlink()
        address.write_text("replacement")
    assert address.read_text() == "replacement"
    assert peer.failures == ["endpoint replaced before teardown"]


async def test_repeated_cancellation_joins_every_accepted_handler(address, monkeypatch):
    entered = asyncio.Event()
    cleaning, release = asyncio.Event(), asyncio.Event()
    peers, sockets = [], []
    gather = asyncio.gather

    def paused_join(*tasks, **kwargs):
        pending = gather(*tasks, **kwargs)
        if peers and tasks == (peers[0].acceptor,):
            async def pause():
                await pending
                cleaning.set()
                await release.wait()
            return pause()
        return pending

    # Interrupt the exact join boundary, not a platform-dependent TCP callback.
    monkeypatch.setattr(asyncio, "gather", paused_join)

    async def invocation():
        async with provider_peer(path=address) as peer:
            peers.append(peer)
            sockets.append(await connect(peer))
            while not peer.active:
                await asyncio.sleep(0)
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(invocation())
    try:
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        await asyncio.wait_for(cleaning.wait(), 2)
        task.cancel()
        done, _ = await asyncio.wait([task], timeout=.02)
        assert not done, "cancellation abandoned owned cleanup"
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        [peer] = peers
        assert not peer.active
        assert all(handler.done() for handler in peer.handlers)
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for sock in sockets:
            sock.close()


async def test_ancillary_descriptors_are_closed_before_refusal(address, monkeypatch):
    if address is None:
        pytest.skip("TCP has no descriptor-transfer protocol")
    closed = []
    close = os.close

    def observed(fd):
        closed.append(fd)
        close(fd)

    async with provider_peer(path=address) as peer:
        with await connect(peer) as sock, open(os.devnull, "rb") as source:
            monkeypatch.setattr(transport.os, "close", observed)
            sock.sendmsg([b"x"], [(socket.SOL_SOCKET, socket.SCM_RIGHTS,
                                  array.array("i", [source.fileno()]))])
            assert await transport.receive(sock) == b""
    assert any("ancillary" in item for item in peer.failures)
    assert len(closed) == 1
    with pytest.raises(OSError):
        os.fstat(closed[0])
