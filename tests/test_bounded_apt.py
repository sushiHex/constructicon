"""APT provisioning ends within its bound, or refuses with a named reason (#291)."""

from __future__ import annotations

import email.utils
import hashlib
import http.server
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


APT_USE = re.compile(r"\bapt(?:-get|itude)?\b|bounded_apt")


def test_every_apt_command_in_a_workflow_is_the_bounded_pinned_pair() -> None:
    found = []
    for path in workflow_files():
        text = path.read_text(encoding="utf-8")
        if path.name in SITES:
            assert text.count(UPDATE) == 1 and text.count(INSTALL) == 1, path.name
            assert text.index(UPDATE) < text.index(INSTALL) < text.index("sudo useradd")
            found.append(path.name)
            text = text.replace(UPDATE, "").replace(INSTALL, "")
        # No other apt use in any workflow, under any of apt's command spellings.
        assert not APT_USE.search(text), path.name
    assert sorted(found) == sorted(SITES)


@pytest.mark.parametrize("line", ["sudo apt update", "apt-get install x", "sudo aptitude -y",
                                  "bash scripts/ci/bounded_apt.sh 99 -q update"])
def test_the_workflow_guard_sees_other_apt_spellings(line: str) -> None:
    assert APT_USE.search(f"          {line}\n")


def run(tmp_path: Path, bound: int, *arguments: str, behavior: str = "ok",
        real: bool = False, extra_env: dict[str, str] | None = None,
        ) -> tuple[subprocess.CompletedProcess[str], float]:
    env = {**os.environ, **(extra_env or {})}
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
  killed) kill -KILL "$$";;
  orphan) (trap '' TERM; exec sleep 300) & printf '%s' "$!" > "$METHOD_PID"; wait;;
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


def process_running(pid: int) -> bool:
    """Whether a process exists and has not terminated.

    `kill -0` also succeeds for a zombie: a stopped method whose orphan was not
    yet reaped, as under a container PID 1 that reaps slowly. On Linux the
    kernel state decides, so zombie (Z) and dead (X) are terminated. Elsewhere
    the fakes run under Git Bash, whose process ids only its own `kill` knows.
    """
    if sys.platform.startswith("linux"):
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except (FileNotFoundError, ProcessLookupError):
            return False
        return state not in {"Z", "X"}
    probe = subprocess.run([git_bash(), "-c", f"kill -0 {pid}"], stdin=subprocess.DEVNULL,
                           capture_output=True, check=False)
    return probe.returncode == 0


def method_alive(tmp_path: Path) -> bool:
    return process_running(int((tmp_path / "method.pid").read_text(encoding="utf-8")))


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="kernel process state")
def test_the_liveness_probe_counts_a_running_method_and_not_a_zombie() -> None:
    running = subprocess.Popen(["sleep", "300"], stdin=subprocess.DEVNULL)
    exited = subprocess.Popen(["true"], stdin=subprocess.DEVNULL)
    try:
        # The running method still blocks success.
        assert process_running(running.pid)
        deadline = time.monotonic() + 10
        stat = Path(f"/proc/{exited.pid}/stat")
        # Unreaped until poll(): the exited child stays a zombie that kill -0 accepts.
        while stat.read_text().rsplit(")", 1)[1].split()[0] != "Z":
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert subprocess.run(["kill", "-0", str(exited.pid)], check=False).returncode == 0
        assert not process_running(exited.pid)
    finally:
        running.kill()
        running.wait()
        exited.wait()
    assert not process_running(running.pid)


@pytest.mark.parametrize("arguments", [
    (), ("x",), ("0", "update"), ("00", "update"), ("0120", "update"), ("2s", "update"),
    ("-1", "update"), ("", "update"), ("1.5", "update"),
])
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


@pytest.mark.parametrize("behavior", ["stall", "orphan"])
def test_a_stalled_command_and_its_methods_stop_at_the_bound(
    tmp_path: Path, behavior: str,
) -> None:
    # "orphan": apt-get exits on TERM while its method ignores TERM; the group
    # KILL after the bound still stops it, so it cannot hold the step open.
    bound = 2
    result, elapsed = run(tmp_path, bound, "-q", "update", behavior=behavior)
    assert (result.returncode, result.stdout, result.stderr) == (
        124,
        f"::error title=APT provisioning bound::apt-get -q update did not finish within {bound}s\n",
        f"apt-provisioning-timeout: apt-get -q update exceeded {bound}s\n",
    )
    assert bound <= elapsed < bound + 8, elapsed
    assert not method_alive(tmp_path)


KILLED = ("::error title=APT provisioning killed::apt-get -q update was killed; "
          "cause not established\n")


def test_a_command_ignoring_term_is_killed_but_not_called_a_timeout(tmp_path: Path) -> None:
    bound = 2
    result, elapsed = run(tmp_path, bound, "-q", "update", behavior="stubborn")
    assert (result.returncode, result.stdout) == (137, KILLED)
    # timeout's own group kill makes bash report it "Killed" before the named reason.
    assert result.stderr.endswith(
        f"apt-provisioning-killed: apt-get -q update was killed (bound {bound}s); "
        "cause not established\n"
    )
    assert "apt-provisioning-timeout" not in result.stderr
    assert bound + KILL_AFTER <= elapsed < bound + KILL_AFTER + 8, elapsed
    assert not method_alive(tmp_path)


def test_a_kill_from_elsewhere_before_the_bound_is_not_called_a_timeout(tmp_path: Path) -> None:
    result, elapsed = run(tmp_path, 60, "-q", "update", behavior="killed")
    assert (result.returncode, result.stdout) == (137, KILLED)
    assert "apt-provisioning-timeout" not in result.stderr and elapsed < 60


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


