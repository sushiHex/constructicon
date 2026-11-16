"""The change-review advice route: one permitted Codex READ turn (ADR 0025).

Credential-free: the real Codex adapter, walker, journal and control plane over
the adapter suite's scripted byte peer, under a READ permit exactly as the
qualification entry's tests drive it. Every provider here is built the way host
assembly builds one, with no reason tuple: its published reasons stay intact.
Nothing here proves a real model answers usefully, vendor facts, containment
on the private host, owner provenance of a permit, or cost.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from argparse import Namespace
from datetime import timedelta
from pathlib import Path

import pytest
from examples.change_review import (
    ADVISOR_COMPONENT,
    DEMO_AFTER,
    DEMO_BEFORE,
    committed_source,
    compare_sources,
    demo_commits,
    inspection,
    review_graph,
)

from constructicon.api import _metered_native
from constructicon.api import change_review_advice as route
from constructicon.api.system import Constructicon
from constructicon.core.address import ExecutionPath
from constructicon.core.control import (
    ADMIN_SCOPE,
    READ_SCOPE,
    AuthenticatedActor,
    command_id_for,
    run_id_for_command,
)
from constructicon.core.envelope import utc_now
from constructicon.core.errors import ContractViolation
from constructicon.core.executor import ExecutorError, ExecutorFailure, ExecutorSuccess
from constructicon.core.graph import Connection, Graph, GraphNode, Ref
from constructicon.core.identity import digest
from constructicon.core.manifest import source_graph_hash_for
from constructicon.core.qualification import QualificationAuthorization
from constructicon.core.refusal import RefusalCode
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.sdk.std import ADVICE_REPLY, PANEL_BALLOT_COMPONENT, PANEL_VOTE, definitions
from constructicon.substrate.executors.codex import (
    UNQUALIFIED_PREREQUISITES,
    CodexOperatorHandle,
    CodexOperatorProvider,
    launch_identity,
)
from constructicon.substrate.executors.codex_host import READ_GRANTS, READ_PROFILE
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.substrate import test_codex_adapter as adapter
from tests.substrate.test_codex_protocol import completed, rerouted, usage_update

portable_binding = adapter.portable_binding
substituted_guard = adapter.substituted_guard

PATH = ExecutionPath(scope=route.SCOPE)
CONFIGURATION = (
    f'model = "{READ_GRANTS.model_selection.model}"\n'
    f'model_reasoning_effort = "{READ_GRANTS.effort}"\n'
)


def summary_of(before: str, after: str) -> route.ChangeSummaryV1:
    """The example's own producer, so the contract is checked against it."""
    report = compare_sources(before, after).model_dump(mode="json", exclude={"tests_executed"})
    return route.ChangeSummaryV1.model_validate(report)


DEMO = summary_of(DEMO_BEFORE, DEMO_AFTER)
OTHER = summary_of(DEMO_BEFORE, "def other(values):\n    return values\n")


def permit_for(tmp_path: Path, identity, summary: route.ChangeSummaryV1, **changes):
    bound = route.bound_values(summary)
    fields = {
        "authorization_id": "ci-change-review-advice", "stage": "qualification-read",
        "actor_id": route.ACTOR_ID, "idempotency_key": bound.idempotency_key,
        "scope": route.SCOPE, "binding": route.EXECUTOR,
        "source_graph_hash": bound.source_graph_hash, "capability_id": route.CAPABILITY,
        "revision": identity.revision,
        "operator_binding_digest": identity.store.operator_binding_digest,
        "journal": str((tmp_path / "advice.sqlite").resolve()), "max_epoch": 1,
        "not_after": utc_now() + timedelta(hours=1), "grants": READ_GRANTS,
        "attempt_record": str((tmp_path / "advice.attempt").resolve()),
    }
    return QualificationAuthorization(**{**fields, **changes})


