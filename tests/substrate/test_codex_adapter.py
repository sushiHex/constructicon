"""The Codex operator adapter's lifecycle and conversation, without a process.

Cross-platform and credential-free (I7). The scripted native below is a genuine
byte channel answering the adapter's own framing; it is not a Codex and proves
nothing about the pinned binary. What it does prove is the adapter's
correlation, its two subscription-mode readings, and that a refused
pre-acceptance reading discards an otherwise successful turn.

The physical launch path — the real acquisition guard and the arguments the
handle hands ``exchange`` — is exercised by the ``LINUX``-marked section at the
end of this file, which skips everywhere else. That section is where ADR 0021's
discard is proved in the production binding rather than in a pure function.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.errors import ContractViolation
from constructicon.core.executor import ExecutorProvider, TaskSpec
from constructicon.core.grants import EffectiveGrants, ModelSelection, Posture
from constructicon.core.identity import digest
from constructicon.core.manifest import CapabilityBinding, CapabilityLease
from constructicon.core.native_operator import (
    NativeOperatorExecutorProfileV3,
    NativeOperatorGrantPolicyV3,
    NativeOperatorIsolationProfileV3,
)
from constructicon.core.run import RunLease
from constructicon.core.workspace import LeaseContext, StaleAcquisition
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.substrate.executors.codex import (
    ADAPTER_REVISION,
    UNQUALIFIED_PREREQUISITES,
    CodexConversation,
    CodexOperatorHandle,
    CodexOperatorProvider,
    launch_identity,
)
from constructicon.substrate.executors.codex_protocol import (
    GATE_INCOMPLETE_FAULT,
    NO_ACCOUNT_FAULT,
    RECORD_BYTES,
    ExpectedAccount,
    account_faults,
    decode_turn,
    unavailable_outcome,
)
from constructicon.substrate.executors.linux import (
    LinuxLauncher,
    ProcessExchangeError,
    ProcessResult,
)
from tests.native_operator_world import native_egress, native_store
from tests.substrate.test_codex_protocol import (
    ACCOUNT_NOTICE,
    EMAIL,
    MANAGED,
    THREAD,
    TURN,
    completed,
)

CAPABILITY = "codex-operator"
BINARY = "/usr/bin/codex"
# Nothing here touches the filesystem: only the Linux acquisition guard creates
# anything under this root, and that path runs in the native lane only.
ACQUISITION_ROOT = Path(tempfile.gettempdir()).resolve() / "constructicon-codex-acquisitions"
CONFIGURATION = 'model = "gpt-5.6-sol"\n'
PLAN = "pro"
EXPECTED = ExpectedAccount(plan_type=PLAN)
MANAGED_RESULT = {"account": MANAGED, "requiresOpenaiAuth": True}
EMPTY_RESULT = {"account": None, "requiresOpenaiAuth": False}
FINISHED = ProcessResult(0, b"", b"", 2.0, payload_returncode=0)

GRANTS = EffectiveGrants(
    posture=Posture.READ,
    model_selection=ModelSelection(kind="explicit", model="gpt-5.6-sol"),
    effort="low",
    allowed_tools=(),
    env_allowlist=(),
    network="allow",
    timeout_s=600,
)


def codex_profile() -> NativeOperatorExecutorProfileV3:
    return NativeOperatorExecutorProfileV3(
        name="codex-operator-read",
        posture=Posture.READ,
        structured_output=True,
        accepted_efforts=("low", "medium"),
        grant_policy=NativeOperatorGrantPolicyV3(
            tool_sets=((),),
            model_ids=("gpt-5.6-sol",),
            environment_names=(),
            workspace_required=False,
            network_modes=("allow",),
            network_access="native_vendor_session_only",
            tool_path="mediated_callbacks_only",
        ),
        isolation=NativeOperatorIsolationProfileV3(
            filesystem="none",
            process_tree_owned=True,
            environment_allowlisted=True,
            network_enforced=True,
            native_workspace="none",
            worker_network="none",
            credential_state="narrow_vendor_store_rw",
            zones="native_and_worker_separate",
        ),
        authentication="vendor_managed_subscription",
        account_assurance="operator_bound_vendor_identity_unverified",
        subscription_overage="forbidden",
    )


class ScriptedNative:
    """A genuine scripted byte channel; not a Codex and not a containment proof."""

    def __init__(self, *, accounts, records=(), thread=THREAD, turn=TURN, initialize=None,
                 hangs_up_after_turn=False, preamble=(), ends_after_preamble=False,
                 read_fails=None, fails_on_nth_account=None, tail=b"", early=()):
        # ``read_fails`` models a transport the adapter does not expect: an
        # exception type no layer catches, which is how a conversation aborts
        # without recording anything.
        self.read_fails = read_fails
        self.tail = tail
        self.early = list(early)
        self.reads_after_close = 0
        self.fails_on_nth_account = fails_on_nth_account
        self.armed = read_fails is not None and fails_on_nth_account is None
        self.accounts_seen = 0
        self.accounts = list(accounts)
        self.records = list(records)
        self.hangs_up_after_turn = hangs_up_after_turn
        self.thread = thread
        self.turn = turn
        self.initialize = initialize
        self.received: list[dict] = []
        self.raw_received: list[bytes] = []
        self.emitted: list[bytes] = []
        self.pending = bytearray()
        self.eof = False
        self.stdin_closed = False
        self.reading = False
        self.writing = False
        self.changed = asyncio.Event()
        for value in preamble:
            self._emit(value)
        if ends_after_preamble:
            self.eof = True

    @property
    def methods(self) -> list[str]:
        return [item.get("method") for item in self.received]

    def _emit(self, value) -> None:
        raw = value + b"\n" if isinstance(value, bytes) else (json.dumps(value) + "\n").encode()
        self.emitted.append(raw)
        self.pending.extend(raw)
        self.changed.set()

    def _respond(self, raw: bytes) -> None:
        request = json.loads(raw)
        self.received.append(request)
        identifier = request.get("id")
        method = request.get("method")
        if identifier is None:
            return
        if method == "initialize":
            self._emit({"id": identifier, **(self.initialize or {"result": {"ok": True}})})
            for value in self.early:
                self._emit(value)
        elif method == "account/read":
            self.accounts_seen += 1
            if self.accounts_seen == self.fails_on_nth_account:
                self.armed = True
                self.changed.set()
                return
            if not self.accounts:
                self.eof = True  # the child exited before answering
                self.changed.set()
                return
            self._emit({"id": identifier, **self.accounts.pop(0)})
        elif method == "thread/start":
            self._emit({"id": identifier, "result": {"thread": {"id": self.thread}}})
        elif method == "turn/start":
            self._emit({"id": identifier, "result": {"turn": {"id": self.turn}}})
            for value in self.records:
                self._emit(value)
            if self.tail:
                self.pending.extend(self.tail)  # deliberately unterminated
                self.eof = True
            if self.hangs_up_after_turn:
                self.eof = True
        else:
            self._emit({"id": identifier, "error": {"code": -32601, "message": str(method)}})

    async def write(self, data: bytes) -> None:
        if self.stdin_closed or self.writing or self.eof:
            raise ContractViolation("scripted stdin is closed or has a pending writer")
        self.writing = True
        try:
            self.raw_received.append(data)
            for line in data.split(b"\n"):
                if line:
                    self._respond(line)
        finally:
            self.writing = False

    async def read(self, maximum: int = 8192) -> bytes:
        if type(maximum) is not int or not 1 <= maximum <= 8192 or self.reading:
            raise ContractViolation("scripted read requires one reader and a bound in 1..8192")
        if self.armed and not self.pending:
            raise self.read_fails
        if self.stdin_closed:
            self.reads_after_close += 1
        self.reading = True
        try:
            while not self.pending and not self.eof:
                self.changed.clear()
                await self.changed.wait()
            value = bytes(self.pending[:maximum])
            del self.pending[:maximum]
            return value
        finally:
            self.reading = False

    async def close_stdin(self) -> None:
        self.stdin_closed = True
        self.eof = True
        self.changed.set()


@dataclass(frozen=True, kw_only=True)
class ScriptedLauncher(LinuxLauncher):
    """The pinned launcher with one scripted byte scope in place of a process.

    It records every argument it is handed, because the adapter's launch is
    otherwise unchecked: the command, the absent workspace, the posture, the
    deadline, and that each acquisition guard is a live descriptor.
    """

    native: ScriptedNative
    result: ProcessResult
    commands: list[tuple[str, ...]] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)
    raises: BaseException | None = None
    raises_after_conversation: bool = False

    async def exchange(self, command, *, workspace, posture, guard_fds, conversation, timeout_s):
        self.commands.append(command)
        self.calls.append({
            "command": command, "workspace": workspace, "posture": posture,
            "timeout_s": timeout_s, "guard_fds": guard_fds,
            # A guard the launcher cannot stat is not holding anything.
            "guard_modes": [os.fstat(fd).st_mode for fd in guard_fds],
        })
        if self.raises is not None and not self.raises_after_conversation:
            raise self.raises
        try:
            await conversation(self.native)
        except (ContractViolation, OSError, RuntimeError) as exc:
            # linux.py collects anything that escapes the callback and re-raises
            # it as ProcessExchangeError carrying the completed result, so the
            # type is lost into __cause__. AssertionError is deliberately not
            # caught: a broken test must still surface as a broken test.
            raise ProcessExchangeError(self.result) from exc
        if self.raises is not None:
            raise self.raises
        return self.result


def bare_launcher(native=None, result=None, **overrides) -> ScriptedLauncher:
    return ScriptedLauncher(
        runtime_root=Path("/opt/codex-runtime"),
        expected_runtime=digest("test-codex-runtime", 1, "runtime"),
        bubblewrap=Path("/usr/bin/bwrap"),
        policy=Path("/etc/apparmor.d/constructicon-m8-launch"),
        expected_policy_sha256="0" * 64,
        native=native if native is not None else ScriptedNative(accounts=[]),
        result=result if result is not None else FINISHED,
        **overrides,
    )


def identity_for(launcher, profile=None):
    return launch_identity(
        launcher=launcher,
        profile=profile if profile is not None else codex_profile(),
        egress=native_egress(),
        store=native_store(),
        executable_digest=digest("test-codex-executable", 1, BINARY),
        configuration=CONFIGURATION,
        catalog=(),
        authenticated_startup_conformance_revision=digest("test-codex-startup", 1, "unproven"),
        subscription_mode_conformance_revision=digest("test-codex-mode", 1, "unproven"),
    )


def provider_for(
    launcher, *, unavailable_reasons=UNQUALIFIED_PREREQUISITES, profile=None,
) -> CodexOperatorProvider:
    resolved = profile if profile is not None else codex_profile()
    return CodexOperatorProvider(
        launcher=launcher,
        profile=resolved,
        identity=identity_for(launcher, resolved),
        expected_account=EXPECTED,
        binary=BINARY,
        configuration=CONFIGURATION,
        catalog=(),
        acquisition_root=ACQUISITION_ROOT,
        unavailable_reasons=unavailable_reasons,
    )


def context(*, epoch=1, grants=GRANTS, run_id="codex-run"):
    scope = ScopePath(segments=("root", "worker"))
    return LeaseContext(
        run_lease=RunLease(
            run_id=RunId(run_id), owner_id=f"owner-{epoch}", epoch=epoch,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        ),
        binding=CapabilityBinding(
            scope=scope, binding="executor", capability_id=CAPABILITY, revision="test",
            effective_grants=grants,
        ),
        path=ExecutionPath(scope=scope),
        manifest_hash=digest("test-manifest", 1, "codex"),
    )


def descriptor_of(provider, capability_id=CAPABILITY) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id=capability_id, kind="executor", revision=provider.identity.revision,
        executor_profile=provider.identity.profile, leased=True,
    )


def conversation_for(native, *, instruction="summarize the issue") -> CodexConversation:
    return CodexConversation(
        task=TaskSpec(instruction=instruction), grants=GRANTS, expected=EXPECTED,
        input_limit=1024 * 1024,
    )


async def converse(native, **kwargs) -> CodexConversation:
    conversation = conversation_for(native, **kwargs)
    await asyncio.wait_for(conversation(native), 5)
    return conversation


def clean_native(*, accounts=None, records=None, hangs_up_after_turn=False, **overrides):
    return ScriptedNative(
        accounts=[{"result": MANAGED_RESULT}, {"result": MANAGED_RESULT}]
        if accounts is None else accounts,
        records=[completed(output={"summary": "done"}, model="gpt-5.6-sol")]
        if records is None else records,
        hangs_up_after_turn=hangs_up_after_turn,
        **overrides,
    )


# --- the published facts -----------------------------------------------------


def test_the_provider_publishes_its_prerequisites_and_refuses_to_acquire():
    provider = CodexOperatorProvider(
        launcher=bare_launcher(), profile=codex_profile(),
        identity=identity_for(bare_launcher()), expected_account=EXPECTED, binary=BINARY,
        configuration=CONFIGURATION, catalog=(),
        acquisition_root=ACQUISITION_ROOT,
    )
    assert provider.unavailable_reasons == UNQUALIFIED_PREREQUISITES
    assert any("ingress" in reason for reason in provider.unavailable_reasons)
    with pytest.raises(ContractViolation):
        asyncio.run(provider.acquire(context()))


def test_the_provider_satisfies_the_executor_provider_seam():
    assert isinstance(provider_for(bare_launcher()), ExecutorProvider)


@pytest.mark.parametrize("field_name", [
    "adapter_revision", "decoder_revision", "callback_protocol_revision",
    "configuration_digest", "callback_catalog_digest", "limits_digest",
    "isolation_revision", "runtime_digest",
])
def test_an_identity_that_drifts_from_the_actual_content_is_refused(field_name):
    launcher = bare_launcher()
    drifted = identity_for(launcher).model_copy(
        update={field_name: digest("test-codex-drift", 1, field_name)},
    )
    with pytest.raises(ContractViolation) as refused:
        CodexOperatorProvider(
            launcher=launcher, profile=codex_profile(), identity=drifted,
            expected_account=EXPECTED, binary=BINARY, configuration=CONFIGURATION, catalog=(),
            acquisition_root=ACQUISITION_ROOT, unavailable_reasons=(),
        )
    assert field_name in str(refused.value)


def test_this_slice_publishes_no_mediated_callback_catalog():
    launcher = bare_launcher()
    with pytest.raises(ContractViolation, match="mediated callback catalog"):
        CodexOperatorProvider(
            launcher=launcher, profile=codex_profile(), identity=identity_for(launcher),
            expected_account=EXPECTED, binary=BINARY, configuration=CONFIGURATION,
            catalog=("contained_python",),
            acquisition_root=ACQUISITION_ROOT, unavailable_reasons=(),
        )


def test_the_adapter_revision_follows_this_module_and_the_protocol():
    launcher = bare_launcher()
    identity = identity_for(launcher)
    assert identity.adapter_revision == ADAPTER_REVISION
    assert identity.decoder_revision == identity.callback_protocol_revision
    assert identity.profile == codex_profile()


def test_the_descriptor_matches_the_identity_and_assembly_accepts_it(journal):
    provider = provider_for(bare_launcher())
    descriptor = descriptor_of(provider)
    assert descriptor.revision == provider.identity.revision
    assert descriptor.executor_profile == provider.identity.profile
    system = Constructicon(
        journal=journal, catalog={CAPABILITY: descriptor},
        capabilities={CAPABILITY: provider}, root_grants=GRANTS,
    )
    described = system.describe().capabilities
    assert len(described) == 1 and described[0].capability_id == CAPABILITY
    # No production availability is published by this slice.
    assert described[0].available is False
    assert described[0].unavailable_reasons == UNQUALIFIED_PREREQUISITES


# --- the lease lifecycle -----------------------------------------------------


async def test_acquire_is_inert_and_materialize_enters_once():
    provider = provider_for(bare_launcher(), unavailable_reasons=())
    acquired = await provider.acquire(context())
    handle = acquired.resource
    assert isinstance(handle, CodexOperatorHandle)
    assert acquired.resource_ref == acquired.acquisition_id
    assert acquired.materialize is not None
    assert not handle.entered and not handle.ready
    await acquired.materialize()
    assert handle.entered and handle.ready
    with pytest.raises(ContractViolation):
        await acquired.materialize()


async def test_close_before_entry_writes_nothing_and_prevents_later_entry():
    launcher = bare_launcher()
    provider = provider_for(launcher, unavailable_reasons=())
    acquired = await provider.acquire(context())
    closure = await provider.close(acquired, "release")
    assert closure.disposition == "released"
    assert not launcher.commands and not launcher.native.received
    with pytest.raises(ContractViolation):
        await acquired.materialize()


async def test_close_refuses_a_handle_that_is_not_its_own():
    launcher = bare_launcher()
    provider = provider_for(launcher, unavailable_reasons=())
    other = provider_for(bare_launcher(), unavailable_reasons=())
    acquired = await provider.acquire(context())
    with pytest.raises(ContractViolation):
        await other.close(acquired, "discard")


async def test_reconciliation_refuses_a_row_that_contradicts_its_identity():
    provider = provider_for(bare_launcher(), unavailable_reasons=())
    ctx = context(epoch=2)
    acquired = await provider.acquire(ctx)
    row = CapabilityLease(
        lease_id=acquired.lease_id, acquisition_epoch=1, run_id=ctx.run_lease.run_id,
        binding_id=ctx.binding.binding, path=ctx.path, state="active",
        resource_ref=acquired.resource_ref,
    )
    stale = StaleAcquisition(lease=row, disposition="discard")
    with pytest.raises(ContractViolation):
        await provider.reconcile(ctx, (stale,))
    absent = row.model_copy(update={"acquisition_epoch": 1, "resource_ref": None})
    with pytest.raises(ContractViolation):
        await provider.reconcile(ctx, (StaleAcquisition(lease=absent, disposition="discard"),))


async def test_reconciliation_reaps_nothing_because_this_slice_owns_no_payload():
    provider = provider_for(bare_launcher(), unavailable_reasons=())
    ctx = context(epoch=3)
    older = await provider.acquire(context(epoch=1))
    row = CapabilityLease(
        lease_id=older.lease_id, acquisition_epoch=1, run_id=ctx.run_lease.run_id,
        binding_id=ctx.binding.binding, path=ctx.path, state="active",
        resource_ref=older.resource_ref,
    )
    outcome = await provider.reconcile(ctx, (StaleAcquisition(lease=row, disposition="discard"),))
    assert outcome.reaped == () and outcome.detail


async def test_grants_differing_from_the_sealed_set_are_refused():
    provider = provider_for(bare_launcher(), unavailable_reasons=())
    acquired = await provider.acquire(context())
    handle = acquired.resource
    await acquired.materialize()
    widened = GRANTS.model_copy(update={"effort": "medium"})
    with pytest.raises(ContractViolation, match="sealed grants"):
        await handle.execute(TaskSpec(instruction="x"), workspace=None, grants=widened)


async def test_an_unsupported_grant_or_task_refuses_before_any_launch():
    launcher = bare_launcher()
    provider = provider_for(launcher, unavailable_reasons=())
    unlisted = GRANTS.model_copy(
        update={"model_selection": ModelSelection(kind="explicit", model="unlisted")},
    )
    acquired = await provider.acquire(context(grants=unlisted))
    await acquired.materialize()
    outcome = await acquired.resource.execute(
        TaskSpec(instruction="x"), workspace=None, grants=unlisted,
    )
    assert outcome.status == "failure" and outcome.error.kind == "unavailable"
    assert not launcher.commands


async def test_a_response_schema_is_refused_by_this_slice():
    launcher = bare_launcher()
    provider = provider_for(launcher, unavailable_reasons=())
    acquired = await provider.acquire(context())
    await acquired.materialize()
    outcome = await acquired.resource.execute(
        TaskSpec(instruction="x", response_schema={"type": "object"}),
        workspace=None, grants=GRANTS,
    )
    assert outcome.status == "failure" and outcome.error.kind == "unavailable"
    assert not launcher.commands


async def test_execute_refuses_before_materialization():
    provider = provider_for(bare_launcher(), unavailable_reasons=())
    acquired = await provider.acquire(context())
    with pytest.raises(ContractViolation):
        await acquired.resource.execute(TaskSpec(instruction="x"), workspace=None, grants=GRANTS)


# --- the conversation --------------------------------------------------------


async def test_a_clean_conversation_reads_the_mode_twice_around_one_turn():
    native = clean_native()
    conversation = await converse(native)
    assert conversation.faults == ()
    assert native.methods == [
        "initialize", "initialized", "account/read", "thread/start", "turn/start", "account/read",
    ]
    assert conversation.observation.terminal
    outcome = decode_turn(
        conversation.observation,
        FINISHED,
        requested_model="gpt-5.6-sol",
    )
    assert outcome.status == "success" and outcome.output == {"summary": "done"}
    assert outcome.served_model == "gpt-5.6-sol"


async def test_the_initialize_bytes_never_request_the_experimental_capability():
    native = clean_native()
    await converse(native)
    assert b"experimentalApi" not in b"".join(native.raw_received)
    assert b"modelProvider" not in b"".join(native.raw_received)
    initialize = native.received[0]
    assert initialize["params"]["capabilities"] == {}


async def test_a_pre_turn_gate_fault_refuses_without_sending_a_turn():
    native = ScriptedNative(accounts=[{"result": EMPTY_RESULT}], hangs_up_after_turn=True)
    conversation = await converse(native)
    assert conversation.faults == account_faults({"result": EMPTY_RESULT}, EXPECTED)
    assert len(conversation.faults) == 2
    assert "thread/start" not in native.methods and "turn/start" not in native.methods
    assert not conversation.observation.terminal


async def test_a_pre_acceptance_gate_fault_discards_a_successful_turn():
    native = clean_native(accounts=[{"result": MANAGED_RESULT}, {"result": EMPTY_RESULT}])
    conversation = await converse(native)
    assert "turn/start" in native.methods
    assert conversation.observation.terminal  # the turn itself succeeded
    assert conversation.faults
    assert NO_ACCOUNT_FAULT in conversation.faults
    outcome = unavailable_outcome(
        conversation.faults, conversation.observation,
        FINISHED, requested_model="gpt-5.6-sol",
    )
    assert outcome.status == "failure" and outcome.error.kind == "unavailable"
    assert outcome.error.produced_output is True
    assert outcome.output is None and outcome.raw_reply is None


async def test_a_pre_acceptance_reading_that_merely_changed_discards_the_turn():
    changed = {"account": {**MANAGED, "planType": "free"}, "requiresOpenaiAuth": True}
    native = clean_native(accounts=[{"result": MANAGED_RESULT}, {"result": changed}])
    conversation = await converse(native)
    assert conversation.observation.terminal
    assert any("changed from" in fault for fault in conversation.faults)


async def test_a_missing_pre_acceptance_reply_is_a_refusal_not_a_wait():
    native = clean_native(accounts=[{"result": MANAGED_RESULT}])
    conversation = await converse(native)
    assert conversation.observation.terminal
    assert conversation.faults and any("account/read" in fault for fault in conversation.faults)


async def test_a_reply_that_does_not_correlate_with_its_request_is_refused():
    native = ScriptedNative(
        accounts=[{"result": MANAGED_RESULT}, {"result": MANAGED_RESULT}],
        records=[completed()],
        initialize={"id": 99, "result": {"ok": True}},
    )
    conversation = await converse(native)
    assert conversation.faults and any("correlate" in fault for fault in conversation.faults)
    assert "thread/start" not in native.methods


async def test_an_error_reply_to_the_first_reading_refuses():
    native = ScriptedNative(accounts=[{"error": {"code": -32603, "message": "internal"}}])
    conversation = await converse(native)
    assert conversation.faults
    assert "turn/start" not in native.methods


async def test_a_refused_initialization_ends_the_conversation():
    native = ScriptedNative(
        accounts=[{"result": MANAGED_RESULT}],
        initialize={"error": {"code": -32600, "message": "refused"}},
    )
    conversation = await converse(native)
    assert conversation.faults
    assert native.methods == ["initialize"]


async def test_an_account_email_in_the_stream_never_reaches_the_outcome():
    """E: ``account/read`` frames are stripped before any transcript is built."""
    native = clean_native()
    conversation = await converse(native)
    assert EMAIL in b"".join(native.emitted).decode()  # it really was in the stream
    assert EMAIL not in conversation.observation.raw
    outcome = decode_turn(
        conversation.observation,
        FINISHED,
        requested_model="gpt-5.6-sol",
    )
    assert EMAIL not in json.dumps(outcome.model_dump(mode="json"))


async def test_an_account_notification_mid_turn_discards_the_turn():
    """The only in-band signal for the window the two readings cannot cover."""
    native = clean_native(records=[ACCOUNT_NOTICE, completed(output={"summary": "done"})])
    conversation = await converse(native)
    assert any("account/updated" in fault for fault in conversation.faults)
    outcome = unavailable_outcome(
        conversation.faults, conversation.observation, FINISHED, requested_model="gpt-5.6-sol",
    )
    assert outcome.status == "failure" and outcome.error.kind == "unavailable"
    # The refusal is public, so it names the method and nothing from its params.
    assert EMAIL not in outcome.error.detail
    assert "chatgptAuthTokens" not in outcome.error.detail
    assert outcome.output is None and outcome.raw_reply is None
    assert EMAIL not in json.dumps(outcome.model_dump(mode="json"))
    # It never reached the transcript, so it could not have reached raw either.
    assert EMAIL not in conversation.observation.raw


@pytest.mark.parametrize("method", ["account/updated", "account/rateLimits/changed"])
async def test_any_account_method_discards_the_turn_not_just_the_documented_one(method):
    """We hold an enumeration of account *requests*, never of notifications."""
    notice = {"method": method, "params": {"account": {"email": EMAIL, "planType": "pro"}}}
    native = clean_native(records=[notice, completed(output={"summary": "done"})])
    conversation = await converse(native)
    assert any(method in fault for fault in conversation.faults)
    assert EMAIL not in conversation.observation.raw
    outcome = unavailable_outcome(
        conversation.faults, conversation.observation, FINISHED, requested_model="gpt-5.6-sol",
    )
    assert outcome.status == "failure" and outcome.error.kind == "unavailable"
    assert EMAIL not in json.dumps(outcome.model_dump(mode="json"))


async def test_an_account_notification_after_the_turn_also_discards_it():
    native = clean_native(records=[completed(output={"summary": "done"}), ACCOUNT_NOTICE])
    conversation = await converse(native)
    assert conversation.observation.terminal
    assert any("account/updated" in fault for fault in conversation.faults)
    assert EMAIL not in conversation.observation.raw


async def test_a_notification_after_the_terminal_record_is_still_the_turns_evidence():
    """The turn's stream does not stop at its terminal record.

    Transcription stays open across the pre-acceptance reading deliberately.
    What may not land there is decided by what a record *is* — id-bearing, or
    account-namespaced — never by when it arrived; a positional filter is
    exactly what let an account notification through before.
    """
    native = clean_native(records=[completed(), {"method": "turn/delta", "params": {}}])
    conversation = await converse(native)
    assert conversation.faults == ()
    assert "turn/delta" in conversation.observation.raw


async def test_a_second_terminal_record_after_the_turn_is_still_contradictory():
    """This branch is only reachable because transcription stays open."""
    native = clean_native(records=[
        completed(output={"first": True}), completed(output={"second": True}),
    ])
    conversation = await converse(native)
    assert conversation.observation.output == {"first": True}
    assert "contradictory" in (conversation.observation.first_error or "")


async def test_a_native_request_is_damage_and_is_never_answered():
    native = clean_native(records=[
        {"id": 900, "method": "item/tool/call", "params": {"tool": "shell"}},
        completed(),
    ])
    conversation = await converse(native)
    assert conversation.observation.malformed_records == 1
    assert 900 not in [item.get("id") for item in native.received]


async def test_a_turn_that_never_terminates_demotes_rather_than_refusing():
    native = clean_native(
        records=[{"method": "item/started", "params": {"threadId": THREAD}}],
        hangs_up_after_turn=True,
    )
    conversation = await converse(native)
    # The scripted child ends after its records, so the reader sees EOF.
    assert not conversation.observation.terminal
    outcome = decode_turn(
        conversation.observation,
        FINISHED,
        requested_model=None,
    )
    assert outcome.status == "partial"


async def test_a_composed_byte_scope_preamble_is_drained_and_never_transcribed():
    """A scope opened by someone else may announce itself on the same stream."""
    announcements = [{"announce": "placement"}, {"announce": "bootstrap"}]
    native = ScriptedNative(
        accounts=[{"result": MANAGED_RESULT}, {"result": MANAGED_RESULT}],
        records=[completed(output={"summary": "done"})],
        preamble=announcements,
    )
    conversation = CodexConversation(
        task=TaskSpec(instruction="x"), grants=GRANTS, expected=EXPECTED,
        input_limit=1024 * 1024, preamble=len(announcements),
    )
    await asyncio.wait_for(conversation(native), 5)
    assert conversation.faults == ()
    assert [json.loads(line) for line in conversation.preamble_records] == announcements
    assert "announce" not in conversation.observation.raw
    assert conversation.observation.terminal
    assert native.methods[0] == "initialize"


async def test_a_byte_scope_that_ends_inside_its_preamble_refuses():
    native = ScriptedNative(
        accounts=[{"result": MANAGED_RESULT}],
        preamble=[{"announce": "placement"}],
        ends_after_preamble=True,
    )
    conversation = CodexConversation(
        task=TaskSpec(instruction="x"), grants=GRANTS, expected=EXPECTED,
        input_limit=1024 * 1024, preamble=2,
    )
    await asyncio.wait_for(conversation(native), 5)
    assert any("preamble" in fault for fault in conversation.faults)
    assert native.methods == []


# --- the gate's completion is recorded, never inferred -----------------------


class Hostile:
    """A byte scope that fails in a way no layer of the adapter catches."""

    def __init__(self, failure=None):
        self.failure = failure if failure is not None else RuntimeError("transport exploded")
        self.closed = False

    async def read(self, maximum=8192):
        raise self.failure

    async def write(self, data):
        return None

    async def close_stdin(self):
        self.closed = True


def aborted_outcome(conversation):
    return unavailable_outcome(
        conversation.faults, conversation.observation, FINISHED, requested_model="gpt-5.6-sol",
    )


def test_a_conversation_refuses_a_backend_default_model_before_any_byte_moves():
    """The precondition fails at construction, not halfway through a turn."""
    backend_default = GRANTS.model_copy(
        update={"model_selection": ModelSelection(kind="backend_default")},
    )
    with pytest.raises(ContractViolation, match="sealed model"):
        CodexConversation(
            task=TaskSpec(instruction="x"), grants=backend_default, expected=EXPECTED,
            input_limit=1024 * 1024,
        )


async def test_a_clean_conversation_records_the_gate_as_completed():
    conversation = await converse(clean_native())
    assert conversation.gate_completed is True and conversation.faults == ()


async def test_a_conversation_aborted_at_its_first_read_never_looks_clean():
    """An empty fault tuple is not evidence that the gate cleared."""
    conversation = conversation_for(None)
    with pytest.raises(RuntimeError):
        await asyncio.wait_for(conversation(Hostile()), 5)
    assert conversation.gate_completed is False
    assert GATE_INCOMPLETE_FAULT in conversation.faults
    outcome = aborted_outcome(conversation)
    assert outcome.status == "failure" and outcome.error.kind == "unavailable"
    assert outcome.output is None and outcome.raw_reply is None


async def test_a_conversation_aborted_during_the_pre_acceptance_reading_refuses():
    """The turn succeeded and the second reading never landed: refuse anyway."""
    native = clean_native(read_fails=RuntimeError("transport exploded"),
                          fails_on_nth_account=2)
    conversation = conversation_for(native)
    with pytest.raises(RuntimeError):
        await asyncio.wait_for(conversation(native), 5)
    assert native.accounts_seen == 2  # the reading was sent and never answered
    assert conversation.observation.terminal  # the turn itself had succeeded
    assert conversation.gate_completed is False
    assert GATE_INCOMPLETE_FAULT in conversation.faults
    outcome = aborted_outcome(conversation)
    assert outcome.status == "failure" and outcome.error.kind == "unavailable"
    assert outcome.output is None and outcome.raw_reply is None


DEEP_RECORD = ("[" * 4000 + "]" * 4000).encode()
"""Thousands of nested arrays: far inside the record ceiling, yet the decoder
exhausts the stack on it and raises ``RecursionError``."""


async def test_a_pathological_record_is_damage_rather_than_an_escape():
    native = clean_native(records=[completed(output={"summary": "done"}), DEEP_RECORD])
    conversation = conversation_for(native)
    escaped = None
    try:
        await asyncio.wait_for(conversation(native), 5)
    except BaseException as exc:  # the point of the test is that nothing escapes
        escaped = exc
    assert escaped is None, escaped
    assert any("malformed" in fault for fault in conversation.faults)
    outcome = aborted_outcome(conversation)
    assert outcome.status == "failure" and outcome.error.kind == "unavailable"


async def test_a_pathological_record_inside_the_turn_is_counted_not_raised():
    native = clean_native(records=[DEEP_RECORD, completed(output={"summary": "done"})])
    conversation = conversation_for(native)
    escaped = None
    try:
        await asyncio.wait_for(conversation(native), 5)
    except BaseException as exc:  # the point of the test is that nothing escapes
        escaped = exc
    assert escaped is None, escaped
    assert conversation.observation.malformed_records == 1
    assert conversation.observation.first_error is not None


# --- the configured model is the one that runs --------------------------------


def two_model_profile():
    policy = codex_profile().grant_policy.model_copy(
        update={"model_ids": ("gpt-5.6-sol", "gpt-5.5")},
    )
    return codex_profile().model_copy(update={"grant_policy": policy})


def provider_with(configuration, *, profile=None, launcher=None):
    """Build the identity from the same configuration, so drift is not the fault."""
    launcher = launcher if launcher is not None else bare_launcher()
    resolved = profile if profile is not None else codex_profile()
    identity = launch_identity(
        launcher=launcher, profile=resolved, egress=native_egress(), store=native_store(),
        executable_digest=digest("test-codex-executable", 1, BINARY),
        configuration=configuration, catalog=(),
        authenticated_startup_conformance_revision=digest("test-codex-startup", 1, "unproven"),
        subscription_mode_conformance_revision=digest("test-codex-mode", 1, "unproven"),
    )
    return CodexOperatorProvider(
        launcher=launcher, profile=resolved, identity=identity, expected_account=EXPECTED,
        binary=BINARY, configuration=configuration, catalog=(),
        acquisition_root=ACQUISITION_ROOT, unavailable_reasons=(),
    )


def test_the_configuration_must_name_a_model_from_the_profiles_inventory():
    with pytest.raises(ContractViolation, match="inventory"):
        provider_with('model = "never-offered"\n')


@pytest.mark.parametrize("configuration,expected", [
    ("this is not = = toml\n", "TOML"),
    ('effort = "low"\n', "top-level model"),
    ("model = 7\n", "top-level model"),
], ids=["not-toml", "no-model", "not-a-string"])
def test_an_unusable_configuration_is_refused_at_construction(configuration, expected):
    with pytest.raises(ContractViolation, match=expected):
        provider_with(configuration)


def test_the_provider_reads_the_model_the_configuration_actually_names():
    assert provider_with(CONFIGURATION).configured_model == "gpt-5.6-sol"


async def test_a_grant_that_disagrees_with_the_configuration_is_refused():
    """The turn sends no model, so the configuration decides what runs (I4)."""
    launcher = bare_launcher(clean_native())
    provider = provider_with(CONFIGURATION, profile=two_model_profile(), launcher=launcher)
    other = GRANTS.model_copy(
        update={"model_selection": ModelSelection(kind="explicit", model="gpt-5.5")},
    )
    acquired = await provider.acquire(context(grants=other))
    await acquired.materialize()
    outcome = await acquired.resource.execute(
        TaskSpec(instruction="x"), workspace=None, grants=other,
    )
    assert outcome.status == "failure" and outcome.error.kind == "unavailable"
    assert "different model" in outcome.error.detail
    assert not launcher.commands


# --- framing damage reaches an outcome ---------------------------------------


@pytest.mark.parametrize("native_kwargs,marker", [
    ({"records": [b"x" * (RECORD_BYTES + 10)]}, "ceiling"),
    ({"records": [], "tail": b'{"method": "item/started"'}, "inside a record"),
], ids=["oversized", "mid-record-eof"])
async def test_framing_damage_reaches_the_outcome_rather_than_vanishing(native_kwargs, marker):
    native = clean_native(**native_kwargs)
    conversation = conversation_for(native)
    await asyncio.wait_for(conversation(native), 5)
    assert marker in (conversation.observation.first_error or "")
    outcome = decode_turn(conversation.observation, FINISHED, requested_model=None)
    assert outcome.status == "partial"
    assert outcome.damage.first_error == conversation.observation.first_error


async def test_a_notification_before_the_turn_is_not_the_turns_evidence():
    native = clean_native(early=[{"method": "turn/delta", "params": {"marker": "beforehand"}}])
    conversation = await converse(native)
    assert conversation.faults == ()
    assert "beforehand" not in conversation.observation.raw


async def test_the_conversation_drains_to_eof_after_closing_stdin():
    native = clean_native()
    await converse(native)
    assert native.stdin_closed and native.reads_after_close >= 1


async def test_an_instruction_too_large_to_frame_refuses_rather_than_escaping():
    native = clean_native()
    conversation = CodexConversation(
        task=TaskSpec(instruction="x" * (512 * 1024)), grants=GRANTS, expected=EXPECTED,
        input_limit=1024 * 1024,
    )
    await asyncio.wait_for(conversation(native), 5)
    assert any("cannot be framed" in fault for fault in conversation.faults)
    assert "turn/start" not in native.methods


async def test_the_conversation_stops_at_its_cumulative_input_budget():
    native = clean_native()
    conversation = CodexConversation(
        task=TaskSpec(instruction="x"), grants=GRANTS, expected=EXPECTED, input_limit=10,
    )
    await asyncio.wait_for(conversation(native), 5)
    assert conversation.faults and any("budget" in fault for fault in conversation.faults)
    assert native.methods == []


# --- the physical launch, through the real acquisition guard -----------------
#
# The guard is deliberately Linux-only and deliberately not injectable, because
# authority is physical (I1). These follow the house precedent in
# tests/substrate/test_contained_gates.py: skip off Linux, and drive a launcher
# double through the real guard rather than around it. Everything below is
# unexercised on any other platform.

LINUX = pytest.mark.skipif(
    sys.platform != "linux", reason="physical acquisition guard needs Linux",
)


async def materialized(launcher, root, *, grants=GRANTS) -> CodexOperatorHandle:
    provider = CodexOperatorProvider(
        launcher=launcher, profile=codex_profile(), identity=identity_for(launcher),
        expected_account=EXPECTED, binary=BINARY, configuration=CONFIGURATION, catalog=(),
        acquisition_root=root, unavailable_reasons=(),
    )
    acquired = await provider.acquire(context(grants=grants))
    await acquired.materialize()
    handle = acquired.resource
    assert isinstance(handle, CodexOperatorHandle)
    return handle


def assert_launch(launcher, *, grants=GRANTS):
    """Nothing else checks what the adapter actually hands the launcher."""
    assert len(launcher.calls) == 1
    call = launcher.calls[0]
    assert call["command"] == (BINARY, "app-server", "--strict-config", "--stdio")
    assert call["workspace"] is None
    assert call["posture"] is grants.posture
    assert call["timeout_s"] == grants.timeout_s
    guards = call["guard_fds"]
    assert guards and len(set(guards)) == len(guards)
    assert len(call["guard_modes"]) == len(guards)


@LINUX
async def test_execute_drives_the_contained_launcher_to_a_success(tmp_path):
    launcher = bare_launcher(clean_native())
    handle = await materialized(launcher, tmp_path)
    outcome = await handle.execute(TaskSpec(instruction="x"), workspace=None, grants=GRANTS)
    assert outcome.status == "success" and outcome.output == {"summary": "done"}
    assert outcome.served_model == "gpt-5.6-sol" and outcome.requested_model == "gpt-5.6-sol"
    assert_launch(launcher)


@LINUX
async def test_execute_discards_a_turn_whose_pre_acceptance_reading_faults(tmp_path):
    """ADR 0021's discard, in the production binding rather than in a fixture."""
    launcher = bare_launcher(
        clean_native(accounts=[{"result": MANAGED_RESULT}, {"result": EMPTY_RESULT}]),
    )
    handle = await materialized(launcher, tmp_path)
    outcome = await handle.execute(TaskSpec(instruction="x"), workspace=None, grants=GRANTS)
    assert outcome.status == "failure" and outcome.error.kind == "unavailable"
    assert NO_ACCOUNT_FAULT in outcome.error.detail
    assert outcome.error.produced_output is True
    assert outcome.output is None and outcome.raw_reply is None
    assert_launch(launcher)


