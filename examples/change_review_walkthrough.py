"""Run a retained, credential-free two-file review in fresh local processes.

Run from this checkout with ``uv run --no-active python -m
examples.change_review_walkthrough``. An optional --workspace must name a new
directory. Everything is retained; neither supplied repositories nor existing
state are overwritten. Advice is a scripted operator example, never model output.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from examples.change_review import git
from examples.change_review_batch import WAIT_SECONDS
from examples.change_review_batch_text import render_batch_text

# The CLI's 180-second settlement budget excludes projection and shutdown.
# Allow two additional minutes for those synchronous operations, rather than
# terminating a valid retained command at the old documentation's 45 seconds.
CHILD_TIMEOUT_SECONDS = WAIT_SECONDS + 120
CHECKOUT = Path(__file__).resolve().parents[1]
SUBMIT_KEY = "walkthrough-batch-1"
ADVICE = {
    "alpha.py": (
        "Scripted operator example (not model advice): add empty-input and "
        "negative-value tests for total/count."
    ),
    "nested/beta.py": (
        "Scripted operator example (not model advice): test label whitespace "
        "and retired old_label callers."
    ),
}


def entry(state: Path, *arguments: str) -> dict[str, Any]:
    """Call the existing JSON protocol in a new process, without a text codec."""
    child = subprocess.run(
        [sys.executable, "-m", "examples.change_review_batch", "--state", str(state),
         *arguments],
        cwd=CHECKOUT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=CHILD_TIMEOUT_SECONDS,
        check=False,
    )
    if child.returncode:
        # Keep failures readable and inert even when child output contains
        # hostile source/advice. The retained workspace remains available.
        stdout = child.stdout[:2_048].decode("utf-8", errors="replace")
        stderr = child.stderr[:2_048].decode("utf-8", errors="replace")
        raise RuntimeError(
            f"walkthrough_child_failed: exit={child.returncode}; "
            f"stdout_prefix={stdout!r}; stdout_bytes={len(child.stdout)}; "
            f"stderr_prefix={stderr!r}; stderr_bytes={len(child.stderr)}"
        )
    return json.loads(child.stdout.decode("utf-8"))


def sample(repository: Path) -> tuple[str, str]:
    """Create two exact commits; these Python source bytes are never executed."""
    repository.mkdir()
    git(repository, "init", "--quiet")
    versions = (
        {"alpha.py": "def total(values):\n    return sum(values)\n",
         "nested/beta.py": "def old_label(name):\n    return name\n"},
        {"alpha.py": "def total(values):\n    return sum(abs(v) for v in values)\n\n"
                     "def count(values):\n    return len(values)\n",
         "nested/beta.py": "def label(name):\n    return 'café: ' + name.strip()\n"},
    )
    commits = []
    for files in versions:
        for name, source in files.items():
            path = repository / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(source.encode("utf-8"))
        git(repository, "add", "--", *files)
        git(repository, "-c", "user.name=Example", "-c", "user.email=example@example.invalid",
            "commit", "--quiet", "-m", "walkthrough sample")
        commits.append(git(repository, "rev-parse", "HEAD").decode("ascii").strip())
    return commits[0], commits[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(f"walkthrough_unexpected_state: {message}")


def show_command(state: Path, *arguments: str) -> None:
    # This is data, not an executable shell string: paths and advice are escaped.
    print("command_argv: " + json.dumps(
        [sys.executable, "-m", "examples.change_review_batch", "--state", str(state),
         "--format", "text", *arguments], ensure_ascii=True,
    ), flush=True)


def walkthrough(workspace: Path) -> None:
    repository, state = workspace / "source", workspace / "state"
    print("Scripted operator walkthrough; no model, provider, VM or submitted code runs.",
          flush=True)
    print("Advice is untrusted example data; completion is not code or merge approval.",
          flush=True)
    print("workspace: " + json.dumps(str(workspace), ensure_ascii=True), flush=True)
    print("repository: " + json.dumps(str(repository), ensure_ascii=True), flush=True)
    print("state: " + json.dumps(str(state), ensure_ascii=True), flush=True)
    before, after = sample(repository)
    submit = ("submit", "--repository", str(repository), "--before-commit", before,
              "--after-commit", after, "--path", "alpha.py", "--path", "nested/beta.py",
              "--key", SUBMIT_KEY)
    show_command(state, *submit)
    submitted = entry(state, *submit)
    run_id = submitted["run_id"]
    require(submitted["result"]["status"] == "parked", "submit must park for advice")
    print("\nSubmitted: both files await advice.", flush=True)
    print(render_batch_text(submitted), end="", flush=True)
    files = {file["path"]: file for file in submitted["files"]}

    def reply_arguments(path: str) -> tuple[str, ...]:
        return ("reply", "--run-id", run_id, "--file-id", files[path]["file_id"],
                "--advice", ADVICE[path], "--key", f"walkthrough-advice-{path}")

    # Answer the second canonical member first to make file identity observable.
    second_reply = reply_arguments("nested/beta.py")
    show_command(state, *second_reply)
    entry(state, *second_reply)
    show_command(state, "status", "--run-id", run_id)
    partial = entry(state, "status", "--run-id", run_id)
    partial_files = {file["path"]: file for file in partial["files"]}
    require(partial["result"]["status"] == "parked", "partial root must stay parked")
    require(partial_files["alpha.py"]["status"] == "parked", "first file must stay parked")
    require(partial_files["nested/beta.py"]["status"] == "succeeded",
            "second file must complete independently")
    print("\nFresh-process partial status: second file complete; first still needs advice.",
          flush=True)
    print(render_batch_text(partial), end="", flush=True)

    first_reply = reply_arguments("alpha.py")
    show_command(state, *first_reply)
    finished = entry(state, *first_reply)
    require(finished["result"]["status"] == "succeeded", "later reply must finish the root")
    print("\nFresh-process later reply: batch complete.", flush=True)
    print(render_batch_text(finished), end="", flush=True)

    replayed_submit = entry(state, *submit)
    replayed_reply = entry(state, *first_reply)
    require(replayed_submit["run_id"] == run_id, "submit replay must retain one RunId")
    require(replayed_submit["submission"]["command"]["replayed"] is True,
            "identical submission must replay")
    require(replayed_reply["reply"]["command"]["replayed"] is True,
            "identical advice must replay")
    require(replayed_submit["result"] == finished["result"] == replayed_reply["result"],
            "replay must preserve the root result and metering")
    print("\nVerified same-key submit replay: true; same-key reply replay: true.", flush=True)
    print("Retained one RunId, root result and metering. Usage is unmeasured; money unknown.",
          flush=True)
    print("Next: inspect retained status; assess the unverified advice and run your own tests.",
          flush=True)
    show_command(state, "status", "--run-id", run_id)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, help="new directory to create and retain")
    args = parser.parse_args(argv)
    try:
        if args.workspace is None:
            workspace = Path(tempfile.mkdtemp(prefix="constructicon-review-batch-"))
        else:
            workspace = args.workspace.resolve()
            # Exclusive creation refuses even an existing empty directory. Never
            # adopt, clear or rewrite operator-owned source/state after a failure.
            workspace.mkdir(parents=False, exist_ok=False)
        walkthrough(workspace)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print("walkthrough_failed: " + repr(str(exc)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
