"""Upgrade coverage for durable M6 schema-v1 command responses."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from constructicon.api.control import ControlPlane
from constructicon.api.run_host import RunHost
from constructicon.core.address import RunId
from constructicon.core.control import (
    APPROVE_SCOPE,
    OPERATE_SCOPE,
    PROMOTE_SCOPE,
    READ_SCOPE,
    ApprovalCommandResult,
    AuthenticatedActor,
    CancellationResult,
    ControlCode,
    ControlRejected,
    PromotionCommandResult,
    RunSubmission,
    command_id_for,
)
from constructicon.core.effect import (
    AttestationDraft,
    CheckResult,
    ComponentProofSubject,
)
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import Digest, canonical_json, digest
from constructicon.core.run import RunStatus
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import BRIEF, ISSUE, atomic, pipeline_graph, triage_impl
from tests.migrations.test_sqlite_v6_to_v7 import _downgrade_v7_schema_to_v6

ACTOR = AuthenticatedActor(
    actor_id="static:v1-upgrade",
    auth_method="static",
    scopes=frozenset({READ_SCOPE, OPERATE_SCOPE, APPROVE_SCOPE, PROMOTE_SCOPE}),
)


def _rewrite_response(
    db_path: Path,
    command_id: str,
    rewrite: Callable[[dict[str, Any]], None],
) -> None:
    """Create exact schema-6 response bytes, then migrate and seal them.

    Terminal responses are immutable in schema 7.  Rewriting a current row and
    its seal would construct a history no production writer can create; the
    compatibility boundary under test is the real schema-6 -> schema-7 climb.
    """

    _downgrade_v7_schema_to_v6(db_path)
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT response_json FROM commands WHERE command_id = ?", (command_id,)
        ).fetchone()
        assert row is not None and isinstance(row[0], str)
        payload = json.loads(row[0])
        assert isinstance(payload, dict)
        rewrite(payload)
        connection.execute(
            "UPDATE commands SET response_json = ? WHERE command_id = ?",
            (
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                command_id,
            ),
        )
        connection.commit()
    SqliteJournal(db_path)


def _schema_v1(payload: dict[str, Any]) -> None:
    payload["schema_version"] = 1


def _schema_v1_run_submission(payload: dict[str, Any]) -> None:
    _schema_v1(payload)
    payload["status_ref"] = {
        "uri": f"constructicon://runs/{payload['run_id']}/result",
        "media_type": "application/json",
        "digest": None,
    }


def _schema_v1_with_uri_only_detail(payload: dict[str, Any]) -> None:
    _schema_v1(payload)
    detail = payload.get("detail")
    assert isinstance(detail, dict)
    detail["digest"] = None


def _prepare_run(world: Any, run_id: RunId) -> None:
    inputs = {"issue": {"title": str(run_id)}}
    manifest = world.validate(pipeline_graph(), inputs)
    world._prepare_run(manifest, run_id=run_id, inputs=inputs)


def _prepare_quiescent_run(
    world: Any,
    journal: SqliteJournal,
    run_id: RunId,
) -> None:
    """Retain a real terminal run that startup recovery must not execute."""

    _prepare_run(world, run_id)
    lease = journal.claim_run(run_id, owner_id="v1-fixture", ttl_s=30)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.RUNNING}),
        target=RunStatus.FAILED,
        event_kind="RunFailed",
    )
    journal.release_run(lease)


def _candidate(world: Any, component: str) -> tuple[Digest, str]:
    definition, impl = atomic(component, (ISSUE,), (BRIEF,), triage_impl)
    baseline = world._register(definition, impl)
    world._promote_initial(component=component, version=baseline)
    candidate = world._register(definition.model_copy(update={"role": "component"}), impl)
    draft = AttestationDraft(
        action="promote",
        subject=ComponentProofSubject(
            component=component,
            version=candidate,
            baseline_version=baseline,
        ),
        checks=(
            CheckResult(
                name="v1-upgrade",
                status="passed",
                detail="fixture candidate passed",
                elapsed_s=0.0,
            ),
        ),
        check_set_hash=digest("check-set", 1, {"fixture": "v1-upgrade"}),
        evidence=(),
        manifest_hash=digest("manifest", 1, {"fixture": component}),
        workspace_id=None,
    )
    attestation = world._journal.mint_policy_attestation(draft)
    return candidate, attestation.attestation_id


async def test_sqlite_replays_v1_run_submission_as_v3(
    world: Any,
    journal: SqliteJournal,
    tmp_path: Path,
) -> None:
    host = RunHost(world, journal=journal, max_concurrency=1)
    control = ControlPlane(system=world, store=journal, run_host=host)
    proposal = pipeline_graph()
    inputs = {"issue": {"title": "v1-start"}}
    first = await control.runs_start(
        ACTOR,
        proposal=proposal,
        inputs=inputs,
        idempotency_key="v1-start",
    )
    assert isinstance(first, RunSubmission)

    _rewrite_response(
        tmp_path / "journal.db",
        first.command.command_id,
        _schema_v1_run_submission,
    )
    replay = await control.runs_start(
        ACTOR,
        proposal=proposal,
        inputs=inputs,
        idempotency_key="v1-start",
    )

    assert isinstance(replay, RunSubmission)
    assert replay.schema_version == 3
    assert replay.run_id == first.run_id
    assert replay.command.replayed is True
    assert "status_ref" not in replay.model_dump(mode="json")
    await host.shutdown()


async def test_v1_upgrade_does_not_excuse_unrelated_scalar_coercion(
    world: Any,
    journal: SqliteJournal,
    tmp_path: Path,
) -> None:
    host = RunHost(world, journal=journal, max_concurrency=1)
    control = ControlPlane(system=world, store=journal, run_host=host)
    proposal = pipeline_graph()
    inputs = {"issue": {"title": "v1-lossless-after-upgrade"}}
    first = await control.runs_start(
        ACTOR,
        proposal=proposal,
        inputs=inputs,
        idempotency_key="v1-lossless-after-upgrade",
    )
    assert isinstance(first, RunSubmission)

    def damage(payload: dict[str, Any]) -> None:
        _schema_v1_run_submission(payload)
        payload["command"]["replayed"] = 0

    _rewrite_response(
        tmp_path / "journal.db",
        first.command.command_id,
        damage,
    )
    with pytest.raises(JournalDamaged, match="matches none of the operation models"):
        await control.runs_start(
            ACTOR,
            proposal=proposal,
            inputs=inputs,
            idempotency_key="v1-lossless-after-upgrade",
        )
    await host.shutdown()


async def test_sqlite_replays_v1_cancellation_as_v3(
    world: Any,
    journal: SqliteJournal,
    tmp_path: Path,
) -> None:
    run_id = RunId("run-v1-cancel")
    _prepare_quiescent_run(world, journal, run_id)
    control = ControlPlane(system=world, store=journal)
    first = await control.runs_cancel(ACTOR, run_id=run_id, idempotency_key="v1-cancel")
    assert isinstance(first, CancellationResult)

    _rewrite_response(tmp_path / "journal.db", first.command.command_id, _schema_v1)
    replay = await control.runs_cancel(ACTOR, run_id=run_id, idempotency_key="v1-cancel")

    assert isinstance(replay, CancellationResult)
    assert replay.schema_version == 3
    assert replay.command.replayed is True
    await control.shutdown()


async def test_sqlite_replays_v1_approval_with_digest_bound_detail(
    world: Any,
    journal: SqliteJournal,
    tmp_path: Path,
) -> None:
    run_id = RunId("run-v1-approval")
    _prepare_quiescent_run(world, journal, run_id)
    stable = world._registry.stable_version("test/triage")
    assert stable is not None
    subject = ComponentProofSubject(
        component="test/triage",
        version=stable,
        baseline_version=stable,
    )
    control = ControlPlane(system=world, store=journal)
    first = await control.runs_approve(
        ACTOR,
        run_id=run_id,
        subject=subject,
        decision="approved",
        reason="upgrade fixture",
        idempotency_key="v1-approval",
    )
    assert isinstance(first, ApprovalCommandResult)

    _rewrite_response(
        tmp_path / "journal.db",
        first.command.command_id,
        _schema_v1_with_uri_only_detail,
    )
    replay = await control.runs_approve(
        ACTOR,
        run_id=run_id,
        subject=subject,
        decision="approved",
        reason="upgrade fixture",
        idempotency_key="v1-approval",
    )

    assert isinstance(replay, ApprovalCommandResult)
    assert replay.schema_version == 3
    assert replay.command.replayed is True
    assert replay.detail.digest is not None
    chunk = control.details_read(ACTOR, replay.detail)
    assert not isinstance(chunk, ControlRejected)
    await control.shutdown()


async def test_sqlite_replays_v1_promotion_with_digest_bound_detail(
    world: Any,
    journal: SqliteJournal,
    tmp_path: Path,
) -> None:
    component = "control/v1-upgrade"
    candidate, attestation_id = _candidate(world, component)
    control = ControlPlane(system=world, store=journal)
    first = await control.registry_promote(
        ACTOR,
        component=component,
        version=candidate,
        attestation_id=attestation_id,
        idempotency_key="v1-promote",
    )
    assert isinstance(first, PromotionCommandResult)

    _rewrite_response(
        tmp_path / "journal.db",
        first.command.command_id,
        _schema_v1_with_uri_only_detail,
    )
    replay = await control.registry_promote(
        ACTOR,
        component=component,
        version=candidate,
        attestation_id=attestation_id,
        idempotency_key="v1-promote",
    )

    assert isinstance(replay, PromotionCommandResult)
    assert replay.schema_version == 3
    assert replay.command.replayed is True
    assert replay.detail.digest is not None
    chunk = control.details_read(ACTOR, replay.detail)
    assert not isinstance(chunk, ControlRejected)
    await control.shutdown()


async def test_damaged_v1_promotion_digest_surfaces_as_journal_damage(
    world: Any,
    journal: SqliteJournal,
    tmp_path: Path,
) -> None:
    component = "control/v1-damaged-promotion"
    candidate, attestation_id = _candidate(world, component)
    control = ControlPlane(system=world, store=journal)
    first = await control.registry_promote(
        ACTOR,
        component=component,
        version=candidate,
        attestation_id=attestation_id,
        idempotency_key="v1-damaged-promotion",
    )
    assert isinstance(first, PromotionCommandResult)

    def damage(payload: dict[str, Any]) -> None:
        _schema_v1(payload)
        payload["to_version"] = "not-a-digest"

    _rewrite_response(
        tmp_path / "journal.db",
        first.command.command_id,
        damage,
    )
    with pytest.raises(JournalDamaged):
        await control.registry_promote(
            ACTOR,
            component=component,
            version=candidate,
            attestation_id=attestation_id,
            idempotency_key="v1-damaged-promotion",
        )
    await control.shutdown()


async def test_sqlite_replays_v1_control_rejection_as_v3(
    world: Any,
    journal: SqliteJournal,
    tmp_path: Path,
) -> None:
    control = ControlPlane(system=world, store=journal)
    run_id = RunId("run-v1-unknown")
    first = await control.runs_cancel(ACTOR, run_id=run_id, idempotency_key="v1-rejection")
    assert isinstance(first, ControlRejected)
    command_id = command_id_for(ACTOR.actor_id, "runs_cancel", "v1-rejection")

    _rewrite_response(tmp_path / "journal.db", command_id, _schema_v1)
    replay = await control.runs_cancel(ACTOR, run_id=run_id, idempotency_key="v1-rejection")

    assert isinstance(replay, ControlRejected)
    assert replay.schema_version == 3
    assert replay.faults == first.faults
    await control.shutdown()


def test_actor_scope_serialization_is_canonical_and_hash_safe() -> None:
    ascending = AuthenticatedActor(
        actor_id="static:scope-order",
        auth_method="static",
        scopes=frozenset((APPROVE_SCOPE, OPERATE_SCOPE, READ_SCOPE)),
    )
    descending = AuthenticatedActor(
        actor_id="static:scope-order",
        auth_method="static",
        scopes=frozenset((READ_SCOPE, OPERATE_SCOPE, APPROVE_SCOPE)),
    )

    expected = sorted((APPROVE_SCOPE, OPERATE_SCOPE, READ_SCOPE))
    assert ascending.model_dump(mode="json")["scopes"] == expected
    assert descending.model_dump(mode="json")["scopes"] == expected
    assert canonical_json(ascending.model_dump(mode="json")) == canonical_json(
        descending.model_dump(mode="json")
    )


def test_control_producers_publish_only_resolver_minted_result_refs(
    world: Any,
    journal: SqliteJournal,
) -> None:
    run_id = RunId("run-control-detail-producer")
    _prepare_run(world, run_id)
    control = ControlPlane(system=world, store=journal)

    pending = control.runs_status(ACTOR, run_id)
    assert not isinstance(pending, ControlRejected)
    assert pending.manifest_ref.digest is not None
    assert pending.result_ref is None

    untyped = control.details_read(ACTOR, pending.manifest_ref.uri)  # type: ignore[arg-type]
    assert isinstance(untyped, ControlRejected)
    assert untyped.faults[0].code is ControlCode.REQUEST_INVALID

    lease = journal.claim_run(run_id, owner_id="detail-producer", ttl_s=30)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.RUNNING}),
        target=RunStatus.FAILED,
        event_kind="RunFailed",
    )
    journal.release_run(lease)
    terminal = journal.latest_terminal_event(run_id)
    assert terminal is not None

    failed = control.runs_status(ACTOR, run_id)
    assert not isinstance(failed, ControlRejected)
    assert failed.result_ref is not None
    assert failed.result_ref.uri.endswith(f"/result/{terminal.seq}")
    chunk = control.details_read(ACTOR, failed.result_ref)
    assert not isinstance(chunk, ControlRejected)
