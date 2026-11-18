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
from typing import Any

from scripts import m8_procedure_package as packager
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
from scripts.ops.m9_read_closure import AdviceClosurePins, ClosurePins, CompletionPins
from scripts.ops.m9_read_command import (
    ADVICE,
    BOOT,
    CONTROLLER,
    M9,
    M9_SITE,
    SERVICE,
    SERVICE_STATE,
    SESSION,
    SHA,
    Site,
    paths,
    read_argv,
)
from scripts.ops.m9_read_window import Qualification

from constructicon.api import change_review_advice as route
from constructicon.api._m9 import proposer
from constructicon.api._m9.evidence import TrialIdentity
from constructicon.api._m9.safety import selector_run
from constructicon.core.errors import ContractViolation
from constructicon.core.identity import digest, json_value
from constructicon.core.qualification import QualificationAuthorization
from constructicon.substrate.executors.codex_host import READ_GRANTS

TRIAL = TrialIdentity("m9-live-1")
STORE_KEY = "n4-codex-pro"
STORE = SERVICE_STATE + "/trial"
ATTEMPT = SERVICE_STATE + "/m9.attempt"
SHARED_PHASES = (
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
)
PHASES = (*SHARED_PHASES, *M9.phases)
CLEANUP = "cleanup-no-vendor"
STORE_MUTATIONS = frozenset({"h4-startup", "h5-lock", "h6-publish", "h6-activate"})
TRIAL_PHASES = frozenset(M9.phases)
_COMPLETE = {"completed": True, "returncode": 0, "timed_out": False}
_EXEC = "&& /bin/bash phase.sh < /dev/null"
_BOOT_FILE = "/proc/sys/kernel/random/boot_id"
_BOOT_SLOT = b"UNREVIEWED"
_M9 = "M9_QUALIFICATION_"
_ADVICE = "CHANGE_REVIEW_QUALIFICATION_"
_DYNAMIC = frozenset({"provider_revision", "operator_binding_digest"})
_SELECTED = frozenset({
    "id", "source_graph", "component", "guard", "summary_sha256", "instruction_digest",
    "session", "state",
})

# The active selection has no public reader: BindingStore exposes only
# open_candidate/close_candidate and the selection check (operator_store.py
# :1098-1216), and the sealed identity is read only by _sealed_file (:1502).
# Both consumers' probes share this one reader, which M9's already used.
_LIVE_SELECTION = """\
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
""" + _LIVE_SELECTION

# The advice route's provider facts through its own host assembly, which
# keeps every published reason; the instruction-bound pins are a pure
# function of the selected summary, checked locally against consumer-pins.
# An occupied journal or attempt record is refused, never archived or removed.
_ADVICE_LIVE = """
import argparse, json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from constructicon.api import change_review_advice as advice
from constructicon.core.identity import json_value
from constructicon.substrate.executors.codex_host import LAUNCH_ROOT
from constructicon.substrate.executors import codex_lane, operator_store
controller, root, label, state, key, journal, attempt = sys.argv[1:]
session = Path(root)
sealed = session / (label + '.sealed.json')
provider = advice.require_provider(advice.host_provider(argparse.Namespace(
    session=session, store_key=key, sealed=sealed,
    qualification=session / 's6a-qualification.json', host_state=Path(state))))
record = {'provider_revision': provider.identity.revision,
    'operator_binding_digest': provider.identity.store.operator_binding_digest}
identity = operator_store._sealed_file(sealed, os.getuid())
if (record['operator_binding_digest'] != identity.operator_binding_digest
        or any(os.path.lexists(path) for path in (journal, attempt, attempt + '.next'))):
    raise SystemExit('CHANGE_REVIEW_QUALIFICATION_ACTIVE_BINDING_OR_STATE_DRIFT')
""" + _LIVE_SELECTION

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
    closure: ClosurePins | AdviceClosurePins


def _require(ok: bool, code: str, prefix: str = _M9) -> None:
    if not ok:
        raise ValueError(prefix + code)


