"""Portable publication-boundary checks for N3a metadata."""

from __future__ import annotations

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.substrate.executors import operator_store


def test_existing_descriptor_name_refuses_and_cleans_its_private_temporary(monkeypatch):
    closed: list[int] = []
    unlinked: list[tuple[str, int]] = []
    target = {"1.json": b"pre-existing descriptor"}

    monkeypatch.setattr(operator_store.secrets, "token_hex", lambda size: "b" * (size * 2))
    monkeypatch.setattr(operator_store.os, "open", lambda *args, **kwargs: 13)
    monkeypatch.setattr(operator_store.os, "write", lambda fd, raw: len(raw))
    monkeypatch.setattr(operator_store.os, "fsync", lambda fd: None)
    monkeypatch.setattr(operator_store.os, "close", closed.append)
    # The ownership law has its own Linux unit proof (test_operator_store_replace).
    monkeypatch.setattr(operator_store, "_seal_metadata_fd", lambda fd, directory_fd: None)

    def link(source, name, **kwargs):
        assert source == ".pending-" + "b" * 32
        assert name in target
        raise FileExistsError(name)

    monkeypatch.setattr(operator_store.os, "link", link)
    monkeypatch.setattr(
        operator_store.os,
        "unlink",
        lambda name, *, dir_fd: unlinked.append((name, dir_fd)),
    )

    with pytest.raises(ContractViolation, match="descriptor publication"):
        operator_store._publish_new(7, "1.json", b"replacement")

    assert target["1.json"] == b"pre-existing descriptor"
    assert closed == [13]
    assert unlinked == [((".pending-" + "b" * 32), 7)]


@pytest.mark.parametrize("extra_bytes", [0, 1])
def test_metadata_enforces_inclusive_size_limit(extra_bytes):
    content_size = operator_store.MAX_METADATA_BYTES - 8 + extra_bytes
    raw = b'{"x":"' + b"a" * content_size + b'"}'
    if extra_bytes:
        with pytest.raises(ContractViolation, match="metadata"):
            operator_store._metadata(raw)
    else:
        assert operator_store._metadata(raw) == {"x": "a" * content_size}
