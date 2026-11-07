"""Selected source facts plus actual credential-free caller/helper execution."""

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest
from scripts import m8_procedure_package as package
from scripts.ops import m9_qualification_boundary as boundary
from scripts.ops.claude_read_session import json_bytes

from tests.test_m9_qualification_boundary import ALIAS, TARGET, NativeTwin, selected
from tests.test_m9_read_transport import bash

PRIOR = "/home/fixture/m8-maint-q13"
CURRENT = "/home/fixture/m9-codex-g12"
OLD_RUNTIME = "sha256:" + "1" * 64


def fixture_contract(root):
    """Fake filesystem is the only substituted platform primitive, no fallback."""
    evidence = {name: json_bytes({"runtime": OLD_RUNTIME, "name": name}).decode()
                for name in ("s4-qualification.json", "s6a-qualification.json")}
    fixture = root / "fake-files.json"
    fixture.write_bytes(json_bytes({PRIOR + "/" + key: raw for key, raw in evidence.items()}))
    hashes = [hashlib.sha256(raw.encode()).hexdigest() for raw in evidence.values()]
    code = '''import hashlib, json, sys
from pathlib import PurePosixPath
path, runtime, first, second, fixture = sys.argv[1:]
# Closed fake platform: an unknown path fails; there is no native file fallback.
files = json.load(open(fixture, encoding="utf-8"))
p = PurePosixPath(path)
expected = dict(zip(("s4-qualification.json", "s6a-qualification.json"), (first, second)))
assert str(p.parent) == "/home/fixture/m8-maint-q13" and p.name in expected
raw = files[path].encode()
assert hashlib.sha256(raw).hexdigest() == expected[p.name]
assert json.loads(raw)["runtime"] == runtime
'''
    helper = (
        'check_evidence() {\n  "$PYTHON" -I -S -B -c ' + shlex.quote(code)
        + ' "$1" ' + shlex.join([OLD_RUNTIME, *hashes, fixture.as_posix()]) + '\n}\n'
    )
    caller = ('check_evidence "$W_PRIOR/s4-qualification.json"\n'
              'check_evidence "$W_PRIOR/s6a-qualification.json"\n')
    body = ('set -Eeuo pipefail\nreadonly M9_BOOT=UNREVIEWED\n'
            + 'PYTHON=' + shlex.quote(Path(sys.executable).as_posix()) + '\n'
            + helper + 'W_PRIOR=' + PRIOR + '\n' + caller
            + "printf 'fixture exact phase output\\n'\n").encode()
    return body, {"helper": helper, "caller": caller, "bindings": {"W_PRIOR": PRIOR}}


def execute(body, root):
    script = root / "caller.sh"
    script.write_bytes(body.replace(b"UNREVIEWED", b"fixture"))
    return subprocess.run(
        [bash(), script.as_posix()], cwd=root, stdin=subprocess.DEVNULL,
        capture_output=True, check=False, timeout=5,
        env=dict(os.environ, MSYS2_ARG_CONV_EXCL="*"),
    )


def test_actual_caller_helper_permits_and_refuses_transplant_repeatably(tmp_path):
    body, contract = fixture_contract(tmp_path)
    for _ in range(2):
        proof = package.helper_contract(body, contract)
        assert proof["coverage"] == "selected-literal-source-only"
        assert proof["execution"] == "not-executed"
        accepted = execute(body, tmp_path)
        assert accepted.returncode == 0 and not accepted.stderr
        assert accepted.stdout == b"fixture exact phase output\n"
    transplanted = body.replace(('W_PRIOR=' + PRIOR).encode(), ('W_PRIOR=' + CURRENT).encode())
    refused = execute(transplanted, tmp_path)
    assert refused.returncode != 0 and b"AssertionError" in refused.stderr
    with pytest.raises(package.Refused):
        package.helper_contract(transplanted, contract)