def provider(tmp_path: Path, binding, native, summary=DEMO, **changes) -> CodexOperatorProvider:
    """Shaped as ``codex_host.operator_provider`` builds it: no reason tuple."""
    launcher = adapter.bare_launcher(native)
    identity = launch_identity(
        launcher=launcher, profile=READ_PROFILE, egress=adapter.native_egress(),
        store=binding[1].sealed,
        executable_digest=digest("test-codex-executable", 1, adapter.BINARY),
        configuration=CONFIGURATION, catalog=(),
        authenticated_startup_conformance_revision=digest("test-advice-startup", 1, "unproven"),
        subscription_mode_conformance_revision=digest("test-advice-mode", 1, "unproven"),
    )
    return CodexOperatorProvider(
        launcher=launcher, profile=READ_PROFILE, identity=identity,
        expected_account=adapter.EXPECTED, binary=adapter.BINARY, configuration=CONFIGURATION,
        catalog=(), acquisition_root=(tmp_path / "acquisitions").resolve(),
        binding_store=binding[1], closure=binding[2],
        qualification=permit_for(tmp_path, identity, summary, **changes),
    )


def turns(native) -> list[dict]:
    return [message for message in native.received if message.get("method") == "turn/start"]


def published(executor: CodexOperatorProvider) -> tuple[bool, tuple[str, ...]]:
    """What ``describe()`` publishes for this provider, from a separate journal."""
    observer = Path(executor.qualification.journal).with_name("describe.sqlite")
    system = Constructicon(
        journal=SqliteJournal(observer), capabilities={route.CAPABILITY: executor},
        catalog={route.CAPABILITY: CapabilityDescriptor(
            capability_id=route.CAPABILITY, kind="executor", leased=True,
            revision=executor.identity.revision, executor_profile=executor.profile,
        )},
    )
    (capability,) = system.describe().capabilities
    return capability.available, tuple(capability.unavailable_reasons)


def failure(journal_path: str, run_id) -> dict:
    journal = SqliteJournal(journal_path)
    (event,) = [e for e in journal.events(run_id, limit=200) if e.kind == "NodeFailed"]
    assert journal.checkpoint(run_id, PATH) is None
    return event.payload


# --- the accepting path ----------------------------------------------------------


async def test_the_permitted_graph_runs_one_turn_and_every_reason_stays_published(
    tmp_path, portable_binding, substituted_guard,
):
    native = adapter.clean_native(records=[completed(answer="Add empty-input tests.")])
    executor = provider(tmp_path, portable_binding, native)
    during = []
    original = native.write

    async def write(raw):
        if b'"turn/start"' in raw:
            during.append((executor.unavailable_reasons, published(executor)))
        await original(raw)

    native.write = write
    before = (executor.unavailable_reasons, published(executor))
    outcome = await route.advise(provider=executor, summary=DEMO)
    after = (executor.unavailable_reasons, published(executor))
    expected = (UNQUALIFIED_PREREQUISITES, (False, UNQUALIFIED_PREREQUISITES))
    assert before == after == expected and during == [expected]
    assert outcome["replayed"] is False
    result = outcome["result"]
    assert result["status"] == "succeeded" and len(turns(native)) == 1
    advice = result["outputs"]["advice"]
    assert set(advice) == set(route.ModelAdvicePayload.model_fields)
    assert "actor_id" not in advice and "message_id" not in advice
    assert advice["advice"] == "Add empty-input tests."
    assert advice["metering_source"] == "codex_fresh_thread_total_v1"
    assert advice["capability_revision"] == executor.identity.revision
    assert advice["requested_model"] == READ_GRANTS.model_selection.model
    assert advice["served_model"] is None
    assert advice["reply_bytes"] == len("Add empty-input tests.")
    bound = route.bound_values(DEMO)
    assert advice["instruction_digest"] == str(bound.instruction_digest)
    record = json.loads(Path(executor.qualification.attempt_record).read_text("utf-8"))
    assert (record["phase"], record["dispatch"]) == ("outcome", "completed")


async def test_a_completed_run_replays_and_never_dispatches_again(
    tmp_path, portable_binding, substituted_guard, monkeypatch,
):
    native = adapter.clean_native(records=[completed(answer="Test count.")])
    first = await route.advise(provider=provider(tmp_path, portable_binding, native),
                               summary=DEMO)
    again = provider(tmp_path, portable_binding, adapter.clean_native())
    second = await route.advise(provider=again, summary=DEMO)
    assert second == {**first, "replayed": True}
    assert again.handles == [] and len(turns(native)) == 1

    def forbidden(*args, **kwargs):
        pytest.fail("a completed replay read a permit or built a provider")

    monkeypatch.setattr(route, "read_authorization", forbidden)
    monkeypatch.setattr(route, "operator_provider", forbidden)
    options = Namespace(stage="run", journal=(tmp_path / "advice.sqlite").resolve(),
                        authorization=tmp_path / "owner.json")
    assert await route.dispatch(options, DEMO) == second


