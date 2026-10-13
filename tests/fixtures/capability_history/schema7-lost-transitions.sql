-- Actual journal writer dfd116b; shape transitions; schema 7.
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
INSERT INTO "capability_leases" VALUES('lease-fc655efeefbfed79da52de213822822a',1,'run-historical-capabilities','workspace','{"iterations":[],"scope":{"segments":["leased-0"]}}','invocation','lost',NULL,'historical/0','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00');
CREATE TABLE channel_acks (
    ack_seq    INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL,
    actor_id   TEXT NOT NULL,
    command_id TEXT NOT NULL UNIQUE,
    acked_at   TEXT NOT NULL, ack_provenance_version INTEGER,
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
    attestation_id     TEXT, command_id TEXT, reply_provenance_version INTEGER,
    UNIQUE(reply_to)
);
CREATE TABLE channel_provenance ( singleton INTEGER PRIMARY KEY CHECK (singleton = 1), legacy_ack_through INTEGER NOT NULL CHECK (legacy_ack_through >= 0), legacy_message_through INTEGER NOT NULL CHECK (legacy_message_through >= 0));
INSERT INTO "channel_provenance" VALUES(1,0,0);
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
CREATE TABLE durable_fact_seals ( family TEXT NOT NULL, fact_key TEXT NOT NULL, selector TEXT NOT NULL, fact_hash TEXT NOT NULL, PRIMARY KEY (family, fact_key), UNIQUE (family, selector));
INSERT INTO "durable_fact_seals" VALUES('channel_provenance','1','1','sha256:a9847fe9438d0a475cd5f86983633396ec1616238d1a7d0e4dd411c5d45d0aac');
INSERT INTO "durable_fact_seals" VALUES('manifest','sha256:586cb23feb6444c1ec8bbaf406c825f9add07fad623044f23e03c8a6310a812e','sha256:586cb23feb6444c1ec8bbaf406c825f9add07fad623044f23e03c8a6310a812e','sha256:fa6ccff5aeb8a954c3dfa499a76a11541e903cb9249f595411e687f36e1ad06b');
INSERT INTO "durable_fact_seals" VALUES('run_world','run-historical-capabilities','run-historical-capabilities','sha256:5ff52d17691a72160eceb33402ff43a0f4503e6975954f0bcafc02b1755820a4');
INSERT INTO "durable_fact_seals" VALUES('run_world','run-historical-empty','run-historical-empty','sha256:68f3c6775077b43666f82a9c6894291e5bdc63f4d0edcc7fd299271b9f70042c');
INSERT INTO "durable_fact_seals" VALUES('event','{"run_id":"run-historical-capabilities","seq":1}','{"event":{"run_id":"run-historical-capabilities","seq":1}}','sha256:d10e8a7ba4009c098b171122605337c308b531f235ed58a7d285960072a299ef');
INSERT INTO "durable_fact_seals" VALUES('event','{"run_id":"run-historical-capabilities","seq":2}','{"event":{"run_id":"run-historical-capabilities","seq":2}}','sha256:1b101f68c91f4b2531f5f8ea922bd4cafce44460bea17c7fe444a30c580e6ab7');
INSERT INTO "durable_fact_seals" VALUES('event','{"run_id":"run-historical-capabilities","seq":3}','{"event":{"run_id":"run-historical-capabilities","seq":3}}','sha256:c16fad9ea78b266e1c2cfb50a1075c4177d742d0e672b992beb4e8c215a563dc');
INSERT INTO "durable_fact_seals" VALUES('event','{"run_id":"run-historical-capabilities","seq":4}','{"event":{"run_id":"run-historical-capabilities","seq":4}}','sha256:c7ae3899b4451ee6ca40dcf7dbb4fb61d5534bd3c140f57abed73ab1ce3196eb');
INSERT INTO "durable_fact_seals" VALUES('event','{"run_id":"run-historical-capabilities","seq":5}','{"event":{"run_id":"run-historical-capabilities","seq":5}}','sha256:1b2c7deb99ea3297568a49ce3406ef1e6fe00e4010e62a33777f32e909714a49');
CREATE TABLE effects (
    idempotency_key TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    request_json    TEXT NOT NULL,
    receipt_json    TEXT,
    prepared_at     TEXT NOT NULL,
    receipted_at    TEXT,
    outcome_run_id  TEXT,
    outcome_event_seq INTEGER
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
INSERT INTO "events" VALUES('run-historical-capabilities',2,'LeaseAcquired',NULL,'{"acquisition_epoch":1,"binding":"workspace","lease_id":"lease-fc655efeefbfed79da52de213822822a","observed_at":"2026-01-01T00:00:00+00:00","resource_ref":"historical/0"}','2026-01-01T00:00:00+00:00');
INSERT INTO "events" VALUES('run-historical-capabilities',3,'LeaseTransition',NULL,'{"acquisition_epoch":1,"disposition":null,"from":"active","lease_id":"lease-fc655efeefbfed79da52de213822822a","observed_at":"2026-01-01T00:00:00+00:00","to":"lost"}','2026-01-01T00:00:00+00:00');
INSERT INTO "events" VALUES('run-historical-capabilities',4,'LeaseTransition',NULL,'{"acquisition_epoch":1,"disposition":null,"from":"lost","lease_id":"lease-fc655efeefbfed79da52de213822822a","observed_at":"2026-01-01T00:00:00+00:00","to":"active"}','2026-01-01T00:00:00+00:00');
INSERT INTO "events" VALUES('run-historical-capabilities',5,'LeaseTransition',NULL,'{"acquisition_epoch":1,"disposition":null,"from":"active","lease_id":"lease-fc655efeefbfed79da52de213822822a","observed_at":"2026-01-01T00:00:00+00:00","to":"lost"}','2026-01-01T00:00:00+00:00');
CREATE TABLE legacy_capability_lease_seals ( lease_id TEXT NOT NULL, acquisition_epoch INTEGER NOT NULL, run_id TEXT NOT NULL, base_hash TEXT NOT NULL, initial_lifecycle_json TEXT NOT NULL, PRIMARY KEY (lease_id, acquisition_epoch));
CREATE TABLE legacy_effect_seals ( idempotency_key TEXT PRIMARY KEY, terminal_fact_hash TEXT NOT NULL);
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
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    creation_command_id TEXT
);
INSERT INTO "runs" VALUES('run-historical-capabilities','sha256:586cb23feb6444c1ec8bbaf406c825f9add07fad623044f23e03c8a6310a812e','sha256:b8e8ee1f7bfefce51b8ab006bd9fca4ff10b47073b08c7adf2b342bf2e56c81d','{}','running','2026-01-01T00:00:00+00:00',NULL,1,123,'2026-01-01T00:00:00+00:00',NULL,5,0,NULL);
INSERT INTO "runs" VALUES('run-historical-empty','sha256:586cb23feb6444c1ec8bbaf406c825f9add07fad623044f23e03c8a6310a812e','sha256:b8e8ee1f7bfefce51b8ab006bd9fca4ff10b47073b08c7adf2b342bf2e56c81d','{}','pending','2026-01-01T00:00:00+00:00',NULL,0,NULL,NULL,NULL,0,0,NULL);
CREATE UNIQUE INDEX channel_reply_command_unique ON channel_messages(command_id) WHERE command_id IS NOT NULL;
DELETE FROM "sqlite_sequence";
COMMIT;
PRAGMA user_version = 7;
