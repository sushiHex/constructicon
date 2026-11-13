"""Model-shaped replies to the channel stored-reply task, and where each one ends (#407).

Every maintenance rehearsal feeds the one correct program. These cases feed what
a model plausibly sends instead (a read and nothing more, an edit that matches
nothing, a call that raises, a stray file) and pin the result: accepted, or the
refusal name the diagnostic packet reports.

What is real, by tier. Each case asserts which worker launcher it used.

- ``portable``: the real adapter (``CodexOperatorProvider`` mediating every
  callback, with its ceilings), entry, Graph, journal, Git capture and the gate's
  exact-extraction exam. The worker is a plain subprocess of this interpreter in
  the checked-out workspace (``PortableProcessLauncher``): no Linux isolation and
  no ``/workspace``. Its base holds the real target and one other blob, so it has
  no ``.gitignore``.
- ``contained``: the same, with the worker, capture and gate launched through the
  provisioned ``LinuxLauncher`` over the full committed tree. It runs only in the
  provisioned lane and is skipped elsewhere.

Never real in either tier: the vendor binary and the model. The native peer is a
scripted byte channel, so a case says what the system does with a reply, never
whether a model sends it. The placement lane's fake provider
(``tests/native_provider.py``) scripts at most one tool call, and that lane
answers the call with fixed text, with no worker, capture or gate behind it; it
cannot carry these cases.

Who answers is the model seat's occupant (``tests/model_seat.py``): ``hostile``
for the cases, ``replay`` for the same turns as records. Each world's ``Realness``
is asserted whole, so a case proves which implementations it selected.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from dataclasses import fields, replace
from pathlib import Path

import pytest

from constructicon.api import maintenance_entry as entry
from constructicon.api.plan_manifest_application import (
    CHANNEL_STORED_REPLY,
    MaintenanceResources,
    channel_reply_checks,
)
from constructicon.core.grants import Posture
from constructicon.core.maintenance import (
    CHANNEL_TARGET_PATH,
    ChannelReplyRequest,
    ChannelReplyResult,
)
from constructicon.core.qualification_write import CallbackObservation
from constructicon.substrate.executors.attempt_turn import turn_path
from constructicon.substrate.executors.codex_protocol import MAX_TOOL_CALLS, TOOL_OUTPUT_BYTES
from constructicon.substrate.executors.linux import LinuxLauncher
from constructicon.substrate.gates.channel_reply import (
    HELPER_SOURCE,
    ExtractionRefusal,
    check_extraction,
)
from constructicon.substrate.git.capture import ContainedWriteWorkspaceProvider
from constructicon.substrate.journal import maintenance_diagnostic, maintenance_evidence
from constructicon.substrate.journal.maintenance_diagnostic import _FAILURES
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.api import test_plan_manifest_application as application_tests
from tests.api.test_plan_manifest_application import PortableProcessLauncher
from tests.maintenance_instructions import CHANNEL_INSTRUCTION, CHANNEL_PURPOSE, pinned
from tests.maintenance_task_world import (
    committed_tree_base,
    configure_executor_guard,
    scripted_task_executor,
)
from tests.model_seat import (
    RECORD_VERSION,
    Call,
    Realness,
    ReplayDiverged,
    Seated,
    Seen,
    Turn,
    hostile,
    live,
    replay,
)
from tests.operator_store_world import StoreWorld
from tests.substrate.test_channel_reply_oracle import BASE
from tests.substrate.test_codex_adapter import descriptor_of
from tests.substrate.test_codex_adapter import portable_binding as portable_binding
from tests.substrate.test_codex_protocol import completed
from tests.substrate.test_contained_gates import MaintenanceNativeLauncher, qualify, unqualified
from tests.substrate.test_linux_containment import launcher as launcher
from tests.substrate.test_native_codex_mediation import write_evidence

concrete_application = application_tests.concrete_application
CHANNEL = pytest.mark.parametrize("concrete_application", ["channel-stored-reply"],
                                  indirect=True)

# The helper as the instruction spells it: the oracle's source, indented once.
HELPER = "".join("    " + line if line.strip() else line
                 for line in HELPER_SOURCE.splitlines(True))
DOCSTRING_HELPER = HELPER.replace(
    ") -> ChannelMessage | None:\n",
    ') -> ChannelMessage | None:\n        """Return the stored reply for a request."""\n', 1)
# The three statements in ``reply_for`` and in ``acknowledge``, as the base has them.
OLD_REPLY_FOR = (
    "            if request.reply_port is None:\n"
    '                raise JournalDamaged(f"channel request {request_id} pins no reply port")\n'
    "            reply_id = reply_message_id(\n"
    "                request_id=request.message_id,\n"
    "                reply_port=request.reply_port,\n"
    "            )\n"
    "            stored = self._by_id.get(str(reply_id))\n"
)
NEW_REPLY_FOR = "            stored = self._stored_reply(request, request_id)\n"
OLD_ACKNOWLEDGE = (
    "                if request.reply_port is None:\n"
    "                    raise JournalDamaged(\n"
    '                        f"channel request {message_id} pins no reply port"\n'
    "                    )\n"
    "                reply_id = reply_message_id(\n"
    "                    request_id=request.message_id,\n"
    "                    reply_port=request.reply_port,\n"
    "                )\n"
    "                reply = self._by_id.get(str(reply_id))\n"
)
NEW_ACKNOWLEDGE = "                reply = self._stored_reply(request, message_id)\n"
LAST_METHOD_END = "        return self._complete_reply(request, message)\n"
NEXT_FUNCTION = "\n\ndef _detached_message("
# The look-alike lookup in ``reply``, which the task leaves alone.
REPLY_LOOKUP = (
    "            stored = self._by_id.get(str(reply_id))\n"
    "            if stored is not None:\n"
)
REPLY_LOOKUP_REWRITTEN = (
    "            stored = self._stored_reply(request, request_id)\n"
    "            if stored is not None:\n"
)


def dedented(text: str) -> str:
    """The same statements one level shallower: a model's misremembered indentation."""
    return "".join(line[4:] if line.startswith("    ") else line
                   for line in text.splitlines(True))