class Repository:
    """A local flat repository with a valid empty index, recording each request."""

    def __init__(self, root: Path) -> None:
        root.mkdir()
        (root / "Packages").write_bytes(b"")
        empty = hashlib.sha256(b"").hexdigest()
        (root / "Release").write_text(
            "Origin: fixture\nLabel: fixture\n"
            f"Date: {email.utils.formatdate(usegmt=True)}\n"
            f"SHA256:\n {empty} 0 Packages\n",
            encoding="utf-8", newline="\n",
        )
        self.requests: list[str] = []
        requests = self.requests

        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args: object, **kwargs: object) -> None:
                super().__init__(*args, directory=str(root), **kwargs)  # type: ignore[arg-type]

            def log_message(self, format: str, *args: object) -> None:
                requests.append(self.path)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def port(self) -> int:
        return self.server.server_address[1]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def refused_port() -> int:
    # The reservation is released before apt runs; another listener taking the
    # port in that window is the remaining nondeterminism, and the URL and
    # refusal assertions below would expose it.
    with socket.create_server(("127.0.0.1", 0)) as probe:
        return probe.getsockname()[1]


def offline_apt(tmp_path: Path, source: str) -> tuple[tuple[str, ...], dict[str, str]]:
    """Confine a real non-root `apt-get update` to one local index.

    `APT_CONFIG` is read before the host's configuration parts and main file,
    and moves both to empty locations, so host hooks, proxies, mirrors and
    retry settings do not apply. Proxy variables are cleared as well.
    """
    for directory in ("parts", "sources.d", "lists/partial", "cache/archives/partial", "etc"):
        (tmp_path / directory).mkdir(parents=True, exist_ok=True)
    sources = tmp_path / "sources.list"
    sources.write_text(source + "\n", encoding="utf-8")
    config = tmp_path / "apt.conf"
    config.write_text(
        f'Dir::Etc::Parts "{tmp_path / "parts"}";\n'
        f'Dir::Etc::Main "{tmp_path / "etc" / "apt.conf"}";\n'
        'Acquire::http::Proxy "DIRECT";\nAcquire::Retries "0";\n'
        # apt's own connection timeout stays above every bound used here.
        'Acquire::http::Timeout "120";\n',
        encoding="utf-8",
    )
    options = (
        "-o", f"Dir::Etc::SourceList={sources}",
        "-o", f"Dir::Etc::SourceParts={tmp_path / 'sources.d'}",
        "-o", f"Dir::State::Lists={tmp_path / 'lists'}",
        "-o", f"Dir::Cache={tmp_path / 'cache'}",
        "-o", "Dir::Cache::pkgcache=", "-o", "Dir::Cache::srcpkgcache=",
        "-o", "Debug::NoLocking=1",
    )
    env = {"APT_CONFIG": str(config), "http_proxy": "", "https_proxy": "",
           "HTTP_PROXY": "", "HTTPS_PROXY": "", "no_proxy": "*"}
    return options, env


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
def test_real_apt_accepts_an_available_local_index_with_the_workflow_arguments(
    tmp_path: Path,
) -> None:
    repository = Repository(tmp_path / "repository")
    try:
        options, env = offline_apt(
            tmp_path, f"deb [trusted=yes] http://127.0.0.1:{repository.port}/ ./")
        result, elapsed = run(tmp_path, 60, *workflow_update_arguments(), *options,
                              real=True, extra_env=env)
    finally:
        repository.close()
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "::error" not in result.stdout and "apt-provisioning-" not in result.stderr
    # A flat source is requested under "./"; its empty index is listed with size 0,
    # so apt needs no Packages download once it holds the Release file.
    assert "/./Release" in repository.requests
    assert any(path.name.endswith("_Release") for path in (tmp_path / "lists").iterdir())
    assert elapsed < 60


@real_apt
def test_real_apt_against_a_stalled_index_refuses_at_its_own_bound(tmp_path: Path) -> None:
    hole = Blackhole()
    bound = 5
    try:
        options, env = offline_apt(
            tmp_path, f"deb [trusted=yes] http://127.0.0.1:{hole.port}/ubuntu noble main")
        result, elapsed = run(tmp_path, bound, *workflow_update_arguments(), *options,
                              real=True, extra_env=env)
        connected = len(hole.held)
    finally:
        hole.close()
    # apt reached the fixture, which held it until the wrapper's bound, not apt's own.
    assert connected >= 1
    assert result.returncode == 124, (result.stdout, result.stderr)
    assert ("::error title=APT provisioning bound::apt-get -q update --error-on=any"
            in result.stdout)
    assert result.stderr.endswith(f"exceeded {bound}s\n")
    assert bound <= elapsed < bound + KILL_AFTER + 5, elapsed


@real_apt
def test_real_apt_against_a_refused_index_fails_before_its_bound(tmp_path: Path) -> None:
    port = refused_port()
    options, env = offline_apt(
        tmp_path, f"deb [trusted=yes] http://127.0.0.1:{port}/ubuntu noble main")
    result, elapsed = run(tmp_path, 60, *workflow_update_arguments(), *options,
                          real=True, extra_env=env)
    output = result.stdout + result.stderr
    assert result.returncode == 100, output
    assert ("::error title=APT provisioning failed::apt-get -q update --error-on=any"
            in result.stdout)
    assert f"127.0.0.1:{port}" in output and "refused" in output.lower(), output
    assert elapsed < 60
    # Without --error-on=any this transient fetch failure is only a warning.
    lenient = subprocess.run(
        ["apt-get", "-q", "update", *options], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=60, env={**os.environ, **env},
    )
    assert lenient.returncode == 0, (lenient.stdout, lenient.stderr)
    assert "W: " in lenient.stdout + lenient.stderr
