# Claude private-host artifact installation

Implementation proposal for [#283](https://github.com/sushiHex/constructicon/issues/283),
the installation prerequisite of the Claude subscription checkpoint in
[#40](https://github.com/sushiHex/constructicon/issues/40). This document does
not authorize deployment or establish subscription qualification. Accepted
plans and ADR 0021 remain unchanged.

## Smallest installation boundary

Install a distinct launch set at `/var/lib/constructicon-m8-claude`, with its
policy at `/etc/apparmor.d/constructicon-m8-claude`. Do not replace the Codex
launch set or touch its operator stores. The service controller remains a
separately verified installation at an exact merged commit.

The helper is `scripts/claude_host_artifacts.py`: stdlib-only, unprivileged,
offline, and never a launcher. Root executes only the fixed stock installation
commands in the later reviewed procedure. The helper neither executes Claude
nor calls a provider. It never imports or executes a CI script.

The existing `scripts/ci/m8_host_artifacts.py` has an explicitly named offline
host-use exception in the earlier runbook. Its location alone does not make
that helper forbidden. Conversely, that exception does not authorize the
hosted Claude fixture or this new helper. This installation receives its own
reviewed procedure; the earlier helper and frozen runbooks are unchanged.

The new policy preserves the hosted policy's enforcement body and finite
profile names. A portable comparison pins that equivalence; it is not a proof
of profile loading, namespace behavior or a successful private-host launch.

## Affirmative phase facts

There are three synchronous phases, not an installer daemon or resumable
state machine:

1. **Stage:** establish the exact helper and source blobs on fetched main's
   first-parent history; validate private workspace custody and closed
   selection inputs; construct a fresh staging tree from pinned vendor bytes,
   committed policy/supervisor/bridge bytes and the curated host runtime.
   Emit the resulting configuration bytes and hash for independent review.
2. **Judge:** rederive the expected tree and compare the entire staged tree,
   including names, types, modes and bytes. Check the literal independently
   reviewed configuration hash, fixed installation tools, root-owned parent
   directories, absent targets and absent conflicting loaded profiles.
3. **Verify:** after the separately reviewed stock root commands, independently
   derive the expected artifacts again and compare the complete installed
   tree and enforcing profiles. Staging is not evidence and is not required
   for this verification. Verify is not authenticated qualification.

The configuration has exactly the maintenance entry's schema. Model, effort,
phase destinations and finite connection limits are explicit selection
inputs. No account fact is inferred; no credentials are read, copied or
hashed. Actual globally routable address pins and numerical limits belong to
the exact attended package. The expected configuration hash is a reviewed
literal, never read back from the file it authenticates.

## Interruption and replacement reasoning

No helper phase has an `await`; interruption can nevertheless occur before
or after every filesystem operation and external fixed-tool return.

| Boundary | Possible retained state | Required next fact |
| --- | --- | --- |
| Before stage directory creation | No stage, or another actor's existing path | Exclusive creation; absence does not prove no previous attempt |
| During stage writes | Partial private tree | No successful stage verdict; refuse reuse |
| After stage, before judge | Changed inputs or stage bytes | Rederivation and whole-tree comparison, not the old report |
| After judge, before installation | A stale judgement | Exact reviewed package and exclusive operator custody; no automatic install |
| During stock root installation | Any prefix of installed files | Verify refuses incomplete, extra or changed contents |
| During profile loading | Files present but profiles absent or wrong | Affirmative enforcing-profile observation |
| After installation, before verification | Apparently complete but unverified tree | Fresh independent verification with staging unavailable |
| Before maintenance launch | Verified artifacts may since have changed | Existing launch-time artifact checks remain mandatory |

A missing success record is unknown completion, never permission to retry.
No failure path publishes `installed: true`. There is no automatic cleanup,
replacement, rollback or continuation. A recovery package must inventory the
actual prefix, preserve evidence and remove only explicitly identified new
Claude artifacts under separately reviewed commands. It never removes an
operator store or changes a drift baseline.

## Runtime and controller requirements

Build the runtime from the fixed Python/Git/CA closure, the shell needed by
the existing containment control, the three statically identified glibc
compatibility libraries, committed supervisor and bridge, and the exact empty
Claude mount targets. Do not copy an old installed Codex runtime or the whole
host `/usr` tree. Record source identities and all resulting content digests.
Vendor archive validation selects the one pinned regular executable member;
it is never executed to discover dependencies.

Controller verification must include the installed `claude_lane`,
`claude_maintenance_session` and `claude_native` modules, not assume that the
existing Codex import list covers them. Imported paths must belong to the
verified controller or standard library. A benign launcher probe and the
credential-free fake profile-transition proof remain distinct from running
the vendor and from authenticating it.

## Promotion to an executable operator package

The implementation PR must first supply passing fake accepting/refusing
tests, appropriate Linux evidence and independent review. The exact merged
commit, controller commit, script hashes, production policy bytes, reviewed
configuration hash, boot/drift facts, exclusive custody and scoped recovery
commands then become one executable package. Until those facts are present,
this document is not a copy-and-paste installation runbook.

Only after installation and controller verification may the separately
reviewed maintenance procedure begin. Login, positive mode observation,
fresh-process persistence, authenticated qualification and the first admitted
READ remain separate affirmative gates. Installation success supplies none
of those facts.
