"""The requester's reply, read from a real whole-chain window's own records.

Every window here is the offline whole chain of ``test_change_review_read``
(qualification, native read, supervisor, guest shell and closure program).
No evidence byte is built by hand: tampers copy the retained custody and
change one file in the copy.
"""

from __future__ import annotations

import base64
import json
import shutil
from hashlib import sha256
from pathlib import Path

import pytest
from scripts.ops import change_review_reply as reply
from scripts.ops.m9_read_closure import _wire

from constructicon.api import change_review_advice as route
from tests.api.test_change_review_advice import DEMO
from tests.substrate.test_codex_adapter import portable_binding as portable_binding
from tests.substrate.test_codex_adapter import substituted_guard as substituted_guard
from tests.test_change_review_read import SUMMARY, settled_read, world

CHANGE = {"before": "1" * 40, "after": "2" * 40, "path": "examples/change_review.py"}


def packet(root: Path, summary: bytes = SUMMARY, instruction: bytes | None = None) -> Path:
    """A prepared packet's three files, as ``change_review_input.prepare`` lays them out."""
    bound = route.bound_values(route.ChangeSummaryV1.model_validate_json(summary))
    root.mkdir(mode=0o700)
    (root / "summary.json").write_bytes(summary)
    (root / "instruction.txt").write_bytes(
        bound.instruction.encode("utf-8") if instruction is None else instruction)
    (root / "packet.json").write_bytes(_wire({
        "schema_version": 1, "controller": "0" * 40, "checked_source_files": {},
        "change": CHANGE, "summary_sha256": sha256(summary).hexdigest(),
        "offline_pins": bound.projection(), "offline_pins_are_provisional": True,
        "execution_authorized": False,
    }))
    return root


def crlf(envelope: bytes) -> bytes:
    record = json.loads(envelope)
    stdout = base64.b64decode(record["stdout"]).replace(b"\n", b"\r\n")
    return json.dumps({**record, "stdout": base64.b64encode(stdout).decode("ascii")},
                      sort_keys=True, separators=(",", ":")).encode() + b"\n"


def copied(work: Path, record: Path, into: Path) -> tuple[Path, Path]:
    shutil.copytree(work, into, symlinks=True)
    return into, into / record.name


def refused(code: str, *args: Path) -> None:
    with pytest.raises(reply.ReplyRefused) as caught:
        reply.collect(*args)
    assert caught.value.code == code


def test_an_accepted_clean_window_delivers_the_whole_advice_and_refuses_each_tamper(
    tmp_path, monkeypatch, portable_binding, substituted_guard,
):
    answer = "Test the empty input.\N{SNOWMAN}"
    platform, path, digest = world(tmp_path, monkeypatch, portable_binding, answer=answer)
    host, result = platform.window(path, digest)
    assert (result.reason, result.cleanup, result.custody_retained) == (
        "read-settled", "clean", False)
    work, record = platform.custody, result.record
    prepared = packet(tmp_path / "packet")
    _, _, stdout = settled_read(platform, host)
    printed = json.loads(stdout)

    delivered = reply.collect(work, record, prepared)
    bound = route.bound_values(DEMO)
    assert delivered == {
        "schema_version": 1, "status": "delivered", "change": CHANGE,
        "summary_sha256": sha256(SUMMARY).hexdigest(),
        "instruction_digest": str(bound.instruction_digest), "window": record.name,
        "run_id": bound.run_id, "accepted_read_sha256": result.accepted_read_sha256,
        "approval_sha256": platform.approval.sha256, "approval_slot": 1,
        # Exactly as the route printed them: no field added, no None renamed.
        "advice": printed["advice"], "metering": printed["result"]["metering"],
    }
    assert delivered["advice"]["advice"] == answer
    assert delivered["metering"]["confirmed_charge"] is None
    assert delivered["metering"]["estimate"] is None
    # Reading changed nothing.
    assert reply.collect(work, record, prepared) == delivered

    def tamper(name: str, change) -> tuple[Path, Path]:
        into, moved = copied(work, record, tmp_path / ("copy-" + name))
        change(into, moved)
        return into, moved

    def edit(target: Path, transform) -> None:
        target.write_bytes(transform(target.read_bytes()))

    captures = lambda into: next(into.glob("native-*/captures"))  # noqa: E731
    evidence = {
        "close": lambda into, moved: edit(
            moved / "close.json",
            lambda raw: raw.replace(result.accepted_read_sha256.encode(), b"0" * 64)),
        "projection": lambda into, moved: edit(
            captures(into) / "read-projection.stdout", lambda raw: raw[:-1] + b" \n"),
        # CRLF producer bytes inside the envelope: a new stdout digest.
        "original": lambda into, moved: edit(
            captures(into) / "read-original.stdout", crlf),
        "status": lambda into, moved: edit(
            captures(into) / "read-projection.status.json",
            lambda raw: raw.replace(b'"returncode": 0', b'"returncode": 1')),
        "missing": lambda into, moved: (captures(into) / "read-original.stdout").unlink(),
        "challenge": lambda into, moved: edit(
            moved / "challenge.json", lambda raw: raw.replace(b'"consumer"', b'"consumer" ')),
    }
    for name, change in evidence.items():
        refused("REPLY_EVIDENCE_MISMATCH", *tamper(name, change), prepared)

    # A packet for another summary binds another run: the accepted advice is refused.
    other = DEMO.model_copy(update={"symbols_partial": not DEMO.symbols_partial})
    other_raw = _wire(other.model_dump(mode="json"))
    refused("REPLY_ADVICE_INVALID", work, record, packet(tmp_path / "other", other_raw))
    refused("REPLY_PACKET_MISMATCH", work, record,
            packet(tmp_path / "forged", instruction=b"another instruction"))
    # Only the window's own record, named by its nonce, directly under work.
    refused("REPLY_RECORD_UNPROVED", work, work / "result", prepared)
    refused("REPLY_RECORD_UNPROVED", tmp_path, record, prepared)

    # A window that is no longer clean, or whose marker still names it, is not delivered.
    for name, change in {
        "retained": lambda into, moved: edit(
            moved / "result.json",
            lambda raw: raw.replace(b'"custody_release_eligible": true',
                                    b'"custody_release_eligible": false')),
        "active": lambda into, moved: (into / "active").write_bytes(moved.name.encode()),
    }.items():
        into, moved = tamper(name, change)
        outcome = reply.collect(into, moved, prepared)
        assert outcome["status"] == "not-delivered" and "advice" not in outcome
        assert outcome["result"]["accepted_read_sha256"] == result.accepted_read_sha256


def test_a_failed_reply_is_not_delivered_and_keeps_its_disposition(
    tmp_path, monkeypatch, portable_binding, substituted_guard, capsys,
):
    platform, path, digest = world(tmp_path, monkeypatch, portable_binding, answer="")
    _, result = platform.window(path, digest)
    assert result.accepted_read_sha256 is None
    prepared = packet(tmp_path / "packet")
    outcome = reply.collect(platform.custody, result.record, prepared)
    assert outcome["status"] == "not-delivered" and "advice" not in outcome
    assert outcome["result"] == json.loads((result.record / "result.json").read_bytes())
    assert outcome["result"]["approval_suspended"] is True

    # The command prints the reply, or only a refusal's code.
    argv = ["--work", str(platform.custody), "--record", str(result.record)]
    assert reply.main([*argv, "--packet", str(prepared)]) == 0
    assert json.loads(capsys.readouterr().out) == outcome
    assert reply.main([*argv, "--packet", str(tmp_path / "absent")]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "refused", "reason": "REPLY_PACKET_MISMATCH"}
