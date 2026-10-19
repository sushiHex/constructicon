# M8 retained drift baseline: completeness investigation

Source-only investigation and executable proposal for
[#238](https://github.com/sushiHex/constructicon/issues/238), against `c3323e1`.
The owner authorized this bounded investigation and proposal, not live adoption.
This living evidence record changes no frozen plan or installed artifact.

## Finding and provenance

The historical source pin remains SHA-256
`e3541663b621a79558be4186a0def104d17c7b7b10a5066bb34edfeb53eb0165`,
2,578 bytes, 62 lines, LF-only. Both complete listings in the historical
[R2 report](https://github.com/sushiHex/constructicon/issues/73#issuecomment-5790260256)
were independently extracted from the public comment and verified identical
after CRLF-to-LF normalization. This is source provenance, not a measurement of
the installed file. The retained private source was not accessed or copied.
The [readiness record](M8-q13-readiness.md#measurement-is-not-approval) prohibits
publishing raw retained tool source or host output; this slice publishes neither.

Source inspection confirms the historical comparison iterates only baseline
rows. It does not establish that every expected key is present exactly once.
Its fact-producing `printf` commands can return success even when a command
substitution failed; a scalar alone does not affirm completion of its query.

Credential-free source-equivalent fixtures exercise those two mechanisms:

| Input or event | Historical mechanism | Proposed contract |
| --- | --- | --- |
| Complete matching inventory | Unchanged | Unchanged |
| Complete changed value | Drifted | Drifted |
| Empty or missing-row inventory | Can report unchanged | Refused |
| Last row without final LF | Can omit that row | Refused |
| Duplicate matching key | Can report unchanged | Refused |
| Unknown key with empty value | Can report unchanged | Refused |
| Unknown key with nonempty value | Drifted, rather than invalid | Refused |
| Failed query hidden by successful outer output | Can produce a comparable empty/zero scalar | Incomplete observation |

The portable comparison fixture is a small Python translation of the reviewed
row loop; the substitution fixture executes Bash with only a synthetic failing
command. Neither runs the retained script's exact bytes, installation, actual
queries or capture branch. These are structural reproductions, not an end-to-end
historical-tool test. New-contract tests execute the actual proposed module.
No current baseline, host value, tool installation or qualification was measured.

## Smallest proposed contract

[`scripts/m8_host_baseline_contract.py`](../../../scripts/m8_host_baseline_contract.py)
is a stdlib-only, source-reviewed proof module. It has no CLI, collector,
subprocess launch, file reader, capture writer or installation entry. It imports
no Constructicon kernel and introduces no alternate runtime mechanism. Existing
runner qualification and host-artifact verification record overlapping facts
but do not supply a reusable complete nine-field baseline type; repurposing
their physical qualification machinery would confuse two different claims.

The existing nine keys remain the entire inventory:

| Key | Proposed scalar domain |
| --- | --- |
| `kernel` | 1–128 ASCII version-token bytes |
| `bwrap_digest` | Exactly 64 lowercase hexadecimal bytes |
| `bwrap_version` | 1–128 ASCII version-token bytes |
| `bwrap_held` | `0` or `1`, decoded to a boolean |
| `apparmor_enabled` | `N` or `Y`, decoded to a boolean |
| `userns_restrict` | `0` or `1`, decoded to a boolean |
| `apparmor_abi` | Exactly 64 lowercase hexadecimal bytes |
| `os_release` | 1–128 ASCII version-token bytes |
| `architecture` | 1–32 lowercase ASCII letters/digits/hyphens; alphanumeric first |

Version tokens start alphanumeric and otherwise allow letters, digits and
`.+:~_-`; whitespace and controls are not accepted. These are proposed domains,
not evidence that all future host platforms conform. Broader domains or a
different inventory require a reviewed source-contract change, not automatic
repair or acceptance of unknown keys.

`decode_baseline` requires bytes bounded to 2,048, exactly nine LF-terminated
TSV rows, exactly one tab per row, no duplicate or unknown keys and no omitted
key. Row order is immaterial. Empty, CRLF, control-bearing, undecodable and
unterminated inputs refuse. A missing file is not synthesized as an empty
baseline; a future reader must report it as unavailable before this decoder.
The frozen `HostFacts` type also validates direct construction. No decoder
silently rewrites or repairs historical bytes.

`decode_observation` reuses `subprocess.CompletedProcess[bytes]` as a completed
query result rather than inventing another process-outcome framework. It
requires the exact nine-key inventory, integer status zero, byte stdout of
1–129 bytes containing exactly one final LF, empty byte stderr, and the same
scalar domains. A result with missing status/stream, nonzero status, diagnostic,
overflow or malformed value is incomplete, never unchanged. Fixed refusal
reasons contain no supplied keys, host values, argv or stderr.

This API cannot attest how its caller obtained a result. Any future collector
must bound streams while reading and record the underlying queries' affirmative
completion, not an outer `printf` status. In particular, determining an absent
package hold must distinguish a successful empty `apt-mark` result from a failed
`apt-mark`; blindly adopting `grep`'s no-match status would be wrong too. The
proposal deliberately does not invent or execute that collector.

Comparison accepts only complete typed inputs and returns two fields: a fixed
`unchanged`/`drifted` status and an inventory-ordered tuple of changed known keys.
It publishes no old/new values. Incomplete inputs raise a fixed refusal before
comparison, not a false clean result. Complete but unhealthy values are allowed:
an unchanged disabled setting is unchanged, not healthy or qualified. The facts
object is private evidence, not a public telemetry payload.

## Alternatives and decision boundary

Merely checking row count permits duplicate/unknown keys. Checking exact keys
without scalar domains permits empty results. Checking values without query
completion permits swallowed failures. Extending the historical Bash loop alone
does not establish all three conditions. A new general evidence framework,
kernel contract or replacement qualification mechanism is unnecessary.

The proposed direction is to retain a reviewed, versioned source contract and
complete typed baseline before any future adoption. This PR makes that proposal
executable; it does not adopt a new live tool version, approve the proposed
domains for an installed collector or migrate a baseline. A separate owner
decision and exact reviewed installation/capture procedure would be needed for
those actions, including compatibility, source identity, permissions, atomic
capture/failure handling and independently completed physical qualification.

[ADR 0019](../../adr/0019-hosted-linux-runners-are-requalified-not-image-pinned.md)
and the [D2 installation record](M8-D2-host-installation.md) remain authoritative.
Nine unchanged facts cannot prove loaded profiles, ownership/modes, current
physical attachment, service identity or the other D2 qualification obligations.
This finding neither weakens q13's guards nor authorizes R6, a refresh, VM start,
credentials, host access, baseline capture or installation. The frozen q13
procedure and readiness record remain untouched.

## Evidence

The focused suite exercises both accepting comparison paths, the historical
structural cases, each missing/failed query, every scalar family, direct typed
construction, real bounds, and the entire public comparison field inventory.
The Bash fixture uses the existing portable Git Bash selector on Windows.
Exact test/mutation and final-head gate results belong in the PR, not an
unmeasured success claim here. No live or Linux physical evidence is claimed.
