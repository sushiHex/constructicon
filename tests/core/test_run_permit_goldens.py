"""The run permit's current law, pinned before it is folded (RUN_PERMIT.md, step 1).

docs/designs/RUN_PERMIT.md proposes one law for the two copies in
core/qualification.py and core/maintenance.py. These goldens record what each
copy does today, including where the two differ, so a fold that changes no
behaviour changes no golden. The owner has decided that a later
requalification adopts the tighter epoch and read rules; that change edits the
two divergence tests below, by name.

Every expected value was observed from the unmodified source at aaf9920, never
derived by reading it. Long wires are pinned by SHA-256 to keep the tree small
(#423); sentences are pinned in full.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
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


# One acquisition wrong in every respect: each permit answers with all its sentences, in order.
OTHER = {
    "run_id": run_id_for_command(command_id_for("other", "runs_start", "other")),
    "path": ExecutionPath(scope=ScopePath(segments=("other",))), "binding": "other",
    "source_graph_hash": None, "capability_id": "other", "revision": "other",
    "operator_binding_digest": digest("other", 1, "other"), "epoch": 2,
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


@pytest.mark.parametrize("permit,grants,faults", [
    (stage.read, plan.GRANTS, QUALIFICATION),
    # Divergence kept by the design: absent pinned grants match (qualification.py:158).
    (stage.authorization, plan.GRANTS, tuple(f for f in QUALIFICATION if "grants" not in f)),
    (plan.authorization, stage.GRANTS, MAINTENANCE),
    (channel_authorization, stage.GRANTS, MAINTENANCE),
], ids=["read", "no-dispatch", "plan-manifest", "channel-reply"])
def test_every_acquisition_refusal_sentence(permit, grants, faults):
    assert permit().acquisition_faults(**OTHER, grants=grants) == faults


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
])
def test_every_shape_refusal_sentence(make, change, sentence):
    with pytest.raises(ValidationError) as refused:
        make(**change)
    assert [error["msg"] for error in refused.value.errors()] == [f"Value error, {sentence}"]


# Divergence: qualification admits any epoch <= max_epoch (qualification.py:171);
# maintenance admits exactly the integer one (maintenance.py:232). The
# requalification adopts maintenance's rule (RUN_PERMIT.md, "Three tightenings", 1).
@pytest.mark.parametrize("epoch,qualification_admits,maintenance_admits", [
    (0, True, False), (-1, True, False), (True, True, False), (0.5, True, False),
    (1, True, True), (2, False, False),
])
def test_the_two_epoch_rules(epoch, qualification_admits, maintenance_admits):
    read = stage.read()
    faults = read.acquisition_faults(**{**stage.acquisition(run_id=read.run_id), "epoch": epoch})
    assert (faults == ()) is qualification_admits
    faults = plan.authorization().acquisition_faults(**{**plan.acquisition(), "epoch": epoch})
    assert (faults == ()) is maintenance_admits


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


@pytest.mark.parametrize("main,argv,graph,golden", [
    (qualification.main, [*CODEX, "qualification-no-dispatch"],
     lambda: qualification.qualification_graph("codex-operator", "qualification-no-dispatch"),
     "7a08b51aab51c5a2f1ae1e99b63e38c03abfde571cd9d6ddd9fc143e68b43e03"),
    (qualification.main, [*CODEX, "qualification-read", *RECORD],
     lambda: qualification.qualification_graph("codex-operator", "qualification-read"),
     "156d35d57817d306a5fd73dffce87d695ebd32bd34a80152cbb0537198767f14"),
    (qualification.main, [*CODEX, "qualification-write", *RECORD, "--fixture", "f"],
     lambda: write_graph("codex-operator", ASSEMBLY.pins),
     "e56464af689582eeb39f13ea1af36e5a7fdf9a06188c36fd87349c279341714a"),
    (claude_qualification.main, ["mint", *FLAGS, *CLAUDE],
     lambda: claude_qualification.graph(claude_qualification.fixed_grants(PROVIDER)),
     "a572f91a9966fd6f30dff9e1ae0a34589d1bc73cd8efc4ca773e6028ad84244f"),
    (claude_write_qualification.main, ["mint", *FLAGS, *CLAUDE],
     lambda: claude_write_qualification.graph(
         claude_write_qualification.fixed_grants(PROVIDER), ASSEMBLY.pins),
     "174a93986a23099794dd7e1bfc93cd0150992e13b18d0d55e5bd9108b3f4b354"),
], ids=["no-dispatch", "read", "write", "claude-read", "claude-write"])
def test_the_three_printed_permits(monkeypatch, capsys, main, argv, graph, golden):
    """Each command's printed bytes, with its own graph's hash named rather than pinned."""

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
    assert sha256(out.replace(graph_hash, "GRAPH")) == golden