def edit_program(*, path=CHANNEL_TARGET_PATH, helper=HELPER, checked=True, acknowledge=True,
                 also_reply=False, misremembered=False, after="") -> str:
    """A read-then-replace edit as a model would write it; ``after`` runs once it wrote."""
    reply_for, acknowledged, following = OLD_REPLY_FOR, OLD_ACKNOWLEDGE, NEXT_FUNCTION
    if misremembered:
        # One level shallower, and one blank line where the file has two.
        reply_for, acknowledged = dedented(reply_for), dedented(acknowledged)
        following = following[1:]
    lines = [
        "from pathlib import Path",
        f"p = Path({path!r})",
        "s = p.read_bytes().decode()",
        "original = s",
        f"reply_for = {reply_for!r}",
        f"acknowledge = {acknowledged!r}",
        f"anchor = {LAST_METHOD_END + following!r}",
    ]
    if checked:
        lines.append("assert s.count(reply_for) == 1 and s.count(anchor) == 1")
    lines.append(f"s = s.replace(reply_for, {NEW_REPLY_FOR!r})")
    if acknowledge:
        if checked:
            lines.append("assert s.count(acknowledge) == 1")
        lines.append(f"s = s.replace(acknowledge, {NEW_ACKNOWLEDGE!r})")
    if also_reply:
        lines.append(f"s = s.replace({REPLY_LOOKUP!r}, {REPLY_LOOKUP_REWRITTEN!r})")
    lines += [
        f"s = s.replace(anchor, {LAST_METHOD_END + chr(10)!r} + {helper!r} + {NEXT_FUNCTION!r})",
        "p.write_bytes(s.encode())",
        *after.splitlines(),
        "print('wrote', p.name, b'_stored_reply' in p.read_bytes())",
    ]
    return "\n".join(lines) + "\n"