@LINUX
async def test_execute_discards_a_turn_interrupted_by_an_account_notification(tmp_path):
    launcher = bare_launcher(clean_native(records=[ACCOUNT_NOTICE, completed()]))
    handle = await materialized(launcher, tmp_path)
    outcome = await handle.execute(TaskSpec(instruction="x"), workspace=None, grants=GRANTS)
    assert outcome.status == "failure" and outcome.error.kind == "unavailable"
    assert "account/updated" in outcome.error.detail
    assert EMAIL not in json.dumps(outcome.model_dump(mode="json"))


@LINUX
async def test_a_launch_prerequisite_failure_is_unavailable_and_decodes_nothing(tmp_path):
    launcher = bare_launcher(clean_native(), raises=OSError("no such runtime root"))
    handle = await materialized(launcher, tmp_path)
    outcome = await handle.execute(TaskSpec(instruction="x"), workspace=None, grants=GRANTS)
    assert outcome.status == "failure" and outcome.error.kind == "unavailable"
    assert "no such runtime root" in outcome.error.detail
    assert outcome.output is None and outcome.raw_reply is None


@LINUX
async def test_a_failed_conversation_still_decodes_the_evidence_it_carried(tmp_path):
    damaged = ProcessResult(1, b"", b"stderr evidence", 3.0, payload_returncode=1)
    launcher = bare_launcher(
        clean_native(), raises=ProcessExchangeError(damaged), raises_after_conversation=True,
    )
    handle = await materialized(launcher, tmp_path)
    outcome = await handle.execute(TaskSpec(instruction="x"), workspace=None, grants=GRANTS)
    assert outcome.status == "failure" and outcome.error.kind == "exit"
    assert outcome.error.exit_code == 1 and outcome.elapsed_s == 3.0
    # The salvage is the point: the evidence the error carried survives.
    assert outcome.output == {"summary": "done"}


