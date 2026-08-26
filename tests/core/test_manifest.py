"""Manifest schema evolution remains semantic, versioned, and fail-closed."""

from __future__ import annotations

import json

import pytest

from constructicon.core.address import RunId
from constructicon.core.errors import JournalDamaged
from constructicon.core.manifest import manifest_hash_for, parse_manifest_json
from constructicon.substrate.journal.sqlite import SqliteJournal


def _v1_manifest(world: object) -> object:
    from constructicon.api.system import Constructicon
    from tests.conftest import pipeline_graph

    assert isinstance(world, Constructicon)
    manifest = world.validate(
        pipeline_graph(),
        {"issue": {"title": "retry loop is flaky"}},
    )
    temporary = manifest.model_copy(
        update={
            "schema_version": 1,
            "resolved_loops": (),
        }
    )
    return temporary.model_copy(
        update={"manifest_hash": manifest_hash_for(temporary)}
    )


def test_v1_manifest_without_loop_field_parses_semantically(world: object) -> None:
    manifest = _v1_manifest(world)
    payload = manifest.model_dump(mode="json")
    payload.pop("resolved_loops")
    raw = json.dumps(payload, indent=2, sort_keys=False)

    parsed = parse_manifest_json(raw)

    assert parsed == manifest
    assert parsed.resolved_loops == ()


def test_v1_manifest_accepts_materialized_empty_loop_default(world: object) -> None:
    manifest = _v1_manifest(world)
    raw = json.dumps(manifest.model_dump(mode="json"), sort_keys=True)
    assert parse_manifest_json(raw) == manifest


def test_v1_manifest_refuses_nonempty_loop_semantics(world: object) -> None:
    manifest = _v1_manifest(world)
    payload = manifest.model_dump(mode="json")
    payload["resolved_loops"] = [{"not": "v1"}]
    with pytest.raises(ValueError, match="version 1 cannot carry loop"):
        parse_manifest_json(json.dumps(payload))


def test_manifest_refuses_unknown_top_level_fields(world: object) -> None:
    manifest = _v1_manifest(world)
    payload = manifest.model_dump(mode="json")
    payload["surprise"] = True
    with pytest.raises(ValueError, match="surprise"):
        parse_manifest_json(json.dumps(payload))


def test_manifest_refuses_unknown_future_schema(world: object) -> None:
    manifest = _v1_manifest(world)
    payload = manifest.model_dump(mode="json")
    payload["schema_version"] = 99
    with pytest.raises(ValueError, match="unsupported"):
        parse_manifest_json(json.dumps(payload))


def test_journal_accepts_semantically_equal_v1_manifest_bytes(
    world: object,
    tmp_path: object,
) -> None:
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    manifest = _v1_manifest(world)
    first = manifest.model_dump(mode="json")
    first.pop("resolved_loops")
    first_raw = json.dumps(first, indent=2, sort_keys=False)
    second_raw = json.dumps(manifest.model_dump(mode="json"), sort_keys=True)
    journal = SqliteJournal(tmp_path / "manifest.db")

    journal.create_run(
        RunId("v1-a"),
        manifest_json=first_raw,
        manifest_hash=manifest.manifest_hash,
        input_hash=manifest.input_hash,
        inputs={"issue": {"title": "retry loop is flaky"}},
    )
    journal.create_run(
        RunId("v1-b"),
        manifest_json=second_raw,
        manifest_hash=manifest.manifest_hash,
        input_hash=manifest.input_hash,
        inputs={"issue": {"title": "retry loop is flaky"}},
    )

    assert journal.run_manifest_hash(RunId("v1-b")) == manifest.manifest_hash


def test_journal_refuses_different_semantics_under_same_manifest_hash(
    world: object,
    tmp_path: object,
) -> None:
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    manifest = _v1_manifest(world)
    original = manifest.model_dump(mode="json")
    original.pop("resolved_loops")
    altered = json.loads(json.dumps(original))
    altered["source_graph"]["name"] = "different-authored-graph"
    journal = SqliteJournal(tmp_path / "damaged-manifest.db")
    journal.create_run(
        RunId("v1-original"),
        manifest_json=json.dumps(original),
        manifest_hash=manifest.manifest_hash,
        input_hash=manifest.input_hash,
        inputs={"issue": {"title": "retry loop is flaky"}},
    )

    with pytest.raises(JournalDamaged, match="different semantics"):
        journal.create_run(
            RunId("v1-altered"),
            manifest_json=json.dumps(altered),
            manifest_hash=manifest.manifest_hash,
            input_hash=manifest.input_hash,
            inputs={"issue": {"title": "retry loop is flaky"}},
        )
