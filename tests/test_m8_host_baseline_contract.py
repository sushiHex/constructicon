"""Portable proposal proofs, not execution of the retained historical tool."""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys

import pytest
from scripts import m8_host_baseline_contract as contract

from tests.test_m8_operator_commands import _bash

VALUES = {
    "kernel": "6.8.0-99-generic",
    "bwrap_digest": "a" * 64,
    "bwrap_version": "0.9.0-1ubuntu0.1",
    "bwrap_held": "1",
    "apparmor_enabled": "Y",
    "userns_restrict": "1",
    "apparmor_abi": "b" * 64,
    "os_release": "24.04",
    "architecture": "amd64",
}


def baseline(values: dict[str, str] | None = None) -> bytes:
    rows = VALUES if values is None else values
    return "".join(f"{k}\t{v}\n" for k, v in rows.items()).encode()


def observations() -> dict[str, subprocess.CompletedProcess[bytes]]:
    return {k: subprocess.CompletedProcess(["synthetic-query"], 0, f"{v}\n".encode(), b"")
            for k, v in VALUES.items()}


def test_accept_complete_and_compare_exact_surface() -> None:
    before = contract.decode_baseline(baseline())
    assert dataclasses.asdict(before) == {
        **{k: v for k, v in VALUES.items()
           if k not in ("bwrap_held", "apparmor_enabled", "userns_restrict")},
        "bwrap_held": True, "apparmor_enabled": True, "userns_restrict": True,
    }
    assert contract.decode_baseline(baseline(dict(reversed(list(VALUES.items()))))) == before
    unchanged = contract.compare(before, contract.decode_observation(observations()))
    assert dataclasses.asdict(unchanged) == {
        "status": "unchanged", "changed_keys": (),
    }
    after = dataclasses.replace(before, kernel="6.8.0-100-generic", bwrap_held=False)
    result = contract.compare(before, after)
    assert dataclasses.asdict(result) == {
        "status": "drifted", "changed_keys": ("kernel", "bwrap_held"),
    }
    assert len(json.dumps(dataclasses.asdict(result))) < 256
    with pytest.raises(dataclasses.FrozenInstanceError):
        before.kernel = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("blob", [
    b"", baseline()[:-1], baseline().split(b"\n", 1)[1],
    baseline() + b"kernel\t6.8.0-99-generic\n", baseline() + b"unknown\t\n",
    baseline().replace(b"kernel\t", b"unknown\t"), baseline() + b"\n",
    baseline().replace(b"kernel\t", b"kernel\t\t"), baseline().replace(b"\n", b"\r\n"),
    b"x" * (contract.MAX_BASELINE_BYTES + 1), baseline().replace(b"amd64", b"\xff"),
    baseline().replace(b"os_release\t24.04", b"kernel\t6.8.0-99-generic"),
])
def test_reject_incomplete_or_ambiguous_baseline(blob: bytes) -> None:
    with pytest.raises(contract.InventoryRefused, match=r"^invalid-baseline$"):
        contract.decode_baseline(blob)


def test_missing_inventory_has_fixed_refusal_not_incidental_lookup_error() -> None:
    for blob in (b"", b"kernel\t6.8.0-99-generic\n", baseline().replace(b"kernel", b"unknown")):
        try:
            contract.decode_baseline(blob)
        except Exception as exc:
            assert type(exc) is contract.InventoryRefused
            assert str(exc) == "invalid-baseline"
            assert exc.reason is contract.Refusal.BASELINE
        else:
            pytest.fail("incomplete inventory accepted")


@pytest.mark.parametrize(("key", "value"), [
    ("kernel", ""), ("kernel", "x" * 129), ("kernel", "a\x00b"),
    ("kernel", "a b"), ("bwrap_digest", "a" * 63), ("bwrap_digest", "A" * 64),
    ("apparmor_abi", "not-a-digest"), ("bwrap_held", "2"), ("apparmor_enabled", "yes"),
    ("userns_restrict", ""), ("architecture", "a" * 33), ("architecture", "AMD64"),
])
def test_scalar_domains_refuse_in_both_directions(key: str, value: str) -> None:
    with pytest.raises(contract.InventoryRefused):
        contract.decode_baseline(baseline({**VALUES, key: value}))
    results = observations()
    results[key].stdout = (value + "\n").encode()
    with pytest.raises(contract.InventoryRefused, match=r"^incomplete-observation$"):
        contract.decode_observation(results)


@pytest.mark.parametrize("key", contract.KEYS)
def test_each_query_must_complete_even_if_valid_value_matches_baseline(key: str) -> None:
    results = observations()
    results[key].returncode = 1
    with pytest.raises(contract.InventoryRefused, match=r"^incomplete-observation$"):
        contract.decode_observation(results)


@pytest.mark.parametrize(("attribute", "value"), [
    ("returncode", None), ("returncode", True), ("stdout", None), ("stdout", "1\n"),
    ("stdout", b""), ("stdout", b"1"), ("stdout", b"1\n\n"), ("stdout", b"\xff\n"),
    ("stdout", b"x" * (contract.MAX_QUERY_BYTES + 1)),
    ("stderr", b"private diagnostic"), ("stderr", None), ("stderr", ""),
])
def test_query_completion_and_stream_contract(attribute: str, value: object) -> None:
    results = observations()
    setattr(results["bwrap_held"], attribute, value)
    with pytest.raises(contract.InventoryRefused, match=r"^incomplete-observation$"):
        contract.decode_observation(results)


