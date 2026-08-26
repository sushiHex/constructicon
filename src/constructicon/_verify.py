"""One verification command (I7): ``uv run verify``.

Runs exactly what CI runs — lint, types, the layer contract, and the full
credential-free test suite — so a contributor (agent first) self-certifies
locally what CI will check.
"""

from __future__ import annotations

import subprocess
import sys

STEPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ruff", ("ruff", "check", "src", "tests")),
    ("mypy", ("mypy",)),
    ("import-linter", ("lint-imports",)),
    ("pytest", ("pytest", "-q")),
)


def main() -> None:
    failures: list[str] = []
    for name, command in STEPS:
        print(f"== {name}: {' '.join(command)}", flush=True)
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            failures.append(name)
    if failures:
        print(f"verify FAILED: {', '.join(failures)}")
        sys.exit(1)
    print("verify OK: lint, types, layer contract, tests")


if __name__ == "__main__":
    main()
