"""Check the native state and report paths in an operator package, off-host."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from constructicon.substrate.executors.egress import MAX_SOCKET_PATH_BYTES, SOCKET_NAME
from constructicon.substrate.git.acquisition import AcquisitionPaths


def _literal(raw: bytes, name: bytes, refusal: str) -> PurePosixPath:
    assignments = re.findall(rb"^" + name + rb"=(.*)$", raw, re.M)
    if len(assignments) != 1 or not re.fullmatch(rb"(?:/[A-Za-z0-9_.-]+)+", assignments[0]):
        raise SystemExit(refusal)
    path = PurePosixPath(os.fsdecode(assignments[0]))
    if ".." in path.parts or os.fsencode(path) != assignments[0]:
        raise SystemExit(refusal)
    return path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: check_native_state_path.py FILE")
    try:
        raw = Path(sys.argv[1]).read_bytes()
    except OSError:
        raise SystemExit("native-state-step-unreadable") from None
    if b"\r" in raw:
        raise SystemExit("native-state-literal-required")
    state = _literal(raw, b"S", "native-state-literal-required")
    longest = AcquisitionPaths(state / "acquisitions", "acq-" + "0" * 32).payload
    size = len(os.fsencode(longest / SOCKET_NAME))
    if size > MAX_SOCKET_PATH_BYTES:
        raise SystemExit(f"native-state-socket-too-long: {size} > {MAX_SOCKET_PATH_BYTES} bytes")
    app = _literal(raw, b"APP", "maintenance-report-literal-required")
    report = _literal(raw, b"REPORT", "maintenance-report-literal-required")
    # capture_evidence protects both APP and the parent of S/application-run.json.
    if any(report.is_relative_to(root) or root.is_relative_to(report) for root in (app, state)):
        raise SystemExit("maintenance-report-path-overlap")
    print(f"native-state-socket-checked: {size} <= {MAX_SOCKET_PATH_BYTES} bytes")
    print("maintenance-report-path-checked")


if __name__ == "__main__":
    main()
