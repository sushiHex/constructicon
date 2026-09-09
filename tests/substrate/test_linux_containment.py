"""Native OS proofs through the production launcher, never a mock boundary.

The dedicated Linux job makes prerequisites mandatory. Ordinary Windows and
unprovisioned Linux gates explicitly report containment as not exercised.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

from constructicon.core.grants import Posture
from constructicon.core.identity import Digest
from constructicon.core.workspace import acquisition_id_for
from constructicon.substrate.executors.linux import LinuxLauncher, ProcessLimits
from constructicon.substrate.git.acquisition import AcquisitionPaths, acquisition_guard


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


async def run(launcher, tmp_path, source, *, posture=Posture.READ, stdin=b"", timeout_s=5):
    paths = AcquisitionPaths(tmp_path, acquisition_id_for("lease-os-proof", 1))
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    async with acquisition_guard(paths) as guard:
        return await launcher.run(
            ("/usr/bin/python3", "-I", "-c", source), workspace=workspace,
            posture=posture, guard_fd=guard, stdin=stdin, timeout_s=timeout_s,
        )


async def test_native_namespace_mount_privilege_and_descriptor_table(launcher, tmp_path):
    source = """
import json, os
from pathlib import Path
fds = {}
for value in Path('/proc/self/fd').iterdir():
    try: fds[value.name] = os.readlink(value)
    except FileNotFoundError: pass
print(json.dumps({
    'ns': {n: os.readlink('/proc/self/ns/' + n) for n in ('user','mnt','pid','ipc','uts','net')},
    'profile': Path('/proc/self/attr/current').read_text().strip(),
    'status': Path('/proc/self/status').read_text(), 'fds': fds,
    'uid': os.getuid(), 'gid': os.getgid(), 'home': os.environ['HOME'],
    'sys': Path('/sys').exists(), 'mounts': Path('/proc/self/mountinfo').read_text(),
    'environment': dict(os.environ),
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
print('confined')
"""
    result = await run(launcher, tmp_path, source, posture=Posture.WRITE)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == b"confined"
    assert (tmp_path / "workspace/change").read_text() == "owned"
    assert outside.read_text() == "protected"


@pytest.mark.parametrize("shape", ["line", "many", "stderr", "stdin"])
async def test_output_and_blocked_input_are_bounded_without_deadlock(launcher, tmp_path, shape):
    launcher.limits = ProcessLimits(input_bytes=1024 * 1024, stdout_bytes=4096, record_bytes=1024,
                                    stderr_bytes=512)
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


async def test_runtime_drift_refuses_before_any_child_starts(launcher, tmp_path):
    launcher.expected_runtime = Digest("sha256:" + "0" * 64)
    with pytest.raises(Exception, match="runtime content differs"):
        await run(launcher, tmp_path, "print('must not launch')")
