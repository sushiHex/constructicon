"""Immutable detail references and one authorization-aware resolver (M6.1)."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, unquote, urlparse

from constructicon.api.cursor import CursorCodec, CursorFault
from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.channel import ChannelDelivery, governing_request
from constructicon.core.control import (
    ADMIN_SCOPE,
    INTERACTION_SCOPES,
    READ_SCOPE,
    AuthenticatedActor,
    ControlCode,
    ControlRejected,
    ControlStore,
    DetailChunk,
    DetailRef,
    channel_authority_holder,
    command_visible_to,
)
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.core.identity import Digest, JsonValue, canonical_json, digest, json_value
from constructicon.core.journal import Journal
from constructicon.core.run import RunStatus
from constructicon.runtime.registry import ComponentRegistry

DEFAULT_DETAIL_BYTES = 16_000
MIN_DETAIL_BYTES = 4
MAX_DETAIL_BYTES = 64_000
TERMINAL_EVENT_STATUSES = {
    "RunSucceeded": RunStatus.SUCCEEDED,
    "RunFailed": RunStatus.FAILED,
    "RunParked": RunStatus.PARKED,
    "RunCancelled": RunStatus.CANCELLED,
}
IMMUTABLE_RESULT_STATUSES = frozenset(TERMINAL_EVENT_STATUSES.values())


@dataclass(frozen=True)
class DetailAddress:
    """The one readable URI vocabulary; construction is never hand-written elsewhere."""

    @staticmethod
    def manifest(run_id: RunId) -> str:
        return f"constructicon://runs/{quote(str(run_id), safe='')}/manifest"

    @staticmethod
    def result(run_id: RunId, terminal_seq: int | None = None) -> str:
        base = f"constructicon://runs/{quote(str(run_id), safe='')}/result"
        return base if terminal_seq is None else f"{base}/{terminal_seq}"

    @staticmethod
    def event(run_id: RunId, seq: int) -> str:
        return f"constructicon://runs/{quote(str(run_id), safe='')}/events/{seq}"

    @staticmethod
    def command(command_id: str) -> str:
        return f"constructicon://commands/{quote(command_id, safe='')}"

    @staticmethod
    def approval(approval_id: str) -> str:
        return f"constructicon://approvals/{quote(approval_id, safe='')}"

    @staticmethod
    def attestation(attestation_id: str) -> str:
        return f"constructicon://attestations/{quote(attestation_id, safe='')}"

    @staticmethod
    def component(name: str, version: Digest) -> str:
        return f"constructicon://components/{quote(name, safe='')}/{quote(str(version), safe='')}"

    @staticmethod
    def channel_message(message_id: Digest) -> str:
        return f"constructicon://channels/messages/{quote(str(message_id), safe='')}"


def authorized_delivery(
    journal: Journal,
    actor: AuthenticatedActor,
    message_id: Digest,
) -> ChannelDelivery | ControlRejected:
    """Load one addressed message under the request whose seal governs it.

    Every channel surface — page, message, detail, reply, ack — enters here, so
    none of them can drift into its own reading of who may act. That matters
    concretely on the read path: a summary's detail reference is required, so a
    page whose law disagreed with the detail resolver's would not merely refuse
    a read, it would raise ``JournalDamaged`` on a legitimate page.
    """

    delivery = journal.channel_delivery(message_id=message_id, actor_id=actor.actor_id)
    if delivery is None:
        return ControlRejected.one_fault(
            ControlCode.CHANNEL_MESSAGE_UNKNOWN,
            f"unknown channel message {message_id}",
            "use a message_id returned by channels_inbox",
        )
    answered = (
        journal.channel_delivery(
            message_id=delivery.message.reply_to,
            actor_id=actor.actor_id,
        )
        if delivery.message.reply_to is not None
        else None
    )
    governing = governing_request(
        delivery.message,
        answered.message if answered is not None else None,
    )
    if not channel_authority_holder(governing, actor):
        required = INTERACTION_SCOPES[governing.interaction]
        return ControlRejected.one_fault(
            ControlCode.AUTH_REQUIRED_SCOPE,
            f"channel message {message_id} is not this actor's to act on",
            f"authenticate as the request's sealed recipient with {required}",
            {"required_scope": required},
        )
    return delivery


class DetailResolver:
    """Authorize, resolve, hash, and chunk immutable canonical detail."""

    def __init__(
        self,
        *,
        system: Constructicon,
        store: ControlStore,
        cursors: CursorCodec,
        journal: Journal,
        registry: ComponentRegistry,
    ) -> None:
        self._system = system
        self._store = store
        self._cursors = cursors
        self._journal = journal
        self._registry = registry

    def reference(
        self,
        actor: AuthenticatedActor,
        uri: str,
    ) -> DetailRef | ControlRejected:
        canonical_uri = self._canonical_uri(uri)
        if isinstance(canonical_uri, ControlRejected):
            return canonical_uri
        resolved = self._resolve(actor, canonical_uri)
        if isinstance(resolved, ControlRejected):
            return resolved
        normalized = json_value(resolved)
        return DetailRef(
            uri=canonical_uri,
            digest=digest("detail", 1, normalized),
        )

    def required_reference(self, actor: AuthenticatedActor, uri: str) -> DetailRef:
        """Mint a detail reference whose absence would contradict its owner."""

        reference = self.reference(actor, uri)
        if isinstance(reference, ControlRejected):
            fault = reference.faults[0]
            raise JournalDamaged(
                f"required detail {uri!r} could not be minted: {fault.code.value}: {fault.message}"
            )
        return reference

    def optional_reference(self, actor: AuthenticatedActor, uri: str) -> DetailRef | None:
        """Mint a detail reference when the addressed immutable fact exists."""

        reference = self.reference(actor, uri)
        return reference if isinstance(reference, DetailRef) else None

    def read(
        self,
        actor: AuthenticatedActor,
        reference: DetailRef | str,
        *,
        cursor: str | None = None,
        max_bytes: int = DEFAULT_DETAIL_BYTES,
    ) -> DetailChunk | ControlRejected:
        if max_bytes < MIN_DETAIL_BYTES or max_bytes > MAX_DETAIL_BYTES:
            return self._fault(
                ControlCode.REQUEST_INVALID,
                (
                    f"max_bytes must be between {MIN_DETAIL_BYTES} and "
                    f"{MAX_DETAIL_BYTES}; received {max_bytes}"
                ),
                f"choose max_bytes in {MIN_DETAIL_BYTES}..{MAX_DETAIL_BYTES}",
            )

        # URI-only reads remain accepted by the resolver for internal resource
        # adapters. Public control surfaces require a typed, digest-bound ref.
        if isinstance(reference, str):
            generated = self.reference(actor, reference)
            if isinstance(generated, ControlRejected):
                return generated
            reference = generated
        if reference.digest is None:
            return self._fault(
                ControlCode.DETAIL_DIGEST_MISMATCH,
                f"detail reference {reference.uri!r} carries no immutable digest",
                "request a fresh DetailRef from the owning status or list operation",
            )

        canonical_uri = self._canonical_uri(reference.uri)
        if isinstance(canonical_uri, ControlRejected):
            return canonical_uri

        # Resolution performs family-specific authorization and terminality checks
        # before any payload is serialized. A result alias is pinned before this
        # point so the digest always names one immutable attempt.
        resolved = self._resolve(actor, canonical_uri)
        if isinstance(resolved, ControlRejected):
            return resolved
        normalized = json_value(resolved)
        observed_digest = digest("detail", 1, normalized)
        if observed_digest != reference.digest:
            return self._fault(
                ControlCode.DETAIL_DIGEST_MISMATCH,
                (
                    f"detail {canonical_uri!r} hashes to {observed_digest}, "
                    f"not the supplied {reference.digest}"
                ),
                "request a fresh DetailRef from the owning status or list operation",
                {
                    "expected": str(reference.digest),
                    "observed": str(observed_digest),
                },
            )

        rendered = canonical_json(normalized)
        raw = rendered.encode("utf-8")
        query: JsonValue = {"uri": canonical_uri, "digest": str(reference.digest)}
        offset = 0
        if cursor is not None:
            try:
                payload = self._cursors.decode(
                    cursor,
                    actor_id=actor.actor_id,
                    kind="detail",
                    query=query,
                )
            except CursorFault as exc:
                return self._fault(exc.code, exc.message, exc.repair)
            if (
                not isinstance(payload.upper_bound, int)
                or isinstance(payload.upper_bound, bool)
                or payload.upper_bound != len(raw)
                or not isinstance(payload.last_key, int)
                or isinstance(payload.last_key, bool)
            ):
                return self._fault(
                    ControlCode.CURSOR_INVALID,
                    "detail cursor no longer matches the referenced immutable bytes",
                    "restart this detail read without a cursor using the same DetailRef",
                )
            offset = payload.last_key

        if offset < 0 or offset > len(raw):
            return self._fault(
                ControlCode.CURSOR_INVALID,
                "detail cursor offset is outside the document",
                "restart this detail read without a cursor",
            )
        # A UTF-8 continuation byte is 0b10xxxxxx, so the byte AT the offset
        # decides the boundary in O(1). Decoding the whole prefix would make
        # paging one document quadratic in its size.
        if offset < len(raw) and (raw[offset] & 0xC0) == 0x80:
            return self._fault(
                ControlCode.CURSOR_INVALID,
                "detail cursor offset is not a UTF-8 code-point boundary",
                "restart this detail read without a cursor",
            )

        end = min(len(raw), offset + max_bytes)
        while end > offset:
            try:
                text = raw[offset:end].decode("utf-8")
                break
            except UnicodeDecodeError:
                end -= 1
        else:
            text = ""

        next_cursor = None
        if end < len(raw):
            next_cursor = self._cursors.encode(
                actor_id=actor.actor_id,
                kind="detail",
                query=query,
                upper_bound=len(raw),
                last_key=end,
            )
        return DetailChunk(
            uri=canonical_uri,
            media_type="application/json",
            digest=reference.digest,
            text=text,
            offset=offset,
            total_bytes=len(raw),
            next_cursor=next_cursor,
        )

    def _canonical_uri(self, uri: str) -> str | ControlRejected:
        """Pin the mutable result alias to its current terminal attempt."""

        parsed = urlparse(uri)
        parts = [unquote(part) for part in parsed.path.split("/") if part]
        if parsed.scheme != "constructicon" or parsed.netloc != "runs":
            return uri
        if len(parts) != 2 or parts[1] != "result":
            return uri

        try:
            run_id = RunId(parts[0])
        except (ValueError, TypeError, ContractViolation) as exc:
            return self._not_found(uri, f"invalid detail URI: {exc}")
        run_record = self._journal.run_record(run_id)
        if run_record is None:
            return self._not_found(uri, f"unknown run {run_id!r}")
        if run_record.status not in IMMUTABLE_RESULT_STATUSES:
            return self._not_immutable(
                uri,
                f"run {run_id!r} is still {run_record.status.value}",
            )
        terminal_event = self._journal.latest_terminal_event(run_id)
        if terminal_event is None:
            return self._not_immutable(
                uri,
                f"run {run_id!r} has no terminal event",
            )
        terminal_status = TERMINAL_EVENT_STATUSES.get(terminal_event.kind)
        if terminal_status is not run_record.status:
            return self._not_immutable(
                uri,
                (
                    f"run {run_id!r} status {run_record.status.value} is not bound "
                    f"to terminal event {terminal_event.seq} ({terminal_event.kind})"
                ),
            )
        return DetailAddress.result(run_id, terminal_event.seq)

    def _resolve(
        self,
        actor: AuthenticatedActor,
        uri: str,
    ) -> JsonValue | ControlRejected:
        parsed = urlparse(uri)
        if parsed.scheme != "constructicon":
            return self._not_found(uri, "detail URI must use constructicon://")
        family = parsed.netloc
        parts = [unquote(part) for part in parsed.path.split("/") if part]
        # Every family but `channels` was reachable only behind the caller's
        # read gate, so that check lives here rather than at the door. A channel
        # message is authorized by the request governing it instead, which is
        # what lets an advisor hold `constructicon:advise` and nothing else (I9)
        # without the relaxed door widening any other family by a single URI.
        if family != "channels" and not actor.allows(READ_SCOPE):
            return self._fault(
                ControlCode.AUTH_REQUIRED_SCOPE,
                f"actor {actor.actor_id!r} lacks required scope {READ_SCOPE!r}",
                f"authenticate with {READ_SCOPE} or {ADMIN_SCOPE}",
                {"required_scope": READ_SCOPE},
            )
        try:
            if family == "runs" and len(parts) == 2:
                run_id = RunId(parts[0])
                run_record = self._journal.run_record(run_id)
                if run_record is None:
                    return self._not_found(uri, f"unknown run {run_id!r}")
                if parts[1] == "manifest":
                    manifest = self._system.manifest_for_run(run_id)
                    return manifest.model_dump(mode="json")

            if family == "runs" and len(parts) == 3 and parts[1] == "result":
                run_id = RunId(parts[0])
                terminal_event = self._journal.event(run_id, int(parts[2]))
                if terminal_event is None:
                    return self._not_found(uri, "terminal event does not exist")
                terminal_status = TERMINAL_EVENT_STATUSES.get(terminal_event.kind)
                if terminal_status is None:
                    return self._not_found(uri, "event is not a terminal run event")
                run_record = self._journal.run_record(run_id)
                if run_record is None:
                    return self._not_found(uri, f"unknown run {run_id!r}")
                outputs: dict[str, JsonValue] = {}
                if terminal_status is RunStatus.SUCCEEDED:
                    materialized = json_value(self._system.materialize_run(run_id))
                    if isinstance(materialized, dict):
                        outputs = materialized
                return {
                    "run": {
                        "run_id": str(run_record.run_id),
                        "manifest_hash": str(run_record.manifest_hash),
                        "input_hash": str(run_record.input_hash),
                        "status": terminal_status.value,
                        "created_at": run_record.created_at.isoformat(),
                        "origin": (
                            run_record.origin.model_dump(mode="json")
                            if run_record.origin is not None
                            else None
                        ),
                    },
                    "outputs": outputs,
                    "terminal_event": terminal_event.model_dump(mode="json"),
                }

            if family == "runs" and len(parts) == 3 and parts[1] == "events":
                run_id = RunId(parts[0])
                event = self._journal.event(run_id, int(parts[2]))
                return (
                    event.model_dump(mode="json")
                    if event is not None
                    else self._not_found(uri, "event does not exist")
                )

            if family == "commands" and len(parts) == 1:
                command_record = self._store.command(parts[0])
                if command_record is None:
                    return self._not_found(uri, "command does not exist")
                if not command_visible_to(command_record, actor):
                    return self._fault(
                        ControlCode.AUTH_REQUIRED_SCOPE,
                        "command records are visible only to their actor or an administrator",
                        "authenticate as the command actor or request constructicon:admin",
                    )
                if command_record.state == "prepared":
                    return self._not_immutable(
                        uri,
                        f"command {command_record.command_id!r} is still prepared",
                    )
                return command_record.model_dump(mode="json")

            if family == "approvals" and len(parts) == 1:
                approval = self._store.approval(parts[0])
                return (
                    approval.model_dump(mode="json")
                    if approval is not None
                    else self._not_found(uri, "approval does not exist")
                )

            if family == "attestations" and len(parts) == 1:
                attestation = self._journal.load_attestation(parts[0])
                return (
                    attestation.model_dump(mode="json")
                    if attestation is not None
                    else self._not_found(uri, "attestation does not exist")
                )

            if family == "channels" and len(parts) == 2 and parts[0] == "messages":
                delivery = authorized_delivery(self._journal, actor, Digest(parts[1]))
                if isinstance(delivery, ControlRejected):
                    return delivery
                return delivery.message.model_dump(mode="json")

            if family == "components" and len(parts) == 2:
                name, version_text = parts
                version = Digest(version_text)
                stored = self._registry.snapshot().get(name, version)
                return (
                    stored.model_dump(mode="json")
                    if stored is not None
                    else self._not_found(uri, "component version does not exist")
                )
        except (ValueError, TypeError, ContractViolation) as exc:
            return self._not_found(uri, f"invalid detail URI: {exc}")
        return self._not_found(uri, "detail URI is not recognized")

    @staticmethod
    def _fault(
        code: ControlCode,
        message: str,
        repair: str,
        details: dict[str, JsonValue] | None = None,
    ) -> ControlRejected:
        return ControlRejected.one_fault(code, message, repair, details)

    @classmethod
    def _not_found(cls, uri: str, message: str) -> ControlRejected:
        return cls._fault(
            ControlCode.DETAIL_NOT_FOUND,
            f"{message}: {uri}",
            "use a DetailRef returned by a Constructicon control response",
        )

    @classmethod
    def _not_immutable(cls, uri: str, message: str) -> ControlRejected:
        return cls._fault(
            ControlCode.DETAIL_NOT_IMMUTABLE,
            f"{message}; immutable detail is not available yet: {uri}",
            "poll the owning status operation until the record is terminal",
        )
