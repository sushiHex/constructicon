"""Contained async WRITE capture under the existing acquisition closure law.

Mutable Git metadata is interpreted only by the Linux boundary. Trusted Git
receives immutable pack bytes through a fresh quarantine, never a stage path.
These workspaces do not enable live executors or replace legacy gate bindings.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

from constructicon.core.address import GitSha
from constructicon.core.envelope import GitRef
from constructicon.core.errors import ContractViolation
from constructicon.core.grants import Posture
from constructicon.core.identity import digest
from constructicon.core.workspace import Disposition, LeaseContext
from constructicon.substrate import _lifetime
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.git import acquisition, authority, contained, pack, process
from constructicon.substrate.git.acquisition import AcquisitionPaths, dispose_acquisition
from constructicon.substrate.git.authority import _PINNED_ENV, candidate_ref_for
from constructicon.substrate.git.contained import ContainedWorkspace, ContainedWorkspaceProvider
from constructicon.substrate.git.pack import PackLimits, commit_oid, import_pack
from constructicon.substrate.git.process import GitProcess

_GIT_ENV = {**_PINNED_ENV, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0"}
_PREAMBLE = "import os,subprocess,sys\nos.environ.update(" + repr(_GIT_ENV) + ")\n"
_CAPTURE = _PREAMBLE + """
def git(*args, **kwargs):
    return subprocess.run(['/usr/bin/git', *args], check=True, **kwargs)
git('add', '--all', stdout=sys.stderr)
if git('status', '--porcelain', '-z', stdout=subprocess.PIPE).stdout:
    git('commit', '--no-gpg-sign', '--file', '-', input=sys.stdin.buffer.read(), stdout=sys.stderr)
git('rev-parse', '--verify', 'HEAD')
"""
_RESET = _PREAMBLE + """
def git(*args, **kwargs):
    return subprocess.run(['/usr/bin/git', *args], check=True, **kwargs)
