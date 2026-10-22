# Claude startup qualification and admitted READ state review

Living implementation review under ADR 0021 and the accepted M8 N6 plan. This
slice composes one authenticated startup observation in a withdrawn operator
store with a separately authorized, admitted READ. Startup alone does not
establish physical installation, account identity, credential persistence,
model eligibility, production availability, or a READ. Fake evidence establishes
implementation behavior, not a live subscription result.

## Authority and state

The root-held maintenance binding, pinned installation configuration and
selected Pro/Max plan precede a QUALIFY invocation. Its exact egress is the
reviewed platform.claude.com and api.anthropic.com policy; LOGIN's narrower
policy and recipe remain separate. One STREAM_JSON process gets the existing
native store mount. The callback sends only bare initialize, get_settings and
get_hooks_listing, serially, with distinct correlated IDs. It does not register
MCP, write a user message, dispatch a model, retry a mode mismatch or inspect
credential content. Existing pure judges decide mode, effective settings and
hooks respectively. Initial first-party Claude API ambiguity is a refusal here.

The callback owns one read task continuously from its first request through
close and EOF. Before each write it audits completed reads, buffered records,
partial frames, EOF, cancellation, deadline and store binding. A request ID and
write count are spent before an uncertain write. After every await it rechecks
state and observes any completed read; a frame arriving during write or between
controls cannot be treated as a later correlated response. Exact UI invalidate
frames alone may interleave, including immediately after a response before the
next control, up to eight total. Unknown system/callback,
duplicate, malformed, oversized and trailing frames refuse. Positive callback
facts require three matching judges, exactly three writes, stdin close and EOF.

One loop-absolute deadline covers preparation, process and callback. Timeout
forbids further protocol work but never abandons owned reader, process, relay
or credential cleanup. The session checks terminal `BindingCheck` equality
after joined cleanup even if the deadline elapsed. Only affirmative process
cleanliness, relay closure, credential closure, terminal binding and callback
completion may yield JOINED_CLEAN; publication occurs after these checks.
Cancellation remains cancellation, not a finite success. The session neither
closes an inherited custody lock nor advances to READ automatically.

## Evidence boundary

Public evidence is bounded enums/counts/booleans: phase, lifecycle, three
verdicts, three-at-most write attempts, eight-at-most UI records, close/EOF,
process/relay/credential/binding facts, selected plan, model and effort bound
to the reviewed configuration and existing exact installation identities.
QUALIFY alone records a revision of the loaded qualification, framing,
judgment, custody/cleanup and evidence-publication source law; older maintenance
record shapes remain unchanged.
There are no wire records, errors, prompts, account fields, credential hashes,
or inferred subscription/production-availability flags. A JOINED_CLEAN
qualification is an observed phase fact, not a production-ready grant.

Fake acceptance covers all three correlated judges, private UI interleaving,
close/EOF and joined cleanup. Refusals cover mode ambiguity, wrong IDs,
duplicate/partial/tail frames, unexpected callbacks, bounds, cancellation,
reentry and resume races. No fake success asserts vendor live behavior.

## Separately admitted READ

The host reader checks the complete bounded qualification record against both
sealed store revisions and the installed configuration and source identities.
Before publication, the service-side operator composition uses the same pure
validator to obtain the selected plan and evidence digest without inventing an
already-sealed store. The sealed reader adds only the two actual generation
comparisons; each validation reads one evidence snapshot.
Every required observation is affirmative; absence, a new unknown field, or a
record about different inputs refuses. Pro and Max select their corresponding
observed subscription mode; this is not an account identity claim.

The API assembles existing contracts: one fixed Graph, one executor lease and
one read-only workspace lease, an exact QualificationAuthorization, and the
existing journal/control-plane/RunHost path. There is no additional scheduler
or public provider discovery. The provider remains unavailable outside this
one authorization. The fixture is a fixed Git ref at a separately pinned
commit, containing only `ready.txt` with the literal `ready` and final LF.
The component requires a successful READ callback and the stripped answer
`ready`; it does not treat an unstructured result's absent `output` as text.

Preparation creates a fresh private service-owned repository. Inspection
validates its ancestry, configuration and objects before constructing
GitAuthority, whose constructor installs its hook. The workspace population
launcher has a 32-KiB archive bound: the one-file Git archive is 10,240 bytes.
The contained file worker retains its distinct narrow READ limits. Sharing
the worker's one-byte artifact limit with population would refuse every real
materialization; the accepting graph test exposed this composition error.

## READ resume and failure boundaries

- Acquisition reserves a durable attempt before returning an inert handle.
  It does not dispatch or make an absent result into success.
- Materialization waits for the acquisition guard and retained store lock.
  Each resumed wait rechecks control, authorization expiry and the acquisition
  fence. Initial binding, fixed ref/commit and materialized base must agree.
- Startup and every callback use the same invocation, ownership epoch, binding
  and acquisition. A callback cannot borrow another run's materialization.
- Immediately before the sole user write, the transaction calls the provider's
  dispatch hook. The hook durably records intent, then rechecks authority after
  that potentially blocking write. A spent or uncertain intent is never retried.
- A native success alone is insufficient. Qualification requires exactly one
  started and completed contained read, a closed non-denying relay, and protocol
  completion. Refusal drops task text while retaining observed telemetry.
- Completion is durably recorded before success is published. A record-write
  failure cannot become success; settlement still attempts every owned cleanup.
- Cleanup joins the process and relay, checks terminal store binding, closes
  descriptors and releases locks, then disposes the acquisition payload under
  its original fence. Cancellation remains cancellation even when cleanup also
  fails. Terminal binding failure is not hidden by an earlier error.
- Journal replay returns the existing run result without another attempt. A
  partial durable attempt is not permission to launch a replacement process.

The fake graph tests exercise admission, materialization, both leases, protocol,
contained-worker invocation, durable completion and replay. Windows substitutes
only platform/process primitives; its passes are not Linux physical evidence.
The hosted composition test uses a harmless native peer, real contained worker,
relay and acquisition guard, with a harmless locked store double. It neither
contacts an upstream service nor qualifies vendor behavior.

## Review corrections and limits

Independent review reproduced qualification controls continuing after custody
changed during a read, followed only by a terminal refusal. The conversation
must check custody at its own resume boundaries, not rely on a launch or final
check. It also identified reusable judgment/publication helpers omitted from
the qualification source identity, and a valid UI-invalidate record refused
when it followed a control response in the same read chunk. These are
implementation defects, not reasons to broaden the protocol or authority.

The fixture answer deliberately uses stripped word equality; exact output
whitespace is not the proof. This was reviewed and retained. Installation,
attended login, fresh-process persistence and live qualification/READ remain
separate operator-session evidence. No fake test supplies those observations.
