# M8 N4 preparation: the proxy bridge

Status: pre-implementation design, independently reviewed once (Codex, job
`job_8257a0ea4e68`, at `c1c3131`) and amended; see
[Review disposition](#review-disposition). Implemented in `c5e7d98` and
`56713c6`; results, deviations and unexecuted proofs are in the
[M8 implementation record](M8-implementation-record.md#n4-preparation-proxy-bridge).
Credential-free N4 preparation.
Base: `6c41ca3`. Branch: `m8/n4-proxy-bridge`.
Scope: the client-compatibility half of the N3b egress path, carried to N4
([issue 77](https://github.com/sushiHex/constructicon/issues/77)) by the N3b
record: "the pinned Codex client's `HTTPS_PROXY` path".
Authority: [ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md)
lines 277-287 and
[ADR 0020](../../adr/0020-native-harnesses-mediate-contained-tools.md) lines
266-296, unchanged. Nothing here amends a frozen plan, qualifies a vendor
destination, or makes the provider available.

N3b gave the native zone one way out: the read-only socket leaf
`/vendor-egress.sock` (`egress.py:51`), bound into the zone's route-less
`--unshare-net` namespace (`linux.py:327-344`), leading to the host-side
CONNECT relay. N3b proved it with a harmless client that speaks CONNECT to the
leaf directly. The pinned Codex client does not do that. This document
establishes, against the pinned source, how that client reaches a proxy, and
designs the smallest in-zone shim that lets it reach the relay.

## Findings against the pinned source

Pinned source: `openai/codex` tag `rust-v0.153.4`, commit
`3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`. Paths are relative to
`codex-rs/`. Dependency sources are not vendored in that tree; they were read
from their upstream tags at the exact versions in `Cargo.lock` (reqwest
0.12.28 at `Cargo.lock:11990`, hyper-util 0.1.20, the tungstenite forks at the
revisions in `Cargo.toml:606-607`). Those reads were not diffed against the
crates.io tarballs, and each such claim says so. Nothing here was executed; the
Linux proof below is where the client's proxy use is first measured.

### (a) Which proxy variables the client honours

**The HTTP clients honour `HTTPS_PROXY` by default, through reqwest's own
system-proxy detection, not through Codex code.**

- The workspace takes reqwest 0.12 with default features on
  (`Cargo.toml:415`), which include `system-proxy` (reqwest `Cargo.toml:37`,
  upstream tag).
- Codex builds nearly every HTTP client through one builder,
  `HttpClientBuilder::base_reqwest_builder`
  (`http-client/src/client_builder.rs:276-298`). It never calls `.proxy()`; it
  adds `.no_proxy()` only for `ProxyRouting::Direct` (`client_builder.rs:268-274`).
- The routing policy comes from the feature flag `respect_system_proxy`, which
  is `UnderDevelopment` and off by default (`features/src/lib.rs:1214-1219`,
  mapped at `core/src/config/mod.rs:1625-1631`). Off means
  `OutboundProxyPolicy::ReqwestDefault`, which leaves the builder unchanged
  (`http-client/src/outbound_proxy.rs:320-321, 475`).
- An unchanged reqwest builder installs `ProxyMatcher::system()`
  (`auto_sys_proxy`, reqwest `async_impl/client.rs:309, 419-420`, upstream tag).
  On Linux that is hyper-util's `Matcher::from_system()`, which reads only the
  environment: `ALL_PROXY`/`all_proxy`, `HTTP_PROXY`/`http_proxy`,
  `HTTPS_PROXY`/`https_proxy` and `NO_PROXY`/`no_proxy`, upper case first
  (hyper-util `matcher.rs:228-248`, upstream tag).
- For an `https` destination it uses `HTTPS_PROXY`, falling back to
  `ALL_PROXY`; `HTTP_PROXY` is never used for `https` (hyper-util
  `matcher.rs:317`). If `REQUEST_METHOD` is set, every environment proxy is
  ignored (hyper-util `matcher.rs:305-311`).
- With the policy flag on, Codex's own resolver reads the same variables on
  Linux, where the platform lookup is always unavailable
  (`outbound_proxy.rs:352-375, 575-583, 868-873`), and applies the URL with
  `reqwest::Proxy::all` (`outbound_proxy.rs:490-496`).

**The websocket transports honour it too, through the forked tungstenite.**
The workspace enables tokio-tungstenite's `proxy` feature
(`Cargo.toml:479-482, 497`). The fork's `connect_socket` calls
`ProxyConfig::from_env` and, when a proxy is set, TCP-connects to the proxy and
tunnels with CONNECT (tokio-tungstenite fork `connect.rs:108-122`, upstream
rev). For `wss` the order is `HTTPS_PROXY`, then `HTTP_PROXY`, then
`ALL_PROXY`, upper case first, empty ignored, `NO_PROXY` honoured (tungstenite
fork `proxy.rs:95-116`, upstream rev). An `https://` proxy URL is refused on
this default path (`proxy.rs:198-201`).

**No transport accepts a Unix-socket proxy.**

- No Codex source calls reqwest's `ClientBuilder::unix_socket`. That option is
  in any case a whole-client transport that disables proxies, not a proxy mode
  (reqwest `async_impl/client.rs:1798-1812`, upstream tag).
- hyper-util's environment parser accepts only `http`, `https` and `socks*`
  schemes; any other scheme is dropped, silently (hyper-util
  `matcher.rs:333-350`). `HTTPS_PROXY=unix:///vendor-egress.sock` would make the
  client go **direct**, which in the zone means no route: it fails closed, but
  it fails.
- The tungstenite fork rejects any scheme but `http`, `socks5`, `socks5h` with
  `UnsupportedProxyScheme` (`proxy.rs:192-202`).
- The only Unix-socket upstream in the tree is the macOS-only `x-unix-socket`
  escape of the separate `network-proxy` crate (`network-proxy/src/upstream.rs:34,
  152-158`), which serves sandboxed child commands, not the app-server's own
  clients, and is behind an experimental flag that is off
  (`features/src/lib.rs:1204-1212`).

So the client can reach a proxy only as `http://host:port` over TCP. **A shim
is required.** The proxy address must be an IP literal: the zone has no
resolver, and the literal means neither the proxy host nor, through CONNECT,
the origin host is resolved in the zone (reqwest resolves only the proxy's
host; the origin name travels in the CONNECT line).

`HTTPS_PROXY` alone is sufficient and is the only variable the shim sets. It
covers `https` (hyper-util) and `wss` (tungstenite, first in its order). Plain
`http` destinations would use `HTTP_PROXY`; with it unset they go direct and
fail, which is the right result because the relay admits only TLS.

### (b) Every network path of `codex app-server`

"Proxied" means the path's client applies the environment proxy as above.
"Bypasses" means it connects directly; in the zone that has no route, so the
path **fails** rather than escapes. "Unknown" means the client's proxy handling
was not read.

**The column is a compatibility claim, never a security claim.** Containment
does not depend on any client honouring `HTTPS_PROXY`: the namespace has no
route, and the only pathname socket the zone can reach besides the store is the
leaf, behind which the relay judges every byte. A path that ignores the proxy
fails; it cannot escape. The rows below say which paths will work through the
bridge, which is an N4 question, not which are contained.

| Path | Trigger | Client | Proxy |
| --- | --- | --- | --- |
| OAuth token refresh, `https://auth.openai.com/oauth/token` (`login/src/auth/manager.rs:197`; override env `CODEX_REFRESH_TOKEN_URL_OVERRIDE`, `:199`) | Logged in, token near expiry or rejected | `create_client()` (`manager.rs:793, 817`) via `build_default_client` (`login/src/auth/default_client.rs:302-310`) | Proxied |
| Auth endpoints (login, device code, revoke) | Login RPCs | `create_raw_auth_client` / `create_default_auth_client` through the factory (`default_client.rs:314-332`) | Proxied |
| Workload-identity token exchange | Workload identity selected | `build_direct` for a loopback token URL, else the proxy policy (`workload-identity/src/exchange.rs:46-60`) | Proxied unless the URL is loopback (bypasses, fails) |
| Account and rate-limit reads (`account/rateLimits/read` and siblings) | JSON-RPC request, logged in | `BackendClient::from_auth` (`app-server/src/request_processors/account_processor.rs:1146-1153`) over `RouteAwareClientPool` (`backend-client/src/client.rs:162-181`), built at `http-client/src/route_aware_client_pool.rs:751-767` | Proxied |
| Responses API over HTTP (SSE) and compact | A turn | `create_client_for_route` (`core/src/client.rs:1124-1136`), which under the default policy is `create_client()` (`default_client.rs:257-261`) | Proxied |
| Responses API over websocket | A turn with the websocket transport | `WebSocketConnector::connect` (`codex-api/src/endpoint/responses_websocket.rs:519-521`) to `dialer::connect` (`websocket-client/src/dialer.rs:36-131`), default route `connect_async_tls_with_config` (`dialer.rs:45-55`) | Proxied (tungstenite env) |
| Realtime websocket | Realtime session RPC | `connect_async_tls_with_config` (`codex-api/src/endpoint/realtime_websocket/methods.rs:965-974`) | Proxied (tungstenite env) |
| Remote models list (`/models`) | Only with Codex-backend (ChatGPT) auth or command auth (`models-manager/src/manager.rs:436-437`) | `endpoint_client.list_models` (`manager.rs:414-418`) | Proxied (factory) |
| Analytics events, `{base}/codex/analytics-events/events` (`analytics/src/client.rs:141`) | Only with auth (`client.rs:835-848`) | `create_client()` (`client.rs:896`) | Proxied |
| OTel export, `otlp-http` | Metrics: `[analytics] enabled` and a metrics exporter; the `codex app-server` default is analytics off unless `--analytics-default-enabled` (`cli/src/main.rs:590-591`). Built at startup (`app-server/src/lib.rs:586-599`), flushed at shutdown (`app-server/src/otel_reloader.rs:108-110`, `otel/src/metrics/client.rs:300-308`) | Bare `reqwest` builders, no `no_proxy` (`otel/src/otlp.rs:106, 152`), handed to the exporters (`otel/src/metrics/client.rs:640`, `otel/src/provider.rs:490`) | Proxied (reqwest default) |
| OTel export, `otlp-grpc` (`config/src/types.rs:550-571`) | Same, with a gRPC exporter configured | Tonic exporter (`otel/src/metrics/client.rs:588-616`), not reqwest | **Unknown** (tonic's proxy handling unread). Fails or reaches the relay; never escapes |
| Built-in Statsig metrics, `https://ab.chatgpt.com/otlp/v1/metrics` (`otel/src/config.rs:9`) | The metrics exporter default (`config/src/types.rs:624`) when analytics is enabled, release builds only (`otel/src/config.rs:15-22`) | As above | Proxied |
| Feedback upload (Sentry DSN, `feedback/src/lib.rs:57-58`) | `feedback/upload` RPC | `RouteAwareClientPool` (`feedback/src/lib.rs:551-605`) | Proxied |
| Curated plugin sync (`api.github.com`, `github.com/openai/plugins.git`, `chatgpt.com/backend-api/plugins/export/curated`; `core-plugins/src/startup_sync.rs:23-30`) | App-server startup plugin tasks when plugins are enabled and no remote catalog is active (`core-plugins/src/manager.rs:693-707`; startup at `app-server/src/lib.rs:924-928`) | First a `git` subprocess (`startup_sync.rs:185-230`), then an HTTP fallback through the factory (`startup_sync.rs:307`, `startup_sync/http_client`) | Git: whatever the subprocess does with the environment, **unknown** here (the production runtime copies `/usr/bin/git` without its `https` remote helper, `scripts/ci/build_m8_runtime.py:39-40`, so it fails). HTTP fallback: proxied |
| Remote control (`/wham/remote/control/...`) enroll and websocket | Persisted or explicit remote-control state (`app-server-transport/src/transport/remote_control/mod.rs:950-956`) | Enroll: `create_client_without_request_logging` (`remote_control/enroll.rs:62, 157`); websocket: `connect_async` (`remote_control/websocket.rs:1362`) | Proxied (both) |
| MCP servers over streamable HTTP | Configured MCP servers | `RouteAwareHttpClient` (`exec-server/src/client/route_aware_http_client.rs:77-116`), used by the rmcp adapter (`rmcp-client/src/rmcp_client.rs:21, 76`) | Proxied |
| Code-mode gRPC host | A code-mode host launch argument (`app-server/src/main.rs:27, 89`) with the `code_mode_host` feature (`app-server/src/lib.rs:555-570`); the adapter's fixed command passes none (`codex.py:165`) | `http(s)` URL: `reqwest::Client::builder()` via the factory (`code-mode/src/grpc_session/transport.rs:93-97`). `unix:` endpoint: a tonic Unix-socket channel (`transport.rs:57-64`) | `http(s)`: proxied. `unix:`: bypasses; it reaches only pathname sockets the zone mounts, which the in-zone walk shows are the leaf alone |
| `process/spawn` subprocesses | A client JSON-RPC request; only Constructicon's conversation writes the app-server's stdin | The child inherits the app-server's environment plus overrides (`app-server/src/request_processors/process_exec_processor.rs:69-108`), so it sees `HTTPS_PROXY` | Whatever the child does; not an app-server client. Contained by the namespace |
| Stdio MCP servers and hook commands | Configuration | Subprocesses in the zone; their environment inheritance was not traced | Unknown; contained by the namespace |
| Update check (`api.github.com/repos/openai/codex/releases/latest`) | `codex doctor` and the TUI only (`cli/src/doctor/updates.rs:43`, `tui/src/updates.rs`); the app-server only reports the requirement (`app-server/src/request_processors/config_processor.rs:488`) | Not reached by `app-server` | Not applicable |
| Any client when `CODEX_SANDBOX=seatbelt` | That variable set (macOS seatbelt) | `build_direct_with_custom_ca_fallback` (`default_client.rs:302-307, 353-355`) | Bypasses (fails). The launcher's `--clearenv` never sets it (`linux.py:330-333`) |

Three facts from the table matter to N4:

1. **Every app-server path to a vendor destination is proxy-capable.** No
   vendor path needs a second mechanism; the shim serves them all.
2. **Several auxiliary paths exist and some fire without a model request**:
   OTel export (config-gated, at startup and shutdown), curated plugin sync (at
   startup, when plugins are enabled), remote control (persisted state). Through
   the shim each becomes a CONNECT that the relay denies as `destination`
   unless its host is sealed. The N4 sealed configuration and destination set
   decide which of them may exist; this slice decides nothing about them.
3. **The relay counts a denial by reason only.** It does not record which host
   was refused. N4's startup-traffic evidence will need the refused
   `(host, port)`; that is carried, not built here.

### (c) TLS roots and SNI

- **Default HTTP TLS is native-tls** (OpenSSL on Linux): reqwest picks it when
  `default-tls` is on and `http3` is off (reqwest `tls.rs:589-594`, upstream
  tag), and Codex's own comment agrees
  (`http-client/src/tls_backend_fallback.rs:3`). Its root discovery on the musl
  package is OpenSSL's, **unverified** here.
- **Custom CA:** `CODEX_CA_CERTIFICATE`, falling back to `SSL_CERT_FILE`, empty
  meaning unset (`http-client/src/custom_ca.rs:61-62, 398-410`). Either forces
  rustls with the bundle added to the built-in roots (`custom_ca.rs:300-331`).
- **Websocket TLS** is rustls with `rustls_native_certs::load_native_certs()`
  plus the custom CA (`websocket-client/src/lib.rs:57-76`,
  `custom_ca.rs:242-286`).
- **OTel exporters** take their CA from configuration: `tls.ca-certificate`
  replaces the built-in roots (`otel/src/otlp.rs:101-117`,
  `config/src/types.rs:542-548`).
- **SNI through a CONNECT proxy is the origin host**, not the proxy: native-tls
  connects with `dst.host()` over the tunnel, rustls builds
  `ServerName::try_from(dst.host())` (reqwest `connect.rs:826-829, 870-875`,
  upstream tag); the websocket takes the domain from the request
  (tokio-tungstenite `tls.rs:132, 203`, upstream rev). The relay's first-hello
  rule (SNI equals the CONNECT host) therefore matches the client's behaviour.
  SNI is the proxy's host only for TLS *to* an `https://` proxy
  (`websocket-client/src/dialer.rs:109`), which the shim never offers.
- **The CONNECT head, as the clients write it** (dependency source read from
  the upstream tags and revisions, not the vendored tarballs):
  - hyper-util's tunnel writes `CONNECT {host}:{port} HTTP/1.1\r\n`, then
    `Host: {host}:{port}\r\n`, then optional headers, then `\r\n`
    (`tunnel.rs:167-197`). The port is always present, `dst.port()` defaulting
    to 443 (`tunnel.rs:144-147`). reqwest passes the client's default
    `User-Agent` into the tunnel (reqwest `connect.rs:810-823, 855-868`), and a
    header map writes names lower case, so Codex's default client, which sets
    `USER_AGENT` (`login/src/auth/default_client.rs:335-339`), sends a
    `user-agent: codex_cli_rs/...` line. It writes nothing before the head, reads
    until the reply starts with `HTTP/1.1 200` or `HTTP/1.0 200` and ends with
    `\r\n\r\n`, refusing any other status, and starts TLS only after that
    (`tunnel.rs:199-230`).
  - The tungstenite fork writes the same request line and `Host`, always adds
    `Proxy-Connection: Keep-Alive`, sends no `User-Agent` (fork `proxy.rs:333-344`,
    `proxy.rs:44`), waits for any 2xx and **drops bytes that arrive after
    `\r\n\r\n` in the same read** (`proxy.rs:49-84`).
  - Hosts arrive lower case because every Codex call site builds a `url::Url`,
    whose special-scheme host parse lower-cases through `idna`
    (url `parser.rs:1048`, `host.rs:81, 109`; the `idna` step itself unread).
    Neither CONNECT writer lower-cases on its own.
- **The relay accepts those heads, by its source.** `parse_connect` judges only
  the request line; header lines are ignored and bounded by the caller
  (`egress.py:204-227`, bound `CONNECT_HEAD_BYTES` 8192 at `egress.py:56, 638-641`).
  Its reply is exactly `HTTP/1.1 200 Connection established\r\n\r\n`
  (`egress.py:64`), sent once, before it reads the ClientHello, with nothing
  after it (`egress.py:648`), so neither reqwest's status rule nor tungstenite's
  dropped-tail behaviour is triggered. The portable suite drives both head
  shapes through the forwarder into the real relay.
- **The head size is far below the bound.** The pinned user agent is
  `"{originator}/0.153.4 ({os type} {os version}; {arch}) {terminal}"` plus
  `" ({clientInfo.name}; {clientInfo.version})"`
  (`login/src/auth/default_client.rs:164-188`). The originator and the suffix
  come from `initialize`'s `clientInfo` (`app-server/src/request_processors/initialize_processor.rs:81-139`),
  which the adapter fixes to `constructicon` and `0` (`codex.py` `CLIENT_NAME`,
  `CLIENT_VERSION`). The terminal token comes from the environment, which
  `--clearenv` empties; the OS segments come from the immutable runtime
  (`os_info` source unread). A realistic head is about 200 bytes against 8192,
  so the bound does not change.

## Design

**The forwarder is a client-compatibility shim, not a boundary (I1).** The
relay stays the one enforcement point: destination, resolver, TLS, lifetime.
The forwarder has no policy, parses nothing, answers nothing and originates no
byte. It is a loopback TCP listener in the zone whose every accepted
connection is joined, byte for byte, to one new connection to the leaf.
Removing it, killing it or bypassing it cannot widen egress: the zone keeps no
route, and the only thing the forwarder can reach is what the zone can already
reach directly, the leaf.

In five lines:

1. The trusted launcher, and only when it mounts the egress leaf, runs the
   vendor command through one fixed in-zone script,
   `/usr/libexec/constructicon-egress-bridge.py`, from the immutable runtime.
2. The script refuses unless `/vendor-egress.sock` is a socket, then binds
   `127.0.0.1:18080` and listens, synchronously.
3. It forks the forwarder, which owns the only copy of the listener, detaches
   from the payload's stdio and writes one readiness byte before it accepts.
4. The script reads that byte (EOF means refuse, no sleep, no poll), then
   `execve`s the vendor command with `HTTPS_PROXY=http://127.0.0.1:18080`
   added to the launcher's environment.
5. Lifetime needs no new owner: the forwarder is a process of the existing
   private PID namespace, so trusted PID 1 terminates and reaps it with the
   payload, before the supervisor releases the acquisition guards.

### Placement

- **Why in the zone.** The listener must be in the zone's network namespace,
  where the client connects. The host cannot listen there without entering the
  namespace, and the launcher has no such authority.
- **Why a separate process, not PID 1.** The trusted PID 1
  (`_supervisor.supervise_namespace`) is a synchronous reaper with
  `PR_SET_DUMPABLE` cleared. Adding network I/O to it would grow the trusted
  init. The forwarder, like the payload, runs as the zone's uid, and the
  payload could signal or trace it. That is acceptable only because it is not a
  boundary: whatever the payload does to it, the payload could equally do by
  connecting to the leaf itself.
- **Why exec, not supervise.** The script replaces itself with the vendor
  binary, so the payload pid, stdio and exit status that PID 1 observes are the
  vendor's, unchanged. The forwarder is its child until the exec'd vendor exits,
  then PID 1's.
- **Why in the launcher.** `LinuxLauncher.argv` already decides, from
  `native_store.egress`, whether the leaf is mounted (`linux.py:342-344`). The
  bridge prefix is added at the same decision, so the forwarder travels only
  with the leaf: no worker launch and no leaf-less native launch can get one.
  The script is content of the immutable runtime (installed by
  `build_m8_runtime.py` beside the supervisor), so its bytes are covered by the
  runtime digest, and the launcher recipe digest covers the prefix.
- **Why a fixed port.** The namespace is private to one execution and the
  listener is bound before the vendor exists, so nothing can hold the port
  first. `18080` is outside Linux's default ephemeral range (32768-60999). No
  environment variable, argument or file selects it.

### What changes identity, and what does not

**The execution identity changes.** `LinuxLauncher.revision` hashes
`linux.py` (`linux.py:305-314`), so the prefix changes it; the runtime gains
the script, so `runtime_digest` (`linux.py:71-107`) changes too. A published
`NativeOperatorLaunchIdentityV3` must therefore be re-derived: the provider
compares `isolation_revision` and `runtime_digest` against the live launcher
(`codex.py:1788-1799`). Nothing is pinned as a literal golden for either; the
test suites derive both from source and from the built runtime.

**Unchanged:** the relay, its policy and its five egress identity digests
(`identity_digests`, `egress.py:170-201`, which do not cover the launcher), so
the N3b egress identity is unchanged; the supervisor; the AppArmor profile (the
workload profile already allows `network`, and the placement fixture already
binds loopback in the zone); the Codex adapter and its command. No L0
contract, journal record, scheduler, or availability change.

**Carried, not built here:** the private-host installer has a fixed
three-artifact inventory (`scripts/ci/m8_host_artifacts.py:56-63, 283-306`) and
installs no runtime. The N4 runtime closure must carry this script.

### The zone now has one loopback listener

N3b's in-zone probe asserts that the host peer's port on the zone's own
`127.0.0.1` refuses (`test_native_egress_containment.py:230-231, 537`). That
stays true under the bridge: the probe dials the peer's ephemeral port, never
`18080`. But its meaning, that nothing in the zone listens on loopback, no
longer holds, and the independent review was right that the design left this
unstated. The proofs therefore replace the implicit claim with an affirmative
inventory: the in-zone probe lists every listening TCP and UDP socket from
`/proc/net/{tcp,tcp6,udp,udp6}` and asserts exactly one, `127.0.0.1:18080`, and
the peer's port is asserted to differ from `18080`. The whole N3b containment
file runs under the prefix, since every leaf-bearing launch now carries it.

### Rejected alternatives

- **A Unix-socket proxy URL.** Unsupported by every transport (finding a).
- **Forwarder inside PID 1.** Grows the trusted init (Placement).
- **A readiness sleep or connect-probe.** A sleep reads time as readiness. A
  connect-probe through the leaf would spend one of the relay's connections
  (`EgressPolicy.connections`) and count as an `eof` denial.
- **A CONNECT-aware forwarder** (parse the head, refuse early). Duplicates the
  relay's rule in a place the payload can tamper with. Parsing is the relay's.
- **Also setting `ALL_PROXY`, `HTTP_PROXY`, `NO_PROXY`.** Not needed (finding
  a); each widens what the environment says. YAGNI.
- **Setting the proxy with `--setenv` in `argv`.** It would expose the proxy
  variable to the bridge script's own interpreter too, and split the port
  between two files. The script owns the port and the variable.

## Process and async lifecycle walk

Design obligations, not executed claims. "Checks" means verified
affirmatively; "assumes" means relied on.

| Step | What can exist when it resumes | Checks / assumes | A failure leaves |
| --- | --- | --- | --- |
| `argv` (synchronous) | Leaf socket replaced since bind | Existing `require_current()` runs before the prefix is added | Existing fixed-text refusal; no bridge, no spawn |
| PID 1 starts the script | The deadline already passed, owner closed | Existing: PID 1 checks both before `Popen` (`_supervisor.py:135-137`) | Existing 125 |
| Script: leaf check | `/vendor-egress.sock` is the empty regular leaf of a leaf-less runtime, or absent | `lstat` is `S_ISSOCK` | Fixed stderr line, exit 126. The vendor never runs |
| Script: `bind` + `listen` | Port taken (cannot happen in a fresh namespace), `lo` down | The call returns | Fixed line, exit 126 |
| Script: `fork` | - | - | Fork failure: fixed line, exit 126 |
| Forwarder child start | Inherited: stdio pipes to the host, the listener, the readiness write end | It replaces fds 0-2 with `/dev/null` and closes every other descriptor except the listener and the readiness end, **before** writing readiness | Any failure: `os._exit` without writing, so the parent reads EOF |
| Parent: readiness read resumes | The byte, or EOF because the child died | Exactly `b"\x01"` | Anything else: fixed line, exit 126 (the child, if alive, is TERMed by PID 1 once the script exits) |
| Parent: before exec | The parent still holds its listener copy and pipe end | It closes both first, so the forwarder holds the only listener and the vendor inherits neither. Python's descriptors are also close-on-exec (PEP 446), a second, independent reason | - |
| Before `execve` | The script's interpreter ignores `SIGPIPE` and `SIGXFSZ`; `execve` keeps ignored signals, whereas PID 1's `subprocess` launch restored them | Both reset to `SIG_DFL` (added in implementation, found by self-review) | - |
| `execve` | - | Environment = inherited + `HTTPS_PROXY` | `OSError`: fixed line, exit 126 |
| Forwarder `accept` resumes | A connection queued since `listen`, possibly before the child ran | - | Accept failure other than interruption ends the forwarder; the listener closes and later connects are refused |
| Handler dial of the leaf | Relay stopped, bound spent, leaf gone | The dial returns | `OSError`: close the client unread. No byte is written to the client, so the vendor sees a closed tunnel, never a forwarder-authored reply |
| Pump read resumes | Data, EOF, reset | - | EOF: `shutdown(SHUT_WR)` on the other side and keep the opposite direction. Error: `shutdown(SHUT_RDWR)` both, which wakes the other pump; join; close both |
| Relay denies or cuts | The relay closed its end of the leaf connection | - | The pump sees EOF or a reset and propagates it; the vendor sees the tunnel end |
| Vendor exits | Forwarder threads blocked in `accept`/`recv` | PID 1 sees the payload exit and TERMs the namespace; KILL after the existing 2 s grace (`_supervisor.py:66-110`) | The forwarder dies; PID 1 reaps it; the supervisor holds the guards until then |
| Forwarder crashes | Vendor streams in flight | - | Its sockets close: in-flight tunnels end, new connects get `ECONNREFUSED`. Nothing else routes. The vendor's request fails |
| Host stop, deadline, controller death | - | Existing relay revocation and supervisor TERM/KILL | Unchanged |

**Why the forwarder must drop the payload's stdio.** It is forked from the
process that becomes the vendor, so it inherits the conversation pipes. If it
kept stdout open, the host would see no EOF when the vendor exited, only when
PID 1 had killed the forwarder: a changed EOF observation on the duplex path
that N2 relies on. Descriptor replacement happens before readiness, so the
vendor cannot exist while the forwarder still holds a stdio copy.

## Negative inferences made affirmative

| Tempting inference | Affirmative replacement |
| --- | --- |
| The vendor ran, so the forwarder was ready | The script execs only after reading the forwarder's readiness byte; EOF refuses |
| No proxy error means the request was forwarded | Forwarding is proved only by the relay's `observed["accepted"]` and the peer's recorded handshake and bytes in the same run |
| The relay accepted, so the client wrote the expected CONNECT | The test records every head the relay's parser received and asserts its exact preface |
| Nothing in the zone listens on loopback | Exactly one listening socket, `127.0.0.1:18080`, from the zone's own `/proc/net` tables |
| The forwarder added nothing because the test passed | A recording upstream asserts byte identity in both directions, and that the forwarder writes nothing to a client whose leaf dial failed |
| The client used the proxy because it reached the peer | The zone has no route (asserted in the same run: a direct connect gives `ENETUNREACH`), and the relay counted the connection |
| The vendor honours `HTTPS_PROXY` | Source only (finding a) until the pinned-binary proof runs; the harmless client proves only the shim |
| The environment holds only `HTTPS_PROXY` extra | The in-zone client reports its whole environment; it is asserted equal to the launcher's plus that one variable |
| Stdio EOF is unchanged | The in-zone client's stdout EOF is observed while the forwarder is still alive (the harness asserts the forwarder's descriptors are `/dev/null`) |

## Test plan

Every behaviour is proved in both directions; the accepting path comes first.

### Portable (Windows and Linux)

`tests/substrate/test_egress_bridge.py`, driving the real forwarder functions
in-process over loopback TCP, with only the leaf dial substituted (the platform
primitive, as N3b substitutes the relay's):

- bytes identical in both directions, including a payload larger than several
  chunks; nothing added, nothing parsed (a non-HTTP payload passes unchanged);
- half-close each way: a client `SHUT_WR` reaches the upstream as EOF while the
  upstream's reply still arrives, and the reverse;
- teardown: an upstream reset closes the client; a client reset closes the
  upstream (Linux only; see mutant 4);
- the script refuses a relative command, and refuses before binding when the
  leaf is absent or a regular file;
- refusal when the leaf dial fails: the client is closed and receives zero
  bytes;
- the vendor environment is the inherited one plus exactly `HTTPS_PROXY`;
- the launcher adds the prefix exactly when the leaf is mounted, never for a
  worker or a leaf-less native launch, and the command follows unchanged;
- **the real relay behind the forwarder** (N3b's portable substitutions) admits
  a reqwest-shaped head (`Host` plus a lower-case `user-agent` line) and a
  tungstenite-shaped head (`Host` plus `Proxy-Connection: Keep-Alive`), replies
  with exactly the established line and nothing after it before the hello, and
  refuses the decoy as `destination`.

### Linux unit tests (the unprivileged `verify` job)

- the leaf check admits a real pathname socket;
- readiness: the forked forwarder's byte arrives before exec; a forwarder that
  dies before readiness makes the script refuse;
- the forwarder's descriptors at readiness are exactly `/dev/null` on 0-2, the
  listener and the readiness end.

### Linux containment (the foundation lane)

In `tests/substrate/test_native_egress_bridge.py`, as `m8-service` with the
production runtime and the N3a store fixture, against the N3b throwaway-CA
peers:

- **accepting:** an in-zone client reads `HTTPS_PROXY` from its environment,
  speaks CONNECT to the forwarder, completes TLS to `allowed.invalid` and gets
  the peer's body; the relay counts one `accepted`; the peer records the
  handshake;
- **refusals:** the decoy through the proxy is denied by the relay as
  `destination`; a direct TCP connect with no proxy gives `ENETUNREACH`; the
  leaf itself stays the only pathname socket;
- the zone's only listening socket is `127.0.0.1:18080`, in this proof and in
  N3b's probe;
- the environment and stdio facts above, and the exact CONNECT preface the
  relay's parser received.

**The pinned binary.** Finding (b) gives a credential-free trigger that needs
no login and no model request: with `[analytics] enabled = true` and an
explicit `[otel] metrics_exporter` of `otlp-http` pointing at
`https://allowed.invalid:<port>/v1/metrics` with the throwaway CA as
`tls.ca-certificate`, the app-server records a process-start metric at startup
(`app-server/src/lib.rs:598`) and flushes it when it shuts down on stdin EOF
(`otel_reloader.rs:108-110`). That flush uses a bare reqwest client, so it takes
`HTTPS_PROXY`. A foundation-lane proof launches the pinned binary through the
existing startup fixture under the bridge, closes stdin, and asserts:

- the exact CONNECT preface the relay's parser received,
  `CONNECT allowed.invalid:<port> HTTP/1.1\r\nHost: allowed.invalid:<port>\r\n`
  (the exporter's client sets no user agent, so this proof does not exercise
  the `user-agent` line; the portable relay test does);
- at least one relay `accepted`, and at least one request at the controlled
  peer that is a `POST /v1/metrics` whose body contains `codex.process.start`
  (`otel/src/metrics/names.rs:7`), not an exact connection count, because the
  rest of startup is not sealed here.

Every other CONNECT in the run is recorded as a denial count and not asserted.
This proves the real client's proxy path for one reqwest client family. The
websocket family stays source-only until N4.

## Mutation inventory

`scripts/check_m8_n4_bridge_mutations.py`, `scripts/_mutations.py` semantics
(assertion failure required; dedented source; four-space multi-line
replacements). Each mutant names its killing test:

1. the pump forwards an altered chunk;
2. EOF does not half-close the other side;
3. EOF closes both sides instead of half-closing;
4. an error does not wake the opposite pump;
5. a failed leaf dial writes a byte to the client;
6. a failed leaf dial leaves the client open;
7. the environment omits `HTTPS_PROXY`;
8. the environment's proxy names another port;
9. the environment adds a second proxy variable;
10. the leaf check accepts a regular file;
11. the leaf check accepts an absent leaf;
12. the script execs without a leaf;
13. the parent accepts EOF as readiness;
14. the parent execs without reading readiness;
15. the forwarder writes readiness before isolating;
16. isolation keeps the payload's stdout;
17. the parent keeps its listener copy across exec;
18. the launcher adds the prefix without a leaf;
19. the launcher omits the prefix with a leaf;
20. exec keeps the interpreter's ignored signals.

Mutants 4, 13-17 and 20 are killed only by the Linux unit tests; on Windows
they report NOT PROVEN, which is expected and is not a kill. Mutant 4's test is
Linux-only because the wake-up is Linux's `shutdown(2)`: on Windows a `recv`
blocked in another thread stays blocked after `shutdown` (measured during
implementation). Mutant 17 is also covered by
close-on-exec in production, so its kill shows only that the explicit close
exists.

## Limits

- **Source-only claims.** Proxy honouring by the websocket transports, the
  default TLS backend's root discovery, and every dependency line cited from an
  upstream tag rather than the vendored tarball.
- **One real-client family.** The pinned-binary proof exercises one reqwest
  client (the OTel exporter). The Responses HTTP, websocket, auth and backend
  clients are claimed from source, not measured.
- **The forwarder is in the payload's reach.** Same uid, same PID namespace.
  The payload can kill it, and so deny itself egress. That is not a widening.
- **Unbounded in-zone connections.** The forwarder spawns threads per
  connection without its own bound; the relay's connection bound and the
  zone's `RLIMIT_NOFILE` (256) and `RLIMIT_AS` bound it. Exhaustion harms only
  the payload's own egress.
- **Refused hosts are not named.** Carried to N4 (finding b, fact 3).
- **The private host's runtime** must carry the script; the M8-D2 installer
  installs no runtime, and the N4 closure is not built here.
- **Subprocesses see the proxy.** Anything the vendor spawns in the zone
  inherits `HTTPS_PROXY` and so can use the forwarder. It could equally dial
  the leaf; the relay judges both the same way.
- **Unknown client families.** `otlp-grpc` export and the code-mode `unix:`
  transport are not claimed to work through the bridge. N4's sealed
  configuration decides whether they may be configured at all.
- **Unexecuted until Linux CI.** Every Linux unit and containment test and the
  mutants 4, 13-17 and 20.

## Review disposition

One independent Codex pass (`gpt-5.6-terra`, effort high, job
`job_8257a0ea4e68`, worktree mounted read-only) reviewed `c1c3131`. Its sandbox
could not reach the dependency sources, so it marked every dependency claim
UNVERIFIED; those claims are labelled as upstream-tag reads above. Each
finding's premise was reproduced against source before disposition. No second
round was run.

| # | Finding | Class | Premise | Disposition |
| --- | --- | --- | --- | --- |
| 1 | P1: a listener at `127.0.0.1:18080` makes N3b's loopback-negative assertion false | introduced | **Partly false.** The assertion dials the host peer's ephemeral port (`test_native_egress_containment.py:230-231`), not `18080`, so it stays true. The true part: its implied meaning, that nothing in the zone listens on loopback, no longer holds | Adopted as an affirmative inventory: exactly one listening socket, `127.0.0.1:18080`, asserted in N3b's probe and in the bridge proof, with the peer port asserted to differ. The whole N3b file runs under the prefix. Also true and adopted: without the script in the runtime every leaf-bearing launch fails, so the runtime builder installs it |
| 2 | P2: "What does not change" understates identity impact | introduced | True (`linux.py:305-314`, `71-107`; `codex.py:1788-1799`) | Section rewritten: launcher revision and runtime digest change; the egress digests do not |
| 3 | P2: `otlp-grpc` is a tonic exporter, not reqwest | introduced | True (`otel/src/metrics/client.rs:588-616`) | Census row split; `otlp-grpc` is Unknown |
| 4 | P2: code-mode accepts a `unix:` endpoint | introduced | True (`code-mode/src/grpc_session/transport.rs:57-64`); reachable only with a launch argument the fixed command never passes | Row corrected: `unix:` bypasses and reaches only mounted pathname sockets |
| 5 | P2: `process/spawn` and subprocess paths omitted | pre-existing | True (`process_exec_processor.rs:69-108`) | Rows added. The census now states that its column is compatibility, never security: containment is the relay's and the namespace's |
| 6 | P3: assert the captured CONNECT preface and "at least one accepted POST containing `codex.process.start`", not an exact count | introduced | Sound | Adopted in the pinned-binary proof |
| 7 | Host installer inventory has no runtime script | pre-existing | True (`m8_host_artifacts.py:56-63, 283-306`) | Recorded as carried to the N4 closure |
| 8 | Dependency behaviour (schemes, `NO_PROXY`, CONNECT form, tungstenite) UNVERIFIED | process | True for the reviewer's sandbox | Kept, labelled as upstream-tag reads; the pinned-binary proof measures the reqwest CONNECT form |

Nothing was rejected outright; finding 1's premise was narrowed, not dismissed.
