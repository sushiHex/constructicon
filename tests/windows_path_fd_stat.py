"""Test-only Windows path/descriptor ctime seam for the Linux evidence reader."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace


class PathFdStatSeam:
    def __init__(self) -> None:
        self.normalized = 0


def install_path_fd_stat_seam(monkeypatch, reader, paths) -> PathFdStatSeam:
    """Align only ctime on matching path/fd views of explicitly named fixtures."""
    evidence = PathFdStatSeam()
    if os.name != "nt":
        return evidence

    targets = {Path(path) for path in paths}
    descriptors = {}
    real_os = reader.os

    def open_file(path, *args, **kwargs):
        descriptor = real_os.open(path, *args, **kwargs)
        candidate = Path(path)
        descriptors.pop(descriptor, None)
        if candidate in targets:
            descriptors[descriptor] = candidate
        return descriptor

    def fstat(descriptor):
        result = real_os.fstat(descriptor)
        path = descriptors.get(descriptor)
        if path is None:
            return result
        try:
            path_info = path.lstat()
        except OSError:
            return result
        if (result.st_dev, result.st_ino) != (path_info.st_dev, path_info.st_ino):
            return result
        fields = {key: getattr(result, key) for key in reader.STABLE}
        fields["st_ctime_ns"] = path_info.st_ctime_ns
        evidence.normalized += 1
        return SimpleNamespace(**fields)

    def close(descriptor):
        descriptors.pop(descriptor, None)
        return real_os.close(descriptor)

    class ReaderOS:
        def __getattr__(self, name):
            return getattr(real_os, name)

        def open(self, path, *args, **kwargs):
            return open_file(path, *args, **kwargs)

        def fstat(self, descriptor):
            return fstat(descriptor)

        def close(self, descriptor):
            return close(descriptor)

    monkeypatch.setattr(reader, "os", ReaderOS())
    return evidence