def _hex(value: object) -> bool:
    return type(value) is str and SHA.fullmatch(value) is not None


def _digest(value: object) -> bool:
    return type(value) is str and value.startswith("sha256:") and _hex(value[7:])


def _object(raw: bytes, keys: set[str], code: str, prefix: str = _M9) -> dict:
    try:
        record = parsed(raw)
    except (ValueError, RecursionError) as exc:
        raise ValueError(prefix + code) from exc
    _require(type(record) is dict and set(record) == keys, code, prefix)
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


def _advice_fixed(selected: dict[str, Any], raw: bytes) -> dict[str, Any]:
    """What change_review_advice.pins must print for the selected summary.

    The instruction-bound values are the route's own pure producers. The
    source identities are selected: they come from the reviewed installed
    bytes, which a later or CRLF checkout does not reproduce.
    """
    try:
        bound = route.bound_values(route.ChangeSummaryV2.model_validate_json(raw))
    except (ValueError, ContractViolation) as exc:  # not the closed summary, or over bound
        raise ValueError(_ADVICE + "SUMMARY_BYTES") from exc
    _require(str(bound.instruction_digest) == selected["instruction_digest"],
             "CONSUMER_SELECTION", _ADVICE)
    fixed: dict[str, Any] = json_value({**bound.projection(), **{
        name: selected[name] for name in ("source_graph", "component", "guard")
    }})
    return fixed


def _advice_pins(raw: bytes, fixed: dict[str, Any]) -> dict[str, Any]:
    # change_review_advice.main prints json.dumps(sort_keys=True) and a newline:
    # the exact LF bytes, so CRLF or reordered output is refused, not reparsed.
    pins = _object(raw, fixed.keys() | _DYNAMIC, "CONSUMER_PINS", _ADVICE)
    _require(
        raw == transport.json_bytes(pins)
        and transport.json_bytes({name: pins[name] for name in fixed})
        == transport.json_bytes(fixed)
        and all(_digest(pins[name]) for name in _DYNAMIC),
        "CONSUMER_PINS", _ADVICE,
    )
    return pins


def _candidate(
    raw: bytes, pins: dict, authorization_id: str, now: datetime, *, key: str,
    scope: object, capability: str, journal: str, attempt: str, prefix: str,
) -> QualificationAuthorization:
    # m9_trial.mint and change_review_advice.mint emit the closed
    # QualificationAuthorization wire form; the descriptor fixes the rest.
    _require(0 < len(raw) <= 8192, "CANDIDATE_BOUND", prefix)
    try:
        candidate = QualificationAuthorization.model_validate_json(raw)
    except ValueError as exc:
        raise ValueError(prefix + "CANDIDATE_PINS") from exc
    _require(
        raw == transport.json_bytes(candidate.model_dump(mode="json"))
        and candidate.authorization_id == authorization_id
        and candidate.stage == "qualification-read"
        and candidate.max_epoch == 1
        and candidate.actor_id == pins["actor"]
        and candidate.idempotency_key == key
        and candidate.run_id == pins["run"]
        and candidate.scope == scope
        and candidate.binding == "executor"
        and candidate.capability_id == capability
        and str(candidate.source_graph_hash) == pins["source_graph"]
        and candidate.revision == pins["provider_revision"]
        and str(candidate.operator_binding_digest) == pins["operator_binding_digest"]
        and candidate.grants == READ_GRANTS
        and candidate.journal == journal
        and candidate.attempt_record == attempt
        and now < candidate.not_after <= now + timedelta(hours=1),
        "CANDIDATE_PINS",
        prefix,
    )
    return candidate


