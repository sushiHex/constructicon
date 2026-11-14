"""The walker seals a guard's refusal codes beside its message, and invents none."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from contextlib import closing
from typing import Any

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.errors import ContractViolation
from constructicon.core.graph import Graph, GraphNode, Ref
from constructicon.core.identity import canonical_json
from constructicon.core.refusal import MAX_REFUSAL_CODES, RefusalCode
from constructicon.core.run import RunStatus
from constructicon.runtime.context import NodeContext
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import BRIEF, ISSUE, atomic

INPUTS = {"issue": {"title": "refuse"}}
MESSAGE = "maintenance writer did not positively succeed"
RAISED: list[BaseException] = []


async def refusing_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    raise RAISED[0]


async def _fail_one_run(system: Constructicon, error: BaseException, name: str) -> RunId:
    RAISED[:] = [error]
    definition, implementation = atomic(f"test/{name}", (ISSUE,), (BRIEF,), refusing_impl)
    version = system._register(definition, implementation)
    system._promote_initial(component=definition.name, version=version)
    graph = Graph(name=name, nodes=(GraphNode(id="node", body=Ref(component=f"test/{name}")),),
                  connections=(), inputs=(ISSUE,), outputs=(BRIEF,))
    manifest = system.validate(graph, INPUTS)
    run_id = RunId(f"run-{name}")
    system._prepare_run(manifest, run_id=run_id, inputs=INPUTS)
    result = await system._run_prepared(run_id, cancellation="abandon")
    assert result.status is RunStatus.FAILED
    return run_id


def _stored_failure(journal: SqliteJournal, run_id: RunId) -> str:
    """The sealed bytes themselves, not a reparsed copy."""
    with closing(sqlite3.connect(journal._db_path)) as connection:
        rows = connection.execute(
            "SELECT payload FROM events WHERE run_id = ? AND kind = 'NodeFailed'", (run_id,),
        ).fetchall()
    assert len(rows) == 1
    return rows[0][0]


async def test_an_uncoded_failure_is_sealed_byte_for_byte_as_before(
    system: Constructicon, journal: SqliteJournal,
) -> None:
    run_id = await _fail_one_run(system, ContractViolation(MESSAGE), "uncoded")
    assert _stored_failure(journal, run_id) == canonical_json(
        {"error": MESSAGE, "error_type": "ContractViolation"})


async def test_a_coded_failure_is_sealed_and_read_back_in_its_order(
    system: Constructicon, journal: SqliteJournal,
) -> None:
    codes = (RefusalCode.WRITER_NOT_POSITIVE, RefusalCode.CAPTURE_UNCHANGED)
    run_id = await _fail_one_run(system, ContractViolation(MESSAGE, refusal=codes), "coded")
    expected = {"error": MESSAGE, "error_type": "ContractViolation",
                "refusal": ["writer.not_positive", "capture.unchanged"]}
    assert _stored_failure(journal, run_id) == canonical_json(expected)
    failure, = (event for event in journal.events(run_id, limit=100)
                if event.kind == "NodeFailed")
    assert failure.payload == expected
    assert [RefusalCode(code) for code in failure.payload["refusal"]] == list(codes)


@pytest.mark.parametrize("error", [
    ValueError(MESSAGE),
    BaseExceptionGroup("grouped", [ContractViolation(MESSAGE, refusal=(
        RefusalCode.CAPTURE_UNCHANGED,))]),
    RuntimeError("wrapped"),
], ids=["foreign", "group", "wrapping"])
async def test_nothing_is_mined_from_any_other_exception(
    system: Constructicon, journal: SqliteJournal, error: BaseException,
) -> None:
    if isinstance(error, RuntimeError):
        error.__cause__ = ContractViolation(MESSAGE, refusal=(RefusalCode.CAPTURE_UNCHANGED,))
    run_id = await _fail_one_run(system, error, "mined-" + type(error).__name__.lower())
    assert "refusal" not in _stored_failure(journal, run_id)


@pytest.mark.parametrize("refusal", [
    ("capture.unchanged",), (RefusalCode.CAPTURE_UNCHANGED,) * (MAX_REFUSAL_CODES + 1),
], ids=["not-a-member", "over-bound"])
def test_a_code_is_a_member_and_the_list_is_bounded(refusal) -> None:
    with pytest.raises(TypeError, match="at most twelve RefusalCode members"):
        ContractViolation(MESSAGE, refusal=refusal)
    at_bound = ContractViolation(MESSAGE, refusal=(RefusalCode.GATE_SUBJECT,) * MAX_REFUSAL_CODES)
    assert len(at_bound.refusal) == MAX_REFUSAL_CODES and str(at_bound) == MESSAGE
    assert ContractViolation(MESSAGE).refusal == ()
    # Checked once and read-only after: nothing unchecked can reach the seal.
    with pytest.raises(AttributeError):
        at_bound.refusal = ("not-a-member",) * (MAX_REFUSAL_CODES + 1)  # type: ignore[misc]
