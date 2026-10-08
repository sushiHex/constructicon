"""M8 N5 Stage 1 on the provisioned lane: one mutant per authorization-reader check.

Run as the unprivileged service with the root-prepared variants installed.
"""

from _mutations import run

READER = "constructicon.substrate.executors.qualification:read_authorization"
TEST = "tests/substrate/test_qualification_linux.py::"

MUTANTS = (
    ("only a root-owned file is an authorization",
     READER, "or info.st_uid != 0\n", "or False\n",
     TEST + "test_the_reader_refuses_each_file_the_owner_did_not_seal[owner]"),
    ("only an owner-and-group file is an authorization",
     READER, "or stat.S_IMODE(info.st_mode) != 0o640\n", "or False\n",
     TEST + "test_the_reader_refuses_each_file_the_owner_did_not_seal[mode]"),
    ("only a root-held directory holds an authorization",
     READER, "parent.st_uid != 0\n", "False\n",
     TEST + "test_the_reader_refuses_each_file_the_owner_did_not_seal[parent]"),
    ("the reader follows no symlink",
     READER, "os.O_RDONLY | _O_NOFOLLOW | _O_CLOEXEC | _O_NONBLOCK",
     "os.O_RDONLY | _O_CLOEXEC | _O_NONBLOCK",
     TEST + "test_the_reader_follows_no_symlink"),
)

if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
