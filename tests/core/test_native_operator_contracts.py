"""ADR 0021 schema-3 operator-mode contracts: strict records, strict decoders.

Nothing here proves a native process, a vendor account, an established egress
or a real store. It proves that the credential-free contracts refuse anything
they were not told, that the decoders never fall back to a permissive parse,
and that the published identity is content-derived and principal-free.
"""

from __future__ import annotations

import inspect
import os
import subprocess
import sys
from typing import Any

import pytest
from pydantic import ValidationError

import constructicon.core as core_package
import constructicon.core.native_operator as native_operator
from constructicon.core.executor import ExecutorLaunchIdentity, ExecutorProfile
from constructicon.core.grants import EffectiveGrants, ModelSelection, Posture
from constructicon.core.identity import canonical_json, digest
from constructicon.core.introspection import CapabilityDescription, SystemDescription
from constructicon.core.native_operator import (
    NATIVE_OPERATOR_LAW_REVISION,
    NATIVE_OPERATOR_SCHEMA_VERSION,
    NativeEgressIdentityV1,
    NativeOperatorExecutorProfileV3,
    NativeOperatorGrantPolicyV3,
    NativeOperatorIsolationProfileV3,
    NativeOperatorLaunchIdentityV3,
    NativeOperatorStoreIdentityV1,
    offered_postures,
    operator_binding_digest,
    parse_executor_launch_identity,
    parse_executor_profile,
)
from constructicon.substrate.executors.fake import FakeExecutor
from constructicon.substrate.executors.fake_native_operator import FakeNativeOperatorExecutor
from tests.executorworld import FakeExecutorProvider, policy
from tests.native_operator_world import (
    NATIVE_ROOT_GRANTS,
    FakeNativeOperatorProvider,
    native_egress,
    native_isolation,
    native_launch_identity,
    native_policy,
    native_profile,
    native_store,
)

NATIVE_LAW_MEMBERS = (
    "_names",
    "Posture",
    "ModelSelection",
    "EffectiveGrants",
    "NativeOperatorGrantPolicyV3",
    "NativeOperatorIsolationProfileV3",
    "NativeOperatorExecutorProfileV3",
    "NativeEgressIdentityV1",
    "NativeOperatorStoreIdentityV1",
    "NativeOperatorLaunchIdentityV3",
)

PUBLIC_NAMES = (
    "NATIVE_OPERATOR_LAW_REVISION",
    "NATIVE_OPERATOR_SCHEMA_VERSION",
    "ExecutorLaunchIdentityUnion",
    "ExecutorProfileUnion",
    "NativeEgressIdentityV1",
    "NativeOperatorExecutorProfileV3",
    "NativeOperatorGrantPolicyV3",
    "NativeOperatorIsolationProfileV3",
    "NativeOperatorLaunchIdentityV3",
    "NativeOperatorStoreIdentityV1",
    "offered_postures",
    "operator_binding_digest",
    "parse_executor_launch_identity",
    "parse_executor_profile",
)

FORBIDDEN_IDENTITY_WORDS = ("principal", "email", "tenant", "workspace_id")


def raw_profile() -> dict[str, Any]:
    dumped = native_profile().model_dump(mode="json")
    assert isinstance(dumped, dict)
    return dumped


def raw_launch() -> dict[str, Any]:
    dumped = native_launch_identity(native_profile()).model_dump(mode="json")
    assert isinstance(dumped, dict)
    return dumped


# -- records ------------------------------------------------------------------


def test_policy_inventory_is_an_exact_normalized_set() -> None:
    raw = native_policy().model_dump(mode="json")
    raw.update(
        tool_sets=[["search", "read", "read"], [], ["read", "search"]],
        model_ids=["b-model", "a-model", "a-model"],
        environment_names=["B", "A", "A"],
    )
    normalized = NativeOperatorGrantPolicyV3.model_validate(raw)
    assert normalized.tool_sets == ((), ("read", "search"))
    assert normalized.model_ids == ("a-model", "b-model")
    assert normalized.environment_names == ("A", "B")
    assert NativeOperatorGrantPolicyV3.model_validate_json(normalized.model_dump_json()) == (
        normalized
    )
    for field, value in (
        ("tool_sets", []),
        ("tool_sets", [[""]]),
        ("model_ids", []),
        ("model_ids", [" "]),
        ("environment_names", [""]),
        ("network_modes", []),
        ("network_modes", ["allow", "allow"]),
        ("network_modes", ["none"]),
        ("network_access", "provider_route_only"),
        ("tool_path", "direct"),
        ("schema_version", 1),
        ("schema_version", 2),
        ("schema_version", 4),
        ("schema_version", "3"),
        ("schema_version", None),
    ):
        with pytest.raises(ValidationError):
            NativeOperatorGrantPolicyV3.model_validate({**raw, field: value})
    with pytest.raises(ValidationError):
        NativeOperatorGrantPolicyV3.model_validate({**raw, "new_hidden_policy": True})


