"""GitAuthority — deterministic code operating on git (I1).

The authority repository is **bare and protected**: only this module's
deterministic subprocess plumbing touches its refs. No agent workspace is
ever a linked worktree of it — linked worktrees share ``refs/*``, so an agent
inside one could move the authority branch directly and "one install path"
would be false. Instead:

- **WRITE workspaces are staging repositories**: a per-acquisition
  ``git init`` + fetch of the exact base. The agent may commit and mangle
  refs there — it holds zero authority refs. ``commit_all`` imports the
  exact candidate object back (OIDs are content-addressed; the commit
  survives import unchanged) under an authority-owned
  ``refs/candidates/…`` ref.
- **Read snapshots are exported trees** (``git archive`` → tarfile): no
  ``.git`` at all, write bits removed symlink-safely. Calibrated claim: a
  fresh snapshot + failing ordinary writes + post-gate content verification
  make any observable mutation fail the check; containment of hostile
  same-uid code is the M8 sandbox layer's job — this is not a read-only
  mount.
- **Install is one git ref transaction** (``update-ref --stdin``): the
  target CAS-moves from the expected base to the prepared merge commit AND
  an idempotency **marker ref** is created — both land or neither. The
  marker is the durable external receipt reconciliation reads after a crash;
  a later force move of the target cannot erase the proof of install.

Every command runs under a pinned environment (identity, dates, locale, no
system/global config), so re-preparing the same candidate onto the same base
yields the same sha. Kernel budget: stdlib subprocess only.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import stat
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from constructicon.core.address import GitSha
from constructicon.core.effect import MergeSubject
from constructicon.core.envelope import GitRef
from constructicon.core.errors import ConstructiconError, ContractViolation
from constructicon.core.identity import Digest, canonical_json, digest
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

MIN_GIT = (2, 38)  # merge-tree --write-tree

_PINNED_ENV = {
    "LC_ALL": "C",
    "TZ": "UTC",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_AUTHOR_NAME": "constructicon",
    "GIT_AUTHOR_EMAIL": "authority@constructicon.invalid",
    "GIT_COMMITTER_NAME": "constructicon",
    "GIT_COMMITTER_EMAIL": "authority@constructicon.invalid",
    # fixed dates: commit identity is deterministic for identical content
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00 +0000",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00 +0000",
}


class GitAuthorityDamaged(ConstructiconError):
    """The authority repository contradicts its own durable receipts."""


class GitEnvironment(BaseModel):
    model_config = ConfigDict(frozen=True)

    git_version: str
    object_format: str
    repository_id: str


class PreparedMerge(BaseModel):
    """The exact-merge-tree result: one complete subject, ready to gate."""

    model_config = ConfigDict(frozen=True)

    subject: MergeSubject


class MergeConflict(BaseModel):
    """Conflict is data, never an exception — a red check downstream."""

    model_config = ConfigDict(frozen=True)

    detail: str


class AlreadyIntegrated(BaseModel):
    """The candidate is already reachable from the target: nothing to merge —
    a reproduced run reports this truthfully instead of double-installing."""

    model_config = ConfigDict(frozen=True)

    target_ref: str
    base: GitSha


class InstallOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    installed: bool
    found_base: GitSha | None = None  # populated when the target genuinely moved


@dataclass(frozen=True)
class ReadSnapshot:
    """An exported, physically read-only tree. Implements WorkspaceView."""

    repository: str
    commit: GitSha
    _path: str

    @property
    def path(self) -> str:
        return self._path

    def git_ref(self) -> GitRef:
        return GitRef(repository=self.repository, commit=self.commit)


class StagedWriteWorkspace:
    """A staging repository + working tree. Implements WriteWorkspace.

    ``commit_all`` commits in staging, then the authority imports the exact
    object and pins it under an authority-owned candidate ref — the data
    plane crossing (I5) happens here, deterministically.
    """

    def __init__(
        self,
        *,
        authority: GitAuthority,
        base: GitSha,
        staging_dir: Path,
        candidate_ref: str,
    ) -> None:
        self._authority = authority
        self.base = base
        self._staging_dir = staging_dir
        self.candidate_ref = candidate_ref
        self._head: GitSha = base
        self._imported = False

    @property
    def path(self) -> str:
        return str(self._staging_dir)

    def git_ref(self) -> GitRef:
        return GitRef(
            repository=self._authority.repository_id,
            commit=self._head,
            diff_against=self.base,
        )

    def reset_to(self, ref: GitRef) -> None:
        """Reset this fresh staging repository to a prior durable candidate.

        The repository identity is checked, the exact commit is fetched and
        verified, and untracked/ignored files are removed so iteration state is
        exactly the GitRef — never a shared mutable worktree.
        """
        if self._imported:
            raise ContractViolation(
                "workspace.reset_to() is only valid before commit_all() imports "
                "this acquisition's candidate"
            )
        if ref.repository != self._authority.repository_id:
            raise ContractViolation(
                f"GitRef repository {ref.repository!r} does not match authority "
                f"{self._authority.repository_id!r}"
            )
        authority = self._authority
        authority._run(
            "fetch", "--quiet", authority.repository_id, ref.commit, cwd=self._staging_dir
        )
        kind = authority._run(
            "cat-file", "-t", ref.commit, cwd=self._staging_dir
        ).stdout.strip()
        if kind != "commit":
            raise ContractViolation(f"reset target {ref.commit} is a {kind}, not a commit")
        authority._run("reset", "--hard", ref.commit, cwd=self._staging_dir)
        authority._run("clean", "-ffdqx", cwd=self._staging_dir)
        observed = authority._run(
            "rev-parse", "HEAD", cwd=self._staging_dir
        ).stdout.strip()
        if observed != str(ref.commit):
            raise ContractViolation(
                f"workspace reset observed HEAD {observed}, expected {ref.commit}"
            )
        self._head = ref.commit

    def commit_all(self, message: str) -> GitSha:
        authority = self._authority
        authority._run("add", "--all", cwd=self._staging_dir)
        status = authority._run(
            "status", "--porcelain", cwd=self._staging_dir
        ).stdout.strip()
        if status:
            authority._run(
                "commit",
                "--no-gpg-sign",
                "--file",
                "-",
                cwd=self._staging_dir,
                input_text=message,
            )
        head = GitSha(
            authority._run("rev-parse", "HEAD", cwd=self._staging_dir).stdout.strip()
        )
        authority.import_candidate(
            staging_dir=self._staging_dir, commit=head, candidate_ref=self.candidate_ref
        )
        self._head = head
        self._imported = True
        return head


class GitAuthority:
    def __init__(self, repo_path: Path | str, workspaces_root: Path | str) -> None:
        self._repo = Path(repo_path)
        self._root = Path(workspaces_root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._snapshot_seq = 0
        version_text = self._run("--version", cwd=None).stdout.strip()
        parts = version_text.split()[-1].split(".")
        version = (int(parts[0]), int(parts[1]))
        if version < MIN_GIT:
            raise ContractViolation(
                f"git {version_text!r} < {MIN_GIT[0]}.{MIN_GIT[1]} — "
                "merge-tree --write-tree is required"
            )
        bare = self._run("rev-parse", "--is-bare-repository").stdout.strip()
        if bare != "true":
            raise ContractViolation(
                f"authority repository {self._repo} must be bare: an update-ref "
                "under a live checkout silently corrupts the working tree"
            )
        object_format = self._run(
            "rev-parse", "--show-object-format"
        ).stdout.strip()
        self.repository_id = str(self._repo)
        self.environment = GitEnvironment(
            git_version=version_text,
            object_format=object_format,
            repository_id=self.repository_id,
        )
        self._install_deny_push_hook()

    def _install_deny_push_hook(self) -> None:
        """Physically refuse every push: ordinary git commands cannot reach
        authority refs from outside — the only install path is the effect."""
        hooks = self._repo / "hooks"
        hooks.mkdir(exist_ok=True)
        hook = hooks / "pre-receive"
        hook.write_text(
            "#!/bin/sh\n"
            "echo 'constructicon authority: pushes are refused;"
            " the only install path is merge_verified' >&2\n"
            "exit 1\n"
        )
        os.chmod(hook, 0o755)

    # -- plumbing -------------------------------------------------------------

    def _run(
        self,
        *args: str,
        cwd: Path | str | None = "AUTHORITY",
        check: bool = True,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(_PINNED_ENV)
        directory = self._repo if cwd == "AUTHORITY" else cwd
        raw_result = subprocess.run(  # never a shell; messages via exact bytes
            ["git", *args],
            cwd=directory,
            env=env,
            input=input_text.encode("utf-8") if input_text is not None else None,
            capture_output=True,
            check=False,
            timeout=60,
        )
        result = subprocess.CompletedProcess(
            args=raw_result.args,
            returncode=raw_result.returncode,
            stdout=raw_result.stdout.decode("utf-8", errors="replace"),
            stderr=raw_result.stderr.decode("utf-8", errors="replace"),
        )
        if check and result.returncode != 0:
            raise ContractViolation(
                f"git {' '.join(args[:3])} failed ({result.returncode}): "
                f"{result.stderr.strip()[:500]}"
            )
        return result

    def read_ref(self, ref: str) -> GitSha | None:
        result = self._run("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
        if result.returncode != 0:
            return None
        return GitSha(result.stdout.strip())

    def resolve_ref(self, ref: str) -> GitSha:
        if not ref.startswith("refs/"):
            raise ContractViolation(
                f"ref {ref!r} must be fully qualified (refs/heads/…) — the "
                "authority never guesses shorthand"
            )
        sha = self.read_ref(ref)
        if sha is None:
            raise ContractViolation(f"ref {ref!r} does not exist in the authority")
        return sha

    def tree_of(self, commit: GitSha) -> GitSha:
        return GitSha(self._run("rev-parse", f"{commit}^{{tree}}").stdout.strip())

    def parents_of(self, commit: GitSha) -> tuple[GitSha, ...]:
        out = self._run("rev-list", "--parents", "-n", "1", commit).stdout.split()
        return tuple(GitSha(sha) for sha in out[1:])

    def is_ancestor(self, commit: GitSha, ref: str) -> bool:
        result = self._run(
            "merge-base", "--is-ancestor", commit, ref, check=False
        )
        return result.returncode == 0

    # -- read snapshots (exported trees) --------------------------------------

    def read_snapshot(self, commit: GitSha) -> ReadSnapshot:
        self._snapshot_seq += 1
        dest = self._root / "snapshots" / f"{commit[:16]}-{self._snapshot_seq}"
        dest.mkdir(parents=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(_PINNED_ENV)
        archive = subprocess.run(
            ["git", "archive", "--format=tar", commit],
            cwd=self._repo,
            env=env,
            capture_output=True,
            check=True,
            timeout=60,
        )
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            tar.extractall(dest, filter="data")
        _set_write_bits(dest, writable=False)
        return ReadSnapshot(repository=self.repository_id, commit=commit, _path=str(dest))

    def discard_snapshot(self, snapshot: ReadSnapshot) -> None:
        _remove_tree(Path(snapshot.path), best_effort=True)

    def content_digest(self, path: Path | str) -> Digest:
        """Deterministic content identity of a tree on disk — the post-gate
        clean-tree verification (a gate cannot go green by mutating what it
        tests)."""
        entries: list[tuple[str, str]] = []
        root = Path(path)
        for file in sorted(p for p in root.rglob("*")):
            rel = str(file.relative_to(root))
            if file.is_symlink():
                entries.append((rel, f"link:{os.readlink(file)}"))
            elif file.is_file():
                entries.append(
                    (rel, str(digest("file", 1, file.read_bytes().hex())))
                )
        return digest("tree-content", 1, entries)

    # -- staging (the WRITE boundary) -----------------------------------------

    def acquire_write(
        self, *, acquisition_id: str, target_ref: str, candidate_ref: str
    ) -> StagedWriteWorkspace:
        base = self.resolve_ref(target_ref)
        staging = self._root / "staging" / acquisition_id
        if staging.exists():  # crash-and-retry within one epoch: start clean
            _remove_tree(staging)
        staging.mkdir(parents=True)
        self._run("init", "--quiet", "--initial-branch", "work", cwd=staging)
        self._run("fetch", "--quiet", str(self._repo), base, cwd=staging)
        self._run("checkout", "--quiet", "-B", "work", base, cwd=staging)
        return StagedWriteWorkspace(
            authority=self,
            base=base,
            staging_dir=staging,
            candidate_ref=candidate_ref,
        )

    def import_candidate(
        self, *, staging_dir: Path, commit: GitSha, candidate_ref: str
    ) -> None:
        """Authority-side import: fetch the exact object, pin it under an
        authority-owned candidate ref (write-once; identical is idempotent)."""
        self._run("fetch", "--quiet", str(staging_dir), commit)
        kind = self._run("cat-file", "-t", commit).stdout.strip()
        if kind != "commit":
            raise ContractViolation(f"candidate {commit} is a {kind}, not a commit")
        current = self.read_ref(candidate_ref)
        if current == commit:
            return
        if current is None:
            self._update_ref("create", candidate_ref, commit)
        else:
            raise ContractViolation(
                f"candidate ref {candidate_ref!r} already pins {current}; "
                f"refusing to move it to {commit}"
            )

    def discard_staging(self, acquisition_id: str) -> bool:
        staging = self._root / "staging" / acquisition_id
        if staging.exists():
            _remove_tree(staging, best_effort=True)
            return True
        return False

    def delete_ref_cas(self, ref: str, expected: GitSha) -> bool:
        """CAS delete; a ref that moved is reported, never deleted."""
        result = self._run("update-ref", "-d", ref, expected, check=False)
        return result.returncode == 0

    # -- the exact merge ------------------------------------------------------

    def prepare_merge(
        self, candidate: GitSha, target_ref: str
    ) -> PreparedMerge | MergeConflict | AlreadyIntegrated:
        base = self.resolve_ref(target_ref)
        if candidate == base or self.is_ancestor(candidate, target_ref):
            return AlreadyIntegrated(target_ref=target_ref, base=base)
        result = self._run(
            "merge-tree", "--write-tree", base, candidate, check=False
        )
        if result.returncode == 1:
            return MergeConflict(detail=result.stdout.strip()[:2000])
        if result.returncode != 0:
            raise ContractViolation(
                f"merge-tree failed ({result.returncode}): {result.stderr.strip()[:500]}"
            )
        tree = GitSha(result.stdout.splitlines()[0].strip())
        merge_commit = GitSha(
            self._run(
                "commit-tree",
                tree,
                "-p",
                base,
                "-p",
                candidate,
                "--no-gpg-sign",
                input_text=(
                    f"constructicon: verified merge of {candidate} into {target_ref}"
                ),
            ).stdout.strip()
        )
        return PreparedMerge(
            subject=MergeSubject(
                repository=self.repository_id,
                target_ref=target_ref,
                candidate=candidate,
                expected_base=base,
                merge_commit=merge_commit,
                tested_tree=tree,
            )
        )

    # -- install: one git ref transaction -------------------------------------

    @staticmethod
    def marker_ref(idempotency_key: Digest) -> str:
        return "refs/constructicon/effects/" + str(idempotency_key).removeprefix(
            "sha256:"
        )

    def _update_ref(self, verb: str, ref: str, new: GitSha, old: GitSha | None = None) -> None:
        line = f"{verb} {ref} {new}" + (f" {old}" if old is not None else "")
        self._run("update-ref", "--stdin", input_text=line + "\n")

    def _ref_transaction(self, lines: list[str]) -> subprocess.CompletedProcess[str]:
        script = "start\n" + "\n".join(lines) + "\nprepare\ncommit\n"
        return self._run("update-ref", "--stdin", input_text=script, check=False)

    def install(self, subject: MergeSubject, idempotency_key: Digest) -> InstallOutcome:
        """CAS-move the target AND create the marker, atomically. On a failed
        transaction the ref is re-read: only a genuine move is a rejection;
        an unchanged ref is transient lock contention (retry once, then
        raise) — never a receipt from an ambiguous exit."""
        marker = self.marker_ref(idempotency_key)
        lines = [
            f"update {subject.target_ref} {subject.merge_commit} {subject.expected_base}",
            f"create {marker} {subject.merge_commit}",
        ]
        for attempt in (1, 2):
            result = self._ref_transaction(lines)
            if result.returncode == 0:
                return InstallOutcome(installed=True)
            # disambiguate: racing identical install, genuine move, or lock
            if self.read_ref(marker) == subject.merge_commit:
                return InstallOutcome(installed=True)
            current = self.read_ref(subject.target_ref)
            if current == subject.merge_commit:
                self._run(  # the racing actor's marker create; best-effort
                    "update-ref", marker, subject.merge_commit, check=False
                )
                return InstallOutcome(installed=True)
            if current != subject.expected_base:
                return InstallOutcome(installed=False, found_base=current)
            if attempt == 2:
                raise GitAuthorityDamaged(
                    f"install transaction failed twice with an unmoved target: "
                    f"{result.stderr.strip()[:500]}"
                )
        raise AssertionError("unreachable")

    def reconcile_install(
        self, subject: MergeSubject, idempotency_key: Digest
    ) -> bool | None:
        """True -> committed; None -> definitively absent (safe to execute).
        The marker is correctness; the reflog stays audit-only."""
        marker = self.read_ref(self.marker_ref(idempotency_key))
        if marker is not None:
            if marker == subject.merge_commit:
                return True
            raise GitAuthorityDamaged(
                f"effect marker for {idempotency_key} points at {marker}, "
                f"not the subject's {subject.merge_commit}"
            )
        current = self.read_ref(subject.target_ref)
        if current == subject.merge_commit or (
            current is not None and self.is_ancestor(subject.merge_commit, subject.target_ref)
        ):
            # installed by an identical racing actor; restore the marker
            self._run(
                "update-ref",
                self.marker_ref(idempotency_key),
                subject.merge_commit,
                check=False,
            )
            return True
        return None


class GitWorkspaceCapability:
    """The leased WRITE-workspace capability (implements ``LeasedCapability``).

    One invocation gets one staging repository. A later loop iteration may
    reset that fresh repository to the prior checkpointed ``GitRef``. Release
    removes mutable staging while retaining the authority-owned candidate ref;
    discard removes both staging and the uncheckpointed candidate ref.
    """

    def __init__(self, authority: GitAuthority, *, target_ref: str) -> None:
        self._authority = authority
        self.target_ref = target_ref

    def _candidate_ref(self, run_id: str, acquisition_id: str) -> str:
        safe_run = "".join(c if c.isalnum() or c in "-_" else "-" for c in run_id)
        return f"refs/candidates/{safe_run}/{acquisition_id}"

    async def acquire(self, context: LeaseContext) -> AcquiredCapability:
        run_id = context.run_lease.run_id
        lease_id = lease_id_for(run_id, context.path, context.binding.binding)
        acquisition_id = acquisition_id_for(lease_id, context.run_lease.epoch)
        candidate_ref = self._candidate_ref(run_id, acquisition_id)
        workspace = self._authority.acquire_write(
            acquisition_id=acquisition_id,
            target_ref=self.target_ref,
            candidate_ref=candidate_ref,
        )
        resource_ref = canonical_json(
            {
                "acquisition": acquisition_id,
                "candidate_ref": candidate_ref,
                "base": str(workspace.base),
            }
        )
        return AcquiredCapability(
            resource=workspace,
            lease_id=lease_id,
            acquisition_id=acquisition_id,
            resource_ref=resource_ref,
        )

    async def close(
        self, acquisition: AcquiredCapability, disposition: Disposition
    ) -> LeaseClosure:
        info = json.loads(acquisition.resource_ref)
        self._authority.discard_staging(info["acquisition"])
        if disposition == "discard":
            self._discard_candidate(info["candidate_ref"])
            return LeaseClosure(disposition="discarded")
        return LeaseClosure(disposition="released")

    async def reconcile(
        self, context: LeaseContext, stale: tuple[StaleAcquisition, ...]
    ) -> LeaseReconciliation:
        reaped: list[str] = []
        for item in stale:
            if item.lease.resource_ref is None:
                continue
            info = json.loads(item.lease.resource_ref)
            removed = self._authority.discard_staging(info["acquisition"])
            if item.disposition == "discard":
                self._discard_candidate(info["candidate_ref"])
                removed = True
            if removed:
                reaped.append(item.lease.resource_ref)
        return LeaseReconciliation(reaped=tuple(reaped))

    def _discard_candidate(self, candidate_ref: str) -> None:
        current = self._authority.read_ref(candidate_ref)
        if current is not None:
            self._authority.delete_ref_cas(candidate_ref, current)


def _set_write_bits(root: Path, *, writable: bool) -> None:
    """Symlink-safe: chmod never follows links; files AND directories, so
    creation fails too, not just edits."""
    paths = [root, *root.rglob("*")]
    ordered = sorted(paths, key=lambda p: len(p.parts), reverse=not writable)
    for path in ordered:
        if path.is_symlink():
            continue
        mode = stat.S_IMODE(os.lstat(path).st_mode)
        if writable:
            os.chmod(path, mode | stat.S_IWUSR)
        else:
            os.chmod(path, mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def _remove_tree(root: Path, *, best_effort: bool = False) -> None:
    """Remove a completed Git tree even when Windows retained read-only bits.

    Clearing the bits up front is the whole job — a removal-time retry hook
    would only rediscover lazily what ``_set_write_bits`` already knows.
    ``best_effort`` keeps the discard paths' ``ignore_errors`` contract: a tree
    another process still holds open must never make cleanup a caller fault.
    """

    try:
        _set_write_bits(root, writable=True)
    except OSError:
        if not best_effort:
            raise
    shutil.rmtree(root, ignore_errors=best_effort)
