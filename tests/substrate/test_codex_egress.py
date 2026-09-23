"""N3b through the actual Codex provider and handle; only primitives substituted.

The relay's two platform primitives, the store syscalls and the acquisition
guard are the substitutions, exactly as in the N2/N3a portable suites. The
published outcome is walked field by field on the accepting path, a refused
path and every allocation, handler and teardown failure path.
"""

from __future__ import annotations

import asyncio
import errno
import json
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.executor import TaskSpec
from constructicon.core.identity import digest
from constructicon.core.native_operator import NativeEgressIdentityV1
from constructicon.substrate.executors import codex, egress
from constructicon.substrate.executors.codex import (
    UNQUALIFIED_PREREQUISITES,
    CodexOperatorProvider,
    launch_identity,
)
from constructicon.substrate.executors.egress import (
    ALLOCATION_FAILED,
    MAX_SOCKET_PATH_BYTES,
    RELAY_FAILED,
    EgressDestination,
    EgressPolicy,
    EgressRelay,
    identity_digests,
)
from constructicon.substrate.git import acquisition as acquisition_module
from constructicon.substrate.git.acquisition import AcquisitionPaths
from tests.native_operator_world import native_store
from tests.substrate.test_codex_adapter import (
    BINARY,
    CONFIGURATION,
    EXPECTED,
    GRANTS,
    ScriptedLauncher,
    bare_launcher,
    clean_native,
    codex_profile,
    context,
)
from tests.substrate.test_codex_adapter import (
    portable_binding as portable_binding,
)
from tests.substrate.test_codex_protocol import (
    assert_published_surfaces_are_bounded,
    strings_of,
)
from tests.substrate.test_egress import (
    ALLOWED,
    DECOY,
    ESTABLISHED,
    head,
    real_hello,
    reply_of,
    until,
)
from tests.substrate.test_egress import (
    listeners as listeners,
)
from tests.substrate.test_egress import (
    peer as peer,
)

EGRESS_REASON = "the native vendor-session egress boundary has not been qualified"


def policy_for(port: int) -> EgressPolicy:
    return EgressPolicy((EgressDestination(ALLOWED, port, "127.0.0.1"),), 4)


def egress_identity(policy: EgressPolicy) -> NativeEgressIdentityV1:
    return NativeEgressIdentityV1(
        **identity_digests(policy),
        physical_conformance_revision=digest("test-egress-conformance", 1, "unproven"),
    )


def provider_for(launcher, *, policy, root, binding=None, reasons=(), egress_id=None):
    return CodexOperatorProvider(
        launcher=launcher, profile=codex_profile(),
        identity=launch_identity(
            launcher=launcher, profile=codex_profile(),
            egress=egress_identity(policy) if egress_id is None else egress_id,
            store=binding[0].sealed if binding is not None else native_store(),
            executable_digest=digest("test-codex-executable", 1, BINARY),
            configuration=CONFIGURATION, catalog=(),
            authenticated_startup_conformance_revision=digest("test-codex-startup", 1, "unproven"),
            subscription_mode_conformance_revision=digest("test-codex-mode", 1, "unproven"),
        ),
        expected_account=EXPECTED, binary=BINARY, configuration=CONFIGURATION, catalog=(),
        acquisition_root=root, unavailable_reasons=reasons,
        binding_store=None if binding is None else binding[0],
        closure=None if binding is None else binding[1],
        egress=policy,
    )


@pytest.fixture
def short_root():
    """The socket path budget leaves at most 49 bytes of acquisition root."""
    root = Path(tempfile.mkdtemp(prefix="n3b")).resolve()
    assert len(os.fsencode(root)) <= MAX_SOCKET_PATH_BYTES - 58, root
    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def events():
    return []


