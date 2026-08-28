"""Local assembly is keyed, static-admin-only, and absent from transports."""

from __future__ import annotations

from typing import Any

from constructicon.api.control import ControlPlane
from constructicon.core.control import (
    ADMIN_SCOPE,
    OPERATE_SCOPE,
    AuthenticatedActor,
    ControlCode,
    ControlRejected,
    PromotionCommandResult,
    RegistrationCommandResult,
)
from constructicon.core.identity import Digest
from constructicon.runtime.registry import ComponentRegistry
from constructicon.sdk.types import DefinitionBundle
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import ISSUE, REVIEW, atomic, review_impl


def _actor(*, method: str, admin: bool) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id=f"{method}:assembly-{'admin' if admin else 'operator'}",
        auth_method=method,  # type: ignore[arg-type]
        scopes=frozenset({ADMIN_SCOPE} if admin else {OPERATE_SCOPE}),
    )


async def test_local_auth_precedence_creates_no_command_or_registry_fact(
    world: Any,
    journal: SqliteJournal,
) -> None:
    definition, implementation = atomic(
        "assembly/review",
        (ISSUE,),
        (REVIEW,),
        review_impl,
    )
    bundle = DefinitionBundle(definition, implementation)
    control = ControlPlane(system=world, store=journal)
    for actor, expected in (
        (_actor(method="oauth", admin=True), ControlCode.AUTH_LOCAL_STATIC_REQUIRED),
        (_actor(method="oauth", admin=False), ControlCode.AUTH_LOCAL_STATIC_REQUIRED),
        (_actor(method="static", admin=False), ControlCode.AUTH_REQUIRED_SCOPE),
    ):
        for operation in ("registry_register", "registry_promote_initial"):
            if operation == "registry_register":
                rejected = await control.registry_register(
                    actor,
                    definition=bundle,
                    idempotency_key=f"denied-register-{actor.actor_id}",
                )
            else:
                rejected = await control.registry_promote_initial(
                    actor,
                    component=definition.name,
                    version=Digest("sha256:" + "0" * 64),
                    idempotency_key=f"denied-initial-{actor.actor_id}",
                )
            assert isinstance(rejected, ControlRejected)
            assert rejected.faults[0].code is expected
    assert journal.latest_command_key(operation="registry_register") is None
    assert journal.latest_command_key(operation="registry_promote_initial") is None
    assert world._registry.snapshot().get(definition.name, definition.content_hash()) is None
    await control.shutdown()


async def test_keyed_registration_and_bootstrap_replay_exactly_without_cache_authority(
    world: Any,
    journal: SqliteJournal,
) -> None:
    definition, implementation = atomic(
        "assembly/review",
        (ISSUE,),
        (REVIEW,),
        review_impl,
    )
    actor = _actor(method="static", admin=True)
    control = ControlPlane(system=world, store=journal)
    registered = await control.registry_register(
        actor,
        definition=DefinitionBundle(definition, implementation),
        idempotency_key="register-review",
    )
    assert isinstance(registered, RegistrationCommandResult)
    assert (definition.name, str(registered.version)) not in world._registry._impls
    replay = await control.registry_register(
        actor,
        definition=definition,
        idempotency_key="register-review",
    )
    assert isinstance(replay, RegistrationCommandResult)
    assert replay.command.replayed is True

    cold = ComponentRegistry(store=journal)
    stored = cold.snapshot().get(definition.name, registered.version)
    assert stored is not None
    assert cold.bind(stored).loadability.status == "loadable"

    promoted = await control.registry_promote_initial(
        actor,
        component=definition.name,
        version=registered.version,
        idempotency_key="promote-review",
    )
    assert isinstance(promoted, PromotionCommandResult)
    assert promoted.from_version is None
    assert promoted.to_version == registered.version
    promoted_replay = await control.registry_promote_initial(
        actor,
        component=definition.name,
        version=registered.version,
        idempotency_key="promote-review",
    )
    assert isinstance(promoted_replay, PromotionCommandResult)
    assert promoted_replay.command.replayed is True
    assert len(cold.snapshot().history[definition.name]) == 1
    await control.shutdown()
