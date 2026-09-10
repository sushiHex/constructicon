"""Async merge gates: one installed runtime, one recorded acquisition.

Identification has no candidate mount. Verification reuses GitAuthority's
exact merge law, then the existing Linux boundary over an owned READ snapshot.
Trusted metadata/filesystem workers are joined; no legacy verifier is wrapped.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import math
import os
import shutil
import tarfile
import weakref
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from constructicon.core.address import GitSha
from constructicon.core.effect import AttestationDraft, CheckResult
from constructicon.core.errors import ContractViolation
from constructicon.core.gates import MergeEvaluation
from constructicon.core.grants import Posture
from constructicon.core.identity import Digest, canonical_json, digest, parse_json_value
from constructicon.core.journal import Journal
from constructicon.core.workspace import (
    AcquiredCapability,
    Disposition,
    LeaseClosure,
    LeaseContext,
    LeaseReconciliation,
    StaleAcquisition,
    acquisition_id_for,
    lease_id_for,
)
from constructicon.substrate import _lifetime
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.executors.linux import LinuxLauncher, require_fixed_artifact
from constructicon.substrate.gates.runner import CheckSpec, _bounded
from constructicon.substrate.git import acquisition, authority, process
from constructicon.substrate.git.acquisition import (
    AcquisitionClosure,
    AcquisitionPaths,
    acquisition_guard,
    dispose_acquisition,
)
from constructicon.substrate.git.authority import AlreadyIntegrated, GitAuthority, MergeConflict
from constructicon.substrate.git.pack import commit_oid
from constructicon.substrate.git.process import GitProcess

# Both channels consume the launcher's hard output budget, including stderr.
# Private scratch and these fixed variables never inherit the service's env.
_CHECK = """
import os, sys
os.dup2(1, 2)
os.environ.update(PYTHONDONTWRITEBYTECODE='1', TMPDIR='/tmp', RUFF_CACHE_DIR='/tmp/ruff')
os.execv(sys.argv[1], sys.argv[1:])
"""


class _GateReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    acquisition: str
    provider: str
    storage_root: str


@dataclass
class _Phase:
    entered: bool = False
    ready: bool = False
    closed: bool = False


@dataclass(frozen=True, eq=False)
class BoundContainedGate:
    provider: ContainedGateRunner
    context: LeaseContext
    paths: AcquisitionPaths
    _phase: _Phase = field(default_factory=_Phase)

    @property
    def target_ref(self) -> str:
        return self.provider.target_ref

    async def materialize(self) -> None:
        if self._phase.closed or self._phase.entered:
            raise ContractViolation("gate materialization requires an inert open handle")
        self._phase.entered = True  # Before the first await/persistent operation.
        async with acquisition_guard(self.paths):
            await self.provider._require_open(self)
            self._phase.ready = True

    async def verify(self, candidate: GitSha) -> MergeEvaluation:
        work = asyncio.create_task(self.provider._verify(self, candidate))

        async def stop() -> None:
            if not work.done():
                work.cancel()
            with suppress(asyncio.CancelledError):
                await work

        try:
            async with asyncio.timeout(self.context.binding.effective_grants.timeout_s):
                while not work.done():
                    await asyncio.wait({work}, timeout=0.05)
                    self.provider._control(self)
                return work.result()
        finally:
            await finish_owned(asyncio.create_task(stop()))


class ContainedGateRunner:
    """Factory-qualified ``gates.contained``; no provider route or executor API."""

    kind = "gates.contained"

    def __init__(
        self, *, journal: Journal, authority: GitAuthority, root: Path,
        target_ref: str, provider_id: str, launcher: LinuxLauncher,
        checks: tuple[CheckSpec, ...],
    ) -> None:
        if not root.is_absolute() or not target_ref.startswith("refs/") or not provider_id:
            raise ContractViolation("gates require an absolute root, full target and provider id")
        if not checks or len({spec.name for spec in checks}) != len(checks):
            raise ContractViolation("contained checks must be nonempty and uniquely named")
        for spec in checks:
            if (
                not spec.name or not spec.argv or not spec.argv[0].startswith("/")
                or any("\0" in arg for arg in spec.argv)
                or not math.isfinite(spec.timeout_s) or spec.timeout_s <= 0
            ):
                raise ContractViolation("contained checks require fixed argv and positive timeouts")
        self._journal = journal
        self.authority = authority
        self.root = root.resolve()
        self.target_ref = target_ref
        self.provider_id = provider_id
        self.launcher = launcher
        self.checks = checks
        self.closure = AcquisitionClosure(authority)
        self._versions: tuple[str, ...] | None = None
        self._qualified: Digest | None = None
        self._handles: weakref.WeakSet[BoundContainedGate] = weakref.WeakSet()

    @classmethod
    async def create(
        cls, *, journal: Journal, authority: GitAuthority, root: Path,
        target_ref: str, provider_id: str, launcher: LinuxLauncher,
        checks: tuple[CheckSpec, ...],
    ) -> ContainedGateRunner:
        runner = cls(
            journal=journal, authority=authority, root=root, target_ref=target_ref,
            provider_id=provider_id, launcher=launcher, checks=checks,
        )
        before = await finish_owned(asyncio.create_task(asyncio.to_thread(
            runner._runtime_identity,
        )))
        versions = []
        # An anonymous lifetime descriptor, not an unrecorded persistent lease.
        read_fd, write_fd = os.pipe()
        try:
            for spec in checks:
                probe = (
                    (*spec.argv[:3], "--version") if spec.argv[1:2] == ("-m",)
                    else (spec.argv[0], "--version")
                )
                result = await launcher.run(
                    ("/usr/bin/python3", "-I", "-c", _CHECK, *probe),
                    workspace=None, posture=Posture.READ, guard_fds=(read_fd,), timeout_s=30,
                )
                if (
                    result.returncode or result.timed_out or result.bound_exceeded
                    or result.payload_returncode != 0
                ):
                    raise ContractViolation("contained gate runtime identification failed")
                versions.append(_bounded(result.stdout.decode(errors="replace")))
        finally:
            os.close(read_fd)
            os.close(write_fd)
        after = await finish_owned(asyncio.create_task(asyncio.to_thread(runner._runtime_identity)))
        if after != before:
            raise ContractViolation("gate runtime changed during identification")
        runner._versions = tuple(versions)
        runner._qualified = after
        return runner

    def _runtime_identity(self) -> Digest:
        executable = Path(self.authority.git_executable)
        if os.name == "posix":
            require_fixed_artifact(executable)
        interpreter = process.git_interpreter()
        sources = (Path(__file__), Path(acquisition.__file__), Path(authority.__file__),
                   Path(process.__file__), Path(_lifetime.__file__))
        return digest("contained-gate-runtime", 1, {
            "launcher": self.launcher.revision,
            "checks": [asdict(spec) for spec in self.checks], "target_ref": self.target_ref,
            "source": [hashlib.sha256(p.read_bytes()).hexdigest() for p in sources],
            "git": hashlib.sha256(executable.read_bytes()).hexdigest(),
            "python": hashlib.sha256(interpreter.read_bytes()).hexdigest() if interpreter else None,
            "object_format": self.authority.environment.object_format,
        })

    @property
    def check_set_hash(self) -> Digest:
        if self._qualified is None or self._versions is None:
            raise ContractViolation("contained gate runtime is not identified")
        if self._runtime_identity() != self._qualified:
            raise ContractViolation("contained gate runtime drifted after identification")
        return digest("contained-check-set", 1, {
            "runtime": self._qualified, "versions": self._versions,
        })

    @property
    def revision(self) -> str:
        return str(self.check_set_hash)

    def is_assembled_from(self, journal: Journal) -> bool:
        return self._journal is journal

    async def acquire(self, context: LeaseContext) -> AcquiredCapability:
        revision = await finish_owned(asyncio.create_task(asyncio.to_thread(lambda: self.revision)))
        if context.binding.revision != revision or context.check_control is None:
            raise ContractViolation("contained gate requires its sealed revision and control check")
        if context.binding.effective_grants.posture not in (Posture.READ, Posture.WRITE):
            raise ContractViolation("gate snapshot requires READ or WRITE posture")
        logical = lease_id_for(context.run_lease.run_id, context.path, context.binding.binding)
        acquired = acquisition_id_for(logical, context.run_lease.epoch)
        handle = BoundContainedGate(self, context, AcquisitionPaths(self.root, acquired))
        self._handles.add(handle)
        # A private recovery locator, not part of the portable launch identity.
        reference = _GateReference(
            acquisition=acquired, provider=self.provider_id, storage_root=str(self.root),
        )
        return AcquiredCapability(
            resource=handle, lease_id=logical, acquisition_id=acquired,
            resource_ref=canonical_json(reference.model_dump(mode="json")),
            materialize=handle.materialize,
        )

    def _owned(self, handle: BoundContainedGate) -> None:
        if handle.provider is not self or handle not in self._handles:
            raise ContractViolation("gate handle does not belong to this provider")

    async def _require_open(self, handle: BoundContainedGate) -> None:
        self._owned(handle)
        await finish_owned(asyncio.create_task(asyncio.to_thread(
            self.closure.require_open, handle.paths,
        )))
        revision = await finish_owned(asyncio.create_task(asyncio.to_thread(lambda: self.revision)))
        if handle._phase.closed or handle.context.binding.revision != revision:
            raise ContractViolation("gate acquisition is closed or its runtime drifted")
        self._control(handle)

    @staticmethod
    def _control(handle: BoundContainedGate) -> None:
        if handle._phase.closed:
            raise ContractViolation("gate acquisition was locally closed")
        control = handle.context.check_control
        if control is None:
            raise ContractViolation("gate lost its invocation control check")
        control()

    async def close(
        self, acquisition: AcquiredCapability, disposition: Disposition,
    ) -> LeaseClosure:
        handle = acquisition.resource
        if not isinstance(handle, BoundContainedGate):
            raise ContractViolation("gate close requires its own handle")
        self._owned(handle)
        handle._phase.closed = True
        if handle._phase.entered:
            await dispose_acquisition(self.closure, handle.paths)
        return LeaseClosure(disposition="released" if disposition == "release" else "discarded")

    async def reconcile(
        self, context: LeaseContext, stale: tuple[StaleAcquisition, ...],
    ) -> LeaseReconciliation:
        reaped = []
        logical = lease_id_for(context.run_lease.run_id, context.path, context.binding.binding)
        for item in stale:
            row = item.lease
            if (
                row.lease_id != logical or row.run_id != context.run_lease.run_id
                or row.path != context.path or row.binding_id != context.binding.binding
                or row.acquisition_epoch >= context.run_lease.epoch or row.resource_ref is None
            ):
                raise ContractViolation("gate recovery row is not this stale invocation")
            reference = _GateReference.model_validate(parse_json_value(row.resource_ref))
            acquired = acquisition_id_for(logical, row.acquisition_epoch)
            if (
                reference.acquisition != acquired or reference.provider != self.provider_id
                or reference.storage_root != str(self.root)
                or canonical_json(reference.model_dump(mode="json")) != row.resource_ref
            ):
                raise ContractViolation("gate recovery reference contradicts its durable row")
            await dispose_acquisition(self.closure, AcquisitionPaths(self.root, acquired))
            reaped.append(row.resource_ref)
        return LeaseReconciliation(reaped=tuple(reaped))

    async def _snapshot(self, handle: BoundContainedGate, commit: GitSha, guard: int) -> Path:
        git = GitProcess(self.authority.git_executable, self.launcher.limits)
        inventory = await git.run(
            "ls-tree", "-r", "-z", "--full-tree", commit,
            cwd=self.authority.repository_id, guard=guard,
        )
        content = await git.run(
            "archive", "--format=tar", commit, cwd=self.authority.repository_id, guard=guard,
        )
        snapshot = handle.paths.payload / "snapshot"

        def extract() -> None:
            snapshot.mkdir(parents=True, exist_ok=False)
            with tarfile.open(fileobj=io.BytesIO(content)) as archive:
                archive.extractall(snapshot, filter="data")
            # Archive attributes may omit or substitute content. Compare actual
            # exported blobs/modes with the exact Git tree before running code.
            # Unsupported gitlinks or lossy exports fail closed, never attest a
            # different filesystem under the original tree's identity.
            expected = {}
            for entry in inventory.split(b"\0"):
                if not entry:
                    continue
                metadata, name = entry.split(b"\t", 1)
                mode, kind, oid = metadata.decode("ascii").split()
                if kind != "blob" or mode not in {"100644", "100755", "120000"}:
                    raise ContractViolation("gate snapshot contains an unsupported Git entry")
                expected[os.fsdecode(name)] = (mode, oid)
            observed = {}
            for path in snapshot.rglob("*"):
                if path.is_symlink():
                    mode, raw = "120000", os.fsencode(os.readlink(path))
                elif path.is_file():
                    mode = "100755" if path.stat().st_mode & 0o111 else "100644"
                    raw = path.read_bytes()
                else:
                    continue
                oid = hashlib.new(
                    self.authority.environment.object_format,
                    f"blob {len(raw)}\0".encode() + raw,
                ).hexdigest()
                observed[path.relative_to(snapshot).as_posix()] = (mode, oid)
            if observed != expected:
                raise ContractViolation("gate snapshot differs from the exact prepared Git tree")

        await finish_owned(asyncio.create_task(asyncio.to_thread(extract)))
        return snapshot

    async def _check(self, spec: CheckSpec, snapshot: Path, guard: int) -> CheckResult:
        result = await self.launcher.run(
            ("/usr/bin/python3", "-I", "-c", _CHECK, *spec.argv),
            workspace=snapshot, posture=Posture.READ, guard_fds=(guard,),
            timeout_s=spec.timeout_s,
        )
        detail = (result.stdout + result.stderr).decode(errors="replace")
        if result.timed_out:
            status = "timeout"
            detail = f"check timed out after {spec.timeout_s}s\n" + detail
        elif result.bound_exceeded:
            status = "infrastructure_error"
            detail = f"check exceeded {result.bound_exceeded} output bound\n" + detail
        elif result.payload_returncode is None or result.returncode != result.payload_returncode:
            status = "infrastructure_error"
            detail = "launcher did not report a complete check exit\n" + detail
        else:
            status = "passed" if result.payload_returncode == 0 else "failed"
        return CheckResult(
            name=spec.name, status=status, detail=_bounded(detail), elapsed_s=result.elapsed_s,
        )

    async def _verify(self, handle: BoundContainedGate, candidate: GitSha) -> MergeEvaluation:
        self._owned(handle)
        if not handle._phase.ready or handle._phase.closed:
            raise ContractViolation("gate verification requires a materialized open acquisition")
        candidate = commit_oid(str(candidate).encode(), self.authority.environment.object_format)
        async with acquisition_guard(handle.paths) as guard:
            await self._require_open(handle)
            # This is only trusted authority plumbing, not a blocking verifier.
            # It owns no payload path; join it before cancellation can return.
            prepared = await finish_owned(asyncio.create_task(asyncio.to_thread(
                self.authority.prepare_merge, candidate, self.target_ref,
            )))
            await self._require_open(handle)
            if isinstance(prepared, (AlreadyIntegrated, MergeConflict)):
                integrated = isinstance(prepared, AlreadyIntegrated)
                return MergeEvaluation(subject=None, attestation_id=None, checks=(CheckResult(
                    name="already-integrated" if integrated else "merge-conflict",
                    status="passed" if integrated else "conflict",
                    detail=(f"candidate {candidate} is already reachable from {self.target_ref}"
                            if isinstance(prepared, AlreadyIntegrated)
                            else _bounded(prepared.detail)),
                    elapsed_s=0,
                ),))
            subject = prepared.subject
            checks: list[CheckResult] = []
            try:
                snapshot = await self._snapshot(handle, subject.merge_commit, guard)
                before = await finish_owned(asyncio.create_task(asyncio.to_thread(
                    self.authority.content_digest, snapshot,
                )))
                for spec in self.checks:
                    await self._require_open(handle)
                    checks.append(await self._check(spec, snapshot, guard))
                # Launcher completion includes descendant teardown, before this read.
                after = await finish_owned(asyncio.create_task(asyncio.to_thread(
                    self.authority.content_digest, snapshot,
                )))
                if after != before:
                    checks.append(CheckResult(
                        name="snapshot-integrity", status="failed",
                        detail="the gate run mutated the tree it tested", elapsed_s=0,
                    ))
            finally:
                # All paths belong to the recorded acquisition, even partial extraction.
                if handle.paths.payload.exists():
                    await finish_owned(asyncio.create_task(asyncio.to_thread(
                        shutil.rmtree, handle.paths.payload,
                    )))
            await self._require_open(handle)
            check_set_hash = await finish_owned(asyncio.create_task(asyncio.to_thread(
                lambda: self.check_set_hash,
            )))
            await asyncio.sleep(0)
            self._control(handle)
            attestation = self._journal.mint_attestation(handle.context.run_lease, AttestationDraft(
                action="merge", subject=subject, checks=tuple(checks),
                check_set_hash=check_set_hash, manifest_hash=handle.context.manifest_hash,
                workspace_id=None,
            ))
            return MergeEvaluation(
                subject=subject, attestation_id=attestation.attestation_id, checks=tuple(checks),
            )
