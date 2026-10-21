"""Private readiness is a trusted process observation, never a stdout claim."""

from __future__ import annotations

import io
import struct
from types import SimpleNamespace

import pytest

from constructicon.substrate.executors import _egress_bridge as bridge
from constructicon.substrate.executors import _supervisor as supervisor


@pytest.fixture
def observed(monkeypatch):
    state = {"label": supervisor.CLAUDE_NATIVE_LABEL.encode() + b"\n",
             "status": b"Name:\tclaude\nNoNewPrivs:\t1\n", "paths": []}

    def read(path, mode):
        assert mode == "rb"
        state["paths"].append(path)
        if state.get("missing"):
            raise FileNotFoundError(path)
        return io.BytesIO(state["label"] if path.endswith("current") else state["status"])

    monkeypatch.setattr(supervisor, "open", read, raising=False)
    return state


def test_native_label_is_read_from_exact_owned_pid_with_nnp(observed):
    assert supervisor._native_transition(123) is True
    assert observed["paths"] == ["/proc/123/attr/current", "/proc/123/status"]


@pytest.mark.parametrize("label", [b"unconfined\n", b"", b"native (complain)\n",
                                   supervisor.CLAUDE_NATIVE_LABEL.encode() + b"\x00"])
def test_unexpected_actual_label_refuses(observed, label):
    observed["label"] = label
    with pytest.raises(OSError, match="unexpected enforcing label"):
        supervisor._native_transition(123)


@pytest.mark.parametrize("status", [b"", b"NoNewPrivs:\t0\n", b"NotNoNewPrivs:\t1\n"])
def test_nnp_must_be_an_exact_affirmative_status_row(observed, status):
    observed["status"] = status
    with pytest.raises(OSError, match="no-new-privileges"):
        supervisor._native_transition(123)


@pytest.mark.parametrize("field,size", [("label", 1025), ("status", 16385)])
def test_process_observation_bounds_bind(observed, field, size):
    observed[field] = b"x" * size
    with pytest.raises(OSError, match="exceeded its bound"):
        supervisor._native_transition(123)


def test_bootstrap_and_disappeared_process_are_not_readiness(observed):
    observed["label"] = supervisor.CLAUDE_BOOTSTRAP_LABEL.encode() + b"\n"
    assert supervisor._native_transition(123) is False
    observed["missing"] = True
    assert supervisor._native_transition(123) is False


def test_only_exact_fixed_native_option_is_admitted():
    arguments = [f"--native-label={supervisor.CLAUDE_NATIVE_LABEL}", "/fixed"]
    assert supervisor._native_option(arguments) is True
    assert arguments == ["/fixed"]
    assert supervisor._native_option(arguments) is False
    assert supervisor._native_option([]) is False
    with pytest.raises(ValueError, match="fixed Claude"):
        supervisor._native_option(["--native-label=unconfined", "/fixed"])


@pytest.mark.parametrize("ready,expired,reaped", [
    (True, False, False), (False, False, False), (True, True, False), (True, False, True),
])
def test_namespace_readiness_is_private_and_requires_completed_observation(
    monkeypatch, ready, expired, reaped,
):
    monkeypatch.setattr(supervisor.sys, "platform", "linux")
    monkeypatch.setattr(supervisor.os, "getpid", lambda: 1)
    monkeypatch.setattr(supervisor.ctypes, "CDLL", lambda *a, **k: SimpleNamespace(
        prctl=lambda *a: 0))
    monkeypatch.setattr(supervisor.signal, "signal", lambda *a: None)
    monkeypatch.setattr(supervisor.select, "POLLIN", 1, raising=False)
    monkeypatch.setattr(supervisor.select, "POLLHUP", 2, raising=False)
    monkeypatch.setattr(supervisor.select, "POLLERR", 4, raising=False)
    monkeypatch.setattr(supervisor.select, "poll", lambda: SimpleNamespace(
        register=lambda *a: None, poll=lambda *a: []), raising=False)
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: 1)
    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda *a, **k: SimpleNamespace(
        pid=123, returncode=None))
    checked, records = [], []

    def transition(pid):
        checked.append(pid)
        return ready

    def reap(child, owner, shutdown, begin, force, *, observe):
        assert child.pid == 123 and owner == 44
        if expired:
            shutdown.request()
        if reaped:
            child.returncode = 0
        observe()
        observe()  # A second tick must not publish a second readiness fact.
        return 0

    monkeypatch.setattr(supervisor, "_native_transition", transition)
    monkeypatch.setattr(supervisor, "_reap", reap)
    control = SimpleNamespace(fileno=lambda: 44, sendall=records.append, send=records.append)
    result = supervisor.supervise_namespace(control, 10, ["/fixed"], native=True)
    admitted = ready and not expired and not reaped
    assert result == (0 if admitted else 125)
    assert records == ([b"\x01"] if admitted else []) + [struct.pack("!i", result)]
    assert checked == ([] if expired or reaped else [123] if ready else [123, 123])


def test_observer_failure_still_reaps_before_propagation(monkeypatch):
    monkeypatch.setattr(supervisor.sys, "platform", "linux")
    for name, value in (("POLLIN", 1), ("POLLHUP", 2), ("POLLERR", 4)):
        monkeypatch.setattr(supervisor.select, name, value, raising=False)
    monkeypatch.setattr(supervisor.select, "poll", lambda: SimpleNamespace(
        register=lambda *a: None, poll=lambda *a: []), raising=False)
    monkeypatch.setattr(supervisor.os, "WNOHANG", 1, raising=False)
    joined = []

    def waitpid(*args):
        joined.append(True)
        raise ChildProcessError

    def failed():
        raise OSError("observation failed")

    monkeypatch.setattr(supervisor.os, "waitpid", waitpid)
    with pytest.raises(OSError, match="observation failed"):
        supervisor._reap(SimpleNamespace(pid=123), 44, supervisor._Shutdown(9999999999),
                         lambda: 1, lambda: None, observe=failed)
    assert joined == [True]


@pytest.mark.parametrize("result", [0, -1])
def test_forwarder_protection_precedes_readiness_and_descriptor_isolation(monkeypatch, result):
    calls = []

    def prctl(*arguments):
        calls.append(arguments)
        return result

    monkeypatch.setattr(bridge.sys, "platform", "linux")
    monkeypatch.setattr(bridge.ctypes, "CDLL", lambda *a, **k: SimpleNamespace(prctl=prctl))
    monkeypatch.setattr(bridge.os, "open", lambda *a: calls.append("open") or 9)
    monkeypatch.setattr(bridge.os, "dup2", lambda *a: calls.append(a))
    monkeypatch.setattr(bridge.os, "listdir", lambda *a: ["0", "1", "2", "9", "10"])
    monkeypatch.setattr(bridge.os, "close", lambda fd: calls.append(("close", fd)))
    if result:
        with pytest.raises(OSError, match="protect proxy forwarder"):
            bridge._isolate(10)
        assert calls == [(4, 0, 0, 0, 0)]
    else:
        bridge._isolate(10)
        assert calls == [(4, 0, 0, 0, 0), "open", (9, 0), (9, 1), (9, 2), ("close", 9)]
