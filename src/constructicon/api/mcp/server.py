"""High-level MCP v2 adapter over the transport-neutral M6 ``ControlPlane``.

Handlers derive one actor, delegate exactly once, and return the domain result.
They do not open SQLite, interpret cursors, calculate identities, or reconcile
mutations.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import quote

from mcp.server import MCPServer
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings

from constructicon import __version__
from constructicon.api.control import ControlPlane
from constructicon.core.address import RunId
from constructicon.core.admission import AdmissionAccepted, AdmissionRejected
from constructicon.core.control import (
    ActorSource,
    ApprovalCommandResult,
    AuthenticatedActor,
    CancellationResult,
    CommandSummary,
    ComponentComparison,
    ControlRejected,
    DetailChunk,
    DetailRef,
    EventPage,
    NamePage,
    PromotionCommandResult,
    RunPage,
    RunResultPreview,
    RunSubmission,
    RunSummary,
    VersionPage,
)
from constructicon.core.effect import ProofSubject
from constructicon.core.identity import Digest, JsonValue
from constructicon.core.introspection import SystemDescription
from constructicon.core.run import RunStatus

MCP_SERVER_NAME = "constructicon"
MCP_SERVER_VERSION = __version__


def create_mcp_server(
    control: ControlPlane,
    actor_source: ActorSource,
    *,
    token_verifier: TokenVerifier | None = None,
    auth: AuthSettings | None = None,
) -> MCPServer[None]:
    """Build one MCP server without adding any control-plane semantics."""

    if (token_verifier is None) != (auth is None):
        raise ValueError("token_verifier and auth must be supplied together")

    @asynccontextmanager
    async def lifespan(server: MCPServer[None]) -> AsyncIterator[None]:
        del server
        await control.startup()
        try:
            yield None
        finally:
            await control.shutdown()

    server = MCPServer[None](
        MCP_SERVER_NAME,
        version=MCP_SERVER_VERSION,
        instructions=(
            "Constructicon's durable control plane. Inspect system_describe before "
            "authoring a Graph. Every mutation requires a caller idempotency key."
        ),
        lifespan=lifespan,
        token_verifier=token_verifier,
        auth=auth,
    )

    async def actor() -> AuthenticatedActor:
        return await actor_source.actor()

    @server.tool(description="Return the authenticated Constructicon actor and scopes.")
    async def whoami() -> AuthenticatedActor:
        return control.whoami(await actor())

    @server.tool(description="Return the bounded M5 Graph authoring and capability contract.")
    async def system_describe(
        component_names: list[str] | None = None,
        limit: int = 100,
    ) -> SystemDescription | ControlRejected:
        return control.system_describe(await actor(), component_names=component_names, limit=limit)

    @server.tool(
        description=(
            "Strictly parse and admit Graph JSON. Invalid proposals return M5 "
            "machine-repairable faults rather than protocol errors."
        )
    )
    async def graphs_validate(
        proposal: dict[str, JsonValue],
        inputs: dict[str, JsonValue],
    ) -> AdmissionAccepted | AdmissionRejected | ControlRejected:
        return control.graphs_validate(await actor(), proposal, inputs)

    @server.tool(description="List a stable snapshot page of durable runs.")
    async def runs_list(
        statuses: list[RunStatus] | None = None,
        cursor: str | None = None,
        limit: int = 25,
    ) -> RunPage | ControlRejected:
        normalized = tuple(statuses) if statuses is not None else None
        return control.runs_list(await actor(), statuses=normalized, cursor=cursor, limit=limit)

    @server.tool(description="Read one durable run's status and liveness.")
    async def runs_status(run_id: str) -> RunSummary | ControlRejected:
        return control.runs_status(await actor(), RunId(run_id))

    @server.tool(description="Read one stable snapshot page of journal events.")
    async def runs_events(
        run_id: str,
        cursor: str | None = None,
        limit: int = 25,
    ) -> EventPage | ControlRejected:
        return control.runs_events(await actor(), RunId(run_id), cursor=cursor, limit=limit)

    @server.tool(description="Read one bounded run-result preview plus full-detail reference.")
    async def runs_result(run_id: str) -> RunResultPreview | ControlRejected:
        return control.runs_result(await actor(), RunId(run_id))

    @server.tool(description="Read one durable command and its stored result.")
    async def commands_status(command_id: str) -> CommandSummary | ControlRejected:
        return control.commands_status(await actor(), command_id)

    @server.tool(description="Page retained versions of one component.")
    async def registry_versions(
        component: str,
        cursor: str | None = None,
        limit: int = 25,
    ) -> VersionPage | ControlRejected:
        return control.registry_versions(await actor(), component, cursor=cursor, limit=limit)

    @server.tool(description="Page unpromoted retained versions of one component.")
    async def registry_candidates(
        component: str,
        cursor: str | None = None,
        limit: int = 25,
    ) -> VersionPage | ControlRejected:
        return control.registry_candidates(await actor(), component, cursor=cursor, limit=limit)

    @server.tool(description="Page the reverse-dependency closure for one component.")
    async def registry_rdeps(
        component: str,
        cursor: str | None = None,
        limit: int = 25,
    ) -> NamePage | ControlRejected:
        return control.registry_rdeps(await actor(), component, cursor=cursor, limit=limit)

    @server.tool(description="Compare two exact retained component versions and their impact.")
    async def registry_compare(
        component: str,
        left: Digest,
        right: Digest,
    ) -> ComponentComparison | ControlRejected:
        return control.registry_compare(await actor(), component, left, right)

    @server.tool(description="Read one bounded chunk of an immutable detail reference.")
    async def details_read(
        reference: DetailRef,
        cursor: str | None = None,
        max_bytes: int = 16_000,
    ) -> DetailChunk | ControlRejected:
        return control.details_read(await actor(), reference, cursor=cursor, max_bytes=max_bytes)

    @server.tool(description="Submit a durable run and return its RunId immediately.")
    async def runs_start(
        proposal: dict[str, JsonValue],
        inputs: dict[str, JsonValue],
        idempotency_key: str,
    ) -> RunSubmission | AdmissionRejected | ControlRejected:
        return await control.runs_start(
            await actor(),
            proposal=proposal,
            inputs=inputs,
            idempotency_key=idempotency_key,
        )

    @server.tool(description="Record durable cancellation intent for a run.")
    async def runs_cancel(
        run_id: str,
        idempotency_key: str,
    ) -> CancellationResult | ControlRejected:
        return await control.runs_cancel(
            await actor(), run_id=RunId(run_id), idempotency_key=idempotency_key
        )

    @server.tool(description="Resume one failed, parked, pending, or lost run.")
    async def runs_resume(
        run_id: str,
        idempotency_key: str,
    ) -> RunSubmission | ControlRejected:
        return await control.runs_resume(
            await actor(), run_id=RunId(run_id), idempotency_key=idempotency_key
        )

    @server.tool(description="Create a new run under a source run's exact manifest and inputs.")
    async def runs_reproduce(
        source_run_id: str,
        idempotency_key: str,
    ) -> RunSubmission | ControlRejected:
        return await control.runs_reproduce(
            await actor(),
            source_run_id=RunId(source_run_id),
            idempotency_key=idempotency_key,
        )

    @server.tool(
        description=(
            "Replay a source world with exact contract-compatible component overrides, "
            "simulated effects, and discard-only mutable capabilities."
        )
    )
    async def runs_counterfactual(
        source_run_id: str,
        overrides: dict[str, Digest],
        idempotency_key: str,
    ) -> RunSubmission | ControlRejected:
        return await control.runs_counterfactual(
            await actor(),
            source_run_id=RunId(source_run_id),
            overrides=overrides,
            idempotency_key=idempotency_key,
        )

    @server.tool(description="Record an authenticated human approval or rejection.")
    async def runs_approve(
        run_id: str,
        subject: ProofSubject,
        decision: Literal["approved", "rejected"],
        idempotency_key: str,
        reason: str | None = None,
    ) -> ApprovalCommandResult | ControlRejected:
        return await control.runs_approve(
            await actor(),
            run_id=RunId(run_id),
            subject=subject,
            decision=decision,
            reason=reason,
            idempotency_key=idempotency_key,
        )

    @server.tool(description="Promote one exact component version under a journal attestation.")
    async def registry_promote(
        component: str,
        version: Digest,
        attestation_id: str,
        idempotency_key: str,
    ) -> PromotionCommandResult | ControlRejected:
        return await control.registry_promote(
            await actor(),
            component=component,
            version=version,
            attestation_id=attestation_id,
            idempotency_key=idempotency_key,
        )

    @server.tool(description="Move stable to the prior retained target using compare-and-swap.")
    async def registry_rollback(
        component: str,
        expected_stable: Digest,
        idempotency_key: str,
    ) -> PromotionCommandResult | ControlRejected:
        return await control.registry_rollback(
            await actor(),
            component=component,
            expected_stable=expected_stable,
            idempotency_key=idempotency_key,
        )

    _register_detail_resources(server, control, actor_source)
    return server


def _register_detail_resources(
    server: MCPServer[None],
    control: ControlPlane,
    actor_source: ActorSource,
) -> None:
    async def chunk(uri: str) -> str:
        result = control.resource_read(await actor_source.actor(), uri, max_bytes=64_000)
        return result.model_dump_json()

    @server.resource(
        "constructicon://runs/{run_id}/manifest",
        name="run-manifest",
        description="Bounded immutable manifest detail. Continue with details_read if needed.",
        mime_type="application/json",
    )
    async def run_manifest(run_id: str) -> str:
        return await chunk(f"constructicon://runs/{run_id}/manifest")

    @server.resource(
        "constructicon://runs/{run_id}/result",
        name="run-result",
        description="Bounded immutable run result detail.",
        mime_type="application/json",
    )
    async def run_result(run_id: str) -> str:
        return await chunk(f"constructicon://runs/{run_id}/result")

    @server.resource(
        "constructicon://runs/{run_id}/events/{seq}",
        name="run-event",
        description="One immutable journal event.",
        mime_type="application/json",
    )
    async def run_event(run_id: str, seq: str) -> str:
        return await chunk(f"constructicon://runs/{run_id}/events/{seq}")

    @server.resource(
        "constructicon://commands/{command_id}",
        name="control-command",
        description="One durable command, plan, and terminal response.",
        mime_type="application/json",
    )
    async def command(command_id: str) -> str:
        return await chunk(f"constructicon://commands/{command_id}")

    @server.resource(
        "constructicon://approvals/{approval_id}",
        name="approval",
        description="One authenticated approval record.",
        mime_type="application/json",
    )
    async def approval(approval_id: str) -> str:
        return await chunk(f"constructicon://approvals/{approval_id}")

    @server.resource(
        "constructicon://attestations/{attestation_id}",
        name="attestation",
        description="One journal-minted deterministic attestation.",
        mime_type="application/json",
    )
    async def attestation(attestation_id: str) -> str:
        return await chunk(f"constructicon://attestations/{attestation_id}")

    @server.resource(
        "constructicon://components/{component}/{version}",
        name="component-version",
        description="One immutable retained component definition.",
        mime_type="application/json",
    )
    async def component_version(component: str, version: str) -> str:
        return await chunk(
            f"constructicon://components/{quote(component, safe='')}/{quote(version, safe='')}"
        )
