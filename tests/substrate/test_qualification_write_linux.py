"""N5 SCRIPTED qualification: physical Linux worker, capture, gate and recovery.

Only the native byte peer and BindingStore syscalls are scripted. No vendor
binary is launched. The fixed qualification graph, guards, workspace capture,
exact checker, attempt record and cold reconstruction all use production code.
Fixtures live under the service's trusted home, not the world-writable /tmp
ancestor; the actual production custody checks are retained.
"""

import sys
import tempfile
from dataclasses import dataclass, field, fields
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.api import _qualification_write_assembly as assembly_module
from constructicon.api import qualification
from constructicon.core.run import RunStatus
from constructicon.substrate.executors import codex, codex_lane
from constructicon.substrate.executors.linux import LinuxLauncher
from tests.api.test_qualification_write_lifecycle import (
    assert_closed,
    reconstruct_write,
    sealed_assembly,
)
from tests.substrate.test_codex_adapter import FINISHED
from tests.substrate.test_codex_adapter import portable_binding as portable_binding
from tests.substrate.test_codex_write import write_native
from tests.substrate.test_codex_write_capture import PhysicalWorkerLauncher
from tests.substrate.test_linux_containment import launcher as launcher

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="requires provisioned physical Linux containment",
)


@pytest.fixture
def private_fixture_root():
    with tempfile.TemporaryDirectory(prefix=".constructicon-n5-write-", dir=Path.home()) as root:
        yield Path(root).resolve()


def physical_launcher(launcher, *, contents="ready"):
    program = (
        "from pathlib import Path\n"
        "assert not Path('/vendor-store').exists()\n"
        "assert not Path('/tmp/home/.codex').exists()\n"
        "assert Path('/proc/net/route').read_text().splitlines()[1:] == []\n"
        f"Path('n5-write.txt').write_bytes({contents!r}.encode()+b'\\n')\n"
    )
    return PhysicalWorkerLauncher(
        **{item.name: getattr(launcher, item.name) for item in fields(LinuxLauncher)},
        native=write_native(program=program), result=FINISHED,
    )


@pytest.mark.parametrize("contents,passed", [("ready", True), ("wrong", False)])
async def test_scripted_qualified_write_runs_real_worker_capture_and_exact_gate(
    launcher, portable_binding, private_fixture_root, contents, passed,
):
    physical = physical_launcher(launcher, contents=contents)
    assembly, auth = await sealed_assembly(private_fixture_root, physical, portable_binding[1:])
    report = await qualification.qualify_write(assembly=assembly, authorization=auth)
    journal = assembly.resources.journal
    assert journal.run_state(auth.run_id).status is (
        RunStatus.SUCCEEDED if passed else RunStatus.FAILED
    ), journal.events(auth.run_id)
    assert (report.verdict == "passed") is passed, report.model_dump_json()
    callbacks = [call for call in physical.worker_calls if call[0] == codex.WORKER_ARGUMENTS]
    assert len(callbacks) == len(physical.native.callback_responses) == len(physical.commands) == 1
    # Positive evidence each distinct physical stage actually ran.
    assert any("git('add', '--all'" in arg
               for command, _ in physical.worker_calls for arg in command)
    assert any(command[:2] == ("/usr/bin/git", "pack-objects")
               for command, _ in physical.worker_calls)
    assert any(assembly.resources.gate.checks[0].argv[-1] in command
               for command, _ in physical.worker_calls)
    assert_closed(assembly, auth.run_id)
    assert assembly.resources.authority.resolve_ref(assembly.resources.fixture.target_ref) == (
        assembly.resources.fixture.base_commit
    )


@pytest.mark.parametrize("checkpointed", [False, True])
async def test_scripted_qualified_write_physical_cold_reconstruction(
    launcher, portable_binding, private_fixture_root, monkeypatch, checkpointed,
):
    await reconstruct_write(private_fixture_root, portable_binding[1:], monkeypatch,
                            checkpointed, lambda: physical_launcher(launcher))


@dataclass(frozen=True, kw_only=True)
class SmokeLauncher(LinuxLauncher):
    """Record real launcher work, with no executor provider or native byte peer."""

    physical_calls: list = field(default_factory=list)

    async def run(self, command, **kwargs):
        self.physical_calls.append((command, kwargs))
        return await LinuxLauncher.run(self, command, **kwargs)


async def test_credential_free_smoke_actual_entry_runs_physical_capture_and_checker(
    launcher, private_fixture_root, monkeypatch,
):
    root = private_fixture_root / "fixture"
    fixture = assembly_module.prepare_fixture(root)
    physical = SmokeLauncher(
        **{item.name: getattr(launcher, item.name) for item in fields(LinuxLauncher)},
    )
    monkeypatch.setattr(codex_lane, "_launcher", lambda _: physical)
    report = await qualification.smoke_write(SimpleNamespace(
        fixture=root, launch_root=Path("/unused-scripted-launch"),
    ))
    assert report.verdict == "passed", report.model_dump_json()
    assert report.target_unchanged is True
    assert report.base_commit == fixture.base_commit
    assert report.checkpoint_chain_validated is True
    assert report.obligation_count == 2 and report.check_count == 1
    assert {row.role for row in report.obligations} == {"workspace", "gate"}
    assert all(row.state == "closed" and row.disposition == "released"
               for row in report.obligations)
    assert any(command == codex.WORKER_ARGUMENTS for command, _ in physical.physical_calls)
    assert any("git('add', '--all'" in arg
               for command, _ in physical.physical_calls for arg in command)
    assert not list(root.glob("*.attempt"))
    assert not list((root / "workspace-acquisitions").glob("payloads/*"))
    assert not list((root / "gate-acquisitions").glob("payloads/*"))
