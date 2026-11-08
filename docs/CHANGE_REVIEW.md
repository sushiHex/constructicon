# Review a Python change without credentials

This checkout example compares two committed Python files, retains a review
request, and collects the local operator's advice. It produces a useful test
planning packet: added, removed and changed public definitions, syntax
diagnostics, exact source references, and the recorded advisor response.

The comparison is deterministic AST inspection. It executes no submitted code,
runs no tests and calls no model, provider or VM. The `demo` response is explicitly
scripted operator advice. A successful run means the packet and advice were
recorded, not that the code is correct or approved for merge.

From a checkout with Git and its own `uv sync --dev --python 3.11` environment, run this in
Bash/Git Bash. The Python child receives no interactive input:

```bash
PYTHONIOENCODING=utf-8 uv run --no-active python - <<'PY'
import json
import subprocess
import sys
import tempfile
from pathlib import Path

state = Path(tempfile.gettempdir()) / "constructicon-change-review"
command = [sys.executable, "-m", "examples.change_review", "--state", str(state),
           "demo", "--key", "walkthrough-1"]
for _ in range(2):
    completed = subprocess.run(command, stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, check=True)
    packet = json.loads(completed.stdout)
    print(json.dumps({"run_id": packet["result"]["run_id"],
                      "status": packet["result"]["status"],
                      "start_replayed": packet["submission"]["command"]["replayed"],
                      "advice_replayed": packet["reply"]["command"]["replayed"],
                      "outputs": packet["result"]["outputs"],
                      "metering": packet["result"]["metering"]}, indent=2))
PY
```

The first run creates a tiny fixed Git sample under the selected state directory
and finishes with `succeeded`: `count` was added and `total` changed. The second
uses the same RunId and recorded advice; both replay flags become `true`. Every
child is a fresh process. Changed committed sample bytes are refused; dirty
working files are ignored. Use a fresh state directory for another fixed example.
The example does not modify
your checkout or any source repository supplied to `submit`.

For your own change, use the same module entry with a state directory and these
arguments (substitute your repository, full lowercase commit SHAs and path):

```text
--state <state-directory> submit --repository <repository> --before-commit <sha> --after-commit <sha> --path package/module.py --key review-1
--state <state-directory> status --run-id <returned-run-id>
--state <state-directory> reply --run-id <returned-run-id> --advice "Add empty-input tests." --key advice-1
--state <state-directory> status --run-id <returned-run-id>
```

For example, replace `command` in the Python runner above with the module prefix
and one of these argument lists. `submit` returns `parked`, its RunId, the request
identity and `request_payload.analysis`, so the operator can inspect the packet
before answering. `reply` starts recovery, answers that run's retained request
as the fixed local actor and waits for completion. `status` only reads: it does
not start workers. Repeating identical submit or reply arguments with the same
key replays their command. Reusing a key for changed source references or advice
is refused. Use a new key for a different review or answer.

The source selector uses one relative POSIX file path at two exact commits. Each
blob must be UTF-8 and at most 32,768 bytes. The trusted CLI parses those immutable
blobs before submission; graph envelopes carry the bounded report and existing
`GitRef` contracts, never source text. The graph composes a small pure packet
component with `constructicon.std/human-advisor` and the existing durable mailbox.
It pins exact registered versions and moves no stable component pointer.

The report compares top-level public functions and classes, including their
bodies and decorators, while ignoring formatting and comments. It does not
analyze imports, module assignments, runtime behavior, dependencies or test
coverage. Syntax problems are retained data; symbol comparison is unavailable
when either file cannot be parsed. Each symbol list shows at most 25 names of
80 characters; counts and `symbols_partial` disclose truncation. Public result
previews may also truncate large output values; `request_payload.analysis`
retains the packet, and the result's detail reference resolves through the
existing pageable `ControlPlane.details_read` API.

The state directory contains durable summary inputs, requests and advice, plus
the local sample commits for `demo`. `submit` retains GitRefs to source commits
in the supplied repository; it does not copy those commits into the state directory.
The local process is trusted and uses one fixed static actor; this example does
not establish separate OS identities or HTTP authentication. Keep the checkout
and its importable example available when restarting unfinished runs. Recovery
uses the existing `ControlPlane` and `RunHost`; shutdown and process restart do
not invent a cancellation or duplicate a completed graph checkpoint.

`result.metering` is the existing public projection at the capability-accounting
event cut. This workflow dispatches no executor: coverage is `unmeasured`, groups
are empty, and estimates and confirmed charges remain `null` with `unknown`
coverage. Empty observations are not a zero-cost claim. See
[the metering decision](adr/0024-retain-native-executor-metering.md).

Focused executable evidence lives in
[the example tests](../tests/e2e/test_change_review_example.py), including real
process death after reply-command completion, fresh-process recovery and replay,
no source execution, conflicting-key refusal and input bounds. This is a
checkout example, not an installed CLI command or production executor route.
