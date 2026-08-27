"""Immutable detail resolution behind one URI vocabulary (M6)."""

from __future__ import annotations

from urllib.parse import unquote, urlparse

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
)
from constructicon.core.identity import Digest, JsonValue, canonical_json, digest, json_value
from constructicon.core.run import RunStatus

DEFAULT_DETAIL_BYTES = 16_000
MAX_DETAIL_BYTES = 64_000


class DetailResolver:
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

    @staticmethod
    def ref(uri: str, content: JsonValue | None = None) -> DetailRef:
        return DetailRef(
            uri=uri,
            digest=(digest("detail", 1, content) if content is not None else None),
        )

    def read(
        self,
        actor: AuthenticatedActor,
        uri: str,
        *,
        cursor: str | None = None,
        max_bytes: int = DEFAULT_DETAIL_BYTES,
    ) -> DetailChunk | ControlRejected:
        if max_bytes <= 0 or max_bytes > MAX_DETAIL_BYTES:
            return ControlRejected(
                faults=(
                    ControlFault(
                        code=ControlCode.REQUEST_INVALID,
                        message=(
                            f"max_bytes must be between 1 and {MAX_DETAIL_BYTES}; "
                            f"received {max_bytes}"
                        ),
                        repair=f"choose max_bytes in 1..{MAX_DETAIL_BYTES}",
                    ),
                )
            )
        resolved = self._resolve(uri)
        if isinstance(resolved, ControlRejected):
            return resolved
        normalized = json_value(resolved)
        rendered = canonical_json(normalized)
        raw = rendered.encode("utf-8")
        detail_digest = digest("detail", 1, normalized)
        query = {"uri": uri, "digest": str(detail_digest)}
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
                return ControlRejected(
                    faults=(
                        ControlFault(
                            code=exc.code,
                            message=exc.message,
                            repair=exc.repair,
                        ),
                    )
                )
            if payload.upper_bound != len(raw) or not isinstance(payload.last_key, int):
                return ControlRejected(
                    faults=(
                        ControlFault(
                            code=ControlCode.CURSOR_QUERY_MISMATCH,
                            message="detail cursor no longer matches the immutable bytes",
                            repair="restart this detail read without a cursor",
                        ),
                    )
                )
            offset = payload.last_key
        if offset < 0 or offset > len(raw):
            return ControlRejected(
                faults=(
                    ControlFault(
                        code=ControlCode.CURSOR_INVALID,
                        message="detail cursor offset is outside the document",
                        repair="restart this detail read without a cursor",
                    ),
                )
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
            uri=uri,
            media_type="application/json",
            digest=detail_digest,
            text=text,
            offset=offset,
            total_bytes=len(raw),
            next_cursor=next_cursor,
        )

    def _resolve(self, uri: str) -> JsonValue | ControlRejected:
        parsed = urlparse(uri)
        if parsed.scheme != "constructicon":
            return self._not_found(uri, "detail URI must use constructicon://")
        family = parsed.netloc
        parts = [unquote(part) for part in parsed.path.split("/") if part]
        try:
            if family == "runs" and len(parts) == 2:
                run_id = RunId(parts[0])
                if parts[1] == "manifest":
                    manifest = self._system.manifest_for_run(run_id)
                    return manifest.model_dump(mode="json")
                if parts[1] == "result":
                    record = self._system.journal.run_record(run_id)
                    if record is None:
                        return self._not_found(uri, f"unknown run {run_id!r}")
                    outputs: dict[str, JsonValue] = {}
                    if record.status is RunStatus.SUCCEEDED:
                        outputs = json_value(self._system.materialize_run(run_id))  # type: ignore[assignment]
                    events = self._system.journal.events(run_id, after_seq=0, limit=10_000)
                    failures = [
                        event.model_dump(mode="json")
                        for event in events
                        if event.kind in {"NodeFailed", "RunFailed", "RunParked"}
                    ]
                    return {
                        "run": record.model_dump(mode="json"),
                        "outputs": outputs,
                        "terminal_events": failures,
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
                record = self._store.command(parts[0])
                return (
                    record.model_dump(mode="json")
                    if record is not None
                    else self._not_found(uri, "command does not exist")
                )
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
                snapshot = self._system.registry.snapshot()
                from constructicon.core.identity import Digest

                version = Digest(version_text)
                stored = snapshot.get(name, version)
                return (
                    stored.model_dump(mode="json")
                    if stored is not None
                    else self._not_found(uri, "component version does not exist")
                )
        except (ValueError, TypeError) as exc:
            return self._not_found(uri, f"invalid detail URI: {exc}")
        return self._not_found(uri, "detail URI is not recognized")

    @staticmethod
    def _not_found(uri: str, message: str) -> ControlRejected:
        return ControlRejected(
            faults=(
                ControlFault(
                    code=ControlCode.DETAIL_NOT_FOUND,
                    message=f"{message}: {uri}",
                    repair="use a DetailRef returned by a Constructicon control response",
                ),
            )
        )