def test_policy_states_every_fixed_literal_without_a_default() -> None:
    raw = native_policy().model_dump(mode="json")
    for field in ("network_access", "tool_path", "network_modes", "workspace_required"):
        incomplete = {key: value for key, value in raw.items() if key != field}
        with pytest.raises(ValidationError) as caught:
            NativeOperatorGrantPolicyV3.model_validate(incomplete)
        assert field in str(caught.value)


def test_isolation_declares_every_physical_fact_and_restates_the_posture_rule() -> None:
    raw = native_isolation().model_dump(mode="json")
    for field, value in (
        ("native_workspace", "workspace_only"),
        ("worker_network", "allow"),
        ("credential_state", "none"),
        ("zones", "single"),
        ("filesystem", "anything"),
        ("schema_version", 2),
        ("schema_version", 4),
        ("schema_version", "3"),
        ("schema_version", None),
    ):
        with pytest.raises(ValidationError):
            NativeOperatorIsolationProfileV3.model_validate({**raw, field: value})
    with pytest.raises(ValidationError):
        NativeOperatorIsolationProfileV3.model_validate({**raw, "extra_fact": True})
    for field in ("native_workspace", "worker_network", "credential_state", "zones"):
        incomplete = {key: value for key, value in raw.items() if key != field}
        with pytest.raises(ValidationError):
            NativeOperatorIsolationProfileV3.model_validate(incomplete)

    read = native_isolation(Posture.READ)
    write = native_isolation(Posture.WRITE)
    assert read.satisfies(Posture.READ) and not read.satisfies(Posture.WRITE)
    assert write.satisfies(Posture.WRITE) and not write.satisfies(Posture.READ)
    for field in ("process_tree_owned", "environment_allowlisted"):
        assert not read.model_copy(update={field: False}).satisfies(Posture.READ)
    snapshot = read.model_copy(update={"filesystem": "read_only_snapshot"})
    assert snapshot.satisfies(Posture.READ)


def test_profile_refuses_blank_names_empty_efforts_and_unknown_assurances() -> None:
    raw = raw_profile()
    for field, value in (
        ("name", "   "),
        ("accepted_efforts", []),
        ("accepted_efforts", [""]),
        ("authentication", "gateway_initial_authentication"),
        ("account_assurance", "operator_bound_vendor_identity_verified"),
        ("subscription_overage", "tolerated"),
        ("posture", "admin"),
        ("schema_version", 2),
        ("schema_version", 4),
        ("schema_version", "3"),
        ("schema_version", None),
    ):
        with pytest.raises(ValidationError):
            NativeOperatorExecutorProfileV3.model_validate({**raw, field: value})
    with pytest.raises(ValidationError):
        NativeOperatorExecutorProfileV3.model_validate({**raw, "postures": ["read"]})
    normalized = NativeOperatorExecutorProfileV3.model_validate(
        {**raw, "accepted_efforts": ["medium", "low", "low"]}
    )
    assert normalized.accepted_efforts == ("low", "medium")
    assert NATIVE_OPERATOR_SCHEMA_VERSION == 3 == native_profile().schema_version


def test_one_profile_offers_exactly_one_posture() -> None:
    assert offered_postures(native_profile(posture=Posture.READ)) == frozenset({Posture.READ})
    assert offered_postures(native_profile(posture=Posture.WRITE)) == frozenset({Posture.WRITE})
    assert offered_postures(FakeExecutor({}).profile) == frozenset({Posture.READ})


# -- decoders -----------------------------------------------------------------