async def test_a_reset_journal_cannot_spend_the_turn_again(
    tmp_path, portable_binding, substituted_guard,
):
    native = adapter.clean_native(records=[completed(answer="Test count.")])
    await route.advise(provider=provider(tmp_path, portable_binding, native), summary=DEMO)
    reset = provider(tmp_path, portable_binding, adapter.clean_native(),
                     journal=str((tmp_path / "reset.sqlite").resolve()))
    with pytest.raises(ContractViolation) as refused:
        await route.advise(provider=reset, summary=DEMO)
    assert refused.value.refusal == (RefusalCode.ADVICE_PERMIT,)
    assert reset.handles == [] and len(turns(native)) == 1


async def test_a_journal_holding_another_run_is_refused_before_recovery(
    tmp_path, portable_binding, substituted_guard,
):
    """One permit, one journal: its RunHost would resume whatever it holds."""
    native = adapter.clean_native(records=[completed(answer="Test count.")])
    await route.advise(provider=provider(tmp_path, portable_binding, native), summary=DEMO)
    second = adapter.clean_native()
    other = provider(tmp_path, portable_binding, second, summary=OTHER,
                     attempt_record=str((tmp_path / "other.attempt").resolve()))
    with pytest.raises(ContractViolation) as refused:
        await route.advise(provider=other, summary=OTHER)
    assert refused.value.refusal == (RefusalCode.ADVICE_JOURNAL,)
    assert second.received == [] and other.handles == []
    assert not (tmp_path / "other.attempt").exists()


async def test_the_peer_receives_exactly_the_permitted_bytes_and_no_path(
    tmp_path, portable_binding, substituted_guard,
):
    repository, before_commit, after_commit = demo_commits(tmp_path / "sample")
    before_ref, before = committed_source(repository, before_commit, "calc.py")
    _, after = committed_source(repository, after_commit, "calc.py")
    summary = summary_of(before, after)
    native = adapter.clean_native(records=[completed(answer="ok")])
    executor = provider(tmp_path, portable_binding, native, summary=summary)
    await route.advise(provider=executor, summary=summary)
    (turn,) = turns(native)
    (item,) = turn["params"]["input"]
    sent = item["text"].encode("utf-8")
    digest_hex = hashlib.sha256(sent).hexdigest()
    assert executor.qualification.idempotency_key == route.KEY_PREFIX + digest_hex
    assert sent == route.bound_values(summary).instruction.encode("utf-8")
    assert len(sent) <= route.INSTRUCTION_MAX_BYTES and b"\r" not in sent
    wire = b"".join(native.raw_received)
    for private in (str(tmp_path), str(repository), before_ref.repository,
                    json.dumps(before_ref.repository)[1:-1], tmp_path.name,
                    str(tmp_path).replace("\\", "/"), "calc.py", "return sum"):
        assert private.encode("utf-8") not in wire
    assert b"/" not in sent and b"\\" not in sent
    assert set(json.loads(sent.decode().partition("\nSummary: ")[2])) == set(
        route.ChangeSummaryV1.model_fields
    )


# --- the guards --------------------------------------------------------------------


async def test_another_packet_under_the_permit_refuses_before_any_turn(
    tmp_path, portable_binding, substituted_guard,
):
    native = adapter.clean_native()
    executor = provider(tmp_path, portable_binding, native, summary=DEMO)
    with pytest.raises(ContractViolation) as refused:
        await route.advise(provider=executor, summary=OTHER)
    assert refused.value.refusal == (RefusalCode.ADVICE_INSTRUCTION,)
    assert native.received == [] and executor.handles == []
    assert not Path(executor.qualification.journal).exists()
    assert not Path(executor.qualification.attempt_record).exists()


