"""The two standard human components, end to end (M7 PR C).

Each declares exactly one input and one output, asks through the narrow facade,
and holds no authority of its own. The advisor returns authorship the executor
stamped; the approval returns a trusted `ApprovalRecord` whose subject it checked
against the one it asked about. Both survive the process that asked them dying.
"""

from __future__ import annotations

import ast
from pathlib import Path

from constructicon.api.control import ControlPlane
from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.admission import AdmissionRejected
from constructicon.core.channel import ChannelEndpoint
from constructicon.core.control import (
    ADVISE_SCOPE,
    APPROVE_SCOPE,
    READ_SCOPE,
    ApprovalCommandResult,
    AuthenticatedActor,
    ChannelReplyResult,
)
from constructicon.core.effect import ComponentProofSubject
from constructicon.core.graph import Graph, GraphNode, Ref
from constructicon.core.human import (
    ADVICE_REPLY_CONTRACT,
    ADVICE_REQUEST_CONTRACT,
    APPROVAL_REPLY_CONTRACT,
    APPROVAL_REQUEST_CONTRACT,
    ApprovalRequestPayload,
)
from constructicon.core.identity import Digest, json_value
from constructicon.core.run import RunStatus
from constructicon.runtime.registry import CapabilityDescriptor, ComponentRegistry
from constructicon.sdk.std import (
    ADVISOR_CHANNEL,
    ADVISOR_COMPONENT,
    APPROVAL_CHANNEL,
    APPROVAL_COMPONENT,
    DURABLE_CHANNEL_KIND,
    definitions,
)
from constructicon.substrate.channels.mailbox import MailboxChannel
from constructicon.substrate.effects.channel import ChannelSendEffect
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import FakeClock

STD = Path(__file__).parents[2] / "src" / "constructicon" / "sdk" / "std.py"
ADVISOR_ID = "static:std-advisor"
APPROVER_ID = "static:std-approver"
ADVICE_CHANNEL_ID = "channel/std-advice"
GATE_CHANNEL_ID = "channel/std-gate"
SUBJECT = ComponentProofSubject(
    component="test/triage",
    version=Digest("sha256:" + "d" * 64),
    baseline_version=None,
)

ADVISOR = AuthenticatedActor(
    actor_id=ADVISOR_ID,
    auth_method="static",
    scopes=frozenset({READ_SCOPE, ADVISE_SCOPE}),
)
APPROVER = AuthenticatedActor(
    actor_id=APPROVER_ID,
    auth_method="static",
    scopes=frozenset({READ_SCOPE, APPROVE_SCOPE}),
)


def test_each_standard_component_declares_exactly_one_input_and_output() -> None:
    """Admission compiles the exchange from that pair, so there is nothing to pick.

    A second port would mean the request's port — and therefore its derived
    identity — was chosen at call time rather than sealed at admission.
    """

    for bundle in definitions():
        assert len(bundle.definition.inputs) == 1, bundle.name
        assert len(bundle.definition.outputs) == 1, bundle.name


def test_the_standard_ports_are_the_shared_l0_contracts() -> None:
    """Executor and component type the same exchange or they type nothing."""

    by_name = {bundle.name: bundle.definition for bundle in definitions()}
    advisor = by_name[ADVISOR_COMPONENT]
    approval = by_name[APPROVAL_COMPONENT]
    for port, contract in (
        (advisor.inputs[0], ADVICE_REQUEST_CONTRACT),
        (advisor.outputs[0], ADVICE_REPLY_CONTRACT),
        (approval.inputs[0], APPROVAL_REQUEST_CONTRACT),
        (approval.outputs[0], APPROVAL_REPLY_CONTRACT),
    ):
        assert port.type_id == contract.type_id
        assert port.schema_hash == contract.schema_hash


