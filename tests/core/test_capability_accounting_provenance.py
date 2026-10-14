"""Storage era contracts are exact facts, not coerced version hints."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from constructicon.core import control
from constructicon.core.identity import digest


@pytest.mark.parametrize("floor", (True, 1.0, -1, "0"))
def test_capability_accounting_era_requires_an_exact_nonnegative_floor(floor: object) -> None:
    assert hasattr(control, "CapabilityAccountingEra")
    model = control.CapabilityAccountingEra
    good = {
        "run_id": "run-era-contract",
        "world_hash": str(digest("run-world-test", 1, {})),
        "source": "schema7-migration",
        "floor": 1,
        "inventory_hash": str(digest("inventory-test", 1, [])),
    }
    assert model.model_validate(good).floor == 1
    with pytest.raises(ValidationError):
        model.model_validate({**good, "floor": floor})
