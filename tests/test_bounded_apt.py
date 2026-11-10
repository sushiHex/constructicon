"""APT provisioning ends within its bound, or refuses with a named reason (#291)."""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from scripts.ci import qualify_m8_runner

from tests.git_bash import git_bash

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ci/bounded_apt.sh"
WORKFLOWS = ROOT / ".github/workflows"
BOUND = 120
"""Measured successful provisioning (#291, 72 hosted jobs): update max 26s, install max 5.6s."""
UPDATE = f"          sudo bash scripts/ci/bounded_apt.sh {BOUND} -q update --error-on=any\n"
INSTALL = (f"          sudo bash scripts/ci/bounded_apt.sh {BOUND} -q -y install "
           f"--no-install-recommends bubblewrap={qualify_m8_runner.PACKAGE}\n")
SITES = ("m8-containment.yml", "m8-runner-qualification.yml", "m8-pi-local-read.yml")
KILL_AFTER = 10


def workflow_files() -> list[Path]:
    return sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])


def test_every_apt_command_in_a_workflow_is_the_bounded_pinned_pair() -> None:
    for path in workflow_files():
        text = path.read_text(encoding="utf-8")
        if path.name not in SITES:
            assert "apt-get" not in text and "bounded_apt" not in text, path.name
            continue
        assert text.count(UPDATE) == 1 and text.count(INSTALL) == 1, path.name
        # No apt command outside the two bounded lines, under any spelling.
        rest = text.replace(UPDATE, "").replace(INSTALL, "")
        assert not re.search(r"\bapt(-get)?\b|bounded_apt", rest), path.name
        assert text.index(UPDATE) < text.index(INSTALL) < text.index("sudo useradd")


def run(tmp_path: Path, bound: int, *arguments: str, behavior: str = "ok",
        real: bool = False) -> tuple[subprocess.CompletedProcess[str], float]:
    env = dict(os.environ)
    if not real:
        fake = tmp_path / "bin"
        fake.mkdir(exist_ok=True)
        (fake / "apt-get").write_text(
            """#!/bin/bash
case "$FAKE_APT" in
  ok) exit 0;;
  fail) echo 'E: index unavailable' >&2; exit 100;;
  stall) sleep 300 & printf '%s' "$!" > "$METHOD_PID"; wait;;
  stubborn) trap '' TERM; sleep 300 & printf '%s' "$!" > "$METHOD_PID"; wait;;
esac
""", encoding="utf-8", newline="\n")
        (fake / "apt-get").chmod(0o755)
        env.update(PATH=f"{fake.as_posix()}{os.pathsep}{env['PATH']}", FAKE_APT=behavior,
                   METHOD_PID=(tmp_path / "method.pid").as_posix())
    started = time.monotonic()
    result = subprocess.run(
        [git_bash(), SCRIPT.as_posix(), str(bound), *arguments],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env,
        timeout=bound + KILL_AFTER + 60,
    )
    return result, time.monotonic() - started


def method_alive(tmp_path: Path) -> bool:
    pid = (tmp_path / "method.pid").read_text(encoding="utf-8")
    probe = subprocess.run([git_bash(), "-c", f"kill -0 {pid}"], stdin=subprocess.DEVNULL,
                           capture_output=True, check=False)
    return probe.returncode == 0


@pytest.mark.parametrize("arguments", [(), ("x",), ("0", "update"), ("2s", "update"),
                                       ("-1", "update"), ("", "update")])
def test_usage_is_refused_without_running_apt(tmp_path: Path, arguments: tuple[str, ...]) -> None:
    fake = tmp_path / "bin"
    fake.mkdir()
    marker = tmp_path / "ran"
    (fake / "apt-get").write_text(f"#!/bin/bash\n: > '{marker.as_posix()}'\n",
                                  encoding="utf-8", newline="\n")
    (fake / "apt-get").chmod(0o755)
    result = subprocess.run(
        [git_bash(), SCRIPT.as_posix(), *arguments], stdin=subprocess.DEVNULL,
        capture_output=True, text=True,
        env={**os.environ, "PATH": f"{fake.as_posix()}{os.pathsep}{os.environ['PATH']}"},
    )
    assert result.returncode == 2
    assert result.stderr.startswith("bounded-apt-usage: ")
    assert not marker.exists()


def test_success_and_apt_failure_keep_apt_status(tmp_path: Path) -> None:
    ok, _ = run(tmp_path, 5, "-q", "update", behavior="ok")
    assert (ok.returncode, ok.stdout, ok.stderr) == (0, "", "")
    failed, elapsed = run(tmp_path, 5, "-q", "update", behavior="fail")
    assert failed.returncode == 100 and elapsed < 5
    assert failed.stdout == "::error title=APT provisioning failed::apt-get -q update exited 100\n"
    assert failed.stderr.endswith("apt-provisioning-failed: apt-get -q update exited 100\n")


