"""Prove closure against the real selector and journal with a scripted native peer."""

import copy
import json
import os
from dataclasses import astuple, replace

import pytest
from scripts.ops import m9_read_closure as closure

from constructicon.api import m9_trial
from constructicon.api._m9 import proposer
from constructicon.api._m9.evidence import TrialIdentity
from constructicon.api._m9.safety import selector_run
from constructicon.api._m9.trial import _open
from constructicon.core.identity import digest
from constructicon.core.run import RunStatus
from tests.e2e.test_m9_executor_trial import provider
from tests.substrate.test_codex_adapter import (
    clean_native,
)
from tests.substrate.test_codex_adapter import (
    portable_binding as portable_binding,
)
from tests.substrate.test_codex_adapter import (
    substituted_guard as substituted_guard,
)
from tests.substrate.test_codex_protocol import completed


def wire(value):
    return (json.dumps(value, sort_keys=True) + "\n").encode()


@pytest.fixture(params=["baseline", "cite-evidence\n"])
async def retained(tmp_path, request, portable_binding, substituted_guard):
    trial = TrialIdentity("m9-live-1")
    store = tmp_path / "trial"
    await m9_trial.seed(store, trial)
    native = clean_native(records=[completed(answer=request.param)])
    executor = provider(store, trial, portable_binding, native, tmp_path / "acquisitions")
    original = await m9_trial.execute_selection(store, trial, executor)
    attempt = store / "selection.attempt"
    identity = executor.identity
    pins = closure.ClosurePins(
        trial.trial_id, executor.qualification.authorization_id, selector_run(trial),
        identity.revision, str(identity.store.operator_binding_digest),
        str(identity.store.subscription_mode_adapter_revision), str(proposer.SOURCE),
        str(digest("m9-selector-task", 1, proposer.task().model_dump(mode="json"))),
    )
    assert sum(m.get("method") == "turn/start" for m in native.received) == 1
    return pins, store, attempt, _open(store, trial, initialize=False), original


def test_guest_projection_and_original_nonreplayed_result(retained, monkeypatch, capsysbinary):
    pins, store, attempt, journal, original = retained
    projection = closure.project(pins, journal, attempt.read_bytes(), next_present=False)
    if os.name == "nt":
        # Windows cannot reproduce the Linux no-follow, uid and 0600 contract.
        monkeypatch.setattr(closure, "_read_attempt", lambda path: path.read_bytes())
    args = [str(store), str(attempt), *astuple(pins)]
    assert closure.main(args) == 0
    emitted = capsysbinary.readouterr()
    assert json.loads(emitted.out) == projection and emitted.err == b""
    result = closure.accept_result(pins, emitted.out, wire(original), b"", 0)
    assert len(result) == 64
    # The operator checkout and Linux installation can have different source bytes.
    with monkeypatch.context() as different_checkout:
        different_checkout.setattr(proposer, "SOURCE", "sha256:" + "0" * 64)
        assert closure.accept_result(pins, emitted.out, wire(original), b"", 0) == result

    for bad in (
        {**original, "replayed": True}, {**original, "replayed": 0},
        {**original, "run": "run-" + "f" * 32}, {**original, "status": "accepted"},
        {**original, "evaluation": "prompt-quality"},
        {**original, "observation": {**original["observation"], "served_model": "assumed"}},
    ):
        with pytest.raises(ValueError):
            closure.accept_result(pins, emitted.out, wire(bad), b"", 0)
    for stderr, rc in ((b"\n", 0), (None, 0), (b"", 1), (b"", None), (b"", False)):
        with pytest.raises(ValueError):
            closure.accept_result(pins, emitted.out, wire(original), stderr, rc)
    for bad in (
        {**projection, "schema_version": True}, {**projection, "lease_closed_released": False},
        {**projection, "attempt_sha256": None}, {**projection, "acquisition_id": "acq-" + "f" * 32},
        {**projection, "pins": {**projection["pins"], "source_digest": "sha256:" + "f" * 64}},
    ):
        with pytest.raises(ValueError):
            closure.accept_result(pins, wire(bad), wire(original), b"", 0)
    duplicate = wire(original).replace(b'"replayed":', b'"replayed": false, "replayed":')
    with pytest.raises(ValueError):
        closure.accept_result(pins, emitted.out, duplicate, b"", 0)

    attempt.with_name(attempt.name + ".next").write_bytes(b"interrupted")
    assert closure.main(args) == 1
    failure = capsysbinary.readouterr()
    assert failure.out == b"" and failure.err == b"M9_READ_CLOSURE_UNPROVED\n"


def test_attempt_and_checkpoint_do_not_substitute_for_each_other(retained, monkeypatch):
    pins, _, attempt, journal, _ = retained
    good = json.loads(attempt.read_bytes())
    for path, bad in (
        (("epoch",), True), (("authorization_id",), "wrong"),
        (("dispatch",), "possibly dispatched"), (("phase",), "intent"),
        (("facts", "answer_bytes"), 64), (("facts", "refusal"), "partial"),
        (("facts", "process", "returncode"), False),
        (("facts", "process", "payload_returncode"), 1),
        (("facts", "process", "timed_out"), True),
        (("facts", "relay", "denied"), {"destination": 1}),
        (("facts", "identities", "qualification"), "sha256:" + "f" * 64),
        (("facts", "identities", "operator_binding_digest"), "sha256:" + "f" * 64),
    ):
        candidate = copy.deepcopy(good)
        owner = candidate
        for key in path[:-1]:
            owner = owner[key]
        owner[path[-1]] = bad
        with pytest.raises(ValueError):
            closure.project(pins, journal, wire(candidate), next_present=False)
    for bad in (
        replace(pins, source_digest="sha256:" + "f" * 64),
        replace(pins, task_digest="sha256:" + "f" * 64),
        replace(pins, provider_revision="sha256:" + "f" * 64),
    ):
        with pytest.raises(ValueError):
            closure.project(bad, journal, wire(good), next_present=False)
    assert journal.checkpoint(pins.run, proposer.PATH) is not None
    record = journal.run_record(pins.run)
    monkeypatch.setattr(
        journal, "run_record", lambda _: record.model_copy(update={"status": RunStatus.RUNNING}),
    )
    with pytest.raises(ValueError):
        closure.project(pins, journal, wire(good), next_present=False)


def test_one_exact_closed_released_lease_is_required(retained, monkeypatch):
    pins, _, attempt, journal, _ = retained
    (lease,) = journal.capability_leases(pins.run)
    for unproved in (
        [], [lease, lease], [lease.model_copy(update={"state": "active"})],
        [lease.model_copy(update={"disposition": "discarded"})],
        [lease.model_copy(update={"acquisition_epoch": 2})],
        [lease.model_copy(update={"binding_id": "other"})],
        [lease.model_copy(update={"lease_id": "lease-" + "f" * 32})],
    ):
        monkeypatch.setattr(journal, "capability_leases", lambda _, rows=unproved: rows)
        with pytest.raises(ValueError):
            closure.project(pins, journal, attempt.read_bytes(), next_present=False)
