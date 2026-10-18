"""Portable evidence for the explicitly synthetic peer, not Linux custody."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from dataclasses import replace

import pytest

from tests.isolated_startup import peer_program
from tests.substrate.test_codex_protocol import managed, spend_result


@pytest.mark.parametrize("plan", ["pro", "plus"])
def test_synthetic_startup_peer_answers_exactly_its_declared_protocol(tmp_path, plan):
    program = peer_program(plan)
    ast.parse(program)
    peer = tmp_path / "peer.py"
    peer.write_bytes(program)
    methods = ["initialize", "initialized", "account/read"]
    if plan == "pro":
        methods.append("account/rateLimits/read")
    requests = [{"method": method, **({} if method == "initialized" else {"id": index})}
                for index, method in enumerate(methods)]
    ran = subprocess.run([sys.executable, "-I", "-S", "-B", str(peer), "app-server",
                          "--strict-config", "--stdio"],
                         input=b"".join((json.dumps(request) + "\n").encode()
                                        for request in requests),
                         capture_output=True, timeout=10, check=False)
    expected = [{"id": 0, "result": {"ok": True}}, {"id": 2, "result": managed(planType=plan)}]
    if plan == "pro":
        expected.append({"id": 3, "result": spend_result()})
    assert (ran.returncode, ran.stdout, ran.stderr) == (
        0, b"".join((json.dumps(reply) + "\n").encode() for reply in expected), b"")


def test_synthetic_startup_peer_refuses_any_model_or_unexpected_method(tmp_path):
    peer = tmp_path / "peer.py"
    peer.write_bytes(peer_program("pro"))
    ran = subprocess.run([sys.executable, "-I", "-S", "-B", str(peer), "app-server",
                          "--strict-config", "--stdio"],
                         input=b'{"id":0,"method":"turn/start"}\n',
                         capture_output=True, timeout=10, check=False)
    assert (ran.returncode, ran.stdout, ran.stderr) == (
        3, b"", b"synthetic-startup-peer-refused\n")


def test_original_launcher_assembly_needs_no_installed_vendor_before_replacement(tmp_path):
    """Portable constructor evidence only: no probe or Linux execution occurs."""
    from constructicon.substrate.executors import codex_lane
    from constructicon.substrate.executors.linux import LinuxLauncher, NativeVendor

    manifest = {"runtime_digest": "sha256:" + "a" * 64, "apparmor_policy_sha256": "b" * 64}
    (tmp_path / "runtime.json").write_bytes(json.dumps(manifest).encode())
    original = codex_lane._launcher(tmp_path)
    assert not (tmp_path / "native-codex").exists()
    peer = NativeVendor(tmp_path / "synthetic-native", tmp_path / "synthetic-catalog.json")
    isolated = replace(original, vendor=peer)
    assert isinstance(isolated, LinuxLauncher) and isolated.vendor == peer
    assert replace(isolated, vendor=original.vendor) == original
    assert isolated.bubblewrap == original.bubblewrap
    assert isolated.runtime_root == original.runtime_root
    assert type(isolated).exchange is LinuxLauncher.exchange
