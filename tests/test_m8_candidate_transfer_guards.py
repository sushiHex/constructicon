"""Direct refusal evidence for candidate-transfer identity and digest guards."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest
from scripts import m8_candidate_transfer as transfer


def pinned_commit() -> tuple[bytes, bytes, transfer.Pins]:
    base = "a" * 40
    vector = b'{"version":1,"cases":[]}'
    raw = (b"tree " + b"b" * 40 + b"\nparent " + base.encode()
           + b"\nauthor tester <test@example.invalid> 1767225600 +0000"
           + b"\ncommitter tester <test@example.invalid> 1767225600 +0000\n\naccepted\n")
    pins = transfer.Pins(
        candidate=transfer.object_oid("commit", raw), base=base,
        run_id="run-" + "c" * 32,
        input_sha256=hashlib.sha256(vector).hexdigest(), render_sha256="d" * 64,
    )
    return raw, vector, pins


def test_commit_bytes_must_match_raw_candidate_oid():
    raw, _vector, pins = pinned_commit()
    with pytest.raises(transfer.TransferRefused, match="candidate-identity"):
        transfer.commit_tree(raw, replace(pins, candidate="e" * 40))


def test_artifact_vector_must_match_pinned_input_digest():
    raw, vector, pins = pinned_commit()
    with pytest.raises(transfer.TransferRefused, match="vector-identity"):
        transfer.artifact_bytes(raw, vector, replace(pins, input_sha256="e" * 64))


def test_artifact_historical_projection_must_match_pins():
    raw, vector, pins = pinned_commit()
    value = json.loads(transfer.artifact_bytes(raw, vector, pins))
    value["historical"]["render_sha256"] = "e" * 64
    artifact = transfer.canonical(value)
    with pytest.raises(transfer.TransferRefused, match="historical-pins"):
        transfer.parse_artifact(artifact, pins)
