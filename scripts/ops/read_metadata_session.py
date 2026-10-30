"""One source-bound metadata collection, without READ execution authority.

Custody/target discovery are externally measured operator prerequisites. Old
authorization bytes identify retained evidence; expiry/grants are never reused.
Capture bounds are post-completion checks, not streaming or disk-write caps.
"""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from scripts.ops import claude_read_commands as commands  # noqa: E402
from scripts.ops import claude_read_session as session  # noqa: E402
from scripts.ops import read_attempt_evidence as reader  # noqa: E402

from constructicon.core.control import command_id_for, run_id_for_command  # noqa: E402
from constructicon.core.qualification import QUALIFICATION_OPERATION  # noqa: E402

require, sha, parsed, bounded = commands.require, commands.sha, commands.parsed, commands.bounded
FILES = ("phase.sh", "bindings.json", "SOURCE-PINS.json")
RETAINED = {
    "context_sha256",
    "bindings_sha256",
    "authorization_sha256",
    "controller_commit",
    "boot",
    "run_root",
    "authorization_id",
    "run_id",
    "max_epoch",
}
FRESH = {"boot", "target", "alias", "namespace", "drift_sha256", "drift_stdout"}
BOOT = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
HISTORY = {
    "context_sha256": "read-context.json",
    "bindings_sha256": "bindings.json",
    "authorization_sha256": "authorization-candidate.json",
}


def sources():
    names = (
        "scripts/ops/read_metadata_session.py",
        "scripts/ops/read_attempt_evidence.py",
        "scripts/ops/claude_read_session.py",
        "scripts/ops/claude_read_commands.py",
        "scripts/m8_procedure_package.py",
        "src/constructicon/core/claude_read_observation.py",
        "src/constructicon/core/control.py",
        "src/constructicon/core/address.py",
        "src/constructicon/core/identity.py",
        "src/constructicon/core/qualification.py",
        "docs/plans/handoffs/M8-private-output-guard.md",
    )
    return {name: sha((ROOT / name).read_bytes()) for name in names}


def revision():
    return sha(session.json_bytes(sources()))


def request_checked(raw, history):
    request = parsed(raw)
    require(
        type(request) is dict
        and set(request) == {"schema_version", "retained", "fresh"}
        and type(request["schema_version"]) is int
        and request["schema_version"] == 1
    )
    old, fresh = request["retained"], request["fresh"]
    require(
        type(old) is dict and set(old) == RETAINED and type(fresh) is dict and set(fresh) == FRESH
    )
    require(all(type(old[k]) is str and commands.SHA.fullmatch(old[k]) for k in HISTORY))
    require(
        type(old["controller_commit"]) is str
        and commands.COMMIT.fullmatch(old["controller_commit"])
        and type(old["max_epoch"]) is int
        and old["max_epoch"] == 1
    )
    require(
        all(type(block["boot"]) is str and BOOT.fullmatch(block["boot"]) for block in (old, fresh))
    )
    require(
        commands._absolute(old["run_root"])
        and re.fullmatch(r"/var/lib/m8-cr-[A-Za-z0-9_-]+", old["run_root"])
    )
    require(
        all(
            type(old[k]) is str and re.fullmatch(r"[A-Za-z0-9:_.-]{1,256}", old[k])
            for k in ("authorization_id", "run_id")
        )
    )
    session._target(fresh["target"], fresh["alias"])
    require(
        type(fresh["namespace"]) is str
        and re.fullmatch(r"[a-z][a-z0-9-]{0,63}", fresh["namespace"])
    )
    require(type(fresh["drift_sha256"]) is str and commands.SHA.fullmatch(fresh["drift_sha256"]))
    line = fresh["drift_stdout"]
    require(
        type(line) is str
        and 1 < len(line.encode()) <= 128
        and line.endswith("\n")
        and line[:-1].isprintable()
    )
    records = {}
    for key, name in HISTORY.items():
        body = bounded(history / name, 16384)
        require(sha(body) == old[key])
        records[name] = parsed(body)
    context, binding, authorization = (records[name] for name in HISTORY.values())
    require(type(context) is dict and type(binding) is dict and type(authorization) is dict)
    require(
        set(context)
        == {
            "phase",
            "boot",
            "controller_commit",
            "bindings_sha256",
            "operator_revision",
            "package_manifest",
            "script_sha256",
        }
        and all(
            type(context[k]) is str and commands.SHA.fullmatch(context[k])
            for k in ("bindings_sha256", "operator_revision", "package_manifest", "script_sha256")
        )
    )
    require(
        context.get("phase") == "read"
        and context.get("boot") == old["boot"]
        and context.get("controller_commit")
        == binding.get("controller_commit")
        == old["controller_commit"]
        and context.get("bindings_sha256") == old["bindings_sha256"]
    )
    values = binding.get("values")
    require(
        type(values) is dict
        and values.get("EXPECTED_BOOT") == old["boot"]
        and values.get("RUN") == old["run_root"]
        and values.get("AUTHORIZATION_ID") == old["authorization_id"]
        and values.get("CANDIDATE_SHA256") == old["authorization_sha256"]
        and values.get("ACTOR") == authorization.get("actor_id")
        and values.get("READ_KEY") == authorization.get("idempotency_key")
    )
    require(
        authorization.get("stage") == "qualification-read"
        and authorization.get("authorization_id") == old["authorization_id"]
        and type(authorization.get("max_epoch")) is int
        and authorization["max_epoch"] == 1
        and authorization.get("journal") == old["run_root"] + "/read.sqlite"
        and authorization.get("attempt_record") == old["run_root"] + "/read-attempt.json"
    )
    require(
        str(
            run_id_for_command(
                command_id_for(
                    authorization["actor_id"],
                    QUALIFICATION_OPERATION,
                    authorization["idempotency_key"],
                )
            )
        )
        == old["run_id"]
    )
    return request