@pytest.mark.parametrize("behavior", ["stall", "stubborn"])
def test_a_stalled_command_and_its_methods_stop_at_the_bound(
    tmp_path: Path, behavior: str,
) -> None:
    bound = 2
    result, elapsed = run(tmp_path, bound, "-q", "update", behavior=behavior)
    assert result.returncode == 124
    assert result.stdout == (
        f"::error title=APT provisioning bound::apt-get -q update did not finish within {bound}s\n"
    )
    # After KILL, timeout's own group kill makes bash report it "Killed" (status 137) first.
    assert result.stderr.endswith(
        f"apt-provisioning-timeout: apt-get -q update exceeded {bound}s\n"
    )
    assert result.stderr.count("\n") == (2 if behavior == "stubborn" else 1)
    # TERM at the bound; a command ignoring TERM is killed KILL_AFTER later.
    floor = bound + (KILL_AFTER if behavior == "stubborn" else 0)
    assert floor <= elapsed < floor + 8, elapsed
    assert not method_alive(tmp_path)


class Blackhole:
    """A local index server that accepts connections and never answers."""

    def __init__(self) -> None:
        self.server = socket.create_server(("127.0.0.1", 0))
        self.held: list[socket.socket] = []
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return self.server.getsockname()[1]

    def _accept(self) -> None:
        while True:
            try:
                connection, _ = self.server.accept()
            except OSError:
                return
            self.held.append(connection)

    def close(self) -> None:
        self.server.close()
        for connection in self.held:
            connection.close()


def refused_port() -> int:
    with socket.create_server(("127.0.0.1", 0)) as probe:
        return probe.getsockname()[1]


def offline_apt(tmp_path: Path, port: int) -> tuple[str, ...]:
    """Options confining a real non-root `apt-get update` to one local index."""
    sources = tmp_path / "sources.list"
    sources.write_text(f"deb [trusted=yes] http://127.0.0.1:{port}/ubuntu noble main\n",
                       encoding="utf-8")
    for directory in ("parts", "lists/partial", "cache/archives/partial"):
        (tmp_path / directory).mkdir(parents=True, exist_ok=True)
    return (
        "-o", f"Dir::Etc::SourceList={sources}",
        "-o", f"Dir::Etc::SourceParts={tmp_path / 'parts'}",
        "-o", f"Dir::State::Lists={tmp_path / 'lists'}", "-o", f"Dir::Cache={tmp_path / 'cache'}",
        "-o", "Dir::Cache::pkgcache=", "-o", "Dir::Cache::srcpkgcache=",
        "-o", "Debug::NoLocking=1", "-o", "Acquire::Retries=0",
    )


def workflow_update_arguments() -> tuple[str, ...]:
    return tuple(UPDATE.split(f"bounded_apt.sh {BOUND} ", 1)[1].split())


HOSTED_LINUX = (sys.platform.startswith("linux")
                and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted")
# Required where CI runs it, so the hosted evidence cannot become a silent skip.
real_apt = pytest.mark.skipif(
    not HOSTED_LINUX and (not sys.platform.startswith("linux") or shutil.which("apt-get") is None),
    reason="real apt-get runs only on a Linux host that has it",
)


@real_apt
def test_real_apt_against_a_stalled_index_refuses_at_its_own_bound(tmp_path: Path) -> None:
    hole = Blackhole()
    try:
        bound = 5
        result, elapsed = run(tmp_path, bound, *workflow_update_arguments(),
                              *offline_apt(tmp_path, hole.port), real=True)
    finally:
        hole.close()
    assert result.returncode == 124, (result.stdout, result.stderr)
    assert "::error title=APT provisioning bound::apt-get -q update --error-on=any" in result.stdout
    assert result.stderr.endswith(f"exceeded {bound}s\n")
    assert bound <= elapsed < bound + KILL_AFTER + 5, elapsed


@real_apt
def test_real_apt_against_a_refused_index_fails_before_its_bound(tmp_path: Path) -> None:
    port = refused_port()
    result, elapsed = run(tmp_path, 60, *workflow_update_arguments(),
                          *offline_apt(tmp_path, port), real=True)
    assert result.returncode == 100, (result.stdout, result.stderr)
    assert ("::error title=APT provisioning failed::apt-get -q update --error-on=any"
            in result.stdout)
    assert elapsed < 60
    # Without --error-on=any the same unobtainable index is only a warning.
    lenient = subprocess.run(
        ["apt-get", "-q", "update", *offline_apt(tmp_path, port)],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
    )
    assert lenient.returncode == 0, (lenient.stdout, lenient.stderr)
    assert "W: " in lenient.stderr or "W: " in lenient.stdout
