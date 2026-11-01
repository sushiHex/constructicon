"""Ratchet: every refusal names its cause (AGENTS.md, "Name the refusal").

Counts each file's bare ``_Refused()`` raises and whole generic refusal
messages such as ``"Claude READ refused"``. A generic refusal hides its cause:
the week-long M8 READ blocker was a closed reason (``subscription-mismatch``)
that one such message collapsed into ``read_contract_refused``.

The allowlist below is the reviewed debt as it stands. A new generic refusal
fails this test; give it a closed code or detail instead. Naming an existing
one lowers its count, and the allowlist must then be lowered to match, so the
ledger never overstates the debt. Raising a count needs a stated reason in the
same change, in the ``reason`` column, reviewed like any other code.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "constructicon"

# A complete message that names nothing but the refusing component.
GENERIC = re.compile(r"[A-Z][A-Za-z0-9 /_-]* refused")

# path (relative to src/constructicon) -> (bare _Refused(), generic messages, reason)
_DEBT = "pre-existing at f3a8ffe; deliberate vs unnamed not yet classified"
ALLOWED: dict[str, tuple[int, int, str]] = {
    "substrate/executors/claude_lane.py": (0, 1, _DEBT),
    "substrate/executors/claude_maintenance_login.py": (0, 17, _DEBT),
    "substrate/executors/claude_maintenance_mode.py": (23, 0, _DEBT),
    "substrate/executors/claude_maintenance_session.py": (0, 5, _DEBT),
    "substrate/executors/claude_operator_io.py": (0, 14, _DEBT),
    "substrate/executors/claude_provider.py": (0, 2, _DEBT),
    "substrate/executors/claude_read.py": (3, 2, _DEBT),
    "substrate/executors/claude_read_worker.py": (0, 1, _DEBT),
    "substrate/executors/claude_startup_qualification.py": (7, 0, _DEBT),
    "substrate/executors/claude_write_worker.py": (0, 1, _DEBT),
    "substrate/executors/pi_protocol.py": (0, 1, _DEBT),
    "substrate/executors/pi_read.py": (0, 1, _DEBT),
}


def _census(path: Path) -> tuple[int, int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    bare = generic = 0
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_Refused" and not node.args and not node.keywords):
            bare += 1
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
              and GENERIC.fullmatch(node.value)):
            generic += 1
    return bare, generic


def _actual() -> dict[str, tuple[int, int]]:
    found = {}
    for path in sorted(SRC.rglob("*.py")):
        counts = _census(path)
        if counts != (0, 0):
            found[path.relative_to(SRC).as_posix()] = counts
    return found


def test_generic_refusals_do_not_grow() -> None:
    actual = _actual()
    allowed = {name: (bare, generic) for name, (bare, generic, _) in ALLOWED.items()}
    grown = {name: (allowed.get(name), counts) for name, counts in actual.items()
             if counts != allowed.get(name)}
    stale = sorted(set(allowed) - set(actual))
    assert not grown and not stale, (
        "generic refusal census differs from the reviewed allowlist "
        f"(name the new refusal, or lower the allowlist): {grown}, stale: {stale}"
    )


def test_every_allowance_states_its_reason() -> None:
    assert all(reason.strip() for _, _, reason in ALLOWED.values())


def test_census_counts_what_it_claims() -> None:
    source = (
        "class _Refused(Exception): ...\n"
        "def f():\n"
        "    raise _Refused()\n"
        "    raise _Refused(code)\n"
        "    raise ValueError('Claude READ refused')\n"
        "    raise ValueError('Claude READ refused: settings')\n"
        "    raise ValueError(f'{name} worker refused')\n"
    )
    probe = SRC.parent.parent / "tests" / "_refusal_probe_tmp.py"
    try:
        probe.write_text(source, encoding="utf-8")
        assert _census(probe) == (1, 1)
    finally:
        probe.unlink(missing_ok=True)
