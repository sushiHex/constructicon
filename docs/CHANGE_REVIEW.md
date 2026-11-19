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

## Review a bounded file batch

`python -m examples.change_review_batch` reviews one to sixteen explicitly
selected files at the same two full commit SHAs. It composes the existing
single-file review graphs inside one root Graph and one durable RunId. Every
source blob is checked before application state is created. Source code is
never executed or placed in graph envelopes; the graph receives bounded facts
and GitRefs. No model, provider or VM is called.

Run the portable Python walkthrough from the checkout environment:

```text
uv run --no-active python -m examples.change_review_walkthrough
```

It retains a new temporary workspace containing two real commits, a two-file
review and its journal. Every submit, reply and status call is a fresh process.
It answers the second file first, shows partial completion, completes the first
file, and demonstrates same-key replay. Advice is explicitly scripted operator
text; this walkthrough calls no model and measures no native usage or price.
It prints readable reports and the retained workspace for later inspection.

Use `--workspace <new-directory>` to select the location. The directory must
not exist; an occupied path is refused rather than reused or overwritten.
The printed command arguments are escaped data, suitable for a Python
`subprocess.run` argument list, rather than shell text to paste blindly.

For ordinary batch commands, put `--format text` before the subcommand to
select the readable view. The default remains JSON:

```text
--state <state-directory> --format text status --run-id <returned-run-id>
```

The text view renders the same already-observed response. It performs no
additional Git or journal reads and starts no workers. It shows each file
identity and status, the retained added/removed/changed names and counts,
syntax/comparison limits and opaque advice marked untrusted. Static facts do
not establish runtime behavior, useful coverage, or correctness of an advice
claim. A successful workflow means the advice was recorded, not that the code
is correct or approved for merge.

For an existing repository, use the same module with these argument shapes:

```text
--state <state-directory> submit --repository <repository> --before-commit <sha> --after-commit <sha> --path package/a.py --path package/b.py --key batch-1
--state <state-directory> status --run-id <returned-run-id>
--state <state-directory> reply --run-id <returned-run-id> --file-id <returned-file-id> --advice "Add a boundary test." --key answer-1
```

Paths must be distinct and satisfy the single-file source contract above. Their
order is canonicalized: reordered identical submissions with the same key replay
the same batch. A changed batch with that key refuses as a control-plane
conflict. A file identity depends on repository and path, not its commits or
position. Reply only to a file identity returned by that batch. Identical reply
keys/payloads replay; changed advice under an existing key conflicts. The actor
is fixed by the local transport, never supplied as an argument.

Status reads retained inputs, the admitted manifest, events and canonical
request/reply identities through public APIs. It starts no workers and performs
no Git reads. A completed file's advice remains visible while another file is
pending. Reply waits for its file and root to settle; shutdown does not invent
cancellation. Interrupted commands recover through the existing control-plane
command law when the corresponding mutation is retried. Submit and reply allow
180 seconds for settlement polling, pausing up to one second between iterations
and using the public run-state query rather than repeatedly rendering complete
status.
This is a polling budget, not a total command wall-time limit: synchronous
projection and shutdown work may take longer. If the budget expires, exit code
2 returns the retained RunId and submission/reply receipt with
`wait_status: "timed_out"`, `partial: true` and a named limitation. It does not
cancel or submit another run. Inspect status or retry the same mutation with
its original key to resume through the existing recovery law.

`result` retains the existing V3 producer projection unchanged, including its
batch metering and accounting cut. Per-file usage is explicitly unknown; the
batch total is never multiplied or divided among files. Scripted advice creates
no native observations, so unmeasured usage is not a zero-cost claim.
The readable view places root metering once, separately from file results. It
retains the event cut, coverage, attempt count and each source's known token
subtotals and observation counts. Missing observations remain unknown; tokens
are not prices or backend-request counts. Estimates, confirmed charges and
per-file attribution remain explicitly unknown. The view adds no ledger or
price calculation.
Responses are capped at 256 KiB including their final LF. Large per-file payloads
are explicitly omitted with `partial`, `limitations` and per-file `omitted`
markers while detail references remain; the root result is preserved. Metadata
that cannot fit refuses by name. Detail reads are bounded at 4 MiB. These are
application projection bounds, not changes to the kernel's contracts.

The text view has its own explicit omission notices within the same 256 KiB
bound. Individual metadata values have a 4 KiB rendering budget; each optional
file-details block has 12 KiB. An oversized value or block is replaced by a
named omission rather than a shortened claim. File identities/statuses,
partial markers and root metering remain
visible when optional facts or advice do not fit. Terminal control characters
and other non-ASCII data are escaped. Use JSON and retained detail references
for complete machine-readable data; text formatting does not change the saved
response or grant authority.

The separate native framing comparison in #459 observed concrete scenarios in
three of three cases versus zero of three before, but truthfulness passed in
only two of three versus three of three before. One reply grouped an added
function into an unsupported unchanged-signature claim. That stopped the
investigation without a positive batch-quality conclusion. The existing framing
and opaque advice contract were retained; no further tuning or semantic advice
checker is part of this workflow. Displaying structural facts beside advice
does not establish that the advice agrees with those facts. These small,
stochastic observations do not establish generalized model quality.

The local state uses the existing journal only. Keep the checkout available for
unfinished-run recovery. There is no batch scheduler, sidecar ledger, new
primitive, native opt-in or quality/merge approval in this entry.

## Opt-in: model advice under an owner's permit

