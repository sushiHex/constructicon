# M8 N3b: state and resume review

Status: pre-implementation design; independent review pending. Base: `6bc9500`.
Scope: N3b of [issue 76](https://github.com/sushiHex/constructicon/issues/76).
Authority: [ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md)
lines 277-287, which preserve the destination-restriction design of
[ADR 0020](../../adr/0020-native-harnesses-mediate-contained-tools.md) lines
266-296, and [M8 rev 3, N3](../milestones/M8-live-executors-rev3.md) lines 89-116.
This record does not amend any of them. No implementation code exists. None is
written until an independent source-based review accepts or corrects this design.

## Boundary and reuse

N3b adds acquisition-scoped `native_vendor_session_only` egress. It adds a
host-side CONNECT relay that permits only fixed destinations. The native zone
reaches it through one read-only socket leaf, bound into the network namespace
the zone already has. The namespace is the physical boundary (I1). The relay adds
the destination, resolver, TLS and lifetime rules. N3b adds no L0 contract,
journal row, durable egress record, supervisor change, AppArmor change,
scheduler or second process owner. The production provider stays unavailable.
All peers are controlled harmless fixtures. No credential, vendor traffic,
model call or VM action is involved.

### Which #76 criteria N3b satisfies

| Source | Criterion | N3b share | Carried |
| --- | --- | --- | --- |
| AC1, rev 3:92-94 | native/worker physical separation | Network side: the worker gets no egress mount and no route | Store side is N3a (merged) |
| AC1 | owner-death, old-reaper races, closure | Stream revocation on cancel, deadline and controller death; relay joined before guard release | Store-lock races stay N3a evidence; not re-run |
| AC1, rev 3:94 | DNS/TLS/destination denial | All of it, against controlled peers | - |
| AC1 | alias, lock handoff, maintenance exclusion | None | N3a (alias, handoff), N3c (maintenance) |
| rev 3:91-92 | acquisition-scoped egress from ADR 0021 | All of ADR 0021:277-287 that controlled peers can prove | Dynamic endpoints and real startup traffic go to N4 |
| rev 2:196-198 | redirected destinations, DNS/TLS checks, long-lived streams, acquisition cancellation, host death | All of these | - |
| rev 2:211-212 | prove the actual new mount and egress placement | Linux lane, production runtime | - |
| rev 2:213-214 | generic `network=allow` truthfully; refuse native `network=none` | `none` refusal before allocation; the narrowed `allow` meaning | No generic route is added (see below) |
| AC2, AC3, AC4, AC6 | publication, crash matrix, refresh, overage | None | N3a (AC2, done), N3c |
| AC5 | non-widening; subscription-to-API; pre-model refusal; phase proof | Supplies only a destination set drawn solely from the sealed policy, plus reusable per-destination peer records | N3c; no phase claim here |
| AC7 | credential-free Linux Actions, nothing secret archived | This slice's own evidence | Both |

`grep network_modes=` over `src` finds no executor profile that offers a generic
`network="allow"`. The only `allow` profiles are the schema-3 native fixtures in
`tests/`, whose meaning `native_vendor_session_only` narrows. N3b proves that
narrowed meaning. The `none` refusal already exists in the grant predicate
(`core/native_operator.py:184-186`) and is tested at contract and admission
level (`tests/core/test_native_operator_contracts.py:319`,
`tests/api/test_native_operator_admission.py:146`). N3b adds one assertion: a
`none` grant never allocates a relay. It adds no generic route.

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

- `EgressDestination(host, port, address)`, frozen. `host` is a lowercase ASCII
  DNS name with no trailing dot and no IP literal. `address` is one literal IP,
  parsed by `ipaddress` at construction. There is exactly one pinned address per
  destination.
- `EgressLimits(connections, total_bytes)`, frozen, with positive integers and no
  defaults. Two constants live in the module: the CONNECT head bound (8 KiB) and
  the ClientHello record bound (5 + 16384 bytes).
- `EgressPolicy(destinations, limits)`, frozen. Each `(host, port)` is unique.
  The policy is sealed at provider construction and never mutated.
- `identity_digests(policy)` returns the five content fields of
  `NativeEgressIdentityV1` (`core/native_operator.py:211-222`):
  - `enforcement_build_digest`: the module source;
  - `destination_policy_digest`: the sorted `(host, port)` set;
  - `resolver_policy_digest`: the pinned address map;
  - `tls_assumptions_digest`: the source of the ClientHello rule;
  - `configuration_digest`: the limits plus the fixed in-zone destination.

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
  the value recorded at bind.
- `EgressRelay(policy, directory, deadline, check_control)` is an async context
  manager. It exposes three facts:
  - `observed`, a counter of classified outcomes, used only as evidence;
  - `_stopping`, a latch;
  - `closed`, set only at the end of a clean exit.
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

For each accepted client connection, in this order:

1. Spend one unit of connection allowance before reading anything. If the bound
   is exceeded, close the connection and record `connection_bound`.
2. Read the CONNECT head into the handler's one buffer, up to the head bound and
   `\r\n\r\n`. Every received byte is charged to the aggregate byte budget,
   whether or not it is ever forwarded.
3. Parse exactly `CONNECT host:port HTTP/1.1`. Header lines are bounded and
   ignored. The following are all refused before any other step, with no name
   resolution: any other method, an absolute-form URI, userinfo, brackets, an IP
   literal, a non-ASCII host, and a `(host, port)` outside the policy.
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
   - no `encrypted_client_hello` extension (0xfe0d, GREASE included);
   - no duplicate extension.
6. Synchronously check that `_stopping` is not set, that
   `loop.time() < deadline`, and that `check_control()` returns.
7. Dial the destination's pinned `address` at the policy port with
   `sock_connect` on a numeric address. The CONNECT host string never reaches
   the dialler.
8. After the dial resumes, repeat check 6. On failure, close the new upstream
   before sending it a byte.
9. Forward the buffered hello record and any buffered remainder, then pump both
   directions with 8 KiB reads. On EOF from one side, half-close the other side's
   write and keep the reverse direction until its EOF.

Every handler await runs inside `asyncio.timeout_at(deadline)`. Every refusal
closes the connection with no reply bytes and increments one named
`observed["denied:<reason>"]`. A handler increments `observed["accepted"]` only
after the dial succeeds and the buffered bytes have been sent. No counter is
incremented in a `finally`.

The relay never terminates TLS, never answers TLS, never injects bytes after
the 200, and has no HTTP client. It therefore cannot follow a redirect. A
redirect to another host reaches it as a new CONNECT and is judged like any
other.

The pinned address enforces the network destination. The SNI rule narrows the
TLS virtual host on a shared address. Neither observes anything after the
ClientHello (see Limits).

### Allocation: where it plugs in

The relay is allocated per execution and inside the task that `_cleanup_owned`
already joins. In `CodexOperatorHandle._converse`, the `self.active` task body
becomes:

```python
self._check_control()
async with EgressRelay(policy, self.paths.payload, deadline, self._check_control) as egress:
    return await launcher.exchange(..., native_store=NativeStoreMount(..., egress=egress))
```

When the provider has no policy, the body stays today's bare `exchange`, with no
mount.

- **After the durable lease.** Materialization follows the walker's lease record,
  and `_converse` re-reads durable closure (`codex.py:1459`) before this task is
  created (ADR 0021:285-286; ADR 0020:277-278).
- **Derived from acquisition identity.** The relay allocates in the acquisition's
  own `AcquisitionPaths.payload`, which the Codex handle does not otherwise use
  (`grep paths.payload` over the executors finds nothing). It creates `payloads/`
  0700 with `exist_ok`. It creates the payload directory itself exclusively
  (`mkdir` 0700). If the directory already exists, allocation is refused; it is
  never reused or cleaned. The socket is `payload/egress.sock`. After a crash,
  the successor's existing `dispose_acquisition` removes the stale socket and
  directory, and only after it holds the old guard
  (`substrate/git/acquisition.py:179-200`). No new cleanup authority or route
  record exists (ADR 0020:293-294).
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
  together with a workspace. A worker launch can therefore never carry it, and
  the mount-free probe never carries it either.

**`scripts/ci/build_m8_runtime.py`** reserves `vendor-egress.sock` as an
immutable empty regular file. Every other zone therefore sees an empty 0444
file, not a socket.

**`codex.py`.**
- `CodexOperatorProvider` takes `egress: EgressPolicy | None = None`.
- When a policy is present, each of the five content fields of `identity.egress`
  must equal `identity_digests(policy)`. The check sits next to the existing
  drift checks (`codex.py:1747-1761`), where the policy is supplied.

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
- an accept after stop;
- a deadline cut;
- an unreachable upstream, counted as `upstream_unreachable`.

A **relay failure** is fatal. It is any of these:
- an exception escaping a handler other than the classified outcomes;
- an accept-loop error other than the listener being closed by the relay itself;
- a teardown error, whether from close, join, unlink or `rmdir`.

Failures are recorded as they happen and raised from `__aexit__` after
teardown. `_converse` already converts `ContractViolation`/`OSError` and
non-cancellation groups into an `unavailable` outcome (`codex.py:1506-1511`).
Allocation failures are handled the same way: a bind or `mkdir` error, an
existing payload, or a Unix path over the `sun_path` limit. Any of them means
refusal, never a fallback. Denials never enter the published outcome. They
appear only in Linux evidence.

## Lifecycle walk

The following are design obligations, not claims about executed tests.
"Assumes" names what the next step relies on. "Checks" names what it verifies
affirmatively.

| Point | What can already exist when control arrives | Next step assumes vs checks | A raise leaves / a `finally` publishes |
| --- | --- | --- | --- |
| `_converse` `await _require_open()` (`codex.py:1459`) | Close latched, closure committed, control lost | Existing post-await `_check_control` checks it (`codex.py:1297`) | Nothing is allocated. The raise propagates as today |
| `create_task` to the task's first step | `_cleanup_owned` may already have cancelled the task | The task body's first statement checks `_check_control()` synchronously, before `mkdir` | A task cancelled before its first step runs no body, so no directory is created |
| Allocation (`mkdir`, bind, listen, `lstat`): synchronous, no await | A stale payload directory, a too-long path, a bind error | Exclusive `mkdir` checks freshness. `lstat` identity is recorded from the bound path | `__aexit__` does not run when `__aenter__` raises, so `__aenter__` closes the socket, unlinks it if its identity matches, removes its own directory, then raises. It publishes nothing |
| Accept task start | The relay is listening, and the probe is running | No client exists: the probe has no mount and the native process is not spawned. Host same-uid processes are trusted custody | - |
| Launcher probe await (`linux.py:387`) | Cancellation or close | Cancelling the task cancels `exchange`; `async with` then runs teardown | Teardown, with `closed` unset |
| `argv` (synchronous, `linux.py:457`) | Socket unlinked, replaced or retyped since bind | `require_current()` checks `S_ISSOCK`, owner and `(dev, ino)` | `ContractViolation`, then `unavailable`. The launcher never rebinds or recreates the socket |
| `argv` to bubblewrap's bind | Replacement between the check and bubblewrap resolving the path | Assumed: the 0700 directory is in trusted host custody (same boundary as the N3a store path) | Recorded as a limit, not checked |
| `sock_accept` resumes with a client | `_stopping` set, deadline passed, connection bound spent | Synchronous checks of the latch and the deadline, then allowance is spent | Close the connection unread and count it. There is no dial |
| `sock_accept` future completed, then cancellation delivered | An accepted socket exists only inside the completed future | Accept is awaited through `shield` on an owned future. On cancellation, if that future holds a result, close that socket | The socket is not left to the garbage collector |
| CONNECT head read resumes | Partial head, EOF, ancillary descriptors, head bound hit, **ClientHello bytes already buffered after `\r\n\r\n`** | Bytes after the head stay in the one handler buffer, and nothing is forwarded | A classified denial closes the client. Buffered bytes are dropped unforwarded |
| Policy decision (synchronous) | Denied `(host, port)` or IP literal | There is no resolver on any path | A denial with zero upstream connections. The peer sees nothing |
| `sendall(200)` resumes | Client closed; teardown latched | Handled at the next check or by cancellation | Close |
| ClientHello read resumes | The whole hello, a partial hello or several records already buffered; the head arrived pipelined with the hello | The parser consumes the buffer first. Only one record is judged, and it must be complete | Fragmented, oversized, non-handshake, missing SNI, SNI mismatch or ECH is a denial. Nothing is forwarded |
| Before dial (synchronous) | Latch set, deadline passed, `check_control` raising | Check all three. `check_control` may raise `_LocalClose`, a `CancelledError` subclass (`codex.py:177-179`); because the call is synchronous, the relay catches any exception from this call only as a control denial and sets `_stopping` | Close. Never mistake it for the handler's own cancellation |
| Dial resumes | Stop latched, deadline passed, control lost, dial failed | Check again after the await | Close the new upstream before any byte. `upstream_unreachable` is a denial |
| Forward of buffered bytes resumes | Upstream closed | - | Close both |
| Pump reads and writes resume | Budget spent, peer EOF, client EOF, ancillary data mid-stream, deadline | Budget is charged before forwarding. Half-close on EOF | Close both halves. The handler's `finally` closes sockets only and counts nothing |
| Handler finishes | A classified outcome is already counted, or an unclassified exception | A done-callback records an unclassified exception into `failures`. Cancellation by teardown is not a failure | - |
| `exchange` returns (native exited) | Handlers still open upstream; a failure is recorded | The relay exit must still revoke streams | - |
| `__aexit__` | Body result, `ProcessExchangeError` or cancellation; open handlers; repeated `cleanup` cancellation | In order: (1) set `_stopping`; (2) close the listener; (3) cancel accept and every handler; (4) join through `finish_owned`; (5) unlink only if identity still matches, then remove the directory; (6) raise recorded failures (grouped with a pending cancellation); (7) set `closed = True` last | Step (7) never runs in a `finally`. After a raise, nothing reports clean. A substituted socket is never unlinked |
| `await self.active` in `_converse` | The outer execute cancelled | Cancelling the awaiting task cancels the inner task and waits for it to complete. `self.active = None` in `finally` runs only after the relay exit has finished | - |
| Decode (`codex.py:1514-1533`) | A result or `ProcessExchangeError` | Both reach `_converse` only through a completed `__aexit__` (see Relay exit) | Terminal binding checks as today |
| `_cleanup_owned` | Materializing, executing or idle | Existing: publish closure, cancel and join `self.active`, then release guards | A relay failure during close surfaces as a cleanup error, as the gather split already handles (`codex.py:1646-1659`) |
| Controller death | Relay sockets exist only in the dead process | The kernel closes the listener, clients and upstreams. The supervisor's owner pipe kills the native tree, and its guard copies are held until quiescence | Stale `payload/egress.sock` and the directory are removed by the successor's `dispose_acquisition` after the guard is free |
| Controller stalled past the deadline | The native process is reaped by the supervisor (`test_linux_containment.py:723`); upstream sockets are open in the stalled process | Assumed: they carry no native bytes (the native side is dead), and the guards stay held, so no successor proceeds | A pinned limit (see below) |
| Successor recovery | The old handle is alive or dead | The walker's recovery commits closure, then waits on the old acquisition guard, which the old handle holds until its relay has been joined | A new store-lock wait also excludes overlapping sessions |

**Latches.** Each latch is written once and never reset: `_stopping`; `closed`;
the handle's existing `executed` and `closed`; and the monotonic connection and
byte counters. Nothing refunds the allowance for a refused or incomplete
connection.

**The durable fence per connection** is deliberately not re-read, because a Git
read per connect adds nothing the structure lacks. Local close cancels the
relay directly. Ownership loss and cancellation reach `check_control` (the
walker's `_check_run_control`), which is inherited with its existing latency.
Successor work waits on the guard that the relay's joining owner holds.

### Relay exit is structural

A `ProcessResult` reaches `_converse` in only two ways: as the task's return
value, or as `ProcessExchangeError` raised inside the `async with`. In both, the
exception or value leaves the block only after `__aexit__` has returned without
raising, and a failure raised from `__aexit__` replaces the body's exception. A
separate `relay.closed` check before decode would therefore be unreachable as a
defence, and its mutant would be equivalent. The load-bearing facts are that
`__aexit__` never suppresses and always raises recorded failures. Mutants 16 and
17 target those.

## Negative inferences made affirmative

| Tempting inference | Affirmative replacement |
| --- | --- |
| Zero denials means no auxiliary traffic | Every denial class is driven once in the same run. The counters are live only with that control |
| A decoy peer's empty record means no connection | The decoy is shown to be listening by a host-side connection recorded in the same run. The allowed peer records at least one connection in the same run |
| No resolver call seen means no DNS | `socket.getaddrinfo`/`loop.getaddrinfo` are substituted with a recorder that raises. The test first calls it once itself (positive control), then asserts zero relay calls on both the accepting and refusing paths |
| No route in `/proc/net/route` means egress denied | In-zone attempts assert errnos: TCP and UDP/53 to 192.0.2.1 give `ENETUNREACH`; namespace `127.0.0.1:<peer port>` gives `ECONNREFUSED`; name lookup raises `gaierror`; a host abstract socket that the host can reach (control) gives `ECONNREFUSED` in the zone |
| A socket at the path is our relay | `S_ISSOCK` + uid + `(dev, ino)` from bind, checked in `argv`, and again before unlink |
| A clean native exit means streams were revoked | The peer observes EOF before `cleanup`/`exchange` returns. That is the peer's observation, not the relay's |
| A successful TLS handshake means the relay judged SNI | `observed["accepted"] == 1` is asserted beside the handshake, and each refusal pair drives the same code |
| A handshake succeeded, so the hello was intact | Affirmative: a verified TLS 1.3 handshake fails on any transcript change. The portable test also asserts byte identity at a recording peer |
| A stream ended, so the deadline ended it | `denied:deadline` is recorded, the client was sending continuously, and peer EOF falls between the deadline and deadline + 1 s |
| No policy means egress is qualified or irrelevant | The egress reason stays by default; with no policy there is no mount; conformance is never minted |
| `ssl` absent inside the runtime means skip | In the required lane the native client's `import ssl` failing is a test failure, not a skip. The same holds for `openssl` missing on the runner |
| An empty `failures` list means a clean exit | `closed` is set as the last statement of a completed exit, never in `finally` |

## Proof plan

Every case exists in a permitting and a refusing direction. The accepting path
comes first in every file.

**Portable** (`tests/substrate/test_egress.py`, plus handle cases next to
`tests/substrate/test_codex_store.py`). Only `_bind_private_socket` (a loopback
TCP listener) and `_receive` (plain `recv`) are substituted, so these run on
Windows too.

- A real `ssl` ClientHello over `MemoryBIO` for `allowed.invalid`. The permitting
  side is accepted and forwarded byte-identical to a recording TCP peer. The
  refusing side covers:
  - SNI of another host;
  - SNI absent;
  - an ECH extension spliced into the real hello;
  - a two-record fragmented hello;
  - a non-handshake record;
  - plaintext;
  - an oversized record.
- CONNECT to a member is accepted. A non-member, an IP literal, the wrong port,
  `GET` absolute-form and an over-bound head are refused with zero peer
  connections.
- A pipelined CONNECT and hello in one send is accepted with the correct SNI, and
  the peer sees exactly the hello. With a wrong SNI it is refused, and the peer
  sees no connection and zero bytes.
- The resolver recorder, with its control: zero calls on the accepting and
  refusing paths.
- Bounds at the point where they bind: exactly `connections` accepted and one
  more refused; exactly `total_bytes` forwarded and one byte more cuts the
  stream.
- The deadline cuts an actively writing stream, and traffic does not extend it.
- Teardown: the peer sees EOF before `__aexit__` returns. An accept after stop
  never dials. A completed accept that is then cancelled closes its socket.
- A control raise before the dial is a denial and sets the latch; the upstream is
  never opened. A `_LocalClose` from control is not treated as the handler's own
  cancellation.
- An unclassified handler exception makes the exit raise and the outcome
  `unavailable`. With no failure, the exit is clean and `closed` is true.
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
  - no policy keeps the default egress reason.
- Handle, through the actual provider and handle:
  - the relay is listening during the scripted exchange and gone afterwards;
  - close during the exchange joins the relay before the guard owner exits (the
    order is recorded);
  - close before the task starts creates no payload;
  - a `network="none"` grant creates no payload;
  - a relay failure publishes `unavailable`.
- A field-walking surface-bound test over the published outcome, on both an
  accepted and a refused path. It seeds the socket path, the pinned address and
  the denial reasons, and asserts that none of them appears in any field.

**Linux unit tests** (Linux-only, unprivileged, run in `verify.yml`), with the
real primitives:
- a real `AF_UNIX` bind and recorded identity;
- `SCM_RIGHTS` refused, with the passed descriptor closed, alongside the same
  bytes accepted without ancillary data;
- a replaced socket refused by `require_current()`.

**Linux containment** (foundation lane, `m8-service`, the production runtime and
store fixture). The native client is inline harmless Python speaking CONNECT to
`/vendor-egress.sock`. A throwaway CA and the certificates are made with
`openssl` in a temporary directory, and the private keys are never archived. The
peers are TLS servers on host `127.0.0.1`.

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
- The native zone sees `S_ISSOCK` at `/vendor-egress.sock`. An ordinary worker,
  through `LinuxLauncher.run` with a workspace, sees an empty regular file, and
  its connect is refused.
- Revocation:
  - Cancel mid-stream: the peer sees EOF before the join returns.
  - Deadline: an actively streaming client is cut at the deadline.
  - Controller death: a child controller running relay plus exchange is killed
    with SIGKILL; the peer sees EOF, and the native tree is reaped by the
    supervisor.
- The stalled-controller limit is pinned: with the loop blocked past the
  deadline, the native process is dead, the upstream connection is still open,
  zero bytes arrive after the native death marker, and after resume the peer
  sees EOF before cleanup returns. If a later change hosts the relay elsewhere,
  this assertion changes deliberately.
- `n3b-egress.json` records the schema, `credential_free_fixture: true`,
  `vendor_conformance_qualified: false`, the launch revision, the egress
  identity digests, the `observed` counts, the per-peer connection and byte
  counts, and the positive-control results. A test asserts that no evidence file
  contains `-----BEGIN`.

## Mutation inventory

`scripts/check_m8_n3b_mutations.py` uses the shared runner, with the tuple shape
of `scripts/check_m8_n3a_mutations.py`. Only an assertion kill counts.
Linux-only mutants (15, 18) report NOT PROVEN on Windows, which is expected;
they are measured in the foundation lane. Each kill test is named in the
inventory.

1. Policy membership check becomes `if False:`.
2. SNI-equals-CONNECT-host comparison is removed.
3. Missing-SNI refusal is removed.
4. ECH refusal is removed.
5. Non-handshake / non-ClientHello refusal is removed.
6. Fragmented-hello (length containment) refusal is removed.
7. Hello is read from a fresh `_receive` instead of the handler buffer
   (killed by the pipelined case).
8. Buffered bytes are forwarded before the SNI decision.
9. The dial uses the CONNECT host instead of the pinned address (killed by the
   resolver recorder).
10. The relay's `timeout_at(deadline)` becomes `deadline + 3600`.
11. The accept-path stop-latch check becomes `False`.
12. The post-dial latch/control recheck becomes `False`.
13. Teardown skips cancelling handlers (killed by "peer EOF before exit returns").
14. The connection bound is off by one.
15. The byte bound is off by one.
16. Ancillary descriptor refusal is removed (Linux-only).
17. `__aexit__` stops raising recorded failures.
18. A completed-then-cancelled accept no longer closes its socket.
19. The task's pre-allocation control check is removed (killed by "close before
    start creates no payload").
20. The exclusive payload `mkdir` becomes `exist_ok=True`.
21. Unlink no longer checks identity (killed by the replaced-socket case).
22. `/vendor-egress.sock` becomes another path.
23. `require_current()` in `argv` is removed.
24. The `identity.egress` drift check is removed.

The existing N3a mutants for `--unshare-net` and store/workspace exclusion are
retained unchanged.

Dropped from the brief's list, with reasons:
- re-resolution per connection: there is no resolver, and mutant 9 is the live
  form;
- the `relay.closed` decode check: equivalent (see Relay exit);
- a forced `EGRESS_NOT_ESTABLISHED`: not adopted (see Availability).

## Limits carried

Each limit is written down, and pinned by an assertion where a test can hold it.

- **Pinned addresses.** There is one literal address per destination, fixed at
  allocation, with no runtime DNS or re-resolution. A moved vendor address
  produces failed connections, never a wider destination. Restoring service needs
  a new sealed policy, which changes the identity and so needs requalification.
  Whether real vendor CDNs make pinning impractical is an N4 finding.
- **Direct CONNECT client.** The proof client speaks CONNECT to the socket
  itself. The Codex `HTTPS_PROXY` path, and any in-namespace TCP bridge, are an N4
  client-compatibility shim, not part of this boundary. Whether the pinned
  binary's auth, refresh and websocket paths honour the proxy is unverified.
- **Stalled-controller sockets.** If the controller's event loop is blocked past
  the deadline, its upstream sockets stay open until it resumes. They carry no
  native bytes, and the guards stay held. This is pinned in the Linux lane. The
  alternative, hosting the relay in the supervisor, was rejected because it
  would change runtime content and the stdlib-only reaper for this one limit.
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
- **Path length.** An acquisition root long enough to exceed `sun_path` fails
  allocation (fail-closed). There is no early construction-time check.
- **Evidence only.** Denials are not published in the outcome. Provider-side
  acceptance after teardown is not claimed exactly once (ADR 0020:296).
  `vendor_conformance_qualified` stays false.
- **Unexecuted until Linux CI runs.** The real bind, `recvmsg` and ancillary
  refusal, the socket leaf in the production runtime, `ssl` inside the runtime,
  `openssl` on the runner, the in-zone errno assertions, controller death and
  the stalled-controller pin have no execution until Linux CI runs them. Windows
  skips are not passes.

## Rejected as unnecessary

- New L0 types or fields: `NativeEgressIdentityV1` already has them, and any
  change would move the law revision.
- The relay in the supervisor.
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
- A construction-time path-length check.
- A `relay.closed` decode check.

## Pre-implementation review questions

The independent review must answer these before code is written:

1. At every await in the ledger, can buffered bytes, a completed accept, a
   control raise, or a latched stop exist in a state that later code treats as
   permission to dial or forward?
2. Is relay teardown joined before either guard is released on every path:
   normal return, `ProcessExchangeError`, outer cancellation, repeated close, and
   a relay failure during close?
3. Can any path reach a destination other than a pinned `(address, port)`,
   including through the resolver, an IP-literal CONNECT, a redirect, or a
   worker launch?
4. Is the payload-directory allocation safe against the existing acquisition
   disposal and reconciliation, including after controller death?
5. Is "denial not fatal, relay failure fatal" consistent with ADR 0021, and does
   any refusal publish private locator data?
6. What has this design not thought about at all?

Any negative answer stops implementation for design correction. A green gate or
an empty fault list is not approval.
