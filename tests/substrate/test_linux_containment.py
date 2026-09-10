"""Native OS proofs through the production launcher, never a mock boundary.

The dedicated Linux job makes prerequisites mandatory. Ordinary Windows and
unprovisioned Linux gates explicitly report containment as not exercised.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import select
import signal
import socket
import sys
import threading
import time
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.grants import Posture
from constructicon.core.identity import Digest, digest
from constructicon.core.manifest import CapabilityLease
from constructicon.core.run import RunStatus
from constructicon.core.workspace import acquisition_id_for
from constructicon.substrate.executors import _supervisor, linux
from constructicon.substrate.executors.linux import (
    SUPERVISOR_PATH,
    LinuxLauncher,
    ProcessLimits,
    runtime_digest,
    runtime_inventory,
)
from constructicon.substrate.git.acquisition import (
    AcquisitionClosure,
    AcquisitionPaths,
    acquisition_guard,
    dispose_acquisition,
)
from constructicon.substrate.git.authority import GitAuthority
from tests.gitworld import seed_authority


@pytest.fixture
def launcher():
    location = os.environ.get("M8_LINUX_ROOT")
    if not location or sys.platform != "linux":
        if os.environ.get("M8_CONTAINMENT_REQUIRED"):
            pytest.fail("the required Linux containment environment is missing")
        pytest.skip("Linux containment not exercised: dedicated provisioned lane required")
    root = Path(location)
    policy = Path("/etc/apparmor.d/constructicon-m8-launch")
    pinned = json.loads((root / "runtime.json").read_text())["runtime_digest"]
    return LinuxLauncher(
        runtime_root=root / "runtime", expected_runtime=Digest(pinned),
        bubblewrap=root / "bwrap",
        policy=policy, expected_policy_sha256=hashlib.sha256(policy.read_bytes()).hexdigest(),
    )


def test_runtime_inventory_is_the_digest_input_and_binds_content(tmp_path):
    root = tmp_path / "runtime"
    root.mkdir()
    payload = root / "payload"
    payload.write_bytes(b"first")
    inventory = runtime_inventory(root, require_immutable=False)
    before = runtime_digest(root, require_immutable=False)
    assert before == digest("linux-runtime-root", 1, inventory)
    payload.write_bytes(b"other")
    assert runtime_digest(root, require_immutable=False) != before


@pytest.mark.parametrize("trigger", ["deadline", "request"])
def test_shutdown_has_one_nonrenewable_two_second_grace(monkeypatch, trigger):
    now = [5.0]
    monkeypatch.setattr(_supervisor, "time", SimpleNamespace(monotonic=lambda: now[0]))
    shutdown = _supervisor._Shutdown(10.0)
    assert not shutdown.requested and not shutdown.forced
    if trigger == "deadline":
        now[0] = 10.0
    else:
        shutdown.request()
    assert shutdown.requested and not shutdown.forced
    started = now[0]
    now[0] = started + 1.999
    assert not shutdown.forced
    shutdown.request()
    shutdown.request()
    assert shutdown.started == started
    now[0] = started + 2.0
    assert shutdown.forced


def test_namespace_signals_are_term_then_kill_and_never_host_wide(monkeypatch):
    signals = []
    process_id = [1]
    monkeypatch.setattr(_supervisor, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(_supervisor, "signal", SimpleNamespace(SIGTERM="term", SIGKILL="kill"))
    monkeypatch.setattr(_supervisor, "os", SimpleNamespace(
        getpid=lambda: process_id[0], kill=lambda pid, sig: signals.append((pid, sig)),
    ))
    _supervisor._signal_namespace(False)
    _supervisor._signal_namespace(True)
    assert signals == [(-1, "term"), (-1, "kill")]
    process_id[0] = 2
    with pytest.raises(OSError, match="private PID 1"):
        _supervisor._signal_namespace(False)
    assert len(signals) == 2


@pytest.mark.skipif(sys.platform != "linux", reason="native runtime link topology")
def test_runtime_cannot_execute_a_symlink_target_outside_its_hashed_closure(tmp_path):
    root = tmp_path / "runtime"
    root.mkdir()
    outside = tmp_path / "unhashed-code"
    outside.write_text("untrusted")
    (root / "supervisor").symlink_to(outside)
    with pytest.raises(ContractViolation, match="leaves the immutable closure"):
        runtime_digest(root, require_immutable=False)


@pytest.mark.parametrize("field", [
    "runtime_root", "expected_runtime", "bubblewrap", "policy", "expected_policy_sha256", "limits",
])
def test_launcher_configuration_cannot_change_across_an_await(tmp_path, field):
    launcher = LinuxLauncher(
        runtime_root=tmp_path, expected_runtime=Digest("sha256:" + "1" * 64),
        bubblewrap=tmp_path / "bwrap", policy=tmp_path / "policy",
        expected_policy_sha256="2" * 64,
    )
    with pytest.raises(FrozenInstanceError):
        setattr(launcher, field, getattr(launcher, field))
    changed = replace(launcher, limits=replace(launcher.limits, stdout_bytes=1000))
    assert changed.revision != launcher.revision
    assert launcher.limits.stdout_bytes != changed.limits.stdout_bytes


@pytest.mark.parametrize("termination", ["deadline", "repeated-cancellation"])
async def test_artifact_verification_yields_and_joins_before_return(
    tmp_path, monkeypatch, termination,
):
    # Portable ownership proof, not a substitute for native artifact validation.
    launcher = LinuxLauncher(
        runtime_root=tmp_path, expected_runtime=Digest("sha256:" + "1" * 64),
        bubblewrap=tmp_path / "bwrap", policy=tmp_path / "policy",
        expected_policy_sha256="2" * 64,
    )
    entered, release, finished = (threading.Event() for _ in range(3))

    def slow_verification(_self):
        entered.set()
        try:
            release.wait(2)
        finally:
            finished.set()

    launches = []

    async def unexpected_launch(*args, **kwargs):
        launches.append(args)
        raise AssertionError("expired artifact verification must not launch a child")

    monkeypatch.setattr(LinuxLauncher, "check_artifacts", slow_verification)
    monkeypatch.setattr(LinuxLauncher, "_run", unexpected_launch)
    call = asyncio.create_task(launcher.run(
        ("/usr/bin/python3",), workspace=None, posture=Posture.READ, guard_fds=(0,),
        timeout_s=.05 if termination == "deadline" else 10,
    ))
    try:
        async with asyncio.timeout(3):
            while not entered.is_set():
                await asyncio.sleep(0)
        assert not finished.is_set(), "artifact verification monopolized the event loop"
        if termination == "deadline":
            await asyncio.sleep(.1)
        else:
            call.cancel()
            await asyncio.sleep(0)
            call.cancel()
            await asyncio.sleep(0)
        assert not call.done(), "artifact verification outlived its owner"
        release.set()
        if termination == "deadline":
            result = await call
            assert result.timed_out and result.stdout == b""
        else:
            with pytest.raises(asyncio.CancelledError):
                await call
        assert finished.is_set()
        assert launches == []
    finally:
        release.set()
        await asyncio.gather(call, return_exceptions=True)


async def run(
    launcher, tmp_path, source, *, posture=Posture.READ, stdin=b"", timeout_s=5,
    probe=True,
):
    paths = AcquisitionPaths(tmp_path, acquisition_id_for("lease-os-proof", 1))
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    async with acquisition_guard(paths) as guard:
        if not probe:
            # Independent recipe proof: availability must not mask removal of
            # the very mount/network rule this hostile payload tests.
            launcher.check_artifacts()
            return await launcher._run(
                ("/usr/bin/python3", "-I", "-c", source), workspace=workspace,
                posture=posture, guard_fds=(guard,), stdin=stdin,
                deadline=asyncio.get_running_loop().time() + timeout_s,
            )
        return await launcher.run(
            ("/usr/bin/python3", "-I", "-c", source), workspace=workspace,
            posture=posture, guard_fds=(guard,), stdin=stdin, timeout_s=timeout_s,
        )


async def test_native_namespace_mount_privilege_and_descriptor_table(launcher, tmp_path):
    source = """
