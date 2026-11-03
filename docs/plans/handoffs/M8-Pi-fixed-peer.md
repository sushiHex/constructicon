# M8 N7: Pi fixed local peer

Status: design for the credential-free proof. No model build or live profile is selected.

The Pi startup proof in #350 established networkless startup and drain. The next
question is whether that same workspace launch can emit the expected READ tool
schema to a peer without gaining any other route. N7 in M8 rev 3 owns provider
choice and conformance. ADR 0021's subscription stores are not part of this
profile.

## One destination, one acquisition

Keep the existing private network namespace and READ mount. Trusted assembly
starts one disposable peer, with neither the workspace nor external networking.
The peer listens on a private filesystem Unix socket; a TCP listener bound to
loopback inside the Pi namespace forwards to that one socket. Mount only the
socket leaf. Do not expose a host port, parent directory, native store, proxy
environment, or caller-selected destination. The HTTP peer is the destination:
it does not forward URLs, implement CONNECT, or connect to another process on
the caller's behalf. Redirects cannot grant routes. No graph field selects the
socket, command, or endpoint.

Reuse the existing in-zone forwarding mechanics if their lifetime and
descriptor isolation fit. The vendor bridge's HTTPS proxy setup is not part of
this profile. Do not generalize the task-shaped adapter into a transport API.
No endpoint leaves existing launcher arguments and historical profiles unchanged.

## Resume and close rules

- Before opening the route, own the peer and socket in an acquisition-private
  directory. Record positive readiness and identify the actual bound socket.
  A path existing, or a peer process having started, is not readiness.
- After any asynchronous launch probe, recheck the grant before mounting and
  starting the payload. Scope socket identity and lifetime to the acquisition;
  never reuse a previous acquisition's pathname or accept a replacement leaf.
  Keep the owner and private directory live across spawn and join. If revocation
  races spawn, an already-mounted leaf must not make a revoked peer reachable.
- Once closing starts, it never returns to ready. Close the listener and all
  accepted streams; unlinking a Unix socket alone does not close either.
  Terminate and join both supervised process trees on normal exit, startup
  failure, timeout and cancellation. A partially started acquisition still
  owns cleanup; never publish success before joined teardown.

## Evidence that unlocks READ

Use real pinned Pi through the actual workspace launcher with a credential-free
HTTP test peer and fixture workspace. Assert the complete tool names and
argument schema captured at the request boundary, a correlated response and
clean drain. Prove the allowed route and positively controlled denial of an
alternate listener, and close with a stream already accepted to prove active
revocation. Keep the workspace unchanged. An outer loopback lab can diagnose
the wire format but cannot substitute for this proof.

Then select and pin one local server, model, and unauthenticated profile.
Confirm host fit and tool-call compatibility before a single bounded READ.
Require a fixture-derived answer, one admitted read, unchanged workspace and
joined cleanup. Keep model selection, execution and integrated closure
separate from the credential-free proof; carry forward accepted historical
Claude and Codex evidence.

## Pinned request recipe

For the fixture use a literal dummy key, not an environment lookup or command.
The [pinned model configuration](https://github.com/earendil-works/pi/blob/71023aec1546d6d677a65669c5665c0927ce0dd0/packages/coding-agent/docs/models.md#L44-L65)
selects an OpenAI-compatible fixture provider at the fixed loopback base URL
ending in /v1. Select the fixture provider and model explicitly, with thinking
off. The [pinned request producer](https://github.com/earendil-works/pi/blob/71023aec1546d6d677a65669c5665c0927ce0dd0/packages/ai/src/api/openai-completions.ts#L797-L858)
builds the streaming chat request and converts its tools. Assert the full
tools array for that request, rather than inferring global tool availability
from CLI flags or from the absence of calls.
