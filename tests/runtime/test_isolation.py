"""Isolation is admission logic, never best effort (I1, ADR 0008): postures
the world cannot mechanically carry are refused before anything runs."""

from __future__ import annotations

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.errors import AdmissionError
from constructicon.core.grants import (
    EffectiveGrants,
    ModelSelection,
    Posture,
)
from constructicon.core.graph import Graph, GraphNode, Ref
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.substrate.executors.fake import FakeExecutor
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import BRIEF, ISSUE, TRIAGE_SCRIPT, atomic, triage_impl

INPUTS = {"issue": {"title": "posture check"}}

WRITE_ROOT = EffectiveGrants(
    posture=Posture.WRITE,
    model_selection=ModelSelection(kind="backend_default"),
    effort=None,
    allowed_tools=(),
    env_allowlist=(),
    network="none",
    timeout_s=600,
)


def lone_graph(bind: dict[str, str]) -> Graph:
    return Graph(
        name="lone",
        nodes=(GraphNode(id="triage", body=Ref(component="test/triage", bind=bind)),),
        inputs=(ISSUE,),
        outputs=(BRIEF,),
    )


def make_system(journal: SqliteJournal, **kwargs: object) -> Constructicon:
    executor = FakeExecutor(dict(TRIAGE_SCRIPT))
    system = Constructicon(
        journal=journal,
        capabilities={"fake-executor": executor},
        catalog={
            "fake-executor": CapabilityDescriptor(
                capability_id="fake-executor",
                kind="executor",
                revision="1",
                executor_profile=executor.profile,
            ),
            "write-workspace": CapabilityDescriptor(
                capability_id="write-workspace",
                kind="workspace",
                revision="1",
                leased=True,
                requires_posture=Posture.WRITE,
            ),
        },
        owner_id="worker-one",
        **kwargs,  # type: ignore[arg-type]
    )
    definition, impl = atomic("test/triage", (ISSUE,), (BRIEF,), triage_impl)
    version = system._register(definition, impl)
    system._promote_initial(component="test/triage", version=version)
    return system


def test_write_posture_needs_an_executor_that_can_enforce_it(
    journal: SqliteJournal,
) -> None:
    """The fake executor offers READ only: WRITE-postured admission refuses
    the world rather than degrading (the M3/M8 failure-table row)."""
    system = make_system(journal, root_grants=WRITE_ROOT)
    with pytest.raises(AdmissionError, match=r"does not offer posture 'write'"):
        system.validate(lone_graph({"executor": "fake-executor"}), INPUTS)


def test_write_workspace_under_read_grants_is_refused(
    journal: SqliteJournal,
) -> None:
    """A WRITE-requiring capability bound under READ grants is an admission
    fault — the workspace analog of the executor posture check."""
    system = make_system(journal)  # default root grants: READ
    with pytest.raises(
        AdmissionError, match="requires WRITE posture; node grants are 'read'"
    ):
        system.validate(lone_graph({"workspace": "write-workspace"}), INPUTS)
