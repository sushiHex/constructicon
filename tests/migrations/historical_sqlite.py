"""Exact pre-current SQLite shapes and identity laws for migration fixtures.

These constants are copied from the defining merged milestone writers.  Tests
construct those worlds directly; they never create a current database and
pretend an older ``user_version`` makes its rows historical.
"""

from __future__ import annotations

import json
from typing import Any

from constructicon.core.address import ExecutionPath, RunId
from constructicon.core.identity import Digest, digest
from constructicon.core.manifest import ExecutionManifest, manifest_hash_for

M1_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    manifest_hash TEXT NOT NULL,
    input_hash    TEXT NOT NULL,
    status        TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    run_id     TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    path_json  TEXT,
    payload    TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS checkpoints (
    run_id          TEXT NOT NULL,
    path_key        TEXT NOT NULL,
    checkpoint_json TEXT NOT NULL,
    PRIMARY KEY (run_id, path_key)
);
CREATE TABLE IF NOT EXISTS manifests (
    manifest_hash TEXT PRIMARY KEY,
    manifest_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attestations (
    attestation_id   TEXT PRIMARY KEY,
    attestation_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS effects (
    idempotency_key TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    request_json    TEXT NOT NULL,
    receipt_json    TEXT,
    prepared_at     TEXT NOT NULL,
    receipted_at    TEXT
);
"""

M2_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id           TEXT PRIMARY KEY,
    manifest_hash    TEXT NOT NULL,
    input_hash       TEXT NOT NULL,
    inputs_json      TEXT NOT NULL,
    status           TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    owner_id         TEXT,
    owner_epoch      INTEGER NOT NULL DEFAULT 0,
    owner_pid        INTEGER,
    heartbeat_at     TEXT,
    lease_expires_at TEXT,
    next_event_seq   INTEGER NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
    run_id     TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    path_json  TEXT,
    payload    TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS checkpoints (
    run_id          TEXT NOT NULL,
    path_key        TEXT NOT NULL,
    identity        TEXT NOT NULL,
    checkpoint_json TEXT NOT NULL,
    PRIMARY KEY (run_id, path_key)
);
CREATE TABLE IF NOT EXISTS manifests (
    manifest_hash TEXT PRIMARY KEY,
    manifest_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attestations (
    attestation_id   TEXT PRIMARY KEY,
    attestation_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS effects (
    idempotency_key TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    request_json    TEXT NOT NULL,
    receipt_json    TEXT,
    prepared_at     TEXT NOT NULL,
    receipted_at    TEXT
);
CREATE TABLE IF NOT EXISTS components (
    registration_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    content_hash     TEXT NOT NULL,
    definition_json  TEXT NOT NULL,
    registered_at    TEXT NOT NULL,
    UNIQUE (name, content_hash)
);
CREATE TABLE IF NOT EXISTS promotions (
    promotion_seq  INTEGER PRIMARY KEY AUTOINCREMENT,
    component      TEXT NOT NULL,
    channel        TEXT NOT NULL,
    from_version   TEXT,
    to_version     TEXT NOT NULL,
    attestation_id TEXT NOT NULL UNIQUE,
    actor          TEXT NOT NULL,
    source_run     TEXT,
    created_at     TEXT NOT NULL
);
"""

M3_LEASE_SCHEMA = """
CREATE TABLE capability_leases (
    lease_id          TEXT NOT NULL,
    acquisition_epoch INTEGER NOT NULL,
    run_id            TEXT NOT NULL,
    binding_id        TEXT NOT NULL,
    scope_json        TEXT NOT NULL,
    lifetime          TEXT NOT NULL,
    state             TEXT NOT NULL,
    disposition       TEXT,
    resource_ref      TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    PRIMARY KEY (lease_id, acquisition_epoch)
);
"""

M3_SCHEMA = M2_SCHEMA + M3_LEASE_SCHEMA


def historical_manifest_v1(
    current: ExecutionManifest,
) -> tuple[ExecutionManifest, str]:
    """Re-identify a loop-free manifest and emit exact M1-M3 stored bytes."""

    placeholder = digest("manifest-placeholder", 1, {})
    legacy = current.model_copy(
        update={
            "schema_version": 1,
            "resolved_loops": (),
            "manifest_hash": placeholder,
        }
    )
    legacy = legacy.model_copy(update={"manifest_hash": manifest_hash_for(legacy)})
    payload = legacy.model_dump(mode="json")
    payload.pop("resolved_loops")
    return legacy, historical_json(payload)


def effect_request_before_m3(
    *,
    manifest_hash: Digest,
    path: ExecutionPath,
    kind: str,
    subject: dict[str, Any],
) -> tuple[Digest, dict[str, Any]]:
    """Return the exact M1/M2 request shape and its historical live key."""

    key = digest(
        "idempotency",
        1,
        {
            "manifest_hash": str(manifest_hash),
            "path": path.model_dump(mode="json"),
            "kind": kind,
            "subject": subject,
        },
    )
    return key, {
        "path": path.model_dump(mode="json"),
        "kind": kind,
        "subject": subject,
        "idempotency_key": str(key),
        "attestation_id": None,
    }


def effect_request_before_m6(
    *,
    run_id: RunId,
    manifest_hash: Digest,
    path: ExecutionPath,
    kind: str,
    subject: dict[str, Any],
) -> tuple[Digest, dict[str, Any]]:
    """Return the exact M3-M5 request shape (run-bound, no mode)."""

    key, old = effect_request_before_m3(
        manifest_hash=manifest_hash,
        path=path,
        kind=kind,
        subject=subject,
    )
    return key, {
        "run_id": str(run_id),
        "manifest_hash": str(manifest_hash),
        **old,
    }


def historical_effect_receipt(request: dict[str, Any]) -> dict[str, Any]:
    """Return the receipt bytes bound to the request shape its writer saw."""

    return {
        "request_hash": str(digest("effect-request", 1, request)),
        "status": "committed",
        "external_reference": "historical/external/1",
        "observed_state": {"stored": True},
    }


def historical_json(value: object) -> str:
    """Mirror Pydantic v2's compact, insertion-ordered ``model_dump_json``."""

    return json.dumps(value, separators=(",", ":"))