def test_the_standard_module_registers_nothing_at_import() -> None:
    """Importing must stay a read: restart recovery imports to *find*, not to write.

    Checked structurally rather than by observing one import, because the module
    is already imported by the time any assertion could run.
    """

    tree = ast.parse(STD.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {
                "_register",
                "_promote_initial",
                "_promote_version",
                "registry_register",
            }
    module_level_calls = [
        node
        for node in tree.body
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
    ]
    assert module_level_calls == []


def test_the_components_reach_only_the_narrow_facade() -> None:
    """No journal, no store, no transport, no identity law inside a component."""

    source = STD.read_text(encoding="utf-8")
    for forbidden in (
        "SqliteJournal",
        "MailboxChannel",
        "ControlPlane",
        "request_message_id",
        "reply_message_id",
        "channel_reply",
        "AuthenticatedActor",
        "ctx.capability",
    ):
        assert forbidden not in source, forbidden
    assert source.count(".ask(") == 2  # exactly one ask per component


def _world(journal: SqliteJournal) -> tuple[Constructicon, MailboxChannel, MailboxChannel]:
    """One system carrying both standard components and their two channels."""

    advice = MailboxChannel(journal, channel_id=ADVICE_CHANNEL_ID)
    gate = MailboxChannel(journal, channel_id=GATE_CHANNEL_ID)
    system = Constructicon(
        journal=journal,
        capabilities={ADVICE_CHANNEL_ID: advice, GATE_CHANNEL_ID: gate},
        catalog={
            ADVICE_CHANNEL_ID: CapabilityDescriptor(
                capability_id=ADVICE_CHANNEL_ID,
                kind="channel.mailbox",
                revision="1",
                channel_profile=advice.profile,
                endpoint=ChannelEndpoint(
                    lane="review",
                    interaction="advice",
                    recipient_actor_id=ADVISOR_ID,
                ),
            ),
            GATE_CHANNEL_ID: CapabilityDescriptor(
                capability_id=GATE_CHANNEL_ID,
                kind="channel.mailbox",
                revision="1",
                channel_profile=gate.profile,
                endpoint=ChannelEndpoint(
                    lane="gate",
                    interaction="approval",
                    recipient_actor_id=APPROVER_ID,
                ),
            ),
        },
        effects={
            "channel_send": ChannelSendEffect(
                journal=journal,
                catalog={
                    (ADVICE_CHANNEL_ID, "1"): advice,
                    (GATE_CHANNEL_ID, "1"): gate,
                },
            )
        },
        owner_id="std-components",
    )
    for bundle in definitions():
        version = system._register(bundle.definition, bundle.implementation)
        system._promote_initial(component=bundle.definition.name, version=version)
    return system, advice, gate


def _graph(component: str, channel_alias: str, channel_id: str, output: str) -> Graph:
    by_name = {bundle.name: bundle.definition for bundle in definitions()}
    definition = by_name[component]
    return Graph(
        name=f"one-{output}",
        nodes=(
            GraphNode(
                id="human",
                body=Ref(component=component, bind={channel_alias: channel_id}),
            ),
        ),
        connections=(),
        inputs=(definition.inputs[0],),
        outputs=(definition.outputs[0],),
    )


async def test_an_advisor_returns_authorship_the_executor_stamped(
    journal: SqliteJournal,
) -> None:
    """What the component says about *who* advised is a transport fact."""

    system, _advice, _gate = _world(journal)
    run_id = RunId("run-std-advisor")
    inputs = {"request": {"question": "does this ship?"}}
    manifest = system.validate(
        _graph(ADVISOR_COMPONENT, ADVISOR_CHANNEL, ADVICE_CHANNEL_ID, "advice"),
        inputs,
    )
    system._prepare_run(manifest, run_id=run_id, inputs=inputs)
    assert (await system._run_prepared(run_id, cancellation="abandon")).status is RunStatus.PARKED

    request = journal.parked_waits()[0].requests[0]
    control = ControlPlane(system=system, store=journal)
    replied = await control.channels_reply(
        ADVISOR,
        message_id=request,
        # The answer even names another actor. It is data, not authorship.
        payload={"verdict": "ship", "actor_id": "static:impostor"},
        idempotency_key="std-advice",
    )
    assert isinstance(replied, ChannelReplyResult)

    woken = await system._run_prepared(run_id, cancellation="abandon")
    assert woken.status is RunStatus.SUCCEEDED
    advice = system.materialize_run(run_id)["advice"]
    assert advice["actor_id"] == ADVISOR_ID
    assert advice["message_id"] == str(replied.message_id)
    assert advice["advice"] == {"verdict": "ship", "actor_id": "static:impostor"}


async def test_an_approval_returns_the_trusted_record_across_a_restart(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """The process that asked dies; a second one imports the component and finishes.

    Restart importability is the point: the registry re-imports the module named
    by the stored `PythonRef` and must find the same function it recorded.
    """

    database = tmp_path / "std.db"
    first = SqliteJournal(database, now_fn=clock.now)
    system, _advice, _gate = _world(first)
    run_id = RunId("run-std-approval")
    inputs = {
        "request": ApprovalRequestPayload(
            subject=json_value(SUBJECT.model_dump(mode="json")),
        ).model_dump(mode="json")
    }
    manifest = system.validate(
        _graph(APPROVAL_COMPONENT, APPROVAL_CHANNEL, GATE_CHANNEL_ID, "decision"),
        inputs,
    )
    system._prepare_run(manifest, run_id=run_id, inputs=inputs)
    assert (await system._run_prepared(run_id, cancellation="abandon")).status is RunStatus.PARKED
    request = first.parked_waits()[0].requests[0]

    # A second process: a fresh journal handle and a fresh system over the same
    # database, holding no memory of the first.
    second = SqliteJournal(database, now_fn=clock.now)
    restarted, _advice_two, _gate_two = _world(second)
    stored = ComponentRegistry(store=second).snapshot()
    assert stored.stable[APPROVAL_COMPONENT] is not None

    control = ControlPlane(system=restarted, store=second)
    decided = await control.runs_approve(
        APPROVER,
        run_id=run_id,
        subject=SUBJECT,
        decision="approved",
        reason="ship it",
        idempotency_key="std-approval",
        request_message_id=request,
    )
    assert isinstance(decided, ApprovalCommandResult)

    outcome = await restarted._run_prepared(run_id, cancellation="abandon")
    assert outcome.status is RunStatus.SUCCEEDED
    record = restarted.materialize_run(run_id)["decision"]["approval"]
    assert record["approval_id"] == decided.approval_id
    assert record["decision"] == "approved"
    assert record["run_id"] == str(run_id)
    assert record["actor"]["actor_id"] == APPROVER_ID
    assert record["subject"] == SUBJECT.model_dump(mode="json")


async def test_an_approval_refuses_a_record_about_another_subject(
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    """The transport proved the reply belongs here; only the request knows what it asked.

    A malformed or mismatched answer is a typed component-boundary failure and
    never becomes a successful output (I4).
    """

    system, _advice, gate = _world(journal)
    run_id = RunId("run-std-approval-mismatch")
    inputs = {
        "request": ApprovalRequestPayload(
            subject=json_value(SUBJECT.model_dump(mode="json")),
        ).model_dump(mode="json")
    }
    manifest = system.validate(
        _graph(APPROVAL_COMPONENT, APPROVAL_CHANNEL, GATE_CHANNEL_ID, "decision"),
        inputs,
    )
    system._prepare_run(manifest, run_id=run_id, inputs=inputs)
    assert (await system._run_prepared(run_id, cancellation="abandon")).status is RunStatus.PARKED
    request = journal.parked_waits()[0].requests[0]

    other = ComponentProofSubject(
        component="test/triage",
        version=Digest("sha256:" + "e" * 64),
        baseline_version=None,
    )
    # Written straight to the transport, bypassing the control plane's own
    # subject check, so the component's is the only thing standing here.
    gate.reply(
        request_id=request,
        actor_id=APPROVER_ID,
        payload={
            "schema_version": 1,
            "approval": {
                "approval_id": "approval-elsewhere",
                "subject": other.model_dump(mode="json"),
                "decision": "approved",
                "reason": None,
                "actor": APPROVER.model_dump(mode="json"),
                "run_id": str(run_id),
                "created_at": clock.now().isoformat(),
            },
        },
        command_id="cmd-std-mismatch",
    )

    outcome = await system._run_prepared(run_id, cancellation="abandon")
    assert outcome.status is RunStatus.FAILED
    failures = [
        str(event.payload.get("error", ""))
        for event in journal.events(run_id, after_seq=0, limit=200)
        if event.kind == "NodeFailed" and event.payload
    ]
    assert any("did not ask about" in failure for failure in failures), failures


async def test_a_malformed_advice_reply_never_becomes_a_successful_output(
    journal: SqliteJournal,
) -> None:
    """The component types its own boundary (I4).

    `channels_reply` stamps every canonical advice answer, so a payload that is
    not one can only arrive by writing straight to the transport. It still must
    not pass: a component validates what it returns.
    """

    system, advice, _gate = _world(journal)
    run_id = RunId("run-std-advisor-malformed")
    inputs = {"request": {"question": "does this ship?"}}
    manifest = system.validate(
        _graph(ADVISOR_COMPONENT, ADVISOR_CHANNEL, ADVICE_CHANNEL_ID, "advice"),
        inputs,
    )
    system._prepare_run(manifest, run_id=run_id, inputs=inputs)
    assert (await system._run_prepared(run_id, cancellation="abandon")).status is RunStatus.PARKED
    request = journal.parked_waits()[0].requests[0]

    advice.reply(
        request_id=request,
        actor_id=ADVISOR_ID,
        payload={"verdict": "ship"},  # no authorship: not an AdviceReplyPayload
        command_id="cmd-std-malformed",
    )

    outcome = await system._run_prepared(run_id, cancellation="abandon")
    assert outcome.status is RunStatus.FAILED


def test_each_standard_component_declares_the_capability_it_may_hold() -> None:
    """`capability_requirements=None` means capability-opaque, not authority-free.

    Omitting it is the historical shape, and admission then validates no alias,
    no kind, and no extra binding — so a graph could hand a component any
    capability it liked. A component introduced today declares what it needs and
    thereby refuses everything else (I3). The kind names the durable transport:
    a human waits across process death.
    """

    for bundle in definitions():
        required = bundle.definition.capability_requirements
        assert required is not None, bundle.name
        assert len(required) == 1, bundle.name
        assert required[0].kind == DURABLE_CHANNEL_KIND, bundle.name

    aliases = {}
    for bundle in definitions():
        declared = bundle.definition.capability_requirements
        assert declared is not None
        aliases[bundle.name] = declared[0].alias
    assert aliases[ADVISOR_COMPONENT] == ADVISOR_CHANNEL
    assert aliases[APPROVAL_COMPONENT] == APPROVAL_CHANNEL


def test_a_graph_may_not_bind_an_undeclared_capability(journal: SqliteJournal) -> None:
    """The declaration is what makes an extra binding refusable at admission."""

    system, _advice, _gate = _world(journal)
    definition = {b.name: b.definition for b in definitions()}[ADVISOR_COMPONENT]
    smuggled = Graph(
        name="smuggle",
        nodes=(
            GraphNode(
                id="human",
                body=Ref(
                    component=ADVISOR_COMPONENT,
                    bind={ADVISOR_CHANNEL: ADVICE_CHANNEL_ID, "extra": GATE_CHANNEL_ID},
                ),
            ),
        ),
        connections=(),
        inputs=(definition.inputs[0],),
        outputs=(definition.outputs[0],),
    )
    outcome = system.admit_graph(smuggled, {"request": {"question": "?"}})
    assert isinstance(outcome, AdmissionRejected)
    assert any("does not declare capability alias" in f.message for f in outcome.faults)


async def test_an_approval_refuses_a_record_about_another_run(
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    """The reply belongs to this run; the record inside it must say so too."""

    system, _advice, gate = _world(journal)
    run_id = RunId("run-std-approval-other-run")
    inputs = {
        "request": ApprovalRequestPayload(
            subject=json_value(SUBJECT.model_dump(mode="json")),
        ).model_dump(mode="json")
    }
    manifest = system.validate(
        _graph(APPROVAL_COMPONENT, APPROVAL_CHANNEL, GATE_CHANNEL_ID, "decision"),
        inputs,
    )
    system._prepare_run(manifest, run_id=run_id, inputs=inputs)
    assert (await system._run_prepared(run_id, cancellation="abandon")).status is RunStatus.PARKED
    request = journal.parked_waits()[0].requests[0]

    gate.reply(
        request_id=request,
        actor_id=APPROVER_ID,
        payload={
            "schema_version": 1,
            "approval": {
                "approval_id": "approval-other-run",
                "subject": SUBJECT.model_dump(mode="json"),
                "decision": "approved",
                "reason": None,
                "actor": APPROVER.model_dump(mode="json"),
                "run_id": "run-somewhere-else",
                "created_at": clock.now().isoformat(),
            },
        },
        command_id="cmd-std-other-run",
    )

    outcome = await system._run_prepared(run_id, cancellation="abandon")
    assert outcome.status is RunStatus.FAILED
    failures = [
        str(event.payload.get("error", ""))
        for event in journal.events(run_id, after_seq=0, limit=200)
        if event.kind == "NodeFailed" and event.payload
    ]
    assert any("run-std-approval-other-run" in failure for failure in failures), failures


async def test_admission_refuses_an_approval_component_on_an_advice_endpoint(
    journal: SqliteJournal,
) -> None:
    """The escalation, refused where both facts are visible.

    `human-approval` typed by the approval contracts, bound to a channel whose
    endpoint seals `interaction="advice"`. Nothing downstream could catch this:
    `channels_reply` would consume it as advice, store the advisor's payload
    verbatim, and the component would return it as a trusted `ApprovalRecord`.
    """

    system, _advice, _gate = _world(journal)
    smuggled = _graph(APPROVAL_COMPONENT, APPROVAL_CHANNEL, ADVICE_CHANNEL_ID, "decision")
    inputs = {
        "request": ApprovalRequestPayload(
            subject=json_value(SUBJECT.model_dump(mode="json")),
        ).model_dump(mode="json")
    }
    outcome = system.admit_graph(smuggled, inputs)
    assert isinstance(outcome, AdmissionRejected)
    assert any("interaction='approval'" in fault.message for fault in outcome.faults)


async def test_admission_refuses_an_advice_component_on_an_approval_endpoint(
    journal: SqliteJournal,
) -> None:
    """The mirror, which would park a run with nothing able to answer it."""

    system, _advice, _gate = _world(journal)
    smuggled = _graph(ADVISOR_COMPONENT, ADVISOR_CHANNEL, GATE_CHANNEL_ID, "advice")
    outcome = system.admit_graph(smuggled, {"request": {"question": "?"}})
    assert isinstance(outcome, AdmissionRejected)
    assert any("interaction='advice'" in fault.message for fault in outcome.faults)
