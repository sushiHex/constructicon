"""One opaque, actor- and query-bound cursor codec (M6)."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from constructicon.core.control import ControlCode
from constructicon.core.identity import Digest, JsonValue, canonical_json, digest, json_value

CURSOR_SCHEMA_VERSION = 2


class CursorPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal[2]
    actor_id: str
    kind: str
    query_hash: Digest
    upper_bound: JsonValue
    last_key: JsonValue | None
    checksum: Digest


@dataclass(frozen=True)
class CursorFault(Exception):
    code: ControlCode
    message: str
    repair: str


class CursorCodec:
    """Base64url canonical JSON with a self-check; not an authority token."""

    def encode(
        self,
        *,
        actor_id: str,
        kind: str,
        query: JsonValue,
        upper_bound: JsonValue,
        last_key: JsonValue | None,
    ) -> str:
        query_hash = digest("control-cursor-query", 1, query)
        body = {
            "schema_version": CURSOR_SCHEMA_VERSION,
            "actor_id": actor_id,
            "kind": kind,
            "query_hash": str(query_hash),
            "upper_bound": json_value(upper_bound),
            "last_key": json_value(last_key),
        }
        payload = {
            **body,
            "checksum": str(digest("control-cursor", CURSOR_SCHEMA_VERSION, body)),
        }
        encoded = base64.urlsafe_b64encode(canonical_json(payload).encode("utf-8"))
        return encoded.decode("ascii").rstrip("=")

    def decode(
        self,
        value: str,
        *,
        actor_id: str,
        kind: str,
        query: JsonValue,
    ) -> CursorPayload:
        try:
            padded = value + "=" * (-len(value) % 4)
            raw = base64.b64decode(
                padded.encode("ascii"),
                altchars=b"-_",
                validate=True,
            )
            payload = CursorPayload.model_validate_json(raw)
        except (ValueError, UnicodeError, binascii.Error, ValidationError) as exc:
            raise CursorFault(
                ControlCode.CURSOR_INVALID,
                f"cursor is malformed or unsupported: {exc}",
                "restart the query without a cursor",
            ) from exc
        body = {
            "schema_version": payload.schema_version,
            "actor_id": payload.actor_id,
            "kind": payload.kind,
            "query_hash": str(payload.query_hash),
            "upper_bound": payload.upper_bound,
            "last_key": payload.last_key,
        }
        expected_checksum = digest("control-cursor", CURSOR_SCHEMA_VERSION, body)
        if payload.checksum != expected_checksum:
            raise CursorFault(
                ControlCode.CURSOR_INVALID,
                "cursor checksum failed accidental-corruption detection",
                "restart the query without a cursor",
            )
        expected_query = digest("control-cursor-query", 1, query)
        if (
            payload.actor_id != actor_id
            or payload.kind != kind
            or payload.query_hash != expected_query
        ):
            raise CursorFault(
                ControlCode.CURSOR_QUERY_MISMATCH,
                "cursor belongs to another actor, endpoint, or filter set",
                "use only the cursor returned by the immediately preceding page",
            )
        return payload
