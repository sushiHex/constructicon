"""A parked unit carries the evidence its own reason needs, and nothing else."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from constructicon.core.address import ExecutionPath, ScopePath
from constructicon.core.identity import digest
from constructicon.core.run import ParkedUnit

PATH = ExecutionPath(scope=ScopePath(segments=("review",)))
REQUEST = digest("channel-message", 1, {"request": "advice"})


def test_a_historical_policy_exhausted_payload_parses_unchanged() -> None:
    """M4 wrote exactly these three keys; they must keep their meaning."""

    historical = {
        "path": PATH.model_dump(mode="json"),
        "reason": "policy_exhausted",
        "completed_iterations": 3,
    }
    unit = ParkedUnit.model_validate(historical)
    assert unit.reason == "policy_exhausted"
    assert unit.completed_iterations == 3
    assert unit.waiting_on is None  # nothing was invented


def test_policy_exhausted_parking_must_record_how_far_it_got() -> None:
    with pytest.raises(ValidationError, match="records completed_iterations"):
        ParkedUnit(path=PATH, reason="policy_exhausted")


@pytest.mark.parametrize("reason", ["awaiting_advisor", "awaiting_approval"])
def test_a_wait_must_record_the_request_it_waits_on(reason: str) -> None:
    """`waiting_on` is what lets recovery reconstruct a wake from durable facts."""

    with pytest.raises(ValidationError, match="records the request it waits on"):
        ParkedUnit(path=PATH, reason=reason)
    unit = ParkedUnit(path=PATH, reason=reason, waiting_on=REQUEST)
    assert unit.waiting_on == REQUEST
    assert unit.completed_iterations is None


@pytest.mark.parametrize(
    "reason",
    ["policy_exhausted", "budget_exhausted", "operator_intervention"],
)
def test_a_park_that_is_not_waiting_cannot_claim_a_request(reason: str) -> None:
    """A phantom `waiting_on` would make the wake scan chase a reply forever."""

    with pytest.raises(ValidationError, match="not waiting on a request"):
        ParkedUnit(
            path=PATH,
            reason=reason,
            completed_iterations=1,
            waiting_on=REQUEST,
        )