import json, os, resource
from pathlib import Path
fds = {}
for value in Path('/proc/self/fd').iterdir():
    try: fds[value.name] = os.readlink(value)
    except FileNotFoundError: pass
try:
    core_fd = os.open('/dev/core', os.O_RDONLY)
except (PermissionError, FileNotFoundError):
    core_denied = True
else:
    os.close(core_fd)
    core_denied = False
print(json.dumps({
    'ns': {n: os.readlink('/proc/self/ns/' + n) for n in ('user','mnt','pid','ipc','uts','net')},
    'profile': Path('/proc/self/attr/current').read_text().strip(),
    'status': Path('/proc/self/status').read_text(), 'fds': fds,
    'uid': os.getuid(), 'gid': os.getgid(), 'home': os.environ['HOME'],
    'sys': Path('/sys').exists(), 'mounts': Path('/proc/self/mountinfo').read_text(),
    'environment': dict(os.environ),
    'uid_map': Path('/proc/self/uid_map').read_text().split(),
    'gid_map': Path('/proc/self/gid_map').read_text().split(),
    'devices': sorted(p.name for p in Path('/dev').iterdir()),
    'core_link': os.readlink('/dev/core'), 'core_denied': core_denied,
    'limits': {name: resource.getrlimit(getattr(resource, 'RLIMIT_' + name))
               for name in ('CORE', 'NOFILE', 'FSIZE', 'AS')},
}))
"""
    result = await run(launcher, tmp_path, source)
    assert result.returncode == 0, result.stderr
    facts = json.loads(result.stdout)
    for name, value in facts["ns"].items():
        assert value != os.readlink(f"/proc/self/ns/{name}")
    assert facts["profile"] == "constructicon-m8-launch//&constructicon-m8-workload (enforce)"
    assert facts["uid"] == os.getuid() and facts["gid"] == os.getgid()
    assert "NoNewPrivs:\t1" in facts["status"]
    assert "CapEff:\t0000000000000000" in facts["status"]
    assert set(facts["fds"]) == {"0", "1", "2"}
    assert facts["sys"] is False and facts["home"] == "/tmp/home"
    assert set(facts["environment"]) <= {"HOME", "PATH", "LANG", "PWD", "LC_CTYPE"}
    assert " shared:" not in facts["mounts"]
    # --dev introduces an intermediate user namespace; parent-side zero is
    # not host root. These are single-ID maps, not a host identity range.
    assert facts["uid_map"] == [str(os.getuid()), "0", "1"]
    assert facts["gid_map"] == [str(os.getgid()), "0", "1"]
    assert set(facts["devices"]) == {
        "core", "fd", "full", "null", "ptmx", "pts", "random", "shm",
        "stderr", "stdin", "stdout", "tty", "urandom", "zero",
    }
    # bubblewrap 0.9.0 emits this legacy alias; presence is not access.
    assert facts["core_link"] == "/proc/kcore" and facts["core_denied"] is True
    assert facts["limits"] == {
        "CORE": [0, 0], "NOFILE": [256, 256], "FSIZE": [134217728, 134217728],
        "AS": [2147483648, 2147483648],
    }
    evidence = os.environ.get("M8_EVIDENCE_DIRECTORY")
    if evidence:
        directory = Path(evidence)
        directory.mkdir(parents=True, exist_ok=True)
        # This is the explicit child projection above, never the host's env.
        (directory / "boundary.json").write_text(json.dumps(facts, sort_keys=True) + "\n")


@pytest.mark.parametrize("operation", [
    "p.write_text('changed')", "p.chmod(0o777); p.write_text('changed')",
    "p.rename('/workspace/renamed')", "p.unlink()",
    "Path('/workspace/new').symlink_to('/outside')",
    "subprocess.run(['/usr/bin/python3', '-c', "
    "\"open('/workspace/sentinel','w').write('changed')\"], check=True)",
])
async def test_read_writes_fail_physically_and_leave_the_snapshot_exact(
    launcher, tmp_path, operation,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sentinel = workspace / "sentinel"
    sentinel.write_text("unchanged")
    source = f"""