def render(request):
    old, fresh = request["retained"], request["fresh"]
    guard = commands._fence("guard", "G1: private drift boundary")
    collector = (ROOT / "scripts/ops/read_attempt_evidence.py").read_bytes().decode("utf-8")
    invocation = shlex.join(
        [
            "/usr/bin/sudo",
            "-n",
            "-u",
            "m8-service",
            "--",
            "/usr/bin/python3",
            "-I",
            "-S",
            "-B",
            "-c",
            collector,
            "--run-root",
            old["run_root"],
            "--authorization-id",
            old["authorization_id"],
            "--run-id",
            old["run_id"],
            "--max-epoch",
            "1",
        ]
    )
    marker = (
        "import pathlib;assert pathlib.Path('drift-marker.stdout').read_bytes()"
        "==b'drift-checked\\n'"
    )
    return (
        "#!/bin/bash\nset -Eeuo pipefail -C\numask 077\n"
        + 'test "$(/usr/bin/cat /proc/sys/kernel/random/boot_id)" = '
        + shlex.quote(fresh["boot"])
        + "\n"
        + "readonly DRIFT_STDOUT_HEX="
        + fresh["drift_stdout"].encode().hex()
        + "\n"
        + "readonly DRIFT_TOOL_SHA256="
        + fresh["drift_sha256"]
        + "\n"
        + 'DRIFT_CAPTURE="$PWD/drift"\n{\n'
        + guard
        + '} > "$PWD/drift-marker.stdout"\n'
        + shlex.join(["/usr/bin/python3", "-I", "-S", "-B", "-c", marker])
        + " < /dev/null\n"
        + "exec "
        + invocation
        + " < /dev/null\n"
    ).encode("utf-8")


def compile_package(request_path, history, out, expected_revision):
    require(expected_revision == revision())
    raw = bounded(request_path, 16384)
    request = request_checked(raw, history)
    script = render(request)
    pins = {
        "scope": "read-metadata",
        "source_revision": expected_revision,
        "sources": sources(),
        "request_sha256": sha(raw),
        "script_sha256": sha(script),
    }
    files = {"phase.sh": script, "bindings.json": raw, "SOURCE-PINS.json": session.json_bytes(pins)}
    out.mkdir(mode=0o700)
    for name, body in files.items():
        session.retain(out / name, body)
    manifest = "".join(f"{sha(body)}  {name}\n" for name, body in files.items()).encode()
    session.retain(out / "MANIFEST.sha256", manifest)
    return sha(manifest)


def package_checked(package, manifest, expected_revision, history):
    require(expected_revision == revision())
    raw = bounded(package / "MANIFEST.sha256", 1024)
    require(
        sha(raw) == manifest
        and {item.name for item in package.iterdir()} == {*FILES, "MANIFEST.sha256"}
    )
    bodies = {name: bounded(package / name, 131072) for name in FILES}
    require(raw == "".join(f"{sha(body)}  {name}\n" for name, body in bodies.items()).encode())
    request = request_checked(bodies["bindings.json"], history)
    pins = parsed(bodies["SOURCE-PINS.json"])
    require(
        pins
        == {
            "scope": "read-metadata",
            "source_revision": expected_revision,
            "sources": sources(),
            "request_sha256": sha(bodies["bindings.json"]),
            "script_sha256": sha(bodies["phase.sh"]),
        }
    )
    require(bodies["phase.sh"] == render(request))
    return request, pins


