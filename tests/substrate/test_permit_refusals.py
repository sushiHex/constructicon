"""Providers carry the actual shared permit checks; grant-only refusals invent none."""

from dataclasses import replace

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.permit import PermitFault
from constructicon.core.refusal import RefusalCode
from tests.core.test_run_permit_goldens import MAINTENANCE, QUALIFICATION, wrong
from tests.substrate import test_claude_provider as claude
from tests.substrate import test_codex_maintenance_authorization as maintenance
from tests.substrate import test_codex_qualification as qualification
from tests.substrate.test_claude_provider import assembled as assembled
from tests.substrate.test_claude_provider import provider as provider
from tests.substrate.test_codex_adapter import portable_binding as portable_binding


def wrong_context(context, authorization):
    fields = wrong(authorization)
    return replace(
        context,
        run_lease=context.run_lease.model_copy(update={
            "run_id": fields["run_id"], "epoch": fields["epoch"],
        }),
        path=fields["path"], source_graph_hash=fields["source_graph_hash"],
        binding=context.binding.model_copy(update={
            "binding": fields["binding"], "capability_id": fields["capability_id"],
            "revision": fields["revision"], "effective_grants": fields["grants"],
        }),
    )


@pytest.mark.parametrize("kind", ["qualification", "maintenance"])
async def test_codex_acquisition_records_every_actual_permit_fault_once(
    tmp_path, portable_binding, monkeypatch, kind,
):
    if kind == "qualification":
        executor, authorization = qualification.qualifying(tmp_path, portable_binding)
        context = qualification.context(authorization)
        sentences = (*QUALIFICATION[:7], *QUALIFICATION[8:])  # no-dispatch pins no grants
    else:
        executor, authorization = maintenance.authorized(tmp_path, portable_binding)
        context = maintenance.context(authorization)
        sentences = MAINTENANCE
    fields = wrong(authorization)
    authorization = authorization.model_copy(update={
        "operator_binding_digest": fields["operator_binding_digest"],
        "not_after": authorization.not_after.replace(year=2000),
    })
    setattr(executor, kind, authorization)
    invocation = wrong_context(context, authorization)
    from constructicon.substrate.executors import codex

    called = []
    original = codex.permit_faults

    def measured(*args, **kwargs):
        called.append(kwargs["now"])
        return original(*args, **kwargs)

    monkeypatch.setattr(codex, "permit_faults", measured)
    with pytest.raises(ContractViolation) as refused:
        await executor.acquire(invocation)
    expected = tuple(fault.refusal for fault in PermitFault
                     if kind == "maintenance" or fault is not PermitFault.GRANTS)
    assert refused.value.refusal == expected
    assert str(refused.value) == "; ".join(sentences)
    assert len(called) == 1 and executor.handles == []


@pytest.mark.parametrize("kind", ["permit-only", "grant-only", "both"])
async def test_claude_keeps_its_message_and_records_only_actual_permit_faults(
    assembled, monkeypatch, kind,
):
    a = assembled
    context = a.context
    if kind != "grant-only":
        context = replace(context, source_graph_hash=None)
    if kind != "permit-only":
        other = a.grants.model_copy(update={"effort": "unconfigured"})
        a.executor.qualification = a.executor.qualification.model_copy(update={"grants": other})
        context = replace(context, binding=context.binding.model_copy(update={
            "effective_grants": other,
        }))
    grant_checks = []
    original = a.executor._grant_faults

    def grant_faults(grants):
        grant_checks.append(grants)
        return original(grants)

    calls = []
    raw = claude.native.permit_faults

    def measured(*args, **kwargs):
        calls.append(kwargs["now"])
        return raw(*args, **kwargs)

    monkeypatch.setattr(a.executor, "_grant_faults", grant_faults)
    monkeypatch.setattr(claude.native, "permit_faults", measured)
    with pytest.raises(ContractViolation) as refused:
        # Unit-test this guard directly: a grant-only mismatch is normally
        # also prevented by assembly and the custody check preceding it.
        a.executor._check_context(context)
    assert str(refused.value) == "Claude READ qualification acquisition refused"
    assert refused.value.refusal == (
        () if kind == "grant-only" else (RefusalCode.PERMIT_SOURCE_GRAPH,)
    )
    assert len(calls) == len(grant_checks) == 1
    assert not a.state.probes and not a.state.exchanges and not a.state.workers


async def test_claude_acquisition_carries_the_context_guards_actual_permit_code(assembled):
    a = assembled
    with pytest.raises(ContractViolation) as refused:
        await a.executor.acquire(replace(a.context, source_graph_hash=None))
    assert str(refused.value) == "Claude READ qualification acquisition refused"
    assert refused.value.refusal == (RefusalCode.PERMIT_SOURCE_GRAPH,)
    assert not a.executor._handles and not a.state.probes and not a.state.exchanges