import subprocess
from pathlib import Path
p = Path('/workspace/sentinel')
try:
    {operation}
except (OSError, subprocess.CalledProcessError):
    print('denied')
else:
    print('WRITE ESCAPED')
"""
    result = await run(launcher, tmp_path, source)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == b"denied"
    assert sentinel.read_text() == "unchanged"
    assert sorted(p.name for p in workspace.iterdir()) == ["sentinel"]


async def test_write_changes_only_its_explicit_workspace(launcher, tmp_path):
    outside = tmp_path / "authority-sentinel"
    outside.write_text("protected")
    source = f"""
from pathlib import Path
Path('/workspace/change').write_text('owned')
assert not Path({str(outside)!r}).exists()
assert not Path('/workspace/authority-sentinel').exists()
print('confined')
"""
    result = await run(launcher, tmp_path, source, posture=Posture.WRITE)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == b"confined"
    assert (tmp_path / "workspace/change").is_file(), "write escaped its selected workspace"
    assert (tmp_path / "workspace/change").read_text() == "owned"
    assert outside.read_text() == "protected"


@pytest.mark.parametrize("shape", ["line", "many", "stderr", "stdin"])
async def test_output_and_blocked_input_are_bounded_without_deadlock(launcher, tmp_path, shape):
    launcher = replace(launcher, limits=ProcessLimits(
        input_bytes=1024 * 1024, stdout_bytes=4096, record_bytes=1024, stderr_bytes=512,
    ))
    source = {
        "line": "import os; os.write(1,b'x'*8192)",
        "many": "import os; os.write(1,b'x\\n'*8192)",
        "stderr": "import os; os.write(2,b'x'*1000000); print('finished')",
        "stdin": "import time; print('waiting',flush=True); time.sleep(100)",
    }[shape]
    result = await run(launcher, tmp_path, source, stdin=b"s" * 1024 * 1024, timeout_s=1)
    assert len(result.stdout) <= 4096 and len(result.stderr) <= 512
    if shape in {"line", "many"}:
        assert result.bound_exceeded is not None
    elif shape == "stdin":
        assert result.timed_out and result.stdout.strip() == b"waiting"
    else:
        assert result.returncode == 0 and result.stdout.strip() == b"finished"


@pytest.mark.parametrize("ending", ["return", "timeout", "cancel"])
async def test_detached_descendants_cannot_hold_pipes_or_write_after_completion(
    launcher, tmp_path, ending,
):
    source = f"""
