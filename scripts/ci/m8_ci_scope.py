"""Fail-closed selection and aggregation for the M8 containment workflow.

This module deliberately uses only Git's committed-tree facts.  A prose-only
classification is an optimization, not evidence about containment, and any
unrecognized input selects the full physical proof lanes (or makes the
classification job fail when the Git evidence itself is unavailable).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

SHA_RE = re.compile(r"[0-9a-fA-F]{40}\Z")
RAW_HEADER_RE = re.compile(
    rb":([0-7]{6}) ([0-7]{6}) ([0-9a-f]{40}) ([0-9a-f]{40}) ([A-Z])(?:[0-9]+)?\Z"
)
MANIFEST_LINE_RE = re.compile(r"([0-9a-f]{64})  ([^\r\n]+)\Z")
INLINE_LINK_RE = re.compile(r"!?\[[^\]\n]*\]\(([^)\n]+)\)")
REFERENCE_LINK_RE = re.compile(r"^\s*\[[^\]\n]+\]:\s*(\S+)", re.MULTILINE)

ABSENT_MODE = "000000"
REGULAR_MODE = "100644"
ZERO_OID = "0" * 40
ROOT_PROSE = frozenset({"README.md", "AGENTS.md", "CONTRIBUTING.md"})
JOB_RESULTS = frozenset({"success", "failure", "cancelled", "skipped"})


class ScopeError(ValueError):
    """The selector could not establish complete, trustworthy input."""


@dataclass(frozen=True)
class DiffEntry:
    old_mode: str
    new_mode: str
    old_oid: str
    new_oid: str
    status: str
    path: str


def _is_sha(value: str) -> bool:
    return SHA_RE.fullmatch(value) is not None


def parse_raw_diff(raw: bytes) -> tuple[DiffEntry, ...]:
    """Parse ``git diff --raw -z --no-renames --abbrev=40`` output."""

    if not raw:
        return ()
    fields = raw.split(b"\0")
    if fields[-1] != b"" or (len(fields) - 1) % 2:
        raise ScopeError("Git returned an incomplete raw diff")

    entries: list[DiffEntry] = []
    for offset in range(0, len(fields) - 1, 2):
        header = fields[offset]
        path_bytes = fields[offset + 1]
        match = RAW_HEADER_RE.fullmatch(header)
        if match is None or not path_bytes:
            raise ScopeError("Git returned an unrecognized raw diff record")
        try:
            path = path_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ScopeError("Git returned a non-UTF-8 path") from error
        entries.append(
            DiffEntry(
                old_mode=match.group(1).decode("ascii"),
                new_mode=match.group(2).decode("ascii"),
                old_oid=match.group(3).decode("ascii"),
                new_oid=match.group(4).decode("ascii"),
                status=match.group(5).decode("ascii"),
                path=path,
            )
        )
    return tuple(entries)


def _safe_repo_path(path: str) -> bool:
    if "\\" in path:
        return False
    parsed = PurePosixPath(path)
    return (
        bool(path)
        and not parsed.is_absolute()
        and all(part not in {"", ".", ".."} for part in parsed.parts)
    )


def _is_prose_path(path: str) -> bool:
    if not _safe_repo_path(path):
        return False
    if path in ROOT_PROSE:
        return True
    if path == "docs/plans/MANIFEST.sha256":
        return True
    parsed = PurePosixPath(path)
    return len(parsed.parts) >= 2 and parsed.parts[0] == "docs" and parsed.suffix == ".md"


def _is_plain_file_change(entry: DiffEntry) -> bool:
    if entry.status == "A":
        return (
            entry.old_mode == ABSENT_MODE
            and entry.new_mode == REGULAR_MODE
            and entry.old_oid == ZERO_OID
            and entry.new_oid != ZERO_OID
        )
    if entry.status == "D":
        return (
            entry.old_mode == REGULAR_MODE
            and entry.new_mode == ABSENT_MODE
            and entry.old_oid != ZERO_OID
            and entry.new_oid == ZERO_OID
        )
    if entry.status == "M":
        return (
            entry.old_mode == REGULAR_MODE
            and entry.new_mode == REGULAR_MODE
            and entry.old_oid != ZERO_OID
            and entry.new_oid != ZERO_OID
        )
    return False


def classify_changes(entries: tuple[DiffEntry, ...]) -> str:
    """Return ``docs`` only for a nonempty set of known plain prose changes."""

    if not entries:
        return "full"
    if all(_is_prose_path(entry.path) and _is_plain_file_change(entry) for entry in entries):
        return "docs"
    return "full"


def _git(repository: Path, *arguments: str) -> bytes:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C.UTF-8",
        }
    )
    try:
        completed = subprocess.run(
            ["git", "--no-replace-objects", *arguments],
            cwd=repository,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ScopeError("Git evidence is unavailable") from error
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ScopeError(f"Git evidence command failed: {detail or 'no diagnostic'}")
    return completed.stdout


def classify_repository(repository: Path, base: str, head: str) -> str:
    """Classify the committed merge-base-to-head diff for two exact commit IDs."""

    if not _is_sha(base) or not _is_sha(head):
        raise ScopeError("base and head must each be an exact 40-hex commit ID")
    repository = repository.resolve()
    for name, commit in (("base", base), ("head", head)):
        resolved = _git(repository, "rev-parse", "--verify", f"{commit}^{{commit}}").strip()
        if not _is_sha(resolved.decode("ascii", errors="ignore")):
            raise ScopeError(f"{name} did not resolve to one commit")

    merge_base = _git(repository, "merge-base", "--", base, head).strip()
    try:
        merge_base_text = merge_base.decode("ascii")
    except UnicodeDecodeError as error:
        raise ScopeError("Git returned an invalid merge base") from error
    if not _is_sha(merge_base_text):
        raise ScopeError("Git did not return exactly one merge base")

    raw = _git(
        repository,
        "diff",
        "--raw",
        "-z",
        "--no-renames",
        "--abbrev=40",
        merge_base_text,
        head,
        "--",
    )
    return classify_changes(parse_raw_diff(raw))


def _markdown_without_fences(text: str) -> str:
    kept: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        stripped = line.lstrip()
        marker = stripped[:3]
        if fence is None and marker in {"```", "~~~"}:
            fence = marker
            continue
        if fence is not None:
            if stripped.startswith(fence):
                fence = None
            continue
        kept.append(line)
    return "\n".join(kept)


def _link_target(raw: str) -> str | None:
    value = raw.strip()
    if value.startswith("<"):
        closing = value.find(">")
        if closing < 0:
            raise ScopeError(f"malformed Markdown link target: {raw}")
        value = value[1:closing]
    else:
        value = value.split(maxsplit=1)[0] if value else ""
    if not value or value.startswith("#"):
        return None
    split = urlsplit(value)
    if split.scheme or split.netloc:
        return None
    target = unquote(split.path)
    return target or None


def _markdown_documents(repository: Path) -> tuple[Path, ...]:
    documents = [repository / name for name in sorted(ROOT_PROSE) if (repository / name).is_file()]
    docs = repository / "docs"
    if docs.is_dir():
        documents.extend(sorted(docs.rglob("*.md")))
    for document in documents:
        if document.is_symlink() or not document.is_file():
            raise ScopeError(f"Markdown document is not a regular file: {document}")
    return tuple(documents)


def verify_markdown_links(repository: Path) -> None:
    repository = repository.resolve()
    for document in _markdown_documents(repository):
        try:
            text = document.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ScopeError(f"could not read Markdown as UTF-8: {document}") from error
        visible = _markdown_without_fences(text)
        raw_targets = INLINE_LINK_RE.findall(visible) + REFERENCE_LINK_RE.findall(visible)
        for raw_target in raw_targets:
            target = _link_target(raw_target)
            if target is None:
                continue
            relative = PurePosixPath(target)
            if relative.is_absolute() or "\\" in target:
                raise ScopeError(f"unsafe relative link in {document}: {target}")
            candidate = (document.parent / Path(*relative.parts)).resolve()
            try:
                candidate.relative_to(repository)
            except ValueError as error:
                raise ScopeError(f"link escapes repository in {document}: {target}") from error
            if not candidate.exists():
                source = document.relative_to(repository).as_posix()
                raise ScopeError(f"missing relative link target from {source}: {target}")


def verify_plan_manifest(repository: Path) -> None:
    plans = repository.resolve() / "docs" / "plans"
    manifest = plans / "MANIFEST.sha256"
    try:
        lines = manifest.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise ScopeError("could not read docs/plans/MANIFEST.sha256") from error

    recorded: dict[str, str] = {}
    for line_number, line in enumerate(lines, 1):
        match = MANIFEST_LINE_RE.fullmatch(line)
        if match is None:
            raise ScopeError(f"malformed plan manifest line {line_number}")
        digest, name = match.groups()
        path = PurePosixPath(name)
        unsafe_part = any(part in {"", ".", ".."} for part in path.parts)
        if path.is_absolute() or "\\" in name or unsafe_part:
            raise ScopeError(f"unsafe plan manifest path on line {line_number}")
        if name in recorded:
            raise ScopeError(f"duplicate plan manifest path: {name}")
        recorded[name] = digest

    expected: dict[str, Path] = {}
    for document in sorted(plans.rglob("*.md")):
        if document.is_symlink() or not document.is_file():
            raise ScopeError(f"planning document is not a regular file: {document}")
        expected[document.relative_to(plans).as_posix()] = document
    missing = sorted(set(expected) - set(recorded))
    extra = sorted(set(recorded) - set(expected))
    if missing or extra:
        raise ScopeError(f"incomplete plan manifest (missing={missing}, extra={extra})")

    for name, document in expected.items():
        actual = hashlib.sha256(document.read_bytes()).hexdigest()
        if actual != recorded[name]:
            raise ScopeError(f"plan manifest digest mismatch: {name}")


def verify_docs(repository: Path) -> None:
    verify_plan_manifest(repository)
    verify_markdown_links(repository)


def gate_allows(scope: str, classification: str, docs: str, proofs: str) -> bool:
    """Accept only the two complete job-state shapes produced by the workflow."""

    states = {classification, docs, proofs}
    if not states <= JOB_RESULTS or classification != "success":
        return False
    if scope == "full":
        return docs == "skipped" and proofs == "success"
    if scope == "docs":
        return docs == "success" and proofs == "skipped"
    return False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    classify = subparsers.add_parser("classify", help="select docs or full CI scope")
    classify.add_argument("--base", required=True)
    classify.add_argument("--head", required=True)
    classify.add_argument("--repository", type=Path, default=Path.cwd())

    docs = subparsers.add_parser("docs", help="verify documentation links and archive")
    docs.add_argument("--repository", type=Path, default=Path.cwd())

    gate = subparsers.add_parser("gate", help="validate the aggregate workflow result")
    gate.add_argument("--scope", required=True)
    gate.add_argument("--classification", required=True)
    gate.add_argument("--docs", required=True)
    gate.add_argument("--proofs", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "classify":
            print(classify_repository(arguments.repository, arguments.base, arguments.head))
            return 0
        if arguments.command == "docs":
            verify_docs(arguments.repository)
            return 0
        if arguments.command == "gate":
            allowed = gate_allows(
                arguments.scope,
                arguments.classification,
                arguments.docs,
                arguments.proofs,
            )
            if not allowed:
                print("m8-ci-scope: aggregate CI evidence is incomplete", file=sys.stderr)
                return 1
            if arguments.scope == "docs":
                print("physical proofs not required: verified prose-only changes")
            else:
                print("all selected physical proof lanes succeeded")
            return 0
    except ScopeError as error:
        print(f"m8-ci-scope: {error}", file=sys.stderr)
        return 2
    raise AssertionError("argparse admitted an unknown command")


if __name__ == "__main__":
    raise SystemExit(main())
