# M8 N3b: state and resume review

Status: pre-implementation design, independently reviewed and amended.
Base: `6bc9500`. Reviewed head: `9058290`.
Scope: N3b of [issue 76](https://github.com/sushiHex/constructicon/issues/76).
Authority: [ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md)
lines 277-287, which preserve the destination-restriction design of
[ADR 0020](../../adr/0020-native-harnesses-mediate-contained-tools.md) lines
266-296, and [M8 rev 3, N3](../milestones/M8-live-executors-rev3.md) lines 89-116.
This record does not amend any of them.

The independent review (Codex `gpt-5.6-terra`, effort xhigh, job
`job_7914037954a5`, worktree mounted read-only) returned "do not start
implementation yet": one P1 and seven P2 findings, plus six P3. Every finding was
re-checked against source before being kept or downgraded. This revision adopts
every accepted P1/P2 and the P3s marked adopted. Rejected findings are recorded
with their reasons under [Review disposition](#review-disposition), so they are
not re-litigated. Nothing in the review was executed on Linux; each Linux claim
below is reasoning until Linux CI runs it.

## Boundary and reuse

N3b adds acquisition-scoped `native_vendor_session_only` egress. It adds a
host-side CONNECT relay that permits only fixed destinations. The native zone
reaches it through one read-only socket leaf, bound into the network namespace
the zone already has.

The namespace is the physical boundary for **network** sockets (I1): the zone
has only `lo`, so no IP route and no abstract Unix socket of the host is
reachable (abstract sockets are scoped by network namespace; `--unshare-net`
is at `linux.py:325`). **Pathname** Unix sockets are not scoped by network
namespace: they are addressed through the filesystem, so the zone reaches
exactly the sockets its mounts expose. Those mounts are the immutable runtime
(which `runtime_inventory` refuses to contain a socket, `linux.py:95-98`), the
egress leaf, and the writable store (`linux.py:338`). A socket that a same-uid
host process created inside the store would therefore be reachable too. This is
a named assumption, not a checked fact: same-uid host processes are trusted
custody, as they already are for the store path and the N3a canonical
ancestors (N3a state review 330-331), and maintenance is excluded by the store
lock. The Linux lane checks the resulting fact affirmatively: an in-zone walk
of the whole zone filesystem (excluding `/proc`) finds `S_ISSOCK` only at
`/vendor-egress.sock`, and a socket planted in the store is found by the same
walk (positive control).

The relay adds the destination, resolver, TLS and lifetime rules. N3b adds no L0
contract, journal row, durable egress record, supervisor change, AppArmor change,
scheduler or second process owner. The production provider stays unavailable.
All peers are controlled harmless fixtures. No credential, vendor traffic,
model call or VM action is involved.

### Which #76 criteria N3b satisfies

| Source | Criterion | N3b share | Carried |
| --- | --- | --- | --- |
| AC1, rev 3:92-94 | native/worker physical separation | Network side: the worker gets no egress mount and no route | Store side is N3a (merged) |
| AC1 | owner-death, old-reaper races, closure | Stream revocation on cancel, deadline and controller death; relay joined before guard release; a successor raced against a stalled old owner | Store-lock races stay N3a evidence; not re-run |
| AC1, rev 3:94 | DNS/TLS/destination denial | All of it, against controlled peers | - |
| AC1 | alias, lock handoff, maintenance exclusion | None | N3a (alias, handoff), N3c (maintenance) |
| rev 3:91-92 | acquisition-scoped egress from ADR 0021 | All of ADR 0021:277-287 that controlled peers can prove | Dynamic endpoints and real startup traffic go to N4 |
| rev 2:196-201 | redirected destinations, DNS/TLS checks, long-lived streams, acquisition cancellation, host death, a successor racing a paused old reaper | All of these | - |
| rev 2:211-212 | prove the actual new mount and egress placement | Linux lane, production runtime | - |
| rev 2:213-214 | generic `network=allow` truthfully; refuse native `network=none` | `none` refusal before allocation; the narrowed `allow` meaning | No generic route is added (see below) |
| AC2, AC3, AC4, AC6 | publication, crash matrix, refresh, overage | None | N3a (AC2, done), N3c |
| AC5 | non-widening; subscription-to-API; pre-model refusal; phase proof | Supplies only a destination set drawn solely from the sealed policy, plus reusable per-destination peer records | N3c; no phase claim here |
| AC7 | credential-free Linux Actions, nothing secret archived | This slice's own evidence | Both |

The schema-3 contract types `network_modes` as `tuple[Literal["allow"], ...]`
and `network_access` as `Literal["native_vendor_session_only"]`
(`core/native_operator.py:80-81`). Every native operator profile's `allow`
therefore carries exactly this narrowed meaning, and N3b proves it. The schema-1
executor profile pairs `allow` with `network_access` `none` or
`provider_route_only` (`core/executor.py:121-122`); N3b adds no route for it and
changes nothing there. The `none` refusal already exists in the grant predicate
(`core/native_operator.py:184-186`) and is tested at contract and admission
level (`tests/core/test_native_operator_contracts.py:319`,
`tests/api/test_native_operator_admission.py:146`). N3b adds one assertion: a
`none` grant never allocates a relay.

### Inputs checked against source

I checked the design brief's citations and they hold, with these corrections:

- The brief calls it unverified that bubblewrap can bind a socket onto a reserved
  file. It has already been measured for the test-only startup image, whose
  builder reserves the leaf with `touch` (`scripts/ci/build_m8_startup_fixture.py:43`).
  `PlacementLauncher` ro-binds a checked socket onto it
  (`tests/provider_placement.py:25-38`), and the placement lane reached the peer
  through it (`M8-provider-placement-evidence.md:32-37`). The production runtime
  reserves no such leaf today (`scripts/ci/build_m8_runtime.py:63` creates
  directories only). The N3b Linux lane is therefore the first execution against
  the production runtime.
- The brief proposes a "resolver log", but the pinned design contains no
  resolver at all. The proof is therefore a substituted system resolver, used
  together with a same-run positive control (see Negative inferences).
- The brief's `relay.closed` decode check would be an equivalent mutant. See
  Relay exit.
- The brief's forced `EGRESS_NOT_ESTABLISHED` is not adopted. See Availability.
- `verify.yml` runs on `ubuntu-latest` under Python 3.11, unprivileged. Linux-only
  unit tests of the relay primitives therefore run in ordinary CI, not only in
  the containment lane.

The native process inherits no relay descriptor. These are affirmative source
facts, not inferences from an absent failure: the supervisor spawns with
`close_fds=True` and passes only `owner_read`, `report_write` and the guards
(`linux.py:607-608`); the relay's sockets are created by Python, so they are
non-inheritable; and the placement evidence recorded "only standard descriptors"
at bootstrap entry (`M8-provider-placement-evidence.md:32-37`).

Reused unchanged: the `--unshare-net` recipe (`linux.py:325`); the probe's
namespace comparison (`linux.py:435-438`); the mount-free probe
(`linux.py:417-421`); the store/workspace exclusion (`linux.py:321-322`); the
supervisor and its deadline reaper; `finish_owned`; the acquisition guard and
closure; `_cleanup_owned`'s cancel-and-join of `self.active` before custody
release (`codex.py:1636-1669`); and the mount-identity pattern of
`PlacementLauncher`.

## Design

### One new module: `substrate/executors/egress.py`

The module is stdlib only, in L1, and imports nothing from `linux.py`.

- `EgressDestination(host, port, address)`, frozen. `host` must match a positive
  DNS-name grammar: lowercase ASCII labels of letters, digits and inner hyphens,
  at most 63 bytes each and 253 in total, no trailing dot, and a final label
  that begins with a letter. That last rule is what excludes every numeric or
  hexadecimal IPv4 spelling (`127.1`, `0x7f.1`, `2130706433`) rather than
  relying on `ipaddress` failing to parse. `port` is an `int` in 1..65535.
  `address` is one literal IP in its canonical `ipaddress` spelling. There is
  exactly one pinned address per destination. It carries no zone id (asyncio
  resolves any dial host containing `%` through `getaddrinfo`), and it is
  globally routable unicast: `is_global`, not multicast, not reserved and not
  IPv6 site-local, so no loopback, private, shared, link-local, documentation
  or unspecified address can be pinned (ADR 0020:275 excludes any localhost
  service inventory). Both were added after the Codex review of `1ec4943`. The
  test suites' controlled peers live on host loopback, so they replace the
  routability predicate `_routable` with one that also admits exactly
  `127.0.0.1`, the way they replace the platform primitives; the zone refusal
  sits outside the predicate and stays real, and nothing in `src` replaces it.
- `EgressPolicy(destinations, connections)`, frozen. `destinations` must be a
  non-empty `tuple` of `EgressDestination`, and `connections` a positive `int`
  (not `bool`), checked before anything is digested, so no mutable container can
  change after its digest was taken. Each `(host, port)` is unique. The policy is
  sealed at provider construction and never mutated. Two constants live in the
  module: the CONNECT head bound (8 KiB) and the ClientHello record bound
  (5 + 16384 bytes).
- `identity_digests(policy)` returns the five content fields of
  `NativeEgressIdentityV1` (`core/native_operator.py:211-222`):
  - `enforcement_build_digest`: the module source;
  - `destination_policy_digest`: the sorted `(host, port)` set;
  - `resolver_policy_digest`: the pinned address map;
  - `tls_assumptions_digest`: the source of the ClientHello rule;
  - `configuration_digest`: the connection bound, the two byte bounds and the
    fixed in-zone destination.

  `physical_conformance_revision` is supplied by whoever ran qualification. It is
  never minted here, as `codex.py:236-240` already does for the other
  conformance revisions.
- Two pure functions:
  - `parse_connect(head) -> (host, port)`;
  - `client_hello_sni(record) -> str`.

  Each one either returns the exact accepted value or raises a classified
  refusal. No other exception may escape either of them.
- `EgressSocket(path, identity)`, frozen. It has a `require_current()` method that
  checks four things with `lstat`: the path is absolute and canonical, it is a
  socket (`S_ISSOCK`), its owner is `getuid()`, and its `(st_dev, st_ino)` equals
  the value recorded at bind. Its refusal text is fixed and names no path.
- `EgressRelay(policy, directory, deadline, check_control)` is an async context
  manager. It exposes two facts:
  - `observed`, a counter of classified outcomes, used only as evidence;
  - `closed`, set only at the end of a clean exit.

  Internally it holds the `_stopping` latch and the owner task recorded at
  entry.
- Two module-level platform primitives are the only things tests substitute:
  - `_bind_private_socket(path)` binds a listening `AF_UNIX` stream socket and
    returns it together with its identity;
  - `_receive(sock, n)` reads with `recvmsg` and a control buffer, closes every
    `SCM_RIGHTS` descriptor, and refuses when any ancillary data or
    `MSG_CTRUNC` is present. This is the accepted fixture law
    (`M8-provider-fixture-proposal.md:149-150`; `_provider_transport.receive`).
    Explicit refusal turns descriptor passing into a counted denial rather than a
    silent kernel discard. It is also what gives each handler one explicit
    buffer that the resume analysis can reason about.

### Relay rules

**Liveness check.** "Live" below means, synchronously: `_stopping` is not set,
the task that entered the relay is not being cancelled (`cancelling() == 0`),
and `loop.time() < deadline`. The owner-cancellation term closes the window in
which the launcher reaps the native tree after an outer cancellation while the
relay would otherwise keep admitting connects; ADR 0020:289 orders "refuses new
connects" first.

For each accepted client connection, in this order:

1. At accept, if the relay is not live, close the connection unread and record
   `stopped` (or `deadline`). Otherwise spend one unit of connection allowance
   before reading anything. If the bound is exceeded, close the connection and
   record `connection_bound`.
2. Read the CONNECT head into the handler's one buffer, up to the head bound and
   `\r\n\r\n`. A head whose terminator does not fit inside the bound is refused.
3. Parse exactly `CONNECT host:port HTTP/1.1`. Header lines are bounded and
   ignored. The following are all refused before any other step, with no name
   resolution: any other method, an absolute-form URI, userinfo, brackets, an IP
   literal, a non-ASCII host, a host outside the grammar, and a `(host, port)`
   outside the policy.
4. Reply `HTTP/1.1 200 Connection established`.
5. Read one TLS record from the same buffer, consuming bytes already buffered
   before reading more. It must meet all of these:
   - content type 22;
   - legacy record version from 0x0301 to 0x0303;
   - length within the bound;
   - handshake type 1, with the handshake length contained exactly in this one
     record (a fragmented hello is refused);
   - exactly one `server_name` extension naming exactly one `host_name` equal to
     the CONNECT host;
   - no `encrypted_client_hello` extension (0xfe0d, GREASE included), wherever
     it appears relative to `server_name`;
   - no duplicate extension.
6. Check liveness, then call `check_control()`.
7. Dial the destination's pinned `address` at the policy port with
   `sock_connect` on a numeric address. The CONNECT host string never reaches
   the dialler.
8. After the dial resumes, repeat check 6. On failure, close the new upstream
   before sending it a byte.
9. Forward the buffered hello record and any buffered remainder, then pump both
   directions with 8 KiB reads. **After every pump read resumes, and before its
   send, check liveness synchronously, in both directions.** On EOF from one
   side, half-close the other side's write and keep the reverse direction until
   its EOF.

Every handler await runs inside `asyncio.timeout_at(deadline)`. The synchronous
rechecks in steps 6, 8 and 9 exist because `timeout_at` alone does not stop a
resumed task: a task wake-up that was already queued runs before timers that
expire in the same loop iteration (`base_events._run_once`), and the first send
of `sock_sendall` is synchronous. The review measured a forward 0.363 s after
the deadline without them (selector loop, Windows).

Every refusal closes the connection with no reply bytes and increments one named
`observed["denied:<reason>"]`. A handler increments `observed["accepted"]` only
after the dial succeeds and the buffered bytes have been sent. A peer reset in
the middle of a stream (`ConnectionError`) is neither a denial nor a relay
failure; it ends that stream and is counted as `reset`. No counter is incremented
in a `finally`.

The relay never terminates TLS, never answers TLS, never injects bytes after
the 200, and has no HTTP client. It therefore cannot follow a redirect. A
redirect to another host reaches it as a new CONNECT and is judged like any
other.

The pinned address and port enforce the network destination; that is the
boundary. **The SNI rule binds only the first ClientHello of a connection and is
not a boundary.** A TLS 1.3 HelloRetryRequest, a pipelined second ClientHello or
a TLS 1.2 renegotiation can carry another SNI or an ECH extension, and none of
them is judged. Each still reaches only the same pinned peer. A record-type state
machine is deliberately not added: a cheap "refuse any second type-22 record"
rule would also refuse TLS 1.2's ClientKeyExchange, and the pinned client's TLS
version is an N4 question. The limit is pinned by a test (see Proof plan).

**No byte budget.** The earlier draft charged an aggregate byte budget but
contradicted itself on what it counted. The only precedent is the test-only
bridge. Relay memory is already bounded per handler by the head and record
bounds and the 8 KiB pump chunk, and connection lifetime is bounded by the
deadline (ADR 0020:294-295). A volume cap bounds no resource and would cut
legitimate long-lived vendor streams, so it is dropped. The connection bound is
kept: it bounds handler tasks and descriptors in the shared controller loop.

### Allocation: where it plugs in

The relay is allocated per execution and inside the task that `_cleanup_owned`
already joins. In `CodexOperatorHandle._converse`, the `self.active` task body
becomes:

```python
self._check_control()
async with EgressRelay(policy, self.paths.payload, deadline, self._check_control) as egress:
    return await launcher.exchange(..., native_store=replace(native_store, egress=egress))
```

When the provider has no policy, the body stays today's bare `exchange`, with no
mount.

- **After the durable lease.** Materialization follows the walker's lease record,
  and `_converse` re-reads durable closure (`codex.py:1459`) before this task is
  created (ADR 0021:285-286; ADR 0020:277-278).
- **Derived from acquisition identity.** The relay allocates in the acquisition's
  own `AcquisitionPaths.payload`. Acquisition ids are derived per binding and
  epoch (`acquisition_id_for(lease_id_for(run, path, binding), epoch)`,
  `codex.py:1827-1828`; the workspace and gate acquisitions derive theirs the
  same way, `git/contained.py:148-150`), so another component's use of
  `paths.payload` for its own acquisition (`git/contained.py:92`,
  `gates/contained.py:324,429`, `git/capture.py:175`) names a different
  directory. The relay does not rely on that alone: it creates `payloads/` 0700
  with `exist_ok`, and creates the payload directory itself exclusively
  (`mkdir` 0700). If the directory already exists, allocation is refused; it is
  never reused or cleaned. The socket is `payload/egress.sock`. After a crash,
  the successor's existing `dispose_acquisition` removes the stale socket and
  directory, and only after it holds the old guard
  (`substrate/git/acquisition.py:179-200`). No new cleanup authority or route
  record exists (ADR 0020:293-294).
- **Path budget.** The socket path is `root` + `/payloads/acq-` + 32 hex +
  `/egress.sock`, a 58-byte suffix (`acquisition.py:37,43-44`). Linux `sun_path`
  holds 108 bytes; the module budget is 107, leaving the terminating NUL, so the
  root may be at most 49 bytes. The provider checks the budget at construction,
  next to its other root checks (`codex.py:1725-1728`), from the actual
  `AcquisitionPaths` layout rather than a hard-coded suffix, and only when an
  egress policy is present. Boundary tests cover the longest accepted and the
  first refused root. The Linux lane gives its tests a short root under `/tmp`;
  a pytest `tmp_path` for `m8-service` would exceed the budget. A bind that still
  fails is refused, never retried.
- **The deadline.** The relay receives the handle's absolute deadline
  (`codex.py:1462`), the one deadline that bounds this acquisition's native work.
  The launcher derives its own deadline from the remaining time a few
  microseconds later (`linux.py:382`), so streams end no later than the native
  process is killed. `EgressRelay` exposes no method that sets or extends the
  deadline.
- **Teardown order.** `_cleanup_owned` publishes closure, cancels `self.active`,
  and gathers it before releasing the guards. Inside that task, the launcher
  reaps the native tree first; the relay's `__aexit__` then refuses connects,
  closes streams and joins its handlers. Both finish before either guard is
  released (ADR 0020:289-290).

**`linux.py`.**
- `NativeStoreMount` gains `egress: EgressSocket | None = None`.
- When it is present, `argv` calls `egress.require_current()` and adds
  `--ro-bind <path> /vendor-egress.sock` before `--`.
- `--unshare-net` is unchanged.
- The mount travels only with a native store, and `argv` already refuses a store
  together with a workspace. A worker launch can therefore never carry it
  (`run()` has no `native_store` parameter, `linux.py:342-359`), and the
  mount-free probe never carries it either.

**`scripts/ci/build_m8_runtime.py`** reserves `vendor-egress.sock` as an
immutable empty regular file. Every other zone therefore sees an empty 0444
file, not a socket. This changes runtime content, and with it the runtime digest
and every qualification that binds it; that is expected and requalifies.

**`codex.py`.**
- `CodexOperatorProvider` takes `egress: EgressPolicy | None = None`.
- When a policy is present, each of the five content fields of `identity.egress`
  must equal `identity_digests(policy)`, and the path budget must hold. The
  checks sit next to the existing drift checks (`codex.py:1747-1761`), where the
  policy is supplied.

**CI.**
- One new step, "Prove N3b acquisition-scoped egress denial", in the
  **foundation** lane directly after the N3a step (`m8-containment.yml:120-141`).
  It reuses the store fixture that step provisions, and runs:
  - `tests/substrate/test_native_egress_containment.py` as `m8-service`, with
    `M8_EGRESS_REQUIRED=1`;
  - `scripts/check_m8_n3b_mutations.py`.
- Add `n3b-*.json` to the artifact list (`m8-containment.yml:299-315`).
- Add the step to `PROOFS`, and the glob assertion, in
  `tests/test_m8_containment_workflow.py:18-25,131`.
- The scope classifier already sends non-prose changes to every lane, so it is
  unchanged.

### Availability

No new forced reason is added. The default reasons already publish
`the native vendor-session egress boundary has not been qualified`
(`codex.py:168-172`). Only a trusted assembly or test that explicitly passes
`unavailable_reasons=()` removes it, and 27 N2/N3a call sites do so to reach the
scripted path. A provider without a policy allocates no relay and adds no mount.
Its namespace keeps only `lo`, which is a stronger denial than the declared mode,
not a widening.

The provider docstring's law that an absent binding "can never be cleared" by an
empty reason tuple (`codex.py:1702-1705`) deliberately does not extend to egress.
An absent store would launch the native zone with no store at all, which is a
broken turn presented as available; an absent egress policy launches it with no
route at all, which can only fail its vendor connection. Neither widens, but the
store case is forced because it is the prerequisite N3a established; forcing the
egress case would rewrite 27 call sites (15+9+1+1+1) to prove nothing new.

A test pins that fact on both sides:
- with no policy, the argv contains no `/vendor-egress.sock` bind and does
  contain `--unshare-net`;
- the default reasons still contain the egress reason.

Nothing at runtime can clear the reason, and nothing here mints
`physical_conformance_revision`.

### Denial versus failure

A **denial** is enforcement working. It is counted in `observed` and is not fatal
to the turn. Denials are:
- a policy, TLS, ancillary, bound or control refusal;
- an accept or connect after stop, or while the owner is being cancelled;
- a deadline cut;
- an unreachable upstream, counted as `upstream_unreachable`.

A **relay failure** is fatal. It is any of these:
- an exception escaping a handler other than the classified outcomes;
- an accept-loop error;
- a teardown error, whether from close, join, unlink or `rmdir`, or a socket
  whose identity changed before exit.

**No failure text is published.** Every allocation failure (a bind or `mkdir`
error, an existing payload, a path over the `sun_path` limit), every handler
failure and every teardown failure is converted inside `egress.py` into a
`ContractViolation` with fixed text, chained `from` the original exception. The
original exception carries private locators: `bounded_detail` only truncates
(`codex_protocol.py:1071-1082`), an `OSError`'s text reaches
`outcome.error.detail` through `_unavailable(str(exc))` (`codex.py:1506-1507`),
and a `mkdir` `FileExistsError` names the full path. The fixed text also means
an unclassified handler exception that is neither `OSError` nor
`ContractViolation` can no longer escape `_converse`. Failures are raised from
`__aexit__` after teardown; with a pending cancellation, the fixed
`ContractViolation` and the cancellation are raised together as a group, which
`_converse` re-raises (`codex.py:1508-1511`) and `_cleanup_owned` splits
(`codex.py:1654-1658`). N3a treated the same leak class as a defect
(`scripts/check_m8_n3a_mutations.py:23-31`). Any of these means refusal, never a
fallback. Denials never enter the published outcome; they appear only in Linux
evidence.

## Lifecycle walk

The following are design obligations, not claims about executed tests.
"Assumes" names what the next step relies on. "Checks" names what it verifies
affirmatively.

| Point | What can already exist when control arrives | Next step assumes vs checks | A raise leaves / a `finally` publishes |
| --- | --- | --- | --- |
| `_converse` `await _require_open()` (`codex.py:1459`) | Close latched, closure committed, control lost | Existing post-await `_check_control` checks it (`codex.py:1297`) | Nothing is allocated. The raise propagates as today |
| `create_task` to the task's first step | `_cleanup_owned` may already have cancelled the task, or the close latch may be set while the task is not yet cancelled | The task body's first statement checks `_check_control()` synchronously, before `mkdir` | A task cancelled before its first step runs no body, so no directory is created. A latched close raises `_LocalClose` before `mkdir` |
| Allocation (`mkdir`, bind, listen, `lstat`): synchronous, no await | A stale payload directory, a too-long path, a bind error | Exclusive `mkdir` checks freshness. `lstat` identity is recorded from the bound path | `__aexit__` does not run when `__aenter__` raises, so `__aenter__` removes its own directory, then raises the fixed-text refusal. It publishes nothing |
| Accept task start | The relay is listening, and the probe is running | Assumed, not checked: no client connects yet. The probe has no mount and the native process is not spawned; a same-uid host process could connect, and same-uid host processes are trusted custody | - |
| Launcher probe await (`linux.py:387`) | Cancellation or close | Cancelling the task cancels `exchange`; `async with` then runs teardown | Teardown, with `closed` unset |
| `argv` (synchronous, `linux.py:457`) | Socket unlinked, replaced or retyped since bind | `require_current()` checks `S_ISSOCK`, owner and `(dev, ino)` | Fixed-text `ContractViolation`, then `unavailable`. The launcher never rebinds or recreates the socket |
| `argv` to bubblewrap's bind | Replacement between the check and bubblewrap resolving the path | Assumed: the 0700 directory is in trusted host custody (same boundary as the N3a store path) | Recorded as a limit, not checked |
| `sock_accept` resumes with a client | Relay not live (stopped, owner cancelling, deadline passed), connection bound spent | Synchronous liveness check, then allowance is spent | Close the connection unread and count it. There is no dial |
| `sock_accept` completed, then cancellation delivered before the accept task steps | An accepted socket exists only inside the completed future | Not checked (see Limits: the orphan closes by reference count) | The socket is not reachable by any relay code |
| CONNECT head read resumes | Partial head, EOF, ancillary descriptors, head bound hit, **ClientHello bytes already buffered after `\r\n\r\n`** | Bytes after the head stay in the one handler buffer, and nothing is forwarded | A classified denial closes the client. Buffered bytes are dropped unforwarded |
| Policy decision (synchronous) | Denied `(host, port)` or IP literal | There is no resolver on any path | A denial with zero upstream connections. The peer sees nothing |
| `sendall(200)` resumes | Client closed; teardown latched | Handled at the next check or by cancellation | Close |
| ClientHello read resumes | The whole hello, a partial hello or several records already buffered; the head arrived pipelined with the hello | The parser consumes the buffer first. Only one record is judged, and it must be complete | Fragmented, oversized, non-handshake, missing SNI, SNI mismatch, ECH, duplicate extension or several host names is a denial. Nothing is forwarded |
| Before dial (synchronous) | Latch set, owner cancelling, deadline passed, `check_control` raising | Check all of them. `check_control` may raise `_LocalClose`, a `CancelledError` subclass (`codex.py:177-179`); because the call is synchronous, the relay catches any exception from this call only as a control denial and sets `_stopping` | Close. Never mistake it for the handler's own cancellation |
| Dial resumes | Stop latched, owner cancelling, deadline passed, control lost, dial failed | Check again after the await | Close the new upstream before any byte. `upstream_unreachable` is a denial |
| Forward of buffered bytes resumes | Upstream closed | - | Close both |
| Pump read resumes | Stop latched, owner cancelling, deadline passed (a queued wake-up runs before the expiring timer), control lost, peer EOF, client EOF, ancillary data mid-stream | Synchronous liveness check, then `check_control()` (a raise latches `_stopping`), before the send, in both directions. Half-close on EOF | Close both halves; the upstream closes abortively, having had zero linger since creation (see Limits: queued bytes). The handler's `finally` closes sockets only and counts nothing |
| Handler finishes | A classified outcome is already counted, or an unclassified exception | The exit collects the terminal state of every handler task it created. Cancellation by teardown is not a failure | - |
| `exchange` returns (native exited) | Handlers still open upstream; a failure is recorded | The relay exit must still revoke streams | - |
| `__aexit__` | Body result, `ProcessExchangeError` or cancellation; open handlers; repeated `cleanup` cancellation | In order: (1) set `_stopping`; (2) cancel the accept task and every handler; (3) join them through `finish_owned`; (4) unlink only if identity still matches, then remove the directory, while the listener still holds the socket's inode (a released inode number can be reused at once; first Linux CI run); (5) close every accepted client, and the listener only after the accept task has finished, so its reader is removed before the descriptor can be reused; (6) raise recorded failures as fixed text (grouped with a pending cancellation); (7) set `closed = True` last | Step (7) never runs in a `finally`. After a raise, nothing reports clean. A substituted socket is never unlinked, and its directory is left for the successor |
| `await self.active` in `_converse` | The outer execute cancelled | Cancelling the awaiting task cancels the inner task and waits for it to complete. `self.active = None` in `finally` runs only after the relay exit has finished (executed in the review's `outer_waits.py`) | - |
| Decode (`codex.py:1514-1533`) | A result or `ProcessExchangeError` | Both reach `_converse` only through a completed `__aexit__` (see Relay exit) | Terminal binding checks as today |
| `_cleanup_owned` | Materializing, executing or idle | Existing: publish closure, cancel and join `self.active`, then release guards | A relay failure during close surfaces as a cleanup error, as the gather split already handles (`codex.py:1646-1659`) |
| Ownership loss | The heartbeat records `OwnershipLost` (`walker.py:429-435`); the walker re-raises without closing the acquisition (`walker.py:1689-1690`); the conversation never calls `check_control` after spawn | Checked at the relay's connect points and after every resumed pump read, before its send (since the Codex review of `1ec4943`; the first form checked connect points only). A raise latches `_stopping` | An established stream forwards nothing read after the loss; an idle one ends at its next read, the relay's stop or the deadline (see Limits). The guards stay held, so a successor waits |
| Controller death | Relay sockets exist only in the dead process; no relay code runs, so nothing is joined in-process | The kernel closes the listener, clients and upstreams; each upstream has had zero linger since creation, so that close is a reset that discards its queue. The supervisor's owner pipe kills the native tree, and its guard copies are held until it has reaped it | Supervisor-observed physical quiescence before successor disposal, not an in-process join: the successor's `dispose_acquisition`, started at the kill, completes only once the guard is free, and then removes the stale `payload/egress.sock` and the directory |
| Controller stalled past the deadline | The native process is reaped by the supervisor (`test_linux_containment.py:723`); upstream sockets are open in the stalled process | Checked in the Linux lane: a successor `dispose_acquisition` started while the upstream is open has not completed, and completes only after the peer sees EOF | A pinned limit (see below) |
| Successor recovery | The old handle is alive or dead | The walker's recovery commits closure, then waits on the old acquisition guard, which the old handle holds until its relay has been joined | A new store-lock wait also excludes overlapping sessions |

**Latches.** Each latch is written once and never reset: `_stopping`; `closed`;
the handle's existing `executed` and `closed`; and the monotonic connection
counter. Nothing refunds the allowance for a refused or incomplete connection.

**The durable fence per connection** is deliberately not re-read, because a Git
read per connect adds nothing the structure lacks. Local close cancels the
relay directly. Ownership loss and cancellation reach `check_control` (the
walker's `_check_run_control`) at connect time and after every resumed pump
read, with its existing latency.
Successor work waits on the guard that the relay's joining owner holds.

### Relay exit is structural

A `ProcessResult` reaches `_converse` in only two ways: as the task's return
value, or as `ProcessExchangeError` raised inside the `async with`. In both, the
exception or value leaves the block only after `__aexit__` has returned without
raising, and a failure raised from `__aexit__` replaces the body's exception. A
separate `relay.closed` check before decode would therefore be unreachable as a
defence, and its mutant would be equivalent. The load-bearing facts are that
`__aexit__` never suppresses and always raises recorded failures. Mutants 20 and
21 target those.

## Negative inferences made affirmative

| Tempting inference | Affirmative replacement |
| --- | --- |
| Zero denials means no auxiliary traffic | Every denial class is driven once in the same run. The counters are live only with that control |
| A decoy peer's empty record means no connection | The decoy is shown to be listening by a host-side connection recorded in the same run. The allowed peer records at least one connection in the same run |
| No resolver call seen means no DNS | `socket.getaddrinfo`/`loop.getaddrinfo` are substituted with a recorder that raises. The test first calls it once itself (positive control), then asserts zero relay calls on both the accepting and refusing paths |
| No route in `/proc/net/route` means egress denied | In-zone attempts assert errnos: TCP and UDP/53 to 192.0.2.1 give `ENETUNREACH`; namespace `127.0.0.1:<peer port>` gives `ECONNREFUSED`; name lookup raises `gaierror`; a host abstract socket that the host can reach (control) gives `ECONNREFUSED` in the zone; an unmounted host socket path gives `ENOENT` |
| No second socket was used, so only the leaf is reachable | The in-zone walk lists every `S_ISSOCK` outside `/proc`; a socket planted in the store is found by the same walk |
| A socket at the path is our relay | `S_ISSOCK` + uid + `(dev, ino)` from bind, checked in `argv`, and identity again before unlink. `(dev, ino)` names the socket only while the relay's listener holds its inode, so both checks run while it does: the unlink precedes the listener's close (added after the first Linux CI run, which measured a released inode number handed to the next file) |
| A clean native exit means streams were revoked | The relay closes every upstream before `__aexit__` returns; the peer's own EOF observation is asserted after the join returns. That is the peer's observation, not the relay's |
| A successful TLS handshake means the relay judged SNI | `observed["accepted"] == 1` is asserted beside the handshake, and each refusal pair drives the same code |
| A handshake succeeded, so the hello was intact | Affirmative: a verified TLS 1.3 handshake fails on any transcript change. The portable test also asserts byte identity at a recording peer |
| A stream ended, so the deadline ended it | `denied:deadline` is recorded, the client was sending continuously, and peer EOF falls between one monotonic clock tick before the deadline (asyncio runs timers up to its clock resolution early) and deadline + 1 s |
| No policy means egress is qualified or irrelevant | The egress reason stays by default; with no policy there is no mount; conformance is never minted |
| `ssl` absent inside the runtime means skip | In the required lane the native client's `import ssl` failing is a test failure, not a skip. The same holds for `openssl` missing on the runner |
| An empty `failures` list means a clean exit | `closed` is set as the last statement of a completed exit, never in `finally` |
| Guards stay held, so no successor proceeds | A successor `dispose_acquisition` is started while a stalled old owner still holds an open upstream; it is asserted incomplete until the peer's EOF |
| A refused outcome leaks nothing because refusals discard fields | The field-walking surface test seeds the acquisition root on the accepting path and on every allocation, handler and teardown failure path |

## Proof plan

Every case exists in a permitting and a refusing direction. The accepting path
comes first in every file.

**Portable** (`tests/substrate/test_egress.py`,
`tests/substrate/test_egress_launch.py` and
`tests/substrate/test_codex_egress.py`). Only `_bind_private_socket` (a loopback
TCP listener plus a stand-in file whose inode is the identity) and `_receive`
(plain `sock_recv`) are substituted, so these run on Windows too.

- A real `ssl` ClientHello over `MemoryBIO` for `allowed.invalid`. The permitting
  side is accepted and forwarded byte-identical to a recording TCP peer. The
  refusing side covers, both as pure parser cases with their reason and as relay
  cases that reach no peer:
  - SNI of another host;
  - SNI absent;
  - an ECH extension spliced into the real hello, before and after `server_name`;
  - a two-record fragmented hello;
  - a non-handshake record;
  - plaintext;
  - an oversized record;
  - a record version below 0x0301 and above 0x0303;
  - a duplicated extension;
  - a `server_name` naming two `host_name` entries.
- CONNECT to a member is accepted. A non-member, an IP literal, the wrong port,
  `GET` absolute-form and an over-bound head are refused with zero peer
  connections. The head bound is tested at its limit: a head of exactly 8 KiB is
  accepted, one byte more is refused.
- A pipelined CONNECT and hello in one send is accepted with the correct SNI, and
  the peer sees exactly the hello. With a wrong SNI it is refused, and the peer
  sees no connection and zero bytes.
- The first-hello limit is pinned: a pipelined second ClientHello naming another
  host is forwarded to the same pinned peer.
- The resolver recorder, with its control: zero calls on the accepting and
  refusing paths.
- The connection bound at the point where it binds: exactly `connections`
  accepted and one more refused.
- The deadline cuts an actively writing stream, and traffic does not extend it.
  An idle handler (a partial head) is cut at the deadline too.
- Teardown: the peer sees EOF once `__aexit__` returns. An accept after stop is
  closed unread and never dials.
- A control raise before the dial is a denial and sets the latch; the upstream is
  never opened. A `_LocalClose` from control is not treated as the handler's own
  cancellation. Control lost while the dial is pending closes the new upstream
  before any byte (the killer for the post-dial recheck).
- Control lost on an established stream: bytes before the loss reach the peer,
  nothing read after it does, the stream is cut with `denied:control`, and the
  latched stop refuses the next connect as `stopped`. (The first form pinned
  the opposite, an established stream forwarding after ownership loss, as a
  limit; the Codex review of `1ec4943` rejected that limit.)
- A destination address that is loopback, private, shared, link-local,
  documentation, unspecified, multicast, reserved or site-local, or that
  carries a zone id, is refused by the real predicate; globally routable IPv4
  and IPv6 addresses are accepted, and the controlled-peer seam admits exactly
  `127.0.0.1` and nothing else.
- `parse_connect`'s own gates, as pure parser cases with their reason: an
  unterminated or non-ASCII head, an extra request-line token, another method
  or version, a zero-padded, signed, missing or over-bound port, userinfo and
  numeric hosts, and IP and bracketed literals; the exact target at port 1 and
  65535.
- An unclassified handler exception makes the exit raise a fixed-text refusal
  and the outcome `unavailable`. With no failure, the exit is clean and `closed`
  is true. A body exception always propagates through the exit.
- Allocation:
  - a fresh payload succeeds;
  - an existing payload is refused and left untouched;
  - a socket replaced before exit is not unlinked, and the exit raises.
- Launcher `argv` (with platform facts substituted, as in
  `test_native_store_launch.py`):
  - a current socket gets exactly one `--ro-bind … /vendor-egress.sock`;
  - a changed `(dev, ino)`, a non-socket or a foreign owner is refused;
  - no egress means no bind, and `--unshare-net` is present in both cases;
  - store plus workspace is refused, as today.
- Provider:
  - matching `identity.egress` is accepted;
  - each of the five drifted fields is refused;
  - no policy keeps the default egress reason;
  - the root budget binds exactly at its longest accepted root.
- Handle, through the actual provider and handle:
  - the relay is listening during the scripted exchange and gone afterwards;
  - close during the exchange joins the relay before the guard owner exits (the
    order is recorded);
  - a close latched after the task is created allocates nothing;
  - a `network="none"` grant creates no payload;
  - a relay failure publishes `unavailable`.
- A field-walking surface-bound test over the published outcome, seeded with the
  acquisition root, the socket path, the pinned address and the denial reasons.
  It runs on an accepted path and a refused path, and on each failure path:
  an existing payload, an over-long path (a bind error that names the path), a
  substituted socket at exit, and an unclassified handler failure.

**Linux unit tests** (Linux-only, unprivileged, run in `verify.yml`), with the
real primitives:
- a real `AF_UNIX` bind and recorded identity;
- `SCM_RIGHTS` refused, with the passed descriptor closed, alongside the same
  bytes accepted without ancillary data;
- a replaced socket refused by `require_current()`, the replacement bound while
  the first listener still holds its inode (the only state the relay checks
  in);
- a real socket replaced before exit is not unlinked, and the exit raises.

**Linux containment** (foundation lane, `m8-service`, the production runtime and
store fixture). The Linux cases drive `EgressRelay` and `launcher.exchange`
directly, as N3a's containment test does (`test_operator_store_containment.py:98`);
the handle path is covered by the portable tests. The native client is inline
harmless Python speaking CONNECT to `/vendor-egress.sock`. A throwaway CA and the
certificates are made with `openssl` in a temporary directory, and the private
keys are never archived. The peers are TLS servers on host `127.0.0.1`. Every
test uses a short acquisition root under `/tmp`.

- Accepted: CONNECT `allowed.invalid:<port>`, then TLS with `CERT_REQUIRED` and
  hostname checking against the throwaway CA, an HTTP request and the peer's
  reply. `observed["accepted"] == 1`.
- Refused, each paired with that accepted case in the same run:
  - CONNECT to the decoy name;
  - CONNECT to an IP literal;
  - SNI mismatch;
  - ECH;
  - a redirect: the allowed peer returns 302 to `decoy.invalid`, the client
    follows, and the relay denies it;
  - direct in-zone TCP, UDP/53 and DNS, with errno assertions;
  - a host abstract socket;
  - an unmounted host socket path.
- The native zone sees `S_ISSOCK` only at `/vendor-egress.sock`; a socket
  planted in the store is found by the same walk. An ordinary worker, through
  `LinuxLauncher.run` with a workspace, sees an empty regular file, and its
  connect is refused with `EACCES`: Linux checks write permission on the path
  before its type, so the 0444 leaf never reaches `ECONNREFUSED`.
- Revocation:
  - Cancel mid-stream: the peer sees EOF after the join returns (asserted within
    2 s).
  - Deadline: an actively streaming client is cut at the deadline.
  - Controller death: a child controller running relay plus exchange is killed
    with SIGKILL. A successor `dispose_acquisition` is started at the kill; it
    completes only after the peer's EOF, and when it completes a non-blocking
    try of the guard's own `flock` is granted: no process holds it. Before the
    kill the same try is refused, the positive control. It removes the stale
    socket. That is
    supervisor-observed physical quiescence, not an in-process join.
  - Controller death with a queue: a child controller floods a peer that never
    reads, so the host send queue toward the peer is non-empty
    (`/proc/net/tcp`) when it is killed. No cleanup runs, yet the queue is gone
    at once and nothing beyond what the peer already held reaches it: only zero
    linger set at the upstream's creation can do that.
- The stalled-controller limit is pinned: a child controller blocks its loop
  past the deadline with an upstream open. Its native process is reaped; no byte
  reaches the peer during the stall (after a settling interval), and at most one
  partial pump write completes after it resumes (see Limits: queued bytes); a
  successor `dispose_acquisition` started in the test process has not completed
  while the upstream is open; after the controller resumes, the peer sees EOF
  and only then does the successor complete. If a later change hosts the relay
  elsewhere, this assertion changes deliberately.
- `n3b-egress.json` records the schema, `credential_free_fixture: true`,
  `vendor_conformance_qualified: false`, the launch revision, the egress
  identity digests, the `observed` counts, the per-peer connection and byte
  counts, and the positive-control results. A test asserts that no evidence file
  contains `-----BEGIN`.

## Mutation inventory

`scripts/check_m8_n3b_mutations.py` uses the shared runner, with the tuple shape
of `scripts/check_m8_n3a_mutations.py`. Only an assertion kill counts. Every
mutant is killed by a portable or Linux-unit test, never by the provisioned
containment tests, because the lane's mutation step runs without the provisioned
environment. The one Linux-only mutant (29) reports NOT PROVEN on Windows,
which is expected; it is measured in the foundation lane. Test files: `E` is
`tests/substrate/test_egress.py`, `L` is `tests/substrate/test_egress_launch.py`,
`C` is `tests/substrate/test_codex_egress.py`.

| # | Mutant | Killing test |
| --- | --- | --- |
| 1 | SNI-equals-CONNECT-host comparison removed | `E::test_a_refused_hello_reaches_no_peer[other-sni]` |
| 2 | Missing-SNI refusal removed | `E::test_client_hello_refusals[no-sni]` |
| 3 | ECH refusal removed | `E::test_client_hello_refusals[ech]` |
| 4 | ECH judged only before `server_name` | `E::test_client_hello_refusals[ech-after-sni]` |
| 5 | Non-ClientHello handshake refusal removed | `E::test_client_hello_refusals[not-client-hello]` |
| 6 | Fragmented-hello (length containment) refusal removed | `E::test_client_hello_refusals[fragmented]` |
| 7 | Record version range upper check removed | `E::test_client_hello_refusals[version-high]` |
| 8 | Duplicate-extension refusal removed | `E::test_client_hello_refusals[duplicate-extension]` |
| 9 | Several-`host_name` refusal removed | `E::test_client_hello_refusals[two-host-names]` |
| 10 | Policy membership check becomes `if False:` | `E::test_a_refused_connect_reaches_no_peer[non-member]` |
| 11 | Hello bytes buffered after the head are dropped | `E::test_a_pipelined_connect_and_hello_is_forwarded_byte_identical` |
| 12 | The dial uses the CONNECT host instead of the pinned address | `E::test_a_pipelined_connect_and_hello_is_forwarded_byte_identical` |
| 13 | The handler's `timeout_at(deadline)` becomes `deadline + 3600` | `E::test_the_deadline_cuts_an_idle_handler` |
| 14 | The accept-path liveness check becomes `False` | `E::test_an_accept_after_stop_is_closed_unread` |
| 15 | The pre-dial control check is removed | `E::test_a_control_raise_before_the_dial_is_a_denial_and_stops_the_relay` |
| 16 | The post-dial recheck is removed | `E::test_control_lost_during_the_dial_closes_the_upstream_before_any_byte` |
| 17 | The pump's liveness and control recheck is removed | `E::test_control_lost_on_an_established_stream_forwards_nothing_more` |
| 18 | Teardown skips cancelling handlers | `E::test_teardown_delivers_peer_eof_once_exit_returns` |
| 19 | The connection bound is off by one | `E::test_the_connection_bound_binds_at_its_limit` |
| 20 | `__aexit__` stops raising recorded failures | `E::test_an_unclassified_handler_failure_is_fatal_at_exit` |
| 21 | `__aexit__` returns `True` (suppresses) | `E::test_the_relay_never_suppresses_the_body_exception` |
| 22 | The exclusive payload `mkdir` becomes `exist_ok=True` | `E::test_an_existing_payload_is_refused_and_left_untouched` |
| 23 | Unlink no longer checks identity | `E::test_a_replaced_socket_is_not_unlinked_and_exit_raises` |
| 24 | The head bound is off by one | `E::test_the_connect_head_bound_binds_at_its_limit` |
| 25 | The host grammar's final-label rule is removed | `E::test_a_policy_refuses_ambiguous_or_mutable_input[numeric-host]` |
| 26 | The policy's tuple requirement is removed | `E::test_a_policy_refuses_ambiguous_or_mutable_input[list]` |
| 27 | Allocation errors are re-raised with their own text | `C::test_no_private_locator_reaches_the_outcome[existing-payload]` |
| 28 | Relay failures are raised with their own text | `C::test_no_private_locator_reaches_the_outcome[handler-failure]` |
| 29 | Ancillary descriptor refusal is removed (Linux-only) | `E::test_ancillary_descriptors_are_closed_and_refused` |
| 30 | The task's pre-allocation control check is removed | `C::test_a_close_latched_after_the_task_is_created_allocates_nothing` |
| 31 | The `identity.egress` drift check is removed | `C::test_a_drifted_egress_identity_is_refused[destination_policy_digest]` |
| 32 | The root budget is off by one | `C::test_the_acquisition_root_budget_binds_at_its_limit` |
| 33 | `/vendor-egress.sock` becomes another path | `L::test_a_current_egress_socket_gets_one_read_only_leaf` |
| 34 | `require_current()` in `argv` is removed | `L::test_a_changed_or_foreign_egress_socket_is_refused[identity]` |
| 35 | `require_current()` no longer checks `S_ISSOCK` | `L::test_a_changed_or_foreign_egress_socket_is_refused[regular-file]` |
| 36 | The owner's `cancelling()` term is dropped from liveness | `E::test_a_cancelled_owner_still_reaping_admits_nothing` |
| 37 | The synchronous deadline term becomes `if False:` | `E::test_a_read_resumed_past_the_deadline_forwards_nothing` |
| 38 | The handle gives the relay a no-op control check | `C::test_control_lost_during_the_exchange_denies_the_connect` |
| 39 | The handle gives the relay `deadline + 3600` | `C::test_the_relay_is_listening_during_the_exchange_and_gone_afterwards` |
| 40 | An upstream is created without zero linger, so its close is graceful | `E::test_nothing_queued_before_the_deadline_reaches_the_peer_after_exit` |
| 41 | Every stream `TimeoutError` counts as `denied:deadline` | `E::test_a_stream_timeout_before_the_deadline_is_a_reset` |
| 42 | The hello record bound is off by one | `E::test_the_hello_record_bound_binds_at_its_limit` |
| 43 | Teardown no longer closes the accepted clients | `E::test_teardown_closes_a_client_whose_handler_never_ran` |
| 44 | Exit closes the listener before releasing the socket path | `E::test_the_socket_is_released_while_the_listener_still_holds_its_inode` |
| 45 | The pump checks liveness only, not control | `E::test_control_lost_on_an_established_stream_forwards_nothing_more` |
| 46 | The routability check is removed | `E::test_a_host_local_or_zoned_address_is_never_admissible[loopback]` |
| 47 | The zone refusal is removed | `E::test_a_host_local_or_zoned_address_is_never_admissible[zone]` |
| 48 | `is_global` is dropped from the predicate | `E::test_a_host_local_or_zoned_address_is_never_admissible[private]` |
| 49 | The multicast term is dropped | `E::test_a_host_local_or_zoned_address_is_never_admissible[multicast]` |
| 50 | The reserved term is dropped | `E::test_a_host_local_or_zoned_address_is_never_admissible[reserved-v6]` |
| 51 | The IPv6 site-local term is dropped | `E::test_a_host_local_or_zoned_address_is_never_admissible[site-local]` |
| 52 | The request-line token count is dropped | `E::test_connect_parser_refusals[extra-token]` |
| 53 | The method gate is dropped | `E::test_connect_parser_refusals[method]` |
| 54 | The version gate is dropped | `E::test_connect_parser_refusals[version]` |
| 55 | The port grammar is dropped | `E::test_connect_parser_refusals[zero-padded-port]` |
| 56 | The port bound is dropped | `E::test_connect_parser_refusals[port-over-bound]` |
| 57 | The host grammar is dropped | `E::test_connect_parser_refusals[userinfo]` |
| 58 | An unbracketed IP literal is no longer its own denial | `E::test_connect_parser_refusals[literal]` |
| 59 | A bracketed literal is no longer its own denial | `E::test_connect_parser_refusals[bracketed]` |
| 60 | The head terminator gate is dropped | `E::test_connect_parser_refusals[unterminated]` |

Mutants 36-43 were added by the implementation review, mutant 44 after the
first Linux CI run, and mutants 45-60 (with 17 and 40 retargeted) after the
Codex review of `1ec4943` (see the implementation record's N3b section).
`parse_connect`'s missing-separator gate has no mutant: without a `:` the
whole target is the port, which the port grammar or the host grammar then
refuses, so removing it is equivalent. The non-ASCII refusal has no mutant
either: removing its `try` turns the refusal into an unclassified error, not a
different verdict.

The existing N3a mutants for `--unshare-net` and store/workspace exclusion are
retained unchanged.

Dropped from the brief's and the first draft's lists, with reasons:
- re-resolution per connection: there is no resolver, and mutant 12 is the live
  form;
- the `relay.closed` decode check: equivalent (see Relay exit);
- a forced `EGRESS_NOT_ESTABLISHED`: not adopted (see Availability);
- the byte-bound mutant: the byte budget is dropped (see Relay rules);
- "buffered bytes forwarded before the SNI decision": the order is structural,
  because no upstream socket exists before the decision; the refused-hello cases
  assert zero peer connections;
- the shielded-accept mutant: the shielded-accept row is dropped (see Review
  disposition, finding 7). Under CPython reference counting the dropped socket
  closes anyway, so the mutant was probably equivalent.

## Limits carried

Each limit is written down, and pinned by an assertion where a test can hold it.

- **Pinned addresses.** There is one literal address per destination, fixed at
  allocation, with no runtime DNS or re-resolution. A moved vendor address
  produces failed connections, never a wider destination. Restoring service needs
  a new sealed policy, which changes the identity and so needs requalification.
  Whether real vendor CDNs make pinning impractical is an N4 finding. The
  routability rule is `ipaddress`'s own classification in the running Python,
  which has changed between patch releases; its edge cases are pinned by the
  address tests on the CI interpreter only. An IPv4-mapped IPv6 spelling of a
  global address is admissible and reaches that IPv4 address.
- **The controlled-peer seam.** The suites replace `_routable` to admit
  `127.0.0.1`. A replaced predicate leaves the egress identity unchanged,
  because `enforcement_build_digest` hashes the module source, exactly as for
  the substituted platform primitives. No production path replaces it, and
  none can without replacing a module attribute.
- **Direct CONNECT client.** The proof client speaks CONNECT to the socket
  itself. The Codex `HTTPS_PROXY` path, and any in-namespace TCP bridge, are an N4
  client-compatibility shim, not part of this boundary. Whether the pinned
  binary's auth, refresh and websocket paths honour the proxy is unverified.
- **Pathname sockets in the store.** The zone reaches any pathname socket that a
  same-uid host process creates inside the writable store. This rests on
  same-uid trusted custody; the in-zone walk checks it only at the time of the
  run.
- **First ClientHello only.** The SNI and ECH rules bind the first ClientHello
  of each connection. A HelloRetryRequest, a pipelined second hello or a TLS 1.2
  renegotiation is not judged; it reaches only the same pinned peer. Pinned by a
  portable test that forwards a second hello naming another host.
- **Ownership loss.** The relay observes control at its connect points and
  after every resumed pump read, before that read's send, so nothing read after
  the loss is forwarded. It is still not continuous: an idle established stream
  stays open until its next read in either direction, the relay's stop or the
  deadline, and the guards stay held meanwhile. `check_control` is the walker's
  synchronous journal read (`cancel_requested`), so an active stream now costs
  one journal read per resumed read (up to one per 8 KiB chunk) in the
  controller's loop; that cost is accepted, not measured. (The first form
  observed control at connect points only and pinned an established stream
  forwarding after the loss; the Codex review of `1ec4943` rejected that.)
- **Stalled-controller sockets.** If the controller's event loop is blocked past
  the deadline, its upstream sockets stay open until it resumes, and the guards
  stay held. The relay reads and forwards nothing during the stall, but the
  kernel keeps transmitting what the relay queued before it, up to the upstream
  socket's send buffer (see Queued bytes). The Linux pin measures zero bytes
  during the stall only after a 0.5 s settle, against a peer that reads
  continuously; it includes a concurrent successor. Hosting the relay in the
  supervisor was rejected: it would put the policy, the CONNECT parser and the
  ClientHello parser inside the stdlib-only trusted reaper and make that reaper
  a network peer, for one limit whose exposure is an open socket that carries
  nothing read after the stop.
  (The first draft's reason, that it "would change runtime content", was wrong:
  this design changes runtime content too, by reserving the leaf.)
- **Queued bytes.** Bytes the relay hands the kernel sit in the upstream
  socket's send queue until the peer's window takes them. The first
  implementation closed the upstream gracefully, so that queue kept reaching
  the pinned peer after the deadline, after exit and after the guards were
  released: a review probe measured 599,538 bytes reaching a peer that read
  only after exit (Windows; Linux send-buffer autotuning allows more). Every
  upstream close is now abortive (`SO_LINGER` zero): the peer gets a reset and
  the kernel discards the queue. The linger is set when the upstream socket is
  created, before any byte can queue, so the close the kernel performs for a
  killed controller, where no cleanup runs, is abortive too (the Codex review
  of `1ec4943`: the first form set it only in cleanup). A Linux containment
  test kills a controller with a non-empty queue toward a non-reading peer and
  asserts the queue gone and nothing beyond what the peer held. That includes a stream that ended cleanly in
  both directions, because a graceful close would keep sending after exit too;
  the cost is that a peer that half-closed and then reads slowly can lose the
  tail of what the client sent. What can still reach the peer after a stop or
  the deadline is only what the kernel transmits before the handler's close
  runs: the queue as it stood at the stop, plus the unsent remainder of one
  pump chunk, because `sock_sendall` finishes a partial write from an I/O
  callback that runs before a timer expiring in the same iteration and never
  passes the liveness check. Never a byte read after the stop. That window is
  one loop step, or the whole stall of a blocked controller. A portable test
  with a non-reading peer pins that nothing queued reaches it after exit; the
  Linux stalled-controller test still asserts at most one chunk after resume.
  In this document and the tests, a peer "sees EOF" when its stream ends, by a
  reset included.
- **An accept completed during teardown.** If the accept future completes in the
  same loop iteration that cancels the accept task, the accepted socket is
  reachable only through that future. No relay code reads, dials or forwards
  for it. It is not closed by the relay: the cancelled task's traceback can
  retain it until the garbage collector frees the relay's tasks, so the client
  may see no EOF until then. That is reasoning from the handler case below, not
  measured for this case.
- **A handler cancelled before its first step.** Teardown can cancel a handler
  that the accept loop created in the same iteration; its `finally` never runs.
  The relay keeps every accepted client and closes them all after the join, so
  the client sees EOF. Such a connection is counted in no `observed` key.
- **Payload left after a teardown failure.** If a normally closed lease's relay
  exit fails (for example a replaced socket), its payload directory stays. The
  lease is disposed by the ordinary close path, not by `reconcile`, which handles
  only stale rows (`codex.py:1868-1901`), so nothing removes that directory. It
  is inert: no later acquisition can reuse it, because allocation is exclusive
  and ids are per acquisition.
- **Native TLS validation** of the vendor peer is an N4 qualification
  assumption, not N3b evidence. The Linux lane's own client validates against a
  throwaway CA, which proves the relay kept the transcript intact, not how the
  pinned binary validates.
- **Dynamic endpoints and real startup traffic** belong to N4 (ADR 0021:282-283).
  Controlled peers prove refusal, not the vendor's actual destination set.
- **No phase-separation claim.** Destination enforcement does not prove that
  initialization and inference are separated (ADR 0021:263-265; #76 AC5). That
  belongs to N3c and N4.
- **TLS observation.** The relay sees only the first ClientHello record. HTTP
  `Host` inside TLS is invisible. Fronting to another virtual host on a pinned
  shared address, with an allowed SNI, is not excluded by the relay; the pinned
  address and the client's own TLS validation bound it. A multi-record hello, or
  any ECH extension including GREASE, is refused. If the pinned client emits
  either, N4 finds the profile unavailable, not widened.
- **Trusted custody** of the socket path covers the gap between the `argv` check
  and bubblewrap's bind (same-uid host processes). This is the same boundary as
  the N3a canonical ancestors.
- **Path length.** The 107-byte budget is conservative reasoning about Linux
  `sun_path`; it has not been measured. A bind that still fails is refused.
- **Evidence only.** Denials are not published in the outcome. Provider-side
  acceptance after teardown is not claimed exactly once (ADR 0020:296).
  `vendor_conformance_qualified` stays false.
- **Unexecuted until Linux CI runs.** The real bind, `recvmsg` and ancillary
  refusal, the `sun_path` limit, the socket leaf in the production runtime,
  pathname-socket reach through `/vendor-store`, the Linux `mkdir` error text,
  `ssl` inside the runtime, `openssl` on the runner, the in-zone errno
  assertions, the zone socket walk, controller death, the stalled-controller pin
  and its concurrent successor have no execution until Linux CI runs them.
  Windows skips are not passes. The abortive close has run on Windows only; how
  Linux discards the queue on reset is reasoning until CI runs the portable
  test there. The first Linux CI run executed most of these; what it
  established, what failed and what is still unexecuted is recorded in the
  implementation record's "First Linux CI run".

## Rejected as unnecessary

- New L0 types or fields: `NativeEgressIdentityV1` already has them, and any
  change would move the law revision.
- The relay in the supervisor (see Limits).
- An in-namespace bridge or bootstrap.
- A hosts file.
- One socket per destination.
- nftables or veth.
- A DNS stub.
- Relay telemetry in the outcome.
- A durable egress record.
- A per-connection durable closure read.
- A fifth CI lane.
- A 403 reply on refusal: closing with no reply leaks nothing and needs no
  second code path.
- Multiple addresses per destination.
- A `relay.closed` decode check.
- A byte budget (see Relay rules).
- A TLS record-type state machine (see Relay rules).

## Review disposition

Classification follows AGENTS.md: introduced, pre-existing, or a design choice
disagreed with. Only the first two block.

| # | Finding | Class | Disposition |
| --- | --- | --- | --- |
| 1 | P1: the private locator leaks into the published outcome through allocation and teardown error text; an unclassified handler failure escapes `_converse` | introduced | Adopted. Fixed-text `ContractViolation ... from exc` for every allocation, handler and teardown failure; four seeded surface cases; mutants 27-28 |
| 2 | P2: the pump forwards bytes after the deadline or stop | introduced | Adopted. Synchronous liveness recheck after every pump read, both directions; mutant 17 |
| 3 | P2 (Codex P1): the store mount is a second socket route | introduced overclaim | Adopted as P2. Boundary narrowed to name the same-uid assumption; in-zone socket walk with a planted-socket control |
| 4 | P2 (Codex P1): later ClientHellos are never inspected | introduced overclaim | Adopted as P2. SNI stated as first-hello only and not a boundary; limit pinned; parser refusals and mutants 4, 7, 8, 9 added |
| 5 | P2: the socket path budget is effectively about 49 bytes of root | introduced | Adopted. Construction-time check from the actual layout, boundary tests, mutant 32, short Linux root. The dirfd alternative is not taken: it would need Linux measurement first |
| 6 | P2 (Codex P1): ownership loss and the paused-old-owner race | introduced (missing proof and limit) | Adopted as P2. Limit written down; ownership loss after the dial pinned portably; the stalled test races a successor |
| 7 | P2: the shielded-accept row does not work | introduced | Adopted the YAGNI option. Row and mutant dropped; reference-count close recorded as a limit |
| 8 | P2: mutation inventory defects | introduced | Adopted. Delayed-dial control-loss killer for the post-dial recheck; `__aexit__` suppression mutant; renumbered; every killing test named |
| 9 | P3 (Codex P1): no forced egress unavailability reason | design choice | Not adopted; the reason the "can never be cleared" law does not extend to egress is recorded under Availability |
| 10 | P3: teardown closes the listener while the accept reader is registered | introduced | Adopted. Accept task cancelled and joined before the listener closes |
| 11 | P3: the relay keeps dialling during the launcher's reap after an outer cancellation | introduced | Adopted. The owner task's `cancelling()` is part of every liveness check |
| 12 | P3: the byte budget contradicts itself | design choice | Adopted by dropping the byte budget; the connection bound is kept, with its reason |
| 13 | P3: negative inferences left in the document | introduced | Adopted. The `network_modes=`, `paths.payload` and "no client exists" statements are now source facts or named assumptions |
| 14 | P3: smaller specification gaps | introduced | Adopted: tuple-only policy validated before digesting; positive DNS grammar; the orphaned-payload limit; the corrected supervisor-rejection reason; the affirmative descriptor facts; the Linux revocation route (direct `exchange`); native TLS validation as an N4 assumption |

Rejected, with reasons:

- **Codex #6's main counterexample** (omit the mount in `linux.py` while the
  egress digest stays stable): `LinuxLauncher.revision` hashes `linux.py`
  (`linux.py:303-311`), and the provider refuses `isolation_revision` and
  `runtime_digest` drift (`codex.py:1754-1761`). Changing it forces a new
  identity and requalification.
- **Codex #2, #3 and #4 as P1:** downgraded; see findings 6, 3 and 4.
- **Codex #10 on the connection bound:** it bounds descriptors and handler tasks
  in the shared controller loop.
- **SCM_RIGHTS refusal as YAGNI:** it is accepted fixture law
  (`M8-provider-fixture-proposal.md:149-150`).
- **Abstract sockets:** they are scoped by network namespace, and
  `--unshare-net` is at `linux.py:325`.
- **AppArmor blocking the connect:** both profiles allow `unix` and `network`
  (`scripts/ci/constructicon-m8-launch.apparmor`).
- **A read-only bind blocking connect:** the placement lane measured it working.
- **A worker carrying the mount:** `run()` has no `native_store` parameter
  (`linux.py:342-359`), and argv refuses store plus workspace
  (`linux.py:321-322`).
- **Deadline ordering:** the launcher's deadline is at or after the relay's,
  since `linux.py:382` computes it later than `codex.py:1462`.
- **Row 323:** executed in the review's `outer_waits.py`; the outer task resumes
  only after the relay's `__aexit__` finishes.
- **Payload collision with workspace or gate acquisitions:** ids are derived
  per binding (`git/contained.py:148-150`).
- **A durable per-connection record:** not required (ADR 0020:292-294).

The review's pre-implementation questions (whether any await admits a dial or
forward from stale state; whether teardown is joined before guard release on
every path; whether any path reaches an unpinned destination; whether allocation
is safe against disposal; whether any refusal publishes locators; and what the
design had not considered) were answered by findings 1-14 above. These
amendments address its blocking findings. The amended text itself has not been
re-reviewed; a narrow follow-up review of these amendments and of the
implementation is still owed.

### Codex review of the implementation (`1ec4943`)

One independent Codex pass (job `job_b21d1b3a3fbb`) reviewed head `1ec4943`.
It is the only Codex round on this slice; its fixes are verified by tests,
mutants and self-review, not by another model pass. Each premise was
reproduced against source before acting; for findings 2 and 3 a probe on the
selector loop showed `EgressDestination` accepting `127.0.0.1`, `10.0.0.1`,
`224.0.0.1`, `::1` and `fe80::1%eth0`, and `sock_connect` to `fe80::1%eth0`
calling a recorded `loop.getaddrinfo` once. Details and verification are in the
implementation record.

| # | Finding | Class | Disposition |
| --- | --- | --- | --- |
| 1 | The writable `/vendor-store` bind can hold a pathname socket planted by a same-uid host process | pre-existing design choice | Rejected, see below |
| 2, 3 | A destination may pin loopback, private, link-local or multicast addresses, and a scoped IPv6 address sends the dial through `getaddrinfo` | introduced | Fixed. Globally routable unicast only, and no zone id. The controlled peers use a test-only predicate seam that admits exactly `127.0.0.1`. Mutants 46-51 |
| 4 | An established stream never re-checks control, and a test pinned bytes reaching the peer after ownership loss | introduced | Fixed. The pump runs liveness and `check_control` after every resumed read, before its send, latching stop. The pinning test is replaced by one proving nothing read after the loss is forwarded. Mutants 17 (retargeted) and 45 |
| 5 | Zero linger is set only in cleanup, so a killed controller's upstream drains its queue | introduced | Fixed. Linger is set at creation (`_upstream`). A Linux containment test kills a controller with a non-empty queue. Mutant 40 retargeted. The `sock_sendall` partial-write limit stays recorded: a checked send loop would be a third substituted primitive for a window of one chunk |
| 6 | The controller-death claim implied a join the killed controller cannot perform | introduced overclaim | Narrowed to supervisor-observed physical quiescence before successor disposal; the test now starts the successor at the kill and asserts the ordering and an empty guard-holder scan with its positive control |
| 7 | `parse_connect`'s gates and the new checks had no mutants | introduced | Adopted. Mutants 52-60 with pure parser cases and their reasons; two gates recorded as having no meaningful mutant (see Mutation inventory) |

**Rejected: finding 1.** The store bind and the pathname sockets that a same-uid
host process can create in it are N3a's accepted design. Same-uid host
processes are trusted store custody, and maintenance is excluded by the store
lock. The in-zone socket walk with its planted-store control proves the
current state affirmatively (see Limits: pathname sockets in the store). This
is not a new N3b hole; an OS-enforced socket-free store is out of scope.
