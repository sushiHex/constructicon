"""Use ephemeral keys with the same verifier as the operator entry."""

import os
import subprocess
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from scripts.ops import m9_owner_approval as approval
from scripts.ops.claude_read_commands import sha
from scripts.ops.claude_read_session import json_bytes


def test_owner_signature_cannot_be_replaced_by_a_local_assertion(tmp_path):
    if not approval.KEYGEN.is_file():
        pytest.skip("OpenSSH ssh-keygen is not installed")

    def key(name):
        path = tmp_path / name
        subprocess.run(
            [str(approval.KEYGEN), "-q", "-t", "ed25519", "-N", "", "-f", str(path)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=True,
            timeout=10,
        )
        return path, b" ".join(path.with_suffix(".pub").read_bytes().split()[:2])

    def sign(path, namespace, challenge):
        return subprocess.run(
            [str(approval.KEYGEN), "-Y", "sign", "-f", str(path), "-n", namespace],
            input=challenge,
            capture_output=True,
            check=True,
            timeout=10,
        ).stdout

    private, public = key("owner")
    other, other_public = key("operator")
    selected = approval.SignedApproval(tmp_path, public, sha(public))
    with pytest.raises(ValueError, match="KEY_NOT_PINNED"):
        approval.SignedApproval(tmp_path, other_public, sha(public))
    expires = datetime.now(UTC) + timedelta(minutes=2)
    payload = {"approval_not_after": expires.isoformat(), "pins_sha256": sha(b"checked-pins")}
    challenge = json_bytes(payload)
    signature = sign(private, approval.NAMESPACE, challenge)
    deadline = time.monotonic() + 30
    accepted = selected.verify(challenge, signature, deadline)
    assert accepted is not None
    assert accepted.challenge_sha256 == sha(challenge) and accepted.expires_at == expires
    assert selected.verify(challenge, sign(other, approval.NAMESPACE, challenge), deadline) is None
    assert selected.verify(challenge, sign(private, "wrong-scope", challenge), deadline) is None
    assert selected.verify(json_bytes({**payload, "nonce": "changed"}), signature, deadline) is None
    assert selected.verify(challenge, b'{"owner":"approved"}', deadline) is None
    stale = json_bytes({**payload, "approval_not_after": (expires - timedelta(days=1)).isoformat()})
    assert selected.verify(stale, sign(private, approval.NAMESPACE, stale), deadline) is None


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
