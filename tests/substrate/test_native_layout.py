"""The launcher's own native data: what it seals is exactly what the design names."""

import json
import os
import tomllib

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.substrate.executors import linux

SELECTORS = {
    "apply_patch_tool_type": None, "tool_mode": "direct",
    "multi_agent_version": None, "experimental_supported_tools": [],
}
SOURCE = {"fetched_at": "fixture", "models": [
    {"slug": "gpt-6.1-sol", "visibility": "list", "base_instructions": "Use functions.exec.",
     "apply_patch_tool_type": "freeform", "tool_mode": "code_mode_only",
     "multi_agent_version": "v2", "experimental_supported_tools": ["clock"],
     "supported_reasoning_levels": [{"effort": "low"}]},
    {"slug": "gpt-6-luna", "visibility": "hide"},
]}


def test_the_sealed_catalog_closes_exactly_the_tool_selectors_of_every_entry():
    sealed = json.loads(linux.sealed_catalog(json.dumps(SOURCE).encode()))
    assert {key: value for key, value in sealed.items() if key != "models"} == {
        "fetched_at": "fixture"}
    assert len(sealed["models"]) == len(SOURCE["models"])
    for before, after in zip(SOURCE["models"], sealed["models"], strict=True):
        assert after == {**before, **SELECTORS}


def test_the_sealed_catalog_is_deterministic_and_a_fixed_point():
    once = linux.sealed_catalog(json.dumps(SOURCE).encode())
    reordered = json.dumps(SOURCE, sort_keys=True, indent=1).encode()
    assert linux.sealed_catalog(reordered) == once
    assert linux.sealed_catalog(once) == once


def test_the_environment_file_names_no_environment():
    assert tomllib.loads(linux.NATIVE_ENVIRONMENTS.decode()) == {"include_local": False}
    assert f"{linux.NATIVE_HOME}/environments.toml" == linux.ENVIRONMENTS_MOUNT


@pytest.fixture
def sealed(monkeypatch):
    data = {}

    def seal(content):
        fd = os.open(os.devnull, os.O_RDONLY)
        data[fd] = content
        return fd

    monkeypatch.setattr(linux, "sealed_data_fd", seal)
    return data


def test_the_layout_seals_the_environment_file_and_the_installed_catalogs_seal(
    tmp_path, sealed,
):
    catalog = tmp_path / "codex-models.json"
    catalog.write_text(json.dumps(SOURCE))
    layout = linux.NativeLayout.seal(linux.NativeVendor(tmp_path / "native-codex", catalog))
    try:
        assert sealed[layout.environments_fd] == linux.NATIVE_ENVIRONMENTS
        assert sealed[layout.catalog_fd] == linux.sealed_catalog(catalog.read_bytes())
        assert layout.mount_fds == (layout.environments_fd, layout.catalog_fd)
    finally:
        layout.close()


def test_without_a_vendor_the_layout_is_the_environment_file_alone(sealed):
    layout = linux.NativeLayout.seal(None)
    try:
        assert layout.catalog_fd is None and layout.mount_fds == (layout.environments_fd,)
    finally:
        layout.close()


@pytest.mark.parametrize("damage", [b"{not json", b'{"models": 7}', b'{"models": [7]}', b"{}"])
def test_a_catalog_that_cannot_be_sealed_refuses_the_launch_and_leaks_nothing(
    tmp_path, sealed, monkeypatch, damage,
):
    closed, close = [], os.close
    monkeypatch.setattr(linux.os, "close", lambda fd: (closed.append(fd), close(fd)))
    catalog = tmp_path / "codex-models.json"
    catalog.write_bytes(damage)
    with pytest.raises(ContractViolation, match="cannot be sealed"):
        linux.NativeLayout.seal(linux.NativeVendor(tmp_path / "native-codex", catalog))
    assert closed == list(sealed)
