"""Compare Python source as data, retain a review request, and collect advice.

Run from the checkout with ``python -m examples.change_review --help``.
This trusted local entry neither executes the submitted source nor calls a model.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from constructicon.api import Constructicon
from constructicon.api.control import ControlPlane
from constructicon.core.address import GitSha, RunId
from constructicon.core.channel import ChannelEndpoint
from constructicon.core.component import ComponentDef, PythonRef
from constructicon.core.control import (
    ADMIN_SCOPE,
    ADVISE_SCOPE,
    OPERATE_SCOPE,
    READ_SCOPE,
    AuthenticatedActor,
    ChannelMessageSummary,
    ControlRejected,
    DetailRef,
    RegistrationCommandResult,
    RunResultPreviewV3,
    RunSubmission,
)
from constructicon.core.envelope import GitRef
from constructicon.core.graph import Connection, Graph, GraphNode
from constructicon.core.identity import Digest, digest
from constructicon.core.ports import Port
from constructicon.core.run import RunStatus
from constructicon.runtime.context import NodeContext
from constructicon.runtime.registry import CapabilityDescriptor, source_digest_for
from constructicon.sdk.std import (
    ADVICE_REPLY,
    ADVICE_REQUEST,
    ADVISOR_CHANNEL,
    ADVISOR_COMPONENT,
    definitions,
)
from constructicon.sdk.types import DefinitionBundle
from constructicon.substrate.channels.mailbox import MailboxChannel
from constructicon.substrate.journal.sqlite import SqliteJournal

SOURCE_BYTES = 32_768
SYMBOL_LIMIT = 25
CHANNEL_ID = "example/change-review"
# This local entry is the trusted transport. Identity is fixed, never a flag.
OPERATOR = AuthenticatedActor(
    actor_id="static:change-review-operator",
    auth_method="static",
    scopes=frozenset({READ_SCOPE, OPERATE_SCOPE, ADMIN_SCOPE, ADVISE_SCOPE}),
)
DEMO_BEFORE = "def total(values):\n    return sum(values)\n"
DEMO_AFTER = (
    "def total(values):\n    return sum(values, start=0)\n\n"
    "def count(values):\n    return len(values)\n"
)
DEMO_ADVICE = "Scripted operator example: add empty-input tests for total and count."


class SourceChange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    before: str = Field(max_length=SOURCE_BYTES)
    after: str = Field(max_length=SOURCE_BYTES)


class ChangeSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: Literal["top-level public functions and classes; AST comparison only"]
    before_hash: Digest
    after_hash: Digest
    syntax_errors: dict[str, Annotated[str, Field(max_length=160)]] = Field(max_length=2)
    comparison_available: bool
    symbols: dict[str, Annotated[list[Annotated[str, Field(max_length=80)]],
                                Field(max_length=SYMBOL_LIMIT)]] = Field(max_length=3)
    counts: dict[str, Annotated[int, Field(ge=0)]] = Field(max_length=3)
    symbols_partial: bool
    tests_executed: Literal[False]


class ReviewInput(ChangeSummary):
    before_ref: GitRef
    after_ref: GitRef


CHANGE_SCHEMA = ReviewInput.model_json_schema()
CHANGE = Port(
    name="change", type_id="example/PythonChangeReview",
    schema_hash=str(digest("json-schema", 1, CHANGE_SCHEMA)), json_schema=CHANGE_SCHEMA,
)
# The graph forwards this same report shape; publish its real schema rather than
# inventing an opaque second nominal contract for the output.
ANALYSIS = CHANGE.model_copy(update={"name": "analysis"})


def compare_sources(before_source: str, after_source: str) -> ChangeSummary:
    """Trusted local preflight: source text never enters a graph envelope."""

    change = SourceChange(before=before_source, after=after_source)
    snapshots: list[dict[str, list[str]]] = []
    errors: dict[str, str] = {}
    for label, source in (("before", change.before), ("after", change.after)):
        if len(source.encode("utf-8")) > SOURCE_BYTES:
            raise ValueError(f"source_bytes_exceeded: {label} exceeds {SOURCE_BYTES} UTF-8 bytes")
        symbols: dict[str, list[str]] = {}
        try:
            tree = ast.parse(source)
            for node in tree.body:
                if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                        and not node.name.startswith("_")):
                    symbols.setdefault(node.name, []).append(ast.dump(node))
        except (SyntaxError, ValueError, RecursionError) as exc:
            # Do not echo a source line, a host filename, or unbounded diagnostics.
            if isinstance(exc, SyntaxError):
                errors[label] = f"line {exc.lineno}: {exc.msg}"[:160]
            else:
                errors[label] = type(exc).__name__
        snapshots.append(symbols)
    before, after = snapshots
    changes = {} if errors else {
        "added": sorted(after.keys() - before.keys()),
        "removed": sorted(before.keys() - after.keys()),
        "changed": sorted(name for name in before.keys() & after.keys()
                          if before[name] != after[name]),
    }
    return ChangeSummary.model_validate({
        "scope": "top-level public functions and classes; AST comparison only",
        "before_hash": str(digest("example-python-source", 1, change.before)),
        "after_hash": str(digest("example-python-source", 1, change.after)),
        "syntax_errors": errors,
        "comparison_available": not errors,
        "symbols": {kind: [name[:80] for name in names[:SYMBOL_LIMIT]]
                    for kind, names in changes.items()},
        "counts": {kind: len(names) for kind, names in changes.items()},
        "symbols_partial": any(len(names) > SYMBOL_LIMIT or any(len(n) > 80 for n in names)
                               for names in changes.values()),
        "tests_executed": False,
    })


async def prepare_review(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    """Compose a bounded report and canonical advisor request, carrying GitRefs."""

    analysis = ReviewInput.model_validate(inputs["change"]).model_dump(mode="json")
    return {
        "analysis": analysis,
        "request": {"question": "What tests or follow-up does this change need?",
                    "analysis": analysis},
    }


def inspection() -> DefinitionBundle:
    inputs, outputs = (CHANGE,), (ANALYSIS, ADVICE_REQUEST)
    return DefinitionBundle(
        definition=ComponentDef(
            name="example/prepare-python-review", role="node",
            capability_requirements=(), inputs=inputs, outputs=outputs,
            body=PythonRef(
                package="examples", module=prepare_review.__module__,
                qualname=prepare_review.__qualname__,
                contract_hash=digest("component-contract", 1, {
                    "inputs": [port.model_dump(mode="json") for port in inputs],
                    "outputs": [port.model_dump(mode="json") for port in outputs],
                }),
                source_digest=source_digest_for(prepare_review),
            ),
        ),
        implementation=prepare_review,
    )


def review_graph(versions: Mapping[str, Digest]) -> Graph:
    """Exact retained versions; registration never needs to move stable pointers."""

    return Graph(
        name="python-change-review",
        nodes=(
            GraphNode(id="inspect", body=inspection().ref(
                version=str(versions["example/prepare-python-review"]))),
            GraphNode(id="review", body=next(
                bundle for bundle in definitions() if bundle.name == ADVISOR_COMPONENT
            ).ref(version=str(versions[ADVISOR_COMPONENT]),
                  bind={ADVISOR_CHANNEL: CHANNEL_ID})),
        ),
        connections=(Connection(src="inspect", dst="review", map={"request": "inspect.request"}),),
        inputs=(CHANGE,), outputs=(ANALYSIS, ADVICE_REPLY),
    )


def assemble(db: Path) -> tuple[Constructicon, ControlPlane]:
    journal = SqliteJournal(db)
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    system = Constructicon(
        journal=journal, capabilities={CHANNEL_ID: mailbox},
        catalog={CHANNEL_ID: CapabilityDescriptor(
            capability_id=CHANNEL_ID, kind="channel.mailbox", revision="1",
            channel_profile=mailbox.profile,
            endpoint=ChannelEndpoint(lane="change-review", interaction="advice",
                                     recipient_actor_id=OPERATOR.actor_id),
        )},
    )
    return system, ControlPlane(system=system, store=journal)


def checked(value: Any) -> Any:
    if isinstance(value, ControlRejected):
        raise RuntimeError(value.model_dump_json())
    return value


async def register(control: ControlPlane) -> dict[str, Digest]:
    bundles = (inspection(), next(b for b in definitions() if b.name == ADVISOR_COMPONENT))
    versions = {}
    for bundle in bundles:
        result = checked(await control.registry_register(
            OPERATOR, definition=bundle,
            idempotency_key=f"register:{bundle.name}:{bundle.definition.content_hash()}",
        ))
        assert isinstance(result, RegistrationCommandResult)
        versions[bundle.name] = result.version
    return versions


async def wait_for(control: ControlPlane, run_id: RunId, *, allow_parked: bool) -> None:
    deadline = asyncio.get_running_loop().time() + 15
    while True:
        summary = checked(control.runs_status(OPERATOR, run_id))
        if summary.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
            return
        if allow_parked and summary.status is RunStatus.PARKED:
            return
        if asyncio.get_running_loop().time() >= deadline:
            raise RuntimeError(f"review_wait_timeout: run={run_id} status={summary.status.value}")
        await asyncio.sleep(0.01)


def request_for(control: ControlPlane, run_id: RunId) -> ChannelMessageSummary | None:
    cursor = None
    while True:
        page = checked(control.channels_inbox(OPERATOR, cursor=cursor, limit=100))
        for item in page.items:
            if item.run_id == run_id and item.kind == "request" and item.channel_id == CHANNEL_ID:
                return item
        cursor = page.page.next_cursor
        if cursor is None:
            return None


def git(repository: Path, *arguments: str) -> bytes:
    """Fixed Git operations only; no shell, credentials, hooks, or inherited Git overrides."""

    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_NO_REPLACE_OBJECTS": "1", "GIT_TERMINAL_PROMPT": "0",
                "GIT_AUTHOR_DATE": "2026-01-01T00:00:00 +0000",
                "GIT_COMMITTER_DATE": "2026-01-01T00:00:00 +0000"})
    result = subprocess.run(
        ["git", "--no-pager", "-C", str(repository), "-c", f"core.hooksPath={os.devnull}",
         "-c", "commit.gpgsign=false", *arguments],
        env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=15, check=False,
    )
    if result.returncode:
        raise ValueError(f"review_git_failed: {arguments[0]} exited {result.returncode}")
    return result.stdout


def committed_source(repository: Path, commit: str, path: str) -> tuple[GitRef, str]:
    if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit) is None:
        raise ValueError("review_commit_invalid: supply a full lowercase commit SHA")
    if (not path or len(path) > 200 or path.startswith("/") or ":" in path
            or "\\" in path or any(part in {"", ".", ".."} for part in path.split("/"))):
        raise ValueError("review_path_invalid: supply a repository-relative POSIX file path")
    if git(repository, "cat-file", "-t", commit).strip() != b"commit":
        raise ValueError("review_commit_invalid: object is not a commit")
    selector = f"{commit}:{path}"
    if git(repository, "cat-file", "-t", selector).strip() != b"blob":
        raise ValueError("review_source_invalid: selected object is not a file blob")
    size = int(git(repository, "cat-file", "-s", selector))
    if size > SOURCE_BYTES:
        raise ValueError(f"source_bytes_exceeded: maximum {SOURCE_BYTES} UTF-8 bytes per file")
    source = git(repository, "cat-file", "blob", selector).decode("utf-8")
    reference = GitRef(repository=str(repository.resolve()), commit=GitSha(commit), paths=(path,))
    return reference, source


def demo_commits(state: Path) -> tuple[Path, str, str]:
    """Materialize only the fixed tutorial repository; repeated calls reuse its commits."""

    repository = state / "sample"
    if not repository.exists():
        repository.mkdir(parents=True)
        git(repository, "init", "--quiet")
        for text, message in ((DEMO_BEFORE, "before"), (DEMO_AFTER, "after")):
            (repository / "calc.py").write_text(text, encoding="utf-8", newline="\n")
            git(repository, "add", "--", "calc.py")
            git(repository, "-c", "user.name=Example", "-c", "user.email=example@example.invalid",
                "commit", "--quiet", "-m", message)
    before = git(repository, "rev-parse", "HEAD^").decode("ascii").strip()
    after = git(repository, "rev-parse", "HEAD").decode("ascii").strip()
    return repository, before, after


def read_detail(control: ControlPlane, reference: DetailRef) -> Any:
    cursor = None
    parts = []
    while True:
        chunk = checked(control.details_read(OPERATOR, reference, cursor=cursor, max_bytes=16_000))
        parts.append(chunk.text)
        cursor = chunk.next_cursor
        if cursor is None:
            return json.loads("".join(parts))


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    change = None
    if args.command == "demo":
        repository, before_commit, after_commit = demo_commits(args.state)
        before_ref, before = committed_source(repository, before_commit, "calc.py")
        after_ref, after = committed_source(repository, after_commit, "calc.py")
        if before != DEMO_BEFORE or after != DEMO_AFTER:
            raise ValueError("review_demo_changed: use a fresh state directory for the example")
        change = ReviewInput(**compare_sources(before, after).model_dump(),
                             before_ref=before_ref, after_ref=after_ref)
    elif args.command == "submit":
        # Read immutable blobs and validate before opening or creating the durable store.
        before_ref, before = committed_source(args.repository, args.before_commit, args.path)
        after_ref, after = committed_source(args.repository, args.after_commit, args.path)
        change = ReviewInput(**compare_sources(before, after).model_dump(),
                             before_ref=before_ref, after_ref=after_ref)
    db = args.state / "review.db"
    if args.command in {"status", "reply"} and not db.is_file():
        raise ValueError("review_store_missing: submit a review first")
    args.state.mkdir(parents=True, exist_ok=True)
    _, control = assemble(db)
    response: dict[str, Any] = {}
    try:
        if args.command == "status":
            # Status is observational: it does not start recovery workers.
            run_id = RunId(args.run_id)
        elif change is not None:
            versions = await register(control)
            await control.startup()
            submission = checked(await control.runs_start(
                OPERATOR, proposal=review_graph(versions),
                inputs={"change": change.model_dump(mode="json")},
                idempotency_key=args.key,
            ))
            assert isinstance(submission, RunSubmission)
            run_id = submission.run_id
            response["submission"] = submission.model_dump(mode="json")
            await wait_for(control, run_id, allow_parked=True)
        else:
            run_id = RunId(args.run_id)
            await control.startup()
        request = request_for(control, run_id)
        response["request"] = request.model_dump(mode="json") if request else None
        response["request_payload"] = (
            read_detail(control, request.detail)["envelope"]["payload"] if request else None
        )
        if args.command in {"demo", "reply"} and request is not None:
            reply = checked(await control.channels_reply(
                OPERATOR, message_id=request.message_id,
                payload=DEMO_ADVICE if args.command == "demo" else args.advice,
                idempotency_key=f"{args.key}:advice" if args.command == "demo" else args.key,
            ))
            response["reply"] = reply.model_dump(mode="json")
            await wait_for(control, run_id, allow_parked=False)
        elif args.command == "reply":
            raise ValueError("review_request_missing: this run has no change-review request")
        result = checked(control.runs_result(OPERATOR, run_id))
        assert isinstance(result, RunResultPreviewV3)
        response["result"] = result.model_dump(mode="json")
        return response
    finally:
        await control.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True, help="local durable state directory")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="complete an explicitly scripted operator example")
    demo.add_argument("--key", required=True)
    submit = commands.add_parser("submit", help="compare committed Python blobs; park for advice")
    submit.add_argument("--repository", type=Path, required=True)
    submit.add_argument("--before-commit", required=True)
    submit.add_argument("--after-commit", required=True)
    submit.add_argument("--path", required=True)
    submit.add_argument("--key", required=True)
    reply = commands.add_parser("reply", help="answer as the fixed local operator")
    reply.add_argument("--run-id", required=True)
    reply.add_argument("--advice", required=True)
    reply.add_argument("--key", required=True)
    status = commands.add_parser("status", help="read a durable result without starting recovery")
    status.add_argument("--run-id", required=True)
    try:
        response = asyncio.run(execute(parser.parse_args()))
        print(json.dumps(response, indent=2))
        return int(response["result"]["status"] not in {"succeeded", "parked"})
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    # Reloadable PythonRefs must name the importable module, never __main__.
    from examples.change_review import main as entry

    raise SystemExit(entry())
