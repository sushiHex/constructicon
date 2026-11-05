# Candidate: legacy gate snapshots must equal their Git tree (issue #369)

Branch `fix/cloud-archive`, from `b22581ac2922b27f35b0a83b528a25a2cb279073`.

## Reproduction
Through `tests.gitworld` (propose -> `GateRunner` -> `merge_verified`), a
candidate adds failing `test_bad.py` plus `.gitattributes` containing
`test_bad.py export-ignore`. Legacy `GitAuthority.read_snapshot` used
`git archive`, which honours the attribute, so the gated snapshot lacked the
test; gates passed and the merge commit contained the failing file. The
premise was confirmed (the new e2e test fails on the old code).

## Design
`read_snapshot` now also runs `git ls-tree -r -z --full-tree`, extracts the
archive, and compares exported files with the tree: path, type (blob/symlink),
blob id (hashed with the repository object format) and executable bit. This
mirrors the existing check in `substrate/gates/contained.py::_snapshot`
(same unsupported-entry refusal for gitlinks). Any difference raises
`ContractViolation("snapshot export differs from the exact Git tree ...")`
before the snapshot is returned, so `GateRunner._verify` never reaches
attest/merge. The export directory is removed on every failure path
(archive, extract, verify). On Windows the executable bit is not compared
(NTFS has none); path, type and content still are. No sandbox, provider
policy, contained gate or workflow was changed.

## Evidence (run locally, observed)
- Refusing: `export-ignore`, `export-subst`, `eol=crlf` unit cases in
  `tests/substrate/test_git_authority.py`, each also asserting no leftover
  snapshot directory.
- Accepting: ordinary candidate with `.gitattributes` (`*.txt text eol=lf`),
  an executable file and plain text; and the e2e ordinary-attributes candidate
  gates and merges (`tests/e2e/test_legacy_gate_snapshot.py`).
- Regression: the export-ignore candidate through the real composed
  graph does not succeed, `main` is unmoved, no `EffectCommitted`, snapshots
  dir empty. These four refusing tests fail with the source change stashed.
- Also passing: `tests/e2e/test_git_repair_loop.py`, `test_merge_effect.py`,
  `tests/substrate/test_git_executable.py`, `tests/test_mutation_inventories.py`
  (59 passed, 2 skipped); ruff on affected files; mypy on `authority.py`.

## Not run
Full suite, `uv run verify`, import-linter, Linux-sandbox/physical lanes,
mutation scripts (no inventory targets `git/authority.py`), CI. No CI result is
claimed.

## Limitations
- Symlink/regular-file symmetry and exec bit are checked on POSIX; Windows
  skips the exec bit.
- Gitlinks (submodules) now refuse in legacy snapshots, as in the contained
  gate; previously they exported as empty directories.
- Same-UID mutation of the snapshot remains out of scope (see module docstring).
- The failed run's surfaced error is the node failure; no new closed refusal
  code was added beyond the message.
- Delivery handoff / implementation record left to the orchestrator.

Issue: #369
