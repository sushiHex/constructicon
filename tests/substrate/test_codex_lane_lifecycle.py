"""Exercise the real lane/relay cleanup around a scripted, networkless startup."""

import asyncio
import json
import os

import pytest

from constructicon.core.identity import canonical_json, digest
from constructicon.substrate.executors import codex_lane, egress
from tests.substrate.test_codex_lane import (
    EVIDENCE_DOMAIN,
    Lane,
    closed,
    startup,
    startup_native,
)


@pytest.mark.parametrize("leftover", [False, True], ids=["empty", "nonempty"])
async def test_producer_lane_cleanup_and_published_evidence(tmp_path, monkeypatch, leftover):
    # The real relay owns creation and release; only its Linux socket primitive
    # and accept wait are replaced, so this also runs on Windows without network I/O.
    class Listener:
        def close(self):
            pass

    def bind(path):
        path.write_bytes(b"socket stand-in")
        info = path.lstat()
        return Listener(), (info.st_dev, info.st_ino)

    async def accept(_self):
        await asyncio.Event().wait()

    def sealed(data):
        path = tmp_path / "configuration"
        path.write_bytes(data)
        return os.open(path, os.O_RDONLY)

    monkeypatch.setattr(egress, "_bind_private_socket", bind)
    monkeypatch.setattr(egress.EgressRelay, "_accept_loop", accept)
    monkeypatch.setattr(codex_lane, "sealed_data_fd", sealed)
    assert codex_lane.EgressRelay is egress.EgressRelay
    lane_dir = tmp_path / "lane"
    seen = []

    def during(_lane):
        assert lane_dir.is_dir() and (lane_dir / "relay").is_dir()
        assert len(list((lane_dir / "relay").iterdir())) == 1
        seen.append("producer-created")
        if leftover:
            (lane_dir / "unexpected").write_bytes(b"bounded residue")

    lane = Lane(tmp_path, startup_native(), during=during)
    try:
        _, evidence = await startup(tmp_path, lane=lane)
        assert seen == ["producer-created"]
        assert evidence["faults"] == [] and evidence["gate"]["completed"] is True
        assert evidence["relay"]["closed"] is True
        assert not (lane_dir / "relay").exists()
        # codex_lane.launch:319 suppresses rmdir errors, so only an empty lane
        # is removed; evidence does not claim that a nonempty lane was removed.
        if leftover:
            assert (lane_dir / "unexpected").read_bytes() == b"bounded residue"
            assert {p.name for p in lane_dir.iterdir()} == {"unexpected"}
        else:
            assert not lane_dir.exists()
        assert all(closed(fd) for fd in lane.mounts[0][2].mount_fds)
        path = tmp_path / "startup.json"
        revision = codex_lane.write_evidence(path, evidence)
        published = json.loads(path.read_bytes())
        assert published == {**evidence, "completed": True}
        assert revision == digest(EVIDENCE_DOMAIN, 1, json.loads(canonical_json(published)))
    finally:
        os.close(lane.lock)
