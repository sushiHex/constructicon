"""The installed selector over the real Codex adapter and a scripted byte peer."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from argparse import Namespace
from datetime import timedelta
from pathlib import Path

import pytest

from constructicon.api import m9_trial
from constructicon.api._m9 import proposer
from constructicon.api._m9.evaluator import OPERATOR, REGISTRAR, Evaluator
from constructicon.api._m9.evidence import TrialIdentity
from constructicon.api._m9.fixture import TARGET, baseline, diagnostic_definition, report_graph
from constructicon.api._m9.issuer import (
    ISSUER_CAP,
    OPERATOR_ISSUER_PATH,
    Issuer,
    operator_issuer_graph,
)
from constructicon.api._m9.safety import before_startup, selector_run
from constructicon.api._m9.trial import _open, run
from constructicon.api.control import ControlPlane
from constructicon.core.address import RunId
from constructicon.core.control import command_id_for, run_id_for_command
from constructicon.core.effect import ComponentProofSubject
from constructicon.core.envelope import ArtifactRef, utc_now
from constructicon.core.errors import ContractViolation
from constructicon.core.identity import digest
from constructicon.core.manifest import CapabilityBinding, CapabilityLease, source_graph_hash_for
from constructicon.core.qualification import QualificationAuthorization
from constructicon.core.run import RunLease, RunStatus
from constructicon.core.workspace import LeaseContext, StaleAcquisition
from constructicon.substrate.executors.codex import CodexOperatorProvider, launch_identity
from constructicon.substrate.executors.codex_host import READ_GRANTS, READ_PROFILE
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.substrate import test_codex_adapter as adapter
from tests.substrate.test_codex_protocol import completed, usage_update

portable_binding = adapter.portable_binding
substituted_guard = adapter.substituted_guard


def provider(root, trial, binding, native, acquisition_root, *, authorization_override=None):
    launcher = adapter.bare_launcher(native)
    configuration = (
        f'model = "{READ_GRANTS.model_selection.model}"\n'
        f'model_reasoning_effort = "{READ_GRANTS.effort}"\n'
    )
    identity = launch_identity(
        launcher=launcher, profile=READ_PROFILE, egress=adapter.native_egress(),
        store=binding[1].sealed,
        executable_digest=digest("test-codex-executable", 1, adapter.BINARY),
        configuration=configuration, catalog=(),
        authenticated_startup_conformance_revision=digest("test-m9-startup", 1, "unproven"),
        subscription_mode_conformance_revision=digest("test-m9-mode", 1, "unproven"),
    )
    authorization = authorization_override or QualificationAuthorization(
        authorization_id="m9-scripted", stage="qualification-read",
        actor_id=proposer.ACTOR.actor_id, idempotency_key=trial.key("select"),
        scope=proposer.PATH.scope, binding="executor",
        source_graph_hash=source_graph_hash_for(proposer.graph()),
        capability_id=proposer.CAPABILITY, revision=identity.revision,
        operator_binding_digest=identity.store.operator_binding_digest,
        journal=str(root / "journal.sqlite"), max_epoch=1,
        not_after=utc_now() + timedelta(hours=1), grants=READ_GRANTS,
        attempt_record=str(root / "selection.attempt"),
    )
    return CodexOperatorProvider(
        launcher=launcher, profile=READ_PROFILE, identity=identity,
        expected_account=adapter.EXPECTED, binary=adapter.BINARY, configuration=configuration,
        catalog=(), acquisition_root=acquisition_root, binding_store=binding[1],
        closure=binding[2], qualification=authorization,
    )


@pytest.mark.parametrize("raw,expected", [
    ("baseline", "baseline"), ("cite-evidence\n", "cite-evidence"),
    (" \r\n\tbaseline \t", "baseline"),
])
def test_catalog_parser_accepts_only_bounded_literal_ids(raw, expected):
    assert proposer.parse_choice(raw) == expected


@pytest.mark.parametrize("raw", [
    None, {}, b"baseline", "", "cite-evidence" + " " * 64, "\vbaseline", "\u00a0baseline",
    "```baseline```", "choose cite-evidence", "baseline\ncite-evidence", "BASELINE",
])
def test_catalog_parser_refuses_freeform_and_bounds_before_stripping(raw):
    with pytest.raises(ValueError, match="M9_SELECTOR_INVALID_CHOICE"):
        proposer.parse_choice(raw)


def test_every_public_observation_field_has_a_binding_bound_and_refusal_is_closed():
    valid = {
        "choice": "cite-evidence", "source": str(proposer.SOURCE),
        "task": str(digest("task", 1, "task")),
        "provider_revision": str(digest("provider", 1, "provider")),
        "requested_model": "model", "served_model": None,
        "input_tokens": None, "output_tokens": None, "reply_bytes": 13, "elapsed_s": 1.0,
    }
    observed = proposer.checked_observation(valid).model_dump(mode="json")
    assert set(observed) == set(proposer.Observation.model_fields)
    for name, value in observed.items():
        if name == "elapsed_s":
            oversized = float("inf")
        elif name in ("input_tokens", "output_tokens"):
            oversized = 1_000_000_001
        elif name == "reply_bytes":
            oversized = 65
        else:
            oversized = "PRIVATE_VALUE" * 128
        with pytest.raises(proposer.SelectorRefused) as refused:
            proposer.checked_observation({**valid, name: oversized})
        assert str(refused.value) == "M9_SELECTOR_INVALID_OBSERVATION"
        assert "PRIVATE_VALUE" not in str(refused.value)
        assert value is None or isinstance(value, (str, int, float))
    assert m9_trial.refusal_code(ValueError("PRIVATE_VALUE")) == "M9_TRIAL_REFUSED"


@pytest.mark.parametrize("error,code", [
    (TypeError("PRIVATE_VALUE"), "M9_SELECTOR_OBSERVATION_TYPE"),
    (OSError("PRIVATE_VALUE"), "M9_SELECTOR_SOURCE_OR_PROVIDER_UNAVAILABLE"),
    (ContractViolation("PRIVATE_VALUE"), "M9_SELECTOR_CONTRACT_REFUSED"),
])
async def test_selector_closes_untrusted_exception_types(monkeypatch, error, code):
    async def fail(*args):
        raise error

    monkeypatch.setattr(proposer, "_select", fail)
    with pytest.raises(proposer.SelectorRefused) as refused:
        await proposer.select(None, {})
    assert str(refused.value) == code


def test_source_read_failure_does_not_publish_filesystem_detail(monkeypatch):
    def missing(path, *args, **kwargs):
        raise OSError("PRIVATE_PATH")

    monkeypatch.setattr(Path, "open", missing)
    with pytest.raises(proposer.SelectorRefused) as refused:
        proposer.source_revision()
    assert str(refused.value) == "M9_SELECTOR_SOURCE_UNAVAILABLE"


def test_package_inventory_bound_refuses_before_reading_unbounded_files(monkeypatch):
    monkeypatch.setattr(Path, "rglob", lambda *args: iter([Path(__file__)] * 513))
    with pytest.raises(proposer.SelectorRefused) as refused:
        proposer.source_revision()
    assert str(refused.value) == "M9_SELECTOR_SOURCE_INVENTORY_INVALID"


@pytest.mark.parametrize("fault", ["foreign-id", "foreign-graph"])
async def test_startup_positively_refuses_foreign_journal_work_before_recovery(
    tmp_path, monkeypatch, fault,
):
    root, trial = tmp_path / "trial", TrialIdentity("inventory")
    journal = _open(root, trial, initialize=True)
    world = Evaluator.assemble(journal, initialize=True)
    graph = report_graph()
    run_id = RunId("foreign")
    if fault == "foreign-graph":
        run_id = run_id_for_command(command_id_for(
            OPERATOR.actor_id, "runs_start", trial.key("source-train-1"),
        ))
        graph = graph.model_copy(update={"name": "foreign"})
    inputs = {"case": {"evidence_id": "train-1", "observation": "DNS lookup timed out"}}
    manifest = world.system.validate(graph, inputs)
    journal.create_run(
        run_id, manifest_json=manifest.model_dump_json(), manifest_hash=manifest.manifest_hash,
        input_hash=manifest.input_hash, inputs=inputs,
    )
    starts = []

    async def forbidden_startup(control):
        starts.append(control)
        pytest.fail("foreign work reached generic startup recovery")

    monkeypatch.setattr(ControlPlane, "startup", forbidden_startup)
    expected = "UNALLOWLISTED_RUN" if fault == "foreign-id" else "RUN_GRAPH_DRIFT"
    with pytest.raises(ValueError, match=expected):
        await m9_trial.seed(root, trial)
    assert starts == []
    assert journal.run_record(run_id).status == RunStatus.PENDING


async def test_issuer_reconciliation_returns_the_actual_acquisition_identity(tmp_path):
    journal = SqliteJournal(tmp_path / "reconcile.sqlite")
    world = Evaluator.assemble(journal, initialize=True)
    version = diagnostic_definition(baseline).content_hash()
    issuer = Issuer(
        journal=journal, approvals=journal, registry=journal, owner="static:owner",
        subject=ComponentProofSubject(component=TARGET, version=version, baseline_version=None),
        seal=RunId("seal"), proposal=RunId("proposal"),
        projection=ArtifactRef(digest=digest("test", 1, "projection"),
                               media_type="application/json", size=1),
        pairs=(), executor=world.executor, fixture=digest("test", 1, "fixture"),
        reverse_dependencies=world.system.rdeps, operator_mailbox=True,
        current_manifest=lambda inputs: world.system.validate(report_graph(), inputs),
    )
    context = LeaseContext(
        run_lease=RunLease(run_id=RunId("reconcile"), owner_id="owner", epoch=1,
                           expires_at=utc_now() + timedelta(minutes=1)),
        path=OPERATOR_ISSUER_PATH,
        binding=CapabilityBinding(scope=OPERATOR_ISSUER_PATH.scope, binding="issuer",
                                  capability_id=ISSUER_CAP, revision="1",
                                  effective_grants=READ_GRANTS),
        manifest_hash=digest("test", 1, "manifest"),
        source_graph_hash=source_graph_hash_for(operator_issuer_graph()),
    )
    acquired = await issuer.acquire(context)
    row = CapabilityLease(
        lease_id=acquired.lease_id, acquisition_epoch=1, run_id=context.run_lease.run_id,
        binding_id="issuer", path=context.path, state="active", resource_ref=acquired.resource_ref,
    )
    # core/workspace.py acquisition_id_for is the producer used by acquire;
    # CapabilityLease durably retains its two inputs, not an acquisition_id field.
    recovered = await issuer.reconcile(
        context, (StaleAcquisition(lease=row, disposition="discard"),),
    )
    assert recovered.reaped == (acquired.acquisition_id,)
    assert (await issuer.close(acquired, "discard")).disposition == "discarded"


@pytest.mark.parametrize("fault", [
    "freeform", "oversized-telemetry", "damaged-tail", "source-unavailable-after-turn",
])
async def test_bad_native_outcome_records_only_closed_failure_and_cannot_promote(
    tmp_path, portable_binding, substituted_guard, monkeypatch, fault,
):
    root, trial = tmp_path / "trial", TrialIdentity("refusal")
    await m9_trial.seed(root, trial)
    original_source_revision = proposer.source_revision
    records = [completed(answer="cite-evidence")]
    changes = {}
    if fault == "freeform":
        records = [completed(answer="Please use cite-evidence")]
    elif fault == "oversized-telemetry":
        records = [usage_update(input_tokens=1_000_000_001), *records]
    elif fault == "damaged-tail":
        changes = {"tail": b'{"unfinished":'}
    native = adapter.clean_native(records=records, **changes)
    if fault == "source-unavailable-after-turn":
        original_write = native.write

        def unavailable():
            raise OSError("PRIVATE_PATH")

        async def write(raw):
            await original_write(raw)
            if json.loads(raw).get("method") == "turn/start":
                monkeypatch.setattr(proposer, "source_revision", unavailable)

        native.write = write
    with pytest.raises(ValueError, match="INCOMPLETE_PRESERVE_STORE_NO_RETRY"):
        await m9_trial.execute_selection(
            root, trial, provider(root, trial, portable_binding, native, tmp_path / "acquisitions"),
        )
    monkeypatch.setattr(proposer, "source_revision", original_source_revision)
    journal = _open(root, trial, initialize=False)
    run_id = selector_run(trial)
    failures = [event for event in journal.events(run_id, limit=100) if event.kind == "NodeFailed"]
    assert len(failures) == 1
    expected = {
        "freeform": "M9_SELECTOR_INVALID_CHOICE",
        "oversized-telemetry": "M9_SELECTOR_INVALID_OBSERVATION",
        "damaged-tail": "M9_SELECTOR_INVALID_OUTCOME",
        "source-unavailable-after-turn": "M9_SELECTOR_SOURCE_OR_PROVIDER_UNAVAILABLE",
    }[fault]
    assert failures[0].payload == {
        "error": expected,
        "error_type": ("SelectorRefused" if fault in (
            "oversized-telemetry", "source-unavailable-after-turn",
        ) else "ValueError"),
    }
    assert journal.checkpoint(run_id, proposer.PATH) is None
    assert journal.snapshot().stable_version(TARGET) == (
        diagnostic_definition(baseline).content_hash()
    )
    with pytest.raises(ValueError, match="INCOMPLETE_PRESERVE_STORE_NO_RETRY"):
        await run(root, trial, "prepare")


async def test_exact_authorization_and_source_drift_refuse_before_dispatch(
    tmp_path, portable_binding, substituted_guard, monkeypatch,
):
    root, trial = tmp_path / "trial", TrialIdentity("pins")
    await m9_trial.seed(root, trial)
    native = adapter.clean_native(records=[completed(answer="cite-evidence")])
    executor = provider(root, trial, portable_binding, native, tmp_path / "acquisitions")
    authorization = executor.qualification
    assert authorization is not None
    for changes in (
        {"actor_id": "static:other"}, {"idempotency_key": "other"},
        {"source_graph_hash": digest("test", 1, "other")},
        {"revision": str(digest("test", 1, "other"))}, {"max_epoch": 2},
        {"grants": READ_GRANTS.model_copy(update={"timeout_s": 1})},
        {"journal": str(tmp_path / "other.sqlite")},
    ):
        executor.qualification = authorization.model_copy(update=changes)
        with pytest.raises(ValueError, match="M9_SELECTOR_AUTHORIZATION_MISMATCH"):
            await m9_trial.execute_selection(root, trial, executor)
    executor.qualification = authorization
    with monkeypatch.context() as changed:
        changed.setattr(proposer, "source_revision", lambda: digest("test", 1, "other-source"))
        with pytest.raises(ValueError, match="M9_STORE_SOURCE_OR_IDENTITY_DRIFT"):
            await m9_trial.execute_selection(root, trial, executor)
    assert native.received == []
    assert not (root / "selection.attempt").exists()
    assert _open(root, trial, initialize=False).run_record(selector_run(trial)) is None


@pytest.mark.parametrize("choice", ["cite-evidence\n", "baseline"])
async def test_real_adapter_selection_composes_with_scripted_exam_and_owner(
    tmp_path, portable_binding, substituted_guard, monkeypatch, choice,
):
    root, trial = tmp_path / "trial", TrialIdentity("selector")
    await m9_trial.seed(root, trial)
    native = adapter.clean_native(records=[completed(answer=choice)])
    executor = provider(root, trial, portable_binding, native, tmp_path / "acquisitions")
    selected = await m9_trial.execute_selection(root, trial, executor)
    assert selected["evaluation"] == "scripted-diagnostic-exam"
    observed = proposer.Observation.model_validate(selected["observation"])
    assert observed.choice == choice.strip()
    assert observed.served_model is None
    assert observed.requested_model == READ_GRANTS.model_selection.model
    assert observed.reply_bytes == len(choice)
    # The actual adapter's turn/start producer saw the fixed TaskSpec instruction.
    turns = [message for message in native.received if message.get("method") == "turn/start"]
    assert len(turns) == 1
    wire = json.dumps(turns[0])
    assert proposer.task().instruction in turns[0]["params"]["input"][0]["text"]
    assert "train-1" in wire and "held-1" not in wire and "held-2" not in wire
    assert proposer.task().context == () and proposer.task().response_schema is None
    attempt = json.loads((root / "selection.attempt").read_text())
    assert attempt["phase"] == "outcome" and attempt["dispatch"] == "completed"
    journal = _open(root, trial, initialize=False)
    old = diagnostic_definition(baseline).content_hash()
    assert journal.snapshot().stable_version(TARGET) == old

    def no_host(*args, **kwargs):
        pytest.fail("a completed proposal replay constructed a host provider")

    monkeypatch.setattr(m9_trial, "_provider", no_host)
    assert (await m9_trial.dispatch(Namespace(
        stage="propose", trial=trial.trial_id, store=root,
    ))) == {**selected, "replayed": True}
    replay = subprocess.run(
        [sys.executable, "-m", "constructicon.api.m9_trial", "propose",
         "--trial", trial.trial_id, "--store", str(root)],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20, check=False,
    )
    assert replay.returncode == 0, (replay.stdout, replay.stderr)
    assert json.loads(replay.stdout) == {**selected, "replayed": True}
    assert sum(message.get("method") == "turn/start" for message in native.received) == 1
    if observed.choice == "baseline":
        with pytest.raises(ValueError, match="BASELINE_NO_PROMOTION"):
            await run(root, trial, "prepare")
        assert journal.snapshot().stable_version(TARGET) == old
        return
    parked = await run(root, trial, "prepare")
    assert parked["status"] == "awaiting-owner"
    parked_record = journal.run_record(parked["run"])
    for role in ("evaluate", "select"):
        with pytest.raises(ValueError, match=r"ISSUANCE_ASSEMBLY_REQUIRED|NONPREPARATION_RUN"):
            before_startup(journal, trial, role=role)
    with pytest.raises(ValueError, match="ISSUANCE_ASSEMBLY_REQUIRED"):
        await m9_trial.dispatch(Namespace(stage="seed", trial=trial.trial_id, store=root))
    with pytest.raises(ValueError, match=r"ISSUANCE_ASSEMBLY_REQUIRED|NONPREPARATION_RUN"):
        await m9_trial.dispatch(Namespace(stage="pins", trial=trial.trial_id, store=root))
    assert await m9_trial.dispatch(Namespace(
        stage="rehearse", trial=trial.trial_id, store=root,
    )) == parked
    assert journal.run_record(parked["run"]) == parked_record
    assert journal.snapshot().stable_version(TARGET) == old
    await run(root, trial, "approve")
    moved = await run(root, trial, "promote")
    assert moved["from"] == old
    assert await run(root, trial, "promote") == {**moved, "replayed": True}
    assert (await run(root, trial, "rollback"))["to"] == old


@pytest.mark.parametrize("fault", ["intent", "reply"])
def test_literal_process_death_cannot_repeat_uncertain_or_uncheckpointed_dispatch(tmp_path, fault):
    process = subprocess.run(
        [sys.executable, "-m", __name__, str(tmp_path), fault],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=45, check=False,
    )
    assert process.returncode == 73, (process.stdout, process.stderr)
    root, trial = tmp_path / "trial", TrialIdentity("death")
    journal = _open(root, trial, initialize=False)
    run_id = selector_run(trial)
    record = journal.run_record(run_id)
    assert record is not None and record.status == RunStatus.RUNNING
    assert journal.checkpoint(run_id, proposer.PATH) is None
    attempt = json.loads((root / "selection.attempt").read_text())
    assert attempt["phase"] == ("intent" if fault == "intent" else "outcome")
    if fault == "reply":
        assert attempt["dispatch"] == "completed"
    assert (root / "dispatch-count").read_text() == "1"
    for stage in ("propose", "prepare", "approve", "promote", "rollback", "seed"):
        retried = subprocess.run(
            [sys.executable, "-m", "constructicon.api.m9_trial", stage,
             "--trial", trial.trial_id, "--store", str(root)],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20, check=False,
        )
        assert retried.returncode == 1, (retried.stdout, retried.stderr)
        assert "INCOMPLETE_PRESERVE_STORE_NO_RETRY" in retried.stderr
    assert (root / "dispatch-count").read_text() == "1"
    assert journal.snapshot().stable_version(TARGET) == (
        diagnostic_definition(baseline).content_hash()
    )


def test_literal_death_after_registration_replays_same_key_before_one_dispatch(tmp_path):
    environment = {**os.environ, "PYTHONHASHSEED": "0"}
    crashed = subprocess.run(
        [sys.executable, "-m", __name__, str(tmp_path), "registration"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=45, check=False,
        env=environment,
    )
    assert crashed.returncode == 73, (crashed.stdout, crashed.stderr)
    root, trial = tmp_path / "trial", TrialIdentity("death")
    journal = _open(root, trial, initialize=False)
    proof = json.loads((root / "pre-dispatch-observed").read_text())
    assert proof == {
        "registration_committed": True, "native_requests": 0, "attempt_reserved": False,
    }
    registration_id = command_id_for(
        REGISTRAR.actor_id, "registry_register", trial.key("selector-register"),
    )
    original = journal.command(registration_id)
    assert original is not None and original.state == "committed"
    assert journal.run_record(selector_run(trial)) is None
    assert not (root / "selection.attempt").exists()
    resumed = subprocess.run(
        [sys.executable, "-m", __name__, str(tmp_path), "resume-registration"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=45, check=False,
        env=environment,
    )
    assert resumed.returncode == 0, (resumed.stdout, resumed.stderr)
    assert json.loads(resumed.stdout)["status"] == "selected"
    assert journal.command(registration_id) == original
    assert journal.snapshot().stable_version(proposer.COMPONENT) is None
    assert (root / "dispatch-count").read_text() == "1"


async def _die(tmp_path, fault):
    from tests.conftest import portable_acquisition_namespace

    with pytest.MonkeyPatch.context() as patch:
        portable_acquisition_namespace.__wrapped__(patch)
        world_root = tmp_path / ("resumed-world" if fault == "resume-registration" else "world")
        world_root.mkdir()
        binding = adapter.portable_binding.__wrapped__(world_root, patch)
        adapter.substituted_guard.__wrapped__(patch, None)
        root, trial = tmp_path / "trial", TrialIdentity("death")
        await m9_trial.seed(root, trial)
        native = adapter.clean_native(records=[completed(answer="cite-evidence")])
        original_write = native.write

        async def write(raw):
            if json.loads(raw).get("method") == "turn/start":
                (root / "dispatch-count").write_text("1")
                assert json.loads((root / "selection.attempt").read_text())["phase"] == "intent"
                if fault == "intent":
                    os._exit(73)
            await original_write(raw)

        native.write = write
        selected_provider = provider(root, trial, binding, native, tmp_path / "acquisitions")
        authorization_file = root / "authorization.fixture.json"
        if fault == "registration":
            authorization_file.write_text(selected_provider.qualification.model_dump_json())

            original_register = ControlPlane.registry_register

            async def after_registration(control, *args, **kwargs):
                await original_register(control, *args, **kwargs)
                journal = SqliteJournal(root / "journal.sqlite")
                registration = journal.command(command_id_for(
                    REGISTRAR.actor_id, "registry_register", trial.key("selector-register"),
                ))
                assert registration is not None and registration.state == "committed"
                assert native.received == [] and not (root / "selection.attempt").exists()
                (root / "pre-dispatch-observed").write_text(json.dumps({
                    "registration_committed": True, "native_requests": len(native.received),
                    "attempt_reserved": (root / "selection.attempt").exists(),
                }))
                os._exit(73)

            patch.setattr(ControlPlane, "registry_register", after_registration)
        elif fault == "resume-registration":
            selected_provider = provider(
                root, trial, binding, native, tmp_path / "acquisitions",
                authorization_override=QualificationAuthorization.model_validate_json(
                    authorization_file.read_text(),
                ),
            )
            result = await m9_trial.execute_selection(root, trial, selected_provider)
            assert sum(message.get("method") == "turn/start" for message in native.received) == 1
            print(json.dumps(result))
            return
        original_completion = SqliteJournal.record_completion

        def complete(journal, lease, checkpoint):
            if checkpoint.path == proposer.PATH:
                assert json.loads((root / "selection.attempt").read_text())["dispatch"] == (
                    "completed"
                )
                os._exit(73)
            return original_completion(journal, lease, checkpoint)

        patch.setattr(SqliteJournal, "record_completion", complete)
        await m9_trial.execute_selection(root, trial, selected_provider)
        raise AssertionError("the selected crash boundary did not execute")


if __name__ == "__main__":
    asyncio.run(_die(Path(sys.argv[1]), sys.argv[2]))
