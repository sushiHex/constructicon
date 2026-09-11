"""Recipe and stream-law checks; physical isolation remains a Linux gate."""

import asyncio
import socket
import stat
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.core.grants import Posture
from constructicon.core.identity import Digest
from constructicon.substrate.executors import linux
from tests.provider_placement import PlacementLauncher
from tests.substrate._provider_transport import ENDPOINT, Budget, forward


@pytest.fixture
def composition(tmp_path, monkeypatch):
    # No physical claim: supply only the platform facts argv consumes.
    monkeypatch.setattr(linux.sys, "platform", "linux")
    monkeypatch.setattr(linux.os, "getuid", lambda: 123, raising=False)
    monkeypatch.setattr(linux.os, "getgid", lambda: 123, raising=False)
    endpoint = (tmp_path / "provider.sock").resolve()
    observed = SimpleNamespace(st_mode=stat.S_IFSOCK, st_uid=123, st_dev=7, st_ino=8)
    original = Path.lstat
    monkeypatch.setattr(Path, "lstat", lambda path:
                        observed if path == endpoint else original(path))
    return PlacementLauncher(
        runtime_root=tmp_path, expected_runtime=Digest("sha256:" + "0" * 64),
        bubblewrap=tmp_path / "bwrap", policy=tmp_path / "policy", expected_policy_sha256="0" * 64,
        endpoint=endpoint, endpoint_identity=(7, 8),
    )


def test_recipe_is_exactly_parent_plus_one_leaf_for_probe_and_call(composition):
    for command in (("/usr/bin/python3", "-I", "-c", "pass"), ("/opt/native/codex",)):
        parent = linux.LinuxLauncher.argv(
            composition, command, workspace=None, posture=Posture.READ,
        )
        actual = composition.argv(command, workspace=None, posture=Posture.READ)
        index = parent.index("--")
        assert actual == (*parent[:index], "--ro-bind", str(composition.endpoint),
                          ENDPOINT, *parent[index:])
        assert actual.count(str(composition.endpoint.parent)) == 1  # Immutable root only.


def test_fixture_refuses_a_workspace_or_changed_endpoint(composition):
    command = ("/usr/bin/python3",)
    with pytest.raises(ValueError, match="no workspace"):
        composition.argv(command, workspace=composition.root, posture=Posture.READ)
    with pytest.raises(ValueError, match="endpoint changed"):
        replace(composition, endpoint_identity=(7, 9)).argv(
            command, workspace=None, posture=Posture.READ,
        )


def test_revision_is_distinct_but_does_not_hash_ephemeral_endpoint(composition, monkeypatch):
    parent = linux.LinuxLauncher.revision.fget(composition)
    before = composition.revision
    assert parent != before
    assert before == replace(composition, endpoint=Path("/another/test/leaf"),
                             endpoint_identity=(50, 90)).revision
    assert before != replace(composition, expected_runtime=Digest("sha256:" + "1" * 64)).revision
    from tests import provider_placement
    original = provider_placement.inspect.getsource
    monkeypatch.setattr(provider_placement.inspect, "getsource", lambda value:
                        original(value) + ("changed" if value is PlacementLauncher else ""))
    assert before != composition.revision


async def sockets():
    # TCP pairs also exercise the Windows event loop used by ordinary verify.
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.setblocking(False)
    client = socket.socket()
    client.setblocking(False)
    await asyncio.get_running_loop().sock_connect(client, listener.getsockname())
    server, _ = await asyncio.get_running_loop().sock_accept(listener)
    listener.close()
    server.setblocking(False)
    return client, server


async def test_bridge_half_close_drains_and_preserves_reverse_direction():
    client, left = await sockets()
    right, peer = await sockets()
    budget = Budget()
    loop = asyncio.get_running_loop()
    with client, left, right, peer:
        task = asyncio.create_task(forward(left, right, budget))
        try:
            await loop.sock_sendall(client, b"request")
            client.shutdown(socket.SHUT_WR)
            assert await loop.sock_recv(peer, 8192) == b"request"
            assert await loop.sock_recv(peer, 8192) == b""
            assert not task.done(), "request EOF discarded the return direction"
            await loop.sock_sendall(peer, b"delayed response")
            peer.shutdown(socket.SHUT_WR)
            assert await loop.sock_recv(client, 8192) == b"delayed response"
            assert await loop.sock_recv(client, 8192) == b""
            await asyncio.wait_for(task, 2)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert budget.total == len(b"requestdelayed response")