The default commands above call no model, and nothing here changes them. The
explicit `model-advice` subcommand instead hands a bounded structural summary
to the installed entry `constructicon.api.change_review_advice`, which asks
Codex READ for advice in one turn
([ADR 0025](adr/0025-consumer-runs-earn-a-permit.md),
[ADR 0027](adr/0027-bounded-structural-change-facts.md)). Source text, a
`GitRef` and paths stay local.

The V2 advice producer keeps hashes, syntax status, public symbol lists,
counts and partial reporting, and adds kinds, changed-part flags and an exact
whole-module AST-change bit. Metadata aligns by position with the existing
symbol lists. Unavailable or partial detail is null; when metadata is available,
a duplicate group carries the multiple kind marker and null changed parts.
Header, decorator, docstring and body flags describe AST differences. A class body flag does not identify a
method, and none of these facts establishes compatibility, behavior or test
coverage. The whole-module bit compares the complete ordered ASTs, including
beyond the public names; it does not localize those changes. The human route's
report above remains unchanged.

The instruction still refuses above 8,192 UTF-8 bytes. Some large summaries
that fit V1 do not fit V2; facts are never silently dropped to make them fit.
Historical V1 packets and replies retain their original pinned tooling.
Current V2 preparation does not upgrade or reinterpret them. Its stages are
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
credential or live authority. Construction is
[credential-free](../tests/api/test_change_review_advice.py), over a scripted
peer. Historical V1 live delivery is recorded in the
[M8 implementation record](plans/handoffs/M8-implementation-record.md);
it does not qualify this V2 component. A later live request requires its own
matching controller, standing record and selected window.

### Prepare the exact input offline

From a Git-byte-exact reviewed source image and its project environment, use the packet preparer
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

### Prepare and return advice for one batch member

The local bridge selects one explicit `file_id` from a retained batch. It
re-reads that member's exact committed sources, verifies the retained V1 facts
and source refs, then calls the existing V2 producer. It never upgrades V1 facts
into V2 facts. The controller repository may be separate from the reviewed
repository; the selected controller must still contain the exact four imported
producer/guard source files.

```text
python -I -B scripts/ops/change_review_batch_prepare.py --state BATCH_STATE_DIRECTORY --run-id RETAINED_BATCH_RUN_ID --file-id SELECTED_FILE_ID --controller REVIEWED_CONTROLLER_FULL_COMMIT --controller-repository CONTROLLER_REPOSITORY --out FRESH_PRIVATE_PACKET_DIRECTORY
```

The original `packet.json`, `summary.json` and `instruction.txt` retain their
existing bytes. An additional `binding.json` selects the immutable batch world,
file, exact request and packet digests. The preparer prints its raw
`binding_sha256`; retain that pin with the packet. Preparation refuses unknown,
answered or terminal requests, changed/unreadable sources and occupied output.
Sibling progress does not invalidate the immutable selection. This binding is
prepared data, not a permit, approval or new source of authority.
The computed consumer packet must pass the existing collector's validator
before its output directory is claimed. Batch-valid paths containing control
characters, for example, cannot become unusable native packets or defer that
refusal until after a model window.

Native execution remains the existing separately selected one-request route,
with its own dedicated journal, permit, custody and cleanup. The bridge does
not launch a model, VM or window. After that window has finished, supply its
actual private custody work and nonce-record paths:

```text
python -I -B scripts/ops/change_review_batch_reply.py --state BATCH_STATE_DIRECTORY --binding PRIVATE_PACKET_DIRECTORY/binding.json --binding-sha256 PREPARED_BINDING_SHA256 --work NATIVE_CUSTODY_WORK_DIRECTORY --record NATIVE_WINDOW_RECORD_DIRECTORY --key BATCH_REPLY_KEY
```

The existing collector checks the window's own retained result, challenge,
capture, accepted-read and clean-close evidence. Caller-provided delivered JSON
is never accepted. The bridge joins that result to the pinned packet and current
exact batch request before sending opaque advice through `ControlPlane` as the
existing local operator. It refuses a native reply above the batch's 4,096-byte
UTF-8 bound, even though the native contract can retain 16,384 bytes. Full native
evidence remains available; advice is never truncated, retuned or retried to fit.

The reply command uses the supplied idempotency key. Repeat the original key
and identical evidence to replay; a changed payload under a known key is a
Core conflict. An already answered target with an unknown key refuses before
claiming a command. If another writer wins after preflight, standard Core reply
law decides the race; it can record a rejected command, but cannot replace the
winning reply. The existing settlement wait and failed/cancelled/timed-out exit
semantics remain. Keep the packet and original private window evidence for
bridge replays; missing evidence refuses rather than starting another model run.
An affirmative Core rejection returns a refusal with its closed fault codes,
not private messages or payload details. Exceptions after reply dispatch or
during settlement/reporting return `unverified`, not a claim of no effect.
Known reply-command metadata is retained when available. A reporting failure
does not undo a committed reply: inspect the retained batch and replay only
the original key and inputs. Unexpected cleanup failures also remain unverified.

The bounded JSON result returns reply-command metadata and separate
`batch_root` / `native_window` usage, each with its own run identity and cut.
Native observations are not inserted into the batch root or allocated as a
per-file meter. No combined total, new ledger or inferred price is produced;
unknown charges and backend requests remain unknown. Raw advice is absent from
this handback response; ordinary batch status exposes the retained opaque
advice. Binding inputs are bounded to 64 KiB and handback output to 64 KiB,
including LF. CLI diagnostics use named reasons without private paths or advice.

This is a trusted local-operator composition of existing contracts. Its checksum
and private-file checks do not attest against a malicious operator rewriting
every input or make an atomic filesystem snapshot. It adds no physical authority,
live qualification, production availability or model-quality conclusion.
