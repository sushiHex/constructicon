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
entry must be an ordinary file, UTF-8 (an optional BOM is ignored for analysis)
and at most 32,768 bytes. Symlinks and trees refuse. The trusted CLI parses those immutable
blobs before submission; graph envelopes carry the bounded report and existing
`GitRef` contracts, never source text. The graph composes a small pure packet
component with `constructicon.std/human-advisor` and the existing durable mailbox.
It pins exact registered versions and moves no stable component pointer.
Git transports are disabled, including automatic partial-clone fetching; all
required objects must already be local. This is a trusted local example, not a
sandbox for malicious repository configuration.

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

## Opt-in: model advice under an owner's permit

The default commands above call no model, and nothing here changes them. The
explicit `model-advice` subcommand instead hands the bounded summary (scope,
hashes, syntax diagnostics, availability, symbol lists, counts and the partial
flag; never source text, a `GitRef` or a path) to the installed entry
`constructicon.api.change_review_advice`, which asks Codex READ for the advice in
one turn ([ADR 0025](adr/0025-consumer-runs-earn-a-permit.md)). Its stages are
`--stage pins` (print what a permit would bind, beside the exact instruction),
`--stage mint` (print a candidate permit; it installs nothing) and `--stage run`.

A real run needs the private Linux host, an owner-minted READ permit placed in
root custody that names this one run, and a live window. The executor stays
unavailable throughout; the permit is the only thing that admits the run, and
its idempotency key commits to the SHA-256 of the exact instruction bytes.
Anywhere else, or without that permit, each stage ends in a named refusal such
as `advice.permit` or `advice.provider`, never a fallback to the human route,
another vendor or an API. The reply is stored as model advice on its own
contract, never as `constructicon.std/AdviceResponse`. This delivery adds no
credential and no live authority, and has made no model call: its evidence is
[credential-free](../tests/api/test_change_review_advice.py), over a scripted
peer.

### Prepare the exact input offline

From the reviewed checkout and its project environment, use the packet preparer
before selecting a host window. For example, this compares the merged opt-in
change itself; all three full commits must already exist locally.
`REVIEWED_CONTROLLER_FULL_COMMIT` is the full commit of the reviewed checkout you
run from (for example, `git rev-parse HEAD`); the entry refuses any other:

```text
python -I -B scripts/ops/change_review_input.py --repository LOCAL_REPOSITORY --controller REVIEWED_CONTROLLER_FULL_COMMIT --before 6857f0d80f94aea353cf748db2d634f47be73705 --after cf81ccf92d395cd704dcf9d8d29b6470ca469563 --path examples/change_review.py --out FRESH_PRIVATE_PACKET_DIRECTORY
```

The entry reads the exact committed blobs through the existing source selector
and AST comparator. It checks the imported summary producer and the three
instruction-guard source files against the selected controller's raw Git blobs;
checkout conversion or a modified source refuses before output is claimed.
It creates `summary.json`, the exact `instruction.txt`, and `packet.json` in one
fresh directory. Existing output refuses; an interrupted partial directory is
retained and must not be reused. Keep the repository, imported source and output
parent trusted while preparing; this is a local byte comparison, not custody
against a concurrent writer or a verification of every package dependency.

Only `summary.json` is the consumer input. Its SHA-256 binds the exact transferred
bytes, while the instruction digest and key bind the instruction the adapter
would send. The packet's source references stay local; repository paths and
source text are absent from the instruction. The example produces one added
symbol (`model_advice`) and two changed symbols (`execute`, `main`). This supports
test/follow-up suggestions from a bounded summary, not a source or coverage audit.

The packet marks its graph/component/run pins provisional and execution
unauthorized. They are preparation facts only. The installed host must derive
and compare its actual pins before a separately approved permit can be placed.
No provider, operator binding, boot, generation, custody, qualification or cost
observation is supplied by packet preparation. The existing owner challenge and
cleanup obligations remain part of the separately selected live window.