import os, signal, time
if os.fork() == 0:
    os.setsid()
    if os.fork(): os._exit(0)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    with open('/workspace/descendant', 'w') as stream:
        while True:
            stream.write('x'); stream.flush(); time.sleep(.01)
while not os.path.exists('/workspace/descendant'): time.sleep(.001)
print('ready',flush=True)
{'time.sleep(100)' if ending != 'return' else ''}
"""
    task = asyncio.create_task(run(
        launcher, tmp_path, source, posture=Posture.WRITE,
        timeout_s=1 if ending == "timeout" else 5,
    ))
    if ending == "cancel":
        async with asyncio.timeout(10):
            while not (tmp_path / "workspace/descendant").exists():
                await asyncio.sleep(.01)
        task.cancel()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        result = await asyncio.wait_for(task, 10)
        assert result.timed_out == (ending == "timeout"), result.stderr
        if ending == "return":
            assert result.returncode == 0, result.stderr
    before = (tmp_path / "workspace/descendant").read_bytes()
    await asyncio.sleep(.1)
    assert (tmp_path / "workspace/descendant").read_bytes() == before


@pytest.mark.parametrize("ending", ["timeout", "cancel", "bound"])
async def test_term_grace_flushes_cooperative_output_before_cleanup(launcher, tmp_path, ending):
    source = """
import os, signal, time
from pathlib import Path
def stop(signum, frame):
    time.sleep(.15)
    os.write(2, b'cooperative shutdown\\n')
    Path('/workspace/flushed').write_text('done')
    os._exit(0)
signal.signal(signal.SIGTERM, stop)
Path('/workspace/ready').touch()
print('ready', flush=True)
""" + ("while True: os.write(1, b'x'*8192)" if ending == "bound" else "time.sleep(100)")
    if ending == "bound":
        launcher = replace(launcher, limits=replace(launcher.limits, record_bytes=1024))
    task = asyncio.create_task(run(
        launcher, tmp_path, source, posture=Posture.WRITE,
        timeout_s=1 if ending == "timeout" else 10,
    ))
    try:
        if ending == "cancel":
            async with asyncio.timeout(5):
                while not (tmp_path / "workspace/ready").exists():
                    assert not task.done(), "cooperative workload did not start"
                    await asyncio.sleep(.01)
            task.cancel()
            await asyncio.sleep(.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            result = await asyncio.wait_for(task, 8)
            assert b"cooperative shutdown" in result.stderr
            assert result.timed_out == (ending == "timeout")
            if ending == "bound":
                assert result.bound_exceeded == "record"
            else:
                assert result.elapsed_s >= 1.1  # Includes actual cooperative cleanup.
        assert (tmp_path / "workspace/flushed").read_text() == "done"
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_term_ignoring_workload_gets_only_the_fixed_grace(launcher, tmp_path):
    result = await run(launcher, tmp_path, """
import signal, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
print('ready', flush=True)
time.sleep(100)
""", timeout_s=1)
    assert result.stdout.strip() == b"ready" and result.timed_out
    assert 2.9 <= result.elapsed_s < 5


async def test_namespace_init_private_descriptors_cannot_be_opened_by_the_payload(
    launcher, tmp_path,
):
    result = await run(launcher, tmp_path, """
import os
from pathlib import Path
assert os.getppid() == 1
try:
    list(Path('/proc/1/fd').iterdir())
except PermissionError:
    print('private init descriptors')
else:
    raise AssertionError('workload may inspect namespace init descriptors')
