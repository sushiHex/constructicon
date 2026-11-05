"""One-shot fixture generator using actual pinned historical journal writers.

Not imported by tests. Run locally with revision and shape; its SQL transcript
is committed separately so ordinary CI needs neither historical Git objects
nor network access. No vendor executable is used.
"""

from __future__ import annotations

import importlib.abc
import importlib.util
import io
import linecache
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch


def main() -> None:
    sys.stdout.reconfigure(newline="\n")
    revision, shape, *parameters = sys.argv[1:]
    archive = subprocess.check_output(
        ["git", "archive", revision, "src"],
        stdin=subprocess.DEVNULL,
    )
    with tarfile.open(fileobj=io.BytesIO(archive)) as package:
        sources = {}
        for member in package.getmembers():
            if member.name.endswith(".py"):
                stream = package.extractfile(member)
                assert stream is not None
                sources[member.name] = stream.read()

    class HistoricalSource(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def find_spec(self, fullname, path=None, target=None):
            if not fullname.startswith("constructicon"):
                return None
            key = "src/" + fullname.replace(".", "/")
            for suffix in ("/__init__.py", ".py"):
                if key + suffix in sources:
                    spec = importlib.util.spec_from_loader(
                        fullname,
                        self,
                        is_package=suffix.startswith("/"),
                    )
                    assert spec is not None
                    spec.origin = key + suffix
                    return spec
            return None

        def create_module(self, spec):
            return None

        def exec_module(self, module):
            module.__file__ = module.__spec__.origin
            source = sources[module.__file__]
            linecache.cache[module.__file__] = (
                len(source),
                None,
                source.decode("utf-8").splitlines(keepends=True),
                module.__file__,
            )
            exec(
                compile(sources[module.__spec__.origin], module.__spec__.origin, "exec"),
                module.__dict__,
            )

    sys.meta_path.insert(0, HistoricalSource())
    from constructicon.core.address import ExecutionPath, RunId, ScopePath
    from constructicon.core.manifest import CapabilityLease
    from constructicon.core.workspace import lease_id_for
    from constructicon.substrate.journal.sqlite import SCHEMA_VERSION, SqliteJournal
    from tests.run_worlds import create_test_run, start_test_run

    if shape == "refuse-newer":
        from constructicon.core.errors import JournalDamaged

        database = Path(parameters[0])
        connection = sqlite3.connect(database)
        try:
            before = tuple(connection.iterdump())
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            connection.close()
        assert version > SCHEMA_VERSION
        error = None
        try:
            SqliteJournal(database)
        except Exception as exc:
            error = exc
        assert isinstance(error, JournalDamaged), error
        assert "refusing to touch it" in str(error)
        connection = sqlite3.connect(database)
        try:
            assert tuple(connection.iterdump()) == before
            assert connection.execute("PRAGMA user_version").fetchone()[0] == version
            assert connection.execute("PRAGMA journal_mode").fetchone()[0] == mode
        finally:
            connection.close()
        print(f"Actual writer {revision} schema {SCHEMA_VERSION} refused schema {version};"
              " exact logical bytes/version/journal mode unchanged.")
        return

    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "historical.db"
        if shape == "attestation-baseline":
            from constructicon.core.effect import (
                AttestationDraft,
                CheckResult,
                ComponentProofSubject,
                EffectRequest,
                MergeSubject,
                channel_send_subject,
                idempotency_key,
            )
            from constructicon.core.identity import digest
            from constructicon.core.registry import PromotionRecord, StoredVersion
            from tests.conftest import BRIEF, ISSUE, atomic, triage_impl
            from tests.migrations.test_sqlite_v6_to_v7 import RUN, _intent

            assert SCHEMA_VERSION == 9, "attestation baseline requires actual schema-9 writer"
            now = datetime(2026, 1, 1, tzinfo=UTC)
            journal = SqliteJournal(database, now_fn=lambda: now)
            manifest = create_test_run(journal, RUN)
            definition, _ = atomic("history/attestation", (ISSUE,), (BRIEF,), triage_impl)
            version = definition.content_hash()
            journal.store_version(StoredVersion(
                definition=definition, content_hash=version, registered_at=now,
            ))
            with patch("os.getpid", return_value=123):
                worker = start_test_run(journal, RUN, owner_id="historical-writer")
            common = dict(checks=(CheckResult(name="history", status="passed",
                          detail="actual schema-9 writer", elapsed_s=0.0),),
                          check_set_hash=digest("check-set", 1, {"history": True}),
                          manifest_hash=manifest.manifest_hash)
            promotion = journal.mint_attestation(worker, AttestationDraft(
                action="promote", subject=ComponentProofSubject(
                    component=definition.name, version=version, baseline_version=None,
                ), **common,
            ))
            journal.store_promotion(PromotionRecord(
                component=definition.name, channel="stable", from_version=None,
                to_version=version, attestation_id=promotion.attestation_id,
                actor="static:historian", source_run=RUN, created_at=now,
            ))
            journal.mint_policy_attestation(AttestationDraft(
                action="promote", subject=ComponentProofSubject(
                    component="history/policy", version=version, baseline_version=None,
                ), **common,
            ))
            merge = journal.mint_attestation(worker, AttestationDraft(
                action="merge", subject=MergeSubject(
                    repository="history/repository", target_ref="refs/heads/main",
                    expected_base="1" * 40, candidate="2" * 40,
                    merge_commit="3" * 40, tested_tree="4" * 40,
                ), **common,
            ))
            path = ExecutionPath(scope=ScopePath(segments=("historical-effect",)))
            subject = {"history": True}
            request = EffectRequest(
                run_id=RUN, manifest_hash=manifest.manifest_hash, path=path,
                kind="history.record", subject=subject,
                idempotency_key=idempotency_key(manifest.manifest_hash, path,
                                                "history.record", subject),
                attestation_id=merge.attestation_id,
            )
            journal.record_effect_prepared(worker, request)
            intent = _intent()
            send = journal.mint_attestation(worker, AttestationDraft(
                action="send", subject=channel_send_subject(intent), **common,
            ))
            journal.channel_append_request(channel_id=intent.channel_id,
                                           intent=intent, attestation_id=send.attestation_id)
            journal.release_run(worker)
            SqliteJournal(database)
            with sqlite3.connect(database) as connection:
                print(f"-- Actual journal writer {revision}; shape {shape}; schema 9.")
                print("-- Run-owned v1 promotion, merge and send; policy v1; retained dependents.")
                print("\n".join(connection.iterdump()))
                print("PRAGMA user_version = 9;")
            connection.close()
            return
        if shape == "disposal-baseline":
            assert SCHEMA_VERSION == 8, "disposal baseline must come from the schema-8 writer"
            fixture = (Path(__file__).parents[1]
                       / "fixtures/capability_history/schema7-lost-transitions.sql")
            connection = sqlite3.connect(database)
            try:
                connection.executescript(fixture.read_text(encoding="utf-8"))
            finally:
                connection.close()
            journal = SqliteJournal(database, now_fn=lambda: datetime(2026, 1, 1, tzinfo=UTC))
            run_id = RunId("run-disposal-fixture")
            create_test_run(journal, run_id)
            with patch("os.getpid", return_value=123):
                worker = start_test_run(journal, run_id, owner_id="fixture-worker")
            for index in range(2):
                path = ExecutionPath(scope=ScopePath(segments=(f"leased-{index}",)))
                journal.record_capability_lease(worker, CapabilityLease(
                    lease_id=lease_id_for(run_id, path, "workspace"),
                    acquisition_epoch=worker.epoch, run_id=run_id, binding_id="workspace",
                    path=path, state="active", resource_ref=f"fake-resource-{index}",
                ))
            journal.release_run(worker)
            assert len(SqliteJournal(database).capability_leases(run_id)) == 2
            connection = sqlite3.connect(database)
            try:
                print(f"-- Actual journal writer {revision}; shape {shape};"
                      f" schema {SCHEMA_VERSION}.")
                print("-- Retained schema-7 losses plus a schema-8 creation with two active pairs.")
                print("\n".join(connection.iterdump()))
                print("PRAGMA user_version = 8;")
            finally:
                connection.close()
            return
        journal = SqliteJournal(database, now_fn=lambda: datetime(2026, 1, 1, tzinfo=UTC))
        run_id = RunId("run-historical-capabilities")
        create_test_run(journal, run_id)
        create_test_run(journal, RunId("run-historical-empty"))
        # Substitute only the platform-bound PID primitive; writer facts are not rewritten.
        with patch("os.getpid", return_value=123):
            worker = start_test_run(journal, run_id, owner_id="historical-writer")
        states = ("active",) if shape == "transitions" else ("active", "closed", "lost")
        for index, state in enumerate(states):
            path = ExecutionPath(scope=ScopePath(segments=(f"leased-{index}",)))
            acquisition = CapabilityLease(
                lease_id=lease_id_for(run_id, path, "workspace"),
                acquisition_epoch=worker.epoch,
                run_id=run_id,
                binding_id="workspace",
                path=path,
                state=state,
                disposition="released" if state == "closed" else None,
                resource_ref=f"historical/{index}",
            )
            journal.record_capability_lease(worker, acquisition)
            if shape == "transitions":
                for source, target in (("active", "lost"), ("lost", "active"), ("active", "lost")):
                    journal.transition_capability_lease(
                        worker,
                        lease_id=acquisition.lease_id,
                        acquisition_epoch=acquisition.acquisition_epoch,
                        expected=frozenset({source}),
                        target=target,
                    )
        journal.release_run(worker)
        assert len(journal.capability_leases(run_id)) == len(states)
        assert len(SqliteJournal(database).capability_leases(run_id)) == len(states)
        connection = sqlite3.connect(database)
        try:
            print(f"-- Actual journal writer {revision}; shape {shape}; schema {SCHEMA_VERSION}.")
            print("\n".join(connection.iterdump()))
            print(f"PRAGMA user_version = {SCHEMA_VERSION};")
        finally:
            connection.close()


if __name__ == "__main__":
    main()
