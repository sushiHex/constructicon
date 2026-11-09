# Stored-reply maintenance: operator package

Preparation for [#397](https://github.com/sushiHex/constructicon/issues/397).
This is a **template**, not a released operating procedure. A normal package
build refuses its unresolved declarations. A `--template` package is for local
review only: never upload or execute it. No host operation, vendor process,
credential inspection or model call was used to prepare this document.

The concrete outcome is at most one useful `channel-stored-reply` contribution
against an eligible current-main base, under the successor application in
[#393](https://github.com/sushiHex/constructicon/issues/393). The risk tier is
consequential: these commands carry installation, binding and attempt authority.
The proof set is focused accepting/refusing composition through the actual
compiler and transport, producer-generated application evidence after joined
shutdown, independent command review, final-head CI and the separately approved
fresh host observations. Local fixture acceptance is never host qualification.

## Release and operating order

Select the actual merged controller containing the #393 successor and the
merged [#396 cache/lane changes](https://github.com/sushiHex/constructicon/pull/396),
including the changed launch inventory. Export and verify its complete Git blobs using
[`reviewed_source.py`](../../../scripts/ops/reviewed_source.py), as documented in
the [operator README](../../../scripts/ops/README.md#source-bytes-before-host-use).
Check that the pinned target still lacks `_stored_reply`; the trusted task
preparer also refuses an already-completed base. Retain the reviewed source
bundle, its sole maintenance ref, byte count and SHA-256. Never strip or change
current-main source merely to create an eligible task.

Before host use, bind the unresolved **source** declarations to reviewed values
in the privately reviewed specialization. Its exact bytes/digest are part of
the release approval; it is not the exported source tree. Select the actual
old launch/controller and D2 revisions from independently retained/observed
installation evidence; neither equality to the new controller nor an old chat
pin establishes them. The compiler's existing source-part `set` handles only
the documented 40-hex declarations in frozen fences. Its `--values` handles
only the five existing measured fields, not arbitrary source or private inputs.
Do not add a new compiler parameter or fabricate a commit to fill this template.

The operating sequence is:

1. Review the exact source/package and permitted installation operations, then
   obtain the applicable R15/LR0/LR9 installation approval. Establish exclusive
   custody and current VM state through the existing coordination and machine
   checks. Current boot, credentials, generation and qualification remain
   unmeasured here. No checkpoint, re-baseline, provisioning or login is supplied.
2. Run the separate original installation files described below. Preserve D2
   evidence before its prescribed requalification. Require actual current
   launch/controller verification, D2 probe, import check and drift evidence.
   Stop on unexpected output; no alternate shell settings or installer retry.
3. Run `cr-physical-preflight`, `cr-session-prepare`, `cr-qualification`, `cr-publish`, then
   `cr-controls` once each. These startup lanes use READ posture. The existing
   S6a held-lock control must join. If and only if controls return alternative
   1 (`refresh-unmeasured`), run `cr-refresh` once; it must report measured.
   There is no extra N5 WRITE model smoke test.
4. Transfer the reviewed bundle as file data using the existing checked
   transfer fence, then run `cr-prepare` and `cr-preflight`. Actual WRITE
   assembly supplies the preview and exact pins; it dispatches no model task.
   Review the full private preview and its bounded private review record.
5. Obtain the exact one-attempt approval below. Fill the measured preview,
   derived RunId and boot through a reviewed values file; build a fresh second
   package. Run `cr-authority` and at most one `cr-run`. Never rerun earlier
   stages or reinterpret a refused/unknown command as unused budget.
6. After a normal completed return, inspect only an accepted result, run
   `cr-quiescence`, collect `cr-report`, discharge `cr-withdraw`, then observe
   `cr-authorization-retained` when authority installation completed.
   The approved cleanup route remains an obligation after failure; it grants no
   diagnostic or new attempt. Park through the existing reviewed VM procedure,
   affirm Off/usage, and release custody only with the required cleanup proof.

The first released build can defer only `cr-authority`, `cr-run`, `cr-report`
and `cr-authorization-retained` for measured session fields. All source/private
declarations must already be reviewed. A fresh boot or changed source, pin,
custody, expiry or package stops
the ordinary route. Dispatch uncertainty remains uncertainty and grants no retry.
An explicit frozen stop/resume rule still controls its selected stage.

### Private specialization

The committed living template stays unresolved. Make a separate private copy
outside both the repository and the verified export; never edit the exported
source tree or commit private inputs. The specialization is literal data filled
into reviewed declarations, not a new execution framework. The existing compiler
already supports this path (`m8_procedure_package.py:730–743`): each selected
source path is read and its original SHA-256 and LF bytes are checked before
assembly. No new compiler flag or API is needed.

Only these substitutions belong to this template's private specialization:

- In **Source and private declarations**, fill the declaration values for
  `C`, `BASE`, `TARGET_SHA256`, `BUNDLE_SHA256`, `BUNDLE_SIZE`, `BUNDLE`, `W`, `K`,
  `W_PRIOR`, `GEN`, `GEN_PRIOR`, `GENERATION`, `FLOOR`, `S`, `APP`, `A`, `ID`,
  `ACTOR`, `KEY` and `REPORT` with independently reviewed literal data.
- Give `S` a short, fresh canonical path of its own, as an unquoted absolute
  literal using ASCII letters, digits, slash, dot, underscore and hyphen.
  The WRITE provider derives the Unix socket from
  `S/acquisitions/payloads/acq-<32 hex>/egress.sock`. A
  descriptive path can compile and pass startup qualification but exceed the
  provider's 107-byte limit before it can produce WRITE pins. Use the same
  absolute path syntax for `APP` and `REPORT`. `REPORT` must be separate from
  both `APP` and `S`, which holds `application-run.json`: the report capture
  refuses equality or a parent/child relationship in either direction.
  Before taking VM custody, run the local check from the reviewed operator checkout:

      uv run python -I -B scripts/ops/check_native_state_path.py PRIVATE_RECIPE

  Require exit zero, `native-state-socket-checked` and
  `maintenance-report-path-checked`. Repeat on the actual compiled
  `cr-preflight.sh` and, when the report step is built, `cr-report.sh` before
  uploading each package. The checker reads the literals without running the
  recipe. The host still checks path freshness, ownership and custody.
- Fill `SOURCE_UPLOAD` in **Bundle transfer**, and `QUIESCENCE_CAPTURE` and
  `QUIESCENCE_STDERR` in **Quiescence capture**, with reviewed private locators.
  Quote literal shell values; never fill a command, expansion or shell expression.
- Point each `sources.NAME.path` at that exact document in the verified export,
  using its absolute local path. Keep `sources.NAME.sha256` unchanged. Frozen
  source fences, their selection/order, commands, output contracts and all other
  living-template code remain byte-for-byte unchanged.
- Fill `labels.current` with exactly the literal generation/session spellings
  that occur in the reviewed private bindings, including prior-descriptor names
  and path components used by this procedure's negative controls. For example,
  the **synthetic, compile-only** bindings `GEN=g15` and `GEN_PRIOR=g14` need
  `labels = {current = ["g14", "g15"], historical = []}`. Keep
  `labels.historical` empty and the step selections unchanged; do not add a range
  or unrelated labels. The compiler checks spelling, not freshness or authority:
  listing a prior spelling in `current` permits its literal reference in this
  current procedure, never activation, qualification or reuse of historical pins.
- For a separately selected original installer fence, the existing source-part
  `set` may fill only its documented `C`, `O` or `D` declaration with the reviewed
  40-hex commit (`m8_procedure_package.py:95–99`). This does not permit editing
  the frozen source file or changing installer shell settings. These separately
  captured installers do not acquire a T5 output contract.
- Keep the five canonical measured declarations as `NAME=UNREVIEWED` in the
  private document. Supply only `PREVIEW_SHA256`, `RUN_ID`, `EXPECTED_BOOT`,
  `DRIFT_STDOUT_HEX` and `DRIFT_TOOL_SHA256` through the existing private
  `--values` file when independently measured and approved. The first build
  needs boot/drift values; only the explicitly deferred steps may still await
  preview/RunId. The second build uses a fresh output and their real approved
  values. No fictional value makes either package operational.

`PRIVATE_VALUES` is a **TOML** file with string values, not a JSON object. Its
complete shape is shown below; the placeholders deliberately fail the existing
value-shape checks and must be replaced with independently approved facts. For
the first build omit `PREVIEW_SHA256` and `RUN_ID` until preflight supplies them.

```toml
EXPECTED_BOOT = "UNREVIEWED"
DRIFT_STDOUT_HEX = "UNREVIEWED"
DRIFT_TOOL_SHA256 = "UNREVIEWED"
PREVIEW_SHA256 = "UNREVIEWED"
RUN_ID = "UNREVIEWED"
```

Use ordinary `build PRIVATE_DOC FRESH_OUT --values PRIVATE_VALUES`, without
`--template`. An unfilled source/private declaration must refuse the build;
template output is never uploaded. Independently review the specialized literal
data, the complete script/output-contract files, the private document digest and
the resulting normal package manifest hash before approving host use. Retain
those exact artifacts privately. Nothing here automatically posts a preview,
review record or package, or makes its contents safe for public disclosure.

## Separate original installation files

Use the source-pinned fences from
[LR](M8-N4-launch-replacement.md#order): LR1/LR2, LR3, LR4, LR5/LR6, LR8,
LR9 only on its exact installed-false/tree/different-positive predicate, then
[HR R17–R19](M8-N4-host-runtime.md#r17--provenance-and-the-locked-wheels-operator-stock-tools-only-no-sudo)
when controller replacement is required, and LR7. The changed launch inventory
requires actual fresh launch verification/replacement under LR; a historical
kept-launch assertion cannot qualify the new source. No R6, R16 or checkpoint.

Keep those files separate from OC's common block. In particular **R17 runs in
plain Bash, exactly as written**, without a wrapper, `-e` or added `pipefail`.
Its variable commit lines and raw records do not have T5's closed stdout
contract. Do not declare empty or invented expected stdout to force them into
the closed-step transport. Preserve their original shell state where the
runbook requires the same shell. Capture their completion/stdout/stderr with
the existing `claude_read_session.capture` primitive and check the original
markers and typed verifier records manually. Its bounds are checked after
completion, not streaming or disk-write ceilings.

Require R17 provenance/locked-wheel records; R18's affirmative staged/ready,
first-parent and installed-true/different-zero records; R19's passed-true and
empty outside list; LR's fresh boot/store-preservation/retirement/install
receipts; and D2's positive verification/probe. A status file alone is no
completion proof. The host-artifact CLI deliberately consumes the saved bounded
AppArmor profile listing on stdin; top-level closed stdin does not erase this
reviewed file-data input. Keep source SHA-256 and LF equality locally/remotely.

LR3's read-only checks of the existing local service account are retained.
They are distinct from standalone vendor account/credential inspection, login,
creation or mutation, none of which this package supplies. Existing startup's
bounded protocol metadata remains subject to its exact phase approval.
Never execute CI host fixtures on
the private guest. Frozen source bytes remain unchanged.

## Attempt approval and real bounds

The approval must identify the actual merged controller/base, target blob,
trusted check set, application and adapter revisions, source bundle/package,
boot, generation/qualification, full preview digest, actor/key-derived RunId,
one epoch and one application attempt. It must select the model and effort from
the actual reviewed WRITE grants, the operator deadline and cleanup reserve,
and the applicable subscription/overage exposure decision before dispatch.

At the provisional #393 source, `codex_host.WRITE_GRANTS` inherits the explicit
`gpt-6.1-sol`/low model and sets 300 executor seconds; `core.maintenance` fixes
epoch one and that grant shape. `maintenance_entry.run_maintenance` has a
1200-second application wait and joins shutdown in `finally`; this is not a
finite total deadline for joined cleanup. Preflight expiry is one hour.
`codex_protocol.MAX_TOOL_CALLS` bounds eight callbacks; `linux.ProcessLimits`
defines the independent input/artifact/stdout/record/stderr byte limits. These
source facts must be rechecked against the final selected revision before the
approval is concrete. No observed token subtotal is a token spending cap.
Backend request count and monetary charge remain unknown; no finite monetary
ceiling is enforced by these commands. The future approval must state that
exposure explicitly, rather than adopting an old q13 decision.

## Source and private declarations

These are unresolved planned inputs, not measured facts. No historical path,
generation, boot or authorization is selected. Fill source/private values in
the reviewed procedure before a normal build; use the compiler's measured-value
file only for its existing five supported names.

```bash
C=UNREVIEWED
BASE=UNREVIEWED
TARGET_SHA256=UNREVIEWED
BUNDLE_SHA256=UNREVIEWED
BUNDLE_SIZE=UNREVIEWED
BUNDLE=UNREVIEWED
```

The OC common block is selected first; these later declarations bind the fresh
session and application. Private locators stay in the privately reviewed
specialization, not a public issue comment or raw host transcript.

```bash
W=UNREVIEWED
K=UNREVIEWED
W_PRIOR=UNREVIEWED
GEN=UNREVIEWED
GEN_PRIOR=UNREVIEWED
GENERATION=UNREVIEWED
FLOOR=UNREVIEWED
S=UNREVIEWED
APP=UNREVIEWED
A=UNREVIEWED
ID=UNREVIEWED
ACTOR=UNREVIEWED
KEY=UNREVIEWED
REPORT=UNREVIEWED
EXPECTED_BOOT=UNREVIEWED
test "$(/usr/bin/cat /proc/sys/kernel/random/boot_id)" = "$EXPECTED_BOOT"
ENTRY=("${PY[@]}" constructicon.api.maintenance_entry)
HOST=(--session "$W" --store-key "$K" --sealed "$W/$GEN.sealed.json"
  --qualification "$W/s6a-qualification.json" --state "$S" --launch-root "$L")
```

## Active binding

Every application stage rechecks the final qualification and active descriptor.
Actual run assembly repeats those checks inside its own source-bound resources.

```bash
load_final_qualification
binding_check "$W/$GEN.sealed.json" accepted -
check_sealed "$W/$GEN.sealed.json" "$Q"
```

## N4 publication

This is the existing strict floor check and publish/activate law, with the
reviewed next generation replacing the historical literal. Producer:
`operator_store` CLI `publish`/`activate`; the generation must exceed the exact
maintenance floor, never a filename inference. Both qualifications must carry
that same selected floor. The root helper independently enforces next generation.

```bash
load_final_qualification
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import json, sys
from pathlib import Path
for name in ("s4-qualification.json", "s6a-qualification.json"):
    custody = json.loads((Path(sys.argv[1]) / name).read_bytes())["custody"]
    assert custody["kind"] == "maintenance"
    assert type(custody["generation_floor"]) is int
    assert custody["generation_floor"] == int(sys.argv[2])
assert int(sys.argv[3]) == int(sys.argv[2]) + 1
print("maintenance-floor-checked")' "$W" "$FLOOR" "$GENERATION" < /dev/null \
  | /usr/bin/grep -qxF maintenance-floor-checked
"${ROOT_STORE[@]}" publish --store-root "$R" --key "$K" --generation "$GENERATION" \
  --qualification-evidence-digest "$Q" --service m8-service --wait 0 \
  < /dev/null | save_sealed "$W/$GEN.sealed.json"
check_sealed "$W/$GEN.sealed.json" "$Q"
"${ROOT_STORE[@]}" activate --store-root "$R" --key "$K" --generation "$GENERATION" \
  --sealed "$W/$GEN.sealed.json" --qualification-evidence-digest "$Q" \
  --service m8-service --wait 0 < /dev/null
binding_check "$W/$GEN.sealed.json" accepted -
binding_check "$W_PRIOR/$GEN_PRIOR.sealed.json" stale-generation "$W/$GEN.sealed.json"
```

## Conditional refresh declarations

Run only after controls' checked `refresh-unmeasured` alternative. The exact L3
fence follows these declarations and must return `refresh-measured`; another
unmeasured observation stops without another refresh attempt.

```bash
load_final_qualification
SEALED="$W/$GEN.sealed.json"
REFRESH_LANE="$W/h8-explicit-lane"
REFRESH_EVIDENCE="$W/h8-explicit.json"
binding_check "$SEALED" accepted -
check_sealed "$SEALED" "$Q"
```

## Bundle transfer

This preserves q13's file-data transfer checks with the upload locator left
unresolved. It is never shell-script input or an inferred source digest.

```bash
SOURCE_UPLOAD=UNREVIEWED
test -f "$SOURCE_UPLOAD" && test ! -L "$SOURCE_UPLOAD"
test "$(/usr/bin/stat -c %s -- "$SOURCE_UPLOAD")" -eq "$BUNDLE_SIZE"
/usr/bin/sha256sum --binary -- "$SOURCE_UPLOAD" < /dev/null \
  | /usr/bin/grep -qxF "$BUNDLE_SHA256 *$SOURCE_UPLOAD"
"${SERVICE[@]}" /usr/bin/test ! -e "$BUNDLE" < /dev/null
"${SERVICE[@]}" /usr/bin/test ! -L "$BUNDLE" < /dev/null
"${SERVICE[@]}" /bin/sh -c 'set -Ceu; umask 077; cat >"$1"' sh "$BUNDLE" < "$SOURCE_UPLOAD"
"${SERVICE[@]}" /usr/bin/test -f "$BUNDLE" < /dev/null
"${SERVICE[@]}" /usr/bin/test ! -L "$BUNDLE" < /dev/null
"${SERVICE[@]}" /usr/bin/sha256sum --binary -- "$BUNDLE" < /dev/null \
  | /usr/bin/grep -qxF "$BUNDLE_SHA256 *$BUNDLE"
echo maintenance-bundle-transferred
```

## Application preparation

After the existing bounded file-data transfer, prepare selects the task once.
Preflight/run derive it from the retained source and root authority. The source
checker consumes the actual `SourcePin` producer and `pinned_purpose`, rather
than imposing the older plan-manifest three-source shape.

```bash
load_final_qualification
binding_check "$W/$GEN.sealed.json" accepted -
check_sealed "$W/$GEN.sealed.json" "$Q"
"${SERVICE[@]}" /bin/mkdir -m 0700 "$S" < /dev/null
"${SERVICE[@]}" /usr/bin/git init --bare -q "$S/closure.git" < /dev/null
"${SERVICE[@]}" "${ENTRY[@]}" prepare --root "$APP" --bundle "$BUNDLE" \
  --bundle-sha256 "$BUNDLE_SHA256" --base "$BASE" --target-ref refs/heads/maintenance \
  --task channel-stored-reply < /dev/null | save_sealed "$S/source-prepared.json"
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import json, sys
from pathlib import Path
sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.api._maintenance_source import SourcePin, pinned_purpose, read_bounded
from constructicon.core.maintenance import CHANNEL_TARGET_PATH
p = SourcePin.model_validate_json(read_bounded(Path(sys.argv[1]), 8192))
retained = SourcePin.model_validate_json(read_bounded(Path(sys.argv[2]) / "source-pin.json", 8192))
assert p == retained and p.base_commit == sys.argv[3] and p.bundle_sha256 == sys.argv[4]
assert p.target_ref == "refs/heads/maintenance" and pinned_purpose(p) == "channel-stored-reply"
assert p.sources == {CHANNEL_TARGET_PATH: sys.argv[5]}
print(json.dumps({"source_prepared": True, "purpose": "channel-stored-reply",
    "base": p.base_commit, "bundle_sha256": p.bundle_sha256,
    "target_sha256": p.sources[CHANNEL_TARGET_PATH]}, sort_keys=True))' \
  "$S/source-prepared.json" "$APP" "$BASE" "$BUNDLE_SHA256" "$TARGET_SHA256" < /dev/null
```

## Actual WRITE preflight

The command/saver statuses are retained independently, following the corrected
g11 C8 capture. The selected task changes the authorization model and scope.
The authority's task, exact target and model grants must be reviewed from this
real producer output, never synthesized in a host-ready package. The bounded
review record is private: authorization identifiers, grants and binding digests
are operator review facts, not an automatically public-safe whitelist. No raw
preview or review record is posted automatically.

```bash
"${SERVICE[@]}" /usr/bin/test ! -e "$S/preflight.json" < /dev/null
"${SERVICE[@]}" /usr/bin/test ! -L "$S/preflight.json" < /dev/null
if "${SERVICE[@]}" "${ENTRY[@]}" preflight --root "$APP" "${HOST[@]}" \
  --authorization-id "$ID" --actor "$ACTOR" --key "$KEY" \
  < /dev/null | save_sealed "$S/preflight.json"
then P8_STATUS=("${PIPESTATUS[@]}"); else P8_STATUS=("${PIPESTATUS[@]}"); fi
test "${#P8_STATUS[@]}" -eq 2
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import hashlib, json, os, stat, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.api._maintenance_source import read_bounded
from constructicon.core.identity import parse_json_value
from constructicon.core.maintenance import ChannelReplyAttemptAuthorization
try:
    assert sys.argv[9] == "0"
    path = Path(sys.argv[1]); info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    assert info.st_uid == os.getuid() and info.st_mode & 0o077 == 0
    raw = read_bounded(path, 8192)
    assert 0 < len(raw) <= 8192
    if sys.argv[8] == "1":
        r = parse_json_value(raw.decode("utf-8", errors="strict"))
        assert type(r) is dict and set(r) == {"accepted", "error", "stage"}
        assert r["accepted"] is False and r["error"] == "maintenance command refused or incomplete"
        assert type(r["stage"]) is str and r["stage"] in ("source", "assembly", "preview", "unknown")
        print(json.dumps({"preflight": False, "stage": r["stage"]}, sort_keys=True))
        raise SystemExit(1)
    assert sys.argv[8] == "0"
    a = ChannelReplyAttemptAuthorization.model_validate_json(raw)
    assert a.authorization_id == sys.argv[3] and a.actor_id == sys.argv[4] and a.idempotency_key == sys.argv[5]
    assert a.journal == sys.argv[2] + "/maintenance.sqlite"
    assert a.attempt_record == sys.argv[2] + "/maintenance-attempt.json"
    assert a.request.base_commit == sys.argv[6] and a.request.target_ref == "refs/heads/maintenance"
    assert a.request.target_sha256 == sys.argv[7]
    assert a.scope.segments == ("constructicon-channel-stored-reply", "writer") and a.binding == "executor"
    assert a.capability_id == "codex-operator" and a.max_epoch == 1
    assert a.workspace.capability_id == "maintenance-workspace" and a.gate.capability_id == "maintenance-gate"
    assert datetime.now(timezone.utc) < a.not_after
    print(json.dumps({"preview_sha256": hashlib.sha256(raw).hexdigest(), "run_id": str(a.run_id),
        "purpose": a.purpose, "target_sha256": a.request.target_sha256,
        "authorization_id": a.authorization_id, "base": a.request.base_commit,
        "source_graph_hash": str(a.source_graph_hash), "application_revision": str(a.application_revision),
        "revision": a.revision, "operator_binding_digest": str(a.operator_binding_digest),
        "workspace": a.workspace.model_dump(mode="json"), "gate": a.gate.model_dump(mode="json"),
        "not_after": a.not_after.isoformat(), "grants": a.grants.model_dump(mode="json")}, sort_keys=True))
except Exception:
    print(json.dumps({"preflight": False, "stage": "unknown"}, sort_keys=True))
    raise SystemExit(1) from None' \
  "$S/preflight.json" "$APP" "$ID" "$ACTOR" "$KEY" "$BASE" "$TARGET_SHA256" \
  "${P8_STATUS[0]}" "${P8_STATUS[1]}" < /dev/null
```

## Historical inspection and report

Only accepted-true normal completion selects inspection. Its producer is
`maintenance_entry.inspect_result`'s own closed channel projection; it does no
assembly or authentication of the unsealed result sidecar.

```bash
"${SERVICE[@]}" "${ENTRY[@]}" inspect --result "$APP/maintenance-result.json" < /dev/null
```

After normal completion, confirm this boot and affirm service-process quiescence
with the existing retained `pgrep` capture before the report. The report's own
capture/custody guards still apply. It reads only its disposable copy at the
current journal schema; never migrate or open a historical original store.

```bash
RUN_ID=UNREVIEWED
test "$(/usr/bin/cat /proc/sys/kernel/random/boot_id)" = "$EXPECTED_BOOT"
"${SERVICE[@]}" "${PY[@]}" constructicon.api.maintenance_report \
  --root "$APP" --out "$REPORT" --command-report "$S/application-run.json" \
  --run-id "$RUN_ID" --authorization-id "$ID" < /dev/null
```

The packet is at most 8192 bytes including LF. It observes journal attestation,
stored result, metering and recorded lease states; it does not authenticate an
unsealed sidecar or prove physical cleanup. Cost remains unknown. Missing or
contradictory evidence cannot become acceptance.

## Cleanup and transport boundaries

The release must include the existing store-withdrawal producer and affirmative
withdrawal receipt, post-command quiescence and authorization disposition,
followed by the existing park/Off/custody-release operations. They are separate
from result observation. No cleanup may erase the dedicated journal, attempt,
candidate, source authority, result or partial captures. A verified cleanup does
not make a refused attempt successful and does not grant another one.

Use frozen [q12 Q6/T5](M8-maintenance-q12-continuation.md#q6-transport-t5)
byte-for-byte for compiled closed steps. It records the native return code and
streams, then checks framing after completion. It has no process timeout or
streaming/disk cap. Empty/extra/malformed output, nonzero status or unexpected
stderr refuses. Record values are checked by the producing step, not T5.
Use strict-key BatchMode SSH with a previously checked alias, LF-only uploaded
files, the exact reviewed manifest digest checked locally and remotely, and
`/bin/bash FILE < /dev/null`; never stdin shell text, encoded PowerShell or an
execution-policy bypass. No host transport is run by this preparation.

## Store withdrawal

This uses the existing `operator_store maintain` CLI and its inherited receipt,
the same producer consumed by the reviewed READ operator inventory. `maintain`
durably withdraws before starting the service child, appends the store/key/
custody/lock/floor inputs itself, and returns only after the child is joined.
`inherit_maintenance` proves those inputs and the root helper's still-held lock;
`held.check()` affirms that receipt before publishing the bounded observation.
This performs no vendor process, credential inspection or provider call.

```bash
"${ROOT_STORE[@]}" maintain --store-root "$R" --key "$K" \
  --service m8-service --wait 0 -- /usr/bin/python3 -I -S -B -c 'import argparse, json, os, sys
from pathlib import Path
sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.substrate.executors.operator_store import inherit_maintenance
p = argparse.ArgumentParser(allow_abbrev=False)
p.add_argument("--store-root", type=Path, required=True)
p.add_argument("--key", required=True)
p.add_argument("--custody", choices=("maintenance",), required=True)
p.add_argument("--lock-fd", type=int, required=True)
p.add_argument("--floor", type=int, required=True)
a = p.parse_args()
with inherit_maintenance(a.store_root, a.key, a.lock_fd,
        generation_floor=a.floor, parent=os.getppid()) as held:
    held.check()
    assert type(held.generation_floor) is int and held.generation_floor >= 1
    result = {"highest_generation": held.generation_floor, "withdrawn": True}
print(json.dumps(result, sort_keys=True))' < /dev/null
```

## Retained authorization

Preserve the installed root authority bytes as historical evidence. After
withdrawal, this read-only observation binds their approved digest, closed task
and derived RunId. Retention is not permission for a new attempt: the spent
exclusive attempt record, exact run/application/pins, expiry and withdrawn store
still govern. No fresh actor/key, root deletion or revocation mechanism is added.

```bash
PREVIEW_SHA256=UNREVIEWED
RUN_ID=UNREVIEWED
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.api._maintenance_source import read_bounded
from constructicon.core.maintenance import ChannelReplyAttemptAuthorization
from constructicon.substrate.executors.maintenance import read_maintenance_authorization
a = read_maintenance_authorization(Path(sys.argv[1]))
assert isinstance(a, ChannelReplyAttemptAuthorization) and str(a.run_id) == sys.argv[3]
assert hashlib.sha256(read_bounded(Path(sys.argv[1]), 8192)).hexdigest() == sys.argv[2]
print(json.dumps({"authorization": "retained", "authorization_sha256": sys.argv[2],
    "purpose": a.purpose, "run_id": str(a.run_id)}, sort_keys=True))' \
  "$A" "$PREVIEW_SHA256" "$RUN_ID" < /dev/null
```

## Drift declarations

Each selected G1 boundary receives its own fresh capture parent, then consumes
these independently approved private values. Neither is measured from the
invocation it validates. Source: the frozen G1 guard and its existing compiler
declaration contract.

```bash
DRIFT_STDOUT_HEX=UNREVIEWED
DRIFT_TOOL_SHA256=UNREVIEWED
```

```bash
umask 077
/usr/bin/mkdir -m 0700 -- "$DRIFT_RECORDS" || exit "$?"
DRIFT_CAPTURE="$DRIFT_RECORDS/before"
```

## Application capture

The corrected g11 C10 fence is selected with only its capture label changed.
Its authorization reader now consumes either fixed task; the installed authority
was already checked against the new task by preflight. The producer returns only
after joined shutdown; the independent saver/diagnostic statuses are retained.

```bash
PREVIEW_SHA256=UNREVIEWED
RUN_ID=UNREVIEWED
[[ "$PREVIEW_SHA256" =~ ^[0-9a-f]{64}$ && "$RUN_ID" =~ ^run-[0-9a-f]{32}$ ]] \
  || { echo 'approved literal preview and run required; stop' >&2; exit 1; }
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import hashlib, sys
from pathlib import Path
sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.api._maintenance_source import read_bounded
from constructicon.substrate.executors.maintenance import read_maintenance_authorization
preview = read_bounded(Path(sys.argv[1]), 8192)
assert hashlib.sha256(preview).hexdigest() == sys.argv[2]
a = read_maintenance_authorization(Path(sys.argv[3]))
assert read_bounded(Path(sys.argv[3]), 8192) == preview and str(a.run_id) == sys.argv[4]
print("reviewed-installed-authority-checked")' "$S/preflight.json" "$PREVIEW_SHA256" "$A" "$RUN_ID" < /dev/null \
  | /usr/bin/grep -qxF reviewed-installed-authority-checked
"${SERVICE[@]}" /bin/bash -c 'set -Eeuo pipefail
umask 077
set -C
CAPTURE_ROOT=$1
shift
for NAME in application-run.json application-status.json application.stderr saver.stderr; do
    test ! -e "$CAPTURE_ROOT/$NAME"
    test ! -L "$CAPTURE_ROOT/$NAME"
done
exec 3>"$CAPTURE_ROOT/application-run.json"
exec 4>"$CAPTURE_ROOT/application-status.json"
exec 5>"$CAPTURE_ROOT/application.stderr"
exec 6>"$CAPTURE_ROOT/saver.stderr"
if "$@" < /dev/null 2>&5 | /usr/bin/cat >&3 2>&6
then P10_STATUS=("${PIPESTATUS[@]}"); else P10_STATUS=("${PIPESTATUS[@]}"); fi
test "${#P10_STATUS[@]}" -eq 2
FD=3
for NAME in application-run.json application-status.json application.stderr saver.stderr; do
    test -f "/dev/fd/$FD"
    test -f "$CAPTURE_ROOT/$NAME"
    test ! -L "$CAPTURE_ROOT/$NAME"
    test "$CAPTURE_ROOT/$NAME" -ef "/dev/fd/$FD"
    FD=$((FD + 1))
done
RUN_DIAGNOSTICS=unexpected
if test ! -s /dev/fd/5 && test ! -s /dev/fd/6
then RUN_DIAGNOSTICS=clean; fi
printf "{\"application\":%s,\"saver\":%s,\"diagnostics\":\"%s\"}\n" \
    "${P10_STATUS[0]}" "${P10_STATUS[1]}" "$RUN_DIAGNOSTICS" >&4
exec 3>&- 4>&- 5>&- 6>&-' channel-reply-application-capture "$S" \
  "${ENTRY[@]}" run --root "$APP" "${HOST[@]}" --authorization "$A" < /dev/null
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import json, sys
from pathlib import Path
sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.api._maintenance_source import read_bounded
from constructicon.core.identity import parse_json_value
from constructicon.substrate.executors.maintenance import read_maintenance_authorization
result = {"accepted": False, "command": "unknown", "meaning": "application-outcome-unknown"}
try:
    a = read_maintenance_authorization(Path(sys.argv[2]))
    assert str(a.run_id) == sys.argv[4]
    status = parse_json_value(read_bounded(Path(sys.argv[3]), 256).decode("utf-8", errors="strict"))
    assert type(status) is dict and set(status) == {"application", "saver", "diagnostics"}
    assert type(status["application"]) is int and status["application"] in (0, 1)
    assert type(status["saver"]) is int and status["saver"] == 0 and status["diagnostics"] == "clean"
    r = parse_json_value(read_bounded(Path(sys.argv[1]), 8192).decode("utf-8", errors="strict"))
    assert type(r) is dict and type(r.get("accepted")) is bool
    if set(r) == {"accepted", "run_id"}:
        assert status["application"] == 0 and r["run_id"] == str(a.run_id)
        result = {"accepted": r["accepted"], "command": "normal-completed",
            "run_id": str(a.run_id), "meaning": "application-accepted" if r["accepted"] else "application-not-accepted"}
    else:
        assert set(r) == {"accepted", "error"} and status["application"] == 1
        assert r["accepted"] is False and r["error"] == "maintenance command refused or incomplete"
        result = {"accepted": False, "command": "refused", "run_id": str(a.run_id),
            "meaning": "application-not-accepted"}
except Exception:
    pass
out = json.dumps(result, sort_keys=True)
assert len(out.encode("utf-8")) <= 256
print(out)
raise SystemExit(0 if result["command"] == "normal-completed" else 1)' \
  "$S/application-run.json" "$A" "$S/application-status.json" "$RUN_ID" < /dev/null
```

## Quiescence capture

This is q13's retained post-completion process observation with only its two
capture locators unresolved. Exit one from pgrep affirmatively means no matching
process; zero, another status or any stderr refuses. Run only after the joined
application completion and while no other service session may start. It does not
authenticate result bytes or alone prove all physical cleanup.

```bash
set -C
QUIESCENCE_CAPTURE=UNREVIEWED
QUIESCENCE_STDERR=UNREVIEWED
test ! -e "$QUIESCENCE_CAPTURE"
test ! -L "$QUIESCENCE_CAPTURE"
test ! -e "$QUIESCENCE_STDERR"
test ! -L "$QUIESCENCE_STDERR"
exec {QUIESCENCE_FD}>"$QUIESCENCE_CAPTURE"
exec {QUIESCENCE_ERR_FD}>"$QUIESCENCE_STDERR"
if /usr/bin/pgrep -u m8-service >&"$QUIESCENCE_FD" 2>&"$QUIESCENCE_ERR_FD"
then QUIESCENCE_STATUS=0; else QUIESCENCE_STATUS=$?; fi
exec {QUIESCENCE_FD}>&-
exec {QUIESCENCE_ERR_FD}>&-
test "$QUIESCENCE_STATUS" -eq 1
test -f "$QUIESCENCE_STDERR"
test ! -L "$QUIESCENCE_STDERR"
test ! -s "$QUIESCENCE_STDERR"
printf '%s\n' diagnosis-quiescence-checked
```

## Offline evidence and release limit

The selected development producer is immutable commit
`6689885723eb5571f620358f9cdeed00a44996e3`, explicitly unreviewed and unselected
for host use. The [focused composition tests](../../../tests/test_channel_reply_operator_package.py)
exercise the actual compiler's template/refusal path, LF files and shell syntax;
the real prepare producer and new source checker; the actual preflight producer
with fake host assembly; the production authority reader with only root-file
custody substituted; and an accepting/no-op real entry lifecycle with the
portable launcher followed by the actual inspector CLI through frozen T5.
The real withdrawal CLI also composes durable withdrawal, the inherited receipt
consumer and joined child completion over the existing portable OS double, on
accepting and wrong-parent cases. The shipped report CLI consumes the accepted
and no-op producer journals through frozen T5 with its top-level task purpose;
an absent-run report refuses that same complete-packet contract. No credential
is opened in these proofs.

This is not execution of all fifteen packaged steps. Drift/transfer markers in
the source-checker fixture are explicit synthetic host seams; the new stage
selection does not transform old N4 component proofs into current host evidence.
The earlier e7f6 report assumed the old task's result/request shape; this
development revision adds the two-task projection and top-level `purpose`.
Both task families now require that purpose key in a complete report packet.
Do not relabel the earlier development proofs as evidence for this or another
revision. Recheck changed producer/fixture blobs and run the affected composition
proofs when selecting the actual merged source.

No installation, qualification, useful live candidate or cleanup/park observation
is established here. Source-bound original installer files, exact late pins,
remaining complete-stage evidence and the applicable approvals must be concrete
before any host window. This paragraph states the preparation limit, not a
second work ledger or permission to resume a stopped procedure.

### Filled private-package correction after #398

The first private-specialization recipe omitted `labels.current`. Filling every
listed declaration with generation/session spellings therefore still refused
the normal build: the unchanged compiler correctly reported undeclared labels.
The corrected recipe explicitly includes only the reviewed literal spellings,
including a prior descriptor used by a negative control. An executed regression
first reproduces the empty-label refusal, also refuses a missing prior spelling,
then fills both and builds all fifteen normal step/contract pairs from synthetic
data. It checks LF bytes, complete file/manifest coverage and digests, output
contracts, absence of unresolved declarations and Bash syntax. It never executes
or uploads those scripts and establishes no real host or generation facts.

A separate initial JSON values-file attempt was a local preparation format
error, corrected to the existing TOML input contract; it was not a product defect.
The application, compiler and frozen fences are unchanged by this doc/test
correction. The controller/source bundle selected for the operating window
remains `c95ca6aaf2e9770b8e46b55f24cb70cd68ffcc71`; the corrected procedure/tooling
revision is reviewed separately and supplies no additional attempt authority.

## Composition

```toml
labels = {current = [], historical = []}

[sources.oc]
path = "M8-N4-operator-commands.md"
sha256 = "bd0972ac633be8ac919a1d271e9c6580cf0fdff7c0edafc9a2ce45fd4aa7e7b9"

[sources.lane]
path = "M8-maintenance-lane-output.md"
sha256 = "a44983423444271ef56a17295edca3309af34e27fb54ff2d968e1b7bbe2ea0e9"

[sources.guard]
path = "M8-private-output-guard.md"
sha256 = "648d5eb2eabc250874a548e5ef036f20657ed61d6149fd96075b60aff41139b7"

[sources.q12]
path = "M8-maintenance-q12-continuation.md"
sha256 = "1fbd0a983fc9537f47198221b5a84937da6b3e79fe0c15fb77b3e9b2ba4d76b1"

[sources.session]
path = "M8-maintenance-session.md"
sha256 = "66aa57ec86e3dbe1462eeb1a17a832aed6ce2cf72d3385e1fd267d74e0647ee2"

[[steps]]
name = "cr-physical-preflight"
stdout = ["drift-checked", "physical-preflight-checked"]
parts = [
  {source = "self", heading = "Source and private declarations", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Source and private declarations", fences = [1]},
  {source = "self", heading = "Drift declarations", fences = [0]},
  {literal = "DRIFT_RECORDS=\"$HOME/maintenance-channel-reply-drift-physical\""},
  {source = "self", heading = "Drift declarations", fences = [1]},
  {source = "guard", heading = "G1: private drift boundary", fences = [0]},
  {source = "q12", heading = "Q5: new and renamed VM fences", fences = [1]},
]

[[steps]]
name = "cr-session-prepare"
stdout = ["drift-checked"]
record = {keys = ["out", "prepared"], max_bytes = 1024}
parts = [
  {source = "self", heading = "Source and private declarations", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Source and private declarations", fences = [1]},
  {source = "self", heading = "Drift declarations", fences = [0]},
  {literal = "DRIFT_RECORDS=\"$HOME/maintenance-channel-reply-drift-session\""},
  {source = "self", heading = "Drift declarations", fences = [1]},
  {source = "guard", heading = "G1: private drift boundary", fences = [0]},
  {source = "oc", heading = "S1. Prepare", fences = [0]},
]

[[steps]]
name = "cr-qualification"
stdout = ["drift-checked", "lane-boundary-checked"]
parts = [
  {source = "self", heading = "Source and private declarations", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Source and private declarations", fences = [1]},
  {literal = "LANES=\"$HOME/maintenance-channel-reply-lanes-cr-qualification\""},
  {source = "self", heading = "Drift declarations", fences = [0]},
  {literal = "DRIFT_RECORDS=\"$HOME/maintenance-channel-reply-drift-qualification\""},
  {source = "self", heading = "Drift declarations", fences = [1]},
  {source = "guard", heading = "G1: private drift boundary", fences = [0]},
  {source = "lane", heading = "L0: common helpers", fences = [0]},
  {source = "lane", heading = "L1: qualification boundary", fences = [0]},
  {source = "oc", heading = "S6a. Maintenance-lock positive control", fences = [0]},
]

[[steps]]
name = "cr-publish"
stdout = ["drift-checked"]
parts = [
  {source = "self", heading = "Source and private declarations", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Source and private declarations", fences = [1]},
  {source = "self", heading = "Drift declarations", fences = [0]},
  {literal = "DRIFT_RECORDS=\"$HOME/maintenance-channel-reply-drift-publish\""},
  {source = "self", heading = "Drift declarations", fences = [1]},
  {source = "guard", heading = "G1: private drift boundary", fences = [0]},
  {source = "self", heading = "N4 publication", fences = [0]},
]

[[steps]]
name = "cr-controls"
stdout = [["drift-checked", "lane-boundary-checked", "refresh-measured", "lane-boundary-checked", "lane-boundary-checked"], ["drift-checked", "lane-boundary-checked", "refresh-unmeasured", "lane-boundary-checked", "lane-boundary-checked"]]
parts = [
  {source = "self", heading = "Source and private declarations", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Source and private declarations", fences = [1]},
  {literal = "LANES=\"$HOME/maintenance-channel-reply-lanes-cr-controls\""},
  {source = "self", heading = "Drift declarations", fences = [0]},
  {literal = "DRIFT_RECORDS=\"$HOME/maintenance-channel-reply-drift-controls\""},
  {source = "self", heading = "Drift declarations", fences = [1]},
  {source = "guard", heading = "G1: private drift boundary", fences = [0]},
  {source = "lane", heading = "L0: common helpers", fences = [0]},
  {source = "lane", heading = "L2: H7 controls", fences = [0]},
]

[[steps]]
name = "cr-refresh"
stdout = ["drift-checked", "refresh-measured"]
parts = [
  {source = "self", heading = "Source and private declarations", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Source and private declarations", fences = [1]},
  {literal = "LANES=\"$HOME/maintenance-channel-reply-lanes-cr-refresh\""},
  {source = "self", heading = "Drift declarations", fences = [0]},
  {literal = "DRIFT_RECORDS=\"$HOME/maintenance-channel-reply-drift-refresh\""},
  {source = "self", heading = "Drift declarations", fences = [1]},
  {source = "guard", heading = "G1: private drift boundary", fences = [0]},
  {source = "lane", heading = "L0: common helpers", fences = [0]},
  {source = "self", heading = "Conditional refresh declarations", fences = [0]},
  {source = "lane", heading = "L3: explicit refresh", fences = [0]},
]

[[steps]]
name = "cr-prepare"
stdout = ["drift-checked", "maintenance-bundle-transferred"]
record = {keys = ["source_prepared", "purpose", "base", "bundle_sha256", "target_sha256"], max_bytes = 1024}
parts = [
  {source = "self", heading = "Source and private declarations", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Source and private declarations", fences = [1]},
  {source = "self", heading = "Drift declarations", fences = [0]},
  {literal = "DRIFT_RECORDS=\"$HOME/maintenance-channel-reply-drift-prepare\""},
  {source = "self", heading = "Drift declarations", fences = [1]},
  {source = "guard", heading = "G1: private drift boundary", fences = [0]},
  {source = "self", heading = "Bundle transfer", fences = [0]},
  {source = "self", heading = "Application preparation", fences = [0]},
]

[[steps]]
name = "cr-preflight"
stdout = ["drift-checked"]
record = {keys = ["preview_sha256", "run_id", "purpose", "target_sha256", "authorization_id", "base", "source_graph_hash", "application_revision", "revision", "operator_binding_digest", "workspace", "gate", "not_after", "grants"], max_bytes = 8192}
parts = [
  {source = "self", heading = "Source and private declarations", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Source and private declarations", fences = [1]},
  {source = "self", heading = "Drift declarations", fences = [0]},
  {literal = "DRIFT_RECORDS=\"$HOME/maintenance-channel-reply-drift-preflight\""},
  {source = "self", heading = "Drift declarations", fences = [1]},
  {source = "guard", heading = "G1: private drift boundary", fences = [0]},
  {source = "self", heading = "Active binding", fences = [0]},
  {source = "self", heading = "Actual WRITE preflight", fences = [0]},
]

[[steps]]
name = "cr-authority"
stdout = ["drift-checked"]
deferred = true
parts = [
  {source = "self", heading = "Source and private declarations", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Source and private declarations", fences = [1]},
  {source = "self", heading = "Drift declarations", fences = [0]},
  {literal = "DRIFT_RECORDS=\"$HOME/maintenance-channel-reply-drift-authority\""},
  {source = "self", heading = "Drift declarations", fences = [1]},
  {source = "guard", heading = "G1: private drift boundary", fences = [0]},
  {source = "self", heading = "Active binding", fences = [0]},
  {source = "session", heading = "P9: install exact reviewed preview as fresh root authority", fences = [0]},
]

[[steps]]
name = "cr-run"
stdout = ["drift-checked"]
record = {keys = ["accepted", "command", "meaning", "run_id"], max_bytes = 1024}
deferred = true
parts = [
  {source = "self", heading = "Source and private declarations", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Source and private declarations", fences = [1]},
  {source = "self", heading = "Drift declarations", fences = [0]},
  {literal = "DRIFT_RECORDS=\"$HOME/maintenance-channel-reply-drift-run\""},
  {source = "self", heading = "Drift declarations", fences = [1]},
  {source = "guard", heading = "G1: private drift boundary", fences = [0]},
  {source = "self", heading = "Active binding", fences = [0]},
  {source = "self", heading = "Application capture", fences = [0]},
]

[[steps]]
name = "cr-inspect"
stdout = []
record = {keys = ["schema_version", "meaning", "purpose", "run_id", "base_sha256", "candidate_sha256", "candidate_commit"], max_bytes = 1024}
parts = [
  {source = "self", heading = "Source and private declarations", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Source and private declarations", fences = [1]},
  {source = "self", heading = "Historical inspection and report", fences = [0]},
]

[[steps]]
name = "cr-quiescence"
stdout = ["diagnosis-quiescence-checked"]
parts = [
  {source = "self", heading = "Source and private declarations", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Source and private declarations", fences = [1]},
  {source = "self", heading = "Quiescence capture", fences = [0]},
]

[[steps]]
name = "cr-report"
stdout = ["drift-checked"]
record = {keys = ["schema_version", "complete", "meaning", "run_id", "purpose", "status", "outcome", "refusal", "diagnostic", "result", "metering", "capability_accounting", "leases", "attestation", "target"], max_bytes = 8192}
deferred = true
parts = [
  {source = "self", heading = "Source and private declarations", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Source and private declarations", fences = [1]},
  {source = "self", heading = "Drift declarations", fences = [0]},
  {literal = "DRIFT_RECORDS=\"$HOME/maintenance-channel-reply-drift-report\""},
  {source = "self", heading = "Drift declarations", fences = [1]},
  {source = "guard", heading = "G1: private drift boundary", fences = [0]},
  {source = "self", heading = "Historical inspection and report", fences = [1]},
]

[[steps]]
name = "cr-withdraw"
stdout = []
record = {keys = ["highest_generation", "withdrawn"], max_bytes = 1024}
parts = [
  {source = "self", heading = "Source and private declarations", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Source and private declarations", fences = [1]},
  {source = "self", heading = "Store withdrawal", fences = [0]},
]

[[steps]]
name = "cr-authorization-retained"
stdout = []
record = {keys = ["authorization", "authorization_sha256", "purpose", "run_id"], max_bytes = 1024}
deferred = true
parts = [
  {source = "self", heading = "Source and private declarations", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Source and private declarations", fences = [1]},
  {source = "self", heading = "Retained authorization", fences = [0]},
]

```