""")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == b"private init descriptors"


async def test_runtime_drift_refuses_before_any_child_starts(launcher, tmp_path):
    launcher = replace(launcher, expected_runtime=Digest("sha256:" + "0" * 64))
    with pytest.raises(Exception, match="runtime content differs"):
        await run(launcher, tmp_path, "print('must not launch')")


async def test_supervisor_source_is_loaded_only_from_the_immutable_closure(
    launcher, tmp_path, monkeypatch,
):
    commands = []
    spawn = asyncio.create_subprocess_exec

    async def observe(*args, **kwargs):
        commands.append(args)
        return await spawn(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", observe)
    result = await run(launcher, tmp_path, "print('done')")
    assert result.returncode == 0, result.stderr
    assert len(commands) == 2  # Physical probe and requested payload.
    for args in commands:
        assert str(launcher.root / SUPERVISOR_PATH) in args
        assert not any(value.endswith("executors/_supervisor.py") for value in args)
    script = launcher.root / SUPERVISOR_PATH
    assert script.stat().st_uid == 0 and not script.stat().st_mode & 0o222
    with pytest.raises(PermissionError):
        script.open("ab")


@pytest.mark.parametrize("phase", ["probe", "spawn"])
async def test_the_call_deadline_includes_probe_and_spawn(launcher, tmp_path, monkeypatch, phase):
    """Delay a real operation, not a fake process or a fake isolation result."""
    if phase == "probe":
        probe = launcher.probe

        async def delayed_probe(_self, *, deadline=None):
            await asyncio.sleep(1.5)
            await probe(deadline=deadline)

        monkeypatch.setattr(LinuxLauncher, "probe", delayed_probe)
    else:
        spawn = asyncio.create_subprocess_exec
        calls = 0

        async def delayed_spawn(*args, **kwargs):
            nonlocal calls
            calls += 1
            process = await spawn(*args, **kwargs)
            if calls == 2:
                # The OS child exists, but Python has not returned its handle.
                # Expiry must close its owner pipe even in this interval.
                await asyncio.sleep(2.5)
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed_spawn)
    started = time.monotonic()
    result = await run(
        launcher, tmp_path,
        "import time; time.sleep(1.5); open('/workspace/started','w').write('bad')",
        posture=Posture.WRITE, timeout_s=.2 if phase == "probe" else 1,
    )
    elapsed = time.monotonic() - started
    assert result.timed_out, "setup was outside the requested deadline"
    assert not (tmp_path / "workspace/started").exists(), "an expired call launched its payload"
    assert abs(result.elapsed_s - elapsed) < .1, "telemetry omitted setup or owned cleanup"
    if phase == "probe":
        assert elapsed < 1, "the call waited for an independent availability deadline"


async def test_successful_call_elapsed_time_includes_availability(launcher, tmp_path, monkeypatch):
    probe = launcher.probe
    physical_run = launcher._run
    probe_elapsed = 0.0
    payloads = []

    async def delayed_probe(_self, *, deadline=None):
        nonlocal probe_elapsed
        started = time.monotonic()
        await asyncio.sleep(.2)
        await probe(deadline=deadline)
        probe_elapsed = time.monotonic() - started

    async def observed_run(_self, *args, **kwargs):
        result = await physical_run(*args, **kwargs)
        if kwargs.get("workspace") is not None:
            payloads.append(result)
        return result

    monkeypatch.setattr(LinuxLauncher, "probe", delayed_probe)
    monkeypatch.setattr(LinuxLauncher, "_run", observed_run)
    result = await run(launcher, tmp_path, "print('complete')")
    assert result.returncode == 0 and result.stdout.strip() == b"complete", result.stderr
    assert len(payloads) == 1 and probe_elapsed >= .2
    assert result.elapsed_s >= probe_elapsed + payloads[0].elapsed_s


async def test_payload_waits_for_controller_ownership_of_the_real_spawn_handle(
    launcher, tmp_path, monkeypatch,
):
    spawn = asyncio.create_subprocess_exec
    calls = 0
    escaped = None

    async def held_spawn(*args, **kwargs):
        nonlocal calls, escaped
        calls += 1
        process = await spawn(*args, **kwargs)
        if calls == 2:
            await asyncio.sleep(.3)
            escaped = (tmp_path / "workspace/started").exists()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", held_spawn)
    result = await run(
        launcher, tmp_path, "open('/workspace/started','w').write('owned')",
        posture=Posture.WRITE,
    )
    assert escaped is False, "payload began while the spawn handle was still unowned"
    assert result.returncode == 0 and (tmp_path / "workspace/started").read_text() == "owned"


async def test_reaper_enforces_expiry_while_the_controller_event_loop_is_stalled(
    launcher, tmp_path,
):
    source = """
