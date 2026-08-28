"""GateRunner — deterministic CheckResult production over a snapshot; the
runner mints the Attestation (I2). Gates in the graph are ordinary registered
components calling this capability; the kernel does not know what a gate is.

The runner is itself a ``LeasedCapability``: the walker binds it per node
with a ``LeaseContext``, so the run lease (fenced minting) and the sealed
manifest hash arrive from the walker — provenance is never caller-supplied.

Checks run inside the **exported read-only snapshot of the prepared merge
commit** — the read-only snapshot's real consumer: a gate cannot go green by
mutating what it tests (content-verified after the run, regardless of
platform permission semantics). Timeouts kill the whole process group;
damaged, hung, or missing-executable outcomes map to their honest statuses,
never clean success (I4). Output is bounded inline with a truncation marker
(a content-addressed artifact store is future work).
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from pydantic import BaseModel, ConfigDict

from constructicon.core.address import GitSha
from constructicon.core.effect import AttestationDraft, CheckResult, MergeSubject
from constructicon.core.identity import Digest, digest
from constructicon.core.journal import Journal
from constructicon.core.workspace import (
    AcquiredCapability,
    Disposition,
    LeaseClosure,
    LeaseContext,
    LeaseReconciliation,
    StaleAcquisition,
)
from constructicon.substrate.git.authority import (
    AlreadyIntegrated,
    GitAuthority,
    MergeConflict,
)

DETAIL_CAP = 8_000  # bytes of inline check output before truncation


@dataclass(frozen=True)
class CheckSpec:
    name: str
    argv: tuple[str, ...]
    timeout_s: float = 120.0


def default_check_specs() -> tuple[CheckSpec, ...]:
    return (
        CheckSpec("ruff", (sys.executable, "-m", "ruff", "check", "--no-cache", ".")),
        CheckSpec(
            "pytest", (sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider")
        ),
    )


class MergeEvaluation(BaseModel):
    """The typed gate verdict a merge node needs — subject, authority id, and
    evidence. A conflict has no subject and can authorize nothing."""

    model_config = ConfigDict(frozen=True)

    subject: MergeSubject | None
    attestation_id: str | None
    checks: tuple[CheckResult, ...]

    @property
    def ok(self) -> bool:
        return (
            self.subject is not None
            and self.attestation_id is not None
            and bool(self.checks)
            and all(check.ok for check in self.checks)
        )


class GateRunner:
    """Constructed at L4 with journal + authority + check specs; implements
    ``LeasedCapability`` so the walker binds it per node."""

    def __init__(
        self,
        *,
        journal: Journal,
        authority: GitAuthority,
        target_ref: str,
        checks: tuple[CheckSpec, ...] | None = None,
    ) -> None:
        self._journal = journal
        self._authority = authority
        self.target_ref = target_ref
        self._checks = checks if checks is not None else default_check_specs()
        self.check_set_hash = self._compute_check_set_hash()

    def _compute_check_set_hash(self) -> Digest:
        """Binds what actually runs: names, argv, timeouts, env policy, and
        resolved tool versions — the tested tree binds pyproject.toml, not
        which binaries ran."""
        versions: dict[str, str] = {}
        for spec in self._checks:
            probe = subprocess.run(
                [*spec.argv[:3], "--version"] if spec.argv[1:2] == ("-m",) else
                [spec.argv[0], "--version"],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            versions[spec.name] = probe.stdout.strip()[:200] or probe.stderr.strip()[:200]
        return digest(
            "check-set",
            1,
            {
                "checks": [
                    {"name": s.name, "argv": list(s.argv), "timeout_s": s.timeout_s}
                    for s in self._checks
                ],
                "env": {"PYTHONDONTWRITEBYTECODE": "1", "isolated_tmp": True},
                "versions": versions,
                "git": self._authority.environment.model_dump(mode="json"),
            },
        )

    # -- LeasedCapability (stateless: closures are trivial, uniform) ---------

    async def acquire(self, context: LeaseContext) -> AcquiredCapability:
        from constructicon.core.workspace import acquisition_id_for, lease_id_for

        lease_id = lease_id_for(
            context.run_lease.run_id, context.path, context.binding.binding
        )
        acquisition_id = acquisition_id_for(lease_id, context.run_lease.epoch)
        return AcquiredCapability(
            resource=BoundGateRunner(self, context),
            lease_id=lease_id,
            acquisition_id=acquisition_id,
            resource_ref="gates",
        )

    async def close(
        self, acquisition: AcquiredCapability, disposition: Disposition
    ) -> LeaseClosure:
        return LeaseClosure(
            disposition="discarded" if disposition == "discard" else "released"
        )

    async def reconcile(
        self, context: LeaseContext, stale: tuple[StaleAcquisition, ...]
    ) -> LeaseReconciliation:
        return LeaseReconciliation()  # snapshots are transient within verify()

    # -- the check run --------------------------------------------------------

    def _run_check(self, spec: CheckSpec, cwd: str, tmp_dir: str) -> CheckResult:
        env = dict(os.environ)
        env.update(
            PYTHONDONTWRITEBYTECODE="1",
            TMPDIR=tmp_dir,
            RUFF_CACHE_DIR=os.path.join(tmp_dir, "ruff"),
        )
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                list(spec.argv),
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,  # the whole gate process tree is ours
            )
        except FileNotFoundError as exc:
            return CheckResult(
                name=spec.name,
                status="infrastructure_error",
                detail=f"executable unavailable: {exc}",
                elapsed_s=time.monotonic() - started,
            )
        try:
            output, _ = process.communicate(timeout=spec.timeout_s)
        except subprocess.TimeoutExpired:
            with_suppress_kill(process.pid)
            partial, _ = process.communicate()
            return CheckResult(
                name=spec.name,
                status="timeout",
                detail=_bounded(f"timed out after {spec.timeout_s}s\n{partial or ''}"),
                elapsed_s=time.monotonic() - started,
            )
        elapsed = time.monotonic() - started
        return CheckResult(
            name=spec.name,
            status="passed" if process.returncode == 0 else "failed",
            detail=_bounded(output or ""),
            elapsed_s=elapsed,
        )

    def _verify(self, context: LeaseContext, candidate: GitSha) -> MergeEvaluation:
        prepared = self._authority.prepare_merge(candidate, self.target_ref)
        if isinstance(prepared, AlreadyIntegrated):
            return MergeEvaluation(
                subject=None,
                attestation_id=None,
                checks=(
                    CheckResult(
                        name="already-integrated",
                        status="passed",
                        detail=(
                            f"candidate {candidate} is already reachable from "
                            f"{prepared.target_ref} — nothing to merge"
                        ),
                        elapsed_s=0.0,
                    ),
                ),
            )
        if isinstance(prepared, MergeConflict):
            return MergeEvaluation(
                subject=None,
                attestation_id=None,
                checks=(
                    CheckResult(
                        name="merge-conflict",
                        status="conflict",
                        detail=_bounded(prepared.detail),
                        elapsed_s=0.0,
                    ),
                ),
            )
        subject = prepared.subject
        snapshot = self._authority.read_snapshot(subject.merge_commit)
        checks: list[CheckResult] = []
        try:
            before = self._authority.content_digest(snapshot.path)
            with tempfile.TemporaryDirectory() as tmp_dir:
                for spec in self._checks:
                    checks.append(self._run_check(spec, snapshot.path, tmp_dir))
            after = self._authority.content_digest(snapshot.path)
            if after != before:
                checks.append(
                    CheckResult(
                        name="snapshot-integrity",
                        status="failed",
                        detail="the gate run mutated the tree it tested",
                        elapsed_s=0.0,
                    )
                )
        finally:
            self._authority.discard_snapshot(snapshot)
        draft = AttestationDraft(
            action="merge",
            subject=subject,
            checks=tuple(checks),
            check_set_hash=self.check_set_hash,
            manifest_hash=context.manifest_hash,  # the invoking sealed world
            workspace_id=None,
        )
        attestation = self._journal.mint_attestation(context.run_lease, draft)
        return MergeEvaluation(
            subject=subject,
            attestation_id=attestation.attestation_id,
            checks=tuple(checks),
        )


class BoundGateRunner:
    """What a node actually holds: verify against one run's sealed world."""

    def __init__(self, runner: GateRunner, context: LeaseContext) -> None:
        self._runner = runner
        self._context = context

    @property
    def target_ref(self) -> str:
        return self._runner.target_ref

    def verify(self, candidate: GitSha) -> MergeEvaluation:
        return self._runner._verify(self._context, candidate)


def with_suppress_kill(pid: int) -> None:
    if os.name == "nt":
        with contextlib.suppress(OSError):
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        return
    getpgid = cast(Callable[[int], int], os.__dict__["getpgid"])
    killpg = cast(Callable[[int, int], None], os.__dict__["killpg"])
    sigkill = cast(int, signal.__dict__["SIGKILL"])
    with contextlib.suppress(ProcessLookupError, PermissionError):
        killpg(getpgid(pid), sigkill)


def _bounded(text: str) -> str:
    encoded = text.encode()
    if len(encoded) <= DETAIL_CAP:
        return text
    return encoded[:DETAIL_CAP].decode(errors="replace") + "\n[truncated]"
