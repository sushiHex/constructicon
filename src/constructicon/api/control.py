"""One public durable control-plane facade with two private collaborators."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from functools import wraps
from typing import Any, Concatenate, Literal, ParamSpec, TypeVar, cast

from constructicon.api._control_commands import (
    COMMAND_TTL_S,
    _CommandExecutor,
)
from constructicon.api._control_queries import DEFAULT_PAGE_SIZE, _ControlQueries
from constructicon.api.cursor import CursorCodec
from constructicon.api.detail import DetailResolver
from constructicon.api.run_host import RunHost
from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.admission import AdmissionAccepted, AdmissionRejected
from constructicon.core.component import ComponentDef
from constructicon.core.control import (
    ADMIN_SCOPE,
    APPROVE_SCOPE,
    OPERATE_SCOPE,
    PROMOTE_SCOPE,
    ApprovalCommandResult,
    AuthenticatedActor,
    CancellationResult,
    CommandSummary,
    ComponentComparison,
    ControlCode,
    ControlRejected,
    ControlStore,
    DetailChunk,
    DetailRef,
    EventPage,
    NamePage,
    PromotionCommandResult,
    RegistrationCommandResult,
    RunPage,
    RunResultPreview,
    RunSubmission,
    RunSummary,
    VersionPage,
)
from constructicon.core.effect import ProofSubject
from constructicon.core.graph import Graph
from constructicon.core.identity import Digest, JsonValue
from constructicon.core.introspection import SystemDescription
from constructicon.core.journal import Journal
from constructicon.core.registry import RegistryStore
from constructicon.core.run import RunStatus
from constructicon.runtime.registry import ComponentRegistry
from constructicon.sdk.types import DefinitionBundle

P = ParamSpec("P")
R = TypeVar("R")


class ControlPlaneClosed(RuntimeError):
    """A mutation arrived after durable control-plane closing began."""


def _facade_mutation(
    required_scope: str,
    *,
    local_static: bool = False,
) -> Callable[
    [Callable[Concatenate[ControlPlane, AuthenticatedActor, P], Awaitable[R]]],
    Callable[Concatenate[ControlPlane, AuthenticatedActor, P], Awaitable[R]],
]:
    def decorate(
        operation: Callable[
            Concatenate[ControlPlane, AuthenticatedActor, P],
            Awaitable[R],
        ],
    ) -> Callable[
        Concatenate[ControlPlane, AuthenticatedActor, P],
        Awaitable[R],
    ]:
        @wraps(operation)
        async def wrapped(
            control: ControlPlane,
            actor: AuthenticatedActor,
            *args: P.args,
            **kwargs: P.kwargs,
        ) -> R:
            await control._require_mutations_open()
            denied = (
                control._authorize_local_admin(actor)
                if local_static
                else control._authorize(actor, required_scope)
            )
            if denied is not None:
                return cast(R, denied)
            await control._admit_mutation()
            try:
                return await operation(control, actor, *args, **kwargs)
            finally:
                control._release_mutation()

        return cast(
            "Callable[Concatenate[ControlPlane, AuthenticatedActor, P], Awaitable[R]]",
            wrapped,
        )

    return decorate


class ControlPlane:
    """Transport-neutral authority and sole lifecycle owner."""

    def __init__(
        self,
        *,
        system: Constructicon,
        store: ControlStore,
        journal: Journal | None = None,
        registry: ComponentRegistry | None = None,
        run_host: RunHost | None = None,
        owner_id: str | None = None,
        command_ttl_s: float = COMMAND_TTL_S,
        cursor_codec: CursorCodec | None = None,
        fault_probe: Callable[[str], None] | None = None,
    ) -> None:
        journal_service = journal or cast(Journal, store)
        registry_service = registry or ComponentRegistry(store=cast(RegistryStore, store))
        cursor_service = cursor_codec or CursorCodec()
        host_service = run_host or RunHost(system, journal=journal_service)
        detail_service = DetailResolver(
            system=system,
            store=store,
            cursors=cursor_service,
            journal=journal_service,
            registry=registry_service,
        )
        self._commands = _CommandExecutor(
            system=system,
            store=store,
            journal=journal_service,
            registry=registry_service,
            run_host=host_service,
            owner_id=owner_id,
            command_ttl_s=command_ttl_s,
            cursor_codec=cursor_service,
            detail_resolver=detail_service,
            fault_probe=fault_probe,
        )
        self._queries = _ControlQueries(
            system=system,
            store=store,
            journal=journal_service,
            registry=registry_service,
            cursors=cursor_service,
            details=detail_service,
        )
        self._run_host = host_service
        self._lifecycle_lock = asyncio.Lock()
        self._lifecycle_state: Literal["new", "starting", "started", "stopping", "stopped"] = "new"
        self._startup_task: asyncio.Task[None] | None = None
        self._shutdown_task: asyncio.Task[None] | None = None
        self._active_mutations = 0
        self._mutations_idle = asyncio.Event()
        self._mutations_idle.set()

    async def startup(self) -> None:
        async with self._lifecycle_lock:
            if self._lifecycle_state == "started":
                return
            if self._lifecycle_state in {"stopping", "stopped"}:
                raise ControlPlaneClosed("ControlPlane is closing or stopped")
            task = self._startup_task
            if task is None:
                self._lifecycle_state = "starting"
                task = asyncio.create_task(
                    self._startup_once(),
                    name="constructicon:control-startup",
                )
                self._startup_task = task
        await asyncio.shield(task)

    async def shutdown(self) -> None:
        async with self._lifecycle_lock:
            if self._lifecycle_state == "stopped":
                return
            task = self._shutdown_task
            if task is None:
                self._lifecycle_state = "stopping"
                task = asyncio.create_task(
                    self._shutdown_once(),
                    name="constructicon:control-shutdown",
                )
                self._shutdown_task = task
        await asyncio.shield(task)

    async def _startup_once(self) -> None:
        try:
            await self._run_host.startup()
        except BaseException:
            await self._run_host.abort_startup()
            async with self._lifecycle_lock:
                if self._lifecycle_state != "stopping":
                    self._lifecycle_state = "new"
                    self._startup_task = None
            raise
        async with self._lifecycle_lock:
            if self._lifecycle_state == "starting":
                self._lifecycle_state = "started"

    async def _shutdown_once(self) -> None:
        startup = self._startup_task
        if startup is not None and not startup.done():
            with suppress(BaseException):
                await asyncio.shield(startup)
        await self._mutations_idle.wait()
        await self._run_host.shutdown()
        async with self._lifecycle_lock:
            self._lifecycle_state = "stopped"

    async def _admit_mutation(self) -> None:
        await self.startup()
        async with self._lifecycle_lock:
            if self._lifecycle_state != "started":
                raise ControlPlaneClosed("ControlPlane closed before command claim")
            self._active_mutations += 1
            self._mutations_idle.clear()

    def _release_mutation(self) -> None:
        # Deliberately synchronous: this runs in a ``finally`` that may execute
        # while the caller's task is already cancelled. Awaiting the lifecycle
        # lock there could raise before the decrement and strand
        # ``_mutations_idle``, hanging every later shutdown forever.
        if self._active_mutations <= 0:
            raise RuntimeError("ControlPlane mutation accounting underflow")
        self._active_mutations -= 1
        if self._active_mutations == 0:
            self._mutations_idle.set()

    async def _require_mutations_open(self) -> None:
        async with self._lifecycle_lock:
            if self._lifecycle_state in {"stopping", "stopped"}:
                raise ControlPlaneClosed("ControlPlane is closing or stopped")

    def _authorize(
        self,
        actor: AuthenticatedActor,
        required_scope: str,
    ) -> ControlRejected | None:
        if actor.allows(required_scope):
            return None
        return self._fault(
            ControlCode.AUTH_REQUIRED_SCOPE,
            f"actor {actor.actor_id!r} lacks required scope {required_scope!r}",
            f"authenticate with {required_scope} or constructicon:admin",
            {"required_scope": required_scope},
        )

    def _authorize_local_admin(
        self,
        actor: AuthenticatedActor,
    ) -> ControlRejected | None:
        if actor.auth_method != "static":
            return self._fault(
                ControlCode.AUTH_LOCAL_STATIC_REQUIRED,
                "local assembly commands require a launcher-minted static actor",
                "invoke this local-only method through trusted launcher assembly",
            )
        return self._authorize(actor, ADMIN_SCOPE)

    @staticmethod
    def _fault(
        code: ControlCode,
        message: str,
        repair: str,
        details: dict[str, JsonValue] | None = None,
    ) -> ControlRejected:
        return ControlRejected.one_fault(code, message, repair, details)

    def whoami(self, actor: AuthenticatedActor) -> AuthenticatedActor:
        return self._queries.whoami(actor)

    def system_describe(
        self,
        actor: AuthenticatedActor,
        *,
        component_names: Sequence[str] | None = None,
        limit: int = 100,
    ) -> SystemDescription | ControlRejected:
        return self._queries.system_describe(
            actor,
            component_names=component_names,
            limit=limit,
        )

    def graphs_validate(
        self,
        actor: AuthenticatedActor,
        proposal: Graph | Mapping[str, Any] | str,
        inputs: Mapping[str, Any],
    ) -> AdmissionAccepted | AdmissionRejected | ControlRejected:
        return self._queries.graphs_validate(actor, proposal, inputs)

    def runs_status(
        self,
        actor: AuthenticatedActor,
        run_id: RunId,
    ) -> RunSummary | ControlRejected:
        return self._queries.runs_status(actor, run_id)

    def runs_list(
        self,
        actor: AuthenticatedActor,
        *,
        statuses: tuple[RunStatus, ...] | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> RunPage | ControlRejected:
        return self._queries.runs_list(
            actor,
            statuses=statuses,
            cursor=cursor,
            limit=limit,
        )

    def runs_events(
        self,
        actor: AuthenticatedActor,
        run_id: RunId,
        *,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> EventPage | ControlRejected:
        return self._queries.runs_events(
            actor,
            run_id,
            cursor=cursor,
            limit=limit,
        )

    def runs_result(
        self,
        actor: AuthenticatedActor,
        run_id: RunId,
    ) -> RunResultPreview | ControlRejected:
        return self._queries.runs_result(actor, run_id)

    def commands_status(
        self,
        actor: AuthenticatedActor,
        command_id: str,
    ) -> CommandSummary | ControlRejected:
        return self._queries.commands_status(actor, command_id)

    def registry_versions(
        self,
        actor: AuthenticatedActor,
        component: str,
        *,
        candidates_only: bool = False,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> VersionPage | ControlRejected:
        return self._queries.registry_versions(
            actor,
            component,
            candidates_only=candidates_only,
            cursor=cursor,
            limit=limit,
        )

    def registry_candidates(
        self,
        actor: AuthenticatedActor,
        component: str,
        *,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> VersionPage | ControlRejected:
        return self._queries.registry_candidates(
            actor,
            component,
            cursor=cursor,
            limit=limit,
        )

    def registry_rdeps(
        self,
        actor: AuthenticatedActor,
        component: str,
        *,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> NamePage | ControlRejected:
        return self._queries.registry_rdeps(
            actor,
            component,
            cursor=cursor,
            limit=limit,
        )

    def registry_compare(
        self,
        actor: AuthenticatedActor,
        component: str,
        left: Digest,
        right: Digest,
    ) -> ComponentComparison | ControlRejected:
        return self._queries.registry_compare(
            actor,
            component,
            left,
            right,
        )

    def details_read(
        self,
        actor: AuthenticatedActor,
        reference: DetailRef,
        *,
        cursor: str | None = None,
        max_bytes: int = 16_000,
    ) -> DetailChunk | ControlRejected:
        return self._queries.details_read(
            actor,
            reference,
            cursor=cursor,
            max_bytes=max_bytes,
        )

    def resource_read(
        self,
        actor: AuthenticatedActor,
        uri: str,
        *,
        max_bytes: int = 64_000,
    ) -> DetailChunk | ControlRejected:
        return self._queries.resource_read(actor, uri, max_bytes=max_bytes)

    @_facade_mutation(OPERATE_SCOPE)
    async def runs_start(
        self,
        actor: AuthenticatedActor,
        *,
        proposal: Graph | Mapping[str, Any] | str,
        inputs: Mapping[str, Any],
        idempotency_key: str,
    ) -> RunSubmission | AdmissionRejected | ControlRejected:
        return await self._commands.runs_start(
            actor,
            proposal=proposal,
            inputs=inputs,
            idempotency_key=idempotency_key,
        )

    @_facade_mutation(OPERATE_SCOPE)
    async def runs_cancel(
        self,
        actor: AuthenticatedActor,
        *,
        run_id: RunId,
        idempotency_key: str,
    ) -> CancellationResult | ControlRejected:
        return await self._commands.runs_cancel(
            actor,
            run_id=run_id,
            idempotency_key=idempotency_key,
        )

    @_facade_mutation(OPERATE_SCOPE)
    async def runs_resume(
        self,
        actor: AuthenticatedActor,
        *,
        run_id: RunId,
        idempotency_key: str,
    ) -> RunSubmission | ControlRejected:
        return await self._commands.runs_resume(
            actor,
            run_id=run_id,
            idempotency_key=idempotency_key,
        )

    @_facade_mutation(OPERATE_SCOPE)
    async def runs_reproduce(
        self,
        actor: AuthenticatedActor,
        *,
        source_run_id: RunId,
        idempotency_key: str,
    ) -> RunSubmission | ControlRejected:
        return await self._commands.runs_reproduce(
            actor,
            source_run_id=source_run_id,
            idempotency_key=idempotency_key,
        )

    @_facade_mutation(OPERATE_SCOPE)
    async def runs_counterfactual(
        self,
        actor: AuthenticatedActor,
        *,
        source_run_id: RunId,
        overrides: Mapping[str, Digest],
        idempotency_key: str,
    ) -> RunSubmission | ControlRejected:
        return await self._commands.runs_counterfactual(
            actor,
            source_run_id=source_run_id,
            overrides=overrides,
            idempotency_key=idempotency_key,
        )

    @_facade_mutation(APPROVE_SCOPE)
    async def runs_approve(
        self,
        actor: AuthenticatedActor,
        *,
        run_id: RunId,
        subject: ProofSubject,
        decision: str,
        reason: str | None,
        idempotency_key: str,
    ) -> ApprovalCommandResult | ControlRejected:
        return await self._commands.runs_approve(
            actor,
            run_id=run_id,
            subject=subject,
            decision=decision,
            reason=reason,
            idempotency_key=idempotency_key,
        )

    @_facade_mutation(ADMIN_SCOPE, local_static=True)
    async def registry_register(
        self,
        actor: AuthenticatedActor,
        *,
        definition: ComponentDef | DefinitionBundle,
        idempotency_key: str,
    ) -> RegistrationCommandResult | ControlRejected:
        return await self._commands.registry_register(
            actor,
            definition=definition,
            idempotency_key=idempotency_key,
        )

    @_facade_mutation(ADMIN_SCOPE, local_static=True)
    async def registry_promote_initial(
        self,
        actor: AuthenticatedActor,
        *,
        component: str,
        version: Digest,
        idempotency_key: str,
    ) -> PromotionCommandResult | ControlRejected:
        return await self._commands.registry_promote_initial(
            actor,
            component=component,
            version=version,
            idempotency_key=idempotency_key,
        )

    @_facade_mutation(PROMOTE_SCOPE)
    async def registry_promote(
        self,
        actor: AuthenticatedActor,
        *,
        component: str,
        version: Digest,
        attestation_id: str,
        idempotency_key: str,
    ) -> PromotionCommandResult | ControlRejected:
        return await self._commands.registry_promote(
            actor,
            component=component,
            version=version,
            attestation_id=attestation_id,
            idempotency_key=idempotency_key,
        )

    @_facade_mutation(PROMOTE_SCOPE)
    async def registry_rollback(
        self,
        actor: AuthenticatedActor,
        *,
        component: str,
        expected_stable: Digest,
        idempotency_key: str,
    ) -> PromotionCommandResult | ControlRejected:
        return await self._commands.registry_rollback(
            actor,
            component=component,
            expected_stable=expected_stable,
            idempotency_key=idempotency_key,
        )


__all__ = ["ControlPlane", "ControlPlaneClosed"]
