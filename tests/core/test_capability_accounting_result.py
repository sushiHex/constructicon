"""Result v2 is an explicit wire family; old bytes do not imply zero accounting."""

from __future__ import annotations

import pytest

from constructicon.core import control
from constructicon.core.identity import canonical_json

OLD = {
    "run_id": "run-old-result",
    "status": "running",
    "outputs": {},
    "failures": {},
    "detail": None,
}


def test_old_result_decoder_preserves_exact_unversioned_shape() -> None:
    assert hasattr(control, "parse_run_result_preview")
    parsed = control.parse_run_result_preview(canonical_json(OLD))
    assert isinstance(parsed, control.RunResultPreview)
    assert parsed.model_dump(mode="json") == OLD
    assert "capability_accounting" not in parsed.model_dump(mode="json")


@pytest.mark.parametrize("version", (True, 2.0, "2", 3))
def test_result_version_is_exact_and_never_guessed(version: object) -> None:
    assert hasattr(control, "parse_run_result_preview")
    with pytest.raises(ValueError):
        control.parse_run_result_preview(canonical_json({**OLD, "result_schema_version": version}))


@pytest.mark.parametrize("version", (True, 2.0, "2", 3))
def test_v2_model_itself_refuses_inexact_version(version):
    payload = {
        **OLD,
        "result_schema_version": 2,
        "failures_partial": False,
        "capability_accounting": {
            "active_count": 0,
            "disposed_count": 0,
            "opaque_lost_count": 0,
            "lost_count": 0,
            "through_event_seq": 0,
            "detail": {
                "uri": "constructicon://runs/run-old-result/accounting/0",
                "digest": "sha256:" + "0" * 64,
            },
        },
    }
    accepted = control.RunResultPreviewV2.model_validate_json(canonical_json(payload))
    assert accepted.result_schema_version == 2
    payload["result_schema_version"] = version
    with pytest.raises(ValueError):
        control.RunResultPreviewV2.model_validate_json(canonical_json(payload))
