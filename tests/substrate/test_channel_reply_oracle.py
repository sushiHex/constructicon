"""The channel stored-reply exam: one exact whole-module extraction, stdlib only.

The positive candidate is a hand-written refactor kept as test data. It is never
produced by the oracle's expected-tree builder; its behavior is calibrated
separately by the shared channel contract and the differential fault battery.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from constructicon.api.plan_manifest_application import CHANNEL_INSTRUCTION, channel_reply_checks
from constructicon.core.errors import ContractViolation
from constructicon.core.maintenance import CHANNEL_TARGET_PATH
from constructicon.substrate.gates import channel_reply
from constructicon.substrate.gates.channel_reply import (
    ExtractionRefusal,
    check_extraction,
    expected_module,
    parse_source,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/channel_stored_reply/in_process_candidate.py.txt"
BASE = (ROOT / CHANNEL_TARGET_PATH).read_bytes().replace(b"\r\n", b"\n")
CANDIDATE = FIXTURE.read_bytes().replace(b"\r\n", b"\n")
HELPER = (
    b"    def _stored_reply(\n"
    b"        self,\n"
    b"        request: ChannelMessage,\n"
    b"        request_id: Digest,\n"
    b"    ) -> ChannelMessage | None:\n"
    b"        if request.reply_port is None:\n"
    b'            raise JournalDamaged(f"channel request {request_id} pins no reply port")\n'
    b"        reply_id = reply_message_id(\n"
    b"            request_id=request.message_id,\n"
    b"            reply_port=request.reply_port,\n"
    b"        )\n"
    b"        return self._by_id.get(str(reply_id))\n"
    b"\n"
)
SMUGGLE = b"# coding: unicode_escape\n# comment\\u000ax = 1\n"


def edit(old: bytes, new: bytes, source: bytes = CANDIDATE) -> bytes:
    assert source.count(old) == 1, old
    return source.replace(old, new, 1)


def refusal(candidate: bytes, base: bytes = BASE) -> str:
    with pytest.raises(ExtractionRefusal) as refused:
        check_extraction(base, candidate)
    return refused.value.code


def test_fixture_is_test_data_and_the_target_stays_unrefactored():
    assert b"_stored_reply" not in BASE and BASE.count(b"pins no reply port") == 2
    assert CANDIDATE.count(b"self._stored_reply(request, ") == 2
    assert HELPER in CANDIDATE and CANDIDATE.count(b"pins no reply port") == 1
    # The instruction spells the oracle's one helper; the fixture matches it by hand.
    assert channel_reply.HELPER_SOURCE.splitlines()[0] in CHANNEL_INSTRUCTION


def test_hand_written_candidate_is_accepted_with_worker_receipt():
    report = check_extraction(BASE, CANDIDATE)
    assert report == {
        "passed": True, "check": "channel-stored-reply-exact-extraction",
        "python": sys.version, "base_sha256": hashlib.sha256(BASE).hexdigest(),
        "candidate_sha256": hashlib.sha256(CANDIDATE).hexdigest(),
    }


@pytest.mark.parametrize("spelling", ["utf8-cookie", "comment", "one-line-call", "blank-lines"])
def test_spelling_that_yields_the_expected_tree_is_not_refused(spelling):
    if spelling == "utf8-cookie":
        candidate = b"# -*- coding: utf-8 -*-\n" + CANDIDATE
    elif spelling == "comment":
        # Plain UTF-8: the escape stays a comment, exactly as the loader reads it.
        candidate = CANDIDATE + b"# note\\u000aSMUGGLED = 1\n"
    elif spelling == "one-line-call":
        candidate = edit(
            b"        reply_id = reply_message_id(\n"
            b"            request_id=request.message_id,\n"
            b"            reply_port=request.reply_port,\n"
            b"        )\n        return",
            b"        reply_id = reply_message_id(request_id=request.message_id, "
            b"reply_port=request.reply_port)\n        return",
        )
    else:
        candidate = edit(b"    def _stored_reply(", b"\n\n    def _stored_reply(")
    assert check_extraction(BASE, candidate)["passed"] is True


def _move_helper_before(anchor: bytes) -> bytes:
    without = edit(HELPER, b"")
    return edit(anchor, HELPER + anchor, without)


def _helper_outside_lock() -> bytes:
    return edit(
        b"            request = self._complete_request(request)\n"
        b"            stored = self._stored_reply(request, request_id)\n"
        b"            if stored is None:\n"
        b"                return None\n"
        b"            return _detached_message(self._complete_reply(request, stored))\n",
        b"            request = self._complete_request(request)\n"
        b"        stored = self._stored_reply(request, request_id)\n"
        b"        with self._lock:\n"
        b"            if stored is None:\n"
        b"                return None\n"
        b"            return _detached_message(self._complete_reply(request, stored))\n",
    )


REFUSED = {
    "noop": lambda: BASE,
    "unused-helper": lambda: edit(
        b"\n\ndef _detached_message(", b"\n" + HELPER + b"\ndef _detached_message(", BASE,
    ).replace(b"\n\n" + HELPER, b"\n" + HELPER),
    "one-caller-only": lambda: edit(
        b"                reply = self._stored_reply(request, message_id)\n",
        b"                if request.reply_port is None:\n"
        b'                    raise JournalDamaged(f"channel request {message_id} '
        b'pins no reply port")\n'
        b"                reply_id = reply_message_id(\n"
        b"                    request_id=request.message_id,\n"
        b"                    reply_port=request.reply_port,\n"
        b"                )\n"
        b"                reply = self._by_id.get(str(reply_id))\n",
    ),
    "extra-edit-elsewhere": lambda: edit(b"if max_batch <= 0:", b"if max_batch < 0:"),
    "changed-fault-text": lambda: edit(b"{request_id} pins no reply port",
                                       b"{request_id} has no reply port"),
    "fault-identifier": lambda: edit(b"{request_id} pins no reply port",
                                     b"{request.message_id} pins no reply port"),
    "reordered-statement": lambda: edit(
        b"            self._validate_history()\n"
        b"            request = self._by_id.get(str(request_id))\n"
        b"            if request is None:\n                return None\n",
        b"            request = self._by_id.get(str(request_id))\n"
        b"            self._validate_history()\n"
        b"            if request is None:\n                return None\n",
    ),
    "call-outside-lock": _helper_outside_lock,
    "wrong-helper-name": lambda: CANDIDATE.replace(b"_stored_reply", b"_stored_reply_for"),
    "wrong-position": lambda: _move_helper_before(b"    def _complete_reply(\n"),
    "swapped-arguments": lambda: edit(b"self._stored_reply(request, request_id)",
                                      b"self._stored_reply(request_id, request)"),
    "helper-annotation": lambda: edit(
        b"    ) -> ChannelMessage | None:\n        if request.reply_port",
        b"    ) -> ChannelMessage:\n        if request.reply_port",
    ),
    "helper-docstring": lambda: edit(
        b"    ) -> ChannelMessage | None:\n        if request.reply_port",
        b'    ) -> ChannelMessage | None:\n        """Look up."""\n        if request.reply_port',
    ),
    "added-class-decorator": lambda: edit(b"\nclass InProcessChannel:",
                                          b"\n@final\nclass InProcessChannel:"),
    "helper-decorator": lambda: edit(b"    def _stored_reply(",
                                     b"    @cache\n    def _stored_reply("),
    "changed-default": lambda: edit(b"max_batch: int = MAX_INBOX_BATCH,", b"max_batch: int = 1,"),
    "class-assignment": lambda: edit(b"    def __init__(\n",
                                     b"    smuggled = True\n\n    def __init__(\n"),
    "duplicate-class": lambda: CANDIDATE + b"\n\nclass InProcessChannel:\n    pass\n",
    "module-edit": lambda: CANDIDATE + b"\nSMUGGLED = 1\n",
    "unicode-escape-smuggling": lambda: (
        b"# coding: unicode_escape\n" + CANDIDATE + b"# note\\u000aSMUGGLED = 1\n"
    ),
}


@pytest.mark.parametrize("name", sorted(REFUSED))
def test_whole_module_equality_refuses_every_other_tree(name):
    candidate = REFUSED[name]()
    assert candidate != CANDIDATE
    assert refusal(candidate) == "candidate-differs"


def test_unicode_escape_raw_bytes_resolve_the_cookie_like_the_loader():
    tree = parse_source(SMUGGLE, "candidate")
    assert [type(node) for node in tree.body] == [ast.Assign]
    # The decoded-str view sees only comments: comparing it would hide the code.
    assert ast.parse(SMUGGLE.decode("utf-8")).body == []


@pytest.mark.parametrize(("candidate", "code"), [
    (b"def broken(:\n", "candidate-unparsable"),
    (b"x = 1\0\n", "candidate-unparsable"),
    (b"#" * (channel_reply.MAX_SOURCE_BYTES + 1), "candidate-too-large"),
], ids=["syntax", "nul", "oversized"])
def test_unparsable_or_unbounded_candidates_refuse_by_name(candidate, code):
    assert refusal(candidate) == code


def test_bound_binds_exactly_at_its_limit():
    padded = CANDIDATE + b"#" * (channel_reply.MAX_SOURCE_BYTES - len(CANDIDATE))
    assert len(padded) == channel_reply.MAX_SOURCE_BYTES
    assert check_extraction(BASE, padded)["passed"] is True
    assert refusal(padded + b"#") == "candidate-too-large"


@pytest.mark.parametrize(("base", "code"), [
    (CANDIDATE, "base-has-helper"),
    (BASE.replace(b"    def _complete_message(", b"    def _complete_any("), "base-anchor-missing"),
    (BASE.replace(b'f"channel request {message_id} pins no reply port"',
                  b'f"channel request {message_id} lacks a reply port"'), "base-block-missing"),
    (BASE + b"\n\nclass InProcessChannel:\n    pass\n", "base-class-missing"),
], ids=["has-helper", "no-anchor", "no-block", "duplicate-class"])
def test_a_base_the_one_rewrite_cannot_apply_to_is_refused(base, code):
    with pytest.raises(ExtractionRefusal) as refused:
        expected_module(base)
    assert refused.value.code == code


def _tree(tmp_path: Path, files: dict[str, bytes]) -> bytes:
    inventory = b""
    for name, raw in sorted(files.items()):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        oid = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
        inventory += f"100644 blob {oid}\t{name}\0".encode()
    return inventory


def test_host_checks_refuse_a_base_with_the_helper_or_a_foreign_target_mode(tmp_path):
    inventory = _tree(tmp_path, {CHANNEL_TARGET_PATH: BASE})
    with pytest.raises(ContractViolation, match="base-has-helper"):
        channel_reply_checks(CANDIDATE, hashlib.sha256(CANDIDATE).hexdigest(), inventory, "sha1")
    with pytest.raises(ContractViolation, match="pinned regular base blob"):
        channel_reply_checks(BASE, hashlib.sha256(BASE).hexdigest(),
                             inventory.replace(b"100644", b"100755"), "sha1")


@pytest.mark.parametrize("change", [None, "noop", "second-file", "other-edit", "removed",
                                    "smuggled", "mode"])
def test_gate_program_pins_inventory_before_the_exact_extraction(tmp_path, change):
    if change == "mode" and os.name != "posix":
        pytest.skip("an executable bit is observable only on POSIX; Linux CI runs this case")
    inventory = _tree(tmp_path, {CHANNEL_TARGET_PATH: BASE, "README.txt": b"unchanged\n"})
    checks = channel_reply_checks(BASE, hashlib.sha256(BASE).hexdigest(), inventory, "sha1")
    assert [spec.name for spec in checks] == ["channel-stored-reply-exact-extraction"]
    target = tmp_path / CHANNEL_TARGET_PATH
    target.write_bytes(CANDIDATE)
    if change == "noop":
        target.write_bytes(BASE)
    elif change == "second-file":
        (tmp_path / "extra.py").write_bytes(b"raise RuntimeError('must never run')\n")
    elif change == "other-edit":
        (tmp_path / "README.txt").write_bytes(b"changed\n")
    elif change == "removed":
        (tmp_path / "README.txt").unlink()
    elif change == "smuggled":
        target.write_bytes(REFUSED["unicode-escape-smuggling"]())
    elif change == "mode":
        target.chmod(0o755)
    result = subprocess.run((sys.executable, *checks[0].argv[1:]), cwd=tmp_path,
        stdin=subprocess.DEVNULL, capture_output=True, timeout=60, check=False)
    if change is None:
        assert result.returncode == 0, result.stderr.decode()
        report = json.loads(result.stdout)
        assert report["passed"] is True and report["python"] == sys.version
        assert report["candidate_sha256"] == hashlib.sha256(CANDIDATE).hexdigest()
    else:
        assert result.returncode != 0 and not result.stdout
