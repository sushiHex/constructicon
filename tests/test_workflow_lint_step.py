"""The workflow linter runs in the required job, verified before it executes.

GitHub voids a workflow with one invalid key or expression and shows only a
jobless run (issue #218). actionlint, pinned by version and sha256 in
verify.yml's ``verify`` job, is what rejects that before merge; this pins the
step so deleting or weakening it fails a test.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
VERIFY = (ROOT / ".github/workflows/verify.yml").read_text(encoding="utf-8")


def _job(name: str) -> str:
    block = re.search(rf"^  {name}:\n((?:    .*\n|\n)+)", VERIFY, re.M)
    assert block is not None, name
    return block[1]


def _step() -> str:
    step = re.search(
        r"^      - name: Lint workflows with actionlint\n((?:        .*\n)+)", _job("verify"), re.M
    )
    assert step is not None, "the verify job has no actionlint step"
    return step[1]


def test_the_linter_step_is_pinned_and_checked_before_it_runs() -> None:
    step = _step()
    assert re.search(r'^          ACTIONLINT_VERSION: "\d+\.\d+\.\d+"$', step, re.M)
    assert re.search(r"^          ACTIONLINT_SHA256: [0-9a-f]{64}$", step, re.M)
    check = step.index("sha256sum --check --strict")
    assert check < step.index("tar -xzf"), "extract only after the checksum passes"
    assert check < step.index('"$RUNNER_TEMP/actionlint"'), "execute only after the checksum passes"
    assert "set -euo pipefail" in step


def test_the_linter_job_is_required_by_the_aggregate() -> None:
    assert re.search(r"needs: \[[^\]]*\bverify\b[^\]]*\]", _job("verify-complete"))


def test_ignores_are_scoped_to_one_file_and_one_message() -> None:
    config = (ROOT / ".github/actionlint.yaml").read_text(encoding="utf-8")
    ignores = re.findall(r"^      - '(.+)'$", config, re.M)
    scoped = r"shellcheck reported issue in this script: SC\d+:"
    assert ignores and all(re.match(scoped, i) for i in ignores)
    assert "paths:\n  .github/workflows/" in config
