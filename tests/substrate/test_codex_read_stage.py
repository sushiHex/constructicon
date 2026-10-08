"""Stage 3's one READ turn under a read authorization (M8 N5, decision S3-1).

Credential-free: the adapter suite's scripted native client over the real
handle. The attempt record must classify every way the attempt can end, from
facts: never dispatched, completed, or possibly dispatched.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from constructicon.core.address import ExecutionPath, ScopePath
from constructicon.core.errors import ContractViolation
from constructicon.core.executor import TaskSpec
from constructicon.core.identity import digest
from constructicon.core.manifest import CapabilityBinding
from constructicon.core.qualification import QualificationAuthorization
from constructicon.core.run import RunLease
from constructicon.core.workspace import LeaseContext
from constructicon.substrate.executors import codex
from constructicon.substrate.executors.attempt_record import AttemptRecord
from constructicon.substrate.executors.codex import CodexOperatorProvider
from tests.substrate import test_codex_adapter as adapter
from tests.substrate.test_codex_adapter import (
    BINARY,
    CAPABILITY,
    CONFIGURATION,
    EMPTY_RESULT,
    EXPECTED,
    GRANTS,
    MANAGED_RESULT,
    bare_launcher,
    clean_native,
    codex_profile,
    identity_for,
)

portable_binding = adapter.portable_binding
substituted_guard = adapter.substituted_guard

GRAPH = digest("test-graph", 1, "qualification-read")
SCOPE = ScopePath(segments=("constructicon-qualification-read", "read"))


def phase(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_record_moves_through_its_three_phases_and_reserves_once(tmp_path):
    path = tmp_path / "stage3.attempt"
    record = AttemptRecord.reserve(path, {"authorization_id": "a"})
    assert phase(path)["phase"] == "acquired"
    assert record.intend() is None and phase(path)["phase"] == "intent"
    record.complete("completed", {"answer_bytes": 5})
    written = phase(path)
    assert (written["phase"], written["dispatch"], written["facts"]) == (
        "outcome", "completed", {"answer_bytes": 5},
    )
    assert written["authorization_id"] == "a"
    assert sorted(item.name for item in tmp_path.iterdir()) == ["stage3.attempt"]
    with pytest.raises(ContractViolation, match="one attempt is spent"):
        AttemptRecord.reserve(path, {"authorization_id": "a"})


def test_an_intent_that_cannot_be_recorded_is_a_refusal_not_a_raise(tmp_path, monkeypatch):
    record = AttemptRecord.reserve(tmp_path / "stage3.attempt", {})

    def broken(content):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(record, "_replace", broken)
    assert record.intend() == "the attempt record could not record intent: No space left on device"


def read_authorization(plain: CodexOperatorProvider, record: Path, **changes):
    fields = {
        "authorization_id": "ci-read",
        "stage": "qualification-read",
        "actor_id": "operator:read",
        "idempotency_key": "stage3",
        "scope": SCOPE,
        "binding": "executor",
        "source_graph_hash": GRAPH,
        "capability_id": CAPABILITY,
        "revision": plain.identity.revision,
        "operator_binding_digest": plain.identity.store.operator_binding_digest,
        "journal": "/var/lib/constructicon/stage3.sqlite",
        "max_epoch": 1,
        "not_after": datetime.now(UTC) + timedelta(hours=1),
        "grants": GRANTS,
        "attempt_record": str(record),
    }
    return QualificationAuthorization(**{**fields, **changes})


def provider(tmp_path, binding, launcher, qualification=None) -> CodexOperatorProvider:
    return CodexOperatorProvider(
        launcher=launcher, profile=codex_profile(),
        identity=identity_for(launcher, store_identity=binding[1].sealed),
        expected_account=EXPECTED, binary=BINARY, configuration=CONFIGURATION, catalog=(),
        acquisition_root=tmp_path / "acquisitions",
        binding_store=binding[1], closure=binding[2], qualification=qualification,
    )


def reading(tmp_path, binding, native):
    """A read-authorized provider over a scripted native client, and its record."""
    record = tmp_path / "stage3.attempt"
    launcher = bare_launcher(native)
    granted = read_authorization(provider(tmp_path, binding, launcher), record)
    return provider(tmp_path, binding, launcher, granted), granted, record


def context(granted) -> LeaseContext:
    return LeaseContext(
        run_lease=RunLease(
            run_id=granted.run_id, owner_id="owner-1", epoch=1,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        ),
        binding=CapabilityBinding(
            scope=SCOPE, binding="executor", capability_id=CAPABILITY,
            revision=granted.revision, effective_grants=GRANTS,
        ),
        path=ExecutionPath(scope=SCOPE),
        manifest_hash=digest("test-manifest", 1, "read"),
        check_control=lambda: None,
        source_graph_hash=GRAPH,
    )


async def turn(qualified, granted):
    acquired = await qualified.acquire(context(granted))
    await acquired.materialize()
    handle = acquired.resource
    outcome = await handle.execute(TaskSpec(instruction="x"), workspace=None, grants=GRANTS)
    return handle, outcome


async def test_one_read_turn_completes_and_its_record_says_so(
    tmp_path, portable_binding, substituted_guard,
):
    qualified, granted, record = reading(tmp_path, portable_binding, clean_native())
    handle, outcome = await turn(qualified, granted)
    assert outcome.status == "success" and handle.dispatch is True
    written = phase(record)
    assert (written["phase"], written["dispatch"]) == ("outcome", "completed")
    facts = written["facts"]
    assert set(facts) == {
        "status", "answer_bytes", "usage", "served_model", "readbacks", "relay", "process",
        "identities",
    }
    assert facts["status"] == "success" and facts["answer_bytes"] == len(outcome.raw_reply)
    assert facts["served_model"] == "unknown" and facts["process"]["returncode"] == 0
    assert facts["identities"]["capability_revision"] == qualified.identity.revision
    assert outcome.raw_reply not in record.read_text(encoding="utf-8")
    with pytest.raises(ContractViolation, match="executes one task only"):
        await handle.execute(TaskSpec(instruction="x"), workspace=None, grants=GRANTS)


async def test_the_spent_attempt_refuses_every_later_acquisition(
    tmp_path, portable_binding, substituted_guard,
):
    """As after a journal reset: the record, not the journal, spends the turn."""
    qualified, granted, record = reading(tmp_path, portable_binding, clean_native())
    await turn(qualified, granted)
    again = provider(tmp_path, portable_binding, bare_launcher(clean_native()), granted)
    with pytest.raises(ContractViolation, match="one attempt is spent"):
        await again.acquire(context(granted))
    assert again.handles == [] and phase(record)["dispatch"] == "completed"


async def test_an_authorization_expired_before_the_turn_dispatches_nothing(
    tmp_path, portable_binding, substituted_guard,
):
    qualified, granted, record = reading(tmp_path, portable_binding, clean_native())
    acquired = await qualified.acquire(context(granted))
    await acquired.materialize()
    qualified.qualification = granted.model_copy(
        update={"not_after": datetime.now(UTC) - timedelta(seconds=1)},
    )
    outcome = await acquired.resource.execute(
        TaskSpec(instruction="x"), workspace=None, grants=GRANTS,
    )
    assert outcome.status == "failure" and "expired" in outcome.error.detail
    assert phase(record)["dispatch"] == "not dispatched"


async def test_a_turn_refused_after_its_intent_is_proven_not_dispatched(
    tmp_path, portable_binding, substituted_guard, monkeypatch,
):
    """The intent is durable, but `turn/start` never reached the client whole:
    the input budget refused it. That is a local failure, not a spent turn."""
    qualified, granted, record = reading(tmp_path, portable_binding, clean_native())
    send = codex.CodexConversation._send

    async def refuse_the_turn(self, io, value):
        if value.get("method") == "turn/start":
            self._refuse("the conversation reached its cumulative input budget")
            return False
        return await send(self, io, value)

    monkeypatch.setattr(codex.CodexConversation, "_send", refuse_the_turn)
    _, outcome = await turn(qualified, granted)
    assert outcome.status == "failure"
    assert phase(record)["dispatch"] == "not dispatched"


async def test_a_failure_after_the_turn_was_written_is_possibly_dispatched(
    tmp_path, portable_binding, substituted_guard,
):
    native = clean_native(accounts=[{"result": MANAGED_RESULT}, {"result": EMPTY_RESULT}])
    qualified, granted, record = reading(tmp_path, portable_binding, native)
    _, outcome = await turn(qualified, granted)
    assert outcome.status == "failure"
    assert phase(record)["dispatch"] == "possibly dispatched"


async def test_a_no_dispatch_authorization_still_never_dispatches(
    tmp_path, portable_binding, substituted_guard,
):
    _, granted, record = reading(tmp_path, portable_binding, clean_native())
    quiet = granted.model_copy(
        update={"stage": "qualification-no-dispatch", "grants": None, "attempt_record": None},
    )
    silent = provider(tmp_path, portable_binding, bare_launcher(clean_native()), quiet)
    acquired = await silent.acquire(context(quiet))
    assert acquired.resource.dispatch is False and acquired.resource.attempt is None
    assert not record.exists()


async def test_a_read_acquisition_dispatches_and_holds_its_reserved_record(
    tmp_path, portable_binding, substituted_guard,
):
    qualified, granted, record = reading(tmp_path, portable_binding, clean_native())
    acquired = await qualified.acquire(context(granted))
    assert acquired.resource.dispatch is True and acquired.resource.attempt is not None
    assert phase(record)["phase"] == "acquired"
