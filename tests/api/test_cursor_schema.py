"""Cursor schema 2 is exact, strict, and calibrated as an error check."""

from __future__ import annotations

import base64
import json

import pytest

from constructicon.api.cursor import CURSOR_SCHEMA_VERSION, CursorCodec, CursorFault
from constructicon.core.control import ControlCode


def _decode(token: str) -> dict[str, object]:
    padded = token + "=" * (-len(token) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def _encode(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def test_cursor_schema_2_uses_a_checksum_not_an_authority_claim() -> None:
    codec = CursorCodec()
    token = codec.encode(
        actor_id="static:reader",
        kind="runs",
        query={"statuses": []},
        upper_bound=["2026-01-01T00:00:00+00:00", "run-z"],
        last_key=None,
    )
    payload = _decode(token)
    assert payload["schema_version"] == CURSOR_SCHEMA_VERSION == 2
    assert "checksum" in payload
    assert "check" not in payload


@pytest.mark.parametrize("schema_version", [1, 3])
def test_cursor_rejects_old_and_future_schemas(schema_version: int) -> None:
    codec = CursorCodec()
    token = codec.encode(
        actor_id="static:reader",
        kind="runs",
        query={},
        upper_bound=None,
        last_key=None,
    )
    payload = _decode(token)
    payload["schema_version"] = schema_version
    with pytest.raises(CursorFault) as caught:
        codec.decode(
            _encode(payload),
            actor_id="static:reader",
            kind="runs",
            query={},
        )
    assert caught.value.code is ControlCode.CURSOR_INVALID


def test_cursor_rejects_non_alphabet_bytes_and_tampering() -> None:
    codec = CursorCodec()
    token = codec.encode(
        actor_id="static:reader",
        kind="events",
        query={"run_id": "run-a"},
        upper_bound=4,
        last_key=1,
    )
    with pytest.raises(CursorFault):
        codec.decode(
            token + "!",
            actor_id="static:reader",
            kind="events",
            query={"run_id": "run-a"},
        )
    payload = _decode(token)
    payload["upper_bound"] = 5
    with pytest.raises(CursorFault) as caught:
        codec.decode(
            _encode(payload),
            actor_id="static:reader",
            kind="events",
            query={"run_id": "run-a"},
        )
    assert "accidental-corruption" in caught.value.message