from pathlib import Path
import time
Path('/workspace/ready').touch()
time.sleep(1.5)
Path('/workspace/expired-write').touch()
time.sleep(100)
"""
    task = asyncio.create_task(run(
        launcher, tmp_path, source, posture=Posture.WRITE, timeout_s=1,
    ))
    try:
        async with asyncio.timeout(10):
            while not (tmp_path / "workspace/ready").exists():
                assert not task.done(), "the real payload never reached its barrier"
                await asyncio.sleep(.01)
        # Intentional: asyncio cannot deliver cancellation in this interval.
        # Only the separate reaper can stop the actual payload before its write.
        time.sleep(2.5)
        assert not (tmp_path / "workspace/expired-write").exists(), (
            "a stalled controller let a payload outlive its authority"
        )
        result = await asyncio.wait_for(task, 5)
        assert result.timed_out
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.skipif(sys.platform != "linux", reason="real Linux owner-pipe event semantics")
def test_buffered_start_does_not_authorize_launch_after_observed_owner_death(monkeypatch):
    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"\x01")
    os.close(write_fd)
    child = os.fork()
    if child == 0:
        # The native fork inherits the real implementation (and a code-object
        # mutant). Observe whether Popen is reached, without racing a payload
        # against the subsequent kill or replacing Linux's poll/read behavior.
        try:
            monkeypatch.setattr(_supervisor.subprocess, "Popen", lambda *a, **kw: os._exit(91))
            code = _supervisor.supervise(
                read_fd, time.monotonic() + 1, ["must-not-start", "--", "payload"],
            )
        except BaseException:
            os._exit(92)
        os._exit(code)
    os.close(read_fd)
    reaped = False
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            pid, status = os.waitpid(child, os.WNOHANG)
            if pid:
                reaped = True
                code = os.waitstatus_to_exitcode(status)
                if code == 92:
                    raise RuntimeError("native supervisor test failed before its observation")
                assert code == 125, (
                    "buffered start plus POLLHUP reached process creation"
                )
                break
            time.sleep(.01)
        if not reaped:
            raise TimeoutError("native supervisor test exceeded its observation bound")
    finally:
        if not reaped:
            os.kill(child, signal.SIGKILL)
            os.waitpid(child, 0)


async def test_probe_reaper_uses_the_call_deadline_when_the_controller_stalls(
    launcher, tmp_path, monkeypatch,
):
    # Extend a real physical probe after it emits its namespace observation.
    # Its private stdout and a pidfd provide barriers without a workspace mount.
    monkeypatch.setattr(linux, "_PROBE", linux._PROBE + (
        "\nimport sys, time\nsys.stdout.flush()\ntime.sleep(100)\n"
    ))
    observed = asyncio.Event()
    lifetime_fd = None
    spawn = asyncio.create_subprocess_exec

    async def observe_spawn(*args, **kwargs):
        nonlocal lifetime_fd
        process = await spawn(*args, **kwargs)
        lifetime_fd = os.pidfd_open(process.pid)
        read = process.stdout.read

        async def observe_read(n):
            data = await read(n)
            if data:
                observed.set()
            return data

        monkeypatch.setattr(process.stdout, "read", observe_read)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", observe_spawn)
    task = asyncio.create_task(run(launcher, tmp_path, "print('must not start')", timeout_s=1))
    try:
        await asyncio.wait_for(observed.wait(), 5)
        assert lifetime_fd is not None
        poller = select.poll()
        poller.register(lifetime_fd, select.POLLIN)
        time.sleep(2)
        assert poller.poll(0), "probe outlived the caller deadline while asyncio was stalled"
        result = await asyncio.wait_for(task, 5)
        assert result.timed_out and result.stdout == b""
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if lifetime_fd is not None:
            os.close(lifetime_fd)


async def test_controller_dies_while_a_real_setup_child_holds_the_guard(launcher, tmp_path):
    authority = GitAuthority(seed_authority(tmp_path / "git"), tmp_path / "legacy")
    closure = AcquisitionClosure(authority)
    paths = AcquisitionPaths(tmp_path / "owned", acquisition_id_for("lease-owner-death", 1))
    owner = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "tests.substrate._linux_owner", str(paths.root), "setup",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    reaper = None
    cleanup = None
    try:
        line = await asyncio.wait_for(owner.stdout.readline(), 15)
        assert line, f"setup owner failed: {await owner.stderr.read()!r}"
        reaper = json.loads(line)["reaper"]
        os.kill(reaper, signal.SIGSTOP)
        children = Path(f"/proc/{reaper}/task/{reaper}/children").read_text().split()
        assert children == [], "payload started before controller acquired the spawn handle"
        owner.kill()
        await owner.wait()
        cleanup = asyncio.create_task(dispose_acquisition(closure, paths))
        async with asyncio.timeout(5):
            while not closure.is_closed(paths):
                await asyncio.sleep(.01)
        await asyncio.sleep(.05)
        assert not cleanup.done(), "setup child did not retain its inherited guard"
        assert not (paths.payload / "live").exists()
        os.kill(reaper, signal.SIGCONT)
        reaper = None
        assert await asyncio.wait_for(cleanup, 10)
        assert not paths.payload.exists() and paths.guard.is_file()
        await asyncio.sleep(.1)
        assert not paths.payload.exists(), "an abandoned setup later launched a producer"
    finally:
        if reaper is not None:
            os.kill(reaper, signal.SIGCONT)
        if owner.returncode is None:
            owner.kill()
        await owner.wait()
        if cleanup is not None:
            await cleanup


async def test_controller_death_cannot_release_the_reapers_guard_before_quiescence(
    launcher, tmp_path,
):
    authority = GitAuthority(seed_authority(tmp_path / "git"), tmp_path / "legacy")
    closure = AcquisitionClosure(authority)
    paths = AcquisitionPaths(tmp_path / "owned", acquisition_id_for("lease-owner-death", 1))
    fresh = AcquisitionPaths(tmp_path / "owned", acquisition_id_for("lease-owner-death", 2))
    fresh.payload.mkdir(parents=True)
    (fresh.payload / "untouched").write_text("new epoch")
    owner = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "tests.substrate._linux_owner", str(paths.root),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    reaper = None
    cleanup = None
    try:
        async with asyncio.timeout(15):
            while not (paths.payload / "live").exists():
                if owner.returncode is not None:
                    pytest.fail(f"owner failed before launch: {await owner.stderr.read()!r}")
                await asyncio.sleep(.01)
        children = Path(f"/proc/{owner.pid}/task/{owner.pid}/children").read_text().split()
        assert len(children) == 1
        reaper = int(children[0])
        os.kill(reaper, signal.SIGSTOP)
        owner.kill()
        await owner.wait()
        cleanup = asyncio.create_task(dispose_acquisition(closure, paths))
        # Observe the durable fence rather than assuming when cleanup ran.
        async with asyncio.timeout(5):
            while not closure.is_closed(paths):
                await asyncio.sleep(.01)
        await asyncio.sleep(.05)
        assert not cleanup.done(), "controller death released a still-live child's guard"
        assert (paths.payload / "live").exists()
        os.kill(reaper, signal.SIGCONT)
        reaper = None
        assert await asyncio.wait_for(cleanup, 10)
        assert not paths.payload.exists() and paths.guard.is_file()
        assert closure.is_closed(paths) and not closure.is_closed(fresh)
        assert (fresh.payload / "untouched").read_text() == "new epoch"
        await asyncio.sleep(.1)
        assert not paths.payload.exists(), "old producer recreated a disposed acquisition"
    finally:
        if reaper is not None:
            os.kill(reaper, signal.SIGCONT)
        if owner.returncode is None:
            owner.kill()
        await owner.wait()
        if cleanup is not None:
            await cleanup


async def test_host_files_sockets_and_inheritable_descriptors_are_absent(launcher, tmp_path):
    sentinel = tmp_path / "host-private"
    sentinel.write_text("host-only-secret")
    fd = os.open(sentinel, os.O_RDONLY)
    os.set_inheritable(fd, True)
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(tmp_path / "host-service.sock"))
    server.listen()
    source = f"""
