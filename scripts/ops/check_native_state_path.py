"""Check the literal native state path in an operator package, off-host."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from constructicon.substrate.executors.egress import MAX_SOCKET_PATH_BYTES, SOCKET_NAME
from constructicon.substrate.git.acquisition import AcquisitionPaths


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: check_native_state_path.py FILE")
    try:
        raw = Path(sys.argv[1]).read_bytes()
    except OSError:
        raise SystemExit("native-state-step-unreadable") from None
    assignments = re.findall(rb"^S=(.*)$", raw, re.M)
    if b"\r" in raw or len(assignments) != 1 or not re.fullmatch(
        rb"(?:/[A-Za-z0-9_.-]+)+", assignments[0],
    ):
        raise SystemExit("native-state-literal-required")
    state = PurePosixPath(os.fsdecode(assignments[0]))
    if ".." in state.parts or os.fsencode(state) != assignments[0]:
        raise SystemExit("native-state-literal-required")
    longest = AcquisitionPaths(state / "acquisitions", "acq-" + "0" * 32).payload
    size = len(os.fsencode(longest / SOCKET_NAME))
    if size > MAX_SOCKET_PATH_BYTES:
        raise SystemExit(f"native-state-socket-too-long: {size} > {MAX_SOCKET_PATH_BYTES} bytes")
    print(f"native-state-socket-checked: {size} <= {MAX_SOCKET_PATH_BYTES} bytes")


if __name__ == "__main__":
    main()
