"""M8 N5 Stage 1 on the provisioned lane: one mutant per authorization-reader check.

Run as the unprivileged service with the root-prepared variants installed;
each variant differs from the sealed authorization in one respect only.
"""

from _mutations import run

READER = "constructicon.substrate.executors.qualification:read_authorization"
STORE = "constructicon.substrate.executors.operator_store:"
TEST = (
    "tests/substrate/test_qualification_linux.py::"
    "test_the_reader_refuses_each_file_the_owner_did_not_seal"
)

MUTANTS = (
    ("only a root-owned file is an authorization",
     READER, "or info.st_uid != 0\n", "or False\n", TEST + "[owner]"),
    ("only an owner-and-group file is an authorization",
     READER, "or stat.S_IMODE(info.st_mode) != 0o640\n", "or False\n", TEST + "[mode]"),
    ("only a single-linked file is an authorization",
     READER, "info.st_nlink != 1\n", "False\n", TEST + "[links]"),
    ("an authorization is bounded",
     READER, "if len(raw) > MAX_AUTHORIZATION_BYTES:", "if False:", TEST + "[size]"),
    ("the reader follows no symlink at the leaf",
     READER, "os.O_RDONLY | _O_NOFOLLOW | _O_CLOEXEC | _O_NONBLOCK",
     "os.O_RDONLY | _O_CLOEXEC | _O_NONBLOCK", TEST + "[leaf-symlink]"),
    ("every ancestor is root-owned",
     STORE + "_trusted_directory",
     "or info.st_uid != 0 or info.st_mode & 0o022", "or info.st_mode & 0o022",
     TEST + "[ancestor-owner]"),
    ("no ancestor is writable by group or others",
     STORE + "_trusted_directory",
     "or info.st_uid != 0 or info.st_mode & 0o022", "or info.st_uid != 0",
     TEST + "[ancestor-mode]"),
    ("the reader follows no symlink in an ancestor",
     STORE + "_open_trusted_directory",
     "part, os.O_RDONLY | _O_DIRECTORY | _O_CLOEXEC | _O_NOFOLLOW,",
     "part, os.O_RDONLY | _O_DIRECTORY | _O_CLOEXEC,", TEST + "[ancestor-symlink]"),
)

if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
