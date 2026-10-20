"""Portable evidence/refusal tests; no AppArmor or physical result is fabricated."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.ci import prove_m8_noexec as proof


def result(output: bytes, code: int = 0, stderr: bytes = b"") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["fixed-fixture"], code, output, stderr)


def test_affirmative_complete_transcript_is_accepted() -> None:
    proof.exact(result(proof.expected_transcript()), 0, proof.expected_transcript())


@pytest.mark.parametrize("index", range(len(proof.expected_transcript().splitlines())))
@pytest.mark.parametrize("mutation", ["missing", "different", "duplicate"])
def test_every_published_observation_is_required(index: int, mutation: str) -> None:
    rows = proof.expected_transcript().splitlines(keepends=True)
    if mutation == "missing":
        del rows[index]
    elif mutation == "different":
        rows[index] = b"unknown\n"
    else:
        rows.insert(index, rows[index])
    with pytest.raises(ValueError, match="affirmative evidence"):
        proof.exact(result(b"".join(rows)), 0, proof.expected_transcript())


@pytest.mark.parametrize("operation", (*proof.OPERATIONS, "child-errno"))
@pytest.mark.parametrize("wrong_errno", ["0", "1", "2", "8", "38"])
def test_only_exact_eacces_counts_as_execution_denial(operation: str, wrong_errno: str) -> None:
    expected = proof.expected_transcript()
    poisoned = expected.replace(
        f"{operation}:13\n".encode(), f"{operation}:{wrong_errno}\n".encode(),
    )
    assert poisoned != expected
    with pytest.raises(ValueError, match="affirmative evidence"):
        proof.exact(result(poisoned), 0, expected)


@pytest.mark.parametrize("code,stderr", [(1, b""), (-9, b""), (0, b"warning")])
def test_clean_exact_process_result_is_required(code: int, stderr: bytes) -> None:
    with pytest.raises(ValueError):
        proof.exact(
            result(proof.expected_transcript(), code, stderr), 0, proof.expected_transcript(),
        )


@pytest.mark.parametrize("operation", proof.OPERATIONS)
def test_execution_control_requires_success_and_its_own_label(operation: str) -> None:
    expected = f"control-label:unconfined\nattempt:{operation}\n".encode()
    proof.exact(result(expected), 0, expected)
    with pytest.raises(ValueError, match="exit mismatch"):
        proof.exact(result(expected, 94), 0, expected)
    with pytest.raises(ValueError, match="affirmative evidence"):
        proof.exact(result(expected.replace(b"unconfined", b"unknown")), 0, expected)


def profiles() -> str:
    names = ("launch", "payload", "missing")
    return "\n".join(proof.PREFIX + name + " (enforce)" for name in names)


def test_exact_profile_set_proves_target_absence() -> None:
    proof.validate_profiles("unrelated (enforce)\n", present=False)
    proof.validate_profiles(profiles() + "\nunrelated (enforce)", present=True)
    with pytest.raises(ValueError, match="profile presence"):
        proof.validate_profiles(profiles(), present=False)


@pytest.mark.parametrize("mutation", ["missing", "complain", "absent-target-exists", "extra"])
def test_profile_absence_or_wrong_mode_never_qualifies(mutation: str) -> None:
    observed = profiles()
    if mutation == "missing":
        observed = observed.replace(proof.LABEL, "")
    elif mutation == "complain":
        observed = observed.replace("(enforce)", "(complain)")
    elif mutation == "absent-target-exists":
        observed += "\n" + proof.PREFIX + "absent (enforce)"
    else:
        observed += "\n" + proof.PREFIX + "unexpected (enforce)"
    with pytest.raises(ValueError, match="profile presence"):
        proof.validate_profiles(observed, present=True)


@pytest.mark.parametrize("code,output", [(0, b""), (77, b"initial-exec-refused:2\n"),
                                        (77, b"initial-exec-refused:13\nbefore:unconfined\n")])
def test_absent_profile_control_is_a_specific_initial_exec_refusal(
    code: int, output: bytes,
) -> None:
    with pytest.raises(ValueError):
        proof.exact(result(output, code), 77, b"initial-exec-refused:13\n")


def test_unsupported_host_refuses_before_creating_any_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(ValueError, match="requires Linux"):
        proof.prove()


def test_failed_physical_proof_does_not_publish_passing_facts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["proof"])

    def failed() -> dict:
        raise ValueError("sentinel private runtime detail")

    monkeypatch.setattr(proof, "prove", failed)
    assert proof.main() == 1
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        "scope": "standalone_fake_no_further_exec_only", "passed": False,
    }
    assert output.err == ""


def test_policy_scope_and_ci_are_standalone() -> None:
    root = Path(__file__).resolve().parents[1]
    policy = (root / "scripts/ci/constructicon-m8-noexec.apparmor").read_text()
    transition = "allow px /opt/constructicon-m8-noexec/payload -> "
    assert transition + "constructicon-m8-noexec-payload," in policy
    assert transition + "constructicon-m8-noexec-absent," in policy
    assert "deny x /**," in policy
    assert "allow file rwlkm /{**,}," in policy  # Deliberate same-process authority remains.
    assert "profile constructicon-m8-noexec-absent " not in policy
    assert not any(fallback in policy for fallback in ("pux", "pix", " ux ", " ix "))
    workflow = (root / ".github/workflows/m8-containment.yml").read_text()
    step = workflow.split("- name: Prove standalone fake no-further-exec feasibility", 1)[1].split(
        "- name:", 1,
    )[0]
    assert "if: matrix.lane == 'foundation'" in step
    assert "scripts/ci/prove_m8_noexec.py" in step
    assert "</dev/null" in step
    assert "${{ runner.temp }}/m8-noexec.json" in workflow


def test_fixed_byte_exchange_runs_a_real_process() -> None:
    source = "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"
    observed = proof.run(
        [sys.executable, "-I", "-c", source], b"ping\n",
    )
    proof.exact(observed, 0, b"ping\n")


@pytest.mark.parametrize("interrupted", [False, True], ids=["deadline", "interruption"])
def test_process_is_killed_and_joined_on_incomplete_exchange(
    monkeypatch: pytest.MonkeyPatch, interrupted: bool,
) -> None:
    original_popen = subprocess.Popen
    processes: list[subprocess.Popen] = []

    def spawn(*args, **kwargs):
        child = original_popen(*args, **kwargs)
        processes.append(child)
        if interrupted:
            communicate = child.communicate

            def first_call(*_args, **_kwargs):
                child.communicate = communicate
                raise InterruptedError("fixture interrupt")

            child.communicate = first_call
        return child

    monkeypatch.setattr(proof.subprocess, "Popen", spawn)
    monkeypatch.setattr(proof, "TIMEOUT_S", 0.1)
    if sys.platform != "linux":
        # Substitute only the unavailable group-kill primitive; the actual
        # subprocess, interrupted/expired exchange and join all still run.
        monkeypatch.setattr(proof.signal, "SIGKILL", 9, raising=False)

        def kill_group(pid: int, _signal: int) -> None:
            assert processes[0].pid == pid
            processes[0].kill()

        monkeypatch.setattr(proof.os, "killpg", kill_group, raising=False)
    error = InterruptedError if interrupted else subprocess.TimeoutExpired
    with pytest.raises(error):
        proof.run([sys.executable, "-I", "-c", "import time; time.sleep(60)"])
    assert len(processes) == 1 and processes[0].returncode is not None


@pytest.fixture
def provisioning(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Substitute OS provisioning only, retaining actual exclusive files/cleanup.

    These are orchestration tests; their synthetic observations are never
    exported as physical evidence.
    """
    root = tmp_path / "owned-proof"
    policies = tmp_path / "profiles"
    policies.write_text("")
    monkeypatch.setattr(proof, "ROOT", root)
    monkeypatch.setattr(proof, "POLICIES", policies)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "github-hosted")
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(os, "chown", lambda *_: None, raising=False)
    monkeypatch.setitem(sys.modules, "pwd", SimpleNamespace(
        getpwnam=lambda _: SimpleNamespace(pw_uid=1001, pw_gid=1001),
    ))
    original_read = Path.read_text
    original_stat = Path.stat
    if os.name == "nt":
        # Windows mode bits do not implement the Linux owner/mode primitive.
        monkeypatch.setattr(Path, "chmod", lambda *_args, **_kwargs: None)

    def read(path, *args, **kwargs):
        if path == Path("/sys/module/apparmor/parameters/enabled"):
            return "Y\n"
        return original_read(path, *args, **kwargs)

    def stat(path, *args, **kwargs):
        observed = original_stat(path, *args, **kwargs)
        if path == root:
            fields = list(observed)
            fields[4] = 0
            fields[0] &= ~0o022
            return os.stat_result(fields)
        return observed

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(Path, "stat", stat)
    events = []
    failures = set()

    def command(argv, data=None):
        if argv[0] == "/usr/bin/cc":
            Path(argv[-1]).write_bytes(b"compiled fixture substitute")
        elif argv[0] == "/usr/sbin/apparmor_parser":
            operation = argv[1]
            events.append(operation)
            if operation == "--add":
                policies.write_text(profiles())
            elif operation == "--remove" and operation not in failures:
                policies.write_text("")
            if operation in failures:
                return result(b"", 1)
        elif argv[0] == "/usr/bin/sudo":
            if argv[-1] in proof.OPERATIONS:
                operation = argv[-1]
                return result(f"control-label:unconfined\nattempt:{operation}\n".encode())
            if argv[-1] == str(root / "missing-launch"):
                return result(b"initial-exec-refused:13\n", 77)
            assert argv[-1] == str(root / "launch") and data == b"ping\n"
            events.append("joined-fixture")
            (root / "fake-store").write_bytes(b"b")
            return result(proof.expected_transcript())
        else:
            pytest.fail("unexpected provisioning command")
        return result(b"")

    monkeypatch.setattr(proof, "run", command)
    return root, policies, events, failures


