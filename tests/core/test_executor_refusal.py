"""Optional bounded executor guard facts preserve the uncoded wire exactly."""

import pytest
from pydantic import ValidationError

from constructicon.core.executor import ExecutorError, ExecutorFailure
from constructicon.core.refusal import MAX_REFUSAL_CODES, RefusalCode


def test_uncoded_executor_error_keeps_exact_historical_shape():
    error = ExecutorError(kind="unavailable", detail="refused")
    assert error.model_dump(mode="json") == {
        "kind": "unavailable", "detail": "refused", "exit_code": None,
        "timed_out_after_s": None, "produced_output": None,
    }
    assert "refusal" not in ExecutorFailure(error=error).model_dump(mode="json")["error"]


def test_executor_codes_are_closed_and_bounded_on_serialization_and_readback():
    codes = (RefusalCode.CALLBACK_WORKER_NONZERO,) * (MAX_REFUSAL_CODES - 1)
    value = ExecutorError(kind="exit", detail="refused", refusal=codes)
    assert ExecutorError.model_validate_json(value.model_dump_json()) == value
    assert value.model_dump(mode="json")["refusal"] == [code.value for code in codes]
    with pytest.raises(ValidationError):
        ExecutorError(kind="exit", detail="refused", refusal=(*codes, codes[0]))
    with pytest.raises(ValidationError):
        ExecutorError.model_validate({"kind": "exit", "detail": "refused",
                                      "refusal": ["private free text"]})