@LINUX
async def test_an_aborted_conversation_refuses_rather_than_decoding_its_result(tmp_path):
    """The shape that was broken: the salvage branch reached with no gate.

    The launcher reports a clean, complete result because the conversation's own
    ``finally`` closed stdin and drained before the exception propagated. Only
    the recorded gate state distinguishes this from a turn that cleared.
    """
    aborting = clean_native(read_fails=RuntimeError("transport exploded"),
                            fails_on_nth_account=2)
    launcher = bare_launcher(aborting)
    handle = await materialized(launcher, tmp_path)
    outcome = await handle.execute(TaskSpec(instruction="x"), workspace=None, grants=GRANTS)
    assert outcome.status == "failure" and outcome.error.kind == "unavailable"
    assert GATE_INCOMPLETE_FAULT in outcome.error.detail
    assert outcome.output is None and outcome.raw_reply is None
    assert_launch(launcher)


@dataclass(frozen=True, kw_only=True)
class DriftingLauncher(ScriptedLauncher):
    """``revision`` is a property, so it can change after the provider is built."""

    drifted: list[bool] = field(default_factory=list)

    @property
    def revision(self):
        if self.drifted:
            return digest("test-codex-drift", 1, "a later recipe")
        launcher_revision = LinuxLauncher.revision
        return launcher_revision.fget(self)


