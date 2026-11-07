"""Run selected Codex qualification packages on one already-started guest.

The selection digest must come from independent review of the current
installation, custody and qualification procedure. No embedded selection,
previous capture, or reusable owner authorization exists in this adapter.
"""

from __future__ import annotations

import math
import re
import shlex
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts import m8_vm_usage
from scripts.ops import claude_read_session as transport
from scripts.ops.claude_read_commands import (
    _d2_script,
    bounded,
    d2_record,
    parsed,
    protected_read_command,
    sha,
)
from scripts.ops.m9_read_closure import ClosurePins
from scripts.ops.m9_read_command import (
    BOOT,
    CONTROLLER,
    SERVICE,
    SERVICE_STATE,
    SESSION,
    SHA,
    read_argv,
)
from scripts.ops.m9_read_window import Qualification

from constructicon.api._m9 import proposer
from constructicon.api._m9.evidence import TrialIdentity
from constructicon.api._m9.safety import selector_run
from constructicon.core.identity import digest, json_value
from constructicon.core.qualification import QualificationAuthorization
from constructicon.substrate.executors.codex_host import READ_GRANTS

TRIAL = TrialIdentity("m9-live-1")
STORE_KEY = "n4-codex-pro"
STORE = SERVICE_STATE + "/trial"
ATTEMPT = SERVICE_STATE + "/m9.attempt"
PHASES = (
    "d2-preserve",
    "d2-verify",
    "preflight-custody-floor",
    "verify-retained-install",
    "physical-preflight",
    "fresh-workspaces",
    "h3-prepare",
    "h4-startup",
    "h5-lock",
    "h6-publish",
    "h6-activate",
    "h7-with-authorized-h8",
    "trial-seed",
    "trial-pins",
    "trial-mint",
)
CLEANUP = "cleanup-no-vendor"
STORE_MUTATIONS = frozenset({"h4-startup", "h5-lock", "h6-publish", "h6-activate"})
TRIAL_PHASES = frozenset({"trial-seed", "trial-pins", "trial-mint"})
_COMPLETE = {"completed": True, "returncode": 0, "timed_out": False}
_EXEC = "&& /bin/bash phase.sh < /dev/null"
_BOOT_FILE = "/proc/sys/kernel/random/boot_id"
_BOOT_SLOT = b"UNREVIEWED"

# `m9_trial.pins` (src/constructicon/api/m9_trial.py) checks the sealed startup
# against the installed runtime, but does not open the active selection. Check
# that selection separately using the same sealed store identity and substrate.
# The pins entry may install its idempotent local deny-push hook; it has no
# model dispatch or operator store mutation path.
_LIVE = """
import argparse, json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from constructicon.api.m9_trial import pins
from constructicon.api._m9.evidence import TrialIdentity
from constructicon.core.identity import json_value
from constructicon.substrate.executors.codex_host import LAUNCH_ROOT
from constructicon.substrate.executors import codex_lane, operator_store
controller, trial, state, session, key, attempt = sys.argv[1:]
state, session = Path(state), Path(session)
sealed = session / 'g12.sealed.json'
record = pins(argparse.Namespace(store=state / 'trial', session=session, store_key=key,
    sealed=sealed, qualification=session / 's6a-qualification.json', state=state),
    TrialIdentity(trial))
identity = operator_store._sealed_file(sealed, os.getuid())
if (record['operator_binding_digest'] != identity.operator_binding_digest
        or os.path.lexists(attempt)):
    raise SystemExit('M9_QUALIFICATION_ACTIVE_BINDING_OR_ATTEMPT_DRIFT')
store = operator_store.BindingStore(LAUNCH_ROOT / 'operator-stores', key, identity)
opened = store.open_candidate()
try:
    descriptor = store._check_selection(opened)
    value = {'pins': record, 'generation': descriptor.generation,
        'qualification': identity.subscription_mode_adapter_revision,
        'runtime': codex_lane._launcher(LAUNCH_ROOT).expected_runtime}
finally:
    store.close_candidate(opened)
print(json.dumps(json_value(value), sort_keys=True))
"""