READ = f"print(open({CHANNEL_TARGET_PATH!r}).read())\n"
PEEK = f"print(len(open({CHANNEL_TARGET_PATH!r}).read()))\n"
WRONG_PATH = "print(open('src/constructicon/channels/in_process.py').read())\n"
HEX_DUMP = f"print(open({CHANNEL_TARGET_PATH!r}, 'rb').read().hex())\n"
EDIT = edit_program()
WHERE = (
    "import os, shutil, sys\n"
    "print(os.getcwd())\n"
    f"print(os.path.isfile({CHANNEL_TARGET_PATH!r}))\n"
    "print(sys.version_info[:2], os.path.exists('.git'), shutil.which('git'))\n"
)
ACCEPTED = "accepted"


def rewrite(seen: tuple[str, ...]) -> str:
    """The whole target written back from the text the previous call printed."""
    # What the peer saw: print's trailing newline, and CRLF from a Windows text pipe.
    text = seen[-1].replace("\r\n", "\n")[:-1]
    for old, new in ((OLD_REPLY_FOR, NEW_REPLY_FOR), (OLD_ACKNOWLEDGE, NEW_ACKNOWLEDGE),
                     (LAST_METHOD_END + NEXT_FUNCTION,
                      LAST_METHOD_END + "\n" + HELPER + NEXT_FUNCTION)):
        text = text.replace(old, new)
    return ("from pathlib import Path\n"
            f"Path({CHANNEL_TARGET_PATH!r}).write_bytes({text.encode()!r})\n"
            "print('rewrote')\n")


def case(programs, outcome, *, node=None, started=None, completed=None, workers=None,
         seen=None):
    """Expected facts; the callback counts default to every program completing."""
    count = len(programs)
    return programs, {
        "outcome": outcome, "node": node,
        "started": count if started is None else started,
        "completed": count if completed is None else completed,
        "workers": ["success"] * count if workers is None else workers,
        "seen": count if seen is None else seen,
    }


