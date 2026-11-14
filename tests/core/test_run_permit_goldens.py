"""The run permit's current law, pinned before it is folded (RUN_PERMIT.md, step 1).

docs/designs/RUN_PERMIT.md proposes one law for the two copies in
core/qualification.py and core/maintenance.py. These goldens record what each
copy does today, including where the two differ, so a fold that changes no
behaviour changes no golden. The owner has decided that a later
requalification adopts the tighter epoch and read rules; that change edits the
two divergence tests below, by name.

Every expected value was observed from the unmodified source at aaf9920 or
7fc6a79, never derived by reading it. Long wires are pinned by SHA-256 to keep the tree small
(#423); sentences are pinned in full.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from constructicon.api import _qualification_write_assembly as write_assembly
from constructicon.api import claude_qualification, claude_write_qualification, qualification
from constructicon.api._qualification_write_graph import write_graph
from constructicon.core.address import ExecutionPath, ScopePath
from constructicon.core.control import command_id_for, run_id_for_command
from constructicon.core.errors import ContractViolation
from constructicon.core.identity import digest
from constructicon.core.maintenance import ChannelReplyAttemptAuthorization
from constructicon.core.manifest import source_graph_hash_for
from constructicon.core.qualification import QualificationAuthorization
from constructicon.substrate.executors import codex_lane
from constructicon.substrate.executors import maintenance as maintenance_reader
from constructicon.substrate.executors import qualification as qualification_reader
from tests.core import test_maintenance_authorization as plan
from tests.core import test_qualification as stage
from tests.core.test_maintenance_channel_authorization import GOLDEN_WIRE, channel_authorization
from tests.core.test_qualification_write import NO_DISPATCH_GOLDEN, pins, write


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_the_schemas_and_the_unpinned_wires_are_unchanged():
    # The plan-manifest schema and wire are pinned in test_maintenance_channel_authorization.
    assert sha256(json.dumps(QualificationAuthorization.model_json_schema(), sort_keys=True)) \
        == "b03e122d98c38b3ade376798b44d4adea16aef57b84b1b7c1d0a4283f1b475f1"
    assert sha256(json.dumps(ChannelReplyAttemptAuthorization.model_json_schema(),
                             sort_keys=True)) \
        == "e5d90018da4492ec437146199999f5a525c4f30bc84177e81ff7645f6ec98103"
    assert sha256(write().model_dump_json()) \
        == "6bc3bd271e98b94b7ea53baf410fef6c55c7814358220c021eac2fe00535005f"
    assert sha256(channel_authorization().model_dump_json()) \
        == "84a8ec671b86ef1608cafb200c588348dfd66f42204f99709bfa16ba6409284d"


def exact(permit) -> dict:
    """The one acquisition this permit admits."""
    return {
        "run_id": permit.run_id, "path": ExecutionPath(scope=permit.scope),
        "binding": permit.binding, "source_graph_hash": permit.source_graph_hash,
        "capability_id": permit.capability_id, "revision": permit.revision,
        "operator_binding_digest": permit.operator_binding_digest,
        "grants": permit.grants or stage.GRANTS, "epoch": 1,
        "now": permit.not_after - timedelta(seconds=1),
    }


def wrong(permit) -> dict:
    """An acquisition wrong in all ten respects, keyed in the order the checks run."""
    return {
        "run_id": run_id_for_command(command_id_for("other", "runs_start", "other")),
        "path": ExecutionPath(scope=ScopePath(segments=("other",))), "binding": "other",
        "source_graph_hash": None, "capability_id": "other", "revision": "other",
        "operator_binding_digest": digest("other", 1, "other"),
        "grants": exact(permit)["grants"].model_copy(update={"timeout_s": 1}), "epoch": 2,
        "now": datetime(2100, 1, 1, tzinfo=UTC),
    }


SHARED = (
    "a different run", "a different invocation", "a different binding",
    "a different source graph", "a different capability", "a different adapter revision",
    "a different operator binding",
)
QUALIFICATION = (
    *(f"qualification refuses {fault}" for fault in SHARED),
    "qualification refuses other grants",
    "qualification refuses an acquisition beyond the authorized epochs",
    "qualification refuses an expired authorization",
)
MAINTENANCE = (
    *(f"maintenance refuses {fault}" for fault in SHARED),
    "maintenance refuses other grants",
    "maintenance refuses an acquisition outside the authorized epoch",
    "maintenance refuses an expired authorization",
)


# The five purposes, each with the sentence each check gives; None is a check that holds.
PURPOSES = {
    # Divergence kept by the design: absent pinned grants match (qualification.py:158).
    "no-dispatch": (stage.authorization, (*QUALIFICATION[:7], None, *QUALIFICATION[8:])),
    "read": (stage.read, QUALIFICATION),
    "write": (write, QUALIFICATION),
    "plan-manifest": (plan.authorization, MAINTENANCE),
    "channel-reply": (channel_authorization, MAINTENANCE),
}


@pytest.mark.parametrize("purpose", PURPOSES)
def test_every_acquisition_refusal_sentence_in_order(purpose):
    make, faults = PURPOSES[purpose]
    assert make().acquisition_faults(**exact(make())) == ()
    assert make().acquisition_faults(**wrong(make())) == tuple(f for f in faults if f)


@pytest.mark.parametrize("check", range(10), ids=list(wrong(write())))
@pytest.mark.parametrize("purpose", PURPOSES)
def test_each_acquisition_check_refuses_alone(purpose, check):
    make, faults = PURPOSES[purpose]
    key = list(wrong(make()))[check]
    refused = make().acquisition_faults(**{**exact(make()), key: wrong(make())[key]})
    assert refused == ((faults[check],) if faults[check] else ())


@pytest.mark.parametrize("make,change,sentence", [
    (stage.authorization, {"write": None}, "only a WRITE authorization carries WRITE pins"),
    (stage.authorization, {"grants": stage.GRANTS},
     "a no-dispatch authorization pins no grants or attempt record"),
    (stage.read, {"max_epoch": 2},
     "a read authorization pins its grants, its attempt record and exactly one epoch"),
    (write, {"attempt_record": None},
     "a write authorization pins its grants, its attempt record and exactly one epoch"),
    (write, {"write": None}, "a WRITE authorization requires its assembly pins"),
    (write, {"grants": stage.GRANTS},
     "a WRITE authorization requires the fixed WRITE grant shape"),
    (plan.authorization, {"max_epoch": 2}, "maintenance authorizes exactly epoch one"),
    (plan.authorization, {"grants": stage.GRANTS},
     "maintenance requires the bounded WRITE grant shape"),
    # Two invalidities at once: which refusal wins (validator order, RUN_PERMIT.md:97-99).
    (stage.authorization, {"write": None, "grants": stage.GRANTS},
     "only a WRITE authorization carries WRITE pins"),
    (write, {"attempt_record": None, "write": None},
     "a write authorization pins its grants, its attempt record and exactly one epoch"),
    (write, {"write": None, "grants": stage.GRANTS},
     "a WRITE authorization requires its assembly pins"),
    (plan.authorization, {"max_epoch": 2, "grants": stage.GRANTS},
     "maintenance authorizes exactly epoch one"),
])
def test_every_shape_refusal_sentence(make, change, sentence):
    with pytest.raises(ValidationError) as refused:
        make(**change)
    assert [error["msg"] for error in refused.value.errors()] == [f"Value error, {sentence}"]


# Divergence: qualification admits any epoch <= max_epoch (qualification.py:171);
# maintenance admits exactly the integer one (maintenance.py:232). The
# requalification adopts maintenance's rule (RUN_PERMIT.md, "Three tightenings", 1).
@pytest.mark.parametrize("epoch,qualification_faults,maintenance_faults", [
    (0, (), MAINTENANCE[8:9]), (-1, (), MAINTENANCE[8:9]), (True, (), MAINTENANCE[8:9]),
    (0.5, (), MAINTENANCE[8:9]), (1, (), ()), (2, QUALIFICATION[8:9], MAINTENANCE[8:9]),
])
def test_the_two_epoch_rules(epoch, qualification_faults, maintenance_faults):
    for permit, faults in ((stage.read(), qualification_faults),
                           (plan.authorization(), maintenance_faults)):
        assert permit.acquisition_faults(**{**exact(permit), "epoch": epoch}) == faults


# Divergence: the qualification reader keeps a repeated key's last value; the
# maintenance reader refuses it. The requalification adopts maintenance's rule
# (RUN_PERMIT.md, "Three tightenings", 2).
def test_the_two_readers_on_a_repeated_key(monkeypatch):
    repeated = NO_DISPATCH_GOLDEN.replace('{"authorization_id"', '{"authorization_id":"x",'
                                          '"authorization_id"', 1)
    monkeypatch.setattr(qualification_reader, "_read_authorization_bytes",
                        lambda _: repeated.encode())
    assert qualification_reader.read_authorization(None).authorization_id == "ci-fixture"
    repeated = GOLDEN_WIRE.replace('{"actor_id"', '{"actor_id":"x","actor_id"', 1)
    monkeypatch.setattr(maintenance_reader, "_read_authorization_bytes",
                        lambda _: repeated.encode())
    with pytest.raises(ContractViolation, match="the maintenance authorization is unavailable") \
            as refused:
        maintenance_reader.read_maintenance_authorization(None)
    assert str(refused.value.__cause__) == "canonical JSON object repeats key 'actor_id'"


# Kept as it is (RUN_PERMIT.md:148-151): a maintenance file with no purpose is read as
# a plan-manifest permit, so a channel-reply file without one is refused.
@pytest.mark.parametrize("wire,read", [
    (GOLDEN_WIRE, "MaintenanceAttemptAuthorization"),
    (channel_authorization().model_dump_json(),
     "the maintenance authorization is unavailable: MaintenanceAttemptAuthorization"),
], ids=["plan-manifest", "channel-reply"])
def test_the_maintenance_reader_on_an_omitted_purpose(monkeypatch, wire, read):
    record = json.loads(wire)
    del record["purpose"]
    raw = json.dumps(record).encode()
    monkeypatch.setattr(maintenance_reader, "_read_authorization_bytes", lambda _: raw)
    try:
        outcome = type(maintenance_reader.read_maintenance_authorization(None)).__name__
    except ContractViolation as refused:
        outcome = f"{refused}: {refused.__cause__.title}"
    assert outcome == read


FLAGS = ["--store-key", "k", "--sealed", "g", "--qualification", "q", "--authorization-id", "a",
         "--actor", "operator", "--key", "k", "--journal", "journal.sqlite", "--hours", "1"]
CLAUDE = ["--fixture", "f", "--launch-config", "c", "--launch-config-sha256", "0" * 64,
          "--store-root", "r", "--acquisition-root", "a", "--attempt-record", "permit.attempt"]
CODEX = ["mint", "--session", "s", "--state", "t", *FLAGS, "--stage"]
RECORD = ["--attempt-record", "permit.attempt"]
# The host assembly each command would do, stubbed; everything after it is the command's own.
PROVIDER = SimpleNamespace(
    identity=SimpleNamespace(
        revision="rev-1", store=SimpleNamespace(operator_binding_digest=stage.BINDING),
    ),
    launcher=SimpleNamespace(claude=SimpleNamespace(model="claude-model", effort="high")),
)
ASSEMBLY = SimpleNamespace(executor=PROVIDER, pins=pins())


@pytest.mark.parametrize("main,argv,graph,model,golden", [
    (qualification.main, [*CODEX, "qualification-no-dispatch"],
     lambda: qualification.qualification_graph("codex-operator", "qualification-no-dispatch"),
     None, "7a08b51aab51c5a2f1ae1e99b63e38c03abfde571cd9d6ddd9fc143e68b43e03"),
    (qualification.main, [*CODEX, "qualification-read", *RECORD],
     lambda: qualification.qualification_graph("codex-operator", "qualification-read"),
     codex_lane.PREPARE_MODEL, "0dbc536b25ca1e7848b6ad45f70b6d39487472d800e86fd61cb7353786672d44"),
    (qualification.main, [*CODEX, "qualification-write", *RECORD, "--fixture", "f"],
     lambda: write_graph("codex-operator", ASSEMBLY.pins),
     codex_lane.PREPARE_MODEL, "3434851dfc7347af6e0a2f087d3cf98382e8dc596127de93637b689bf09abc2c"),
    (claude_qualification.main, ["mint", *FLAGS, *CLAUDE],
     lambda: claude_qualification.graph(claude_qualification.fixed_grants(PROVIDER)),
     None, "a572f91a9966fd6f30dff9e1ae0a34589d1bc73cd8efc4ca773e6028ad84244f"),
    (claude_write_qualification.main, ["mint", *FLAGS, *CLAUDE],
     lambda: claude_write_qualification.graph(
         claude_write_qualification.fixed_grants(PROVIDER), ASSEMBLY.pins),
     None, "174a93986a23099794dd7e1bfc93cd0150992e13b18d0d55e5bd9108b3f4b354"),
], ids=["no-dispatch", "read", "write", "claude-read", "claude-write"])
def test_the_three_printed_permits(monkeypatch, capsys, main, argv, graph, model, golden):
    """Each command's printed bytes, with its graph hash and Codex model named, not pinned."""

    async def assembled(*_, **__):
        return ASSEMBLY

    for module in (qualification, claude_qualification, claude_write_qualification):
        monkeypatch.setattr(module, "utc_now", lambda: datetime(2026, 11, 14, tzinfo=UTC))
    monkeypatch.setattr(qualification, "operator_provider", lambda _: PROVIDER)
    monkeypatch.setattr(qualification, "SqliteJournal", lambda path: path)
    monkeypatch.setattr(write_assembly, "assemble_write", assembled)
    monkeypatch.setattr(claude_qualification, "assemble", lambda _: PROVIDER)
    monkeypatch.setattr(claude_write_qualification, "assemble", assembled)
    assert main(argv) == 0
    out, graph_hash = capsys.readouterr().out, str(source_graph_hash_for(graph()))
    assert out.count(graph_hash) == 1
    out = out.replace(graph_hash, "GRAPH")
    if model is not None:
        assert out.count(f'"model":"{model}"') == 1
        out = out.replace(f'"model":"{model}"', '"model":"MODEL"')
    assert sha256(out) == golden
