"""The WRITE capture exports its base's whole ancestry, unmeasured since generation 16 (#423).

``ContainedWriteWorkspaceProvider.require_capture_headroom`` refuses at assembly when
the pinned base's ancestry leaves no room under ``MAINTENANCE_PACK_LIMITS``: "Git base
leaves no capture object headroom" or "Git base leaves no expanded capture headroom".
The CI scope script's ``capture-headroom`` command measures HEAD as the next candidate
base. Only verify.yml runs it, on full history.

It says that candidate leaves about forty captures of room in objects and in expanded
bytes, measured as the guard measures them. It does not decide for the actual pin,
which the assembly guard still does, nor say the compressed pack fits its wire bound.
"""

import asyncio
import shutil
import subprocess
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.ci import m8_ci_scope as scope

from constructicon.api.maintenance_entry import MAINTENANCE_PACK_LIMITS
from constructicon.core.address import GitSha
from constructicon.core.errors import ContractViolation
from constructicon.substrate.executors.linux import ProcessLimits
from constructicon.substrate.git.capture import ContainedWriteWorkspaceProvider
from constructicon.substrate.git.contained import ContainedWorkspaceProvider
from constructicon.substrate.git.pack import PackLimits
from tests.test_verify_scope import _job

ROOT = Path(__file__).resolve().parents[1]
CHECKOUT = pytest.mark.skipif(
    shutil.which("git") is None or not (ROOT / ".git").exists(),
    reason="needs this repository's Git checkout",
)
COMMAND = "      - run: python3 scripts/ci/m8_ci_scope.py capture-headroom\n"


def _git(*arguments: str) -> str:
    return subprocess.run(["git", *arguments], cwd=ROOT, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, check=True).stdout.strip()


def _guard(limits: PackLimits) -> None:
    """The producer's own guard, on this checkout as its authority."""
    provider = SimpleNamespace(
        git=shutil.which("git"), launcher=SimpleNamespace(limits=ProcessLimits()),
        authority=SimpleNamespace(repository_id=ROOT, environment=SimpleNamespace(
            object_format=_git("rev-parse", "--show-object-format"))),
        pack_limits=limits,
    )
    provider._export = partial(ContainedWorkspaceProvider._export, provider)
    head = GitSha(_git("rev-parse", "HEAD"))
    asyncio.run(ContainedWriteWorkspaceProvider.require_capture_headroom(provider, head))


def test_the_scope_script_restates_the_maintenance_capture_bounds_exactly():
    assert MAINTENANCE_PACK_LIMITS.expanded_bytes == scope.CAPTURE_EXPANDED_BOUND
    assert MAINTENANCE_PACK_LIMITS.objects == scope.CAPTURE_OBJECT_BOUND
    assert scope.REQUIRED_CAPTURE_MARGIN > 0 and scope.REQUIRED_CAPTURE_OBJECTS > 0


def test_only_full_history_jobs_run_the_check():
    for name in ("docs", "verify"):
        job = _job(name)
        assert COMMAND in job and "          fetch-depth: 0\n" in job
    containment = (ROOT / ".github/workflows/m8-containment.yml").read_text(encoding="utf-8")
    assert "capture-headroom" not in containment


@CHECKOUT
def test_the_producers_guard_refuses_exactly_where_the_script_measures():
    size, count = scope.verify_capture_headroom(ROOT)
    _guard(PackLimits(objects=count + 1, expanded_bytes=size + 1))
    with pytest.raises(ContractViolation, match="no capture object headroom"):
        _guard(PackLimits(objects=count, expanded_bytes=size + 1))
    with pytest.raises(ContractViolation, match="no expanded capture headroom"):
        _guard(PackLimits(objects=count + 1, expanded_bytes=size))


@CHECKOUT
def test_ambient_line_ending_configuration_does_not_change_the_measurement(monkeypatch):
    plain = scope.verify_capture_headroom(ROOT)
    for name, value in (("COUNT", "1"), ("KEY_0", "core.autocrlf"), ("VALUE_0", "true")):
        monkeypatch.setenv("GIT_CONFIG_" + name, value)
    assert scope.verify_capture_headroom(ROOT) == plain


@CHECKOUT
def test_a_shallow_clone_is_refused_by_name(tmp_path):
    clone = tmp_path / "shallow"
    subprocess.run(["git", "clone", "--quiet", "--depth", "1", ROOT.as_uri(), str(clone)],
                   stdin=subprocess.DEVNULL, capture_output=True, check=True)
    with pytest.raises(scope.ScopeError, match="capture-headroom-margin: HEAD's history"):
        scope.verify_capture_headroom(clone)


@CHECKOUT
def test_the_command_prints_the_candidate_base_and_reports_its_refusal(monkeypatch, capsys):
    size, count = scope.verify_capture_headroom(ROOT)
    assert scope.main(["capture-headroom", "--repository", str(ROOT)]) == 0
    bound, objects = scope.CAPTURE_EXPANDED_BOUND, scope.CAPTURE_OBJECT_BOUND
    assert (f"next candidate base (HEAD): {size} of {bound} expanded bytes, {bound - size} "
            f"to spare; {count} of {objects} objects, {objects - count} to spare"
            in capsys.readouterr().out)

    def refuse(repository):
        raise scope.ScopeError("capture-headroom-margin: full")

    monkeypatch.setattr(scope, "verify_capture_headroom", refuse)
    assert scope.main(["capture-headroom", "--repository", str(ROOT)]) == 2
    assert "capture-headroom-margin" in capsys.readouterr().err
    assert scope.main(["docs", "--repository", str(ROOT)]) == 0


@CHECKOUT
def test_an_ancestry_at_the_byte_margin_is_refused_by_name():
    size, _ = scope.verify_capture_headroom(ROOT)
    bound = size + scope.REQUIRED_CAPTURE_MARGIN
    scope.verify_capture_headroom(ROOT, bound)
    with pytest.raises(scope.ScopeError, match=r"base \(HEAD\) expands to"):
        scope.verify_capture_headroom(ROOT, bound - 1)


@CHECKOUT
def test_an_ancestry_at_the_object_margin_is_refused_by_name():
    _, count = scope.verify_capture_headroom(ROOT)
    bound = count + scope.REQUIRED_CAPTURE_OBJECTS
    scope.verify_capture_headroom(ROOT, object_bound=bound)
    with pytest.raises(scope.ScopeError, match=r"base \(HEAD\) has \d+ objects"):
        scope.verify_capture_headroom(ROOT, object_bound=bound - 1)
