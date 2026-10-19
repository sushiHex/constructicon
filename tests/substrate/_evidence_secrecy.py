"""Assert the exact evidence family emitted on one isolated proof lane."""

from collections.abc import Collection
from pathlib import Path

BRIDGE_N4 = (
    "n4-bridge.json",
    "n4-lane-login.json",
    "n4-lane-startup.json",
    "n4-lane-trust.json",
    "n4-pinned-client.json",
)
MAINTENANCE_N4 = ("n4-inherited-maintenance.json",)


def assert_clean_evidence(
    directory: Path | None,
    pattern: str,
    expected_names: Collection[str] | None,
    tokens: Collection[str],
    *,
    required: bool = False,
) -> None:
    if directory is None:
        assert not required, "required evidence directory is missing"
        return
    files = sorted(directory.glob(pattern))
    if expected_names is not None:
        assert [path.name for path in files] == sorted(expected_names)
    for path in files:
        text = path.read_text()
        assert "-----BEGIN" not in text and "PRIVATE KEY" not in text, path.name
        assert not any(token in text for token in tokens), path.name
