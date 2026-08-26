"""The one identity law (I13 errata).

Every hash in the system is a domain-separated SHA-256 over canonical JSON:

    digest(domain, schema_version, payload) =
        sha256("constructicon\\0" + domain + "\\0" + str(schema_version) + "\\0"
               + canonical_json(payload))

Canonical JSON: sorted object keys, UTF-8, no insignificant whitespace, no
NaN/Infinity, explicit null preservation. A digest field never participates in
its own payload; idempotency keys are computed, never caller-authored.

``json_value`` is the one wire normalizer. Values inside the walker and journal
are JSON values; Pydantic models, enums, and tuples are converted at component
boundaries so live execution and checkpoint restoration have identical
semantics.
"""

from __future__ import annotations

import hashlib
import json
import math
from enum import Enum
from typing import Any, TypeAlias

from pydantic import BaseModel, RootModel, field_validator

_PREFIX = "sha256:"

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list[Any] | dict[str, Any]


class Digest(RootModel[str]):
    """Canonical digest form: ``sha256:<64 lowercase hex>``."""

    @field_validator("root")
    @classmethod
    def _well_formed(cls, value: str) -> str:
        if not value.startswith(_PREFIX):
            raise ValueError(f"digest must start with {_PREFIX!r}")
        hexpart = value[len(_PREFIX) :]
        if len(hexpart) != 64 or any(c not in "0123456789abcdef" for c in hexpart):
            raise ValueError("digest must carry 64 lowercase hex characters")
        return value

    def __str__(self) -> str:
        return self.root

    def __hash__(self) -> int:
        return hash(self.root)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Digest):
            return self.root == other.root
        return NotImplemented


def json_value(payload: Any) -> JsonValue:
    """Normalize a component value into Constructicon's canonical JSON wire form.

    This is deliberately strict: arbitrary Python objects never cross a graph
    boundary or enter a checkpoint. Domain objects cross as their JSON model,
    and a consumer reconstructs them explicitly with ``model_validate``.
    """

    if isinstance(payload, BaseModel):
        return json_value(payload.model_dump(mode="json"))
    if isinstance(payload, Enum):
        return json_value(payload.value)
    if payload is None or isinstance(payload, (str, int, bool)):
        return payload
    if isinstance(payload, float):
        if not math.isfinite(payload):
            raise ValueError("canonical JSON forbids NaN and Infinity")
        return payload
    if isinstance(payload, dict):
        normalized: dict[str, JsonValue] = {}
        for key, item in payload.items():
            if not isinstance(key, str):
                raise ValueError("canonical JSON object keys must be strings")
            normalized[key] = json_value(item)
        return normalized
    if isinstance(payload, (list, tuple)):
        return [json_value(item) for item in payload]
    raise ValueError(
        f"value of type {type(payload).__name__} is not a JSON wire value; "
        "return a Pydantic model or JSON-compatible value"
    )


def canonical_json(payload: Any) -> str:
    """Serialize a value canonically after applying the one wire normalizer."""

    normalized = json_value(payload)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest(domain: str, schema_version: int, payload: Any) -> Digest:
    """Apply the identity law: one domain-separated hash for every identity."""

    material = "\0".join(
        ("constructicon", domain, str(schema_version), canonical_json(payload))
    )
    return Digest(_PREFIX + hashlib.sha256(material.encode("utf-8")).hexdigest())