def context_bytes(manifest, request, pins):
    return session.json_bytes(
        {
            "scope": "read-metadata",
            "manifest": manifest,
            "source_revision": pins["source_revision"],
            "request_sha256": pins["request_sha256"],
            "script_sha256": pins["script_sha256"],
            "historical_boot": request["retained"]["boot"],
            "current_boot": request["fresh"]["boot"],
        }
    )


def transport(package, manifest, expected_revision, history, captures):
    request, pins = package_checked(package, manifest, expected_revision, history)
    fresh = request["fresh"]
    name = fresh["namespace"] + "-metadata-" + manifest[:16]
    argv = session.staging_commands(package, manifest, name, fresh["target"], fresh["alias"])
    session.retain(captures / "metadata-context.json", context_bytes(manifest, request, pins))
    for suffix, command in zip(("preflight", "mkdir", "copy"), argv[:3], strict=True):
        status, out, err = session.capture("metadata-" + suffix, captures, command, 120)
        require(commands.completed_zero(status) and out == err == b"")
    status, _, _ = session.capture("metadata-native", captures, argv[3], 60, reader.OUTPUT_BYTES)
    return status


def _closed(value, choices, *, nullable=False):
    return (nullable and value is None) or (type(value) is str and value in choices)


def observation_checked(raw):
    value = parsed(raw)
    require(
        type(value) is dict
        and set(value) == {"schema_version", "attempt", "journal"}
        and type(value["schema_version"]) is int
        and value["schema_version"] == 1
    )
    attempt, journal = value["attempt"], value["journal"]
    common = {"state", "partial"}
    fields = {
        "phase",
        "dispatch",
        "status",
        "callback_started",
        "callback_completed",
        "initial_binding_checked",
        "terminal_binding_checked",
        "relay_closed",
        "callback_observation",
    }
    require(
        type(attempt) is dict
        and set(attempt) == common | fields
        and type(journal) is dict
        and set(journal) == common | {"run_status", "event_count", "events"}
    )
    for record in (attempt, journal):
        require(
            _closed(record["state"], ("valid", "invalid", "missing"))
            and type(record["partial"]) is bool
        )
        if record["state"] != "valid":
            require(
                record["partial"] is True
                and all(v is None for k, v in record.items() if k not in common)
            )
    if attempt["state"] == "valid":
        require(
            _closed(attempt["phase"], reader.PHASES)
            and attempt["partial"] == (attempt["phase"] != "outcome")
        )
        if attempt["phase"] == "outcome":
            require(
                _closed(attempt["dispatch"], reader.DISPATCH)
                and _closed(attempt["status"], reader.STATUS, nullable=True)
                and reader._integer(attempt["callback_started"], 1)
                and reader._integer(attempt["callback_completed"], attempt["callback_started"])
                and all(
                    type(attempt[k]) is bool
                    for k in ("initial_binding_checked", "terminal_binding_checked", "relay_closed")
                )
            )
        else:
            require(all(attempt[k] is None for k in fields - {"phase", "callback_observation"}))
        cb = attempt["callback_observation"]
        if cb is not None:
            require(
                type(cb) is dict
                and set(cb)
                == {"schema_version", "admitted_started", "admitted_completed", "worker_results"}
                and type(cb["schema_version"]) is int
                and cb["schema_version"] == 1
                and reader._integer(cb["admitted_started"], 8)
                and reader._integer(cb["admitted_completed"], cb["admitted_started"])
                and type(cb["worker_results"]) is list
                and len(cb["worker_results"]) == cb["admitted_started"]
                and all(
                    v is None or (type(v) is str and v in reader.WORKERS)
                    for v in cb["worker_results"]
                )
                and all(v == "success" for v in cb["worker_results"][: cb["admitted_completed"]])
            )
    if journal["state"] == "valid":
        require(
            _closed(journal["run_status"], reader.RUN_STATUS)
            and reader._integer(journal["event_count"], reader.EVENT_LIMIT)
            and type(journal["events"]) is list
            and len(journal["events"]) == journal["event_count"]
        )
        for event in journal["events"]:
            require(
                type(event) is dict
                and set(event) in ({"kind", "error_type", "reason"},
                                   {"kind", "error_type", "reason", "refusal_context"},
                                   {"kind", "error_type", "reason", "initialize_observation"})
                and _closed(event["kind"], reader.EVENTS | {"other"})
                and _closed(event["error_type"], reader.ERRORS | {"other"}, nullable=True)
                and _closed(event["reason"], {*reader.REASONS.values(), reader.INITIALIZE_REASON,
                                              "other"}, nullable=True)
            )
            require((event["reason"] == reader.INITIALIZE_REASON)
                    == ("initialize_observation" in event))
            if "initialize_observation" in event:
                require(event["kind"] == "NodeFailed"
                        and event["error_type"] == "ContractViolation"
                        and reader.initialize_fields_valid(event["initialize_observation"]))
            if "refusal_context" in event:
                context = event["refusal_context"]
                require(
                    event["kind"] == "NodeFailed"
                    and event["error_type"] == "ContractViolation"
                    and event["reason"] in {
                        reason for message, reason in reader.REASONS.items()
                        if message.startswith("Claude READ refused [known_refusal=")
                    }
                    and type(context) is dict
                    and set(context) == {"family", "phase", "predicate", "terminal_result_accepted"}
                    and _closed(context["family"], reader.REFUSAL_FAMILIES)
                    and _closed(context["phase"], reader.REFUSAL_PHASES)
                    and _closed(context["predicate"], reader.REFUSAL_PREDICATES)
                    and type(context["terminal_result_accepted"]) is bool
                )
    require(len(raw) <= reader.OUTPUT_BYTES)
    return value