def test_profile_dispatch_selects_by_the_declared_version() -> None:
    raw = raw_profile()
    assert type(parse_executor_profile(raw)) is NativeOperatorExecutorProfileV3
    legacy = FakeExecutor({}).profile.model_dump(mode="json")
    assert "schema_version" not in legacy
    assert type(parse_executor_profile(legacy)) is ExecutorProfile
    assert parse_executor_profile(native_profile()) == native_profile()
    for version in (1, 2, 4, 3.0, None, True):
        with pytest.raises(ValueError) as caught:
            parse_executor_profile({**raw, "schema_version": version})
        assert "is unsupported" in str(caught.value)
    with pytest.raises(ValueError, match="must be a JSON object"):
        parse_executor_profile("[1, 2]")


def _decode_outcome(decode: Any, raw: Any) -> Any:
    """The decode result or its refusal, so a wrong route fails by assertion."""

    try:
        return decode(raw)
    except (TypeError, ValueError) as refusal:
        return refusal


def test_a_declared_three_is_never_routed_to_the_unversioned_parser() -> None:
    profile = _decode_outcome(parse_executor_profile, raw_profile())
    assert type(profile) is NativeOperatorExecutorProfileV3, profile
    identity = _decode_outcome(parse_executor_launch_identity, raw_launch())
    assert type(identity) is NativeOperatorLaunchIdentityV3, identity


def test_a_string_version_never_selects_the_native_profile() -> None:
    with pytest.raises(ValueError) as caught:
        parse_executor_profile({**raw_profile(), "schema_version": "3"})
    assert "is unsupported" in str(caught.value)


def test_a_failed_native_decode_never_falls_back_to_the_unversioned_profile() -> None:
    raw = raw_profile()
    incomplete = {key: value for key, value in raw.items() if key != "authentication"}
    with pytest.raises(ValidationError) as caught:
        parse_executor_profile(incomplete)
    assert "authentication" in str(caught.value)
    with pytest.raises(ValidationError) as mixed:
        parse_executor_profile({**raw, "grant_policy": policy().model_dump(mode="json")})
    assert "grant_policy" in str(mixed.value)


def test_launch_dispatch_selects_by_the_declared_version() -> None:
    raw = raw_launch()
    assert type(parse_executor_launch_identity(raw)) is NativeOperatorLaunchIdentityV3
    v1 = FakeExecutorProvider().identity.model_dump(mode="json")
    assert type(parse_executor_launch_identity(v1)) is ExecutorLaunchIdentity
    assert parse_executor_launch_identity(FakeExecutorProvider().identity) == (
        FakeExecutorProvider().identity
    )
    absent = {key: value for key, value in v1.items() if key != "schema_version"}
    for candidate in (absent, {**raw, "schema_version": 2}, {**raw, "schema_version": 4}):
        with pytest.raises(ValueError) as caught:
            parse_executor_launch_identity(candidate)
        assert "is unsupported" in str(caught.value)
    with pytest.raises(ValueError, match="must be a JSON object"):
        parse_executor_launch_identity("null")
    with pytest.raises(ValidationError):
        parse_executor_launch_identity(
            {**raw, "profile": FakeExecutorProvider().identity.profile.model_dump(mode="json")}
        )


def test_a_schema_one_launch_identity_refuses_a_hybrid_native_profile() -> None:
    v1 = FakeExecutorProvider().identity.model_dump(mode="json")
    hybrid = dict(v1["profile"])
    hybrid.update(schema_version=3, authentication="vendor_managed_subscription")
    with pytest.raises(ValueError, match="requires the unversioned profile"):
        parse_executor_launch_identity({**v1, "profile": hybrid})


def test_parse_agrees_for_json_and_mappings_and_reencodes_the_exact_input() -> None:
    profile = native_profile()
    identity = native_launch_identity(profile)
    for original in (profile, identity):
        encoded = original.model_dump_json()
        parser = parse_executor_profile if original is profile else parse_executor_launch_identity
        from_text = parser(encoded)
        from_mapping = parser(original.model_dump(mode="json"))
        assert from_text == from_mapping == original
        assert from_text.model_dump_json() == encoded


