"""The real ``codex_lane`` command line with only custody and launch substituted.

Run as a script: ``python -I -S -B lane_cli_double.py SRC PURELIB RECORDS -- ARGV``.
``RECORDS/<name of --evidence>`` holds a record the production lane code
already produced (with a scripted peer, never a vendor). Argument parsing, the evidence reservation,
``EvidenceFile.publish``, the stderr summary, the refresh verdict and the exit
status are the installed module's own. The substitutions mirror
``tests/substrate/test_codex_lane.py::main_world``.
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager, nullcontext


def main() -> int:
    source, purelib, records = sys.argv[1:4]
    if sys.argv[4] != "--":
        raise SystemExit("usage: lane_cli_double.py SRC PURELIB RECORDS -- ARGV")
    argv = sys.argv[5:]
    sys.path[:0] = [source, purelib]
    import json
    from pathlib import Path

    from constructicon.substrate.executors import codex_lane

    name = Path(argv[argv.index("--evidence") + 1]).name
    evidence = json.loads((Path(records) / name).read_text(encoding="utf-8"))

    async def lane(*args: object, **options: object) -> dict:
        return evidence

    @asynccontextmanager
    async def active(store: object):
        yield None

    class Sealed:
        @staticmethod
        def model_validate_json(raw: str) -> None:
            return None

    codex_lane._launcher = lambda root: None
    codex_lane.vendor_executable = lambda launcher: None
    codex_lane._policy = lambda path: None
    codex_lane.inherit_maintenance = lambda *args, **options: nullcontext(None)
    codex_lane.maintenance_custody = lambda withdrawn: None
    codex_lane.NativeOperatorStoreIdentityV1 = Sealed
    codex_lane.BindingStore = lambda *args: None
    codex_lane.active_custody = active
    codex_lane.run_login = lane
    codex_lane.run_startup = lane
    # Only the platform newline differs on native Windows; Linux writes LF.
    sys.stdout.reconfigure(newline="\n")
    sys.stderr.reconfigure(newline="\n")
    return codex_lane.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
