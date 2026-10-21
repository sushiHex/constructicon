"""Static proposed-policy proof; this does not load or qualify a host profile."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROPOSED = ROOT / "scripts/constructicon-m8-claude.apparmor"
HOSTED = ROOT / "scripts/ci/constructicon-m8-claude.apparmor"


def _enforcement_lines(path: Path) -> list[str]:
    """Compare policy statements, excluding only comments and blank lines."""
    return [body for raw in path.read_text(encoding="utf-8").splitlines()
            if (body := raw.split("#", 1)[0].strip())]


def test_proposed_claude_profile_is_the_hosted_enforcement_body() -> None:
    proposed = _enforcement_lines(PROPOSED)
    assert proposed == _enforcement_lines(HOSTED)
    assert proposed[0] == "abi <abi/4.0>,"
    assert [line for line in proposed if line.startswith("profile ")] == [
        ("profile constructicon-m8-claude-launch "
         "/var/lib/constructicon-m8-claude/bwrap "
         "flags=(attach_disconnected,mediate_deleted) {"),
        ("profile constructicon-m8-claude-bootstrap "
         "flags=(attach_disconnected,mediate_deleted) {"),
        ("profile constructicon-m8-claude-native "
         "flags=(attach_disconnected,mediate_deleted) {"),
    ]