def test_query_inventory_is_closed_and_direct_construction_cannot_bypass_types() -> None:
    for results in ({}, {**observations(), "unknown": observations()["kernel"]}):
        with pytest.raises(contract.InventoryRefused):
            contract.decode_observation(results)
    results = observations()
    del results["kernel"]
    with pytest.raises(contract.InventoryRefused):
        contract.decode_observation(results)
    before = contract.decode_baseline(baseline())
    for changes in ({"bwrap_held": 1}, {"kernel": ""}, {"apparmor_abi": None}):
        with pytest.raises(contract.InventoryRefused):
            dataclasses.replace(before, **changes)


def test_accept_unhealthy_complete_values_without_claiming_qualification() -> None:
    values = {**VALUES, "bwrap_held": "0", "apparmor_enabled": "N", "userns_restrict": "0"}
    facts = contract.decode_baseline(baseline(values))
    assert dataclasses.asdict(contract.compare(facts, facts)) == {
        "status": "unchanged", "changed_keys": (),
    }
    assert not facts.bwrap_held and not facts.apparmor_enabled and not facts.userns_restrict
    results = observations()
    for key, value in values.items():
        results[key].stdout = (value + "\n").encode()
    assert contract.decode_observation(results) == facts


def test_accept_exact_scalar_bound_then_reject_next_byte() -> None:
    values = {**VALUES, "kernel": "x" * 128}
    results = observations()
    results["kernel"].stdout = b"x" * 128 + b"\n"
    assert contract.decode_observation(results) == contract.decode_baseline(baseline(values))
    results["kernel"].stdout = b"x" * 129 + b"\n"
    with pytest.raises(contract.InventoryRefused):
        contract.decode_observation(results)


def test_query_byte_bound_precedes_scalar_interpretation(monkeypatch) -> None:
    interpreted: list[str] = []
    original = contract._valid_scalar

    def observe(key, value):
        interpreted.append(value)
        return original(key, value)

    monkeypatch.setattr(contract, "_valid_scalar", observe)
    results = observations()
    results["kernel"].stdout = b"x" * contract.MAX_QUERY_BYTES + b"\n"
    with pytest.raises(contract.InventoryRefused):
        contract.decode_observation(results)
    assert interpreted == []


def test_every_published_field_is_fixed_or_known_key_without_host_values() -> None:
    before = contract.decode_baseline(baseline())
    after = contract.decode_baseline(baseline({
        "kernel": "other", "bwrap_digest": "c" * 64, "bwrap_version": "other",
        "bwrap_held": "0", "apparmor_enabled": "N", "userns_restrict": "0",
        "apparmor_abi": "d" * 64, "os_release": "other", "architecture": "arm64",
    }))
    surface = dataclasses.asdict(contract.compare(before, after))
    assert set(surface) == {"status", "changed_keys"}
    for key, value in surface.items():
        if key == "status":
            assert value in ("unchanged", "drifted")
        else:
            assert type(value) is tuple and value == contract.KEYS
    assert len(json.dumps(surface)) <= 256


# Deliberately narrow source-equivalent fixtures. These exercise the two reviewed
# mechanisms, not the retained script's exact bytes, path, commands or installation.
LEGACY_COMPARE = """import json, sys
current = json.loads(sys.argv[1])
drift = False
for row in sys.stdin.buffer:
    if not row.endswith(b'\\n'):
        break
    key, _, was = row[:-1].decode().partition('\\t')
    if current.get(key, '') != was:
        drift = True
raise SystemExit(1 if drift else 0)
"""


@pytest.mark.parametrize(("blob", "expected"), [
    (baseline(), 0), (b"", 0), (baseline()[:-1], 0),
    (baseline().split(b"\n", 1)[1], 0), (baseline() + b"kernel\t6.8.0-99-generic\n", 0),
    (baseline() + b"unknown\t\n", 0), (baseline() + b"unknown\tnonempty\n", 1),
    (baseline().replace(b"amd64\n", b"stale-without-lf"), 0),
    (baseline().replace(b"6.8.0-99-generic", b"changed"), 1),
])
def test_historical_comparison_mechanism_source_equivalent(blob: bytes, expected: int) -> None:
    result = subprocess.run(
        [sys.executable, "-I", "-c", LEGACY_COMPARE, json.dumps(VALUES)],
        input=blob, capture_output=True, timeout=10, check=False,
    )
    assert (result.returncode, result.stdout, result.stderr) == (expected, b"", b"")


def test_failed_substitution_masking_source_equivalent(tmp_path) -> None:
    # Portable Bash is optional on Windows; the Python comparison proofs above
    # always run. No query touches host facts: the only query here is `exit 7`.
    bash = _bash()
    result = subprocess.run(
        [bash, "-c", "set -uo pipefail; printf 'fact\\t%s\\n' \"$(exit 7)\""],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=10, check=False, cwd=tmp_path,
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, b"fact\t\n", b"")
    masked = subprocess.run(
        [sys.executable, "-I", "-c", LEGACY_COMPARE, json.dumps({"fact": ""})],
        input=result.stdout, capture_output=True, timeout=10, check=False,
    )
    assert (masked.returncode, masked.stdout, masked.stderr) == (0, b"", b"")
