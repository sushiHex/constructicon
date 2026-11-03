"""Offline verification exercises the same streaming verifier as the operator."""

import hashlib

import pytest

from scripts.ci.verify_m8_pi_local_artifacts import verify


def test_verifier_requires_both_exact_size_and_digest(tmp_path):
    path = tmp_path / "artifact"
    data = b"fixture artifact"
    path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    assert verify(path, len(data), digest) == {"bytes": len(data), "sha256": digest}
    with pytest.raises(ValueError):
        verify(path, len(data) + 1, digest)
    with pytest.raises(ValueError):
        verify(path, len(data), "0" * 64)
