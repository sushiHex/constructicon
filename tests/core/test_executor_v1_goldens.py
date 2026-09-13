"""Gateway v1 bytes and revisions, captured before N1 and never recomputed.

Every literal below was captured at base
``d2b8f9421e3b3a5d9edeec42064fa3b42100fa52`` from an independent checkout of
that commit. ADR 0021 admits the native operator records beside the v1 closure
only if the v1 closure keeps its exact serialized meaning, its source-derived
law revision, and its content-derived launch revision. A change here is a
compatibility break, not a test to update.
"""

from __future__ import annotations

from constructicon.core.executor import (
    EXECUTOR_LAW_REVISION,
    ExecutorLaunchIdentity,
    ExecutorProfile,
)
from constructicon.core.native_operator import (
    parse_executor_launch_identity,
    parse_executor_profile,
)
from constructicon.substrate.executors.fake import FakeExecutor
from tests.executorworld import FakeExecutorProvider

BASE = "d2b8f9421e3b3a5d9edeec42064fa3b42100fa52"

LAW_REVISION_AT_BASE = "sha256:8da4745822d8915145e417f86273006010d66089b0fa0e8157a03e5c5c473f9b"

LEGACY_PROFILE = (
    '{"name":"fake","structured_output":true,"postures":["read"],'
    '"isolation":{"filesystem":"none","process_tree_owned":true,'
    '"environment_allowlisted":true,"network_enforced":true},"accepted_efforts":[]}'
)

COMPLETE_PROFILE = (
    '{"name":"fake","structured_output":true,"postures":["read"],'
    '"isolation":{"filesystem":"none","process_tree_owned":true,'
    '"environment_allowlisted":true,"network_enforced":true},"accepted_efforts":[],'
    '"grant_policy":{"schema_version":1,"tool_sets":[[],["read"],["read","search"]],'
    '"network_modes":["none"],"network_access":"none",'
    '"environment_names":["SAFE_TEST"],"workspace_required":false}}'
)

LAUNCH_IDENTITY_JSON = (
    '{"schema_version":1,"executable_digest":'
    '"sha256:7af6ce502514dabbabccfa1c895696df9c76697971d68c1b0d7df1548584c9ce",'
    '"runtime_digest":'
    '"sha256:137bdf365032b3645214eb17add90171ff5aef9d1498f698324ffe98053e2702",'
    '"adapter_revision":'
    '"sha256:b3a0407b96b73069c4530f0cc08841ac71af684ec6eb5b8e0980eefc324465f8",'
    '"decoder_revision":'
    '"sha256:88098015f61eefa45d143ebf3c144a0b1f57bca20f4180aafe2bf19be12daf79",'
    '"isolation_revision":'
    '"sha256:b267a082558cbc2ce846b93dcda9cce565d9ca420cd0e8385eaa62a3c977e02c",'
    '"configuration_digest":'
    '"sha256:e388b7a8b39ff0834b9967f2dd572d5cf303774747a6132fb9fc0a325ba1258f",'
    '"limits_digest":'
    '"sha256:a91a460ab0bc85264cf56119b4cc362bca48a9a1e3e0536dfdba5946dcb58933",'
    '"profile":{"name":"fake","structured_output":true,"postures":["read"],'
    '"isolation":{"filesystem":"none","process_tree_owned":true,'
    '"environment_allowlisted":true,"network_enforced":true},"accepted_efforts":[],'
    '"grant_policy":{"schema_version":1,"tool_sets":[[],["read"],["read","search"]],'
    '"network_modes":["none"],"network_access":"none",'
    '"environment_names":["SAFE_TEST"],"workspace_required":false}},'
    '"provider_route":null}'
)

LAUNCH_REVISION = "sha256:d4d8a00bab79e6dc06fbb5fdbfbfe4fb626c747b3cdabb9ebf694eeba7732039"


def test_shared_v1_law_revision_still_equals_its_base_capture() -> None:
    assert str(EXECUTOR_LAW_REVISION) == LAW_REVISION_AT_BASE


def test_legacy_profile_keeps_its_base_bytes_through_the_new_decoder() -> None:
    assert FakeExecutor({}).profile.model_dump_json() == LEGACY_PROFILE
    decoded = parse_executor_profile(LEGACY_PROFILE)
    assert type(decoded) is ExecutorProfile
    assert decoded.model_dump_json() == LEGACY_PROFILE


def test_complete_v1_profile_keeps_its_base_bytes_through_the_new_decoder() -> None:
    assert FakeExecutorProvider().identity.profile.model_dump_json() == COMPLETE_PROFILE
    decoded = parse_executor_profile(COMPLETE_PROFILE)
    assert type(decoded) is ExecutorProfile
    assert decoded.model_dump_json() == COMPLETE_PROFILE


def test_v1_launch_identity_keeps_its_base_bytes_and_content_revision() -> None:
    identity = FakeExecutorProvider().identity
    assert identity.model_dump_json() == LAUNCH_IDENTITY_JSON
    assert identity.revision == LAUNCH_REVISION
    decoded = parse_executor_launch_identity(LAUNCH_IDENTITY_JSON)
    assert type(decoded) is ExecutorLaunchIdentity
    assert decoded.model_dump_json() == LAUNCH_IDENTITY_JSON
    assert decoded.revision == LAUNCH_REVISION
