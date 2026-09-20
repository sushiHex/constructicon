"""Tampered but internally coherent active selections must be refused."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.identity import canonical_json, digest
from tests.operator_store_world import StoreWorld, _identity


def _update_active(world: StoreWorld, **changes: object) -> None:
    active = json.loads(world.metadata["active.json"])
    active.update(changes)
    world.metadata["active.json"] = canonical_json(active).encode()


def test_active_key_must_match_the_configured_binding(tmp_path, monkeypatch):
    world = StoreWorld(tmp_path)
    _update_active(world, key="another-key")
    world.install(monkeypatch)

    with pytest.raises(ContractViolation, match="active selection"):
        world.binding().open_candidate()


@pytest.mark.parametrize("field", ["binding_digest", "descriptor_digest"])
def test_active_digests_must_match_the_selected_descriptor(tmp_path, monkeypatch, field):
    world = StoreWorld(tmp_path)
    _update_active(world, **{field: str(digest("wrong-active-selection", 1, field))})
    world.install(monkeypatch)

    with pytest.raises(ContractViolation, match="active selection"):
        world.binding().open_candidate()


def test_selected_descriptor_generation_must_match_active_generation(tmp_path, monkeypatch):
    world = StoreWorld(tmp_path)
    descriptor = world.descriptor(2)
    world.metadata["1.json"] = canonical_json(descriptor.body()).encode()
    world.sealed = world.sealed.model_copy(update={
        "operator_binding_digest": descriptor.binding_digest,
    })
    world.activate(1)
    world.install(monkeypatch)

    with pytest.raises(ContractViolation, match="active selection"):
        world.binding().open_candidate()


def test_historical_same_instance_lock_remap_is_refused(tmp_path, monkeypatch):
    world = StoreWorld(tmp_path)
    world.write_descriptor(2, lock=_identity("old-lock"))
    world.install(monkeypatch)

    with pytest.raises(ContractViolation, match="instance history"):
        world.binding().open_candidate()


def test_binding_digest_is_derived_from_selected_key_generation_and_instance(
    tmp_path, monkeypatch,
):
    world = StoreWorld(tmp_path)
    wrong_binding = digest("wrong-derived-binding", 1, "same-active-record")
    descriptor = replace(world.descriptor(1), binding_digest=wrong_binding)
    world.metadata["1.json"] = canonical_json(descriptor.body()).encode()
    world.sealed = world.sealed.model_copy(update={"operator_binding_digest": wrong_binding})
    world.activate(1)
    world.install(monkeypatch)

    with pytest.raises(ContractViolation, match="binding"):
        world.binding().open_candidate()