@LINUX
async def test_a_launch_recipe_that_drifts_after_construction_refuses(tmp_path):
    launcher = DriftingLauncher(
        runtime_root=Path("/opt/codex-runtime"),
        expected_runtime=digest("test-codex-runtime", 1, "runtime"),
        bubblewrap=Path("/usr/bin/bwrap"),
        policy=Path("/etc/apparmor.d/constructicon-m8-launch"),
        expected_policy_sha256="0" * 64,
        native=clean_native(), result=FINISHED,
    )
    handle = await materialized(launcher, tmp_path)
    launcher.drifted.append(True)  # the recipe's own sources changed under us
    with pytest.raises(ContractViolation, match="drifted"):
        await handle.execute(TaskSpec(instruction="x"), workspace=None, grants=GRANTS)
    assert not launcher.commands


@LINUX
@pytest.mark.parametrize("cancelled", [True, False], ids=["cancelled", "plain"])
async def test_a_grouped_cleanup_failure_keeps_a_cancellation_a_cancellation(
    tmp_path, cancelled,
):
    """A cancellation inside the group is still a cancellation, not an outcome."""
    inner = asyncio.CancelledError() if cancelled else RuntimeError("cleanup failed")
    group = BaseExceptionGroup("contained process cleanup failed", [inner])
    launcher = bare_launcher(clean_native(), raises=group)
    handle = await materialized(launcher, tmp_path)
    call = handle.execute(TaskSpec(instruction="x"), workspace=None, grants=GRANTS)
    if cancelled:
        with pytest.raises(asyncio.CancelledError):
            await call
    else:
        outcome = await call
        assert outcome.status == "failure" and outcome.error.kind == "unavailable"
        assert "cleanup failed" in outcome.error.detail


