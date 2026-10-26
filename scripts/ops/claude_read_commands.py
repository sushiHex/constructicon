"""Fixed Claude READ operator commands and their receipt contracts.

This is operator tooling, not the installed executor. Trusted private bindings
name the installed controller independently of this tool's content revision.
There is no scheduler, arbitrary shell command, fixture flag or authority mint.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from scripts import m8_procedure_package as packager

from constructicon.core import identity as _identity

ROOT = Path(__file__).resolve().parents[2]
SHA = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
BASE = ("EXPECTED_BOOT", "R", "RUN", "AUTH", "ACQ", "QUAL", "ACTOR", "READ_KEY", "AUTHORIZATION_ID")
LATE = (
    "FLOOR",
    "GENERATION",
    "Q",
    "QUAL_RAW_SHA256",
    "SEALED_SHA256",
    "CANDIDATE_SHA256",
    "OWNER_APPROVAL_SHA256",
)
PATHS = {"R", "RUN", "AUTH", "ACQ", "QUAL"}
DOC_SHA = "836e37b61f381e3465d04d6938c5a7dbe8001e56003754d9fcd07067635f6954"
DOCUMENTS = {
    "read": ("M8-N6-first-read-session.md", DOC_SHA),
    "lr": (
        "M8-N4-launch-replacement.md",
        "16cb614cdf76b1d1f9fc983b3eeb8decc9bf00b28e8cf92dd246489e477aada4",
    ),
    "q12": (
        "M8-maintenance-q12-continuation.md",
        "1fbd0a983fc9537f47198221b5a84937da6b3e79fe0c15fb77b3e9b2ba4d76b1",
    ),
    "q13": (
        "M8-maintenance-q13-continuation.md",
        "d89888f69eaab22bb5860cde31190b44e0a6a3a9ddbf4c875a73a9413d93b9d9",
    ),
    "guard": (
        "M8-private-output-guard.md",
        "648d5eb2eabc250874a548e5ef036f20657ed61d6149fd96075b60aff41139b7",
    ),
}
TASK = (
    "Use the read_file tool exactly once to read ready.txt. "
    "Reply with the single word found in that file, and nothing else."
)
ACCEPTANCE = {
    "task": TASK,
    "one_attempt": True,
    "max_epoch": 1,
    "read_deadline_s": 120,
    "drive_wait_s": 180,
    "stdin_bytes": 8192,
    "stdout_bytes": 524288,
    "record_bytes": 262144,
    "worker_output_bytes": 65536,
    "fixture_archive_bytes": 32768,
    "observe_connections": 16,
    "tokens_observational": True,
    "backend_request_count_unknown": True,
    "no_enforced_money_cap": True,
    "subscription_overage_and_cost_exposure_accepted": True,
    "cleanup_can_exceed_wait": True,
    "no_retry": True,
}
PIN_KEYS = {
    "launch_commit",
    "configuration_sha256",
    "controller_helper_sha256",
    "launch_helper_sha256",
    "checker_path",
    "checker_sha256",
    "checker_size",
    "drift_sha256",
    "drift_stdout",
    "d2_commit",
    "d2_workspace",
}
RESERVED = {
    "__controller_commit",
    "__namespace",
    "__controller_workspace",
    "__launch_workspace",
    "__selected_plan",
    "__drift_hex",
    *("__" + key for key in PIN_KEYS),
} - {"__drift_stdout"}


class Refused(ValueError):
    """Finite operator refusal, never containing a private value."""


@dataclass(frozen=True)
class Phase:
    stdout: bytes
    checks: frozenset[str]
    outputs: Mapping[str, tuple[str, str, int]]


def _phase(stdout=b"drift-checked\n", checks=(), outputs=None):
    return Phase(stdout, frozenset(checks), MappingProxyType(outputs or {}))


COMMON_CHECKS = frozenset({"exclusive_custody", "exact_drift_expectation", "source_review"})
PHASES = MappingProxyType(
    {
        "d2-preserve": _phase(b"g11-boot-d2-records-preserved\n"),
        "d2-verify": _phase(
            b"d2-record-checked\ndrift-checked\n",
            ("prior_d2_records_preserved",),
            {"record": ("PHASE_DIRECTORY", "d2-records/lr2.out", 65536)},
        ),
        "controller-verify": _phase(
            b"drift-checked\ncontroller-verify-recorded\n",
            outputs={"verification": ("CONTROLLER_W", "{namespace}-controller-verify.json", 65536)},
        ),
        "launch-verify": _phase(
            b"drift-checked\nmaintenance-launch-verify-recorded\n",
            ("controller_verified",),
            {"verification": ("CLAUDE_W", "{namespace}-launch-verify.json", 8192)},
        ),
        "checker-verify": _phase(checks=("controller_verified", "launch_verified")),
        "parents": _phase(
            checks=("controller_verified", "launch_verified", "parent_paths_approved")
        ),
        "reload": _phase(
            checks=(
                "controller_verified",
                "launch_verified",
                "parents_checked",
                "store_withdrawn",
                "installed_checker_verified",
            ),
            outputs={
                "stdout": ("R", "reload.stdout", 4096),
                "stderr": ("R", "reload.stderr", 4096),
                "evidence": ("RUN", "reload.json", 4096),
            },
        ),
        "reload-check": _phase(
            checks=("reload_completed_zero", "installed_checker_custody"),
            outputs={
                "digest": ("R", "reload.digest", 72),
                "stderr": ("R", "reload-checker.stderr", 4096),
            },
        ),
        "qualify": _phase(
            checks=(
                "controller_verified",
                "launch_verified",
                "parents_checked",
                "store_withdrawn",
                "reload_checked",
            ),
            outputs={
                "stdout": ("R", "qualify.stdout", 4096),
                "stderr": ("R", "qualify.stderr", 4096),
                "evidence": ("QUAL", "", 4096),
            },
        ),
        "qualify-check": _phase(
            checks=("qualify_completed_zero", "installed_checker_custody"),
            outputs={
                "digest": ("R", "qualification.digest", 72),
                "stderr": ("R", "checker.stderr", 4096),
            },
        ),
        "inventory": _phase(
            checks=("qualification_checked",),
            outputs={
                "inventory": ("R", "inventory.json", 256),
                "stderr": ("R", "inventory.stderr", 4096),
            },
        ),
        "withdraw-before": _phase(
            checks=("qualification_checked", "positive_descriptor_inventory"),
            outputs={
                "stdout": ("R", "withdraw-before.stdout", 64),
                "stderr": ("R", "withdraw-before.stderr", 4096),
            },
        ),
        "publish": _phase(
            checks=("qualification_checked", "positive_descriptor_inventory", "withdrawal_checked"),
            outputs={
                "sealed": ("R", "published-sealed.json", 8192),
                "stderr": ("R", "publish.stderr", 4096),
            },
        ),
        "sealed-install": _phase(
            checks=("published_identity_checked", "protected_destination_absent")
        ),
        "activate": _phase(
            checks=("sealed_installed_exact", "published_identity_checked", "cleanup_prepared"),
            outputs={
                "stdout": ("R", "activate.stdout", 64),
                "stderr": ("R", "activate.stderr", 4096),
            },
        ),
        "fixture": _phase(
            checks=("activation_checked",),
            outputs={
                "fixture": ("R", "fixture.json", 8192),
                "stderr": ("R", "fixture.stderr", 4096),
            },
        ),
        "mint": _phase(
            checks=("activation_checked", "fixture_checked"),
            outputs={
                "candidate": ("R", "authorization-candidate.json", 8192),
                "stderr": ("R", "mint.stderr", 4096),
            },
        ),
        "candidate-pins": _phase(
            checks=("activation_checked", "fixture_checked", "mint_completed_zero"),
            outputs={
                "pins": ("R", "candidate-pins.json", 8192),
                "stderr": ("R", "candidate-pins.stderr", 4096),
            },
        ),
        "authority-install": _phase(
            checks=(
                "mint_candidate_checked",
                "owner_exact_scope_budget_accepted",
                "actual_grants_task_model_effort_window_checked",
                "active_binding_checked",
                "protected_destination_absent",
                "cleanup_prepared",
            )
        ),
        "read": _phase(
            checks=(
                "authority_installed_exact",
                "owner_exact_scope_budget_accepted",
                "actual_grants_task_model_effort_window_checked",
                "active_binding_checked",
                "controller_verified",
                "launch_verified",
                "qualification_checked",
                "cleanup_prepared",
            ),
            outputs={
                "result": ("R", "read-status.json", 4096),
                "stderr": ("R", "read.stderr", 4096),
            },
        ),
        "withdraw-after": _phase(
            checks=("activation_may_have_completed",),
            outputs={
                "stdout": ("R", "withdraw-after.stdout", 64),
                "stderr": ("R", "withdraw-after.stderr", 4096),
            },
        ),
    }
)


def _absolute(value):
    return (
        type(value) is str
        and re.fullmatch(r"/[A-Za-z0-9_./-]{1,200}", value) is not None
        and str(PurePosixPath(value)) == value
        and ".." not in PurePosixPath(value).parts
    )


@dataclass(frozen=True)
class Bindings:
    """Trusted operator data; source/phase grants pin its exact serialized bytes."""

    controller_commit: str
    namespace: str
    controller_workspace: str
    launch_workspace: str
    selected_plan: str
    values: Mapping[str, str]
    pins: Mapping[str, str | int]

    @classmethod
    def from_dict(cls, record):
        require(
            type(record) is dict
            and set(record)
            == {
                "schema_version",
                "controller_commit",
                "namespace",
                "controller_workspace",
                "launch_workspace",
                "selected_plan",
                "values",
                "pins",
            }
        )
        require(type(record["schema_version"]) is int and record["schema_version"] == 1)
        require(
            type(record["controller_commit"]) is str
            and COMMIT.fullmatch(record["controller_commit"])
        )
        require(
            type(record["namespace"]) is str
            and re.fullmatch(r"[a-z][a-z0-9-]{0,63}", record["namespace"])
        )
        require(all(_absolute(record[key]) for key in ("controller_workspace", "launch_workspace")))
        require(record["selected_plan"] in ("pro", "max"))
        values, pins = record["values"], record["pins"]
        require(
            type(values) is dict
            and set(values) == {*BASE, *LATE}
            and all(type(v) is str and 0 < len(v) <= 512 for v in values.values())
        )
        require(type(pins) is dict and set(pins) == PIN_KEYS)
        require(
            all(
                type(pins[key]) is str and SHA.fullmatch(pins[key])
                for key in PIN_KEYS
                if key.endswith("sha256")
            )
        )
        require(
            all(
                type(pins[key]) is str and COMMIT.fullmatch(pins[key])
                for key in ("launch_commit", "d2_commit")
            )
        )
        require(_absolute(pins["checker_path"]) and _absolute(pins["d2_workspace"]))
        require(type(pins["checker_size"]) is int and 0 < pins["checker_size"] <= 65536)
        line = pins["drift_stdout"]
        require(
            type(line) is str
            and 1 < len(line) <= 128
            and line.endswith("\n")
            and line[:-1].isprintable()
        )
        return cls(
            record["controller_commit"],
            record["namespace"],
            record["controller_workspace"],
            record["launch_workspace"],
            record["selected_plan"],
            MappingProxyType(dict(values)),
            MappingProxyType(dict(pins)),
        )

    @classmethod
    def from_file(cls, path):
        return cls.from_dict(parsed(bounded(path, 16384)))

    def expanded(self):
        values = dict(self.values)
        values.update(
            {
                "__controller_commit": self.controller_commit,
                "__namespace": self.namespace,
                "__controller_workspace": self.controller_workspace,
                "__launch_workspace": self.launch_workspace,
                "__selected_plan": self.selected_plan,
            }
        )
        values.update(
            {"__" + key: str(value) for key, value in self.pins.items() if key != "drift_stdout"}
        )
        values["__drift_hex"] = self.pins["drift_stdout"].encode("utf-8").hex()
        return values


def _document(key):
    name, expected = DOCUMENTS[key]
    raw = (ROOT / "docs/plans/handoffs" / name).read_bytes()
    require(b"\r" not in raw and sha(raw) == expected)
    return raw.decode("utf-8")


def _fence(key, heading, index=0):
    language, body = packager.fences(packager.section(_document(key), heading))[index]
    require(language == "bash")
    return body


def _sources():
    headings = (
        "Package and current-boot prerequisites",
        "Fresh qualification and exact digest",
        "Affirm withdrawal, publish and activate one generation",
        "Fixed fixture, candidate authorization and owner call decision",
        "One run, terminal checks and no retry",
    )
    blocks = [
        [
            body
            for language, body in packager.fences(packager.section(_document("read"), heading))
            if language == "bash"
        ]
        for heading in headings
    ]
    require(tuple(map(len, blocks)) == (1, 1, 3, 2, 2))
    return packager, {}, blocks


def operator_revision():
    """Measured tooling content; callers must independently select this revision."""
    paths = [
        Path(__file__),
        Path(__file__).with_name("claude_read_session.py"),
        ROOT / "scripts/m8_procedure_package.py",
        ROOT / "scripts/check_claude_phase.py",
    ]
    paths += [ROOT / "docs/plans/handoffs" / name for name, _ in DOCUMENTS.values()]
    return sha(
        b"".join(
            path.relative_to(ROOT).as_posix().encode() + b"\0" + path.read_bytes() + b"\0"
            for path in paths
        )
    )


def _d2_script(values, phase):
    boot = (
        "EXPECTED_BOOT=UNREVIEWED\n"
        '[[ "$EXPECTED_BOOT" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}'
        "-[0-9a-f]{4}-[0-9a-f]{12}$ ]] || exit 1\n"
        'test "$(/usr/bin/cat /proc/sys/kernel/random/boot_id)" = "$EXPECTED_BOOT" || exit 1\n'
    )
    anchor = (
        'readonly D2_PHASE_ROOT="$PWD"\n'
        'test "${D2_PHASE_ROOT:0:1}" = / && test -d "$D2_PHASE_ROOT" || exit 1\n'
        'test "$D2_PHASE_ROOT" = "$(/usr/bin/pwd -P)" || exit 1\n'
    )
    if phase == "d2-preserve":
        body = _fence("q13", "Q5: new and renamed VM fences")
        require(body.count('"$HOME/maintenance-q13-d2-prior"') == 1)
        body = body.replace('"$HOME/maintenance-q13-d2-prior"', '"$D2_PHASE_ROOT/d2-prior"')
        body = body.replace('"$HOME/m8-host"', shlex.quote(values["__d2_workspace"]))
    else:
        lr = _fence("lr", "LR2. Host qualification on this boot")
        lr = lr.replace(
            "D=<40-hex commit the qualification set was installed at>", "D=" + values["__d2_commit"]
        )
        lr = lr.replace('V="$HOME/m8-host"', "V=" + shlex.quote(values["__d2_workspace"]))
        body = (
            'RECORDS="$D2_PHASE_ROOT/d2-records"\n'
            + _fence("q12", "Q4: private host records")
            + "{\n"
            + lr
            + '} > "$RECORDS/lr2.out"\nrecord_check d2 "$RECORDS/lr2.out" "$D"\n'
            + _fence("q13", "Q7: private drift declarations")
            + 'DRIFT_RECORDS="$D2_PHASE_ROOT/drift-d2"\n'
            + _fence("q13", "Q7: private drift declarations", 1)
            + 'DRIFT_CAPTURE="$DRIFT_RECORDS/after-record"\n'
            + _fence("guard", "G1: private drift boundary")
        )
        body = body.replace(
            "DRIFT_STDOUT_HEX=UNREVIEWED\n",
            "readonly DRIFT_STDOUT_HEX=" + values["__drift_hex"] + "\n",
        )
        body = body.replace(
            "DRIFT_TOOL_SHA256=UNREVIEWED\n",
            "readonly DRIFT_TOOL_SHA256=" + values["__drift_sha256"] + "\n",
        )
    result = (
        "#!/bin/bash\n"
        + boot.replace(
            "EXPECTED_BOOT=UNREVIEWED", "readonly EXPECTED_BOOT=" + values["EXPECTED_BOOT"]
        )
        + anchor
        + body
    )
    require("UNREVIEWED" not in result and "\r" not in result)
    return result.encode("utf-8")


_EXPECTED_CODE = r'''
"""Independent metadata-only READ assembly pins; never mint or execute a task."""

import argparse
import json
import sys

sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.api import claude_qualification as api
from constructicon.core.manifest import source_graph_hash_for
from constructicon.core.envelope import utc_now


def expected(options):
    provider = api.assemble(options)
    opened = provider.binding_store.open_candidate()
    provider.binding_store.close_candidate(opened)
    grants = api.fixed_grants(provider)
    return {
        "schema": 1,
        "stage": "qualification-read",
        "scope": api.SCOPE.model_dump(mode="json"),
        "binding": api.EXECUTOR,
        "capability_id": api.CAPABILITY,
        "source_graph_hash": str(source_graph_hash_for(api.graph(grants))),
        "revision": provider.identity.revision,
        "operator_binding_digest": str(provider.identity.store.operator_binding_digest),
        "grants": grants.model_dump(mode="json"),
        "workspace_revision": provider.workspace_revision,
        "expected_base": str(provider.expected_base),
        "fixture_identity": str(api.fixture.inspect_fixture(options.fixture)),
        "qualification_digest": str(provider.identity.store.store_conformance_revision),
        "subscription_mode_revision": str(
            provider.identity.store.subscription_mode_adapter_revision
        ),
        "active_binding_checked": True,
        "checked_at": utc_now().isoformat(),
    }


def main():
    from pathlib import Path

    parser = argparse.ArgumentParser(allow_abbrev=False)
    for name in (
        "fixture",
        "launch-config",
        "store-root",
        "sealed",
        "qualification",
        "acquisition-root",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--launch-config-sha256", required=True)
    parser.add_argument("--store-key", required=True)
    print(json.dumps(expected(parser.parse_args()), sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
'''

_READ_CODE = r"""
import os, pathlib, pwd, stat, sys