git('index-pack', '--stdin', input=sys.stdin.buffer.read(), stdout=sys.stderr)
git('reset', '--hard', sys.argv[1], stdout=sys.stderr)
git('clean', '-ffdqx', stdout=sys.stderr)
git('rev-parse', '--verify', 'HEAD')
"""


@dataclass(frozen=True, eq=False)
class ContainedWriteWorkspace(ContainedWorkspace):
    """Only the explicit async capability exposes reset/capture."""

    async def reset_to(self, ref: GitRef) -> None:
        async with asyncio.timeout(self.context.binding.effective_grants.timeout_s):
            await cast(ContainedWriteWorkspaceProvider, self.provider).reset(self, ref)

    async def commit_all(self, message: str) -> GitSha:
        async with asyncio.timeout(self.context.binding.effective_grants.timeout_s):
            return await cast(ContainedWriteWorkspaceProvider, self.provider).capture(self, message)

    def git_ref(self) -> GitRef:
        return GitRef(
            repository=self.provider.authority.repository_id,
            commit=self._phase.head or self.base, diff_against=self.base,
        )


class ContainedWriteWorkspaceProvider(ContainedWorkspaceProvider):
    """A separate capability kind and call convention, not a relabeled legacy view."""

    kind = "workspace.contained"
    pack_limits = PackLimits()

    @property
    def revision(self) -> str:
        interpreter = process.git_interpreter()
        sources = [Path(__file__), Path(acquisition.__file__), Path(authority.__file__),
                   Path(contained.__file__), Path(pack.__file__), Path(process.__file__),
                   Path(_lifetime.__file__)]
        return str(digest("contained-write-workspace", 1, {
            "source": [hashlib.sha256(source.read_bytes()).hexdigest() for source in sources],
            "launcher": self.launcher.revision, "target": self.target_ref,
            "git": hashlib.sha256(Path(self.git).read_bytes()).hexdigest(),
            "python": hashlib.sha256(interpreter.read_bytes()).hexdigest() if interpreter else None,
            "object_format": self.authority.environment.object_format,
            "pack_limits": asdict(self.pack_limits),
        }))

    def _workspace(
        self, context: LeaseContext, paths: AcquisitionPaths, base: GitSha,
    ) -> ContainedWriteWorkspace:
        if self.posture is not Posture.WRITE:
            raise ContractViolation("contained capture requires WRITE posture")
        if context.check_control is None:
            raise ContractViolation("contained capture requires the invocation control check")
        if context.binding.revision != self.revision:
            raise ContractViolation("contained workspace revision differs from its binding")
        return ContainedWriteWorkspace(self, context, paths, base)

    def _check(self, workspace: ContainedWriteWorkspace) -> None:
        self.owned_view(workspace, workspace.context)
        if workspace.context.binding.revision != self.revision:
            raise ContractViolation("contained workspace implementation drifted")
        control = workspace.context.check_control
        if control is None:
            raise ContractViolation("contained capture lost its invocation control check")
        control()

    def _candidate_ref(self, workspace: ContainedWorkspace) -> str:
        return candidate_ref_for(workspace.context.run_lease.run_id, workspace.paths.acquisition_id)

    async def _candidate(self, workspace: ContainedWorkspace) -> GitSha | None:
        return await finish_owned(asyncio.create_task(asyncio.to_thread(
            self.closure.candidate, self._candidate_ref(workspace),
        )))

    async def _contained(
        self, workspace: ContainedWriteWorkspace, guard: int, command: tuple[str, ...], *,
        posture: Posture, stdin: bytes = b"",
    ) -> bytes:
        self._check(workspace)
        result = await self.launcher.run(
            command, workspace=Path(workspace.path), posture=posture, guard_fds=(guard,),
            stdin=stdin, input_kind="artifact",
            timeout_s=workspace.context.binding.effective_grants.timeout_s,
        )
        if result.returncode or result.timed_out or result.bound_exceeded:
            detail = result.stderr.decode(errors="replace")[:500]
            raise ContractViolation("contained Git failed: " + detail)
        return result.stdout

    async def reset(self, workspace: ContainedWriteWorkspace, ref: GitRef) -> None:
        self._check(workspace)
        if ref.repository != self.authority.repository_id:
            raise ContractViolation("reset GitRef belongs to another authority")
        oid = commit_oid(str(ref.commit).encode(), self.authority.environment.object_format)
        async with workspace.use() as guard:
            if await self._candidate(workspace) is not None:
                raise ContractViolation("reset is unavailable after candidate publication")
            content = await self._export(
                "pack-objects", "--stdout", "--revs", stdin=f"{oid}\n".encode(),
            )
            raw = await self._contained(
                workspace, guard, ("/usr/bin/python3", "-I", "-c", _RESET, oid),
                posture=Posture.WRITE, stdin=content,
            )
            if commit_oid(raw, self.authority.environment.object_format) != oid:
                raise ContractViolation("contained reset resolved a different commit")
            self._check(workspace)
            workspace._phase.head = oid

    async def capture(self, workspace: ContainedWriteWorkspace, message: str) -> GitSha:
        self._check(workspace)
        async with workspace.use() as guard:
            current = await self._candidate(workspace)
            if current is not None:
                self._check(workspace)
                workspace._phase.head = current
                return current
            raw = await self._contained(
                workspace, guard, ("/usr/bin/python3", "-I", "-c", _CAPTURE),
                posture=Posture.WRITE, stdin=message.encode("utf-8"),
            )
            oid = commit_oid(raw, self.authority.environment.object_format)
            # The previous launcher has joined its reaper before this new READ
            # boundary is opened. No mutable stage writer survives into export.
            content = await self._contained(
                workspace, guard, ("/usr/bin/git", "pack-objects", "--stdout", "--revs"),
                posture=Posture.READ, stdin=f"{oid}\n".encode(),
            )
            await import_pack(
                self.authority, GitProcess(self.git, self.launcher.limits),
                acquisition_root=workspace.paths.payload, candidate=oid, pack=content,
                limits=self.pack_limits, guard=guard,
            )
        # Physical work is quiescent. Ref publication owns no staging path, so
        # recovery may finish disposal here; Git, not the guard, fences a late ref.
        await asyncio.sleep(0)
        self._check(workspace)
        await finish_owned(asyncio.create_task(asyncio.to_thread(
            self.closure.publish, workspace.paths, self._candidate_ref(workspace), oid,
        )))
        workspace._phase.head = oid
        return oid

    async def _dispose(
        self, paths: AcquisitionPaths, run_id: str, disposition: Disposition,
    ) -> None:
        await dispose_acquisition(
            self.closure, paths, candidate_ref=candidate_ref_for(run_id, paths.acquisition_id),
            disposition=disposition,
        )
