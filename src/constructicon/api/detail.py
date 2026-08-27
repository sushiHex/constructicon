"""Immutable detail references and one authorization-aware resolver (M6.1)."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, unquote, urlparse

from constructicon.api.cursor import CursorCodec, CursorFault
from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.control import (
    AuthenticatedActor,
    ControlCode,
    ControlFault,
    ControlRejected,
    ControlStore,
    DetailChunk,
    DetailRef,
    command_visible_to,
)
from constructicon.core.errors import ContractViolation
from constructicon.core.identity import Digest, JsonValue, canonical_json, digest, json_value
from constructicon.core.journal import JournalEvent
from constructicon.core.run import RunStatus

DEFAULT_DETAIL_BYTES = 16_000
MAX_DETAIL_BYTES = 64_000
IMMUTABLE_RESULT_STATUSES = frozenset({RunStatus.SUCCEEDED, RunStatus.CANCELLED})


@dataclass(frozen=True)
class DetailAddress:
    """The one readable URI vocabulary; construction is never hand-written elsewhere."""

    @staticmethod
    def manifest(run_id: RunId) -> str:
        return f"constructicon://runs/{quote(str(run_id), safe='')}/manifest"

    @staticmethod
    def result(run_id: RunId) -> str:
        return f"constructicon://runs/{quote(str(run_id), safe='')}/result"

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
        return (
            f"constructicon://components/{quote(name, safe='')}/"
            f"{quote(str(version), safe='')}"
        )


class DetailResolver:
    """Authorize, resolve, hash, and chunk immutable canonical detail."""

    def __init__(
        self,
        *,
        system: Constructicon,
        store: ControlStore,
        cursors: CursorCodec,
    ) -> None:
        self._system = system
        self._store = store
        self._cursors = cursors

    def reference(
        self,
        actor: AuthenticatedActor,
        uri: str,
    ) -> DetailRef | ControlRejected:
        resolved = self._resolve(actor, uri)
        if isinstance(resolved, ControlRejected):
            return resolved
        normalized = json_value(resolved)
        return DetailRef(uri=uri, digest=digest("detail", 1, normalized))

    def read(
        self,
        actor: AuthenticatedActor,
        reference: DetailRef | str,
        *,
        cursor: str | None = None,
        max_bytes: int = DEFAULT_DETAIL_BYTES,
    ) -> DetailChunk | ControlRejected:
        if max_bytes <= 0 or max_bytes > MAX_DETAIL_BYTES:
            return self._fault(
                ControlCode.REQUEST_INVALID,
                f"max_bytes must be between 1 and {MAX_DETAIL_BYTES}; received {max_bytes}",
                f"choose max_bytes in 1..{MAX_DETAIL_BYTES}",
            )

        # URI-only reads remain accepted while MCP and the Python facade migrate;
        # they are immediately converted into an authorized, digest-bound reference.
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

        # Resolution performs family-specific authorization and terminality checks
        # before any payload is serialized.
        resolved = self._resolve(actor, reference.uri)
        if isinstance(resolved, ControlRejected):
            return resolved
        normalized = json_value(resolved)
        observed_digest = digest("detail", 1, normalized)
        if observed_digest != reference.digest:
            return self._fault(
                ControlCode.DETAIL_DIGEST_MISMATCH,
                (
                    f"detail {reference.uri!r} hashes to {observed_digest}, "
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
        query: JsonValue = {"uri": reference.uri, "digest": str(reference.digest)}
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
            if payload.upper_bound != len(raw) or not isinstance(payload.last_key, int):
                return self._fault(
                    ControlCode.CURSOR_QUERY_MISMATCH,
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
            uri=reference.uri,
            media_type=reference.media_type,
            digest=reference.digest,
            text=text,
            offset=offset,
            total_bytes=len(raw),
            next_cursor=next_cursor,
        )

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
        try:
            if family == "runs" and len(parts) == 2:
                run_id = RunId(parts[0])
                run_record = self._system.journal.run_record(run_id)
                if run_record is None:
                    return self._not_found(uri, f"unknown run {run_id!r}")
                if parts[1] == "manifest":
                    manifest = self._system.manifest_for_run(run_id)
                    return manifest.model_dump(mode="json")
                if parts[1] == "result":
                    if run_record.status not in IMMUTABLE_RESULT_STATUSES:
                        return self._not_immutable(
                            uri,
                            f"run {run_id!r} is still {run_record.status.value}",
                        )
                    outputs: dict[str, JsonValue] = {}
                    if run_record.status is RunStatus.SUCCEEDED:
                        materialized = json_value(self._system.materialize_run(run_id))
                        if isinstance(materialized, dict):
                            outputs = materialized
                    terminal_events = [
                        event.model_dump(mode="json")
                        for event in self._events(run_id)
                        if event.kind
                        in {
                            "NodeFailed",
                            "RunFailed",
                            "RunParked",
                            "RunCancelled",
                            "RunSucceeded",
                        }
                    ]
                    return {
                        "run": run_record.model_dump(mode="json"),
                        "outputs": outputs,
                        "terminal_events": terminal_events,
                    }

            if family == "runs" and len(parts) == 3 and parts[1] == "events":
                run_id = RunId(parts[0])
                event = self._system.journal.event(run_id, int(parts[2]))
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
                attestation = self._system.journal.load_attestation(parts[0])
                return (
                    attestation.model_dump(mode="json")
                    if attestation is not None
                    else self._not_found(uri, "attestation does not exist")
                )

            if family == "components" and len(parts) == 2:
                name, version_text = parts
                version = Digest(version_text)
                stored = self._system.registry.snapshot().get(name, version)
                return (
                    stored.model_dump(mode="json")
                    if stored is not None
                    else self._not_found(uri, "component version does not exist")
                )
        except (ValueError, TypeError, ContractViolation) as exc:
            return self._not_found(uri, f"invalid detail URI: {exc}")
        return self._not_found(uri, "detail URI is not recognized")

    def _events(self, run_id: RunId) -> list[JournalEvent]:
        events: list[JournalEvent] = []
        after = 0
        while True:
            page = self._system.journal.events(run_id, after_seq=after, limit=1_000)
            if not page:
                return events
            events.extend(page)
            after = page[-1].seq

    @staticmethod
    def _fault(
        code: ControlCode,
        message: str,
        repair: str,
        details: dict[str, JsonValue] | None = None,
    ) -> ControlRejected:
        return ControlRejected(
            faults=(
                ControlFault(
                    code=code,
                    message=message,
                    repair=repair,
                    details=details or {},
                ),
            )
        )

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