@pytest.mark.parametrize("change", ["parent", "runtime", "raw-sha", "caller", "duplicate"])
def test_each_input_binding_refuses_even_when_new_script_digest_is_selected(tmp_path, change):
    body, contract = fixture_contract(tmp_path)
    if change == "parent":
        body = body.replace(('W_PRIOR=' + PRIOR).encode(), ('W_PRIOR=' + CURRENT).encode())
    elif change == "runtime":
        body = body.replace(OLD_RUNTIME.encode(), ("sha256:" + "2" * 64).encode())
    elif change == "raw-sha":
        match = re.search(rb" ([0-9a-f]{64}) ", body)
        assert match is not None
        body = body.replace(match[1], b"0" * 64)
    elif change == "caller":
        body = body.replace(b'check_evidence "$W_PRIOR/s4', b'check_evidence "$W/s4')
    else:
        body += ('W_PRIOR=' + PRIOR + '\n').encode()
    reason = {"parent": "binding W_PRIOR declaration", "runtime": "helper block",
              "raw-sha": "helper block", "caller": "caller block",
              "duplicate": "binding W_PRIOR declaration"}[change]
    with pytest.raises(package.Refused, match=reason):
        package.helper_contract(body, contract)


def test_contract_cli_emits_repeatable_source_only_proof_and_refuses(tmp_path):
    body, contract = fixture_contract(tmp_path)
    script, data = tmp_path / "script.sh", tmp_path / "contract.json"
    script.write_bytes(body)
    data.write_bytes(json_bytes(contract))
    argv = [sys.executable, "-I", "-S", "-B", str(Path(package.__file__)),
            "check-contract", str(script), str(data)]
    results = [subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                              check=False, timeout=5) for _ in range(2)]
    assert all(result.returncode == 0 and not result.stderr for result in results)
    assert results[0].stdout == results[1].stdout
    assert json.loads(results[0].stdout)["execution"] == "not-executed"
    script.write_bytes(body.replace(('W_PRIOR=' + PRIOR).encode(),
                                    ('W_PRIOR=' + CURRENT).encode()))
    refused = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                             check=False, timeout=5)
    assert refused.returncode == 1 and not refused.stdout
    assert b"binding W_PRIOR declaration" in refused.stderr
    assert CURRENT.encode() not in refused.stderr and PRIOR.encode() not in refused.stderr


def test_contract_diagnostics_distinguish_shape_and_binding_without_echoing_values(tmp_path):
    body, contract = fixture_contract(tmp_path)
    with pytest.raises(package.Refused, match="contract keys"):
        package.helper_contract(body, {})
    with pytest.raises(package.Refused, match="script must"):
        package.helper_contract(b"", contract)
    contract["bindings"] = {"PRIVATE_PIN": "sensitive-fixture-value"}
    with pytest.raises(package.Refused, match="binding PRIVATE_PIN declaration") as refused:
        package.helper_contract(body, contract)
    assert "sensitive-fixture-value" not in str(refused.value)


def v2_selection(root):
    path, _ = selected(root)
    body, contract = fixture_contract(root)
    path.with_name("preflight-custody-floor.sh").write_bytes(body)
    record = json.loads(path.read_bytes())
    record["schema_version"] = 2
    record["phases"]["preflight-custody-floor"]["script"] = boundary.sha(body)
    record["helper_contracts"] = {phase: [] for phase in (*boundary.PHASES, boundary.CLEANUP)}
    record["helper_contracts"]["preflight-custody-floor"] = [contract]
    raw = json_bytes(record)
    path.write_bytes(raw)
    return path, boundary.sha(raw)


class ContractTwin(NativeTwin):
    def __call__(self, argv, **kwargs):
        command = argv[-1]
        # Closed dispatch: every external request must have exactly one fake
        # implementation. Unknown or ambiguous operations cannot silently pass
        # and never call native SSH/SCP/PowerShell as a fallback.
        classes = [name for name, matches in {
            "copy": argv[0] == boundary.transport.SCP,
            "boot": command.startswith("/usr/bin/cat "),
            "execute": "/bin/bash phase.sh" in command,
            "preflight": "ok=u!=0 and h==h.resolve(strict=True)" in command,
            "mkdir": "umask 077;test ! -e" in command,
            "cleanup-hash": 'cd "$HOME/' in command and "/bin/bash phase.sh" not in command,
            "d2-readback": "/d2-records/lr2.out" in command,
            "live": "ACTIVE_BINDING_OR_ATTEMPT_DRIFT" in command,
            "withdrawal": "WITHDRAWAL_LOCK_UNAVAILABLE" in command,
            "park": "Stop-VM" in command,
            "usage": command == boundary.m8_vm_usage.QUERY,
            "park-boot": command == f'test "$(/usr/bin/cat {boundary._BOOT_FILE})" = '
                                    "01234567-89ab-cdef-0123-456789abcdef",
        }.items() if matches]
        assert len(classes) == 1, f"unclassified/ambiguous fixture request: {classes}"
        if not hasattr(self, "external_calls"):
            self.external_calls = []
        self.external_calls.append(classes[0])
        if "/bin/bash phase.sh" in command:
            remote = command.split('cd "$HOME/', 1)[1].split('"', 1)[0]
            phase = self.staged[remote]
            if phase == "preflight-custody-floor":
                self.events.append(phase)
                script = self.work / "work" / phase / "phase.sh"
                result = execute(script.read_bytes(), self.work)
                kwargs["stdout"].write(result.stdout)
                kwargs["stderr"].write(result.stderr)
                self.contract_executed = True
                return subprocess.CompletedProcess(argv, result.returncode)
        return super().__call__(argv, **kwargs)