import os, socket
from pathlib import Path
assert not Path({str(sentinel)!r}).exists()
assert not Path({str(tmp_path / 'host-service.sock')!r}).exists()
assert not Path('/proc/{os.getpid()}/root').exists()
for value in Path('/proc/self/fd').iterdir():
    try: target = os.readlink(value)
    except FileNotFoundError: continue
    assert 'host-private' not in target and 'host-service' not in target
assert not Path('/dev/tty').exists() or not os.isatty(0)
print('absent')
"""
    try:
        result = await run(launcher, tmp_path, source, probe=False)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == b"absent"
        assert sentinel.read_text() == "host-only-secret"
    finally:
        server.close()
        os.close(fd)


async def test_child_and_grandchild_cannot_reach_the_host_loopback_service(launcher, tmp_path):
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    port = server.getsockname()[1]
    source = f"""
import os, socket
def denied():
    with socket.socket() as stream:
        stream.settimeout(.2)
        try: stream.connect(('127.0.0.1', {port}))
        except OSError: return True
        return False
assert denied()
pid = os.fork()
if pid == 0: os._exit(0 if denied() else 9)
assert os.waitpid(pid, 0)[1] == 0
print('network denied')
"""
    try:
        result = await run(launcher, tmp_path, source, probe=False)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == b"network denied"
        server.setblocking(False)
        with pytest.raises(BlockingIOError):
            server.accept()
    finally:
        server.close()


async def test_workspace_symlink_cannot_enlarge_the_mount(launcher, tmp_path):
    outside = tmp_path / "protected"
    outside.write_text("unchanged")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "escape").symlink_to(outside)
    source = """
