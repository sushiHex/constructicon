"""The requester's reply, read from a real whole-chain window's own records.

Every window here is the offline whole chain of ``test_change_review_read``
(qualification, native read, supervisor, guest shell and closure program),
run on a summary that the real producer, ``change_review_input.prepare``,
made from real commits. No evidence or packet byte is built by hand: each
tamper copies the retained custody or packet and changes one file.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
from pathlib import Path

import pytest
from scripts.ops import change_review_input as producer
from scripts.ops import change_review_reply as reply

from constructicon.api import change_review_advice as route
from tests import test_change_review_read as chain
from tests.substrate.test_codex_adapter import portable_binding as portable_binding
from tests.substrate.test_codex_adapter import substituted_guard as substituted_guard
from tests.test_change_review_input import source_world as source_world
from tests.test_m9_read_window import Fake


@pytest.fixture
def produced(source_world, tmp_path, monkeypatch):
    """A real packet, and the whole chain rebound to its summary."""
    repository, controller, before, after = source_world
    packet = tmp_path / "packet"
    record = producer.prepare(repository, controller, before, after, "calc.py", packet)
    raw = (packet / "summary.json").read_bytes()
    # The chain reads these module values at call time; ``selection``'s default
    # argument was bound to the old bytes, so it is passed explicitly below.
    monkeypatch.setattr(chain, "DEMO", route.ChangeSummaryV2.model_validate_json(raw))
    monkeypatch.setattr(chain, "SUMMARY", raw)
    return packet, record, (repository, controller, before, after)


@pytest.fixture
def checked(monkeypatch):
    """Every directory the reply checks. On POSIX the custody's own check runs as well;
    pytest's Windows temp root is not private custody (test_m9_owner_approval covers
    that check on a private home directory)."""
    seen: list[Path] = []
    real = reply.private_directory

    def check(path: Path) -> None:
        seen.append(path)
        if os.name == "posix":
            real(path)

    monkeypatch.setattr(reply, "private_directory", check)
    return seen


def window(tmp_path, monkeypatch, binding, **options):
    platform = chain.Platform(tmp_path, monkeypatch, binding, **options)
    path, digest = chain.selection(tmp_path, summary=chain.SUMMARY)
    host, result = platform.window(path, digest)
    return platform, host, result


def crlf(envelope: bytes) -> bytes:
    record = json.loads(envelope)
    stdout = base64.b64decode(record["stdout"]).replace(b"\n", b"\r\n")
    return json.dumps({**record, "stdout": base64.b64encode(stdout).decode("ascii")},
                      sort_keys=True, separators=(",", ":")).encode() + b"\n"


def edit(target: Path, transform) -> None:
    target.write_bytes(transform(target.read_bytes()))


def refused(code: str, *args: Path) -> None:
    with pytest.raises(reply.ReplyRefused) as caught:
        reply.collect(*args)
    assert caught.value.code == code


def test_an_accepted_clean_window_delivers_the_whole_advice_and_refuses_each_tamper(
    tmp_path, monkeypatch, portable_binding, substituted_guard, produced, checked,
):
    packet, record_out, (repository, controller, before, after) = produced
    # At the reply bound: worst-case JSON escaping and non-ASCII, so neither the
    # preview's truncation nor a capture ceiling can shorten what is delivered.
    answer = "\x01" * (route.MODEL_ADVICE_MAX_BYTES - 3) + "\N{SNOWMAN}"
    assert len(answer.encode("utf-8")) == route.MODEL_ADVICE_MAX_BYTES
    platform, host, result = window(tmp_path, monkeypatch, portable_binding, answer=answer)
    assert (result.reason, result.cleanup, result.custody_retained) == (
        "read-settled", "clean", False)
    work, record = platform.custody, result.record
    _, _, stdout = chain.settled_read(platform, host)
    printed = json.loads(stdout)

    delivered = reply.collect(work, record, packet)
    bound = route.bound_values(chain.DEMO)
    assert delivered == {
        "schema_version": 1, "status": "delivered",
        "change": {"before": before, "after": after, "path": "calc.py"},
        "summary_sha256": record_out["summary_sha256"],
        "instruction_digest": str(bound.instruction_digest), "window": record.name,
        "run_id": bound.run_id, "accepted_read_sha256": result.accepted_read_sha256,
        "approval_sha256": platform.approval.sha256, "approval_slot": 1,
        # Exactly as the route printed them: no field added, no None renamed.
        "advice": printed["advice"], "metering": printed["result"]["metering"],
    }
    assert delivered["advice"]["advice"] == answer
    assert delivered["advice"]["reply_bytes"] == route.MODEL_ADVICE_MAX_BYTES
    assert delivered["metering"]["confirmed_charge"] is None
    assert delivered["metering"]["estimate"] is None
    native = next(work.glob("native-*"))
    assert checked == [work, record, packet, native, native / "captures"]
    # Reading changed nothing.
    assert reply.collect(work, record, packet) == delivered
    # A directory the custody check refuses is refused by its own phase's code.
    for target, code in ((record, "REPLY_RECORD_UNPROVED"), (packet, "REPLY_PACKET_MISMATCH"),
                         (native / "captures", "REPLY_EVIDENCE_MISMATCH")):
        def unsafe(path: Path, target=target) -> None:
            if path == target:
                raise ValueError("M9_OWNER_UNSAFE_CUSTODY")

        monkeypatch.setattr(reply, "private_directory", unsafe)
        refused(code, work, record, packet)
    monkeypatch.setattr(reply, "private_directory", lambda path: None)

    copies = iter(range(100))

    def custody(change) -> tuple[Path, Path]:
        into = tmp_path / f"custody-{next(copies)}"
        shutil.copytree(work, into, symlinks=True)
        change(into, into / record.name)
        return into, into / record.name

    def captures(into: Path) -> Path:
        return next(into.glob("native-*/captures"))

    # Control: an unchanged copy delivers, so each refusal below is its tamper's.
    assert reply.collect(*custody(lambda into, moved: None), packet) == {
        **delivered, "window": record.name}
    for change in (
        lambda into, moved: edit(moved / "close.json", lambda raw: raw.replace(
            result.accepted_read_sha256.encode(), b"0" * 64)),
        lambda into, moved: edit(captures(into) / "read-projection.stdout",
                                 lambda raw: raw[:-1] + b" \n"),
        # CRLF producer bytes inside the envelope: a new stdout digest.
        lambda into, moved: edit(captures(into) / "read-original.stdout", crlf),
        # A boolean is not a return code.
        lambda into, moved: edit(captures(into) / "read-projection.status.json",
                                 lambda raw: raw.replace(b'"returncode": 0',
                                                         b'"returncode": false')),
        lambda into, moved: edit(captures(into) / "read-original.stdout",
                                 lambda raw: raw.replace(b'"returncode":0',
                                                         b'"returncode":false')),
        lambda into, moved: (captures(into) / "read-original.stdout").unlink(),
        # Other challenge bytes name other captures.
        lambda into, moved: edit(moved / "challenge.json",
                                 lambda raw: raw.replace(b'"consumer"', b'"consumer" ')),
    ):
        refused("REPLY_EVIDENCE_MISMATCH", *custody(change), packet)
    for change in (
        lambda into, moved: edit(moved / "result.json", lambda raw: raw.replace(
            b'"schema_version": 2', b'"schema_version": 2.0')),
        lambda into, moved: edit(moved / "result.json", lambda raw: raw.replace(
            b'"approval_slot": 1', b'"approval_slot": NaN')),
        lambda into, moved: edit(moved / "result.json", lambda raw: b"[" * 100_000),
    ):
        refused("REPLY_RECORD_UNPROVED", *custody(change), packet)
    # Only the window's own record, named by its nonce, directly under work.
    refused("REPLY_RECORD_UNPROVED", work, work / "result", packet)
    refused("REPLY_RECORD_UNPROVED", tmp_path, record, packet)

    # The packet is exactly the producer's, for the summary the run answered.
    copied = iter(range(100))

    def forged(name: str, transform) -> Path:
        into = tmp_path / f"packet-{next(copied)}"
        shutil.copytree(packet, into)
        edit(into / name, transform)
        return into

    assert reply.collect(work, record, forged("packet.json", lambda raw: raw)) == delivered
    for name, transform in (
        ("packet.json", lambda raw: raw.replace(before.encode(), b"not-a-commit")),
        ("packet.json", lambda raw: raw.replace(b'"schema_version": 1', b'"schema_version": true')),
        ("packet.json", lambda raw: raw.replace(b'"calc.py"', b'"../calc.py"')),
        ("packet.json",
         lambda raw: raw.replace(b'"instruction_bytes": ', b'"instruction_bytes": 1')),
        ("instruction.txt", lambda raw: raw + b" "),
        ("summary.json", lambda raw: raw.replace(b"\n", b"\r\n")),
    ):
        refused("REPLY_PACKET_MISMATCH", work, record, forged(name, transform))
    # A real packet for another change binds another run: the accepted advice is refused.
    other = tmp_path / "packet-reversed"
    producer.prepare(repository, controller, after, before, "calc.py", other)
    refused("REPLY_ADVICE_INVALID", work, record, other)

    # A window that is no longer clean, or whose marker still names it, is not delivered.
    for change in (
        lambda into, moved: edit(moved / "result.json", lambda raw: raw.replace(
            b'"custody_release_eligible": true', b'"custody_release_eligible": false')),
        lambda into, moved: (into / "active").write_bytes(moved.name.encode()),
    ):
        into, moved = custody(change)
        outcome = reply.collect(into, moved, packet)
        assert outcome["status"] == "not-delivered" and "advice" not in outcome
        assert outcome["result"]["accepted_read_sha256"] == result.accepted_read_sha256


def test_a_window_that_ends_before_its_challenge_is_not_delivered(
    tmp_path, produced, checked,
):
    """The real supervisor, through its own fake boundary, losing qualification."""
    packet, _, _ = produced
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    result = Fake(work, "qualification lost").run()
    assert result.reason == "qualification-unproved"
    assert not (result.record / "challenge.json").exists()
    outcome = reply.collect(work, result.record, packet)
    assert outcome["status"] == "not-delivered" and "advice" not in outcome
    assert outcome["result"] == json.loads((result.record / "result.json").read_bytes())
    assert outcome["result"]["approval_slot"] is None
    # No challenge: no captures are looked for.
    assert checked == [work, result.record, packet]


def test_a_failed_reply_is_not_delivered_and_keeps_its_disposition(
    tmp_path, monkeypatch, portable_binding, substituted_guard, produced, checked, capsys,
):
    packet, _, _ = produced
    platform, _, result = window(tmp_path, monkeypatch, portable_binding, answer="")
    assert result.accepted_read_sha256 is None
    outcome = reply.collect(platform.custody, result.record, packet)
    assert outcome["status"] == "not-delivered" and "advice" not in outcome
    assert outcome["result"] == json.loads((result.record / "result.json").read_bytes())
    assert outcome["result"]["approval_suspended"] is True

    # The command prints the reply, or only a refusal's code.
    argv = ["--work", str(platform.custody), "--record", str(result.record)]
    assert reply.main([*argv, "--packet", str(packet)]) == 0
    assert json.loads(capsys.readouterr().out) == outcome
    assert reply.main([*argv, "--packet", str(tmp_path / "absent")]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "refused", "reason": "REPLY_PACKET_MISMATCH"}

    # A closed summary within the read bound whose framed instruction is over its
    # bound: the route's named ContractViolation is the packet's refusal, never a
    # traceback past the command.
    names = {kind: [kind[0] + f"{n:02d}" + "\N{GREEK SMALL LETTER LAMDA}" * 18 + "x" * 59
                    for n in range(25)] for kind in ("added", "removed", "changed")}
    wide = route.ChangeSummaryV2.model_validate({
        **json.loads((packet / "summary.json").read_bytes()), "symbols": names,
        "symbols_partial": True, "kinds": None, "changed_parts": None,
    })
    raw = producer._wire(wide.model_dump(mode="json"))
    assert len(raw) <= reply.SUMMARY_LIMIT
    with pytest.raises(route.ContractViolation):
        route.bound_values(wide)
    oversized = tmp_path / "packet-oversized"
    shutil.copytree(packet, oversized)
    (oversized / "summary.json").write_bytes(raw)
    edit(oversized / "packet.json", lambda old: old.replace(
        json.loads(old)["summary_sha256"].encode(), reply.hashlib.sha256(raw).hexdigest().encode()))
    assert reply.main([*argv, "--packet", str(oversized)]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "refused", "reason": "REPLY_PACKET_MISMATCH"}
