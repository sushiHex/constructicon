"""CheckResult keeps ``status`` and ``ok`` in lockstep after validation (#370)."""

from __future__ import annotations

import copy
from typing import get_args

import pytest
from pydantic import ValidationError

from constructicon.core.effect import CheckResult, CheckStatus

BASE = {"name": "n", "detail": "", "elapsed_s": 0}


def _make(**kw: object) -> CheckResult:
    return CheckResult.model_validate({**BASE, **kw})


@pytest.mark.parametrize("raw", [True, "true", "True", 1, "yes"])
def test_legacy_truthy_ok_without_status_passes(raw: object) -> None:
    r = _make(ok=raw)
    assert (r.status, r.ok) == ("passed", True)


@pytest.mark.parametrize("raw", [False, "false", "False", 0, "no"])
def test_legacy_falsy_ok_without_status_fails(raw: object) -> None:
    # Regression: the string "false" used to yield status='passed', ok=False.
    r = _make(ok=raw)
    assert (r.status, r.ok) == ("failed", False)


def test_uncoercible_ok_is_refused() -> None:
    with pytest.raises(ValidationError):
        _make(ok="maybe")
    with pytest.raises(ValidationError):
        _make(ok="maybe", status="passed")


@pytest.mark.parametrize("status", get_args(CheckStatus))
def test_status_only_derives_ok(status: str) -> None:
    r = _make(status=status)
    assert r.status == status
    assert r.ok is (status == "passed")


@pytest.mark.parametrize("status", get_args(CheckStatus))
@pytest.mark.parametrize("ok", [True, False, "true", "false"])
def test_both_fields_agree_or_are_refused(status: str, ok: object) -> None:
    coerced = ok in (True, "true")
    if coerced == (status == "passed"):
        r = _make(status=status, ok=ok)
        assert (r.status, r.ok) == (status, coerced)
    else:
        with pytest.raises(ValidationError, match="contradicts"):
            _make(status=status, ok=ok)


def test_omitting_both_is_refused() -> None:
    with pytest.raises(ValidationError):
        CheckResult.model_validate(BASE)


def test_unknown_status_is_refused() -> None:
    with pytest.raises(ValidationError):
        _make(status="bogus")
    with pytest.raises(ValidationError):
        _make(status="bogus", ok=True)


def test_caller_input_is_not_mutated() -> None:
    for payload in (
        {**BASE, "ok": "false"},
        {**BASE, "status": "failed"},
        {**BASE, "status": "passed", "ok": "true"},
    ):
        before = copy.deepcopy(payload)
        CheckResult.model_validate(payload)
        assert payload == before


def test_roundtrip_of_dump_is_stable() -> None:
    for status in get_args(CheckStatus):
        r = _make(status=status)
        assert CheckResult.model_validate(r.model_dump(mode="json")) == r
