"""WRITE pins and retained authorization bytes, without host or provider I/O."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from constructicon.core.address import GitSha
from constructicon.core.grants import EffectiveGrants, Posture
from constructicon.core.identity import Digest
from constructicon.core.qualification import QualificationAuthorization
from constructicon.core.qualification_write import (
    QualificationCapabilityPin,
    QualificationFixturePin,
    WriteQualificationPins,
    WriteQualificationRequest,
)
from tests.core.test_qualification import acquisition, authorization, read

REVISION = Digest("sha256:" + "a" * 64)
BASE = GitSha("b" * 40)
WRITE_GRANTS = EffectiveGrants(
    posture=Posture.WRITE,
    model_selection={"kind": "explicit", "model": "gpt-6.1-sol"},
    effort="low", allowed_tools=("contained_python",), env_allowlist=(),
    network="allow", timeout_s=300,
)


def pins(**changes) -> WriteQualificationPins:
    return WriteQualificationPins(**{
        "workspace": {"capability_id": "n5-write-workspace", "revision": REVISION},
        "gate": {"capability_id": "n5-write-gate", "revision": REVISION},
        "fixture": {"identity": REVISION, "base_commit": BASE,
                    "target_ref": "refs/heads/n5-write"},
        "report_definition": REVISION,
        **changes,
    })


def write(**changes) -> QualificationAuthorization:
    return authorization(**{
        "authorization_id": "n5-stage4-write-g5-20261012",
        "stage": "qualification-write", "grants": WRITE_GRANTS,
        "revision": str(REVISION),
        "journal": "/var/lib/constructicon-m8-state/n5-stage4-write-g5/qualification.sqlite",
        "attempt_record": "/var/lib/constructicon-m8-state/n5-stage4-write-g5/write.attempt",
        "write": pins(), **changes,
    })


def test_write_round_trips_as_the_existing_provider_interface():
    granted = write()
    decoded = QualificationAuthorization.model_validate_json(granted.model_dump_json())
    assert decoded == granted and decoded.dispatches
    assert decoded.write == pins()
    assert decoded.acquisition_faults(**acquisition(
        run_id=decoded.run_id, revision=str(REVISION), grants=WRITE_GRANTS,
    )) == ()


def test_dispatch_predicate_includes_write_without_changing_retained_stages():
    # Isolate the provider's public predicate from the constructor that also
    # consumes it, so a mutant cannot turn this proof into a fixture error.
    granted = read().model_copy(update={
        "stage": "qualification-write", "grants": WRITE_GRANTS, "write": pins(),
    })
    assert granted.dispatches
    assert read().dispatches
    assert not authorization().dispatches


def test_complete_production_size_write_authorization_fits_the_existing_root_reader():
    raw = write().model_dump_json().encode("utf-8")
    assert len(raw) <= 8192
    record = json.loads(raw)
    assert "write" in record
    assert set(record["write"]) == {"workspace", "gate", "fixture", "report_definition"}
    assert record["write"]["fixture"]["base_commit"] == BASE
    assert QualificationAuthorization.model_validate_json(raw).write == pins()


@pytest.mark.parametrize("change", [
    {"grants": None}, {"attempt_record": None}, {"attempt_record": ""},
    {"max_epoch": 2}, {"write": None},
])
def test_write_requires_its_grants_record_one_epoch_and_assembly_pins(change):
    with pytest.raises(ValidationError):
        write(**change)


@pytest.mark.parametrize("change", [
    {"posture": Posture.READ}, {"timeout_s": 120}, {"allowed_tools": ()},
    {"timeout_s": 301},
    {"allowed_tools": ("contained_python", "other")}, {"env_allowlist": ("SECRET",)},
    {"network": "none"}, {"model_selection": {"kind": "backend_default", "model": None}},
    {"model_selection": {"kind": "backend_default", "model": "gpt-6.1-sol"}},
    {"model_selection": {"kind": "explicit", "model": ""}}, {"effort": None},
])
def test_write_authorization_refuses_other_grant_shapes(change):
    grants = EffectiveGrants.model_validate({**WRITE_GRANTS.model_dump(), **change})
    with pytest.raises(ValidationError):
        write(grants=grants)


def test_acquisition_still_compares_the_exact_model_and_effort_not_just_write_shape():
    granted = write()
    for change in (
        {"model_selection": {"kind": "explicit", "model": "other"}}, {"effort": "high"},
    ):
        grants = EffectiveGrants.model_validate({**WRITE_GRANTS.model_dump(), **change})
        assert granted.acquisition_faults(**acquisition(
            run_id=granted.run_id, revision=str(REVISION), grants=grants,
        )) == ("qualification refuses other grants",)
    assert granted.acquisition_faults(**acquisition(
        run_id=granted.run_id, revision=str(REVISION), grants=WRITE_GRANTS, epoch=2,
    )) == ("qualification refuses an acquisition beyond the authorized epochs",)


@pytest.mark.parametrize("make", [authorization, read])
@pytest.mark.parametrize("extra", [None, pins])
def test_historical_stages_refuse_even_explicit_null_write_keys(make, extra):
    value = None if extra is None else extra()
    with pytest.raises(ValidationError, match="WRITE pins"):
        make(write=value)


@pytest.mark.parametrize("model,fields", [
    (QualificationCapabilityPin, {"capability_id": "workspace", "revision": REVISION}),
    (QualificationFixturePin, {"identity": REVISION, "base_commit": BASE,
                              "target_ref": "refs/heads/n5-write"}),
    (WriteQualificationRequest, {"authorization_id": "write", "fixture_identity": REVISION,
                                "base_commit": BASE}),
])
def test_new_records_are_closed_and_frozen(model, fields):
    record = model(**fields)
    with pytest.raises(ValidationError):
        model(**{**fields, "locator": "/private/host/path"})
    with pytest.raises(ValidationError):
        record.base_commit = BASE


@pytest.mark.parametrize("change", [
    {"workspace": None}, {"gate": None}, {"fixture": None}, {"report_definition": None},
    {"workspace": {"capability_id": "", "revision": REVISION}},
    {"gate": {"capability_id": "gate", "revision": "not-a-digest"}},
    {"extra": "field"},
])
def test_write_pin_block_requires_every_real_identity(change):
    with pytest.raises(ValidationError):
        pins(**change)


@pytest.mark.parametrize("base", ["", "b" * 39, "b" * 41, "B" * 40, "g" * 64])
def test_fixture_and_request_require_an_exact_git_object_identity(base):
    with pytest.raises(ValidationError):
        QualificationFixturePin(identity=REVISION, base_commit=base, target_ref="refs/heads/n5")
    with pytest.raises(ValidationError):
        WriteQualificationRequest(authorization_id="write", fixture_identity=REVISION,
                                  base_commit=base)


@pytest.mark.parametrize("length", [40, 64])
def test_both_supported_git_object_formats_are_retained(length):
    fixture = QualificationFixturePin(identity=REVISION, base_commit="b" * length,
                                      target_ref="refs/heads/n5")
    assert fixture.base_commit == "b" * length


def test_fixture_target_requires_a_full_ref():
    with pytest.raises(ValidationError):
        QualificationFixturePin(identity=REVISION, base_commit=BASE, target_ref="main")


# Captured from the unmodified authorization code at b2d4543 before implementing
# WRITE. Keep the old defaults and exact model_dump_json ordering, not a golden
# generated by the serializer under test.
GOLDEN_COMMON = (
    '"actor_id":"operator","idempotency_key":"stage1",'
    '"scope":{"segments":["qualification","qualify"]},"binding":"executor",'
    '"source_graph_hash":"sha256:8be9cbb91ec6c81ce7c1fdb7bb7a0172d70140ecfa1201e5db4cbb8202ae6fb4",'
    '"capability_id":"codex-operator","revision":"rev-1",'
    '"operator_binding_digest":"sha256:58609159ca21c745b83995ccb09e739d49081fc91ccab92956b771428da2e2e6",'
    '"journal":"/var/lib/constructicon/qualification.sqlite","max_epoch":1,'
    '"not_after":"2026-10-08T14:00:00Z",'
)
NO_DISPATCH_GOLDEN = (
    '{"authorization_id":"ci-fixture","stage":"qualification-no-dispatch",'
    + GOLDEN_COMMON + '"grants":null,"attempt_record":null}'
)
READ_GOLDEN = (
    '{"authorization_id":"ci-fixture","stage":"qualification-read",'
    + GOLDEN_COMMON + '"grants":{"posture":"read",'
    '"model_selection":{"kind":"explicit","model":"m"},"effort":"low",'
    '"allowed_tools":[],"env_allowlist":[],"network":"allow","timeout_s":120},'
    '"attempt_record":"/var/lib/constructicon/stage3.attempt"}'
)


@pytest.mark.parametrize("make,golden", [
    (authorization, NO_DISPATCH_GOLDEN), (read, READ_GOLDEN),
])
def test_retained_authorization_wire_bytes_and_defaults_are_unchanged(make, golden):
    record = make()
    assert record.model_dump_json() == golden
    assert "write" not in record.model_dump()
    assert "write" not in record.model_dump(mode="json")
    assert QualificationAuthorization.model_validate_json(golden).model_dump_json() == golden
