"""Pin the workflow source policy; GitHub execution remains separate evidence."""

import re
from pathlib import Path


def test_verify_supersedes_only_its_own_pr_runs():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/verify.yml"
    ).read_text(encoding="utf-8")
    concurrency = re.findall(r"^concurrency:\n((?:  [^\n]+\n)+)", workflow, re.MULTILINE)
    assert concurrency == [
        "  group: ${{ github.workflow }}-"
        "${{ github.event_name }}-"
        "${{ github.event.pull_request.number || github.run_id }}\n"
        "  cancel-in-progress: ${{ github.event_name == 'pull_request' }}\n"
    ]
