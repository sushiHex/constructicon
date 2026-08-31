"""Private authorization-aware bounded control-plane queries (M6.2)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypeGuard, cast

from pydantic import ValidationError

from constructicon.api.cursor import CursorCodec, CursorFault
from constructicon.api.detail import DetailAddress, DetailResolver, authorized_delivery
from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.admission import AdmissionAccepted, AdmissionRejected
from constructicon.core.channel import (
    ActorInboxRevision,
    ChannelDelivery,
    ChannelInteraction,
    InvalidChannelRevision,
)
from constructicon.core.control import (
    ADMIN_SCOPE,
    ADVISE_SCOPE,
    APPROVE_SCOPE,
    READ_SCOPE,
    AuthenticatedActor,
    ChannelMessagePage,
    ChannelMessageSummary,
    CommandSummary,
    ComponentComparison,
    ControlCode,
    ControlRejected,
    ControlStore,
    DetailChunk,
    DetailRef,
    EventPage,
    EventSummary,
    NamePage,
    PageInfo,
    RunPage,
    RunResultPreview,
    RunSummary,
    VersionPage,
    VersionSummary,
    channel_reach,
    scope_refusal,
)
from constructicon.core.graph import Graph
from constructicon.core.identity import Digest, JsonValue, canonical_json, digest, json_value
from constructicon.core.introspection import SystemDescription
from constructicon.core.journal import Journal
from constructicon.core.registry import (
    InvalidRegistryRevision,
    RegistryRevision,
    RegistrySnapshot,
    registry_snapshot_digest,
)
from constructicon.core.run import RunStatus
from constructicon.runtime.registry import ComponentRegistry

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


def _is_index(value: JsonValue) -> TypeGuard[int]:
    """A JSON number that is a real position: an int, not a bool, not negative."""

    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


class _ControlQueries:
    def __init__(
        self,
        *,
        system: Constructicon,
        store: ControlStore,
        journal: Journal,
        registry: ComponentRegistry,
        cursors: CursorCodec,
        details: DetailResolver,
    ) -> None:
        self._system = system
        self._store = store
        self._journal = journal
        self._registry = registry
        self._cursors = cursors
        self._details = details

    def whoami(self, actor: AuthenticatedActor) -> AuthenticatedActor:
        return actor

    def system_describe(
        self,
        actor: AuthenticatedActor,
        *,
        component_names: Sequence[str] | None = None,
        limit: int = 100,
    ) -> SystemDescription | ControlRejected:
        denied = self._authorize(actor)
        return denied or self._system.describe(
            component_names=component_names,
            limit=limit,
        )

    def graphs_validate(
        self,
        actor: AuthenticatedActor,
        proposal: Graph | Mapping[str, Any] | str,
        inputs: Mapping[str, Any],
    ) -> AdmissionAccepted | AdmissionRejected | ControlRejected:
        denied = self._authorize(actor)
        return denied or self._system.admit_graph(proposal, inputs)

    def runs_status(
        self,
        actor: AuthenticatedActor,
        run_id: RunId,
    ) -> RunSummary | ControlRejected:
        denied = self._authorize(actor)
        if denied:
            return denied
        record = self._journal.run_record(run_id)
        if record is None:
            return self._fault(
                ControlCode.RUN_UNKNOWN,
                f"unknown run {run_id!r}",
                "use a RunId returned by a Constructicon run mutation",
            )
        return self._run_summary(actor, record)

    def runs_list(
        self,
        actor: AuthenticatedActor,
        *,
        statuses: tuple[RunStatus, ...] | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> RunPage | ControlRejected:
        denied = self._authorize(actor)
        invalid = self._limit_fault(limit)
        if denied or invalid:
            return denied or cast(ControlRejected, invalid)
        query: JsonValue = {"statuses": [status.value for status in statuses] if statuses else None}
        after: tuple[str, str] | None = None
        if cursor is None:
            upper = self._journal.latest_run_key(statuses=statuses)
        else:
            decoded = self._decode_cursor(actor, cursor, kind="runs", query=query)
            if isinstance(decoded, ControlRejected):
                return decoded
            upper = self._pair(decoded.upper_bound)
            after = self._pair(decoded.last_key)
            current_max = self._journal.latest_run_key(statuses=None)
            if (
                upper is None
                or after is None
                or after > upper
                or current_max is None
                or upper > current_max
            ):
                return self._cursor_shape_fault()
        if upper is None:
            return RunPage(
                items=(),
                page=PageInfo(
                    next_cursor=None,
                    snapshot_digest=digest("run-page", 1, {"query": query, "upper": None}),
                    count=0,
                ),
            )
        records = self._journal.run_records(
            statuses=statuses,
            after=after,
            through=upper,
            limit=limit + 1,
        )
        visible = records[:limit]
        next_cursor = None
        if len(records) > limit and visible:
            last = visible[-1]
            next_cursor = self._cursors.encode(
                actor_id=actor.actor_id,
                kind="runs",
                query=query,
                upper_bound=list(upper),
                last_key=[last.created_at.isoformat(), str(last.run_id)],
            )
        return RunPage(
            items=tuple(self._run_summary(actor, record) for record in visible),
            page=PageInfo(
                next_cursor=next_cursor,
                snapshot_digest=digest("run-page", 1, {"query": query, "upper": list(upper)}),
                count=len(visible),
            ),
        )

    def runs_events(
        self,
        actor: AuthenticatedActor,
        run_id: RunId,
        *,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> EventPage | ControlRejected:
        denied = self._authorize(actor)
        invalid = self._limit_fault(limit)
        if denied or invalid:
            return denied or cast(ControlRejected, invalid)
        if self._journal.run_record(run_id) is None:
            return self._fault(
                ControlCode.RUN_UNKNOWN,
                f"unknown run {run_id!r}",
                "use a RunId returned by a Constructicon run mutation",
            )
        query: JsonValue = {"run_id": str(run_id)}
        if cursor is None:
            through = self._journal.max_event_seq(run_id)
            after_seq = 0
        else:
            decoded = self._decode_cursor(
                actor,
                cursor,
                kind="run-events",
                query=query,
            )
            if isinstance(decoded, ControlRejected):
                return decoded
            if (
                not isinstance(decoded.upper_bound, int)
                or isinstance(decoded.upper_bound, bool)
                or not isinstance(decoded.last_key, int)
                or isinstance(decoded.last_key, bool)
            ):
                return self._cursor_shape_fault()
            through = decoded.upper_bound
            after_seq = decoded.last_key
            if not 0 <= after_seq <= through <= self._journal.max_event_seq(run_id):
                return self._cursor_shape_fault()
        events = [
            event
            for event in self._journal.events(
                run_id,
                after_seq=after_seq,
                limit=limit + 1,
            )
            if event.seq <= through
        ]
        visible = events[:limit]
        next_cursor = None
        if len(events) > limit and visible:
            next_cursor = self._cursors.encode(
                actor_id=actor.actor_id,
                kind="run-events",
                query=query,
                upper_bound=through,
                last_key=visible[-1].seq,
            )
        items = tuple(
            EventSummary(
                run_id=event.run_id,
                seq=event.seq,
                kind=event.kind,
                path=event.path.render() if event.path else None,
                created_at=event.created_at,
                payload=(
                    cast(dict[str, JsonValue], json_value(event.payload))
                    if event.payload is not None
                    else None
                ),
                detail=self._details.required_reference(
                    actor,
                    DetailAddress.event(run_id, event.seq),
                ),
            )
            for event in visible
        )
        return EventPage(
            run_id=run_id,
            items=items,
            through_seq=through,
            page=PageInfo(
                next_cursor=next_cursor,
                snapshot_digest=digest(
                    "event-page",
                    1,
                    {"run_id": str(run_id), "through": through},
                ),
                count=len(items),
            ),
        )

    def runs_result(
        self,
        actor: AuthenticatedActor,
        run_id: RunId,
    ) -> RunResultPreview | ControlRejected:
        denied = self._authorize(actor)
        if denied:
            return denied
        record = self._journal.run_record(run_id)
        if record is None:
            return self._fault(
                ControlCode.RUN_UNKNOWN,
                f"unknown run {run_id!r}",
                "use a RunId returned by a Constructicon run mutation",
            )
        outputs: dict[str, JsonValue] = {}
        if record.status is RunStatus.SUCCEEDED:
            materialized = json_value(self._system.materialize_run(run_id))
            if isinstance(materialized, dict):
                outputs = self._bounded_mapping(materialized)
        failures: dict[str, str] = {}
        for event in self._journal.events(run_id, after_seq=0, limit=1_000):
            if event.kind == "NodeFailed" and event.path and event.payload:
                failures[event.path.render()] = str(event.payload.get("error", "failed"))
        return RunResultPreview(
            run_id=run_id,
            status=record.status,
            outputs=outputs,
            failures=dict(list(sorted(failures.items()))[:20]),
            detail=self._details.optional_reference(actor, DetailAddress.result(run_id)),
        )

    def commands_status(
        self,
        actor: AuthenticatedActor,
        command_id: str,
    ) -> CommandSummary | ControlRejected:
        denied = self._authorize(actor)
        if denied:
            return denied
        record = self._store.command(command_id)
        if record is None:
            return self._fault(
                ControlCode.COMMAND_UNKNOWN,
                f"unknown command {command_id!r}",
                "use a command_id returned by a mutating control operation",
            )
        if record.actor.actor_id != actor.actor_id and not actor.allows(ADMIN_SCOPE):
            return self._fault(
                ControlCode.AUTH_REQUIRED_SCOPE,
                "command records are visible only to their actor or an administrator",
                "authenticate as the command actor or request constructicon:admin",
            )
        return CommandSummary(
            command_id=record.command_id,
            operation=record.operation,
            state=record.state,
            actor_id=record.actor.actor_id,
            request_hash=record.request_hash,
            created_at=record.created_at,
            updated_at=record.updated_at,
            completed_at=record.completed_at,
            detail=self._details.optional_reference(
                actor,
                DetailAddress.command(command_id),
            ),
        )

    def channels_inbox(
        self,
        actor: AuthenticatedActor,
        *,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> ChannelMessagePage | ControlRejected:
        """One bounded page of the messages waiting on this actor.

        Whose inbox this is, is never a parameter: it is derived from the
        authenticated actor, so no caller can read another recipient's queue.
        Which rows it holds is derived too, from each message's sealed
        interaction, and that filter is pushed into the bounded query so
        ``limit`` counts rows the actor may actually see.
        """

        interactions = self._channel_interactions(actor)
        if isinstance(interactions, ControlRejected):
            return interactions
        invalid = self._limit_fault(limit)
        if invalid:
            return invalid
        # Both halves of the reader's authority are bound into the cursor: the
        # codec binds `actor_id` itself, and the normalized interaction set
        # rides in the query hash. A cursor therefore cannot be replayed across
        # identities, and a page cannot silently continue under scopes the
        # actor no longer holds.
        query: JsonValue = {
            "actor_id": actor.actor_id,
            "interactions": sorted(interactions),
        }
        after: tuple[int, str] | None = None
        if cursor is None:
            revision = self._journal.channel_actor_revision(actor_id=actor.actor_id)
        else:
            decoded = self._decode_cursor(actor, cursor, kind="channel-inbox", query=query)
            if isinstance(decoded, ControlRejected):
                return decoded
            carried = self._inbox_revision(decoded.upper_bound)
            after = self._inbox_key(decoded.last_key)
            # A cursor is a self-checking envelope, not an authority token: its
            # checksum detects corruption, never forgery. So every field it
            # carries is re-validated here, including that the continuation
            # falls inside the bound it claims to continue.
            if carried is None or after is None or after[0] > carried.message_seq:
                return self._cursor_shape_fault()
            revision = carried
        try:
            deliveries = self._journal.channel_actor_inbox(
                actor_id=actor.actor_id,
                revision=revision,
                interactions=interactions,
                after=after,
                limit=limit + 1,
            )
        except InvalidChannelRevision:
            # A cut just read cannot be ahead of the history it was read from,
            # and an append-only history never invalidates one it already
            # issued. Only a carried cut can be stale, forged, or minted
            # against another store — which is a cursor fault, not damage.
            if cursor is None:
                raise
            return self._cursor_shape_fault()
        visible = deliveries[:limit]
        upper: JsonValue = revision.model_dump(mode="json")
        next_cursor = None
        if len(deliveries) > limit and visible:
            last = visible[-1]
            next_cursor = self._cursors.encode(
                actor_id=actor.actor_id,
                kind="channel-inbox",
                query=query,
                upper_bound=upper,
                last_key=[last.message_seq, str(last.message.message_id)],
            )
        return ChannelMessagePage(
            items=tuple(self._channel_summary(actor, delivery) for delivery in visible),
            page=PageInfo(
                next_cursor=next_cursor,
                snapshot_digest=digest(
                    "channel-inbox-page",
                    1,
                    {"query": query, "upper": upper},
                ),
                count=len(visible),
            ),
        )

    def channels_message(
        self,
        actor: AuthenticatedActor,
        message_id: Digest,
    ) -> ChannelMessageSummary | ControlRejected:
        """One exact message, authorized by the request that governs it.

        A reply is addressed to the run rather than to a person, so its
        authority is the request it answers — resolved through the same law the
        page and the detail resource apply.
        """

        delivery = authorized_delivery(self._journal, actor, message_id)
        if isinstance(delivery, ControlRejected):
            return delivery
        return self._channel_summary(actor, delivery)

    def registry_versions(
        self,
        actor: AuthenticatedActor,
        component: str,
        *,
        candidates_only: bool = False,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> VersionPage | ControlRejected:
        denied = self._authorize(actor)
        invalid = self._limit_fault(limit)
        if denied or invalid:
            return denied or cast(ControlRejected, invalid)
        query: JsonValue = {
            "component": component,
            "candidates_only": candidates_only,
        }
        if cursor is None:
            snapshot = self._registry.snapshot()
            offset = 0
        else:
            decoded = self._decode_cursor(
                actor,
                cursor,
                kind="registry-versions",
                query=query,
            )
            if isinstance(decoded, ControlRejected):
                return decoded
            loaded = self._registry_cursor_snapshot(decoded.upper_bound)
            if isinstance(loaded, ControlRejected):
                return loaded
            snapshot = loaded
            offset = decoded.last_key
            if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
                return self._cursor_shape_fault()
        if component not in snapshot.versions:
            return self._fault(
                ControlCode.REGISTRY_VERSION_UNKNOWN,
                f"unknown component {component!r}",
                "choose a component returned by system_describe",
            )
        versions = list(snapshot.order.get(component, ()))
        if candidates_only:
            stable = snapshot.stable.get(component)
            versions = [version for version in versions if version != stable]
        if offset > len(versions):
            return self._cursor_shape_fault()
        visible_hashes = versions[offset : offset + limit]
        next_offset = offset + len(visible_hashes)
        next_cursor = None
        if next_offset < len(versions):
            next_cursor = self._cursors.encode(
                actor_id=actor.actor_id,
                kind="registry-versions",
                query=query,
                upper_bound=snapshot.revision.model_dump(mode="json"),
                last_key=next_offset,
            )
        stable = snapshot.stable.get(component)
        items = tuple(
            VersionSummary(
                component=component,
                version=Digest(version_text),
                stable=version_text == stable,
                registered_at=snapshot.versions[component][version_text].registered_at,
                detail=self._details.required_reference(
                    actor,
                    DetailAddress.component(component, Digest(version_text)),
                ),
            )
            for version_text in visible_hashes
        )
        return VersionPage(
            component=component,
            items=items,
            page=PageInfo(
                next_cursor=next_cursor,
                snapshot_digest=registry_snapshot_digest(snapshot),
                count=len(items),
            ),
        )

    def registry_candidates(
        self,
        actor: AuthenticatedActor,
        component: str,
        *,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> VersionPage | ControlRejected:
        return self.registry_versions(
            actor,
            component,
            candidates_only=True,
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
        denied = self._authorize(actor)
        invalid = self._limit_fault(limit)
        if denied or invalid:
            return denied or cast(ControlRejected, invalid)
        query: JsonValue = {"component": component}
        if cursor is None:
            snapshot = self._registry.snapshot()
            offset = 0
        else:
            decoded = self._decode_cursor(
                actor,
                cursor,
                kind="registry-rdeps",
                query=query,
            )
            if isinstance(decoded, ControlRejected):
                return decoded
            loaded = self._registry_cursor_snapshot(decoded.upper_bound)
            if isinstance(loaded, ControlRejected):
                return loaded
            snapshot = loaded
            offset = decoded.last_key
            if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
                return self._cursor_shape_fault()
        names = self._registry.rdeps(component, snapshot=snapshot)
        if offset > len(names):
            return self._cursor_shape_fault()
        visible = names[offset : offset + limit]
        next_offset = offset + len(visible)
        next_cursor = None
        if next_offset < len(names):
            next_cursor = self._cursors.encode(
                actor_id=actor.actor_id,
                kind="registry-rdeps",
                query=query,
                upper_bound=snapshot.revision.model_dump(mode="json"),
                last_key=next_offset,
            )
        return NamePage(
            kind="reverse_dependencies",
            items=tuple(visible),
            page=PageInfo(
                next_cursor=next_cursor,
                snapshot_digest=registry_snapshot_digest(snapshot),
                count=len(visible),
            ),
        )

    def registry_compare(
        self,
        actor: AuthenticatedActor,
        component: str,
        left: Digest,
        right: Digest,
    ) -> ComponentComparison | ControlRejected:
        denied = self._authorize(actor)
        if denied:
            return denied
        snapshot = self._registry.snapshot()
        left_stored = snapshot.get(component, left)
        right_stored = snapshot.get(component, right)
        if left_stored is None or right_stored is None:
            return self._fault(
                ControlCode.REGISTRY_VERSION_UNKNOWN,
                f"comparison requires two retained versions of {component!r}",
                "choose exact versions returned by registry_versions",
            )
        a = left_stored.definition
        b = right_stored.definition
        pairs = {
            "role": (a.role, b.role),
            "body_kind": (
                "composite" if isinstance(a.body, Graph) else "atomic",
                "composite" if isinstance(b.body, Graph) else "atomic",
            ),
            "inputs": (
                [port.model_dump(mode="json") for port in a.inputs],
                [port.model_dump(mode="json") for port in b.inputs],
            ),
            "outputs": (
                [port.model_dump(mode="json") for port in a.outputs],
                [port.model_dump(mode="json") for port in b.outputs],
            ),
            "capability_requirements": (
                [item.model_dump(mode="json") for item in (a.capability_requirements or ())],
                [item.model_dump(mode="json") for item in (b.capability_requirements or ())],
            ),
            "learning": (
                a.metadata.learning.model_dump(mode="json") if a.metadata.learning else None,
                b.metadata.learning.model_dump(mode="json") if b.metadata.learning else None,
            ),
            "implementation_digest": (
                None if isinstance(a.body, Graph) else str(a.body.source_digest),
                None if isinstance(b.body, Graph) else str(b.body.source_digest),
            ),
        }
        changes: dict[str, JsonValue] = {}
        for name, (before, after) in pairs.items():
            if before != after:
                changes[name] = {
                    "before": json_value(before),
                    "after": json_value(after),
                }
        return ComponentComparison(
            component=component,
            left=left,
            right=right,
            changes=changes,
            reverse_dependencies=tuple(self._registry.rdeps(component, snapshot=snapshot)),
        )

    def details_read(
        self,
        actor: AuthenticatedActor,
        reference: DetailRef,
        *,
        cursor: str | None = None,
        max_bytes: int = 16_000,
    ) -> DetailChunk | ControlRejected:
        denied = self._authorize_detail(actor)
        if denied:
            return denied
        if not isinstance(reference, DetailRef):
            return self._fault(
                ControlCode.REQUEST_INVALID,
                "details_read requires a digest-bound DetailRef",
                "pass the complete reference returned by a status or list operation",
            )
        return self._details.read(
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
        denied = self._authorize_detail(actor)
        if denied:
            return denied
        reference = self._details.reference(actor, uri)
        if isinstance(reference, ControlRejected):
            return reference
        return self._details.read(actor, reference, max_bytes=max_bytes)

    def _run_summary(self, actor: AuthenticatedActor, record: Any) -> RunSummary:
        run_id = record.run_id
        return RunSummary(
            run_id=run_id,
            status=record.status,
            liveness=record.liveness,
            created_at=record.created_at,
            manifest_hash=record.manifest_hash,
            input_hash=record.input_hash,
            origin=record.origin,
            manifest_ref=self._details.required_reference(
                actor,
                DetailAddress.manifest(run_id),
            ),
            result_ref=self._details.optional_reference(
                actor,
                DetailAddress.result(run_id),
            ),
        )

    def _channel_summary(
        self,
        actor: AuthenticatedActor,
        delivery: ChannelDelivery,
    ) -> ChannelMessageSummary:
        """One page row and one addressed read render through one law."""

        message = delivery.message
        return ChannelMessageSummary(
            message_id=message.message_id,
            message_seq=delivery.message_seq,
            channel_id=message.channel_id,
            lane=message.lane,
            interaction=message.interaction,
            kind=message.kind,
            reply_to=message.reply_to,
            run_id=message.envelope.run_id,
            port=message.envelope.port,
            type_id=message.contract.type_id,
            schema_hash=message.contract.schema_hash,
            created_at=message.envelope.created_at,
            acknowledged=delivery.acknowledged,
            detail=self._details.required_reference(
                actor,
                DetailAddress.channel_message(message.message_id),
            ),
        )

    def _channel_interactions(
        self,
        actor: AuthenticatedActor,
    ) -> frozenset[ChannelInteraction] | ControlRejected:
        """This actor's channel reach, or a refusal when it has none.

        Read is deliberately not required. An advisor is its own role rather
        than an observer with extra rights (I9), so it holds
        ``constructicon:advise`` and nothing else, and reads only its own work.

        Holding no interaction scope is refused rather than served an empty
        page, because the two answers say different things: an empty page says
        nothing is waiting for you, and this says the surface is not yours to
        read at all. An advise-only actor with only approvals pending does get
        the empty page, and that is honest — those messages are not its work.
        """

        interactions = channel_reach(actor)
        if not interactions:
            return self._fault(
                ControlCode.AUTH_REQUIRED_SCOPE,
                f"actor {actor.actor_id!r} holds no channel interaction scope",
                f"authenticate with {ADVISE_SCOPE}, {APPROVE_SCOPE}, or {ADMIN_SCOPE}",
                {"required_scopes": [ADVISE_SCOPE, APPROVE_SCOPE]},
            )
        return interactions

    def _authorize_detail(self, actor: AuthenticatedActor) -> ControlRejected | None:
        """The detail door admits any reader; each family holds its own lock.

        A channel message is authorized by the request that governs it, so an
        advisor reads the detail its own inbox handed it without holding read.
        Every other family still requires read, checked where it resolves — so
        this door cannot widen one of them, and no URI reaches a store read
        before the family that owns it has authorized the actor.
        """

        if actor.allows(READ_SCOPE) or channel_reach(actor):
            return None
        return self._fault(
            ControlCode.AUTH_REQUIRED_SCOPE,
            f"actor {actor.actor_id!r} may read no detail family",
            f"authenticate with {READ_SCOPE}, {ADVISE_SCOPE}, {APPROVE_SCOPE}, or {ADMIN_SCOPE}",
            {"required_scope": READ_SCOPE},
        )

    @staticmethod
    def _inbox_revision(value: JsonValue | None) -> ActorInboxRevision | None:
        """The cross-channel cut a cursor carries, validated by its own model.

        A revision is one named vector, not a pair of loose numbers, so the
        cursor carries it as one and the model that defines it does the
        checking — there is no second hand-written schema here to drift from it.
        """

        try:
            return ActorInboxRevision.model_validate(value)
        except ValidationError:
            return None

    @staticmethod
    def _inbox_key(value: JsonValue | None) -> tuple[int, str] | None:
        """Exactly the continuation key ``channel_actor_inbox`` publishes.

        Durable position paired with message id, because an actor's messages
        are sparse in a shared history: a page-position count would redeliver.
        """

        if not isinstance(value, list) or len(value) != 2:
            return None
        message_seq, message_id = value
        if not _is_index(message_seq) or not isinstance(message_id, str):
            return None
        return (message_seq, message_id)

    @staticmethod
    def _bounded_mapping(value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        result: dict[str, JsonValue] = {}
        for key in sorted(value)[:20]:
            item = value[key]
            result[key] = item if len(canonical_json(item)) <= 2_000 else {"truncated": True}
        return result

    @staticmethod
    def _pair(value: JsonValue | None) -> tuple[str, str] | None:
        if (
            isinstance(value, list)
            and len(value) == 2
            and all(isinstance(item, str) for item in value)
        ):
            return (value[0], value[1])
        return None

    def _authorize(self, actor: AuthenticatedActor) -> ControlRejected | None:
        return scope_refusal(actor, READ_SCOPE)

    def _limit_fault(self, limit: int) -> ControlRejected | None:
        if 1 <= limit <= MAX_PAGE_SIZE:
            return None
        return self._fault(
            ControlCode.REQUEST_INVALID,
            f"page limit must be in 1..{MAX_PAGE_SIZE}; received {limit}",
            f"choose a limit in 1..{MAX_PAGE_SIZE}",
        )

    def _decode_cursor(
        self,
        actor: AuthenticatedActor,
        cursor: str,
        *,
        kind: str,
        query: JsonValue,
    ) -> Any | ControlRejected:
        try:
            return self._cursors.decode(
                cursor,
                actor_id=actor.actor_id,
                kind=kind,
                query=query,
            )
        except CursorFault as exc:
            return self._fault(exc.code, exc.message, exc.repair)

    def _cursor_shape_fault(self) -> ControlRejected:
        return self._fault(
            ControlCode.CURSOR_INVALID,
            "cursor continuation shape is invalid",
            "restart the query without a cursor",
        )

    def _registry_cursor_snapshot(
        self,
        upper_bound: JsonValue,
    ) -> RegistrySnapshot | ControlRejected:
        try:
            return self._registry.snapshot(RegistryRevision.model_validate(upper_bound))
        except (ValidationError, InvalidRegistryRevision) as exc:
            return self._fault(
                ControlCode.CURSOR_INVALID,
                f"registry cursor revision is invalid: {exc}",
                "restart the query without a cursor",
            )

    @staticmethod
    def _fault(
        code: ControlCode,
        message: str,
        repair: str,
        details: dict[str, JsonValue] | None = None,
    ) -> ControlRejected:
        return ControlRejected.one_fault(code, message, repair, details)