# Cases that mean the same in both tiers. ``seen`` is how many callback outputs
# were returned to the peer, which is all a model would ever see of a call.
SHARED = {
    # No tool call at all: the turn succeeds and nothing was written.
    "text-only": case([], "capture-unchanged", node="writer"),
    # The generation-18 shape: one successful callback, then the turn ends.
    "read-then-end": case([READ], "capture-unchanged", node="writer"),
    # The natural two steps. The first prints the whole target.
    "read-then-edit": case([READ, EDIT], ACCEPTED),
    # The second program is computed from the first output, as a model's is: a
    # wrong or missing output would write a wrong file.
    "rewrite-from-what-it-read": case([READ, rewrite], ACCEPTED),
    # A replace that matches nothing and no assert: a silent rewrite of the same bytes.
    "edit-matches-nothing": case([READ, edit_program(checked=False, misremembered=True)],
                                 "capture-unchanged", node="writer"),
    # One uncaught exception ends the attempt; the peer is sent no output for it.
    "call-raises": case([WRONG_PATH], "writer-not-positive", node="writer",
                        completed=0, workers=["nonzero"], seen=0),
    # A correct write does not survive a later call that raises.
    "edit-then-raise": case([EDIT, WRONG_PATH], "writer-not-positive", node="writer",
                            completed=1, workers=["success", "nonzero"], seen=1),
    # 43,520 hex characters: the worker succeeds, the adapter refuses the output.
    "output-over-bound": case([HEX_DUMP], "writer-not-positive", node="writer",
                              completed=0, workers=["success"], seen=0),
    # The ninth call is never admitted, and the eight completed ones are discarded.
    "nine-calls": case([PEEK] * (MAX_TOOL_CALLS + 1), "writer-not-positive", node="writer",
                       started=MAX_TOOL_CALLS, completed=MAX_TOOL_CALLS,
                       workers=["success"] * MAX_TOOL_CALLS, seen=MAX_TOOL_CALLS),
    "edit-plus-backup": case(
        [READ, edit_program(after="Path(str(p) + '.bak').write_bytes(original.encode())")],
        "gate-not-positive", node="checker"),
    "helper-docstring": case([READ, edit_program(helper=DOCSTRING_HELPER)],
                             "gate-not-positive", node="checker"),
    "reply-also-rewritten": case([READ, edit_program(also_reply=True)],
                                 "gate-not-positive", node="checker"),
    "one-caller-only": case([READ, edit_program(acknowledge=False)],
                            "gate-not-positive", node="checker"),
}
COMPILE = edit_program(after="import py_compile\npy_compile.compile(str(p), doraise=True)")
# The portable tier runs every shared case. The contained tier repeats the ones
# whose answer depends on the real worker, bound or tree, and adds four that mean
# nothing without them (a portable base has no /workspace and no .gitignore, and
# this interpreter can import the project).
CONTAINED = {
    name: SHARED[name] for name in (
        "read-then-end", "read-then-edit", "rewrite-from-what-it-read", "call-raises",
        "output-over-bound", "edit-plus-backup",
    )
} | {
    # Where a call runs, as the worker itself reports it.
    "where-am-i": case([WHERE], "capture-unchanged", node="writer"),
    # The absolute spelling of the bound root.
    "edit-by-workspace-path": case(
        [READ, edit_program(path="/workspace/" + CHANNEL_TARGET_PATH)], ACCEPTED),
    # The full tree ignores __pycache__/, so the compiled file is not captured.
    "edit-plus-py-compile": case([READ, COMPILE], ACCEPTED),
    # The worker's interpreter is isolated: the project is not importable.
    "imports-the-project": case(["import constructicon\nprint(constructicon.__file__)\n"],
                                "writer-not-positive", node="writer",
                                completed=0, workers=["nonzero"], seen=0),
}


def said(text: str) -> Seen:
    """A callback output as this platform's pipe delivers it to the peer."""
    return Seen.of(text.replace("\n", os.linesep))


WHOLE = said(BASE.decode() + "\n")
WROTE = said(f"wrote {Path(CHANNEL_TARGET_PATH).name} True\n")
# Hostile cases as recorded turns: version 1 of the record a live attempt would
# fill. The hostile runs below assert these are what their seats saw.
RECORDED = {
    "read-then-end": Turn((Call(READ, WHOLE),), True, "done"),
    "read-then-edit": Turn((Call(READ, WHOLE), Call(EDIT, WROTE)), True, "done"),
    # The failing call returned nothing, and the turn never replied.
    "edit-then-raise": Turn((Call(EDIT, WROTE), Call(WRONG_PATH, None)), False, None),
}
# Records the system no longer reproduces: the reason, and where the run ends.
DIVERGED = {
    # Recorded over another file. The first output differs, so the edit is never sent.
    "another-base": (
        Turn((Call(READ, Seen.of("another file\n")), Call(EDIT, WROTE)), True, "done"),
        "call 1: recorded Seen", case([READ], "capture-unchanged", node="writer")[1]),
    # Recorded as seen, but the adapter refuses this output: nothing comes back.
    "output-now-refused": (
        Turn((Call(HEX_DUMP, Seen.of("recorded")), Call(EDIT, WROTE)), True, "done"),
        "call 1: recorded an output, none was returned",
        SHARED["output-over-bound"][1]),
}
PORTABLE = Realness(model="hostile", worker=PortableProcessLauncher, contained=False,
                    store_world=StoreWorld, identity="fixture")
PHYSICAL = replace(PORTABLE, worker=MaintenanceNativeLauncher, contained=True)