# -- the one pure predicate ---------------------------------------------------


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"posture": Posture.WRITE}, "executor offers only posture 'read', not 'write'"),
        ({"allowed_tools": ("search",)}, "does not offer exact tool set"),
        ({"network": "none"}, "network 'none' excludes model networking"),
        ({"env_allowlist": ("UNDECLARED",)}, "cannot inherit environment names"),
        ({"effort": None}, "requires an explicit listed effort"),
        ({"effort": "unknown"}, "requires an explicit listed effort"),
        (
            {"model_selection": ModelSelection(kind="backend_default")},
            "requires an explicit model from its finite inventory",
        ),
        (
            {"model_selection": ModelSelection(kind="explicit", model="  ")},
            "requires an explicit model from its finite inventory",
        ),
        (
            {"model_selection": ModelSelection(kind="explicit", model="other-model")},
            "does not offer model 'other-model'",
        ),
    ],
)
def test_adapter_and_profile_share_every_native_grant_refusal(
    change: dict[str, Any], message: str
) -> None:
    profile = native_profile()
    executor = FakeNativeOperatorExecutor({}, profile=profile)
    grants = NATIVE_ROOT_GRANTS.model_copy(update=change)
    faults = executor.validate_grants(grants)
    assert faults == profile.grant_faults(grants)
    assert any(message in fault for fault in faults), faults


def test_accepted_grants_and_equivalent_tool_orderings_produce_no_fault() -> None:
    profile = native_profile()
    assert profile.grant_faults(NATIVE_ROOT_GRANTS) == ()
    reordered = NATIVE_ROOT_GRANTS.model_copy(
        update={"allowed_tools": ("search", "read", "read")}
    )
    assert profile.grant_faults(reordered) == ()
    assert profile.grant_faults(
        NATIVE_ROOT_GRANTS.model_copy(update={"allowed_tools": ()})
    ) == ()


@pytest.mark.parametrize(
    "field", ["process_tree_owned", "environment_allowlisted", "network_enforced", "filesystem"]
)
def test_complete_native_policy_requires_every_physical_declaration(field: str) -> None:
    profile = native_profile()
    changed = profile.model_copy(
        update={
            "isolation": profile.isolation.model_copy(
                update={field: "workspace_only" if field == "filesystem" else False}
            )
        }
    )
    assert changed.grant_faults(NATIVE_ROOT_GRANTS)


def test_overage_is_a_profile_fact_that_no_grant_can_select() -> None:
    forbidden = native_profile(overage="forbidden")
    authorized = native_profile(overage="operator_authorized")
    assert canonical_json(forbidden) != canonical_json(authorized)
    assert native_launch_identity(forbidden).revision != native_launch_identity(authorized).revision
    assert set(EffectiveGrants.model_fields) == {
        "posture",
        "model_selection",
        "effort",
        "allowed_tools",
        "env_allowlist",
        "network",
        "timeout_s",
    }


# -- identity -----------------------------------------------------------------


def test_operator_binding_digest_binds_key_generation_and_instance() -> None:
    base = operator_binding_digest("operator-a", 1, "store-a")
    assert base != operator_binding_digest("operator-b", 1, "store-a")
    assert base != operator_binding_digest("operator-a", 2, "store-a")
    assert base != operator_binding_digest("operator-a", 1, "store-b")
    assert base == operator_binding_digest("operator-a", 1, "store-a")
    for key, generation, instance in (
        ("", 1, "store-a"),
        ("  ", 1, "store-a"),
        ("operator-a", 0, "store-a"),
        ("operator-a", -1, "store-a"),
        ("operator-a", 1, ""),
    ):
        with pytest.raises(ValueError):
            operator_binding_digest(key, generation, instance)


def test_native_law_inventory_is_complete() -> None:
    assert (
        digest(
            "executor-native-operator-law",
            3,
            {
                name: inspect.getsource(getattr(native_operator, name))
                for name in NATIVE_LAW_MEMBERS
            },
        )
        == NATIVE_OPERATOR_LAW_REVISION
    )


def test_native_law_is_bound_into_every_published_revision(monkeypatch: Any) -> None:
    identity = native_launch_identity(native_profile())
    original = identity.revision
    assert original == str(
        digest(
            "executor-native-operator-launch",
            3,
            {
                "law": NATIVE_OPERATOR_LAW_REVISION,
                "identity": identity.model_dump(mode="json"),
            },
        )
    )
    monkeypatch.setattr(
        "constructicon.core.native_operator.NATIVE_OPERATOR_LAW_REVISION",
        digest("other", 1, {}),
    )
    assert identity.revision != original