p = pathlib.Path(sys.argv[1])
u = pwd.getpwnam("m8-service").pw_uid if sys.argv[2] == "service" else os.geteuid()
limit = int(sys.argv[3])
assert os.geteuid() == u and u > 0 and (p.resolve(strict=True) == p)
i = p.lstat()
assert (
    stat.S_ISREG(i.st_mode)
    and i.st_uid == u
    and (stat.S_IMODE(i.st_mode) == 384)
    and (i.st_nlink == 1)
    and (0 <= i.st_size <= limit)
)
assert all(
    (
        stat.S_ISDIR(t.st_mode)
        and t.st_uid in (0, u)
        and (not t.st_mode & 18)
        and (q.resolve(strict=True) == q)
        for q in p.parents
        for t in (q.lstat(),)
    )
)
fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
with os.fdopen(fd, "rb") as f:
    opened = os.fstat(f.fileno())
    assert (opened.st_dev, opened.st_ino) == (i.st_dev, i.st_ino)
    raw = f.read(limit + 1)
after = p.lstat()
assert len(raw) == i.st_size and all(
    (
        getattr(after, k) == getattr(i, k)
        for k in (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_nlink",
            "st_uid",
            "st_gid",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
    )
)
sys.stdout.buffer.write(raw)
"""


def require(ok):
    if not ok:
        raise Refused("first-read preparation refused")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def bounded(path, limit=65536, empty=False):
    info = path.lstat()
    require(
        stat.S_ISREG(info.st_mode)
        and info.st_nlink == 1
        and ((0 if empty else 1) <= info.st_size <= limit)
    )
    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)), "rb") as stream:
        current = os.fstat(stream.fileno())
        require(
            (current.st_dev, current.st_ino, current.st_size)
            == (info.st_dev, info.st_ino, info.st_size)
        )
        raw = stream.read(limit + 1)
    require(len(raw) == info.st_size)
    return raw


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def parsed(raw):
    return json.loads(
        raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=lambda _: require(False)
    )


def values_checked(values, phase):
    require(
        phase in PHASES
        and type(values) is dict
        and (
            set(values)
            == {
                *RESERVED,
                *BASE,
                "FLOOR",
                "GENERATION",
                "Q",
                "QUAL_RAW_SHA256",
                "SEALED_SHA256",
                "CANDIDATE_SHA256",
                "OWNER_APPROVAL_SHA256",
            }
        )
    )
    require(all(type(v) is str and 0 < len(v) <= 512 for v in values.values()))
    required = set(BASE)
    if phase in (
        "withdraw-before",
        "publish",
        "sealed-install",
        "activate",
        "mint",
        "authority-install",
        "read",
        "withdraw-after",
    ):
        required |= {"FLOOR", "GENERATION"}
    if phase in (
        "publish",
        "sealed-install",
        "activate",
        "mint",
        "candidate-pins",
        "authority-install",
        "read",
    ):
        required |= {"Q", "QUAL_RAW_SHA256"}
    if phase in (
        "sealed-install",
        "activate",
        "mint",
        "candidate-pins",
        "authority-install",
        "read",
    ):
        required.add("SEALED_SHA256")
    if phase in ("authority-install", "read"):
        required |= {"CANDIDATE_SHA256", "OWNER_APPROVAL_SHA256"}
    require(all(type(values[key]) is str and values[key] != "UNREVIEWED" for key in required))
    require(
        re.fullmatch("[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", values["EXPECTED_BOOT"])
        is not None
    )
    for key in PATHS:
        path = values[key]
        require(
            re.fullmatch("/[A-Za-z0-9_./-]{1,180}", path) is not None
            and str(PurePosixPath(path)) == path
            and (".." not in PurePosixPath(path).parts)
        )
    roots = [PurePosixPath(values[key]) for key in ("R", "RUN", "AUTH", "ACQ")]
    require(
        all(
            (
                a != b and a not in b.parents and (b not in a.parents)
                for i, a in enumerate(roots)
                for b in roots[i + 1 :]
            )
        )
    )
    require(values["QUAL"] == values["RUN"] + "/qualify.json")
    require(re.fullmatch("/home/[A-Za-z0-9_-]+/m8-claude-first-read-[A-Za-z0-9_-]+", values["R"]))
    require(
        all(
            re.fullmatch("/var/lib/m8-cr-[A-Za-z0-9_-]+", values[k]) for k in ("RUN", "AUTH", "ACQ")
        )
    )
    require(len((values["ACQ"] + "/payloads/acq-" + "0" * 32 + "/egress.sock").encode()) <= 107)
    for key in ("ACTOR", "READ_KEY", "AUTHORIZATION_ID"):
        require(re.fullmatch("[A-Za-z0-9][A-Za-z0-9:_.-]{0,127}", values[key]) is not None)
    require(":" in values["ACTOR"])
    if "FLOOR" in required:
        require(all(re.fullmatch("[1-9][0-9]{0,8}", values[k]) for k in ("FLOOR", "GENERATION")))
        require(int(values["GENERATION"]) == int(values["FLOOR"]) + 1)
    if "Q" in required:
        require(re.fullmatch("sha256:[0-9a-f]{64}", values["Q"]) is not None)
    for key in required & {
        "QUAL_RAW_SHA256",
        "SEALED_SHA256",
        "CANDIDATE_SHA256",
        "OWNER_APPROVAL_SHA256",
    }:
        require(SHA.fullmatch(values[key]) is not None)
    return required


def snapshot(root, name, expected, limit=65536):
    raw = bounded(root / name, limit)
    require(sha(raw) == expected)
    return raw


def completed_zero(value):
    return (
        type(value) is dict
        and set(value) == {"completed", "returncode", "timed_out"}
        and (value["completed"] is True)
        and (type(value["returncode"]) is int)
        and (value["returncode"] == 0)
        and (value["timed_out"] is False)
    )


def d2_receipt_gate(evidence, values, phase):
    require(completed_zero(parsed(bounded(evidence / (phase + ".status.json"), 256))))
    require(bounded(evidence / (phase + ".stderr"), 4096, empty=True) == b"")
    expected = (
        b"g11-boot-d2-records-preserved\n"
        if phase == "d2-preserve"
        else b"d2-record-checked\ndrift-checked\n"
    )
    require(bounded(evidence / (phase + ".stdout"), 128) == expected)
    context = parsed(bounded(evidence / (phase + "-context.json"), 2048))
    require(
        set(context)
        == {
            "phase",
            "package_manifest",
            "operator_revision",
            "bindings_sha256",
            "script_sha256",
            "boot",
            "controller_commit",
        }
        and context["controller_commit"] == values["__controller_commit"]
        and context["operator_revision"] == operator_revision()
        and context["phase"] == phase
        and (context["boot"] == values["EXPECTED_BOOT"])
        and all(
            type(context[k]) is str and SHA.fullmatch(context[k])
            for k in (
                "package_manifest",
                "operator_revision",
                "bindings_sha256",
                "script_sha256",
            )
        )
    )
    _sources()
    require(context["script_sha256"] == sha(_d2_script(values, phase)))


def d2_gate(evidence, values):
    d2_receipt_gate(evidence, values, "d2-preserve")
    d2_receipt_gate(evidence, values, "d2-verify")
    raw = bounded(evidence / "d2-lr2.out", 65536)
    require(b"\r" not in raw)
    text, at = (raw.decode("utf-8"), 0)

    def line(expected):
        nonlocal at
        end = text.index("\n", at)
        require(text[at:end] == expected)
        at = end + 1

    def record():
        nonlocal at
        value, end = json.JSONDecoder(object_pairs_hook=unique).raw_decode(text, at)
        require(type(value) is dict and text[end : end + 1] == "\n")
        at = end + 1
        return value

    line(values["EXPECTED_BOOT"])
    line("verify exit 0")
    verify = record()
    require(
        verify.get("command") == "verify"
        and verify.get("commit") == values["__d2_commit"]
        and (verify.get("first_parent") is True)
        and (verify.get("script_matches_commit") is True)
        and (verify.get("installed") is True)
    )
    line("probe exit 0")
    probe = record()
    require(
        probe.get("qualified") is True
        and probe.get("commit") == values["__d2_commit"]
        and (probe.get("scope") == "runner_prerequisites_only")
        and (probe.get("production_available") is False)
        and (at == len(text))
    )


def qualification_gate(evidence, values, pins):
    from constructicon.substrate.executors import claude_lane

    phase_receipt(evidence, values, "qualify")
    phase_receipt(evidence, values, "qualify-check")
    readback_receipt(evidence, values, "qualify", "evidence", "qualification.json")
    readback_receipt(evidence, values, "qualify-check", "digest", "checker.stdout")
    quiet_command(evidence, values, "qualify", stdout=True)
    quiet_command(evidence, values, "qualify-check")
    raw = snapshot(evidence, "qualification.json", values["QUAL_RAW_SHA256"], 4096)
    record = parsed(raw)
    identity = _identity
    require(
        str(
            identity.digest(
                "claude-maintenance-entry-evidence",
                1,
                identity.parse_json_value(raw.decode("utf-8")),
            )
        )
        == values["Q"]
    )
    require(bounded(evidence / "checker.stdout", 72) == (values["Q"] + "\n").encode())
    for name in ("qualify", "qualify-check"):
        require(completed_zero(parsed(bounded(evidence / (name + ".status.json"), 256))))
        require(bounded(evidence / (name + ".stderr"), 4096, empty=True) == b"")
    facts, q = (record["facts"], record["facts"]["qualification"])
    require(
        type(record["schema_version"]) is int
        and record["schema_version"] == 7
        and (record["completed"] is True)
        and (record["qualification_revision"] == str(claude_lane.qualification_revision()))
        and (record["subscription_qualified"] is False)
        and (record["production_available"] is False)
    )
    require(
        facts["phase"] == "qualify"
        and facts["lifecycle"] == "joined-clean"
        and all(
            facts[k] is True
            for k in ("process_clean", "relay_closed", "credential_closed", "custody_current")
        )
    )
    require(
        q["selected_plan"] == values["__selected_plan"]
        and q["lifecycle"] == "qualified"
        and (q["initialize_verdict"] == "mode-match")
        and (q["settings_verdict"] == "match")
        and (q["settings_mismatch_reason"] is None)
        and (q["hooks_verdict"] == "match")
        and (type(q["request_writes"]) is int)
        and (q["request_writes"] == 3)
        and (q["stdin_closed"] is True)
        and (q["eof"] is True)
    )


def authority_gate(evidence, values):
    from datetime import datetime, timedelta

    from constructicon.core.native_operator import NativeOperatorStoreIdentityV1
    from constructicon.core.qualification import QualificationAuthorization

    phase_receipt(evidence, values, "mint")
    phase_receipt(evidence, values, "candidate-pins")
    quiet_command(evidence, values, "mint")
    quiet_command(evidence, values, "candidate-pins")
    readback_receipt(evidence, values, "mint", "candidate", "authorization-candidate.json")
    readback_receipt(evidence, values, "candidate-pins", "pins", "candidate-pins.json")
    raw = snapshot(evidence, "authorization-candidate.json", values["CANDIDATE_SHA256"], 8192)
    typed = QualificationAuthorization.model_validate(parsed(raw))
    candidate = parsed(raw)
    require(
        json.dumps(candidate, sort_keys=True, separators=(",", ":"))
        == json.dumps(typed.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    )
    expected = parsed(bounded(evidence / "candidate-pins.json", 8192))
    require(
        set(expected)
        == {
            "schema",
            "stage",
            "scope",
            "binding",
            "capability_id",
            "source_graph_hash",
            "revision",
            "operator_binding_digest",
            "grants",
            "workspace_revision",
            "expected_base",
            "fixture_identity",
            "qualification_digest",
            "subscription_mode_revision",
            "checked_at",
            "active_binding_checked",
        }
        and type(expected["schema"]) is int
        and (expected["schema"] == 1)
        and (expected["active_binding_checked"] is True)
    )
    require(
        all(
            candidate[key] == expected[key]
            for key in (
                "stage",
                "scope",
                "binding",
                "capability_id",
                "source_graph_hash",
                "revision",
                "operator_binding_digest",
                "grants",
            )
        )
    )
    require(
        expected["qualification_digest"] == expected["subscription_mode_revision"] == values["Q"]
    )
    seal = NativeOperatorStoreIdentityV1.model_validate(
        parsed(snapshot(evidence, "published-sealed.json", values["SEALED_SHA256"], 8192))
    )
    require(
        str(seal.operator_binding_digest) == expected["operator_binding_digest"]
        and str(seal.store_conformance_revision)
        == str(seal.subscription_mode_adapter_revision)
        == values["Q"]
    )
    readback_receipt(evidence, values, "fixture", "fixture", "fixture.json")
    phase_receipt(evidence, values, "fixture")
    quiet_command(evidence, values, "fixture")
    fixture = parsed(bounded(evidence / "fixture.json", 8192))
    require(fixture["fixture_revision"] == expected["fixture_identity"])
    checked = datetime.fromisoformat(expected["checked_at"])
    require(
        checked.tzinfo is not None
        and checked <= datetime.now(UTC) < typed.not_after <= checked + timedelta(hours=1)
    )
    require(
        candidate["stage"] == "qualification-read"
        and candidate["actor_id"] == values["ACTOR"]
        and (candidate["idempotency_key"] == values["READ_KEY"])
        and (candidate["authorization_id"] == values["AUTHORIZATION_ID"])
        and (type(candidate["max_epoch"]) is int)
        and (candidate["max_epoch"] == 1)
        and (candidate["binding"] == "executor")
        and (candidate["capability_id"] == "claude-operator")
        and (
            candidate["scope"] == {"segments": ["constructicon-claude-qualification-read", "read"]}
        )
        and (candidate["journal"] == values["RUN"] + "/read.sqlite")
        and (candidate["attempt_record"] == values["RUN"] + "/read-attempt.json")
    )
    approval = parsed(
        snapshot(evidence, "owner-approval.json", values["OWNER_APPROVAL_SHA256"], 8192)
    )
    require(
        set(approval) == {"schema", "owner_decision", "procedure_sha256", "source_c", "acceptance"}
    )
    require(
        type(approval["schema"]) is int
        and approval["schema"] == 1
        and (approval["procedure_sha256"] == DOC_SHA)
        and (approval["source_c"] == values["__controller_commit"])
        and (
            json.dumps(approval["acceptance"], sort_keys=True, separators=(",", ":"))
            == json.dumps(ACCEPTANCE, sort_keys=True, separators=(",", ":"))
        )
        and (
            re.fullmatch(
                "https://github.com/sushiHex/constructicon/issues/77#issuecomment-[0-9]+",
                approval["owner_decision"],
            )
            is not None
        )
    )


def phase_receipt(evidence, values, phase):
    require(completed_zero(parsed(bounded(evidence / (phase + ".status.json"), 256))))
    require(bounded(evidence / (phase + ".stderr"), 4096, empty=True) == b"")
    require(bounded(evidence / (phase + ".stdout"), 128) == PHASES[phase].stdout)
    context = parsed(bounded(evidence / (phase + "-context.json"), 2048))
    require(
        set(context)
        == {
            "phase",
            "package_manifest",
            "operator_revision",
            "bindings_sha256",
            "script_sha256",
            "boot",
            "controller_commit",
        }
        and context["controller_commit"] == values["__controller_commit"]
        and context["operator_revision"] == operator_revision()
        and context["phase"] == phase
        and (context["boot"] == values["EXPECTED_BOOT"])
        and all(
            type(context[k]) is str and SHA.fullmatch(context[k])
            for k in (
                "package_manifest",
                "operator_revision",
                "bindings_sha256",
                "script_sha256",
            )
        )
        and (context["script_sha256"] == sha(_scripts(values, phase, evidence)))
    )


def readback_receipt(evidence, values, phase, part, filename):
    name = phase + "-readback-" + part
    require(
        completed_zero(parsed(bounded(evidence / (name + ".status.json"), 256)))
        and bounded(evidence / (name + ".stderr"), 4096, empty=True) == b""
    )
    context = parsed(bounded(evidence / (name + "-context.json"), 2048))
    original = parsed(bounded(evidence / (phase + "-context.json"), 2048))
    require(
        set(context) == {"request", "part", "sha256"}
        and context["request"] == original
        and (original["boot"] == values["EXPECTED_BOOT"])
        and (context["part"] == part)
        and (context["sha256"] == sha(bounded(evidence / filename, 8192, empty=True)))
    )


def quiet_command(evidence, values, phase, stdout=False):
    for part in ("stdout", "stderr") if stdout else ("stderr",):
        filename = phase + ".command." + part
        readback_receipt(evidence, values, phase, part, filename)
        require(bounded(evidence / filename, 4096, empty=True) == b"")


def reload_gate(evidence, values):
    phase_receipt(evidence, values, "reload")
    phase_receipt(evidence, values, "reload-check")
    readback_receipt(evidence, values, "reload", "evidence", "reload.json")
    readback_receipt(evidence, values, "reload-check", "digest", "reload.digest")
    quiet_command(evidence, values, "reload", stdout=True)
    quiet_command(evidence, values, "reload-check")
    identity = _identity
    raw = bounded(evidence / "reload.json", 4096)
    record = parsed(raw)
    require(
        type(record["schema_version"]) is int
        and record["schema_version"] == 7
        and (record["completed"] is True)
        and (record["facts"]["phase"] == "reload")
    )
    require(
        bounded(evidence / "reload.digest", 72)
        == (str(identity.digest("claude-maintenance-entry-evidence", 1, record)) + "\n").encode()
    )


def inventory_gate(evidence, values):
    phase_receipt(evidence, values, "inventory")
    quiet_command(evidence, values, "inventory")
    readback_receipt(evidence, values, "inventory", "inventory", "inventory.json")
    record = parsed(bounded(evidence / "inventory.json", 256))
    require(
        set(record) == {"highest_generation", "withdrawn"}
        and record["withdrawn"] is True
        and (type(record["highest_generation"]) is int)
        and (record["highest_generation"] >= 1)
        and (str(record["highest_generation"]) == values["FLOOR"])
        and (int(values["GENERATION"]) == record["highest_generation"] + 1)
    )


def cleanup_gate(evidence, values):
    package = evidence / "cleanup-package"
    names = ("phase.sh", "bindings.json", "SOURCE-PINS.json")
    raws = {name: bounded(package / name) for name in names}
    require(
        bounded(package / "MANIFEST.sha256", 1024)
        == "".join(f"{sha(raws[n])}  {n}\n" for n in names).encode()
        and {p.name for p in package.iterdir()} == {*names, "MANIFEST.sha256"}
    )
    require(raws["phase.sh"] == _scripts(values, "withdraw-after", evidence))
    pins = parsed(raws["SOURCE-PINS.json"])
    require(
        pins
        == {
            "controller_commit": values["__controller_commit"],
            "operator_revision": operator_revision(),
            "phase": "withdraw-after",
            "bindings_sha256": sha(raws["bindings.json"]),
            "script_sha256": sha(raws["phase.sh"]),
        }
    )


def withdrawal_gate(evidence, values):
    """Affirm the fixed child completed before publication, on this exact boot."""
    inventory_gate(evidence, values)
    phase_receipt(evidence, values, "withdraw-before")
    quiet_command(evidence, values, "withdraw-before")
    readback_receipt(
        evidence, values, "withdraw-before", "stdout", "withdraw-before.command.stdout"
    )
    require(bounded(evidence / "withdraw-before.command.stdout", 64) == b"withdrawn-checked\n")
    context = parsed(bounded(evidence / "withdraw-before-context.json", 2048))
    require(
        set(context)
        == {
            "phase",
            "package_manifest",
            "operator_revision",
            "bindings_sha256",
            "script_sha256",
            "boot",
            "controller_commit",
        }
        and context["controller_commit"] == values["__controller_commit"]
        and context["operator_revision"] == operator_revision()
        and context["phase"] == "withdraw-before"
        and (context["boot"] == values["EXPECTED_BOOT"])
        and all(
            type(context[k]) is str and SHA.fullmatch(context[k])
            for k in (
                "package_manifest",
                "operator_revision",
                "bindings_sha256",
                "script_sha256",
            )
        )
        and (context["script_sha256"] == sha(_scripts(values, "withdraw-before", evidence)))
    )


def terminal_gate(evidence, values):
    phase_receipt(evidence, values, "read")
    quiet_command(evidence, values, "read")
    readback_receipt(evidence, values, "read", "result", "read-status.json")
    require(bounded(evidence / "read-status.json", 64) == b'{"status": "succeeded"}\n')


def cleanup_complete(evidence, values):
    phase_receipt(evidence, values, "withdraw-after")
    quiet_command(evidence, values, "withdraw-after")
    readback_receipt(evidence, values, "withdraw-after", "stdout", "withdraw-after.command.stdout")
    require(bounded(evidence / "withdraw-after.command.stdout", 64) == b"withdrawn-checked\n")


def byte_guard(path, expected, role):
    """Fixed scoped root read: retain the service/root custody modes from source."""
    require(
        role in ("qualification", "seal", "candidate", "authorization") and SHA.fullmatch(expected)
    )
    code = r"""
import hashlib, os, pathlib, pwd, stat, sys

p = pathlib.Path(sys.argv[1])
expected = sys.argv[2]
role = sys.argv[3]
svc = pwd.getpwnam("m8-service").pw_uid
s = p.lstat()
owner = p.parent.lstat().st_uid
uid = {"qualification": svc, "seal": svc, "candidate": owner, "authorization": 0}[role]
mode = 416 if role == "authorization" else 384
ok = (
    p == p.resolve(strict=True)
    and stat.S_ISREG(s.st_mode)
    and (s.st_nlink == 1)
    and (s.st_uid == uid)
    and (stat.S_IMODE(s.st_mode) == mode)
    and (0 < s.st_size <= 8192)
)
ok = ok and all(
    (
        q == q.resolve(strict=True)
        and stat.S_ISDIR(t.st_mode)
        and (t.st_uid in (0, svc, owner))
        and (not t.st_mode & 18)
        for q in (p.parent, *p.parent.parents)
        for t in (q.lstat(),)
    )
)
sys.exit(1) if not ok else None
fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
t = os.fstat(fd)
sys.exit(1) if (s.st_dev, s.st_ino, s.st_size) != (t.st_dev, t.st_ino, t.st_size) else None
raw = os.read(fd, 8193)
os.close(fd)
sys.exit(0 if len(raw) == s.st_size and hashlib.sha256(raw).hexdigest() == expected else 1)
"""
    return (
        shlex.join(["/usr/bin/sudo", "-n", "/usr/bin/python3", "-I", "-S", "-B", "-c", code])
        + ' "'
        + path
        + '" '
        + expected
        + " "
        + role
        + "\n"
    )


def _scripts(values, phase, evidence):
    packager, pins, blocks = _sources()
    required = values_checked(values, phase)
    if phase in ("d2-preserve", "d2-verify"):
        if phase == "d2-verify":
            d2_receipt_gate(evidence, values, "d2-preserve")
        return _d2_script(values, phase)
    if phase != "withdraw-after":
        d2_gate(evidence, values)
    if phase == "qualify":
        reload_gate(evidence, values)
    if phase == "checker-verify":
        phase_receipt(evidence, values, "controller-verify")
        phase_receipt(evidence, values, "launch-verify")
    if phase == "reload":
        phase_receipt(evidence, values, "checker-verify")
    if phase in ("withdraw-before", "publish"):
        inventory_gate(evidence, values)
    if phase in ("activate", "authority-install", "read"):
        cleanup_gate(evidence, values)
    common = blocks[0][0]
    common = common.replace(
        "C=8085b6af19dfaa31c8194b878d418a8e00b0ae73", "C=" + values["__controller_commit"]
    )
    common = common.replace(
        "L=b39350ce52abf846268e610af1175689e968386dc29c4ed67ea9d081d3391277",
        "L=" + values["__configuration_sha256"],
    )
    start = common.index("R=UNREVIEWED\n")
    end = common.index("STORE=(")
    common = (
        common[:start]
        + "".join("readonly " + k + "=" + shlex.quote(values[k]) + "\n" for k in BASE[1:])
        + "readonly CHECKER="
        + shlex.quote(values["__checker_path"])
        + "\n"
        + common[end:]
    )
    for k in ("FLOOR", "GENERATION"):
        if k in required:
            common += "readonly " + k + "=" + values[k] + "\n"
    if "Q" in required:
        common += "readonly Q=" + values["Q"] + "\n"
        qualification_gate(evidence, values, pins)
    if "SEALED_SHA256" in required:
        phase_receipt(evidence, values, "publish")
        readback_receipt(evidence, values, "publish", "sealed", "published-sealed.json")
        quiet_command(evidence, values, "publish")
        snapshot(evidence, "published-sealed.json", values["SEALED_SHA256"], 8192)
    if phase in ("authority-install", "read"):
        authority_gate(evidence, values)
    if phase == "publish":
        withdrawal_gate(evidence, values)
    byte_guards = ""
    for key, remote, role in (
        ("QUAL_RAW_SHA256", "$QUAL", "qualification"),
        ("SEALED_SHA256", "$AUTH/sealed.json", "seal"),
        ("CANDIDATE_SHA256", "$R/authorization-candidate.json", "candidate"),
    ):
        if key in required:
            if key == "SEALED_SHA256" and phase == "sealed-install":
                remote = "$R/published-sealed.json"
            if key == "SEALED_SHA256" and phase == "sealed-install":
                role = "candidate"
            byte_guards += byte_guard(remote, values[key], role)
    if phase == "read":
        byte_guards += byte_guard(
            "$AUTH/authorization.json", values["CANDIDATE_SHA256"], "authorization"
        )
    if phase in ("qualify-check", "reload-check", "checker-verify"):
        checker_guard = _checker_verification_code(values)
        byte_guards += (
            shlex.join(["/usr/bin/python3", "-I", "-S", "-B", "-c", checker_guard]) + "\n"
        )
    qualify, checker = blocks[1][0].splitlines(keepends=True)
    withdraw, publish, sealed = blocks[2]
    withdraw_code, before = withdraw.rsplit("sudo -n ", 1)
    sealed_install, activate = sealed.rsplit('sudo -n "${STORE[@]}" activate', 1)
    fixture, mint = blocks[3][0].splitlines(keepends=True)
    commands = {
        "qualify": qualify,
        "qualify-check": checker,
        "checker-verify": "",
        "reload": qualify.replace(" qualify ", " reload ")
        .replace('"$RUN/qualify"', '"$RUN/reload"')
        .replace('"$QUAL"', '"$RUN/reload.json"')
        .replace('"$R/qualify.', '"$R/reload.'),
        "reload-check": checker.replace("--phase qualify", "--phase reload")
        .replace('"$QUAL"', '"$RUN/reload.json"')
        .replace('"$R/qualification.digest"', '"$R/reload.digest"')
        .replace('"$R/checker.stderr"', '"$R/reload-checker.stderr"'),
        "withdraw-before": withdraw_code + "sudo -n " + before,
        "publish": publish.replace("Q=UNREVIEWED\n", "", 1),
        "sealed-install": sealed_install,
        "activate": 'sudo -n "${STORE[@]}" activate' + activate,
        "fixture": fixture,
        "mint": mint,
        "authority-install": blocks[3][1],
        "read": blocks[4][0],
        "withdraw-after": withdraw_code + blocks[4][1],
    }
    if phase == "inventory":
        inventory = r"""
import argparse, os, sys, json
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
with inherit_maintenance(
    a.store_root, a.key, a.lock_fd, generation_floor=a.floor, parent=os.getppid()
) as held:
    held.check()
    assert type(held.generation_floor) is int and held.generation_floor >= 1
    print(
        json.dumps({"highest_generation": held.generation_floor, "withdrawn": True}, sort_keys=True)
    )
"""
        commands[phase] = (
            'sudo -n "${STORE[@]}" maintain --store-root "$STORES" --key "$STORE_KEY" '
            '--service "$SERVICE" --wait 0 -- /usr/bin/python3 -I -S -B -c '
            + shlex.quote(inventory)
            + ' < /dev/null > "$R/inventory.json" 2> "$R/inventory.stderr"\n'
        )
    if phase == "candidate-pins":
        code = _EXPECTED_CODE
        commands[phase] = (
            'sudo -n -u "$SERVICE" -- /usr/bin/python3 -I -S -B -c '
            + shlex.quote(code)
            + ' --fixture "$RUN/fixture" --launch-config "$CONFIG" --launch-config-sha256 "$L" '
            '--store-root "$STORES" --store-key "$STORE_KEY" --sealed "$AUTH/sealed.json" '
            '--qualification "$QUAL" --acquisition-root "$ACQ" < /dev/null '
            '> "$R/candidate-pins.json" 2> "$R/candidate-pins.stderr"\n'
        )
    if phase in ("controller-verify", "launch-verify"):
        body = _verification_body(values, phase)
        body = body.replace("canonical-policy-diagnostic-", "first-read-")
        body = body.replace(
            "EXPECTED_BOOT=UNREVIEWED", "readonly EXPECTED_BOOT=" + values["EXPECTED_BOOT"]
        )
        command = body
    else:
        if phase == "parents":
            custody_code = r"""
import os, pathlib, stat, sys

paths = [pathlib.Path(x) for x in sys.argv[1:]]
u = os.geteuid()
ok = u != 0 and (not any((os.path.lexists(p) for p in paths)))
ok = ok and all(
    (
        p.parent == p.parent.resolve(strict=True)
        and all(
            (
                stat.S_ISDIR(s.st_mode)
                and (not s.st_mode & 18)
                and (s.st_uid in ((0, u) if i == 0 else (0,)))
                for q in (p.parent, *p.parent.parents)
                for s in (q.lstat(),)
            )
        )
        for i, p in enumerate(paths)
    )
)
sys.exit(0 if ok else 1)
"""
            command = (
                "/usr/bin/python3 -I -S -B -c "
                + shlex.quote(custody_code)
                + ' "$R" "$RUN" "$AUTH" "$ACQ"\n'
                'test ! -e "$R" && test ! -L "$R"\n/usr/bin/mkdir -m 0700 -- "$R"\n'
                'for p in "$RUN" "$AUTH" "$ACQ"; do\n'
                '  sudo -n /usr/bin/test ! -e "$p"\n  sudo -n /usr/bin/test ! -L "$p"\ndone\n'
                'sudo -n /usr/bin/install -d -o "$SERVICE" -g "$SERVICE" -m 0700 "$RUN" "$ACQ"\n'
                'sudo -n /usr/bin/install -d -o root -g "$SERVICE" -m 0750 "$AUTH"\n'
            )
        else:
            command = commands[phase].replace(
                "--selected-plan max", "--selected-plan " + values["__selected_plan"]
            )
        command = common + byte_guards + command
    guard_doc = _document("guard")
    guard_blocks = packager.fences(packager.section(guard_doc, "G1: private drift boundary"))
    require(len(guard_blocks) == 1 and guard_blocks[0][0] == "bash")
    preface = (
        "#!/bin/bash\nset -Eeuo pipefail -C\numask 077\nreadonly EXPECTED_BOOT="
        + values["EXPECTED_BOOT"]
        + '\ntest "$(/usr/bin/cat /proc/sys/kernel/random/boot_id)" = "$EXPECTED_BOOT"\n'
        "readonly DRIFT_STDOUT_HEX="
        + values["__drift_hex"]
        + "\nreadonly DRIFT_TOOL_SHA256="
        + values["__drift_sha256"]
        + '\nDRIFT_CAPTURE="$PWD/drift"\n'
        + guard_blocks[0][1]
    )
    if phase in ("controller-verify", "launch-verify"):
        command = command.replace("readonly EXPECTED_BOOT=" + values["EXPECTED_BOOT"] + "\n", "", 1)
    result = (preface + command).encode("utf-8")
    require(b"UNREVIEWED" not in result and b"\r" not in result)
    return result


def _checker_verification_code(values):
    path, size, digest = (
        values["__checker_path"],
        values["__checker_size"],
        values["__checker_sha256"],
    )
    boot = (values["EXPECTED_BOOT"] + "\n").encode("ascii")
    return (
        "import hashlib,pathlib,stat,sys;"
        f"p=pathlib.Path({path!r});s=p.lstat();"
        "ok=stat.S_ISREG(s.st_mode) and s.st_uid==0 and s.st_gid==0 and "
        f"stat.S_IMODE(s.st_mode)==0o444 and s.st_nlink==1 and s.st_size=={size};"
        "parents=(p.parent,*p.parent.parents);"
        "ok=ok and all(stat.S_ISDIR(t.st_mode) and t.st_uid==0 and t.st_gid==0 and "
        "not t.st_mode&0o022 and q.resolve(strict=True)==q for q in parents for t in (q.lstat(),));"
        "ok=ok and stat.S_IMODE(p.parent.lstat().st_mode)==0o555;"
        "ok=ok and pathlib.Path('/proc/sys/kernel/random/boot_id').read_bytes()=="
        f"{boot!r};"
        "sys.exit(1) if not ok else None;raw=p.read_bytes();"
        f"ok=ok and hashlib.sha256(raw).hexdigest()=={digest!r};"
        "sys.exit(1) if not ok else None;"
    )


def _verification_body(values, phase):
    namespace = values["__namespace"]
    q = shlex.quote
    if phase == "controller-verify":
        workspace = q(values["__controller_workspace"])
        name = namespace + "-controller-verify.json"
        return (
            f"C={values['__controller_commit']}\nW={workspace}\n"
            'test -f "$W/m8_host_artifacts.py" && test ! -L "$W/m8_host_artifacts.py"\n'
            'test "$(/usr/bin/sha256sum "$W/m8_host_artifacts.py" | /usr/bin/cut -d\' \' -f1)" = '
            f"{values['__controller_helper_sha256']}\n"
            f'test ! -e "$W/{name}" && test ! -L "$W/{name}"\n'
            '/usr/bin/python3 -I "$W/m8_host_artifacts.py" verify-controller "$C" "$W" '
            f'< /dev/null > "$W/{name}"\n'
            "printf 'controller-verify-recorded\\n'\n"
        )
    workspace = q(values["__launch_workspace"])
    name = namespace + "-launch-verify.json"
    profiles = namespace + "-profiles.txt"
    return (
        f"A={values['__launch_commit']}\nL={values['__configuration_sha256']}\nAW={workspace}\n"
        f'P="$AW/{profiles}"\nR="$AW/{name}"\n'
        'test -f "$AW/claude_host_artifacts.py" && test ! -L "$AW/claude_host_artifacts.py"\n'
        'test "$(/usr/bin/sha256sum "$AW/claude_host_artifacts.py" | /usr/bin/cut -d\' \' -f1)" = '
        f"{values['__launch_helper_sha256']}\n"
        'test ! -e "$AW/staging" && test ! -L "$AW/staging"\n'
        'test ! -e "$P" && test ! -L "$P" && test ! -e "$R" && test ! -L "$R"\n'
        'sudo -n /usr/bin/cat /sys/kernel/security/apparmor/profiles > "$P"\n'
        'test "$(/usr/bin/wc -c < "$P")" -lt 1048576\n'
        '/usr/bin/python3 -I -S -B "$AW/claude_host_artifacts.py" verify "$A" "$AW" '
        '--launch-config-sha256 "$L" < "$P" > "$R"\n'
        "printf 'maintenance-launch-verify-recorded\\n'\n"
    )


def compile_phase(bindings, phase, evidence):
    require(type(bindings) is Bindings and phase in PHASES and isinstance(evidence, Path))
    return _scripts(bindings.expanded(), phase, evidence)


def check_phase_receipt(bindings, phase, evidence):
    require(type(bindings) is Bindings and phase in PHASES)
    values = bindings.expanded()
    if phase == "d2-preserve":
        d2_receipt_gate(evidence, values, phase)
    elif phase == "d2-verify":
        d2_gate(evidence, values)
    else:
        phase_receipt(evidence, values, phase)
        if "stderr" in PHASES[phase].outputs:
            quiet_command(
                evidence, values, phase, stdout=phase in ("reload", "qualify", "activate")
            )
        if phase == "read":
            terminal_gate(evidence, values)
        elif phase == "withdraw-after":
            cleanup_complete(evidence, values)


def build_package(phase, bindings_path, evidence, out, expected_operator_revision):
    require(expected_operator_revision == operator_revision())
    raw = bounded(bindings_path, 16384)
    bindings = Bindings.from_dict(parsed(raw))
    script = compile_phase(bindings, phase, evidence)
    pins = {
        "controller_commit": bindings.controller_commit,
        "operator_revision": expected_operator_revision,
        "phase": phase,
        "bindings_sha256": sha(raw),
        "script_sha256": sha(script),
    }
    files = {
        "phase.sh": script,
        "bindings.json": raw,
        "SOURCE-PINS.json": (json.dumps(pins, sort_keys=True) + "\n").encode(),
    }
    out.mkdir(mode=0o700)
    for name, body in files.items():
        with (out / name).open("xb") as stream:
            stream.write(body)
    manifest = "".join(f"{sha(body)}  {name}\n" for name, body in files.items()).encode()
    with (out / "MANIFEST.sha256").open("xb") as stream:
        stream.write(manifest)
    return sha(manifest)


def package_checked(package, manifest, expected_operator_revision):
    require(expected_operator_revision == operator_revision())
    raw = bounded(package / "MANIFEST.sha256", 1024)
    require(sha(raw) == manifest)
    names = ("phase.sh", "bindings.json", "SOURCE-PINS.json")
    bodies = {name: bounded(package / name, 131072) for name in names}
    require(
        raw == "".join(f"{sha(bodies[name])}  {name}\n" for name in names).encode()
        and {item.name for item in package.iterdir()} == {*names, "MANIFEST.sha256"}
    )
    bindings = Bindings.from_dict(parsed(bodies["bindings.json"]))
    pins = parsed(bodies["SOURCE-PINS.json"])
    require(
        set(pins)
        == {"controller_commit", "operator_revision", "phase", "bindings_sha256", "script_sha256"}
        and pins["controller_commit"] == bindings.controller_commit
        and pins["operator_revision"] == expected_operator_revision
        and pins["phase"] in PHASES
        and pins["bindings_sha256"] == sha(bodies["bindings.json"])
        and pins["script_sha256"] == sha(bodies["phase.sh"])
    )
    return pins, bindings


def validated_package(package, manifest, revision, evidence):
    pins, bindings = package_checked(package, manifest, revision)
    require(
        bounded(package / "phase.sh", 131072) == compile_phase(bindings, pins["phase"], evidence)
    )
    return pins, bindings


def context_bytes(manifest, pins, bindings):
    return (
        json.dumps(
            {
                "phase": pins["phase"],
                "package_manifest": manifest,
                "operator_revision": pins["operator_revision"],
                "controller_commit": bindings.controller_commit,
                "bindings_sha256": pins["bindings_sha256"],
                "script_sha256": pins["script_sha256"],
                "boot": bindings.values["EXPECTED_BOOT"],
            },
            sort_keys=True,
        )
        + "\n"
    ).encode()


def remote_name(bindings, phase, manifest):
    require(phase in PHASES and SHA.fullmatch(manifest))
    return bindings.namespace + "-" + phase + "-" + manifest[:16]


def readback_spec(bindings, phase, part, manifest):
    require(phase in PHASES and part in PHASES[phase].outputs)
    variable, suffix, limit = PHASES[phase].outputs[part]
    base = {
        "CONTROLLER_W": bindings.controller_workspace,
        "CLAUDE_W": bindings.launch_workspace,
        "PHASE_DIRECTORY": str(
            PurePosixPath(bindings.values["R"]).parent / remote_name(bindings, phase, manifest)
        ),
    }.get(variable, bindings.values.get(variable))
    require(type(base) is str)
    path = base + ("/" + suffix.format(namespace=bindings.namespace) if suffix else "")
    service = variable in ("QUAL", "RUN")
    slots = {
        ("qualify", "evidence"): "qualification.json",
        ("qualify-check", "digest"): "checker.stdout",
        ("reload", "evidence"): "reload.json",
        ("reload-check", "digest"): "reload.digest",
        ("inventory", "inventory"): "inventory.json",
        ("publish", "sealed"): "published-sealed.json",
        ("fixture", "fixture"): "fixture.json",
        ("mint", "candidate"): "authorization-candidate.json",
        ("candidate-pins", "pins"): "candidate-pins.json",
        ("d2-verify", "record"): "d2-lr2.out",
        ("read", "result"): "read-status.json",
    }
    slot = slots.get(
        (phase, part),
        phase + ".command." + part
        if part in ("stdout", "stderr")
        else phase + "." + part + ".json",
    )
    return path, limit, service, slot


def protected_read_command(path, limit, service):
    require(
        _absolute(path) and type(limit) is int and 1 <= limit <= 65536 and type(service) is bool
    )
    prefix = ["/usr/bin/sudo", "-n", "-u", "m8-service", "--"] if service else []
    return shlex.join(
        [
            *prefix,
            "/usr/bin/python3",
            "-I",
            "-S",
            "-B",
            "-c",
            _READ_CODE,
            path,
            "service" if service else "operator",
            str(limit),
        ]
    )
