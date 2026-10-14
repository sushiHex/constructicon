-- Actual journal writer 181672a; shape initial; schema 6.
BEGIN TRANSACTION;
CREATE TABLE approvals (
    approval_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, subject_json TEXT NOT NULL,
    decision TEXT NOT NULL, reason TEXT, actor_json TEXT NOT NULL,
    command_id TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
);
CREATE TABLE attestations (
    attestation_id   TEXT PRIMARY KEY,
    attestation_json TEXT NOT NULL
);
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
INSERT INTO "capability_leases" VALUES('lease-fc655efeefbfed79da52de213822822a',1,'run-historical-capabilities','workspace','{"iterations":[],"scope":{"segments":["leased-0"]}}','invocation','active',NULL,'historical/0','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00');
INSERT INTO "capability_leases" VALUES('lease-d5195148d22370b9322fd1714edd281a',1,'run-historical-capabilities','workspace','{"iterations":[],"scope":{"segments":["leased-1"]}}','invocation','closed','released','historical/1','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00');
INSERT INTO "capability_leases" VALUES('lease-e337b33f73c69c85f31a48f4aad4deff',1,'run-historical-capabilities','workspace','{"iterations":[],"scope":{"segments":["leased-2"]}}','invocation','lost',NULL,'historical/2','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00');
CREATE TABLE channel_acks (
    ack_seq    INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL,
    actor_id   TEXT NOT NULL,
    command_id TEXT NOT NULL UNIQUE,
    acked_at   TEXT NOT NULL,
    UNIQUE(message_id, actor_id)
);
CREATE TABLE channel_messages (
    message_seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id         TEXT NOT NULL UNIQUE,
    channel_id         TEXT NOT NULL,
    lane               TEXT NOT NULL,
    interaction        TEXT NOT NULL,
    kind               TEXT NOT NULL,
    reply_to           TEXT,
    recipient_actor_id TEXT,
    sender_actor_id    TEXT,
    run_id             TEXT NOT NULL,
    path_json          TEXT NOT NULL,
    port               TEXT NOT NULL,
    type_id            TEXT NOT NULL,
    schema_hash        TEXT NOT NULL,
    reply_port         TEXT,
    reply_type_id      TEXT,
    reply_schema_hash  TEXT,
    envelope_json      TEXT NOT NULL,
    attestation_id     TEXT,
    UNIQUE(reply_to)
);
CREATE TABLE checkpoints (
    run_id          TEXT NOT NULL,
    path_key        TEXT NOT NULL,
    identity        TEXT NOT NULL,
    checkpoint_json TEXT NOT NULL,
    PRIMARY KEY (run_id, path_key)
);
CREATE TABLE commands (
    command_id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, actor_json TEXT NOT NULL,
    operation TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL,
    request_json TEXT NOT NULL, plan_json TEXT, state TEXT NOT NULL, response_json TEXT,
    owner_id TEXT, owner_epoch INTEGER NOT NULL DEFAULT 0, lease_expires_at TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT,
    UNIQUE(actor_id, operation, idempotency_key)
);
CREATE TABLE components (
    registration_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    content_hash     TEXT NOT NULL,
    definition_json  TEXT NOT NULL,
    registered_at    TEXT NOT NULL,
    UNIQUE (name, content_hash)
);
CREATE TABLE effects (
    idempotency_key TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    request_json    TEXT NOT NULL,
    receipt_json    TEXT,
    prepared_at     TEXT NOT NULL,
    receipted_at    TEXT
);
CREATE TABLE events (
    run_id     TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    path_json  TEXT,
    payload    TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
INSERT INTO "events" VALUES('run-historical-capabilities',1,'RunStarted',NULL,NULL,'2026-01-01T00:00:00+00:00');
INSERT INTO "events" VALUES('run-historical-capabilities',2,'LeaseAcquired',NULL,'{"acquisition_epoch":1,"binding":"workspace","lease_id":"lease-fc655efeefbfed79da52de213822822a","resource_ref":"historical/0"}','2026-01-01T00:00:00+00:00');
INSERT INTO "events" VALUES('run-historical-capabilities',3,'LeaseAcquired',NULL,'{"acquisition_epoch":1,"binding":"workspace","lease_id":"lease-d5195148d22370b9322fd1714edd281a","resource_ref":"historical/1"}','2026-01-01T00:00:00+00:00');
INSERT INTO "events" VALUES('run-historical-capabilities',4,'LeaseAcquired',NULL,'{"acquisition_epoch":1,"binding":"workspace","lease_id":"lease-e337b33f73c69c85f31a48f4aad4deff","resource_ref":"historical/2"}','2026-01-01T00:00:00+00:00');
CREATE TABLE manifests (
    manifest_hash TEXT PRIMARY KEY,
    manifest_json TEXT NOT NULL
);
INSERT INTO "manifests" VALUES('sha256:586cb23feb6444c1ec8bbaf406c825f9add07fad623044f23e03c8a6310a812e','{"schema_version":2,"source_graph":{"schema_version":1,"name":"tests/empty","nodes":[],"connections":[],"inputs":[],"outputs":[]},"source_graph_hash":"sha256:3a6d07497942d3547d21a793e60cad1791068b4385823e4cdce11f6fff27b39e","resolved_components":[],"resolved_connections":[],"capability_bindings":[],"resolved_loops":[],"input_hash":"sha256:b8e8ee1f7bfefce51b8ab006bd9fca4ff10b47073b08c7adf2b342bf2e56c81d","world_hash":"sha256:c90715eb747cdcd72c842fa8cf3b746de521637af46fbe78317aa6a788519030","manifest_hash":"sha256:586cb23feb6444c1ec8bbaf406c825f9add07fad623044f23e03c8a6310a812e"}');
CREATE TABLE promotions (
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
CREATE TABLE run_origins (
    run_id TEXT PRIMARY KEY, origin_json TEXT NOT NULL
);
CREATE TABLE runs (
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
INSERT INTO "runs" VALUES('run-historical-capabilities','sha256:586cb23feb6444c1ec8bbaf406c825f9add07fad623044f23e03c8a6310a812e','sha256:b8e8ee1f7bfefce51b8ab006bd9fca4ff10b47073b08c7adf2b342bf2e56c81d','{}','running','2026-01-01T00:00:00+00:00',NULL,1,123,'2026-01-01T00:00:00+00:00',NULL,4,0);
INSERT INTO "runs" VALUES('run-historical-empty','sha256:586cb23feb6444c1ec8bbaf406c825f9add07fad623044f23e03c8a6310a812e','sha256:b8e8ee1f7bfefce51b8ab006bd9fca4ff10b47073b08c7adf2b342bf2e56c81d','{}','pending','2026-01-01T00:00:00+00:00',NULL,0,NULL,NULL,NULL,0,0);
DELETE FROM "sqlite_sequence";
COMMIT;
PRAGMA user_version = 6;