def sent_as_written(seat: Seated, programs) -> bool:
    """Every literal program reached the wire as its case wrote it, in order."""
    return len(seat.sent) <= len(programs) and all(
        sent == step for sent, step in zip(seat.sent, programs, strict=False)
        if isinstance(step, str))


def seated(programs) -> Seated:
    """The hostile occupant; with no call at all it still says why."""
    return hostile(programs) if programs else hostile(
        (), reply="The file is read-only, so I changed nothing.")


async def attempt(resources, launch, binding, tmp_path, monkeypatch, seat: Seated):
    """One entry run against the seated reply; the facts a packet would carry."""
    resources, executor, scripted, _configuration, authorization = await scripted_task_executor(
        resources, launch, binding, tmp_path, seat, task=CHANNEL_STORED_REPLY)
    native = scripted.native
    assert native is seat and authorization.purpose == "channel-stored-reply"
    configure_executor_guard(monkeypatch)
    result = await entry.run_maintenance(resources=resources, executor=executor,
        executor_descriptor=descriptor_of(executor, "executor"), authorization=authorization)
    journal, run_id, request = resources.journal, authorization.run_id, resources.request
    # The instruction the peer was sent is the committed file's text, which the request
    # pins by digest; it is read from the repository and never restated here.
    assert request.instruction_sha256 == hashlib.sha256(
        CHANNEL_INSTRUCTION.encode()).hexdigest()
    turn, = (item for item in native.received if item.get("method") == "turn/start")
    assert [item["text"] for item in turn["params"]["input"]] == [CHANNEL_INSTRUCTION]
    failures = [event for event in journal.events(run_id, limit=100)
                if event.kind == "NodeFailed"]
    if result is None:
        failure, = failures
        assert failure.payload["error_type"] == "ContractViolation", failure.payload
        outcome, node = _FAILURES[failure.payload["error"]], failure.path.scope.segments[-1]
        assert not (Path(authorization.journal).parent / "maintenance-result.json").exists()
    else:
        assert isinstance(result, ChannelReplyResult) and result.evaluation.ok and not failures
        assert resources.authority.parents_of(result.candidate.commit) == (request.base_commit,)
        outcome, node = ACCEPTED, None
    assert resources.authority.resolve_ref(request.target_ref) == request.base_commit
    record = json.loads(Path(authorization.attempt_record).read_bytes())
    callbacks = record["callbacks"]
    # Which worker ran: every admitted program reached this launcher, in order.
    workers = [kwargs for _command, kwargs in launch.calls if kwargs.get("input_kind") == "task"]
    assert [kwargs["stdin"].decode() for kwargs in workers] == seat.sent[:len(workers)]
    assert len(workers) == callbacks["admitted_started"]
    assert all(kwargs["posture"] is Posture.WRITE for kwargs in workers)
    assert all(response["result"]["success"] is True for response in seat.callback_responses)
    assert len(seat.seen) == len(seat.callback_responses)
    # The retained fingerprints are of exactly these bytes: each program as the
    # worker received it, and each output the peer was handed. They are what
    # tells a read and nothing more from a rewrite of the same bytes, which end
    # in the same refusal. No text is retained beside them.
    content = record["facts"]["content_digests"]
    assert maintenance_diagnostic._content_digests(
        record["facts"], CallbackObservation.model_validate(callbacks)) == content
    assert [item["program"] for item in content["callbacks"]] == [
        by_digest(kwargs["stdin"]) for kwargs in workers]
    for index, text in enumerate(seat.seen):
        assert content["callbacks"][index]["output"] == by_digest(text.encode())
    assert [item["output"] is None for item in content["callbacks"]] == [
        category is None for category in callbacks["worker_results"]]
    text = Path(authorization.attempt_record).read_text(encoding="utf-8")
    assert not any(program.strip() and program in text for program in seat.sent)
    seat.kept = kept_turn(Path(authorization.attempt_record), seat, len(workers), content)
    return {
        "outcome": outcome, "node": node, "started": callbacks["admitted_started"],
        "completed": callbacks["admitted_completed"],
        "workers": callbacks["worker_results"], "seen": len(seat.seen),
    }, scripted.realness, content


