"""Exercise the exact manual decision and custody boundaries."""

import os
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from scripts.ops import m9_owner_approval as approval
from scripts.ops.claude_read_commands import sha
from scripts.ops.claude_read_session import json_bytes


def test_manual_decision_approves_only_one_current_challenge(tmp_path):
    owner = approval.ManualApproval(tmp_path)
    expires = datetime.now(UTC) + timedelta(minutes=2)
    payload = {"approval_not_after": expires.isoformat(), "pins_sha256": sha(b"checked-pins")}
    challenge = json_bytes(payload)
    digest = sha(challenge)
    approved = json_bytes({"decision": "approve", "challenge_sha256": digest})
    deadline = time.monotonic() + 30
    accepted = owner.verify(challenge, approved, deadline)
    assert accepted is not None
    assert accepted.challenge_sha256 == digest and accepted.expires_at == expires
    assert accepted.decision_sha256 == sha(approved)
    assert owner.verify(challenge, approved, time.monotonic() - 1) is None
    assert owner.verify(challenge, b'{"owner":"approved"}', deadline) is None
    declined = json_bytes({"decision": "decline", "challenge_sha256": digest})
    assert owner.verify(challenge, declined, deadline) is None
    changed = json_bytes({**payload, "pins_sha256": sha(b"different-pins")})
    assert owner.verify(changed, approved, deadline) is None
    stale = json_bytes({**payload, "approval_not_after": (expires - timedelta(days=1)).isoformat()})
    stale_approval = json_bytes({"decision": "approve", "challenge_sha256": sha(stale)})
    assert owner.verify(stale, stale_approval, deadline) is None
    with pytest.raises(ValueError, match="PINS_UNPROVED"):
        owner.await_decision(challenge, b"different-pins", deadline)
    assert not list(tmp_path.iterdir())


def test_changed_displayed_pins_refuse_after_approval_is_published(tmp_path, monkeypatch):
    pins = b"original"
    challenge = json_bytes({"pins_sha256": sha(pins)})
    packet = tmp_path / sha(challenge)

    def publish(_):
        (packet / "pins.json").write_bytes(b"modified")
        (packet / "approval.json").write_bytes(json_bytes({
            "decision": "approve", "challenge_sha256": sha(challenge),
        }))

    monkeypatch.setattr(approval.time, "sleep", publish)
    with pytest.raises(ValueError, match="PINS_CHANGED"):
        approval.ManualApproval(tmp_path).await_decision(challenge, pins, time.monotonic() + 1)


def test_verifier_custody_refuses_shared_writes():
    with tempfile.TemporaryDirectory(dir=Path.home().resolve(strict=True)) as tmp:
        private = Path(tmp)
        approval.private_directory(private)
        if os.name == "nt":
            import ntsecuritycon as rights
            import win32security as security

            mask = security.DACL_SECURITY_INFORMATION
            acl = security.GetNamedSecurityInfo(
                tmp, security.SE_FILE_OBJECT, mask
            ).GetSecurityDescriptorDacl()
            everyone = security.ConvertStringSidToSid("S-1-1-0")
            acl.AddAccessAllowedAce(security.ACL_REVISION, rights.FILE_ADD_FILE, everyone)
            security.SetNamedSecurityInfo(tmp, security.SE_FILE_OBJECT, mask, None, None, acl, None)
        else:
            private.chmod(0o770)
        with pytest.raises(ValueError, match="UNSAFE_CUSTODY"):
            approval.private_directory(private)
