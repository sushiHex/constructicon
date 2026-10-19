"""Prepare exact locked controller wheels; the isolated import proof stays offline."""

from __future__ import annotations

import http.client
import io
import os
import re
import sys
import urllib.request
from pathlib import Path

from scripts.ci import m8_host_artifacts as artifacts

ROOT = Path(__file__).resolve().parents[2]


class WheelFailure(ValueError):
    """Only a safe package label and fixed failure class reach CI diagnostics."""

    def __init__(self, package: str, failure: str) -> None:
        label = (package if isinstance(package, str)
                 and re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", package)
                 else "invalid-package")
        super().__init__(f"controller wheels: {label}: {failure}")


def selected_wheels(lock: bytes, glibc: int) -> list[dict[str, str]]:
    return [artifacts.select_wheel(package, glibc)
            for package in artifacts.controller_closure(lock)]


def validate(data: bytes, wheel: dict[str, str]) -> None:
    try:
        artifacts.require_locked(io.BytesIO(data), wheel)
    except ValueError:
        raise WheelFailure(wheel["name"], "integrity") from None


def read_locked(directory: Path, wheel: dict[str, str]) -> bytes:
    """A local cache entry is accepted only after validating its actual bytes."""
    try:
        data = (directory / wheel["file"]).read_bytes()
    except FileNotFoundError:
        raise WheelFailure(wheel["name"], "missing") from None
    except OSError:
        raise WheelFailure(wheel["name"], "read") from None
    validate(data, wheel)
    return data


def acquire(directory: Path, selected: list[dict[str, str]]) -> None:
    directory.mkdir(exist_ok=True)
    for wheel in selected:
        path = directory / wheel["file"]
        if not os.path.lexists(path):
            try:
                with urllib.request.urlopen(wheel["url"], timeout=120) as response:
                    data = response.read()
            except (OSError, ValueError, http.client.HTTPException):
                raise WheelFailure(wheel["name"], "transport") from None
            validate(data, wheel)
            try:
                with path.open("xb") as stream:
                    stream.write(data)
            except OSError:
                raise WheelFailure(wheel["name"], "write") from None
        read_locked(directory, wheel)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("controller wheels: preparation: arguments", file=sys.stderr)
        return 1
    try:
        selected = selected_wheels((ROOT / artifacts.LOCK).read_bytes(), artifacts.host_glibc())
        acquire(Path(args[0]), selected)
    except WheelFailure as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print("controller wheels: preparation: selection-or-storage", file=sys.stderr)
        return 1
    except Exception:
        print("controller wheels: preparation: unexpected", file=sys.stderr)
        return 1
    print(f"controller wheels: validated {len(selected)} locked files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
