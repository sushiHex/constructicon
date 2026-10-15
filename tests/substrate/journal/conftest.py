"""Explicit platform seams for accepting maintenance capture fixtures only."""

import os

import pytest

from constructicon.substrate.journal import maintenance_evidence as evidence


@pytest.fixture
def portable_capture_custody(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.name == "nt":
        monkeypatch.setattr(evidence, "_custody", lambda info, *, private: True)
        original = evidence._metadata

        def metadata(info):
            # Windows lstat/fstat ctime differ; retain all other real fields.
            return {**original(info), "ctime_ns": 0}

        monkeypatch.setattr(evidence, "_metadata", metadata)
    elif os.name == "posix" and os.getuid() == 0:
        # Remove only the positive-UID prerequisite for root-run fixtures.
        # Both production owner sets are {0}; retain real owner/write bits.
        monkeypatch.setattr(evidence, "_custody", lambda info, *, private: (
            info.st_uid == 0 and not info.st_mode & 0o022))