def check(package, manifest, expected_revision, history, captures):
    request, pins = package_checked(package, manifest, expected_revision, history)
    require(
        bounded(captures / "metadata-context.json", 2048) == context_bytes(manifest, request, pins)
    )
    for suffix in ("preflight", "mkdir", "copy"):
        require(
            commands.completed_zero(
                parsed(bounded(captures / ("metadata-" + suffix + ".status.json"), 256))
            )
            and bounded(captures / ("metadata-" + suffix + ".stdout"), 4096, empty=True) == b""
            and bounded(captures / ("metadata-" + suffix + ".stderr"), 4096, empty=True) == b""
        )
    status = parsed(bounded(captures / "metadata-native.status.json", 256))
    require(
        type(status) is dict
        and set(status) == {"completed", "returncode", "timed_out"}
        and status["completed"] is True
        and type(status["returncode"]) is int
        and status["returncode"] in (0, 1)
        and status["timed_out"] is False
        and bounded(captures / "metadata-native.stderr", 4096, empty=True) == b""
    )
    observation = observation_checked(
        bounded(captures / "metadata-native.stdout", reader.OUTPUT_BYTES)
    )
    invalid = any(observation[k]["state"] == "invalid" for k in ("attempt", "journal"))
    require((status["returncode"] == 1) == invalid)
    return {"collection_checked": not invalid, "observation": observation}


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        del message
        self.exit(2, "metadata arguments refused\n")


def main():
    parser = _Parser(add_help=False, allow_abbrev=False)
    parser.add_argument("action", choices=("describe", "compile", "transport", "check"))
    for name in ("request", "history", "out", "package", "captures"):
        parser.add_argument("--" + name, type=Path)
    for name in ("revision", "manifest"):
        parser.add_argument("--" + name)
    args = parser.parse_args()
    if args.action == "describe":
        result, code = (
            {"scope": "read-metadata", "source_revision": revision(), "sources": sources()},
            0,
        )
    elif args.action == "compile":
        require(all(v is not None for v in (args.request, args.history, args.out, args.revision)))
        result = {"manifest": compile_package(args.request, args.history, args.out, args.revision)}
        code = 0
    else:
        require(
            all(
                v is not None
                for v in (args.package, args.manifest, args.revision, args.history, args.captures)
            )
        )
        if args.action == "transport":
            result = transport(
                args.package, args.manifest, args.revision, args.history, args.captures
            )
            code = 0 if commands.completed_zero(result) else 1
        else:
            result = check(args.package, args.manifest, args.revision, args.history, args.captures)
            code = 0 if result["collection_checked"] else 1
    sys.stdout.buffer.write(session.json_bytes(result))
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print("metadata step refused", file=sys.stderr)
        raise SystemExit(1) from None
