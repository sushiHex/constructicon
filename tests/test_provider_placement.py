"""Recipe and stream-law checks; physical isolation remains a Linux gate."""

import asyncio
import socket
import stat
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
    if drift == "extra":
        mounts.append("6 4 1:6 / /tmp/authority ro - ext4 /dev/test ro")
    if drift == "root-rw":
        mounts[0] = mounts[0].replace("ro", "rw")
    if drift == "endpoint-rw":
        mounts[-1] = mounts[-1].replace("ro", "rw")
    contents = {
        "/proc/self/mountinfo": "\n".join(mounts),
        "/proc/net/dev": "header\nheader\nlo: 0\n" + ("eth0: 0" if drift == "network" else ""),
        "/proc/net/route": "header\n", "/proc/net/ipv6_route": "",
    }
    monkeypatch.setattr(Path, "read_text", lambda path: contents[str(path).replace("\\", "/")])
    monkeypatch.setattr(Path, "lstat", lambda path:
                        SimpleNamespace(st_mode=stat.S_IFSOCK, st_dev=7, st_ino=8))
    names = ("0", "1", "2", "9") if drift == "fd" else ("0", "1", "2")
    monkeypatch.setattr(Path, "iterdir", lambda path: iter(Path(name) for name in names))
    monkeypatch.setattr(bootstrap.os, "readlink", lambda path: "observed")
    if drift == "none":
        assert bootstrap.topology([7, 8])["interfaces"] == ["lo"]
    else:
        with pytest.raises(ValueError):
            bootstrap.topology([7, 8])
