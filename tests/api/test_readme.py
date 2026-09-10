"""The README's literal two-file example completes and replays after restart."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from constructicon.core.run import RunStatus
from constructicon.substrate.journal.sqlite import SqliteJournal


def test_readme_workflow_completes_and_replays(tmp_path: Path) -> None:
    readme = (Path(__file__).parents[2] / "README.md").read_text(encoding="utf-8")
    sources = re.findall(r"^```python\n(.*?)^```$", readme, re.MULTILINE | re.DOTALL)
    for filename, source in zip(("demo_component.py", "demo.py"), sources, strict=True):
        (tmp_path / filename).write_text(source, encoding="utf-8")

    expected = "succeeded {'brief': {'title': 'Fix the flaky retry'}}\n"
    for _ in range(2):
        completed = subprocess.run(
            [sys.executable, "demo.py"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        assert completed.stdout == expected
        assert completed.stderr == ""

    records = SqliteJournal(tmp_path / ".constructicon" / "demo.db").run_records(limit=2)
    assert len(records) == 1
    assert records[0].status is RunStatus.SUCCEEDED
