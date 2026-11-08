"""The cache exception must not make a required job or proof optional."""

from pathlib import Path

import pytest

from tests.ci_cache_policy import CACHE_PIN, assert_only_archive_cache_is_advisory

WORKFLOWS = Path(__file__).parents[1] / ".github/workflows"


@pytest.mark.parametrize("filename", [
    "verify.yml", "m8-containment.yml", "m8-runner-qualification.yml",
])
def test_actual_required_workflows_allow_only_the_identified_cache_actions(filename):
    assert_only_archive_cache_is_advisory((WORKFLOWS / filename).read_text(encoding="utf-8"))


@pytest.mark.parametrize("fault", [
    "job", "aggregate-job", "proof", "aggregate-step", "noncache", "mispinned",
    "expression", "nested", "run", "wrong-job", "duplicate", "quoted-value",
    "floating", "wrong-mode",
])
def test_advisory_exception_refuses_any_widening(fault):
    text = (WORKFLOWS / "verify.yml").read_text(encoding="utf-8")
    if fault in {"job", "aggregate-job"}:
        job = "verify" if fault == "job" else "verify-complete"
        text = text.replace(f"  {job}:\n", f"  {job}:\n    continue-on-error: true\n", 1)
    elif fault in {"proof", "aggregate-step"}:
        name = ("Acquire pinned actionlint archive" if fault == "proof"
                else "Require the complete selected job result")
        before = f"      - name: {name}\n"
        assert before in text
        text = text.replace(before, before + "        continue-on-error: true\n", 1)
    elif fault == "noncache":
        text = text.replace(f"actions/cache/restore@{CACHE_PIN}", "other/action@" + CACHE_PIN, 1)
    elif fault in {"mispinned", "floating", "wrong-mode"}:
        replacement = {
            "mispinned": "actions/cache/restore@" + "a" * 40,
            "floating": "actions/cache/restore@v4",
            "wrong-mode": f"actions/cache/save@{CACHE_PIN}",
        }[fault]
        text = text.replace(f"actions/cache/restore@{CACHE_PIN}", replacement, 1)
    elif fault in {"expression", "nested", "duplicate", "quoted-value"}:
        replacement = {
            "expression": "        continue-on-error: ${{ true }}\n",
            "nested": "          continue-on-error: true\n",
            "duplicate": "        continue-on-error: true\n        continue-on-error: false\n",
            "quoted-value": "        continue-on-error: 'true'\n",
        }[fault]
        text = text.replace("        continue-on-error: true\n", replacement, 1)
    elif fault == "run":
        text = text.replace("        id: actionlint-cache\n",
                            "        id: actionlint-cache\n        run: exit 0\n", 1)
    else:
        text = text.replace("  verify:\n", "  verify-complete-impostor:\n", 1)
    with pytest.raises(AssertionError):
        assert_only_archive_cache_is_advisory(text)