def by_digest(raw: bytes) -> dict[str, object]:
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def kept_turn(attempt_record: Path, seat: Seated, launched: int, content) -> Turn:
    """The turn the attempt kept on disk: the seat's own record, in one private file.

    It is what the peer sent and saw, less any call that never reached the
    launcher, in the record's canonical bytes. Its text is in that file and in
    no other file of the private root.
    """
    path = turn_path(attempt_record)
    raw = path.read_bytes()
    turn = Turn.from_json(raw.decode())
    assert turn.to_json().encode() == raw
    said = seat.recording()
    assert turn == Turn(said.calls[:launched], said.completed, said.reply)
    # The digest block indexes the file: the same programs, by fingerprint.
    assert [by_digest(call.program.encode()) for call in turn.calls] == [
        item["program"] for item in content["callbacks"]]
    if turn.completed:
        assert content["reply"] == (
            None if turn.reply is None else by_digest(turn.reply.encode()))
    # Structural: the capture's fixed names cannot carry it, nothing was left
    # beside it, and no other file in the private root holds its text.
    assert path.parent == attempt_record.parent
    assert not {path.name, path.name + ".next"} & set(maintenance_evidence.FILES)
    assert not path.with_name(path.name + ".next").exists()
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    texts = [text.encode() for text in (*(call.program for call in turn.calls), turn.reply)
             if text and text.strip()]
    for other in path.parent.iterdir():
        if other.is_file() and other != path:
            held = other.read_bytes()
            assert not any(text in held for text in texts), other.name
    return turn


def retain(tier, name, observed, seat, **extra):
    write_evidence(f"codex-maintenance-{seat.occupant}-{tier}-{name}.json", {
        "issue": 407, "tier": tier, "case": name, "model": seat.occupant, **observed,
        "seen_bytes": [len(text.encode()) for text in seat.seen],
        "instruction_sha256": hashlib.sha256(CHANNEL_INSTRUCTION.encode()).hexdigest(),
        **extra,
    })


def run_in(root: Path, program: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I"], input=program.encode(), cwd=root,
                          capture_output=True, timeout=60, check=False)


def test_the_scripted_edits_are_what_their_cases_claim(tmp_path):
    """The programs themselves, outside any entry: one is the extraction, the rest are not."""
    target = tmp_path / CHANNEL_TARGET_PATH
    target.parent.mkdir(parents=True)

    def candidate(program):
        target.write_bytes(BASE)
        done = run_in(tmp_path, program)
        assert done.returncode == 0, done.stderr.decode()
        return target.read_bytes()

    assert BASE.decode().count(OLD_REPLY_FOR) == BASE.decode().count(OLD_ACKNOWLEDGE) == 1
    assert BASE.decode().count(REPLY_LOOKUP) == 1
    assert check_extraction(BASE, candidate(EDIT))["passed"] is True
    assert candidate(rewrite((BASE.decode() + "\n",))) == candidate(EDIT)
    assert candidate(rewrite(("another file\n",))) != candidate(EDIT)
    for program in (edit_program(helper=DOCSTRING_HELPER), edit_program(also_reply=True),
                    edit_program(acknowledge=False)):
        with pytest.raises(ExtractionRefusal) as refused:
            check_extraction(BASE, candidate(program))
        assert refused.value.code == "candidate-differs"
    assert candidate(edit_program(checked=False, misremembered=True)) == BASE
    # The whole target fits one callback output; its hex dump does not.
    assert len(BASE) + 1 <= TOOL_OUTPUT_BYTES < 2 * len(BASE)
    assert run_in(tmp_path, WRONG_PATH).returncode != 0