def test_orchestration_publishes_only_after_its_owned_cleanup(provisioning) -> None:
    root, policies, events, _failures = provisioning
    report = proof.prove()
    assert events == ["--add", "joined-fixture", "--remove"]
    assert not root.exists() and policies.read_text() == ""
    assert report["cleanup_complete"] is True
    assert report["production_available"] is False and report["claude_qualified"] is False


def test_preexisting_fixture_is_never_removed_or_overwritten(provisioning) -> None:
    root, _policies, events, _failures = provisioning
    root.mkdir()
    sentinel = root / "retained"
    sentinel.write_bytes(b"prior owner")
    with pytest.raises(FileExistsError):
        proof.prove()
    assert sentinel.read_bytes() == b"prior owner" and events == []


def test_partial_profile_load_is_removed_before_owned_files(provisioning) -> None:
    root, policies, events, failures = provisioning
    failures.add("--add")
    with pytest.raises(ValueError, match="exit mismatch"):
        proof.prove()
    assert events == ["--add", "--remove"]
    assert not root.exists() and policies.read_text() == ""


def test_cleanup_failure_is_not_success_or_file_removal(provisioning) -> None:
    root, policies, events, failures = provisioning
    failures.add("--remove")
    with pytest.raises(ValueError, match="exit mismatch"):
        proof.prove()
    assert events == ["--add", "joined-fixture", "--remove"]
    assert root.exists() and policies.read_text() == profiles()