@pytest.fixture
def recorded_guard(monkeypatch, events):
    @asynccontextmanager
    async def guard(paths):
        paths.guard.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(paths.guard, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            yield descriptor
        finally:
            os.close(descriptor)
            events.append("guard-released")

    monkeypatch.setattr(codex, "acquisition_guard", guard)
    monkeypatch.setattr(acquisition_module, "acquisition_guard", guard)


@pytest.fixture
def relays(monkeypatch, events):
    created: list[EgressRelay] = []

    class Recording(EgressRelay):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

        async def __aexit__(self, *details):
            try:
                return await super().__aexit__(*details)
            finally:
                events.append("relay-exited")

    monkeypatch.setattr(codex, "EgressRelay", Recording)
    return created


@dataclass(frozen=True, kw_only=True)
class EgressLauncher(ScriptedLauncher):
    """The scripted launcher, whose native side first speaks to the relay."""

    client: object = None
    seen: list = field(default_factory=list)

    async def exchange(self, command, *, workspace, posture, guard_fds, conversation,
                       timeout_s, native_store=None):
        socket = None if native_store is None else native_store.egress
        self.seen.append({
            "egress": socket, "exists": socket is not None and socket.path.exists(),
        })
        if self.client is not None:
            await self.client(native_store)
        return await super().exchange(
            command, workspace=workspace, posture=posture, guard_fds=guard_fds,
            conversation=conversation, timeout_s=timeout_s, native_store=native_store,
        )


def egress_launcher(client=None) -> EgressLauncher:
    base = bare_launcher(clean_native())
    return EgressLauncher(
        runtime_root=base.runtime_root, expected_runtime=base.expected_runtime,
        bubblewrap=base.bubblewrap, policy=base.policy,
        expected_policy_sha256=base.expected_policy_sha256,
        native=base.native, result=base.result, client=client,
    )


async def open_handle(provider, *, grants=GRANTS, check_control=lambda: None):
    acquired = await provider.acquire(context(grants=grants, check_control=check_control))
    await acquired.materialize()
    return acquired, acquired.resource


async def outcome_of(handle, grants=GRANTS):
    try:
        return await handle.execute(TaskSpec(instruction="x"), workspace=None, grants=grants)
    except BaseException as exc:
        pytest.fail(f"execute raised {type(exc).__name__} instead of publishing an outcome")


def connecting(listeners, peer, relays, target, facts):
    """A native side that speaks CONNECT and one real hello, recording facts only."""
    hello = real_hello()

    async def client(native_store):
        reader, writer = await asyncio.open_connection(*listeners[-1].getsockname()[:2])
        writer.write(head(target, peer.port) + hello)
        await writer.drain()
        facts["reply"] = await reply_of(reader)
        facts["forwarded"] = await until(lambda: peer.received() == hello, 2.0)
        facts["judged"] = await until(lambda: bool(relays[0].observed), 2.0)
        writer.close()

    return client


# --- accepting paths first -----------------------------------------------------


async def test_the_relay_is_listening_during_the_exchange_and_gone_afterwards(
    short_root, portable_binding, recorded_guard, listeners, peer, relays,
):
    facts: dict = {}
    launcher = egress_launcher(connecting(listeners, peer, relays, ALLOWED, facts))
    provider = provider_for(launcher, policy=policy_for(peer.port), root=short_root,
                            binding=portable_binding[1:])
    acquired, handle = await open_handle(provider)
    loop = asyncio.get_running_loop()
    before = loop.time()
    outcome = await outcome_of(handle)
    after = loop.time()
    assert outcome.status == "success" and outcome.output == {"summary": "done"}
    # The relay's deadline is the exchange's own shared deadline.
    assert before + GRANTS.timeout_s <= relays[0]._deadline <= after + GRANTS.timeout_s
    assert facts == {"reply": ESTABLISHED, "forwarded": True, "judged": True}
    seen = launcher.seen[0]
    assert seen["exists"] and seen["egress"].path.parent == handle.paths.payload
    assert launcher.calls[0]["native_store"].egress == seen["egress"]
    assert relays[0].closed and relays[0].observed == {"accepted": 1}
    assert not handle.paths.payload.exists(), "the relay outlived its exchange"
    await provider.close(acquired, "release")


async def test_no_policy_allocates_no_relay_and_mounts_no_leaf(
    short_root, portable_binding, recorded_guard, listeners, relays,
):
    launcher = egress_launcher()
    provider = CodexOperatorProvider(
        launcher=launcher, profile=codex_profile(),
        identity=provider_for(
            launcher, policy=policy_for(443), root=short_root, binding=portable_binding[1:],
        ).identity,
        expected_account=EXPECTED, binary=BINARY, configuration=CONFIGURATION, catalog=(),
        acquisition_root=short_root, unavailable_reasons=(),
        binding_store=portable_binding[1], closure=portable_binding[2],
    )
    acquired, handle = await open_handle(provider)
    outcome = await outcome_of(handle)
    assert outcome.status == "success"
    assert launcher.seen == [{"egress": None, "exists": False}]
    assert relays == [] and listeners == []
    assert not handle.paths.payload.exists()
    await provider.close(acquired, "release")


def test_a_matching_egress_identity_is_accepted_and_the_reason_stays(short_root):
    provider = provider_for(
        bare_launcher(), policy=policy_for(443), root=short_root,
        reasons=UNQUALIFIED_PREREQUISITES,
    )
    assert provider.egress == policy_for(443)
    assert EGRESS_REASON in provider.unavailable_reasons
    assert EGRESS_REASON in UNQUALIFIED_PREREQUISITES


@pytest.mark.parametrize("name", sorted(identity_digests(policy_for(443))))
def test_a_drifted_egress_identity_is_refused(short_root, name):
    policy = policy_for(443)
    drifted = egress_identity(policy).model_copy(
        update={name: digest("test-egress-drift", 1, name)},
    )
    with pytest.raises(ContractViolation, match=f"egress {name} differs"):
        provider_for(bare_launcher(), policy=policy, root=short_root, egress_id=drifted)


def test_the_acquisition_root_budget_binds_at_its_limit(tmp_path):
    anchor = Path(tmp_path.anchor)

    def socket_bytes(root):
        paths = AcquisitionPaths(root, "acq-" + "0" * 32)
        return len(os.fsencode(paths.payload / "egress.sock"))

    width = MAX_SOCKET_PATH_BYTES - socket_bytes(anchor / "x") + 1
    longest = anchor / ("x" * width)
    assert socket_bytes(longest) == MAX_SOCKET_PATH_BYTES
    try:
        accepted = provider_for(bare_launcher(), policy=policy_for(443), root=longest)
    except ContractViolation as exc:
        pytest.fail(f"the longest root inside the budget was refused: {exc}")
    assert accepted.egress is not None
    with pytest.raises(ContractViolation, match="too long") as refused:
        provider_for(bare_launcher(), policy=policy_for(443), root=anchor / ("x" * (width + 1)))
    assert "xxxx" not in str(refused.value)


# --- lifecycle -----------------------------------------------------------------


async def test_close_during_the_exchange_joins_the_relay_before_the_guard_owner_exits(
    short_root, portable_binding, recorded_guard, listeners, relays, events,
):
    entered = asyncio.Event()

    @dataclass(frozen=True, kw_only=True)
    class Blocking(ScriptedLauncher):
        async def exchange(self, command, *, workspace, posture, guard_fds, conversation,
                           timeout_s, native_store=None):
            native_store.before_spawn()
            entered.set()
            await asyncio.sleep(30)
            raise AssertionError("the blocked exchange was never cancelled")

    base = bare_launcher(clean_native())
    launcher = Blocking(
        runtime_root=base.runtime_root, expected_runtime=base.expected_runtime,
        bubblewrap=base.bubblewrap, policy=base.policy,
        expected_policy_sha256=base.expected_policy_sha256, native=base.native,
        result=base.result,
    )
    provider = provider_for(launcher, policy=policy_for(443), root=short_root,
                            binding=portable_binding[1:])
    acquired, handle = await open_handle(provider)
    running = asyncio.create_task(
        handle.execute(TaskSpec(instruction="x"), workspace=None, grants=GRANTS),
    )
    await asyncio.wait_for(entered.wait(), 5)
    assert handle.paths.payload.exists()
    await provider.close(acquired, "discard")
    with pytest.raises(asyncio.CancelledError):
        await running
    assert events == ["relay-exited", "guard-released"]
    assert relays[0].closed and not handle.paths.payload.exists()


class OwnershipLost(Exception):
    """Shaped like the walker's control raise: neither OSError nor ContractViolation."""


async def test_control_lost_during_the_exchange_denies_the_connect(
    short_root, portable_binding, recorded_guard, listeners, peer, relays,
):
    lost: list[bool] = []
    facts: dict = {}

    def control():
        if lost:
            raise OwnershipLost("ownership lost")

    async def native(native_store):
        lost.append(True)
        reader, writer = await asyncio.open_connection(*listeners[-1].getsockname()[:2])
        writer.write(head(ALLOWED, peer.port) + real_hello())
        await writer.drain()
        facts["reply"] = await reply_of(reader)
        facts["closed"] = await reply_of(reader, 1)
        facts["judged"] = await until(lambda: bool(relays[0].observed), 2.0)
        writer.close()

    provider = provider_for(egress_launcher(native), policy=policy_for(peer.port),
                            root=short_root, binding=portable_binding[1:])
    acquired, handle = await open_handle(provider, check_control=control)
    with pytest.raises(OwnershipLost):
        await handle.execute(TaskSpec(instruction="x"), workspace=None, grants=GRANTS)
    assert facts == {"reply": ESTABLISHED, "closed": b"", "judged": True}
    assert relays[0].observed == {"denied:control": 1}
    assert peer.connections == [], "the relay dialled after the handle lost control"
    assert relays[0].closed and not handle.paths.payload.exists()
    await provider.close(acquired, "discard")


async def test_a_close_latched_after_the_task_is_created_allocates_nothing(
    short_root, portable_binding, recorded_guard, listeners, relays,
):
    holder = []

    def control():
        # A close that lands after the exchange task exists but before it runs.
        if holder and holder[0].active is not None:
            holder[0].closed = True

    provider = provider_for(egress_launcher(), policy=policy_for(443), root=short_root,
                            binding=portable_binding[1:])
    acquired, handle = await open_handle(provider, check_control=control)
    holder.append(handle)
    caught = None
    try:
        await handle.execute(TaskSpec(instruction="x"), workspace=None, grants=GRANTS)
    except asyncio.CancelledError as exc:
        caught = exc
    assert caught is not None
    assert listeners == [] and relays == [], "a closed acquisition allocated a relay"
    assert not handle.paths.payload.exists()
    await provider.close(acquired, "discard")


async def test_a_network_none_grant_creates_no_payload(
    short_root, portable_binding, recorded_guard, listeners, relays,
):
    denied = GRANTS.model_copy(update={"network": "none"})
    launcher = egress_launcher()
    provider = provider_for(launcher, policy=policy_for(443), root=short_root,
                            binding=portable_binding[1:])
    acquired, handle = await open_handle(provider, grants=denied)
    outcome = await outcome_of(handle, denied)
    assert outcome.status == "failure" and outcome.error.kind == "unavailable"
    assert "network 'none'" in outcome.error.detail
    assert launcher.seen == [] and listeners == [] and relays == []
    assert not handle.paths.payload.exists()
    await provider.close(acquired, "discard")


# --- the published surface -------------------------------------------------------


SURFACES = ["accepted", "refused", "existing-payload", "over-long-path",
            "substituted-socket", "handler-failure"]


@pytest.mark.parametrize("case", SURFACES)
async def test_no_private_locator_reaches_the_outcome(
    short_root, portable_binding, recorded_guard, listeners, peer, relays, monkeypatch, case,
):
    private = [str(short_root), short_root.as_posix(), "127.0.0.1", "denied:", "egress.sock"]
    client = None
    facts: dict = {}
    if case in ("accepted", "refused"):
        client = connecting(
            listeners, peer, relays, ALLOWED if case == "accepted" else DECOY, facts,
        )
    elif case == "over-long-path":
        def refuse(path):
            raise OSError(errno.EINVAL, "AF_UNIX path too long", str(path))

        monkeypatch.setattr(egress, "_bind_private_socket", refuse)
    elif case == "substituted-socket":
        async def client(native_store):
            native_store.egress.path.unlink()
            native_store.egress.path.write_text(f"substituted under {short_root}")
    elif case == "handler-failure":
        async def failing(sock, count):
            raise RuntimeError(f"unclassified failure under {short_root}")

        async def client(native_store):
            monkeypatch.setattr(egress, "_receive", failing)
            _, writer = await asyncio.open_connection(*listeners[-1].getsockname()[:2])
            await until(lambda: relays[0]._handlers and relays[0]._handlers[0].done())
            writer.close()

    provider = provider_for(egress_launcher(client), policy=policy_for(peer.port),
                            root=short_root, binding=portable_binding[1:])
    acquired, handle = await open_handle(provider)
    if case == "existing-payload":
        handle.paths.payload.mkdir(parents=True)
    outcome = await outcome_of(handle)
    if case in ("accepted", "refused"):
        assert outcome.status == "success", "a denial must not be fatal to the turn"
        assert facts["judged"] and facts["forwarded"] == (case == "accepted")
        assert relays[0].observed == (
            {"accepted": 1} if case == "accepted" else {"denied:destination": 1}
        )
    else:
        assert outcome.status == "failure" and outcome.error.kind == "unavailable"
        assert outcome.output is None and outcome.raw_reply is None
        allocation = case in ("existing-payload", "over-long-path")
        assert outcome.error.detail == (ALLOCATION_FAILED if allocation else RELAY_FAILED)
    assert_published_surfaces_are_bounded(outcome)
    published = json.dumps(outcome.model_dump(mode="json"))
    for item in private:
        assert item not in published, (case, item)
    for name, text in strings_of(outcome.model_dump(mode="json")):
        assert all(item not in text for item in private), (case, name)
    await provider.close(acquired, "discard")