@CHANNEL
@pytest.mark.parametrize("name", sorted(SHARED))
async def test_a_model_shaped_reply_ends_where_the_packet_says(
    concrete_application, portable_binding, tmp_path, monkeypatch, name,
):
    resources, _executor, _system, control, launch = concrete_application
    await control.shutdown()
    programs, expected = SHARED[name]
    seat = seated(programs)
    observed, realness, content = await attempt(resources, launch, portable_binding, tmp_path,
                                                monkeypatch, seat)
    retain("portable", name, observed, seat, content_digests=content)
    assert realness == PORTABLE and realness.worker is type(launch)
    assert sent_as_written(seat, programs)
    assert observed == expected, observed
    if name in RECORDED:
        assert seat.recording() == RECORDED[name]
        # The file the adapter kept is that record, byte for byte (``kept_turn``
        # checked its canonical form). It is therefore exactly what
        # ``test_a_recorded_turn_replays_to_the_end_it_was_recorded_at`` replays.
        assert seat.kept == RECORDED[name]
    if name == "read-then-end":
        # The peer was handed the whole target, as a model's first step expects.
        assert seat.seen[0].replace("\r\n", "\n") == BASE.decode() + "\n"


def test_a_recorded_turn_keeps_its_exact_form_and_the_live_seat_stays_empty():
    turn = RECORDED["edit-then-raise"]
    record = json.loads(turn.to_json())
    assert set(record) == {"version", "calls", "completed", "reply"}
    assert record["version"] == RECORD_VERSION and record["completed"] is False
    assert record["reply"] is None and record["calls"][1] == {"program": WRONG_PATH, "seen": None}
    assert set(record["calls"][0]["seen"]) == {"sha256", "bytes"}
    assert Turn.from_json(turn.to_json()) == turn
    for damaged in ({**record, "version": RECORD_VERSION + 1}, {**record, "output": "text"},
                    {**record, "completed": 0}, {**record, "reply": "said after no completion"},
                    {**record, "calls": record["calls"][::-1]}):
        with pytest.raises(ValueError):
            Turn.from_json(json.dumps(damaged))
    with pytest.raises(ValueError, match="sent nothing"):
        replay(Turn((), False, None))
    # A seat records what its peer emitted, and before the turn that is nothing.
    assert hostile([READ]).recording() == Turn((), False, None)
    # A turn may complete without a message; that is not a turn that never completed.
    wordless = replay(Turn((), True, None))
    assert wordless.records == [completed(answer=None)]
    with pytest.raises(NotImplementedError, match="owner-approved window"):
        live()


@CHANNEL
@pytest.mark.parametrize("name", sorted(RECORDED))
async def test_a_recorded_turn_replays_to_the_end_it_was_recorded_at(
    concrete_application, portable_binding, tmp_path, monkeypatch, name,
):
    resources, _executor, _system, control, launch = concrete_application
    await control.shutdown()
    turn = Turn.from_json(RECORDED[name].to_json())
    seat = replay(turn)
    observed, realness, content = await attempt(resources, launch, portable_binding, tmp_path,
                                                monkeypatch, seat)
    retain("portable", name, observed, seat, content_digests=content)
    seat.settle()
    assert seat.recording() == turn and realness == replace(PORTABLE, model="replay")
    assert observed == SHARED[name][1], observed
    # A replayed attempt keeps the turn it replayed: the file reproduces itself.
    assert seat.kept == turn


@CHANNEL
@pytest.mark.parametrize("name", sorted(DIVERGED))
async def test_a_replay_that_diverges_stops_there_and_fails(
    concrete_application, portable_binding, tmp_path, monkeypatch, name,
):
    resources, _executor, _system, control, launch = concrete_application
    await control.shutdown()
    turn, reason, expected = DIVERGED[name]
    seat = replay(turn)
    observed, realness, _content = await attempt(resources, launch, portable_binding, tmp_path,
                                                monkeypatch, seat)
    assert realness == replace(PORTABLE, model="replay")
    with pytest.raises(ReplayDiverged, match=reason):
        seat.settle()
    # Closed loop: the recorded edit after the divergence was never sent or run.
    assert seat.sent == [turn.calls[0].program] and observed == expected, observed


