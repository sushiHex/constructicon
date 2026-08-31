"""Throwaway repro: promote-only actor vs DetailResolver._family_lock."""

from __future__ import annotations

from typing import Any

from constructicon.api.control import ControlPlane
from constructicon.core.control import PROMOTE_SCOPE, AuthenticatedActor
from constructicon.substrate.journal.sqlite import SqliteJournal

from tests.api.test_control_v1_replay_upgrade import _candidate

PROMOTE_ONLY = AuthenticatedActor(
    actor_id="static:promoter",
    auth_method="static",
    scopes=frozenset({PROMOTE_SCOPE}),
)


async def test_promote_only_actor(world: Any, journal: SqliteJournal) -> None:
    component = "control/promote-only"
    candidate, attestation_id = _candidate(world, component)
    control = ControlPlane(system=world, store=journal)
    try:
        result = await control.registry_promote(
            PROMOTE_ONLY,
            component=component,
            version=candidate,
            attestation_id=attestation_id,
            idempotency_key="promote-only-1",
        )
        print("RESULT:", type(result), result)
    except Exception as exc:  # noqa: BLE001
        print("RAISED:", type(exc).__name__, exc)
        print("STABLE NOW:", control._commands._registry.stable_version(component))
    await control.shutdown()