@pytest.mark.parametrize("drift", ["none", "extra", "root-rw", "endpoint-rw", "fd", "network"])
def test_actual_namespace_preflight_checks_named_mounts_flags_and_fds(monkeypatch, drift):
    from tests.substrate import _provider_bootstrap as bootstrap
    mounts = [
        "1 0 1:1 / / ro - ext4 /dev/test ro",
        "2 1 1:2 / /proc rw - proc proc rw",
        "3 1 1:3 / /dev rw - tmpfs tmpfs rw",
        "4 1 1:4 / /tmp rw - tmpfs tmpfs rw",
        f"5 1 1:5 / {ENDPOINT} ro - ext4 /dev/test ro",
    ]
    devices = ("null", "zero", "full", "random", "urandom", "tty")
    mounts += [f"{number} 3 1:6 / /dev/{name} rw - devtmpfs devtmpfs rw"
               for number, name in enumerate(devices, 6)]
    mounts.append("12 3 1:7 / /dev/pts rw - devpts devpts rw")
    if drift == "extra":
        mounts.append("6 4 1:6 / /tmp/authority ro - ext4 /dev/test ro")
    if drift == "root-rw":
        mounts[0] = mounts[0].replace("ro", "rw")
    if drift == "endpoint-rw":
        mounts[4] = mounts[4].replace("ro", "rw")
    contents = {
        "/proc/self/mountinfo": "\n".join(mounts),
        "/proc/net/dev": "header\nheader\nlo: 0\n" + ("eth0: 0" if drift == "network" else ""),
        "/proc/net/route": "header\n", "/proc/net/ipv6_route": "",
    }
    monkeypatch.setattr(Path, "read_text", lambda path: contents[str(path).replace("\\", "/")])
    monkeypatch.setattr(Path, "lstat", lambda path:
                        SimpleNamespace(st_mode=stat.S_IFSOCK, st_dev=7, st_ino=8))
    monkeypatch.setattr(Path, "stat", lambda path: SimpleNamespace(st_mode=stat.S_IFCHR))
    names = ("0", "1", "2", "9") if drift == "fd" else ("0", "1", "2")
    monkeypatch.setattr(Path, "iterdir", lambda path: iter(Path(name) for name in names))
    monkeypatch.setattr(bootstrap.os, "readlink", lambda path: "observed")
    if drift == "none":
        observed = bootstrap.topology([7, 8])
        assert observed["interfaces"] == ["lo"]
        assert observed["identity"] == [7, 8]
    else:
        with pytest.raises(ValueError):
            bootstrap.topology([7, 8])


async def test_failed_conversation_keeps_its_owned_result(composition, tmp_path, monkeypatch):
    from constructicon.substrate.executors.linux import ProcessExchangeError, ProcessResult
    from tests.substrate import test_provider_placement as placement
    result = ProcessResult(7, b"partial", b"diagnostic", .1, False, None, 7)

    async def failed(*_args, **_kwargs):
        raise ProcessExchangeError(result) from ValueError("bad RPC")

    monkeypatch.setattr(placement, "exchange", failed)
    record = {}
    peer = SimpleNamespace(deadline=asyncio.get_running_loop().time() + 20)
    with pytest.raises(ProcessExchangeError):
        await placement.observe(composition, peer, tmp_path, record=record)
    assert "outcome" in record
    assert record["outcome"]["payload_returncode"] == 7
    assert record["outcome"]["stdout"] == b"partial".hex()
    assert record["outcome"]["stderr"] == b"diagnostic".hex()
    assert record["failure"] == "ValueError('bad RPC')"


async def test_case_emits_failed_evidence_after_peer_join(composition, monkeypatch):
    from dataclasses import fields

    from tests.substrate import test_provider_placement as placement
    order, saved, names = [], [], []

    @asynccontextmanager
    async def peer_fixture(*, path, **kwargs):
        path.touch()
        try:
            yield SimpleNamespace(requests=[], failures=[], active=set(), handlers=set(),
                                  budget=Budget())
        finally:
            order.append("joined")

    def emitted(name, value):
        order.append("evidence")
        saved.append(value)
        names.append(name)

    monkeypatch.setattr(placement, "provider_peer", peer_fixture)
    monkeypatch.setattr(placement, "write_evidence", emitted)
    image = linux.LinuxLauncher(**{field.name: getattr(composition, field.name)
                                  for field in fields(linux.LinuxLauncher)})
    with pytest.raises(ValueError, match="case failed"):
        async with placement.placement(image) as (_composed, _peer, record):
            record["failure"] = "retained observation"
            raise ValueError("case failed")
    assert order == ["joined", "evidence"]
    assert saved[0]["failure"] == "retained observation"
    async with (
        placement.placement(image) as (_one, _peer_one, record_one),
        placement.placement(image) as (_two, _peer_two, record_two),
    ):
        record_one["member"] = "first"
        record_two["member"] = "second"
    assert len(set(names)) == 3, "one invocation overwrote another's evidence"
    assert [record["member"] for record in saved[1:]] == ["second", "first"]


async def test_cancel_control_cannot_accept_resident_descendants(tmp_path, monkeypatch):
    from tests.substrate import test_provider_placement as placement

    @asynccontextmanager
    async def fixture(*_args, **_kwargs):
        yield None, SimpleNamespace(active=set(), handlers=set()), {}

    class Wire:
        calls = 0

        async def read(self):
            self.calls += 1
            if self.calls == 1:
                return {"placement": {}}
            if self.calls == 2:
                return {"descendant_ready": True}
            await asyncio.Event().wait()

    async def observe(*_args, query, **_kwargs):
        await query(Wire(), {})

    monkeypatch.setattr(placement, "placement", fixture)
    monkeypatch.setattr(placement, "observe", observe)
    monkeypatch.setattr(placement, "descendants", lambda pid: dict.fromkeys(range(4), "resident"))
    monkeypatch.setattr(placement, "birth", lambda pid: "resident")
    with pytest.raises(AssertionError):
        await placement.test_existing_owner_reaps_bridge_and_session_changed_descendant(
            None, tmp_path, "cancel",
        )
