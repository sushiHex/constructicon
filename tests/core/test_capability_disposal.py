"""Disposal requests retain exact bounded administrative intent."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from constructicon.core import control
from constructicon.core.identity import canonical_json


def request_model():
    model = getattr(control, "CapabilityDisposalRequest", None)
    assert model is not None, "one strict disposal request contract is required"
    return model


def test_disposal_request_canonicalizes_pair_order_without_repairing_members():
    raw = {
        "run_id": "run-disposal",
        "reason": "cleanup remains unavailable",
        "pairs": [
            {"lease_id": "second", "acquisition_epoch": 2},
            {"lease_id": "first", "acquisition_epoch": 1},
        ],
    }
    request = request_model().model_validate_json(canonical_json(raw))
    assert [pair.lease_id for pair in request.pairs] == ["first", "second"]
    assert request.reason == raw["reason"]
    with pytest.raises(ValidationError):
        request_model().model_validate_json(canonical_json({**raw, "pairs": raw["pairs"] * 2}))


@pytest.mark.parametrize(
    "change",
    (
        {"pairs": []},
        {"pairs": [{"lease_id": "x", "acquisition_epoch": True}]},
        {"pairs": [{"lease_id": "", "acquisition_epoch": 1}]},
        {"pairs": [{"lease_id": "x" * 201, "acquisition_epoch": 1}]},
        {"reason": ""},
        {"reason": "x" * 1001},
        {"reason": "line\nbreak"},
        {"actor_id": "caller-authored"},
    ),
)
def test_disposal_request_refuses_invalid_input(change):
    raw = {
        "run_id": "run-disposal",
        "pairs": [{"lease_id": "x", "acquisition_epoch": 1}],
        "reason": "bounded reason",
        **change,
    }
    with pytest.raises(ValidationError):
        request_model().model_validate_json(canonical_json(raw))


def test_disposal_request_bounds_bind_at_one_hundred_pairs_and_scalar_reason():
    raw = {
        "run_id": "run-disposal",
        "reason": "🙂" * 1000,
        "pairs": [
            {"lease_id": f"lease-{index:03}", "acquisition_epoch": 1} for index in range(100)
        ],
    }
    request = request_model().model_validate_json(canonical_json(raw))
    assert len(request.pairs) == 100
    assert len(request.reason.encode("utf-8")) == 4000
    with pytest.raises(ValidationError):
        request_model().model_validate_json(
            canonical_json(
                {
                    **raw,
                    "pairs": [*raw["pairs"], {"lease_id": "last", "acquisition_epoch": 1}],
                }
            )
        )


def test_disposal_receipt_rejects_an_extent_larger_than_its_bounded_batch(monkeypatch):
    model = getattr(control, "CapabilityDisposalRecorded", None)
    assert model is not None
    calls = []

    def observed_range(*arguments):
        calls.append(arguments)
        assert arguments == (1,), "receipt allocation must derive from bounded pair count"
        return range(*arguments)

    monkeypatch.setattr(control, "range", observed_range, raising=False)
    raw = {
        "command_id": "command",
        "run_id": "run-disposal",
        "manifest_hash": "sha256:" + "1" * 64,
        "owner_epoch": 1,
        "before_event_seq": 0,
        "audit_event_seq": 102,
        "pairs": [{"lease_id": "x", "acquisition_epoch": 1}],
        "row_baseline_hashes": ["sha256:" + "2" * 64],
        "transition_event_seqs": [1],
    }
    with pytest.raises(ValidationError):
        model.model_validate_json(canonical_json(raw))
    assert calls == []


def test_exact_positive_epoch_is_not_silently_tightened_to_sqlite_integer_range():
    request = request_model().model_validate_json(
        canonical_json(
            {
                "run_id": "run-disposal",
                "reason": "exact selection",
                "pairs": [{"lease_id": "x", "acquisition_epoch": 2**100}],
            }
        )
    )
    assert request.pairs[0].acquisition_epoch == 2**100
