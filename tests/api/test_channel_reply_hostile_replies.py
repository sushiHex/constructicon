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
scripted byte channel (``WriteNative``), so a case says what the system does with
a reply, never whether a model sends it. The placement lane's fake provider
(``tests/native_provider.py``) scripts at most one tool call, and that lane
answers the call with fixed text, with no worker, capture or gate behind it; it
cannot carry these cases.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import fields
from pathlib import Path

import pytest

from constructicon.api import maintenance_entry as entry
from constructicon.api.plan_manifest_application import (
    CHANNEL_INSTRUCTION,
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
from constructicon.substrate.executors.codex_protocol import MAX_TOOL_CALLS, TOOL_OUTPUT_BYTES
from constructicon.substrate.executors.linux import LinuxLauncher
from constructicon.substrate.gates.channel_reply import (
    HELPER_SOURCE,
    ExtractionRefusal,
    check_extraction,
)
from constructicon.substrate.git.capture import ContainedWriteWorkspaceProvider
from constructicon.substrate.journal import maintenance_diagnostic
from constructicon.substrate.journal.maintenance_diagnostic import _FAILURES
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.api import test_plan_manifest_application as application_tests
from tests.api.test_plan_manifest_application import PortableProcessLauncher
from tests.maintenance_task_world import (
    committed_tree_base,
    configure_executor_guard,
    scripted_task_executor,
)
from tests.substrate.test_channel_reply_oracle import BASE
from tests.substrate.test_codex_adapter import descriptor_of
from tests.substrate.test_codex_adapter import portable_binding as portable_binding
from tests.substrate.test_codex_protocol import completed
from tests.substrate.test_codex_write import WriteNative
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
        "read-then-end", "read-then-edit", "call-raises", "output-over-bound",
        "edit-plus-backup",
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


def hostile_native(programs) -> WriteNative:
    """The scripted peer: each program as one callback in turn, then completion."""
    if not programs:
        native = WriteNative("never sent")
        native.records[:] = [completed(answer="The file is read-only, so I changed nothing.")]
        return native
    return WriteNative(programs[0], callbacks=[
        WriteNative._callback_for(f"server-{index}", f"call-{index}", program)
        for index, program in enumerate(programs, 1)
    ])


async def attempt(resources, launch, binding, tmp_path, monkeypatch, programs):
    """One entry run against the scripted reply; the facts a packet would carry."""
    native = hostile_native(programs)
    resources, executor, scripted, _configuration, authorization = await scripted_task_executor(
        resources, launch, binding, tmp_path, "", task=CHANNEL_STORED_REPLY, native=native)
    assert scripted.native is native and authorization.purpose == "channel-stored-reply"
    configure_executor_guard(monkeypatch)
    result = await entry.run_maintenance(resources=resources, executor=executor,
        executor_descriptor=descriptor_of(executor, "executor"), authorization=authorization)
    journal, run_id, request = resources.journal, authorization.run_id, resources.request
    # The instruction the peer was sent is the task's own, imported and never restated.
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
    assert [kwargs["stdin"].decode() for kwargs in workers] == programs[:len(workers)]
    assert len(workers) == callbacks["admitted_started"]
    assert all(kwargs["posture"] is Posture.WRITE for kwargs in workers)
    seen = []
    for response in native.callback_responses:
        assert response["result"]["success"] is True
        item, = response["result"]["contentItems"]
        seen.append(item["text"])
    # The retained fingerprints are of exactly these bytes: each program as the
    # worker received it, and each output the peer was handed. They are what
    # tells a read and nothing more from a rewrite of the same bytes, which end
    # in the same refusal. No text is retained beside them.
    content = record["facts"]["content_digests"]
    assert maintenance_diagnostic._content_digests(
        record["facts"], CallbackObservation.model_validate(callbacks)) == content
    assert [item["program"] for item in content["callbacks"]] == [
        by_digest(kwargs["stdin"]) for kwargs in workers]
    for index, text in enumerate(seen):
        assert content["callbacks"][index]["output"] == by_digest(text.encode())
    assert [item["output"] is None for item in content["callbacks"]] == [
        category is None for category in callbacks["worker_results"]]
    text = Path(authorization.attempt_record).read_text(encoding="utf-8")
    assert not any(program.strip() and program in text for program in programs)
    return {
        "outcome": outcome, "node": node, "started": callbacks["admitted_started"],
        "completed": callbacks["admitted_completed"],
        "workers": callbacks["worker_results"], "seen": len(seen),
    }, seen, content


def by_digest(raw: bytes) -> dict[str, object]:
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def retain(tier, name, observed, seen, **extra):
    write_evidence(f"codex-maintenance-hostile-{tier}-{name}.json", {
        "issue": 407, "tier": tier, "case": name, **observed,
        "seen_bytes": [len(text.encode()) for text in seen],
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
    assert type(launch) is PortableProcessLauncher
    programs, expected = SHARED[name]
    observed, seen, content = await attempt(resources, launch, portable_binding, tmp_path,
                                            monkeypatch, programs)
    retain("portable", name, observed, seen, content_digests=content)
    assert observed == expected, observed
    if name == "read-then-end":
        # The peer was handed the whole target, as a model's first step expects.
        assert seen[0].replace("\r\n", "\n") == BASE.decode() + "\n"


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
        base_commit=base, target_sha256=target_sha256, check_set_hash=gate.check_set_hash)
    return MaintenanceResources(journal, git, workspace, gate, request, source), physical


@pytest.mark.parametrize("name", sorted(CONTAINED))
async def test_a_model_shaped_reply_through_the_contained_worker_capture_and_gate(
    launcher, portable_binding, tmp_path, monkeypatch, name,
):
    resources, physical = await contained_world(launcher, tmp_path)
    programs, expected = CONTAINED[name]
    observed, seen, content = await attempt(resources, physical, portable_binding, tmp_path,
                                            monkeypatch, programs)
    # Every recorded call really launched through the provisioned boundary.
    assert type(physical) is MaintenanceNativeLauncher and isinstance(physical, LinuxLauncher)
    retain("contained", name, observed, seen, content_digests=content,
           **({"worker_reports": seen[0].splitlines()} if name == "where-am-i" else {}))
    assert observed == expected, observed
    if name == "read-then-end":
        assert seen[0] == BASE.decode() + "\n"
    if name == "where-am-i":
        assert seen[0].splitlines()[:2] == ["/workspace", "True"], seen[0]