# `maintain_offline` publishes this withdrawal after syncing `active.json`.
# Read it under the same lock, without repairing or mutating the store.
_WITHDRAWN = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from constructicon.substrate.executors.codex_host import LAUNCH_ROOT
from constructicon.substrate.executors import operator_store as store
key = sys.argv[2]
opened = store._open_offline(LAUNCH_ROOT / 'operator-stores', key, 0,
    'M9_QUALIFICATION_WITHDRAWAL_LOCK_UNAVAILABLE', after_reboot=True)
try:
    withdrawn = store._current_withdrawal(opened, key)
    print(json.dumps({'key': withdrawn.key, 'generation_floor': withdrawn.generation_floor},
                     sort_keys=True))
finally:
    store._close_opened(opened)
"""


@dataclass(frozen=True)
class QualifiedRead:
    qualification: Qualification
    target: str
    alias: str
    boot: str
    authorization: str
    closure: ClosurePins


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise ValueError("M9_QUALIFICATION_" + code)


def _hex(value: object) -> bool:
    return type(value) is str and SHA.fullmatch(value) is not None


def _digest(value: object) -> bool:
    return type(value) is str and value.startswith("sha256:") and _hex(value[7:])


def _object(raw: bytes, keys: set[str], code: str) -> dict:
    try:
        record = parsed(raw)
    except (ValueError, RecursionError) as exc:
        raise ValueError("M9_QUALIFICATION_" + code) from exc
    _require(type(record) is dict and set(record) == keys, code)
    return record


def _fixed_pins(selector: dict) -> dict:
    # The same fixed producers as m9_trial.seed and m9_trial.pins.
    return json_value(
        {
            **selector,
            "task": digest("m9-selector-task", 1, proposer.task().model_dump(mode="json")),
            "input": digest("inputs", 1, {"training": proposer.training()}),
            "grants": READ_GRANTS.model_dump(mode="json"),
            "run": selector_run(TRIAL),
            "actor": proposer.ACTOR.actor_id,
            "key": TRIAL.key("select"),
            "evaluation": "scripted-diagnostic-exam",
        }
    )


def _trial_pins(raw: bytes, selector: dict) -> dict:
    fixed = _fixed_pins(selector)
    actual = {"provider_revision", "operator_binding_digest"}
    pins = _object(raw, fixed.keys() | actual, "SELECTOR_PINS")
    _require(
        transport.json_bytes({name: pins[name] for name in fixed}) == transport.json_bytes(fixed)
        and all(_digest(pins[name]) for name in actual),
        "SELECTOR_PINS",
    )
    return pins


def _candidate(
    raw: bytes, pins: dict, authorization_id: str, now: datetime
) -> QualificationAuthorization:
    # m9_trial.mint emits the closed QualificationAuthorization wire form.
    _require(0 < len(raw) <= 8192, "CANDIDATE_BOUND")
    candidate = QualificationAuthorization.model_validate_json(raw)
    _require(
        raw == transport.json_bytes(candidate.model_dump(mode="json"))
        and candidate.authorization_id == authorization_id
        and candidate.stage == "qualification-read"
        and candidate.max_epoch == 1
        and candidate.actor_id == pins["actor"]
        and candidate.idempotency_key == pins["key"]
        and candidate.run_id == pins["run"]
        and candidate.scope == proposer.PATH.scope
        and candidate.binding == "executor"
        and candidate.capability_id == proposer.CAPABILITY
        and str(candidate.source_graph_hash) == pins["source_graph"]
        and candidate.revision == pins["provider_revision"]
        and str(candidate.operator_binding_digest) == pins["operator_binding_digest"]
        and candidate.grants == READ_GRANTS
        and candidate.journal == STORE + "/journal.sqlite"
        and candidate.attempt_record == ATTEMPT
        and now < candidate.not_after <= now + timedelta(hours=1),
        "CANDIDATE_PINS",
    )
    return candidate


class QualificationBoundary:
    """One reviewed target and selected bundle, under already-held VM custody.

    ``selection`` is a checked JSON file; each sibling ``PHASE.sh`` is a
    reviewed LF template with exactly one ``UNREVIEWED`` boot slot. The first
    twelve phases also bind the exact expected output bytes by SHA-256. H7 may
    select both reviewed receipts for the conditional H8 path. The
    selected ``selector`` fields (source, component, and source_graph) come
    from the reviewed controller's raw bytes: they differ in a later or CRLF
    checkout. The installed trial's three dynamic receipts are checked here.
    Constructor validation runs no subprocess and spends no local work path.
    A selected script is executable authority, so the caller must independently
    verify the selection digest before using it. Keep inputs and captures private.
    """

    def __init__(
        self,
        selection: Path,
        selection_sha256: str,
        work: Path,
        *,
        target: str,
        alias: str,
        run=None,
    ) -> None:
        transport._target(target, alias)
        raw = bounded(selection, 8192)
        _require(sha(raw) == selection_sha256, "SELECTION_DIGEST")
        selected = _object(
            raw,
            {
                "schema_version",
                "target",
                "alias",
                "previous_boot",
                "controller",
                "d2",
                "runtime",
                "previous_generation",
                "authorization",
                "authorization_id",
                "phases",
                "selector",
            },
            "SELECTION_SHAPE",
        )
        previous = selected["previous_boot"]
        generation = selected["previous_generation"]
        auth = selected["authorization"]
        selector = selected["selector"]
        d2 = selected["d2"]
        _require(
            type(selected["schema_version"]) is int
            and selected["schema_version"] == 1
            and selected["target"] == target
            and selected["alias"] == alias
            and type(previous) is str
            and BOOT.fullmatch(previous) is not None
            and type(selected["controller"]) is str
            and re.fullmatch(r"[0-9a-f]{40}", selected["controller"]) is not None
            and _digest(selected["runtime"])
            and type(generation) is int
            and 0 < generation < 2**53 - 1
            and type(auth) is str
            and type(selected["authorization_id"]) is str
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", selected["authorization_id"])
            is not None,
            "SELECTION_SHAPE",
        )
        _require(
            type(selector) is dict
            and selector.keys() == {"source", "source_graph", "component"}
            and all(_digest(value) for value in selector.values()),
            "SELECTOR_SELECTION",
        )
        self._remote_home = "/home/" + target.split("@", 1)[0]
        _require(
            type(d2) is dict
            and d2.keys() == {"revision", "workspace", "helper_sha256", "drift_sha256", "drift_hex"}
            and type(d2["revision"]) is str
            and re.fullmatch(r"[0-9a-f]{40}", d2["revision"]) is not None
            and type(d2["workspace"]) is str
            and re.fullmatch(re.escape(self._remote_home) + r"/[A-Za-z0-9_-]+", d2["workspace"])
            is not None
            and _hex(d2["helper_sha256"])
            and _hex(d2["drift_sha256"])
            and type(d2["drift_hex"]) is str
            and re.fullmatch(r"(?:[0-9a-f]{2}){1,1024}", d2["drift_hex"]) is not None,
            "D2_SELECTION",
        )
        read_argv("0" * 64, auth, 1)
        phases = selected["phases"]
        _require(type(phases) is dict and phases.keys() == {*PHASES, CLEANUP}, "PHASE_SET")
        self._templates = {}
        self._receipts = {}
        for name in (*PHASES, CLEANUP):
            entry = phases[name]
            exact = name not in TRIAL_PHASES and name != CLEANUP
            _require(
                type(entry) is dict
                and entry.keys() == ({"script", "stdout"} if exact else {"script"})
                and _hex(entry["script"]),
                "PHASE_SELECTION",
            )
            if exact:
                receipt = entry["stdout"]
                choices = receipt if type(receipt) is list else [receipt]
                _require(
                    0 < len(choices) <= (2 if name == "h7-with-authorized-h8" else 1)
                    and all(_hex(item) for item in choices)
                    and len(set(choices)) == len(choices),
                    "PHASE_SELECTION",
                )
                self._receipts[name] = frozenset(choices)
            body = bounded(selection.with_name(name + ".sh"), 128 * 1024)
            _require(
                sha(body) == entry["script"]
                and body.count(_BOOT_SLOT) == 1
                and body.endswith(b"\n")
                and b"\r" not in body,
                "PHASE_TEMPLATE",
            )
            self._templates[name] = body
        self._work, self._captures, self._run = work, work / "captures", run
        self._selected, self._selection_sha = selected, selection_sha256
        self._target, self._alias = target, alias
        self._ssh = [transport.SSH, "-T", *transport.ssh_options(alias), target]
        self._boot = None
        self._prepared_cleanup = None
        self._qualification = None
        self._live = None
        self._serial = 0
        self._d2_readback = None
        self._started = self._mutated = self._uncertain = self._withdrawn = self._park = False

    def _call(self, name, argv, cutoff, limit=4096):
        seconds = cutoff - time.monotonic()
        _require(math.isfinite(seconds) and seconds > 0, "DEADLINE")
        status, out, err = transport.capture(
            name,
            self._captures,
            argv,
            seconds,
            limit,
            run=self._run,
        )
        _require(time.monotonic() < cutoff, "DEADLINE")
        _require(
            status == _COMPLETE and type(status["returncode"]) is int and not err,
            "COMMAND_UNPROVED",
        )
        return out

    def _guard(self) -> str:
        _require(self._boot is not None, "BOOT_UNPROVED")
        return f'test "$(/usr/bin/cat {_BOOT_FILE})" = {self._boot}'

    def _probe(self, name, code, args, cutoff):
        command = shlex.join([*SERVICE, code, CONTROLLER, *args])
        return self._call(name, [*self._ssh, self._guard() + " && " + command], cutoff, 8192)

    def _stage(self, phase, cutoff):
        guard = self._guard() + " && "
        binding = {"boot": self._boot, "controller": self._selected["controller"], "phase": phase}
        script = self._templates[phase].replace(_BOOT_SLOT, self._boot.encode("ascii"))
        if phase in ("d2-preserve", "d2-verify"):
            d2 = self._selected["d2"]
            _require(
                script
                == _d2_script(
                    {
                        "EXPECTED_BOOT": self._boot,
                        "__d2_commit": d2["revision"],
                        "__d2_workspace": d2["workspace"],
                        "__drift_sha256": d2["drift_sha256"],
                        "__drift_hex": d2["drift_hex"],
                    },
                    phase,
                ),
                "D2_SCRIPT_SELECTION",
            )
        files = {
            "bindings.json": transport.json_bytes(binding),
            "phase.sh": script,
            "SOURCE-PINS.json": transport.json_bytes({"selection_sha256": self._selection_sha}),
        }
        manifest = "".join(f"{sha(files[name])}  {name}\n" for name in sorted(files)).encode(
            "ascii"
        )
        package = self._work / phase
        package.mkdir(mode=0o700)
        for name, raw in {**files, "MANIFEST.sha256": manifest}.items():
            transport.retain(package / name, raw)
        manifest_sha = sha(manifest)
        remote = "m9-qual-" + manifest_sha[:24]
        ops = transport.staging_commands(package, manifest_sha, remote, self._target, self._alias)
        for index, argv in enumerate(ops[:3]):
            if index != 2:  # SCP transfers inert bytes; both SSH commands check boot.
                argv = [*argv[:-1], guard + argv[-1]]
            _require(self._call(f"{phase}-stage-{index}", argv, cutoff) == b"", "STAGE_OUTPUT")
        _require(ops[3][-1].endswith(_EXEC), "STAGE_SHAPE")
        if phase in ("d2-preserve", "d2-verify"):
            d2 = self._selected["d2"]
            helper = shlex.quote(d2["workspace"] + "/m8_host_artifacts.py")
            guard += (
                f"/usr/bin/sudo -n true < /dev/null && test -f {helper} && test ! -L {helper} && "
                f'test "$(/usr/bin/sha256sum -- {helper} | /usr/bin/cut -d " " -f 1)"'
                f" = {d2['helper_sha256']} && "
            )
            if phase == "d2-verify":
                self._d2_readback = self._remote_home + "/" + remote + "/d2-records/lr2.out"
        return [*ops[3][:-1], guard + ops[3][-1]]

    def _observe_live(self, name, cutoff):
        raw = self._probe(
            name, _LIVE, [TRIAL.trial_id, SERVICE_STATE, SESSION, STORE_KEY, ATTEMPT], cutoff
        )
        result = _object(raw, {"pins", "generation", "qualification", "runtime"}, "LIVE_SHAPE")
        _require(
            type(result["generation"]) is int
            and result["generation"] == self._selected["previous_generation"] + 1
            and _digest(result["qualification"])
            and result["runtime"] == self._selected["runtime"],
            "LIVE_IDENTITY",
        )
        result["pins"] = _trial_pins(
            transport.json_bytes(result["pins"]), self._selected["selector"]
        )
        return result

    def qualify(self, cutoff: float) -> QualifiedRead:
        _require(not self._started, "ALREADY_STARTED")
        self._started = True
        self._work.mkdir(mode=0o700)
        self._captures.mkdir(mode=0o700)
        boot = self._call("boot", [*self._ssh, "/usr/bin/cat " + _BOOT_FILE], cutoff, 64)
        other = self._call(
            "independent-boot", [*self._ssh, "/usr/bin/cat -- " + _BOOT_FILE], cutoff, 64
        )
        value = boot.removesuffix(b"\n").decode("ascii")
        _require(
            boot == other == (value + "\n").encode("ascii")
            and BOOT.fullmatch(value) is not None
            and value != self._selected["previous_boot"],
            "FRESH_BOOT",
        )
        self._boot = value
        cleanup = self._stage(CLEANUP, cutoff)
        check = [*cleanup[:-1], cleanup[-1].removesuffix(_EXEC).rstrip()]
        _require(self._call("cleanup-prestage-hash", check, cutoff) == b"", "STAGE_OUTPUT")
        self._prepared_cleanup = cleanup
        captured = {}
        for phase in PHASES:
            command = self._stage(phase, cutoff)
            # A timeout or disconnected response is not a join. An unknown
            # qualification phase can outlive SSH and must retain custody.
            self._uncertain = True
            self._mutated |= phase in STORE_MUTATIONS
            out = self._call(phase, command, cutoff, 65536)
            self._uncertain = False
            if phase in TRIAL_PHASES:
                captured[phase] = out
            else:
                _require(sha(out) in self._receipts[phase], "PHASE_RECEIPT")
            if phase == "d2-verify":
                _require(self._d2_readback is not None, "D2_READBACK")
                readback = protected_read_command(self._d2_readback, 65536, False)
                record = self._call(
                    "d2-readback", [*self._ssh, self._guard() + " && " + readback], cutoff, 65536
                )
                d2_record(record, self._boot, self._selected["d2"]["revision"])
        live = self._observe_live("live-before-selection", cutoff)
        pins = _trial_pins(captured["trial-pins"], self._selected["selector"])
        _require(pins == live["pins"], "LIVE_DRIFT")
        seed = {"status": "seeded", **{name: pins[name] for name in ("source", "task", "input")}}
        _require(captured["trial-seed"] == transport.json_bytes(seed), "SEED_RECEIPT")
        raw = captured["trial-mint"]
        now = datetime.now(UTC)
        candidate = _candidate(raw, pins, self._selected["authorization_id"], now)
        closure = ClosurePins(
            TRIAL.trial_id,
            candidate.authorization_id,
            pins["run"],
            pins["provider_revision"],
            pins["operator_binding_digest"],
            live["qualification"],
            pins["source"],
            pins["task"],
        )
        identity = {
            "target": self._target,
            "boot": self._boot,
            "generation": live["generation"],
            "qualification": live["qualification"],
        }
        packet = transport.json_bytes(
            {
                **live,
                **identity,
                "alias": self._alias,
                "selection_sha256": self._selection_sha,
                "controller": self._selected["controller"],
                "authorization": self._selected["authorization"],
                "candidate_sha256": sha(raw),
            }
        )
        qualification = Qualification(
            sha(transport.json_bytes(identity)),
            packet,
            raw,
            candidate.not_after,
            time.monotonic() + (candidate.not_after - now).total_seconds(),
        )
        _require(time.monotonic() < cutoff, "DEADLINE")
        self._live = live
        self._qualification = QualifiedRead(
            qualification,
            self._target,
            self._alias,
            self._boot,
            self._selected["authorization"],
            closure,
        )
        return self._qualification

    def check_live(self, qualified: QualifiedRead, cutoff: float) -> bool:
        _require(qualified is self._qualification and not self._withdrawn, "LIVE_SELECTION")
        self._serial += 1
        matches = self._observe_live(f"live-check-{self._serial}", cutoff) == self._live
        _require(time.monotonic() < cutoff, "DEADLINE")
        return matches

    def withdraw(self, qualified: QualifiedRead | None, cutoff: float) -> str:
        _require(
            self._boot is not None
            and not self._uncertain
            and not self._withdrawn
            and (qualified is None or qualified is self._qualification),
            "WITHDRAW_UNSAFE",
        )
        floor = self._selected["previous_generation"]
        receipts = []
        if self._mutated:
            _require(self._prepared_cleanup is not None, "WITHDRAW_UNPREPARED")
            self._uncertain = True
            out = self._call(CLEANUP, self._prepared_cleanup, cutoff, 128)
            # The selected no-vendor package writes this after StoreMaintenance.check.
            matched = [
                n for n in (floor, floor + 1) if out == f"codex-withdrawn-floor-{n}\n".encode()
            ]
            _require(
                len(matched) == 1 and (qualified is None or matched[0] == floor + 1),
                "WITHDRAW_RECEIPT",
            )
            floor = matched[0]
            receipts.append(sha(out))
        observed = self._probe("withdraw-readback", _WITHDRAWN, [STORE_KEY], cutoff)
        _require(
            observed == transport.json_bytes({"key": STORE_KEY, "generation_floor": floor}),
            "WITHDRAW_READBACK",
        )
        receipts.append(sha(observed))
        checked = transport.json_bytes({"boot": self._boot, "withdrawal_receipts": receipts})
        transport.retain(self._captures / "withdraw-checked.json", checked)
        _require(time.monotonic() < cutoff, "DEADLINE")
        self._withdrawn = True
        return sha(checked)

    def park(self, cutoff: float) -> None:
        _require(self._withdrawn and not self._park, "PARK_UNSAFE")
        self._park = True
        now = time.monotonic()
        request_cutoff = (
            now + (cutoff - now) * 2 / 3
        )  # Reserve time for the independent observation.
        _require(
            self._call("park-boot", [*self._ssh, self._guard()], request_cutoff) == b"",
            "PARK_BOOT_UNPROVED",
        )
        # M8-D2-host-installation.md: clean Stop-VM, never Save-VM or force-off.
        argv = [
            *m8_vm_usage.powershell_argv()[:-1],
            "$ErrorActionPreference = 'Stop'; Stop-VM -Name 'constructicon-m8'",
        ]
        _require(self._call("park", argv, request_cutoff) == b"", "PARK_OUTPUT")

    def check_park(self, cutoff: float) -> str:
        _require(self._withdrawn and self._park, "PARK_NOT_REQUESTED")
        raw = self._call(
            "park-usage", m8_vm_usage.powershell_argv(), cutoff, m8_vm_usage.MAX_SOURCE_BYTES
        )
        report = m8_vm_usage._parse(raw)
        _require(report["verdict"] == "idle-observed", "PARK_UNPROVED")
        checked = transport.json_bytes(report)
        transport.retain(self._captures / "park-checked.json", checked)
        _require(time.monotonic() < cutoff, "DEADLINE")
        return sha(checked)