async def test_a_packet_that_bypasses_the_entry_spends_no_turn_at_the_node(
    tmp_path, portable_binding, substituted_guard, monkeypatch,
):
    """Submitted under the permitted key, another packet reaches the node; the
    node's recomputation refuses before ``execute``. It spends the permit's
    reservation without a dispatch, as ADR 0025 section 2 says it must."""
    native = adapter.clean_native()
    executor = provider(tmp_path, portable_binding, native, summary=DEMO)
    permitted = route.bound_values(DEMO)
    monkeypatch.setattr(route, "bound_values", lambda summary: permitted)
    outcome = await route.advise(provider=executor, summary=OTHER)
    assert outcome["result"]["status"] == "failed"
    assert turns(native) == []
    assert failure(executor.qualification.journal, permitted.run_id)["refusal"] == [
        "advice.instruction",
    ]


@pytest.mark.parametrize(("records", "codes"), [
    ([completed(answer="")], ["advice.not_positive"]),
    ([completed(answer=None)], ["advice.not_positive"]),
    ([completed(answer="done", status="failed")], ["advice.not_positive"]),
    ([completed(answer="x" * (route.MODEL_ADVICE_MAX_BYTES + 1))], ["advice.reply_bound"]),
    ([completed(answer="\N{SNOWMAN}" * (route.MODEL_ADVICE_MAX_BYTES // 3 + 1))],
     ["advice.reply_bound"]),
], ids=["empty", "absent", "failed", "oversized", "oversized-in-bytes"])
async def test_a_reply_that_is_not_bounded_text_refuses_and_never_checkpoints(
    tmp_path, portable_binding, substituted_guard, records, codes,
):
    native = adapter.clean_native(records=records)
    executor = provider(tmp_path, portable_binding, native)
    outcome = await route.advise(provider=executor, summary=DEMO)
    assert outcome["result"]["status"] == "failed" and len(turns(native)) == 1
    payload = failure(executor.qualification.journal, route.bound_values(DEMO).run_id)
    assert payload["refusal"] == codes


async def test_a_reply_at_its_bound_is_accepted(tmp_path, portable_binding, substituted_guard):
    answer = "x" * route.MODEL_ADVICE_MAX_BYTES
    native = adapter.clean_native(records=[completed(answer=answer)])
    executor = provider(tmp_path, portable_binding, native)
    outcome = await route.advise(provider=executor, summary=DEMO)
    assert outcome["result"]["status"] == "succeeded"
    # The public preview may truncate a large value; the checkpoint holds it whole.
    journal = SqliteJournal(executor.qualification.journal)
    retained = journal.checkpoint(route.bound_values(DEMO).run_id, PATH)
    assert retained is not None
    payload = retained.outputs["advice"].payload
    assert payload["advice"] == answer and payload["reply_bytes"] == route.MODEL_ADVICE_MAX_BYTES


@pytest.mark.parametrize(("outcome", "codes"), [
    (ExecutorSuccess(output="", requested_model="m"), (RefusalCode.ADVICE_NOT_POSITIVE,)),
    (ExecutorSuccess(output=None, requested_model="m"), (RefusalCode.ADVICE_NOT_POSITIVE,)),
    (ExecutorSuccess(output={"advice": "x"}, requested_model="m"),
     (RefusalCode.ADVICE_NOT_POSITIVE,)),
    (ExecutorFailure(output="salvaged", error=ExecutorError(
        kind="timeout", detail="t", refusal=(RefusalCode.PERMIT_EXPIRED,))),
     (RefusalCode.ADVICE_NOT_POSITIVE, RefusalCode.PERMIT_EXPIRED)),
    (ExecutorSuccess(output="ok", requested_model=None), (RefusalCode.ADVICE_NOT_POSITIVE,)),
], ids=["empty", "none", "structured", "salvaged-failure", "unrecorded-model"])
async def test_the_node_accepts_only_a_bounded_text_success(outcome, codes):
    """Outcomes the scripted peer cannot produce, at the node's own guard."""
    handle = object.__new__(CodexOperatorHandle)
    sent = []

    async def execute(task, *, workspace, grants):
        sent.append(task)
        return outcome

    handle.execute = execute
    handle.context = Namespace(binding=Namespace(revision="sha256:" + "0" * 64))
    bound = route.bound_values(DEMO)
    ctx = Namespace(run_id=bound.run_id, capability=lambda alias: handle, grants=READ_GRANTS)
    with pytest.raises(ContractViolation) as refused:
        await route.advise_node(ctx, {"summary": DEMO.model_dump(mode="json")})
    assert refused.value.refusal == codes
    assert [task.instruction for task in sent] == [bound.instruction]
    assert sent[0].context == () and sent[0].response_schema is None


def test_an_oversized_instruction_refuses_by_name_and_is_never_truncated():
    wide = ["\u4e00" * 80 + str(n) for n in range(25)]
    names = [name[:80] for name in wide]
    summary = DEMO.model_copy(update={"symbols": {"added": names, "removed": names,
                                                  "changed": names}})
    with pytest.raises(ContractViolation) as refused:
        route.instruction_for(route.ChangeSummaryV1.model_validate(summary.model_dump()))
    assert refused.value.refusal == (RefusalCode.ADVICE_INSTRUCTION_BOUND,)
    narrow = DEMO.model_copy(update={"symbols": {"added": [n[:20] for n in names]}})
    assert len(route.instruction_for(narrow).encode()) <= route.INSTRUCTION_MAX_BYTES


@pytest.mark.parametrize("change", [
    {"tests_executed": False},
    {"before_ref": {"repository": "/private/repository"}},
    {"source": "def total(values): ..."},
    {"symbols": {"added": ["a/b"]}},
    {"symbols": {"added": ["../etc"]}},
    {"symbols": {"elsewhere": ["name"]}},
    {"syntax_errors": {"after": "line 1: /private/repository/calc.py"}},
    {"comparison_available": "true"},
], ids=["tests-executed", "git-ref", "source", "slash", "dots", "kind", "diagnostic", "coerced"])
async def test_a_field_outside_the_closed_summary_refuses_at_the_node(change):
    payload = {**DEMO.model_dump(mode="json"), **change}
    with pytest.raises(ContractViolation) as refused:
        await route.advise_node(Namespace(run_id="unused"), {"summary": payload})
    assert refused.value.refusal == (RefusalCode.ADVICE_SUMMARY,)


async def test_the_node_compares_its_run_before_it_touches_the_executor():
    touched = []
    ctx = Namespace(run_id="run-elsewhere", capability=lambda alias: touched.append(alias))
    with pytest.raises(ContractViolation) as refused:
        await route.advise_node(ctx, {"summary": DEMO.model_dump(mode="json")})
    assert refused.value.refusal == (RefusalCode.ADVICE_INSTRUCTION,) and touched == []
    expected = run_id_for_command(command_id_for(
        route.ACTOR_ID, "runs_start", route.bound_values(DEMO).idempotency_key,
    ))
    assert route.advice_run_id(route.bound_values(DEMO).instruction) == expected


@pytest.mark.parametrize("changes", [
    {"actor_id": "static:other"}, {"stage": "qualification-no-dispatch", "grants": None,
                                   "attempt_record": None},
    {"source_graph_hash": digest("test", 1, "other")}, {"capability_id": "codex-other"},
    {"grants": READ_GRANTS.model_copy(update={"timeout_s": 1})},
    {"scope": route.ScopePath(segments=("elsewhere", "advise"))}, {"journal": "relative.sqlite"},
], ids=["actor", "stage", "graph", "capability", "grants", "scope", "journal"])
async def test_a_permit_naming_anything_else_refuses_before_any_journal(
    tmp_path, portable_binding, substituted_guard, changes,
):
    native = adapter.clean_native()
    executor = provider(tmp_path, portable_binding, native, **changes)
    with pytest.raises(ContractViolation) as refused:
        await route.advise(provider=executor, summary=DEMO)
    assert refused.value.refusal == (RefusalCode.ADVICE_PERMIT,)
    assert native.received == [] and not (tmp_path / "advice.sqlite").exists()


async def test_an_absent_permit_is_a_named_refusal_not_a_fallback(
    tmp_path, portable_binding, substituted_guard,
):
    executor = provider(tmp_path, portable_binding, adapter.clean_native())
    executor.qualification = None
    with pytest.raises(ContractViolation) as refused:
        await route.advise(provider=executor, summary=DEMO)
    assert refused.value.refusal == (RefusalCode.ADVICE_PERMIT,)
    options = Namespace(stage="run", journal=(tmp_path / "advice.sqlite").resolve(),
                        authorization=None)
    with pytest.raises(ContractViolation) as unpermitted:
        await route.dispatch(options, DEMO)
    assert unpermitted.value.refusal == (RefusalCode.ADVICE_PERMIT,)


async def test_an_assembly_that_passes_a_reason_tuple_is_refused(
    tmp_path, portable_binding, substituted_guard, monkeypatch,
):
    """The premortem's first failure: an emptied tuple must never reach a run."""
    built = provider(tmp_path, portable_binding, adapter.clean_native())
    available = CodexOperatorProvider(
        launcher=built.launcher, profile=built.profile, identity=built.identity,
        expected_account=built.expected_account, binary=built.binary,
        configuration=built.configuration, catalog=built.catalog,
        acquisition_root=(tmp_path / "acquisitions").resolve(), unavailable_reasons=(),
        binding_store=built.binding_store, closure=built.closure,
        qualification=built.qualification,
    )
    with pytest.raises(ContractViolation) as refused:
        await route.advise(provider=available, summary=DEMO)
    assert refused.value.refusal == (RefusalCode.ADVICE_PROVIDER,)
    assert not (tmp_path / "advice.sqlite").exists()


async def test_the_route_assembles_only_through_host_assembly_with_reasons_intact(
    tmp_path, portable_binding, substituted_guard, monkeypatch,
):
    """The installed ``run`` builds its provider only through ``host_provider``;
    with host assembly substituted by its credential-free twin, the run succeeds
    and the provider it used still publishes every reason."""
    native = adapter.clean_native(records=[completed(answer="Test it.")])
    executor = provider(tmp_path, portable_binding, native)
    seen = []

    def assembly(host, authorization):
        assert authorization == executor.qualification
        seen.append(host)
        return executor

    monkeypatch.setattr(route, "operator_provider", assembly)
    monkeypatch.setattr(route, "read_authorization", lambda path: executor.qualification)
    options = Namespace(
        stage="run", journal=Path(executor.qualification.journal),
        authorization=tmp_path / "owner.json", session=tmp_path, store_key="key",
        sealed=tmp_path, qualification=tmp_path, host_state=tmp_path,
    )
    try:
        outcome = await route.dispatch(options, DEMO)
    except ContractViolation as error:
        pytest.fail(f"the route's own assembly was refused: {error.refusal}")
    assert len(seen) == 1 and outcome["result"]["status"] == "succeeded"
    assert executor.unavailable_reasons == UNQUALIFIED_PREREQUISITES


def _mint_argv(tmp_path: Path, summary_file: Path, *extra: str) -> list[str]:
    return [
        "--summary", str(summary_file), "--stage", "mint",
        "--session", str(tmp_path), "--sealed", str(tmp_path),
        "--qualification", str(tmp_path), "--state", str(tmp_path), "--store-key", "key",
        "--journal", str((tmp_path / "fresh.sqlite").resolve()),
        "--attempt-record", str((tmp_path / "fresh.attempt").resolve()), *extra,
    ]


@pytest.mark.parametrize("extra", [(), ("--authorization-id", ""),
                                   ("--authorization-id", "x" * 129)])
def test_mint_refuses_a_missing_or_unbounded_id_by_name_before_assembly(
    tmp_path, monkeypatch, capsys, extra,
):
    """Through the installed entry: the id is checked before host assembly runs."""
    summary_file = tmp_path / "summary.json"
    summary_file.write_text(DEMO.model_dump_json(), encoding="utf-8")

    def forbidden(*args, **kwargs):
        raise AssertionError("host assembly ran before the mint inputs were checked")

    monkeypatch.setattr(route, "operator_provider", forbidden)
    assert route.main(_mint_argv(tmp_path, summary_file, *extra)) == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "refused"
    assert printed["refusal"] == [str(RefusalCode.ADVICE_PERMIT)]


def test_mint_through_the_installed_entry_prints_the_candidate(
    tmp_path, portable_binding, monkeypatch, capsys,
):
    """Accepting mint, with only host assembly replaced by its credential-free twin."""
    native = adapter.clean_native(records=[])
    executor = provider(tmp_path, portable_binding, native)
    monkeypatch.setattr(route, "operator_provider", lambda host, authorization: executor)
    summary_file = tmp_path / "summary.json"
    summary_file.write_text(DEMO.model_dump_json(), encoding="utf-8")
    argv = _mint_argv(tmp_path, summary_file, "--authorization-id", "owner-advice-1")
    assert route.main(argv) == 0
    candidate = QualificationAuthorization.model_validate_json(capsys.readouterr().out)
    bound = route.bound_values(DEMO)
    assert candidate.authorization_id == "owner-advice-1"
    assert candidate.idempotency_key == bound.idempotency_key
    assert candidate.source_graph_hash == bound.source_graph_hash
    assert candidate.revision == executor.identity.revision
    assert not (tmp_path / "fresh.sqlite").exists() and not (tmp_path / "fresh.attempt").exists()
    assert turns(native) == []


def test_the_route_constructs_no_provider_and_passes_no_reasons():
    source = Path(route.__file__).read_text(encoding="utf-8")
    assert "unavailable_reasons=" not in source
    assert "CodexOperatorProvider(" not in source
    assert source.count("operator_provider(") == 1


# --- metering, contracts and identity ---------------------------------------------


async def test_metering_reaches_the_versioned_result(
    tmp_path, portable_binding, substituted_guard,
):
    native = adapter.clean_native(records=[
        usage_update(input_tokens=5, output_tokens=1),
        usage_update(input_tokens=13, output_tokens=4),
        rerouted("gpt-6-rerouted"), completed(answer="Test count."),
    ])
    outcome = await route.advise(provider=provider(tmp_path, portable_binding, native),
                                 summary=DEMO)
    result = outcome["result"]
    assert result["result_schema_version"] == 3
    metering = result["metering"]
    assert metering["coverage"] == "supported_observations" and metering["attempt_count"] == 1
    (group,) = metering["groups"]
    assert group["source"] == route.METERING_SOURCE
    assert (group["known_input_tokens"], group["known_output_tokens"]) == (13, 4)
    assert metering["estimate"] is None and metering["confirmed_charge"] is None
    assert result["outputs"]["advice"]["served_model"] == "gpt-6-rerouted"
    (codex,) = [entry for entry in _metered_native._ROUTES
                if entry.provider is CodexOperatorProvider]
    assert codex.source == route.METERING_SOURCE


async def test_model_advice_cannot_bind_where_human_advice_is_required(
    tmp_path, portable_binding, substituted_guard,
):
    executor = provider(tmp_path, portable_binding, adapter.clean_native())
    system = Constructicon(
        journal=SqliteJournal(tmp_path / "admission.sqlite"), root_grants=READ_GRANTS,
        capabilities={route.CAPABILITY: executor},
        catalog={route.CAPABILITY: CapabilityDescriptor(
            capability_id=route.CAPABILITY, kind="executor", leased=True,
            revision=executor.identity.revision, executor_profile=executor.profile,
        )},
    )
    system._register(route.advice_definition(), route.advise_node)
    (ballot,) = [bundle for bundle in definitions() if bundle.name == PANEL_BALLOT_COMPONENT]
    system._register(ballot.definition, ballot.implementation)
    assert ADVICE_REPLY in ballot.definition.inputs
    assert route.MODEL_ADVICE.name == ADVICE_REPLY.name
    assert route.MODEL_ADVICE.type_id != ADVICE_REPLY.type_id
    (advise,) = route.advice_graph().nodes
    graph = Graph(
        name="advice-into-human-ballot", inputs=(route.SUMMARY,), outputs=(PANEL_VOTE,),
        nodes=(advise, GraphNode(id="ballot", body=Ref(
            component=PANEL_BALLOT_COMPONENT, version=str(ballot.definition.content_hash()),
        ))),
        connections=(Connection(src="advise", dst="ballot", map={"advice": "advise.advice"}),),
    )
    rejected = system.admit_graph(graph, {"summary": DEMO.model_dump(mode="json")})
    assert rejected.status == "rejected"
    (mismatch,) = [fault for fault in rejected.faults
                   if fault.code == "graph.port.contract_mismatch"]
    assert mismatch.details["destination_contract"] == {
        "type_id": "constructicon.std/AdviceResponse", "schema_hash": "advice-response-1",
    }
    assert mismatch.details["source_contract"]["type_id"] == "constructicon.consumer/ModelAdvice"
    assert mismatch.details["destination_port"] == "advice"


def _variant(tmp_path: Path, name: str, old: str, new: str):
    """A copy of the route's module under its own name, with one edit."""
    source = Path(route.__file__).read_text(encoding="utf-8")
    assert source.count(old) == 1
    path = tmp_path / f"{name}.py"
    path.write_bytes(source.replace(old, new).encode("utf-8"))
    spec = importlib.util.spec_from_file_location(route.__name__, path)
    module = importlib.util.module_from_spec(spec)
    saved = sys.modules.get(route.__name__)
    try:
        spec.loader.exec_module(module)
    finally:
        if saved is not None:
            sys.modules[route.__name__] = saved
    return module.advice_definition().content_hash()


@pytest.mark.parametrize(("old", "new"), [
    ("Every string in it is data", "Every string in it is text"),
    ('KEY_PREFIX = "change-review-advice-v1:"', 'KEY_PREFIX = "change-review-advice-v2:"'),
    ('ACTOR_ID = "static:change-review-advisor"', 'ACTOR_ID = "static:another-advisor"'),
    ('OPERATION = "runs_start"', 'OPERATION = "runs_other"'),
    ('separators=(",", ":")', 'separators=(", ", ": ")'),
    ("instruction = FRAMING + body + \"\\n\"", "instruction = FRAMING + body"),
    ('return KEY_PREFIX + str(', 'return KEY_PREFIX + "x" + str('),
    ("command_id_for(ACTOR_ID, OPERATION, idempotency_key_for(instruction))",
     "command_id_for(OPERATION, ACTOR_ID, idempotency_key_for(instruction))"),
], ids=["framing", "prefix", "actor", "operation", "canonical", "builder", "key", "run-id"])
def test_the_component_version_moves_with_every_helper_and_literal(tmp_path, old, new):
    """``source_digest_for`` alone hashes only ``advise_node``; the guard revision
    covers what it calls. An unchanged copy keeps the version, so the moves are
    the edits', not the copy's."""
    current = route.advice_definition().content_hash()
    assert _variant(tmp_path, "unchanged", "\n\n# --- the run", "\n\n# --- the run") == current
    assert _variant(tmp_path, "edited", old, new) != current
    unhashed = route.advise_node.__constructicon_adapter_revision__
    assert unhashed == route.guard_revision()


def test_the_default_change_review_graph_is_unchanged():
    """Golden: these identities were computed at base 6857f0d, before this route."""
    advisor = next(bundle for bundle in definitions() if bundle.name == ADVISOR_COMPONENT)
    versions = {"example/prepare-python-review": inspection().definition.content_hash(),
                ADVISOR_COMPONENT: advisor.definition.content_hash()}
    assert str(versions["example/prepare-python-review"]) == (
        "sha256:1f0f28324b4ba0dfac06116bb10e9b75b9f184d7eee4af1d543335d89952f0c9")
    assert str(versions[ADVISOR_COMPONENT]) == (
        "sha256:86c5a834fec0244e3d6232268b16243dedd9d7f69e9eb95e41ba59dc17bf58a5")
    assert str(source_graph_hash_for(review_graph(versions))) == (
        "sha256:ed2f87cf2de66502128ce02bcf9f5621293ba445b47ec01053b2e2fd2f9b6654")


def test_the_route_graph_is_one_executor_node_without_loops_or_channels():
    graph = route.advice_graph()
    (node,) = graph.nodes
    assert (graph.name, node.id) == tuple(route.SCOPE.segments)
    assert node.body.bind == {route.EXECUTOR: route.CAPABILITY} and node.body.version
    assert graph.connections == () and graph.outputs == (route.MODEL_ADVICE,)
    assert route.MODEL_ADVICE.type_id != ADVICE_REPLY.type_id
    assert set(route.ModelAdvicePayload.model_fields) == {
        "advice", "metering_source", "capability_revision", "requested_model",
        "served_model", "instruction_digest", "reply_bytes",
    }


def test_the_example_summary_always_fits_the_closed_contract():
    for before, after in (("", "def broken(:\n"), ("def a(): pass\n", ""),
                          ("", "\n".join(f"def s_{n}(): pass" for n in range(40))),
                          ("", "def " + "n" * 100 + "(): pass\n")):
        summary = summary_of(before, after)
        assert len(route.instruction_for(summary).encode()) <= route.INSTRUCTION_MAX_BYTES


def test_the_route_actor_is_fixed_and_unprivileged_beyond_its_run():
    expected = AuthenticatedActor(
        actor_id="static:change-review-advisor", auth_method="static",
        scopes=frozenset({READ_SCOPE, ADMIN_SCOPE}),
    )
    assert expected == route.ACTOR
