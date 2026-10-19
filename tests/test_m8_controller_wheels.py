"""Locked acquisition and offline consumption retain the same byte proof."""

from __future__ import annotations

import hashlib
import http.client
import io
import urllib.error
from pathlib import Path

import pytest
from scripts.ci import m8_host_artifacts as artifacts

from tests.test_m8_controller_env import fixture_lock, wheel_line


@pytest.fixture
def wheels():
    from scripts.ci import acquire_m8_controller_wheels

    return acquire_m8_controller_wheels


@pytest.fixture
def selection():
    data = b"the exact locked wheel bytes"
    wheel = artifacts.select_wheel(artifacts.controller_closure(fixture_lock(
        demo_wheels=wheel_line("demo-1.0-py3-none-any.whl", hashlib.sha256(data).hexdigest()),
    ))[0], 39)
    return wheel, data


@pytest.mark.parametrize("state", ["missing", "wrong-digest", "valid"])
def test_offline_consumer_requires_exact_prepared_bytes(
    wheels, selection, tmp_path: Path, monkeypatch, state: str,
) -> None:
    wheel, data = selection

    def network(*_args, **_kwargs):
        pytest.fail("the offline consumer must never acquire a wheel")

    monkeypatch.setattr(wheels.urllib.request, "urlopen", network)
    path = tmp_path / wheel["file"]
    if state != "missing":
        path.write_bytes(data if state == "valid" else b"a cache entry is not byte proof")
    if state == "valid":
        assert wheels.read_locked(tmp_path, wheel) == data
    else:
        failure = "missing" if state == "missing" else "integrity"
        with pytest.raises(wheels.WheelFailure, match=f"demo: {failure}"):
            wheels.read_locked(tmp_path, wheel)


def test_preparation_selects_only_locked_runtime_wheels(wheels) -> None:
    selected = wheels.selected_wheels(fixture_lock(), 39)
    assert [wheel["name"] for wheel in selected] == ["demo", "leaf"]
    assert [wheel["file"] for wheel in selected] == [
        "demo-1.0-py3-none-any.whl", "leaf-1.0-py3-none-any.whl"]


def test_acquisition_validates_download_and_each_cache_hit(
    wheels, selection, tmp_path: Path, monkeypatch,
) -> None:
    wheel, data = selection
    calls = []

    def response(url, *, timeout):
        calls.append((url, timeout))
        return io.BytesIO(data)

    monkeypatch.setattr(wheels.urllib.request, "urlopen", response)
    destination = tmp_path / "wheels"
    wheels.acquire(destination, [wheel])
    assert (destination / wheel["file"]).read_bytes() == data
    wheels.acquire(destination, [wheel])
    assert calls == [(wheel["url"], 120)]
    (destination / wheel["file"]).write_bytes(b"changed cache bytes")
    with pytest.raises(wheels.WheelFailure, match="demo: integrity"):
        wheels.acquire(destination, [wheel])
    assert calls == [(wheel["url"], 120)], "an invalid cache entry is not silently repaired"


@pytest.mark.parametrize("kind", ["transport", "integrity"])
def test_failed_acquisition_names_only_the_package_and_failure_class(
    wheels, selection, tmp_path: Path, monkeypatch, kind: str,
) -> None:
    wheel, _data = selection
    calls = []

    def response(url, *, timeout):
        calls.append((url, timeout))
        if kind == "transport":
            raise urllib.error.URLError("https://private.invalid/private-path")
        return io.BytesIO(b"untrusted bytes")

    monkeypatch.setattr(wheels.urllib.request, "urlopen", response)
    destination = tmp_path / "wheels"
    with pytest.raises(wheels.WheelFailure) as failed:
        wheels.acquire(destination, [wheel])
    assert str(failed.value) == f"controller wheels: demo: {kind}"
    assert calls == [(wheel["url"], 120)], "one attempt, without retry or timeout expansion"
    assert not (destination / wheel["file"]).exists()


@pytest.mark.parametrize("state", ["valid", "transport", "truncated", "unexpected"])
def test_cli_reports_success_or_only_a_safe_acquisition_failure(
    wheels, selection, tmp_path: Path, monkeypatch, capsys, state: str,
) -> None:
    wheel, data = selection
    (tmp_path / artifacts.LOCK).write_bytes(fixture_lock())
    monkeypatch.setattr(wheels, "ROOT", tmp_path)
    monkeypatch.setattr(wheels.artifacts, "host_glibc", lambda: 39)
    monkeypatch.setattr(wheels, "selected_wheels", lambda *_: [wheel])

    class TruncatedResponse(io.BytesIO):
        def read(self, *_args, **_kwargs):
            raise http.client.IncompleteRead(b"https://private.invalid/private-path")

    def failure(*_args, **_kwargs):
        if state == "transport":
            raise urllib.error.URLError("https://private.invalid/private-path")
        if state == "truncated":
            return TruncatedResponse(data)
        if state == "unexpected":
            raise RuntimeError("https://private.invalid/private-path")
        return io.BytesIO(data)

    monkeypatch.setattr(wheels.urllib.request, "urlopen", failure)
    assert wheels.main([str(tmp_path / "wheels")]) == (0 if state == "valid" else 1)
    captured = capsys.readouterr()
    if state in {"transport", "truncated"}:
        assert captured.out == "" and captured.err == "controller wheels: demo: transport\n"
    elif state == "unexpected":
        assert captured.out == ""
        assert captured.err == "controller wheels: preparation: unexpected\n"
    else:
        assert captured.out == "controller wheels: validated 1 locked files\n"
        assert captured.err == ""
    if state != "valid":
        assert not (tmp_path / "wheels" / wheel["file"]).exists()
    assert str(wheels.WheelFailure("private/path", "transport")) == (
        "controller wheels: invalid-package: transport")


def test_isolated_controller_proof_contains_no_network_acquisition() -> None:
    import inspect

    from tests.test_m8_controller_env import (
        test_the_staged_controller_imports_under_isolated_python,
    )

    source = inspect.getsource(test_the_staged_controller_imports_under_isolated_python)
    assert "urlopen" not in source
