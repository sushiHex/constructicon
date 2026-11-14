"""The WRITE capture exports the base's whole ancestry, unmeasured since generation 16 (#423).

``ContainedWriteWorkspaceProvider.require_capture_headroom`` refuses at assembly with
"Git base leaves no expanded capture headroom" once the ancestry's expanded objects
reach ``MAINTENANCE_PACK_LIMITS.expanded_bytes``. The check lives in the CI scope
script so prose-only changes run it too.

It says HEAD's ancestry leaves one MiB under that bound, measured as the guard
measures it. It does not say a given capture's own objects fit, nor that the
compressed pack fits its separate wire bound.
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

ROOT = Path(__file__).resolve().parents[1]
CHECKOUT = pytest.mark.skipif(
    shutil.which("git") is None or not (ROOT / ".git").exists(),
    reason="needs this repository's Git checkout",
)


def _git(*arguments: str) -> str:
    return subprocess.run(["git", *arguments], cwd=ROOT, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, check=True).stdout.strip()


def _guard(expanded_bytes: int) -> None:
    """The producer's own guard, on this checkout as its authority."""
    provider = SimpleNamespace(
        git=shutil.which("git"), launcher=SimpleNamespace(limits=ProcessLimits()),
        authority=SimpleNamespace(repository_id=ROOT, environment=SimpleNamespace(
            object_format=_git("rev-parse", "--show-object-format"))),
        pack_limits=PackLimits(expanded_bytes=expanded_bytes),
    )
    provider._export = partial(ContainedWorkspaceProvider._export, provider)
    head = GitSha(_git("rev-parse", "HEAD"))
    asyncio.run(ContainedWriteWorkspaceProvider.require_capture_headroom(provider, head))


def test_the_scope_script_restates_the_maintenance_capture_bounds_exactly():
    assert MAINTENANCE_PACK_LIMITS.expanded_bytes == scope.CAPTURE_EXPANDED_BOUND
    assert MAINTENANCE_PACK_LIMITS.objects == scope.CAPTURE_OBJECT_BOUND
    assert scope.REQUIRED_CAPTURE_MARGIN > 0


@CHECKOUT
def test_the_producers_guard_refuses_exactly_where_the_script_measures():
    size = scope.CAPTURE_EXPANDED_BOUND - scope.verify_capture_headroom(ROOT)
    _guard(size + 1)
    with pytest.raises(ContractViolation, match="no expanded capture headroom"):
        _guard(size)


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
def test_the_docs_command_prints_the_headroom_and_reports_its_refusal(monkeypatch, capsys):
    headroom = scope.verify_capture_headroom(ROOT)
    assert scope.main(["docs", "--repository", str(ROOT)]) == 0
    assert (f"capture headroom: {scope.CAPTURE_EXPANDED_BOUND - headroom} of "
            f"{scope.CAPTURE_EXPANDED_BOUND} expanded bytes, {headroom} to spare"
            in capsys.readouterr().out)

    def refuse(repository):
        raise scope.ScopeError("capture-headroom-margin: full")

    monkeypatch.setattr(scope, "verify_capture_headroom", refuse)
    assert scope.main(["docs", "--repository", str(ROOT)]) == 2
    assert "capture-headroom-margin" in capsys.readouterr().err


@CHECKOUT
def test_an_ancestry_at_the_margin_is_refused_by_name():
    size = scope.CAPTURE_EXPANDED_BOUND - scope.verify_capture_headroom(ROOT)
    bound = size + scope.REQUIRED_CAPTURE_MARGIN
    assert scope.verify_capture_headroom(ROOT, bound) == scope.REQUIRED_CAPTURE_MARGIN
    with pytest.raises(scope.ScopeError, match="capture-headroom-margin: HEAD's ancestry expands"):
        scope.verify_capture_headroom(ROOT, bound - 1)