from pathlib import Path
try: Path('/workspace/escape').write_text('escaped')
except OSError: print('denied')
else: print('escaped')
"""
    result = await run(launcher, tmp_path, source, posture=Posture.WRITE)
    assert result.returncode == 0 and result.stdout.strip() == b"denied", result.stderr
    assert outside.read_text() == "unchanged"


async def test_instruction_and_argv_metacharacters_are_only_data(launcher, tmp_path):
    values = ("--help", "quotes'\"", "$(touch escaped)", "one\ntwo", "unicode:\u2603")
    source = "import json,sys; print(json.dumps([sys.argv[1:],sys.stdin.read()]))"
    paths = AcquisitionPaths(tmp_path, acquisition_id_for("lease-argv", 1))
    async with acquisition_guard(paths) as guard:
        result = await launcher.run(
            ("/usr/bin/python3", "-I", "-c", source, *values), workspace=None,
            posture=Posture.READ, guard_fds=(guard,), stdin="\n".join(values).encode(), timeout_s=5,
        )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [list(values), "\n".join(values)]


async def test_missing_profile_attachment_refuses_before_the_requested_payload(launcher, tmp_path):
    launcher = replace(launcher, bubblewrap=launcher.bubblewrap.with_name("unprofiled-bwrap"))
    with pytest.raises(Exception, match="physical Linux launch probe failed"):
        await run(launcher, tmp_path, "open('/workspace/backend-started','w').write('bad')")
    assert not (tmp_path / "workspace/backend-started").exists()


@pytest.mark.parametrize("phase", ["before_record", "after_record", "during_materialization"])
async def test_real_controller_death_on_both_sides_of_the_durable_lease(launcher, tmp_path, phase):
    from constructicon.api.control import ControlPlane
    from tests.substrate._lease_owner import assemble

    seed_authority(tmp_path)
    owner = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "tests.substrate._lease_owner", str(tmp_path), phase,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        line = await asyncio.wait_for(owner.stdout.readline(), 20)
        if not line:
            pytest.fail(f"controller did not reach its seam: {await owner.stderr.read()!r}")
        event = json.loads(line)
        assert event["phase"] == phase
        row = CapabilityLease.model_validate(event["lease"])
        old = AcquisitionPaths(tmp_path / "owned", acquisition_id_for(
            row.lease_id, row.acquisition_epoch,
        ))
        assert old.payload.exists() == (phase == "during_materialization")
        if phase == "before_record":
            assert not old.root.exists()
        owner.kill()
        await owner.wait()
        system, journal, provider = assemble(tmp_path, "successor-controller")
        retained = journal.capability_leases(row.run_id)
        assert len(retained) == (0 if phase == "before_record" else 1)
        if retained:
            assert retained[0].resource_ref == row.resource_ref
        async with asyncio.timeout(5):
            while journal.run_state(row.run_id).liveness != "lost":
                await asyncio.sleep(.01)
        control = ControlPlane(system=system, store=journal)
        await control.startup()
        try:
            async with asyncio.timeout(15):
                while journal.run_state(row.run_id).status not in (
                    RunStatus.SUCCEEDED, RunStatus.FAILED,
                ):
                    await asyncio.sleep(.01)
            assert journal.run_state(row.run_id).status is RunStatus.SUCCEEDED
            assert not old.payload.exists()
            assert provider.closure.is_closed(old) == (phase != "before_record")
            rows = journal.capability_leases(row.run_id)
            assert all(item.state == "closed" for item in rows)
            assert max(item.acquisition_epoch for item in rows) > row.acquisition_epoch
        finally:
            await control.shutdown()
    finally:
        if owner.returncode is None:
            owner.kill()
        await owner.wait()
