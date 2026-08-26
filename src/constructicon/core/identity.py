"""The one identity law (I13 errata).

Every hash in the system is a domain-separated SHA-256 over canonical JSON:

    digest(domain, schema_version, payload) =
        sha256("constructicon\\0" + domain + "\\0" + str(schema_version) + "\\0"
               + canonical_json(payload))

Canonical JSON: sorted object keys, UTF-8, no insignificant whitespace, no
NaN/Infinity, explicit null preservation. A digest field never participates in
its own payload; idempotency keys are computed, never caller-authored.

Domains in use:
    component:v1        -> ComponentDef.content_hash
    graph:v1            -> ExecutionManifest.source_graph_hash
    world:v1            -> ExecutionManifest.world_hash
    manifest:v1         -> ExecutionManifest.manifest_hash (excludes itself)
    invocation:v1       -> invocation_id
    inputs:v1           -> ExecutionManifest.input_hash / Checkpoint.input_hash
    effect-request:v1   -> EffectReceipt.request_hash
    idempotency:v1      -> EffectRequest.idempotency_key
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from pydantic import RootModel, field_validator

_PREFIX = "sha256:"


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


def _reject_non_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("canonical JSON forbids NaN and Infinity")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("canonical JSON object keys must be strings")
            _reject_non_finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_non_finite(item)


def canonical_json(payload: Any) -> str:
    """Serialize a JSON value canonically: sorted keys, compact, UTF-8, finite."""
    _reject_non_finite(payload)
    return json.dumps(
        payload,
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