def test_whole_m9_composition_executes_contract_pair_and_retains_proof(tmp_path, monkeypatch):
    twin = ContractTwin(monkeypatch, tmp_path)
    path, digest = v2_selection(tmp_path)
    host = boundary.QualificationBoundary(path, digest, tmp_path / "work", target=TARGET,
                                          alias=ALIAS, run=twin)
    assert host.contract_coverage == "selected-literal-source-only"
    cutoff = time.monotonic() + 10
    qualified = host.qualify(cutoff)
    assert twin.contract_executed and twin.events == list(boundary.PHASES)
    assert host.check_live(qualified, cutoff)
    host.withdraw(qualified, cutoff)
    host.park(cutoff)
    host.check_park(cutoff)
    pins = json.loads((tmp_path / "work/preflight-custody-floor/SOURCE-PINS.json").read_bytes())
    assert pins["helper_contract_coverage"] == host.contract_coverage
    assert pins["helper_contract_proofs"][0]["execution"] == "not-executed"
    assert set(twin.external_calls) == {
        "copy", "boot", "execute", "preflight", "mkdir", "cleanup-hash", "d2-readback",
        "live", "withdrawal", "park", "usage", "park-boot",
    }


def test_composition_fixture_has_no_unknown_or_ambiguous_fallback(tmp_path, monkeypatch):
    twin = ContractTwin(monkeypatch, tmp_path)
    for command in ("unclassified", "Stop-VM ACTIVE_BINDING_OR_ATTEMPT_DRIFT"):
        with pytest.raises(AssertionError, match="unclassified/ambiguous"):
            twin(["fake-ssh", command])


@pytest.mark.parametrize("failure", ["transplant", "missing-phase", "empty-inventory"])
def test_v2_composition_refuses_before_work_or_external_call(tmp_path, failure):
    path, _ = v2_selection(tmp_path)
    record = json.loads(path.read_bytes())
    if failure == "transplant":
        script = path.with_name("preflight-custody-floor.sh")
        raw = script.read_bytes().replace(('W_PRIOR=' + PRIOR).encode(),
                                         ('W_PRIOR=' + CURRENT).encode())
        script.write_bytes(raw)
        record["phases"]["preflight-custody-floor"]["script"] = boundary.sha(raw)
    elif failure == "missing-phase":
        del record["helper_contracts"][boundary.CLEANUP]
    else:
        record["helper_contracts"] = {phase: [] for phase in record["helper_contracts"]}
    raw = json_bytes(record)
    path.write_bytes(raw)

    def no_native(*args, **kwargs):
        pytest.fail("contract refusal must precede every external call")

    reason = ("phase preflight-custody-floor:.*binding W_PRIOR declaration"
              if failure == "transplant" else "HELPER_CONTRACT_INVENTORY")
    with pytest.raises((ValueError, package.Refused), match=reason):
        boundary.QualificationBoundary(path, boundary.sha(raw), tmp_path / "work", target=TARGET,
                                       alias=ALIAS, run=no_native)
    assert not (tmp_path / "work").exists()


def test_legacy_coverage_is_explicit(tmp_path):
    path, digest = selected(tmp_path)
    host = boundary.QualificationBoundary(path, digest, tmp_path / "work", target=TARGET,
                                          alias=ALIAS, run=lambda *a, **kw: pytest.fail("native"))
    assert host.contract_coverage == "legacy-unverified"
