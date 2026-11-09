"""The sole advisory-step exception shared by the required-workflow guards."""

import re

CACHE_PIN = "0057852bfaa89a56745cba8c7296529d2fc39830"
CACHE_STEPS = {
    f"{verb} pinned {asset} {kind}": (job, mode)
    for asset, kind, job in (
        ("actionlint", "archive", "verify"), ("pi", "archive", "proofs"),
        ("codex", "archive", "proofs"), ("cosign", "binary", "proofs"),
    )
    for verb, mode in (("Restore", "restore"), ("Save", "save"))
}


def assert_only_archive_cache_is_advisory(workflow: str) -> None:
    """Every optional declaration must belong to one exact pinned cache action."""
    steps = list(re.finditer(
        r"^      - name: (?P<name>[^\n]+)\n.*?(?=^      - |^  \S|\Z)",
        workflow, re.M | re.S,
    ))
    for declaration in re.finditer("continue-on-error", workflow):
        step = next((item for item in steps
                     if item.start() <= declaration.start() < item.end()), None)
        assert step is not None, "optional job or unnamed step"
        assert step["name"] in CACHE_STEPS, "only identified archive caches may be advisory"
        job, mode = CACHE_STEPS[step["name"]]
        owners = re.findall(r"^  ([\w-]+):$", workflow[:step.start()], re.M)
        assert owners and owners[-1] == job, "cache exception is outside its acquiring job"
        block = step[0]
        assert [line for line in block.splitlines() if "continue-on-error" in line] == [
            "        continue-on-error: true",
        ], "only one literal step-level true is permitted"
        uses = re.findall(r"^        uses: ([^\n]+)$", block, re.M)
        assert len(uses) == 1 and uses[0].split("#", 1)[0].strip() == (
            f"actions/cache/{mode}@{CACHE_PIN}"
        ), "cache action and revision must match exactly"
        assert not re.search(r"^\s*[\"']?run[\"']?\s*:", block, re.M), (
            "an advisory cache action cannot carry a run body"
        )