@LINUX
async def test_close_cancels_an_exchange_still_in_flight(tmp_path):
    entered = asyncio.Event()

    @dataclass(frozen=True, kw_only=True)
    class Blocking(ScriptedLauncher):
        async def exchange(self, command, *, workspace, posture, guard_fds, conversation,
                           timeout_s):
            entered.set()
            await asyncio.sleep(30)
            raise AssertionError("the blocked exchange was never cancelled")

    launcher = Blocking(
        runtime_root=Path("/opt/codex-runtime"),
        expected_runtime=digest("test-codex-runtime", 1, "runtime"),
        bubblewrap=Path("/usr/bin/bwrap"),
        policy=Path("/etc/apparmor.d/constructicon-m8-launch"),
        expected_policy_sha256="0" * 64,
        native=clean_native(), result=FINISHED,
    )
    provider = CodexOperatorProvider(
        launcher=launcher, profile=codex_profile(), identity=identity_for(launcher),
        expected_account=EXPECTED, binary=BINARY, configuration=CONFIGURATION, catalog=(),
        acquisition_root=tmp_path, unavailable_reasons=(),
    )
    acquired = await provider.acquire(context())
    await acquired.materialize()
    running = asyncio.create_task(
        acquired.resource.execute(TaskSpec(instruction="x"), workspace=None, grants=GRANTS),
    )
    await asyncio.wait_for(entered.wait(), 5)
    closure = await provider.close(acquired, "discard")
    assert closure.disposition == "discarded"
    with pytest.raises(asyncio.CancelledError):
        await running
