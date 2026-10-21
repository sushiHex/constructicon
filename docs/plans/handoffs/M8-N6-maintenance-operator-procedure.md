# Claude maintenance entry: operator procedure draft

This is a preparation document for [#40](https://github.com/sushiHex/constructicon/issues/40),
not an authorization or an executable private-host installation package.
The [maintenance state review](M8-N6-subscription-maintenance-state-review.md)
owns the proposed lifecycle. Accepted ADR 0021 and the frozen M8 plans remain
unchanged. No account, credential or vendor process was used to write this
procedure. The implementation's fake proofs do not establish subscription
authentication.

## Readiness boundary

The repository has a reviewed root-held `operator_store maintain` entry and
Claude launcher artifact checks. It does **not** yet have a reviewed private-
host Claude vendor/runtime/AppArmor installation command. That missing
composition is tracked in [#283](https://github.com/sushiHex/constructicon/issues/283).
The hosted fixture
is explicitly CI-only. Do not run it on the private host, reinterpret the
Codex launch-set installer as a Claude installer, or substitute ad hoc root
commands. Generic controller verification can attest source at a commit; it
does not install or qualify the Claude native artifacts.

Before this draft becomes an attended package, record and review:

- The merged controller commit and exact-head verification, containment and
  review results; the independently checked controller installation.
- The Claude 2.1.296 vendor member, immutable vendor tree, curated runtime
  closure, fixed bubblewrap and AppArmor policy identities. Installation and
  benign launch/profile checks must establish these facts on the actual host.
- Exclusive custody, current boot and drift checks, and a recovery procedure
  for a dropped SSH session. Unexpected drift stops; no R6 re-baseline is
  implied.
- The private store selection and withdrawal generation; whether this is an
  explicitly authorized first credential-file creation or an existing store.
- The exact configuration bytes and their separately reviewed SHA-256; actual
  globally routable address pins and finite connection budgets for each phase.
- The selected Pro/Max plan, model and effort as fixed installation inputs.
  They are not inferred from a login result.

Private transport locators, account identifiers and raw output remain private.
The issue records checked facts and non-secret artifact identities only.

## One command per acquisition

The service entry is `constructicon.substrate.executors.claude_lane`. These
are its command shapes, **not copy-and-paste host commands**: uppercase names
below are reviewed private-package inputs, not values to discover or fill in
at execution time.

```text
python3 -I -m constructicon.substrate.executors.claude_lane login
  --launch-config CONFIG --launch-config-sha256 REVIEWED_SHA256
  --lane-dir FRESH_LOGIN_DIR --evidence NEW_LOGIN_EVIDENCE
  [--first-login]

python3 -I -m constructicon.substrate.executors.claude_lane observe
  --launch-config CONFIG --launch-config-sha256 REVIEWED_SHA256
  --lane-dir FRESH_OBSERVE_DIR --evidence NEW_OBSERVE_EVIDENCE
  --selected-plan SELECTED_PLAN

python3 -I -m constructicon.substrate.executors.claude_lane reload
  --launch-config CONFIG --launch-config-sha256 REVIEWED_SHA256
  --lane-dir FRESH_RELOAD_DIR --evidence NEW_RELOAD_EVIDENCE
  --selected-plan SELECTED_PLAN
```

Each command is the fixed service command inside a separate reviewed
`operator_store maintain ... -- LANE` root invocation. The root helper supplies
the inherited store root/key, maintenance custody, retained lock descriptor
and generation floor. The lane never reacquires a free lock as proof. The
expected configuration hash is a literal in that reviewed command, not read
from the configuration it authenticates. There is no arbitrary native argv,
environment override, login operation in a mode phase, or automatic next phase.

The configuration is closed schema 1, at most 8 KiB. It binds launch root,
runtime digest, fixed bubblewrap hash, launch policy and hash, vendor tree and
digest, pinned vendor version, model/effort and three egress policies. Each
policy supplies exact `(host, 443, globally routable literal address)` entries
and a positive finite connection cap. Login admits only `platform.claude.com`;
observe and reload admit exactly that host and `api.anthropic.com`. The hash
check precedes parsing and custody. The policy is not widened after a denial.

## Attended login

All preparation, diagnosis, observation and reload commands have closed stdin.
Only the explicitly attended login uses an operator-started private `ssh -T`
session. Its remote command is fixed in the reviewed package. Do not pipe a
script or pre-filled authorization response into that session, invoke a shell
prompt, or use `tee`, a transcript collector or public CI log for its streams.
The operator waits for the actual vendor prompt, completes the vendor browser
flow and enters the response directly into the private session, never chat.

The native command is fixed to `--safe-mode auth login --claudeai`. The
physical relay denies `api.anthropic.com` before dialing, including the API-key
creation destination. It does not intercept TLS or rewrite OAuth. This also
denies profile lookup and can leave subscription metadata absent. That is a
possible refusal, not permission to open the destination during login.

The phase has one 600-second deadline, one opaque LF-terminated input line of
at most 4,096 bytes and at most 256 KiB forwarded stdout. The three private
streams must be distinct pipe/socket backing objects. Retained stderr is at
most 64 KiB and can be forwarded only after joined native/relay teardown with
time remaining on the original deadline. Cleanup is joined even after that
deadline; it does not gain permission for further I/O. An uncertain input
write is never resent. First-login creation is exclusive, never truncation.

## Observation and reload

After the login acquisition joins and releases, observation is a new explicit
maintenance acquisition. It sends only bare initialization, at most twice in
120 seconds, and continues to the second request only for the exact supported
ambiguous mode. The second is no earlier than 30 seconds after the first
response. Wrong mode, malformed frames and pending actions refuse immediately.
No login, user message, tool registration or model request follows a refusal.

Missing metadata alone does not cause the vendor's refresh. If natural expiry
must be awaited, hold neither a lock nor a process during that interval. No
expiry edits, forced 401, token parsing or unsupported refresh operation is
allowed. The next acquisition must establish its own custody facts.

Reload is a third process/acquisition: one initialization under a fresh
120-second deadline must positively match the selected plan. Earlier in-memory
mode, mtime, process exit and empty fault lists cannot replace that result.
No phase automatically publishes a descriptor, activates a binding, qualifies
startup or dispatches READ.

## Evidence and stop rules

The lane reserves a fresh evidence name before effects and publishes bounded
phase facts only after cleanup. The evidence's `completed` flag means the
record was completely published, not that the phase passed. Its domain is
`claude-maintenance-entry-evidence`, not Codex qualification evidence. Even a
joined-clean result states `subscription_qualified: false` and
`production_available: false`; it is not an activation conformance revision.

A dropped SSH session, missing record or timeout is not proof of remote
termination. Stop, preserve withdrawal and use the separately reviewed recovery
check before another acquisition. Do not retry automatically. Unexpected
output or drift stops the attended package. Positive mode plus fresh reload
feeds a separate authenticated qualification gate; only after that gate and
its exact procedure may the bounded admitted READ checkpoint run.