class QualificationBoundary:
    """One reviewed target and selected bundle, under already-held VM custody.

    ``selection`` is a checked JSON file; each sibling ``PHASE.sh`` is a
    reviewed LF template with exactly one ``UNREVIEWED`` boot slot. The
    shared twelve phases also bind the exact expected output bytes by SHA-256.
    H7 may select both reviewed receipts for the conditional H8 path. The
    consumer's own phases are captured and checked here against its fixed
    producers. Constructor validation runs no subprocess and spends no local
    work path. A selected script is executable authority, so the caller must
    independently verify the selection digest before using it. Keep inputs and
    captures private.

    Schemas 1 and 2 select M9: the selected ``selector`` fields (source,
    component, and source_graph) come from the reviewed controller's raw
    bytes; they differ in a later or CRLF checkout. Schema 2 adds
    ``helper_contracts``: an entry for every phase, each containing a list of
    the packager's reviewed literal contracts. Empty lists explicitly declare
    no selected helpers. Their source-only coverage and content-bound proofs
    are retained in each phase's SOURCE-PINS. Inventory completeness and shell
    semantics remain review/fixture claims. Schema 1 remains readable with
    explicit ``legacy-unverified`` coverage; it must never be reported as
    having passed these new checks.

    Schema 3 selects the change-review advice consumer, with schema 2's
    helper contracts. Its ``consumer`` fixes the source identities, the
    summary digest and the instruction digest, and a fresh service session and
    state; the sibling ``summary.json`` holds the exact summary bytes. Every
    guest path derives from those and the authorization id: there is no
    separate, independently editable path field.
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
        # No consumer is named until the schema is read.
        self._prefix = "READ_QUALIFICATION_"
        transport._target(target, alias)
        raw = bounded(selection, 2 * 1024 * 1024)
        self._need(sha(raw) == selection_sha256, "SELECTION_DIGEST")
        # v1 selections remain historical inputs with explicitly unverified
        # helper coverage. New v2 packages inventory every phase (an empty list
        # explicitly declares no selected helper) and bind source contracts.
        header = parsed(raw)
        self._need(type(header) is dict, "SELECTION_SHAPE")
        version = header.get("schema_version")
        self._need(type(version) is int and version in (1, 2, 3), "SELECTION_SHAPE")
        self._consumer = ADVICE if version == 3 else M9
        self._prefix = _ADVICE if version == 3 else _M9
        self._need(version != 1 or len(raw) <= 8192, "SELECTION_SHAPE")
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
                "authorization_id",
                "phases",
            } | ({"helper_contracts"} if version >= 2 else set())
            | ({"consumer"} if version == 3 else {"authorization", "selector"}),
            "SELECTION_SHAPE",
            self._prefix,
        )
        previous = selected["previous_boot"]
        generation = selected["previous_generation"]
        d2 = selected["d2"]
        self._need(
            type(selected["schema_version"]) is int
            and selected["schema_version"] == version
            and selected["target"] == target
            and selected["alias"] == alias
            and type(previous) is str
            and BOOT.fullmatch(previous) is not None
            and type(selected["controller"]) is str
            and re.fullmatch(r"[0-9a-f]{40}", selected["controller"]) is not None
            and _digest(selected["runtime"])
            and type(generation) is int
            and 0 < generation < 2**53 - 1
            and type(selected["authorization_id"]) is str
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", selected["authorization_id"])
            is not None,
            "SELECTION_SHAPE",
        )
        self._site: Site | None = None
        self._fixed: dict[str, Any] = {}
        self._summary = b""
        if version == 3:
            auth = self._select_consumer(selection, selected)
        else:
            auth = selected["authorization"]
            selector = selected["selector"]
            self._need(type(auth) is str, "SELECTION_SHAPE")
            self._need(
                type(selector) is dict
                and selector.keys() == {"source", "source_graph", "component"}
                and all(_digest(value) for value in selector.values()),
                "SELECTOR_SELECTION",
            )
        self._authorization = auth
        self._phases = (*SHARED_PHASES, *self._consumer.phases)
        self._remote_home = "/home/" + target.split("@", 1)[0]
        self._need(
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
        read_argv("0" * 64, auth, 1, self._site or M9_SITE)
        phases = selected["phases"]
        self._need(type(phases) is dict and phases.keys() == {*self._phases, CLEANUP},
                   "PHASE_SET")
        self._templates = {}
        self._receipts = {}
        self._contract_proofs = {}
        contracts = selected.get("helper_contracts")
        if version >= 2:
            self._need(type(contracts) is dict and contracts.keys() == {*self._phases, CLEANUP},
                       "HELPER_CONTRACT_INVENTORY")
            self._need(all(type(items) is list and len(items) <= 16 for items in contracts.values())
                       and any(contracts.values()), "HELPER_CONTRACT_INVENTORY")
        self.contract_coverage = (
            "selected-literal-source-only" if version >= 2 else "legacy-unverified"
        )
        for name in (*self._phases, CLEANUP):
            entry = phases[name]
            exact = name not in self._consumer.phases and name != CLEANUP
            self._need(
                type(entry) is dict
                and entry.keys() == ({"script", "stdout"} if exact else {"script"})
                and _hex(entry["script"]),
                "PHASE_SELECTION",
            )
            if exact:
                receipt = entry["stdout"]
                choices = receipt if type(receipt) is list else [receipt]
                self._need(
                    0 < len(choices) <= (2 if name == "h7-with-authorized-h8" else 1)
                    and all(_hex(item) for item in choices)
                    and len(set(choices)) == len(choices),
                    "PHASE_SELECTION",
                )
                self._receipts[name] = frozenset(choices)
            body = bounded(selection.with_name(name + ".sh"), 128 * 1024)
            self._need(
                sha(body) == entry["script"]
                and body.count(_BOOT_SLOT) == 1
                and body.endswith(b"\n")
                and b"\r" not in body,
                "PHASE_TEMPLATE",
            )
            self._templates[name] = body
            if version >= 2:
                try:
                    self._contract_proofs[name] = [
                        packager.helper_contract(body, contract) for contract in contracts[name]
                    ]
                except packager.Refused as exc:
                    raise packager.Refused(f"phase {name}: {exc}") from exc
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
        self._completed_phase_exit = None
        self._started = self._mutated = self._uncertain = self._withdrawn = self._park = False

    def _need(self, ok: bool, code: str) -> None:
        _require(ok, code, self._prefix)

    def selected_pins(self) -> dict[str, Any]:
        """What the reviewed selection already fixes, before any process.

        Standing-approval check point (a) compares the record with this, in
        the shape of the packet ``qualify`` builds: the consumer, controller,
        runtime and strict host-key alias, and the consumer's fixed pins
        (``_advice_fixed``). M9 selects no consumer pins.
        """
        return {
            "consumer": self._consumer.id,
            "controller": self._selected["controller"],
            "runtime": self._selected["runtime"],
            "alias": self._alias,
            "pins": dict(self._fixed),
        }

    def _select_consumer(self, selection: Path, selected: dict[str, Any]) -> str:
        """Schema 3: the advice consumer's selected data; returns its permit path."""
        chosen = selected["consumer"]
        self._need(
            type(chosen) is dict and chosen.keys() == _SELECTED
            and chosen["id"] == ADVICE.id
            and all(_digest(chosen[name]) for name in (
                "source_graph", "component", "guard", "instruction_digest",
            ))
            and _hex(chosen["summary_sha256"])
            and type(chosen["session"]) is dict and chosen["session"].keys() == {"root", "label"},
            "CONSUMER_SELECTION",
        )
        try:
            # A fresh service session and state: never M9's, which are
            # historical and must not be assumed absent or reused.
            self._site = Site(ADVICE, chosen["session"]["root"], chosen["session"]["label"],
                              chosen["state"])
            slots = paths(self._site, selected["authorization_id"])
        except ValueError as exc:
            raise ValueError(self._prefix + "CONSUMER_SELECTION") from exc
        try:
            summary = bounded(selection.with_name("summary.json"), route.INSTRUCTION_MAX_BYTES)
        except (OSError, ValueError) as exc:
            raise ValueError(self._prefix + "SUMMARY_BYTES") from exc
        # The exact selected bytes, checked before any process or placement.
        self._need(sha(summary) == chosen["summary_sha256"], "SUMMARY_BYTES")
        self._fixed = _advice_fixed(chosen, summary)
        self._summary = summary
        self._slots = slots
        return slots["authorization"]

    def _call(self, name, argv, cutoff, limit=4096):
        if name in self._phases:
            self._completed_phase_exit = None
        seconds = cutoff - time.monotonic()
        self._need(math.isfinite(seconds) and seconds > 0, "DEADLINE")
        status, out, err = transport.capture(
            name,
            self._captures,
            argv,
            seconds,
            limit,
            run=self._run,
        )
        if name in self._phases:
            # capture records completion only after subprocess.run returns.
            # ssh(1) EXIT STATUS (https://man.openbsd.org/ssh#EXIT_STATUS):
            # 255 denotes a transport error. Signal-style exits stay unknown.
            # This only permits a locked withdrawal read, not a worker-join claim.
            self._completed_phase_exit = (
                status["returncode"]
                if type(status) is dict and status.keys() == _COMPLETE.keys()
                and status["completed"] is True and status["timed_out"] is False
                and type(status["returncode"]) is int and 1 <= status["returncode"] <= 127
                else None
            )
        self._need(time.monotonic() < cutoff, "DEADLINE")
        self._need(
            status == _COMPLETE and type(status["returncode"]) is int and not err,
            "COMMAND_UNPROVED",
        )
        return out

    def _guard(self) -> str:
        self._need(self._boot is not None, "BOOT_UNPROVED")
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
            self._need(
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
            "SOURCE-PINS.json": transport.json_bytes({
                "selection_sha256": self._selection_sha,
                "helper_contract_coverage": self.contract_coverage,
                "helper_contract_proofs": self._contract_proofs.get(phase, []),
            }),
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
            self._need(self._call(f"{phase}-stage-{index}", argv, cutoff) == b"", "STAGE_OUTPUT")
        self._need(ops[3][-1].endswith(_EXEC), "STAGE_SHAPE")
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
        if self._site is None:
            args = [TRIAL.trial_id, SERVICE_STATE, SESSION, STORE_KEY, ATTEMPT]
            raw = self._probe(name, _LIVE, args, cutoff)
        else:
            site, slots = self._site, self._slots
            args = [site.root, site.label, site.state, STORE_KEY, slots["journal"],
                    slots["attempt"]]
            raw = self._probe(name, _ADVICE_LIVE, args, cutoff)
        result = _object(raw, {"pins", "generation", "qualification", "runtime"}, "LIVE_SHAPE",
                         self._prefix)
        self._need(
            type(result["generation"]) is int
            and result["generation"] == self._selected["previous_generation"] + 1
            and _digest(result["qualification"])
            and result["runtime"] == self._selected["runtime"],
            "LIVE_IDENTITY",
        )
        if self._site is None:
            result["pins"] = _trial_pins(
                transport.json_bytes(result["pins"]), self._selected["selector"]
            )
        else:
            current = result["pins"]
            self._need(type(current) is dict and current.keys() == _DYNAMIC, "LIVE_SHAPE")
            result["pins"] = _advice_pins(
                transport.json_bytes({**self._fixed, **current}), self._fixed,
            )
        return result

    def _consumer_read(
        self, captured: dict[str, bytes], live: dict[str, Any], now: datetime,
    ) -> tuple[bytes, QualificationAuthorization, ClosurePins | AdviceClosurePins]:
        """The consumer's own phases: its pins, its candidate and its closure."""
        authorization_id = self._selected["authorization_id"]
        if self._site is None:
            pins = _trial_pins(captured["trial-pins"], self._selected["selector"])
            self._need(pins == live["pins"], "LIVE_DRIFT")
            seed = {"status": "seeded",
                    **{name: pins[name] for name in ("source", "task", "input")}}
            self._need(captured["trial-seed"] == transport.json_bytes(seed), "SEED_RECEIPT")
            raw = captured["trial-mint"]
            candidate = _candidate(
                raw, pins, authorization_id, now, key=pins["key"],
                scope=proposer.PATH.scope, capability=proposer.CAPABILITY,
                journal=STORE + "/journal.sqlite", attempt=ATTEMPT, prefix=self._prefix,
            )
            return raw, candidate, ClosurePins(
                TRIAL.trial_id,
                candidate.authorization_id,
                pins["run"],
                pins["provider_revision"],
                pins["operator_binding_digest"],
                live["qualification"],
                pins["source"],
                pins["task"],
            )
        pins = _advice_pins(captured["consumer-pins"], self._fixed)
        self._need(pins == live["pins"], "LIVE_DRIFT")
        raw = captured["consumer-mint"]
        candidate = _candidate(
            raw, pins, authorization_id, now, key=pins["idempotency_key"],
            scope=route.SCOPE, capability=route.CAPABILITY,
            journal=self._slots["journal"], attempt=self._slots["attempt"], prefix=self._prefix,
        )
        return raw, candidate, AdviceClosurePins(
            CompletionPins(
                candidate.authorization_id, pins["run"], pins["provider_revision"],
                pins["operator_binding_digest"], live["qualification"],
            ),
            pins["instruction_digest"], self._site, self._summary, sha(self._summary),
        )

    def qualify(self, cutoff: float) -> QualifiedRead:
        self._need(not self._started, "ALREADY_STARTED")
        self._started = True
        self._work.mkdir(mode=0o700)
        self._captures.mkdir(mode=0o700)
        boot = self._call("boot", [*self._ssh, "/usr/bin/cat " + _BOOT_FILE], cutoff, 64)
        other = self._call(
            "independent-boot", [*self._ssh, "/usr/bin/cat -- " + _BOOT_FILE], cutoff, 64
        )
        value = boot.removesuffix(b"\n").decode("ascii")
        self._need(
            boot == other == (value + "\n").encode("ascii")
            and BOOT.fullmatch(value) is not None
            and value != self._selected["previous_boot"],
            "FRESH_BOOT",
        )
        self._boot = value
        cleanup = self._stage(CLEANUP, cutoff)
        check = [*cleanup[:-1], cleanup[-1].removesuffix(_EXEC).rstrip()]
        self._need(self._call("cleanup-prestage-hash", check, cutoff) == b"", "STAGE_OUTPUT")
        self._prepared_cleanup = cleanup
        captured = {}
        for phase in self._phases:
            command = self._stage(phase, cutoff)
            # A timeout or disconnected response is not a join. An unknown
            # qualification phase can outlive SSH and must retain custody.
            self._uncertain = True
            self._mutated |= phase in STORE_MUTATIONS
            out = self._call(phase, command, cutoff, 65536)
            self._uncertain = False
            if phase in self._consumer.phases:
                captured[phase] = out
            else:
                self._need(sha(out) in self._receipts[phase], "PHASE_RECEIPT")
            if phase == "d2-verify":
                self._need(self._d2_readback is not None, "D2_READBACK")
                readback = protected_read_command(self._d2_readback, 65536, False)
                record = self._call(
                    "d2-readback", [*self._ssh, self._guard() + " && " + readback], cutoff, 65536
                )
                d2_record(record, self._boot, self._selected["d2"]["revision"])
        live = self._observe_live("live-before-selection", cutoff)
        now = datetime.now(UTC)
        raw, candidate, closure = self._consumer_read(captured, live, now)
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
                "authorization": self._authorization,
                "candidate_sha256": sha(raw),
            }
        )
        qualification = Qualification(
            sha(transport.json_bytes(identity)),
            packet,
            raw,
            candidate.not_after,
            time.monotonic() + (candidate.not_after - now).total_seconds(),
            self._consumer.id,
        )
        self._need(time.monotonic() < cutoff, "DEADLINE")
        self._live = live
        self._qualification = QualifiedRead(
            qualification,
            self._target,
            self._alias,
            self._boot,
            self._authorization,
            closure,
        )
        return self._qualification

    def check_live(self, qualified: QualifiedRead, cutoff: float) -> bool:
        self._need(qualified is self._qualification and not self._withdrawn, "LIVE_SELECTION")
        self._serial += 1
        matches = self._observe_live(f"live-check-{self._serial}", cutoff) == self._live
        self._need(time.monotonic() < cutoff, "DEADLINE")
        return matches

    def withdraw(self, qualified: QualifiedRead | None, cutoff: float) -> str:
        self._need(
            self._boot is not None
            and (not self._uncertain or (
                self._completed_phase_exit is not None and not self._mutated
            ))
            and not self._withdrawn
            and (qualified is None or qualified is self._qualification),
            "WITHDRAW_UNSAFE",
        )
        # Consume eligibility before the read-only locked probe. Failure keeps
        # uncertainty/custody and cannot license another probe or a park.
        self._completed_phase_exit = None
        floor = self._selected["previous_generation"]
        receipts = []
        if self._mutated:
            self._need(self._prepared_cleanup is not None, "WITHDRAW_UNPREPARED")
            self._uncertain = True
            out = self._call(CLEANUP, self._prepared_cleanup, cutoff, 128)
            # The selected no-vendor package writes this after StoreMaintenance.check.
            matched = [
                n for n in (floor, floor + 1) if out == f"codex-withdrawn-floor-{n}\n".encode()
            ]
            self._need(
                len(matched) == 1 and (qualified is None or matched[0] == floor + 1),
                "WITHDRAW_RECEIPT",
            )
            floor = matched[0]
            receipts.append(sha(out))
        observed = self._probe("withdraw-readback", _WITHDRAWN, [STORE_KEY], cutoff)
        self._need(
            observed == transport.json_bytes({"key": STORE_KEY, "generation_floor": floor}),
            "WITHDRAW_READBACK",
        )
        receipts.append(sha(observed))
        checked = transport.json_bytes({"boot": self._boot, "withdrawal_receipts": receipts})
        transport.retain(self._captures / "withdraw-checked.json", checked)
        self._need(time.monotonic() < cutoff, "DEADLINE")
        self._withdrawn = True
        return sha(checked)

    def park(self, cutoff: float) -> None:
        self._need(self._withdrawn and not self._park, "PARK_UNSAFE")
        self._park = True
        now = time.monotonic()
        request_cutoff = (
            now + (cutoff - now) * 2 / 3
        )  # Reserve time for the independent observation.
        self._need(
            self._call("park-boot", [*self._ssh, self._guard()], request_cutoff) == b"",
            "PARK_BOOT_UNPROVED",
        )
        # M8-D2-host-installation.md: clean Stop-VM, never Save-VM or force-off.
        argv = [
            *m8_vm_usage.powershell_argv()[:-1],
            "$ErrorActionPreference = 'Stop'; Stop-VM -Name 'constructicon-m8'",
        ]
        self._need(self._call("park", argv, request_cutoff) == b"", "PARK_OUTPUT")

    def check_park(self, cutoff: float) -> str:
        self._need(self._withdrawn and self._park, "PARK_NOT_REQUESTED")
        raw = self._call(
            "park-usage", m8_vm_usage.powershell_argv(), cutoff, m8_vm_usage.MAX_SOURCE_BYTES
        )
        report = m8_vm_usage._parse(raw)
        self._need(report["verdict"] == "idle-observed", "PARK_UNPROVED")
        checked = transport.json_bytes(report)
        transport.retain(self._captures / "park-checked.json", checked)
        self._need(time.monotonic() < cutoff, "DEADLINE")
        return sha(checked)
