"""Maintenance-only entry for the finite Claude native conversations.

The JSON configuration is a reviewed installation input, not a discovery or
installer. Each invocation uses one root-held withdrawn store and one process.
Evidence records bounded lifecycle facts, never login or subscription approval.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from constructicon.core.identity import Digest, digest, parse_json_value
from constructicon.substrate.executors.claude_maintenance_login import (
    LIFETIME_SECONDS as LOGIN_SECONDS,
)
from constructicon.substrate.executors.claude_maintenance_mode import (
    INPUT_BYTES as MODE_INPUT_BYTES,
)
from constructicon.substrate.executors.claude_maintenance_mode import (
    LIFETIME_SECONDS as MODE_SECONDS,
)
from constructicon.substrate.executors.claude_maintenance_mode import (
    OUTPUT_BYTES as MODE_OUTPUT_BYTES,
)
from constructicon.substrate.executors.claude_maintenance_session import (
    ClaudeMaintenanceSessionFacts,
    ClaudeMaintenanceSessionLifecycle,
    ClaudeMaintenanceSessionPhase,
    run_maintenance_session,
)
from constructicon.substrate.executors.claude_native import (
    ClaudeNativeRecipe,
    ClaudeNativeVendor,
)
from constructicon.substrate.executors.claude_operator_io import (
    LINE_BYTES as LOGIN_INPUT_BYTES,
)
from constructicon.substrate.executors.claude_operator_io import (
    STDERR_BYTES,
    ClaudeOperatorFDIO,
)
from constructicon.substrate.executors.claude_operator_io import (
    STDOUT_BYTES as LOGIN_OUTPUT_BYTES,
)
from constructicon.substrate.executors.claude_protocol import (
    CLAUDE_CODE_VERSION,
    RECORD_BYTES,
    ClaudePlan,
)
from constructicon.substrate.executors.codex_lane import EvidenceFile, _fsync_directory
from constructicon.substrate.executors.egress import (
    EgressDestination,
    EgressPolicy,
    identity_digests,
)
from constructicon.substrate.executors.linux import BWRAP_SHA256, LinuxLauncher, ProcessLimits
from constructicon.substrate.executors.operator_store import inherit_maintenance

EVIDENCE_DOMAIN = "claude-maintenance-entry-evidence"
EVIDENCE_SCHEMA = 1
CONFIG_BYTES = 8 * 1024
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_PHASE_HOSTS = {
    "login": frozenset({"platform.claude.com"}),
    "observe": frozenset({"platform.claude.com", "api.anthropic.com"}),
    "reload": frozenset({"platform.claude.com", "api.anthropic.com"}),
}
_CONFIG_FIELDS = frozenset({
    "schema_version", "launch_root", "runtime_digest", "bubblewrap_sha256",
    "launch_policy", "launch_policy_sha256", "vendor_tree", "vendor_digest",
    "vendor_version", "model", "effort", "egress",
})
_QUALIFICATION_SOURCES = (
    "constructicon.substrate.executors.claude_lane",
    "constructicon.substrate.executors.claude_maintenance_session",
    "constructicon.substrate.executors.claude_startup_qualification",
    "constructicon.substrate.executors.claude_maintenance_mode",
    "constructicon.substrate.executors.claude_startup",
    "constructicon.substrate.executors.claude_protocol",
    "constructicon.substrate.executors.claude_native_events",
    "constructicon.substrate.executors.claude_initialize",
    "constructicon.substrate._lifetime",
    "constructicon.core.identity",
)


def qualification_revision() -> Digest:
    """Bind QUALIFY evidence to the actual source law, not a stable label."""
    sources: dict[str, Path] = {}
    for name in _QUALIFICATION_SOURCES:
        module = sys.modules.get(name)
        source = inspect.getsourcefile(module) if module is not None else None
        if source is None or Path(source).suffix != ".py":
            raise ValueError("Claude qualification source is not loaded")
        sources[name] = Path(source)
    source_hashes = {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in sources.items()
    }
    source_hashes["codex.EvidenceFile"] = hashlib.sha256(
        inspect.getsource(EvidenceFile).encode("utf-8")
    ).hexdigest()
    source_hashes["codex._fsync_directory"] = hashlib.sha256(
        inspect.getsource(_fsync_directory).encode("utf-8")
    ).hexdigest()
    return digest("claude-startup-qualification-source", 1, source_hashes)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        self.exit(2, "Claude maintenance entry refused\n")


def _absolute(value: object) -> Path:
    if type(value) is not str or not value or len(value) > 4096:
        raise ValueError("invalid trusted path")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("invalid trusted path")
    return path


def _digest(value: object) -> Digest:
    if type(value) is not str:
        raise ValueError("invalid trusted digest")
    return Digest(value)


def _sha256(value: object) -> str:
    if type(value) is not str or _HEX.fullmatch(value) is None:
        raise ValueError("invalid trusted sha256")
    return value


def _policy(value: object, *, phase: str) -> EgressPolicy:
    if type(value) is not dict or set(value) != {"destinations", "connections"}:
        raise ValueError("invalid trusted egress policy")
    destinations = value["destinations"]
    connections = value["connections"]
    if (type(destinations) is not list or len(destinations) != len(_PHASE_HOSTS[phase])
            or type(connections) is not int or connections <= 0):
        raise ValueError("invalid trusted egress policy")
    items: list[EgressDestination] = []
    for item in destinations:
        if (type(item) is not list or len(item) != 3 or type(item[0]) is not str
                or type(item[1]) is not int or item[1] != 443
                or type(item[2]) is not str):
            raise ValueError("invalid trusted egress destination")
        items.append(EgressDestination(item[0], item[1], item[2]))
    if {item.host for item in items} != _PHASE_HOSTS[phase]:
        raise ValueError("invalid trusted egress destination")
    return EgressPolicy(tuple(items), connections)


@dataclass(frozen=True, slots=True)
class LaneConfiguration:
    configuration_sha256: str
    launch_root: Path
    runtime_digest: Digest
    launch_policy: Path
    launch_policy_sha256: str
    vendor_tree: Path
    vendor_digest: Digest
    model: str
    effort: str
    egress: dict[str, EgressPolicy]

    def launcher(self, phase: ClaudeMaintenanceSessionPhase) -> LinuxLauncher:
        recipe = (ClaudeNativeRecipe.LOGIN if phase is ClaudeMaintenanceSessionPhase.LOGIN
                  else ClaudeNativeRecipe.STREAM_JSON)
        login = phase is ClaudeMaintenanceSessionPhase.LOGIN
        return LinuxLauncher(
            runtime_root=self.launch_root / "runtime",
            expected_runtime=self.runtime_digest,
            bubblewrap=self.launch_root / "bwrap",
            policy=self.launch_policy,
            expected_policy_sha256=self.launch_policy_sha256,
            limits=ProcessLimits(
                input_bytes=LOGIN_INPUT_BYTES if login else MODE_INPUT_BYTES,
                stdout_bytes=LOGIN_OUTPUT_BYTES if login else MODE_OUTPUT_BYTES,
                record_bytes=RECORD_BYTES, stderr_bytes=STDERR_BYTES,
            ),
            claude=ClaudeNativeVendor(self.vendor_tree, self.model, self.effort,
                                      self.vendor_digest),
            claude_recipe=recipe,
        )


def read_configuration(path: Path, *, expected_sha256: str) -> LaneConfiguration:
    """Read one bounded, duplicate-free reviewed assembly snapshot."""
    expected_sha256 = _sha256(expected_sha256)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("invalid trusted configuration")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("invalid trusted configuration")
    flags = (os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
             | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if (not stat.S_ISREG(opened.st_mode)
                or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)):
            raise ValueError("trusted configuration changed")
        parts: list[bytes] = []
        remaining = CONFIG_BYTES + 1
        while remaining:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            parts.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(parts)
    finally:
        os.close(fd)
    if not 0 < len(raw) <= CONFIG_BYTES:
        raise ValueError("invalid trusted configuration size")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("trusted configuration differs from reviewed bytes")
    value = parse_json_value(raw.decode("utf-8"))
    if type(value) is not dict or set(value) != _CONFIG_FIELDS:
        raise ValueError("invalid trusted configuration fields")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("invalid trusted configuration schema")
    if _sha256(value["bubblewrap_sha256"]) != BWRAP_SHA256:
        raise ValueError("unsupported bubblewrap identity")
    if type(value["vendor_version"]) is not str or value["vendor_version"] != CLAUDE_CODE_VERSION:
        raise ValueError("unsupported Claude version")
    egress = value["egress"]
    if type(egress) is not dict or set(egress) != set(_PHASE_HOSTS):
        raise ValueError("invalid trusted egress phases")
    policies = {phase: _policy(egress[phase], phase=phase) for phase in _PHASE_HOSTS}
    model, effort = value["model"], value["effort"]
    if type(model) is not str or type(effort) is not str:
        raise ValueError("invalid trusted Claude selection")
    # The native contract checks the exact model/effort grammar at construction.
    ClaudeNativeVendor(_absolute(value["vendor_tree"]), model, effort,
                       _digest(value["vendor_digest"]))
    return LaneConfiguration(
        configuration_sha256=expected_sha256,
        launch_root=_absolute(value["launch_root"]),
        runtime_digest=_digest(value["runtime_digest"]),
        launch_policy=_absolute(value["launch_policy"]),
        launch_policy_sha256=_sha256(value["launch_policy_sha256"]),
        vendor_tree=_absolute(value["vendor_tree"]),
        vendor_digest=_digest(value["vendor_digest"]),
        model=model, effort=effort, egress=policies,
    )


def _public_facts(
    facts: ClaudeMaintenanceSessionFacts, *, selected_plan: ClaudePlan | None = None,
    configuration: LaneConfiguration | None = None,
) -> dict[str, object]:
    login = facts.login_facts
    mode = facts.mode_observation
    public: dict[str, object] = {
        "phase": facts.phase.value,
        "lifecycle": facts.lifecycle.value,
        "login": None if login is None else {
            "lifecycle": login.lifecycle.value,
            "input_write_attempted": login.input_write_attempted,
            "stdin_closed": login.stdin_closed,
            "stdout_eof": login.stdout_eof,
            "stdout_bytes": login.stdout_bytes,
        },
        "mode": None if mode is None else {
            "phase": mode.phase.value,
            "mode_verdict": None if mode.mode_verdict is None else mode.mode_verdict.value,
            "lifecycle": mode.lifecycle.value,
            "request_writes": mode.request_writes,
            "ui_records": mode.ui_records,
            "stdin_closed": mode.stdin_closed,
            "eof": mode.eof,
        },
        "relay_closed": facts.relay_closed,
        "custody_current": facts.custody_current,
        "credential_closed": facts.credential_closed,
        "process_clean": facts.process_clean,
    }
    if facts.phase is ClaudeMaintenanceSessionPhase.QUALIFY:
        if type(selected_plan) is not ClaudePlan or configuration is None:
            raise ValueError("qualification evidence requires sealed selection")
        qualification = facts.qualification
        public["qualification"] = {
            "lifecycle": None if qualification is None else qualification.lifecycle.value,
            "initialize_verdict": (None if qualification is None
                                   or qualification.initialize_verdict is None
                                   else qualification.initialize_verdict.value),
            "settings_verdict": (None if qualification is None
                                 or qualification.settings_verdict is None
                                 else qualification.settings_verdict.value),
            "hooks_verdict": (None if qualification is None
                              or qualification.hooks_verdict is None
                              else qualification.hooks_verdict.value),
            "request_writes": None if qualification is None else qualification.request_writes,
            "ui_records": None if qualification is None else qualification.ui_records,
            "stdin_closed": None if qualification is None else qualification.stdin_closed,
            "eof": None if qualification is None else qualification.eof,
            "selected_plan": "pro" if selected_plan is ClaudePlan.PRO else "max",
            "model": configuration.model,
            "effort": configuration.effort,
        }
    return public


def _record(
    facts: ClaudeMaintenanceSessionFacts, launcher: LinuxLauncher,
    policy: EgressPolicy, configuration: LaneConfiguration,
    *, selected_plan: ClaudePlan | None = None,
) -> dict[str, object]:
    if type(facts) is not ClaudeMaintenanceSessionFacts:
        raise ValueError("invalid Claude maintenance session facts")
    record: dict[str, object] = {
        "schema_version": EVIDENCE_SCHEMA,
        "subscription_qualified": False,
        "production_available": False,
        "facts": _public_facts(facts, selected_plan=selected_plan,
                               configuration=configuration),
        "runtime_digest": str(configuration.runtime_digest),
        "vendor_digest": str(configuration.vendor_digest),
        "launch_policy_sha256": configuration.launch_policy_sha256,
        "launch_config_sha256": configuration.configuration_sha256,
        "launch_revision": str(launcher.revision),
        "egress": {name: str(value) for name, value in identity_digests(policy).items()},
    }
    if facts.phase is ClaudeMaintenanceSessionPhase.QUALIFY:
        record["qualification_revision"] = str(qualification_revision())
    return record


async def _run(
    *, phase: ClaudeMaintenanceSessionPhase, selected_plan: ClaudePlan | None,
    first_login: bool, configuration: LaneConfiguration, store_root: Path,
    key: str, lock_fd: int, floor: int, lane_dir: Path,
) -> tuple[ClaudeMaintenanceSessionFacts, LinuxLauncher, EgressPolicy]:
    seconds = LOGIN_SECONDS if phase is ClaudeMaintenanceSessionPhase.LOGIN else MODE_SECONDS
    deadline = asyncio.get_running_loop().time() + seconds
    operator = (ClaudeOperatorFDIO(input_fd=0, output_fd=1, error_fd=2,
                                   deadline=deadline)
                if phase is ClaudeMaintenanceSessionPhase.LOGIN else None)
    launcher = configuration.launcher(phase)
    policy = configuration.egress["observe" if phase is ClaudeMaintenanceSessionPhase.QUALIFY
                                  else phase.value]
    with inherit_maintenance(store_root, key, lock_fd,
                             generation_floor=floor, parent=os.getppid()) as custody:
        facts = await run_maintenance_session(
            custody, launcher, policy, lane_dir, phase=phase,
            selected_plan=selected_plan, operator=operator, first_login=first_login,
            deadline=deadline,
        )
    return facts, launcher, policy


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(prog="claude_lane", allow_abbrev=False)
    parser.add_argument("phase", choices=("login", "observe", "reload", "qualify"))
    parser.add_argument("--launch-config", type=Path, required=True)
    parser.add_argument("--launch-config-sha256", required=True)
    parser.add_argument("--lane-dir", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--selected-plan", choices=("pro", "max"))
    parser.add_argument("--first-login", action="store_true")
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--custody", choices=("maintenance",), required=True)
    parser.add_argument("--lock-fd", type=int, required=True)
    parser.add_argument("--floor", type=int, required=True)
    options = parser.parse_args(argv)
    phase = ClaudeMaintenanceSessionPhase(options.phase)
    selected_plan = {"pro": ClaudePlan.PRO, "max": ClaudePlan.MAX}.get(options.selected_plan)
    if ((phase is ClaudeMaintenanceSessionPhase.LOGIN) != (selected_plan is None)
            or (options.first_login and phase is not ClaudeMaintenanceSessionPhase.LOGIN)
            or options.lock_fd < 0 or options.floor < 0 or not options.key
            or any(not path.is_absolute() or ".." in path.parts for path in (
                options.store_root, options.lane_dir, options.evidence,
            ))):
        parser.error("invalid Claude maintenance entry")
    try:
        configuration = read_configuration(
            options.launch_config, expected_sha256=options.launch_config_sha256,
        )
        reservation = EvidenceFile(options.evidence, domain=EVIDENCE_DOMAIN)
        try:
            facts, launcher, policy = asyncio.run(_run(
                phase=phase, selected_plan=selected_plan, first_login=options.first_login,
                configuration=configuration, store_root=options.store_root,
                key=options.key, lock_fd=options.lock_fd, floor=options.floor,
                lane_dir=options.lane_dir,
            ))
            evidence = _record(facts, launcher, policy, configuration,
                               selected_plan=selected_plan)
            reservation.publish(evidence)
        except BaseException:
            reservation.abandon()
            raise
    except BaseException:
        print("Claude maintenance entry refused", file=sys.stderr)
        return 1
    return 0 if facts.lifecycle is ClaudeMaintenanceSessionLifecycle.JOINED_CLEAN else 1


if __name__ == "__main__":
    raise SystemExit(main())
