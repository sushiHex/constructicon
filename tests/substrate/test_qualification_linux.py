"""The qualification entry on the provisioned Linux lane (M8 N5 Stage 1).

Everything physical is real: the launcher, the credential-free operator store,
the flock guard, the closure authority, a process that dies holding them, and
the production reader of a root-written authorization. The provider stays
unavailable throughout and no handle ever dispatches.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from constructicon.api.qualification import qualify
from constructicon.core.errors import ContractViolation
from constructicon.core.run import RunStatus
from constructicon.substrate.executors.codex import UNQUALIFIED_PREREQUISITES
from constructicon.substrate.executors.qualification import read_authorization
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.substrate._qualification_twin import DEATH, assemble
from tests.substrate.test_codex_adapter import GRANTS

TWIN = Path(__file__).with_name("_qualification_twin.py")


@pytest.fixture
def authorizations() -> Path:
    location = os.environ.get("M8_QUALIFICATION_AUTHORIZATIONS")
    if not location or sys.platform != "linux":
        if os.environ.get("M8_QUALIFICATION_REQUIRED"):
            pytest.fail("required Stage 1 qualification twin is unprovisioned")
        pytest.skip("the qualification twin requires the provisioned Linux lane")
    return Path(location)


def rows(granted) -> list[tuple[int, str, str | None]]:
    return [
        (row.acquisition_epoch, row.state, row.disposition)
        for row in SqliteJournal(granted.journal).capability_leases(granted.run_id)
    ]


async def test_the_authorized_run_takes_the_real_guard_and_store_and_never_dispatches(
    authorizations,
):
    granted = read_authorization(authorizations / "accepted.json")
    qualified = assemble(granted)

    status = await qualify_once(qualified)

    assert status is RunStatus.SUCCEEDED
    assert qualified.unavailable_reasons == UNQUALIFIED_PREREQUISITES
    (handle,) = qualified.handles
    assert handle.entered and handle.dispatch is False and not handle.executed
    assert handle.paths.guard.is_file() and handle.paths.guard.stat().st_uid == os.getuid()
    assert rows(granted) == [(1, "closed", "released")]


async def test_a_successor_recovers_from_real_process_death_within_the_budget(
    authorizations,
):
    """The owner dies by _exit holding the flock guard and the store lock; the
    successor reconciles epoch 1 after physical quiescence, and epoch 2 is beyond
    the one authorized acquisition, so nothing more is minted."""
    path = authorizations / "recovered.json"
    granted = read_authorization(path)
    owner = subprocess.run(
        [sys.executable, str(TWIN), "die", str(path)],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
    )
    assert owner.returncode == DEATH, owner.stderr[-2000:]
    assert '"materialized"' in owner.stdout
    assert rows(granted) == [(1, "active", None)]

    successor = assemble(granted)
    status = await qualify_once(successor, timeout_s=120)

    assert status is RunStatus.FAILED
    assert rows(granted) == [(1, "closed", "discarded")]
    assert successor.handles == []


@pytest.mark.parametrize(
    "variant",
    ["runtime-owned.json", "world-readable.json", "../qualification-writable/accepted.json"],
    ids=["owner", "mode", "parent"],
)
def test_the_reader_refuses_each_file_the_owner_did_not_seal(authorizations, variant):
    """Root prepared one variant per check (CI), each otherwise identical, so
    every refusal is that check's alone."""
    path = (authorizations / variant).resolve()
    assert path.is_file()
    with pytest.raises(ContractViolation, match="unavailable"):
        read_authorization(path)


def test_the_reader_follows_no_symlink(authorizations, tmp_path):
    link = tmp_path / "link.json"
    link.symlink_to(authorizations / "accepted.json")
    with pytest.raises(ContractViolation, match="unavailable"):
        read_authorization(link)


async def qualify_once(provider, *, timeout_s: float = 60) -> RunStatus:
    return await qualify(provider=provider, grants=GRANTS, timeout_s=timeout_s)