def test_every_identity_fact_changes_the_published_revision() -> None:
    identity = native_launch_identity(native_profile())
    for field in set(NativeOperatorLaunchIdentityV3.model_fields) - {
        "schema_version",
        "profile",
        "egress",
        "store",
    }:
        changed = identity.model_copy(update={field: digest("changed", 1, field)})
        assert changed.revision != identity.revision, field
    for field in set(NativeEgressIdentityV1.model_fields) - {"schema_version"}:
        egress = identity.egress.model_copy(update={field: digest("changed", 1, field)})
        assert identity.model_copy(update={"egress": egress}).revision != identity.revision, field
    for field in set(NativeOperatorStoreIdentityV1.model_fields) - {"schema_version"}:
        store = identity.store.model_copy(update={field: digest("changed", 1, field)})
        assert identity.model_copy(update={"store": store}).revision != identity.revision, field
    other = identity.model_copy(update={"profile": native_profile(name="other-native")})
    assert other.revision != identity.revision


def test_native_revision_is_stable_across_process_hash_seeds() -> None:
    script = (
        "from tests.native_operator_world import native_launch_identity, native_profile; "
        "print(native_launch_identity(native_profile()).revision)"
    )
    revisions = [
        subprocess.run(
            [sys.executable, "-c", script],
            env={**os.environ, "PYTHONHASHSEED": seed},
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout.strip()
        for seed in ("1", "2", "3")
    ]
    assert len(set(revisions)) == 1
    assert revisions[0].startswith("sha256:")


def test_vendor_principal_labels_never_reach_the_published_identity() -> None:
    first = FakeNativeOperatorProvider(vendor_principal_label="operator-one@example.test")
    second = FakeNativeOperatorProvider(vendor_principal_label="operator-two@example.test")
    assert first.identity.revision == second.identity.revision
    assert first.identity.model_dump_json() == second.identity.model_dump_json()
    assert first.descriptor() == second.descriptor()
    published = canonical_json(first.identity)
    assert "operator-one@example.test" not in published
    for word in FORBIDDEN_IDENTITY_WORDS:
        assert word not in published


def test_store_generation_is_identity_and_a_refresh_is_not() -> None:
    first = FakeNativeOperatorProvider(generation=1)
    second = FakeNativeOperatorProvider(generation=2)
    assert first.identity.store != second.identity.store
    assert first.identity.revision != second.identity.revision
    before = first.identity.model_dump_json()
    before_revision = first.identity.revision
    first.simulate_refresh()
    assert first.identity.model_dump_json() == before
    assert first.identity.revision == before_revision


def test_native_profile_round_trips_through_the_description_records() -> None:
    description = CapabilityDescription(
        capability_id="native-fake",
        kind="executor",
        revision=native_launch_identity(native_profile()).revision,
        leased=True,
        requires_posture=None,
        executor_profile=native_profile(),
        channel_profile=None,
        channel_endpoint=None,
        available=True,
        unavailable_reasons=(),
    )
    encoded = description.model_dump_json()
    decoded = CapabilityDescription.model_validate_json(encoded)
    assert type(decoded.executor_profile) is NativeOperatorExecutorProfileV3
    assert decoded.model_dump_json() == encoded
    assert SystemDescription.model_json_schema()["title"] == "SystemDescription"
    legacy = description.model_copy(update={"executor_profile": FakeExecutor({}).profile})
    assert type(
        CapabilityDescription.model_validate_json(legacy.model_dump_json()).executor_profile
    ) is ExecutorProfile
    absent = description.model_copy(update={"executor_profile": None})
    assert CapabilityDescription.model_validate_json(absent.model_dump_json()).executor_profile is (
        None
    )


def test_every_new_public_name_is_importable_from_core() -> None:
    for name in PUBLIC_NAMES:
        assert hasattr(core_package, name), name
        assert name in core_package.__all__, name


def test_native_egress_and_store_records_forbid_extra_and_missing_facts() -> None:
    egress = native_egress().model_dump(mode="json")
    store = native_store().model_dump(mode="json")
    for model, raw in (
        (NativeEgressIdentityV1, egress),
        (NativeOperatorStoreIdentityV1, store),
    ):
        assert model.model_validate(raw).model_dump(mode="json") == raw
        with pytest.raises(ValidationError):
            model.model_validate({**raw, "endpoint": "https://example.test"})
        for field in set(raw) - {"schema_version"}:
            with pytest.raises(ValidationError):
                model.model_validate({key: value for key, value in raw.items() if key != field})
        with pytest.raises(ValidationError):
            model.model_validate({**raw, "schema_version": 3})
