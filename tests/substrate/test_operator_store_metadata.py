"""Malformed private metadata is unavailable, not a blocking or raw exception."""

import stat
from types import SimpleNamespace

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.substrate.executors import operator_store


def test_deep_metadata_is_a_bounded_refusal_not_a_parser_exception():
    assert operator_store._metadata(b'{"positive":true}') == {"positive": True}
    raw = ("[" * 1000 + "0" + "]" * 1000).encode()
    assert len(raw) < operator_store.MAX_METADATA_BYTES
    try:
        operator_store._metadata(raw)
    except ContractViolation as exc:
        assert str(exc) == "native store metadata is unavailable"
    except RecursionError:
        pytest.fail("a bounded malformed record escaped as a parser exception")
    else:
        pytest.fail("malformed metadata was accepted")


def test_metadata_open_cannot_block_before_nonregular_file_refusal(monkeypatch):
    flags_seen = []
    closed = []
    nonblocking = 0x800
    monkeypatch.setattr(operator_store, "_O_NONBLOCK", nonblocking)

    def opened(target, flags, *, dir_fd):
        flags_seen.append(flags)
        return 42

    monkeypatch.setattr(operator_store.os, "open", opened)
    monkeypatch.setattr(operator_store.os, "fstat", lambda fd: SimpleNamespace(
        st_mode=stat.S_IFIFO | 0o600, st_nlink=1, st_size=0, st_uid=0,
    ))
    monkeypatch.setattr(operator_store.os, "close", closed.append)
    with pytest.raises(ContractViolation, match="metadata is unavailable"):
        operator_store._read_metadata(SimpleNamespace(bundle_fd=7), "active.json")
    assert len(flags_seen) == 1 and flags_seen[0] & nonblocking
    assert closed == [42]
