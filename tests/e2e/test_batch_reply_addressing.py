"""Reply preparation addresses one file; the full response still observes all."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from examples import change_review_batch as batch
from examples.change_review import OPERATOR, assemble, checked

from tests.e2e.test_change_review_batch_example import (
    ROOT,
    assert_public_result,
    by_path,
    entry,
    output,
    source_commits,
    submit_arguments,
)

PROBE_PREFIX = "TEST_REPLY_ADDRESSING="


def addressed_reply(
    state: Path, run_id: str, file_id: str, advice: str, key: str,
) -> tuple[subprocess.CompletedProcess, dict]:
    # Wrap the public boundary without replacing authorization, the durable
    # command, or observation. Reads after entering channels_reply are the
    # legitimate full-response path and do not belong to preparation's bound.
    code = """
import json
import sys
import examples.change_review_batch as batch
from constructicon.api.control import ControlPlane
messages = []
reply_calls = 0
original_message = ControlPlane.channels_message
original_reply = ControlPlane.channels_reply
def counted_message(self, actor, message_id):
    if reply_calls == 0:
        messages.append(str(message_id))
    return original_message(self, actor, message_id)
async def counted_reply(self, actor, *, message_id, payload, idempotency_key):
    global reply_calls
    reply_calls += 1
    return await original_reply(self, actor, message_id=message_id, payload=payload,
                                idempotency_key=idempotency_key)
ControlPlane.channels_message = counted_message
ControlPlane.channels_reply = counted_reply
try:
    status = batch.main()
finally:
    print('TEST_REPLY_ADDRESSING=' + json.dumps({
        'messages_before_reply': messages, 'reply_calls': reply_calls,
    }), file=sys.stderr)
raise SystemExit(status)
"""
    process = subprocess.run(
        [sys.executable, "-c", code, "--state", str(state), "reply", "--run-id", run_id,
         "--file-id", file_id, "--advice", advice, "--key", key],
        cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
        timeout=90, check=False,
    )
    probes = [line.removeprefix(PROBE_PREFIX) for line in process.stderr.splitlines()
              if line.startswith(PROBE_PREFIX)]
    assert len(probes) == 1, (process.returncode, process.stdout, process.stderr)
    return process, json.loads(probes[0])


def test_reply_preparation_reads_only_its_selected_file_and_keeps_real_command_semantics(
    tmp_path: Path,
) -> None:
    repository, before, after = source_commits(
        tmp_path,
        {"a.py": b"def old_a(): pass\n", "b.py": b"def old_b(): pass\n"},
        {"a.py": b"def new_a(): pass\n", "b.py": b"def new_b(): pass\n"},
    )
    state = tmp_path / "state"
    submitted = output(entry(state, *submit_arguments(
        repository, before, after, ("b.py", "a.py"), key="addressed-batch",
    )))
    assert submitted["result"]["status"] == "parked"
    run_id = submitted["run_id"]
    initial = by_path(submitted)
    selected, sibling = initial["b.py"], initial["a.py"]
    assert selected["request"]["message_id"] != sibling["request"]["message_id"]

    # A validly shaped identity outside this sealed batch does not reach either
    # the channel read or the mutating operation.
    foreign = batch.file_identity(str(repository.resolve()), "unselected.py")
    refused, refused_probe = addressed_reply(state, run_id, foreign, "Do not route.", "nonmember")
    assert refused.returncode == 1 and "batch_file_unknown" in refused.stderr
    assert refused_probe == {"messages_before_reply": [], "reply_calls": 0}

    arguments = (state, run_id, selected["file_id"], "Review b only.", "addressed-advice")
    answered_process, first_probe = addressed_reply(*arguments)
    answered = output(answered_process)
    files = by_path(answered)
    assert answered["reply"]["request_id"] == selected["request"]["message_id"]
    assert answered["reply"]["command"]["replayed"] is False
    assert files["b.py"]["status"] == "succeeded"
    assert files["b.py"]["advice"]["advice"] == "Review b only."
    assert files["b.py"]["advice"]["actor_id"] == OPERATOR.actor_id
    assert files["a.py"]["status"] == "parked" and files["a.py"]["advice"] is None
    assert files["a.py"]["request"]["message_id"] == sibling["request"]["message_id"]
    assert first_probe["reply_calls"] == 1
    assert first_probe["messages_before_reply"] == [selected["request"]["message_id"]]

    replay_process, replay_probe = addressed_reply(*arguments)
    replay = output(replay_process)
    assert replay["reply"]["command"]["replayed"] is True
    assert replay["reply"]["message_id"] == answered["reply"]["message_id"]
    assert replay["result"] == answered["result"]
    assert replay_probe == first_probe

    changed, changed_probe = addressed_reply(
        state, run_id, selected["file_id"], "Changed payload.", "addressed-advice",
    )
    assert changed.returncode == 1 and "control.idempotency.conflict" in changed.stderr
    assert changed_probe == first_probe
    crosswired, crosswired_probe = addressed_reply(
        state, run_id, sibling["file_id"], "Review b only.", "addressed-advice",
    )
    assert crosswired.returncode == 1 and "control.idempotency.conflict" in crosswired.stderr
    assert crosswired_probe == {
        "messages_before_reply": [sibling["request"]["message_id"]], "reply_calls": 1,
    }
    observed = output(entry(state, "status", "--run-id", run_id))
    assert observed["result"] == answered["result"]
    assert by_path(observed)["a.py"]["reply"] is None

    final_process, final_probe = addressed_reply(
        state, run_id, sibling["file_id"], "Review a separately.", "sibling-advice",
    )
    finished = output(final_process)
    assert finished["result"]["status"] == "succeeded"
    assert all(file["status"] == "succeeded" for file in finished["files"])
    assert by_path(finished)["a.py"]["advice"]["advice"] == "Review a separately."
    assert final_probe == crosswired_probe
    assert_public_result(state, finished)
    _, control = assemble(state / "review.db")
    assert checked(control.runs_list(OPERATOR)).page.count == 1