async def contained_world(launcher, tmp_path):
    """The provisioned launcher over the full committed tree, for this task."""
    physical = MaintenanceNativeLauncher(
        **{item.name: getattr(launcher, item.name) for item in fields(LinuxLauncher)},
    )
    journal = SqliteJournal(tmp_path / "hostile.sqlite")
    runner = unqualified(tmp_path, physical, journal=journal)
    git = runner.authority
    base = await committed_tree_base(git)
    source = git._run("show", f"{base}:{CHANNEL_TARGET_PATH}").stdout.encode()
    assert source == BASE
    assert b"__pycache__/\n" in git._run("show", f"{base}:.gitignore").stdout.encode()
    inventory = git._run("ls-tree", "-r", "-z", base).stdout.encode()
    target_sha256 = hashlib.sha256(source).hexdigest()
    runner.checks = channel_reply_checks(source, target_sha256, inventory,
                                         git.environment.object_format)
    gate = await qualify(runner)
    workspace = ContainedWriteWorkspaceProvider(
        git, root=tmp_path / "writer-acquisitions", target_ref=runner.target_ref,
        provider_id="maintenance-workspace", posture=Posture.WRITE, launcher=physical,
    )
    request = ChannelReplyRequest(repository=git.repository_id, target_ref=runner.target_ref,
        base_commit=base, target_sha256=target_sha256, check_set_hash=gate.check_set_hash,
        **pinned(CHANNEL_PURPOSE))
    return MaintenanceResources(journal, git, workspace, gate, request, source,
                                CHANNEL_INSTRUCTION), physical


@pytest.mark.parametrize("name", sorted(CONTAINED))
async def test_a_model_shaped_reply_through_the_contained_worker_capture_and_gate(
    launcher, portable_binding, tmp_path, monkeypatch, name,
):
    resources, physical = await contained_world(launcher, tmp_path)
    programs, expected = CONTAINED[name]
    seat = seated(programs)
    observed, realness, content = await attempt(resources, physical, portable_binding, tmp_path,
                                                monkeypatch, seat)
    # Every recorded call really launched through the provisioned boundary.
    assert realness == PHYSICAL and realness.worker is type(physical)
    assert sent_as_written(seat, programs)
    retain("contained", name, observed, seat, content_digests=content,
           **({"worker_reports": seat.seen[0].splitlines()} if name == "where-am-i" else {}))
    assert observed == expected, observed
    if name in RECORDED:
        assert seat.recording() == RECORDED[name]
    if name == "read-then-end":
        assert seat.seen[0] == BASE.decode() + "\n"
    if name == "where-am-i":
        assert seat.seen[0].splitlines()[:2] == ["/workspace", "True"], seat.seen[0]


@pytest.mark.parametrize("name", ["read-then-edit", "another-base"])
async def test_a_recorded_turn_through_the_contained_worker_capture_and_gate(
    launcher, portable_binding, tmp_path, monkeypatch, name,
):
    resources, physical = await contained_world(launcher, tmp_path)
    turn, reason, expected = DIVERGED.get(name) or (RECORDED[name], None, SHARED[name][1])
    seat = replay(Turn.from_json(turn.to_json()))
    observed, realness, content = await attempt(resources, physical, portable_binding, tmp_path,
                                                monkeypatch, seat)
    assert realness == replace(PHYSICAL, model="replay")
    retain("contained", name, observed, seat, content_digests=content)
    assert observed == expected, observed
    if reason is None:
        seat.settle()
        assert seat.recording() == turn
    else:
        with pytest.raises(ReplayDiverged, match=reason):
            seat.settle()
        assert seat.sent == [turn.calls[0].program]
