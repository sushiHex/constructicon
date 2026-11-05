-- Actual journal writer 15e87ef20ed3233c12a289df34088dc0ac8f8a84; shape attestation-baseline; schema 9.
-- Run-owned v1 promotion, merge and send; policy v1; retained dependents.
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
INSERT INTO "attestations" VALUES('att-c470bafee2ff23435cc7a465d1b98b7c1c9d523d262ff10bc7d16617ad605611','{"attestation_id":"att-c470bafee2ff23435cc7a465d1b98b7c1c9d523d262ff10bc7d16617ad605611","action":"promote","subject":{"kind":"component","component":"history/attestation","version":"sha256:082f5b315ea29f177f1e70e1a8adde412c1d1ede321bb32bc94f7b998a7b86cd","baseline_version":null},"checks":[{"name":"history","status":"passed","ok":true,"detail":"actual schema-9 writer","elapsed_s":0.0}],"check_set_hash":"sha256:e0df9c3a9efb15a0501de768cb52ef380d3c7b5f7b6a01cd4383af7f12c501af","evidence":[],"manifest_hash":"sha256:586cb23feb6444c1ec8bbaf406c825f9add07fad623044f23e03c8a6310a812e","created_by_run":"run-v6-legacy","workspace_id":null,"created_at":"2026-01-01T00:00:00Z"}');
INSERT INTO "attestations" VALUES('att-45e17818b733e0ae012cf6e19f4337a0af171ae5b0f5ac8dde35793e363be296','{"attestation_id":"att-45e17818b733e0ae012cf6e19f4337a0af171ae5b0f5ac8dde35793e363be296","action":"promote","subject":{"kind":"component","component":"history/policy","version":"sha256:082f5b315ea29f177f1e70e1a8adde412c1d1ede321bb32bc94f7b998a7b86cd","baseline_version":null},"checks":[{"name":"history","status":"passed","ok":true,"detail":"actual schema-9 writer","elapsed_s":0.0}],"check_set_hash":"sha256:e0df9c3a9efb15a0501de768cb52ef380d3c7b5f7b6a01cd4383af7f12c501af","evidence":[],"manifest_hash":"sha256:586cb23feb6444c1ec8bbaf406c825f9add07fad623044f23e03c8a6310a812e","created_by_run":null,"workspace_id":null,"created_at":"2026-01-01T00:00:00Z"}');
INSERT INTO "attestations" VALUES('att-510ea94b837f20c455ee40113e2b70de7f8919b24958d47d9f9cbdf540149bb4','{"attestation_id":"att-510ea94b837f20c455ee40113e2b70de7f8919b24958d47d9f9cbdf540149bb4","action":"merge","subject":{"kind":"git_merge","repository":"history/repository","target_ref":"refs/heads/main","candidate":"2222222222222222222222222222222222222222","expected_base":"1111111111111111111111111111111111111111","merge_commit":"3333333333333333333333333333333333333333","tested_tree":"4444444444444444444444444444444444444444"},"checks":[{"name":"history","status":"passed","ok":true,"detail":"actual schema-9 writer","elapsed_s":0.0}],"check_set_hash":"sha256:e0df9c3a9efb15a0501de768cb52ef380d3c7b5f7b6a01cd4383af7f12c501af","evidence":[],"manifest_hash":"sha256:586cb23feb6444c1ec8bbaf406c825f9add07fad623044f23e03c8a6310a812e","created_by_run":"run-v6-legacy","workspace_id":null,"created_at":"2026-01-01T00:00:00Z"}');
INSERT INTO "attestations" VALUES('att-99bcdef41b7c69218243e493e8c785cb3a4bdeca01aea6205785ad1fbaf52345','{"attestation_id":"att-99bcdef41b7c69218243e493e8c785cb3a4bdeca01aea6205785ad1fbaf52345","action":"send","subject":{"kind":"channel_send","message_id":"sha256:72465fa294bd099801eaf333ccde125be293be979271e37d10ba85731ec9f7b5","channel_id":"channel/legacy","channel_revision":"1","lane":"review","interaction":"advice","recipient_actor_id":"static:legacy-advisor","run_id":"run-v6-legacy","path":{"scope":{"segments":["review"]},"iterations":[]},"port":"request","contract":{"type_id":"test/Ask","schema_hash":"ask-v1"},"reply_port":"reply","reply_contract":{"type_id":"test/Answer","schema_hash":"answer-v1"},"payload_digest":"sha256:340180fc73b405ff1e7b6beb5cf597f636267da4bfaa669291913f3db4b4914b"},"checks":[{"name":"history","status":"passed","ok":true,"detail":"actual schema-9 writer","elapsed_s":0.0}],"check_set_hash":"sha256:e0df9c3a9efb15a0501de768cb52ef380d3c7b5f7b6a01cd4383af7f12c501af","evidence":[],"manifest_hash":"sha256:586cb23feb6444c1ec8bbaf406c825f9add07fad623044f23e03c8a6310a812e","created_by_run":"run-v6-legacy","workspace_id":null,"created_at":"2026-01-01T00:00:00Z"}');
CREATE TABLE capability_accounting_eras ( run_id TEXT PRIMARY KEY, world_hash TEXT NOT NULL, source TEXT NOT NULL, floor INTEGER NOT NULL, inventory_hash TEXT NOT NULL);
INSERT INTO "capability_accounting_eras" VALUES('run-v6-legacy','sha256:ce796e8c3060108f6c5ccef07dc976033c9c0b4b213a061c58d6158f777ce9d9','schema8-creation',0,'sha256:f24959a6c4e025fb54728bcbd432a530c4c440cae3e27d2129142c6dbe275fd1');
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
INSERT INTO "channel_messages" VALUES(1,'sha256:72465fa294bd099801eaf333ccde125be293be979271e37d10ba85731ec9f7b5','channel/legacy','review','advice','request',NULL,'static:legacy-advisor',NULL,'run-v6-legacy','{"iterations":[],"scope":{"segments":["review"]}}','request','test/Ask','ask-v1','reply','test/Answer','answer-v1','{"run_id":"run-v6-legacy","path":{"scope":{"segments":["review"]},"iterations":[]},"port":"request","created_at":"2026-01-01T00:00:00Z","provenance":[],"payload":{"question":"ship?"}}','att-99bcdef41b7c69218243e493e8c785cb3a4bdeca01aea6205785ad1fbaf52345',NULL,NULL);
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
INSERT INTO "components" VALUES(1,'history/attestation','sha256:082f5b315ea29f177f1e70e1a8adde412c1d1ede321bb32bc94f7b998a7b86cd','{"name":"history/attestation","role":"node","body":{"package":"tests","module":"tests.conftest","qualname":"triage_impl","contract_hash":"sha256:4937e79de4b1dea3baa7b5170b4dc8a28c632e92119ec07720bd72b6f23209be","source_digest":"sha256:19f400d01dc722d90a7cb70e301cc066f3a23c59578f719833118b9fe3c5b089"},"inputs":[{"name":"issue","type_id":"test/Issue","schema_hash":"s1","json_schema":null,"cardinality":"one"}],"outputs":[{"name":"brief","type_id":"test/Brief","schema_hash":"s1","json_schema":null,"cardinality":"one"}],"metadata":{"learning":null,"lineage":null,"labels":[]}}','2026-01-01T00:00:00+00:00');
CREATE TABLE durable_fact_seals ( family TEXT NOT NULL, fact_key TEXT NOT NULL, selector TEXT NOT NULL, fact_hash TEXT NOT NULL, PRIMARY KEY (family, fact_key), UNIQUE (family, selector));
INSERT INTO "durable_fact_seals" VALUES('channel_provenance','1','1','sha256:a9847fe9438d0a475cd5f86983633396ec1616238d1a7d0e4dd411c5d45d0aac');
INSERT INTO "durable_fact_seals" VALUES('manifest','sha256:586cb23feb6444c1ec8bbaf406c825f9add07fad623044f23e03c8a6310a812e','sha256:586cb23feb6444c1ec8bbaf406c825f9add07fad623044f23e03c8a6310a812e','sha256:fa6ccff5aeb8a954c3dfa499a76a11541e903cb9249f595411e687f36e1ad06b');
INSERT INTO "durable_fact_seals" VALUES('run_world','run-v6-legacy','run-v6-legacy','sha256:97b6b13d9dcfc1775ae2dd8774b25e07cbbf8d16d85a00d45fb0bcd650e18aa5');
INSERT INTO "durable_fact_seals" VALUES('capability_accounting_era','run-v6-legacy','run-v6-legacy','sha256:6c31f4d3b761dd20eba0fa49853334b3bc4fcc987475ebaf300313a43f0b9100');
INSERT INTO "durable_fact_seals" VALUES('component_registration','1','{"content_hash":"sha256:082f5b315ea29f177f1e70e1a8adde412c1d1ede321bb32bc94f7b998a7b86cd","name":"history/attestation"}','sha256:7d32d332981a2f75a68ec5c080c244f532b07a1b123f09ce836631e4a2391e28');
INSERT INTO "durable_fact_seals" VALUES('event','{"run_id":"run-v6-legacy","seq":1}','{"event":{"run_id":"run-v6-legacy","seq":1}}','sha256:2785965c57f25f5f43bd77cb9f786a3ca13ede35dabdc56281fa0f26f7c61f83');
INSERT INTO "durable_fact_seals" VALUES('attestation','att-c470bafee2ff23435cc7a465d1b98b7c1c9d523d262ff10bc7d16617ad605611','att-c470bafee2ff23435cc7a465d1b98b7c1c9d523d262ff10bc7d16617ad605611','sha256:97d3f8f114d94eca4aabe171e36d355b17424e02cace1b393944fcf5697557cb');
INSERT INTO "durable_fact_seals" VALUES('promotion','1','att-c470bafee2ff23435cc7a465d1b98b7c1c9d523d262ff10bc7d16617ad605611','sha256:834bed525fee0b06cbd23aecac7424ab061a32d55bf8d88521ea245417b2fe65');
INSERT INTO "durable_fact_seals" VALUES('attestation','att-45e17818b733e0ae012cf6e19f4337a0af171ae5b0f5ac8dde35793e363be296','att-45e17818b733e0ae012cf6e19f4337a0af171ae5b0f5ac8dde35793e363be296','sha256:28011a65ee5116151dfc36595bef6536bb61236acd9e4d2b303713090e114e0b');
INSERT INTO "durable_fact_seals" VALUES('attestation','att-510ea94b837f20c455ee40113e2b70de7f8919b24958d47d9f9cbdf540149bb4','att-510ea94b837f20c455ee40113e2b70de7f8919b24958d47d9f9cbdf540149bb4','sha256:5c76c2f66c34328803c3a5314c7d42741251ee27630df1d401f0fdb489858b0e');
INSERT INTO "durable_fact_seals" VALUES('effect_preparation','sha256:0edf76059ac50805ebd8b375a0b486f247a516bac23acd0f2e391d609f09e02c','sha256:0edf76059ac50805ebd8b375a0b486f247a516bac23acd0f2e391d609f09e02c','sha256:c1b19c778630d5c1c33271f7e7a65cc28fe679f0705e8a72f78668d28c44bcc5');
INSERT INTO "durable_fact_seals" VALUES('attestation','att-99bcdef41b7c69218243e493e8c785cb3a4bdeca01aea6205785ad1fbaf52345','att-99bcdef41b7c69218243e493e8c785cb3a4bdeca01aea6205785ad1fbaf52345','sha256:3b02f7030a5b38f0d1179a4d768eab3c11acad4d1a07f6f339d350f4c49ab541');
INSERT INTO "durable_fact_seals" VALUES('channel_message','sha256:72465fa294bd099801eaf333ccde125be293be979271e37d10ba85731ec9f7b5','1','sha256:cce01700ff13df3729f6a984b98935fbe109332ae22290fb1c13293a2736bf16');
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
INSERT INTO "effects" VALUES('sha256:0edf76059ac50805ebd8b375a0b486f247a516bac23acd0f2e391d609f09e02c','run-v6-legacy','{"run_id":"run-v6-legacy","manifest_hash":"sha256:586cb23feb6444c1ec8bbaf406c825f9add07fad623044f23e03c8a6310a812e","path":{"scope":{"segments":["historical-effect"]},"iterations":[]},"kind":"history.record","subject":{"history":true},"idempotency_key":"sha256:0edf76059ac50805ebd8b375a0b486f247a516bac23acd0f2e391d609f09e02c","attestation_id":"att-510ea94b837f20c455ee40113e2b70de7f8919b24958d47d9f9cbdf540149bb4","mode":"live"}',NULL,'2026-01-01T00:00:00+00:00',NULL,NULL,NULL);
CREATE TABLE events (
    run_id     TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    path_json  TEXT,
    payload    TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
INSERT INTO "events" VALUES('run-v6-legacy',1,'RunStarted',NULL,NULL,'2026-01-01T00:00:00+00:00');
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
INSERT INTO "promotions" VALUES(1,'history/attestation','stable',NULL,'sha256:082f5b315ea29f177f1e70e1a8adde412c1d1ede321bb32bc94f7b998a7b86cd','att-c470bafee2ff23435cc7a465d1b98b7c1c9d523d262ff10bc7d16617ad605611','static:historian','run-v6-legacy','2026-01-01T00:00:00+00:00');
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
INSERT INTO "runs" VALUES('run-v6-legacy','sha256:586cb23feb6444c1ec8bbaf406c825f9add07fad623044f23e03c8a6310a812e','sha256:b8e8ee1f7bfefce51b8ab006bd9fca4ff10b47073b08c7adf2b342bf2e56c81d','{}','running','2026-01-01T00:00:00+00:00',NULL,1,123,'2026-01-01T00:00:00+00:00',NULL,1,0,NULL);
CREATE UNIQUE INDEX channel_reply_command_unique ON channel_messages(command_id) WHERE command_id IS NOT NULL;
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('components',1);
INSERT INTO "sqlite_sequence" VALUES('promotions',1);
INSERT INTO "sqlite_sequence" VALUES('channel_messages',1);
COMMIT;
PRAGMA user_version = 9;
