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


async def test_a_successor_reconciles_real_process_death_and_mints_nothing_beyond_the_budget(
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




# Root prepares one unsealed variant per reader check in CI, each otherwise a
# byte-identical copy of the accepted authorization, so each refusal is that
# check's alone; the accepted file itself is the positive control.
VARIANTS = {
    "owner": "qualification/runtime-owned.json",
    "mode": "qualification/world-readable.json",
    "links": "qualification/hardlinked.json",
    "size": "qualification/oversized.json",
    "leaf-symlink": "qualification/linked.json",
    "ancestor-owner": "qualification-writable/accepted.json",
    "ancestor-mode": "qualification-open/accepted.json",
    "ancestor-symlink": "qualification-alias/accepted.json",
}


def test_the_reader_accepts_the_sealed_authorization(authorizations):
    granted = read_authorization(authorizations / "accepted.json")
    assert granted.authorization_id == "ci-twin-accepted"


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_the_reader_refuses_each_file_the_owner_did_not_seal(authorizations, variant):
    path = authorizations.parent / VARIANTS[variant]
    assert os.path.lexists(path)
    with pytest.raises(ContractViolation, match="unavailable"):
        read_authorization(path)


async def qualify_once(provider, *, timeout_s: float = 60) -> RunStatus:
    return await qualify(provider=provider, grants=GRANTS, timeout_s=timeout_s)
