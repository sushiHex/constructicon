"""A real pair of checkouts must not silently exchange verification sources."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
import venv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def checkouts(tmp_path: Path) -> tuple[Path, Path, Path]:
    seed = tmp_path / "seed"
    package = seed / "src" / "constructicon"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "from pathlib import Path\n"
        "Path(__file__).parents[2].joinpath('package-imported').touch()\n",
        encoding="utf-8",
    )
    shutil.copyfile(ROOT / "src" / "constructicon" / "_verify.py", package / "_verify.py")
    bootstrap = ROOT / "conftest.py"
    (seed / "conftest.py").write_text(
        bootstrap.read_text(encoding="utf-8") if bootstrap.exists() else "",
        encoding="utf-8",
    )
    tests = seed / "tests"
    tests.mkdir()
    (tests / "conftest.py").write_text(
        "from pathlib import Path\n"
        "Path(__file__).parents[1].joinpath('collection-started').touch()\n",
        encoding="utf-8",
    )
    (tests / "test_checkout.py").write_text(
        "from pathlib import Path\n"
        "import constructicon\n"
        "def test_checkout():\n"
        "    assert Path(constructicon.__file__).resolve() == "
        "Path(__file__).parents[1] / 'src' / 'constructicon' / '__init__.py'\n"
        "    Path(__file__).parents[1].joinpath('test-ran').touch()\n",
        encoding="utf-8",
    )
    for command in (
        ["git", "init", "-q"],
        ["git", "add", "."],
        ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
         "-c", "commit.gpgsign=false", "commit", "-qm", "fixture"],
    ):
        subprocess.run(command, cwd=seed, check=True, capture_output=True, stdin=subprocess.DEVNULL)
    intended, foreign = tmp_path / "intended", tmp_path / "foreign"
    for checkout in (intended, foreign):
        subprocess.run(
            ["git", "clone", "-q", "--no-hardlinks", str(seed), str(checkout)],
            check=True, capture_output=True, stdin=subprocess.DEVNULL,
        )
    environment = tmp_path / "environment"
    venv.EnvBuilder(with_pip=False).create(environment)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return intended, foreign, python


@pytest.mark.parametrize(
    ("selected", "entrypoint"),
    [("intended", "pytest"), ("intended", "verify"),
     ("foreign", "pytest"), ("foreign", "verify"), ("missing", "pytest")],
)
def test_checkout_identity_precedes_collection(
    checkouts: tuple[Path, Path, Path], selected: str, entrypoint: str,
) -> None:
    intended, foreign, python = checkouts
    # Hatchling's path-based editable installs use this same .pth mechanism.
    # Only development tools come from the parent environment; no packages are installed.
    site = python.parent.parent / (
        "Lib/site-packages" if os.name == "nt" else
        f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
    )
    source = {"intended": intended, "foreign": foreign, "missing": intended / "absent"}[selected]
    (site / "_constructicon.pth").write_text(
        f"{source / 'src'}\n{sysconfig.get_path('purelib')}\n", encoding="utf-8",
    )
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    probe = subprocess.run(
        [str(python), "-c", "from importlib.util import find_spec; "
         "s = find_spec('constructicon'); print(s.origin if s else 'missing')"],
        cwd=intended, env=env, capture_output=True, text=True, check=True,
        stdin=subprocess.DEVNULL, timeout=30,
    )
    expected = source / "src" / "constructicon" / "__init__.py"
    assert probe.stdout.strip() == (str(expected) if selected != "missing" else "missing")
    assert not (source / "package-imported").exists()
    command = (
        [str(python), "-m", "pytest", "-q"] if entrypoint == "pytest" else
        [str(python), "-c", "import sys; from constructicon import _verify; "
         "_verify.STEPS = (('pytest', (sys.executable, '-m', 'pytest', '-q')),); _verify.main()"]
    )
    result = subprocess.run(
        command, cwd=intended, env=env, capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=30,
    )
    output = result.stdout + result.stderr
    if selected == "intended":
        assert result.returncode == 0, output
        assert "1 passed" in output
        assert (intended / "package-imported").is_file()
        assert (intended / "collection-started").is_file()
        assert (intended / "test-ran").is_file()
    else:
        assert result.returncode != 0, output
        assert "constructicon source mismatch" in output
        assert str(intended / "src" / "constructicon" / "__init__.py") in output
        assert (str(expected) if selected == "foreign" else "missing") in output
        assert "uv run --no-active verify" in output
        assert not (intended / "collection-started").exists()
        assert not (intended / "test-ran").exists()
        if entrypoint == "pytest":
            assert not (foreign / "package-imported").exists()
        if selected == "foreign":
            # Deliberate subprocess imports remain supported, outside development pytest.
            imported = subprocess.run(
                [str(python), "-c", "import constructicon; print(constructicon.__file__)"],
                cwd=intended, env=env, capture_output=True, text=True, check=True,
                stdin=subprocess.DEVNULL, timeout=30,
            )
            assert Path(imported.stdout.strip()).resolve() == expected
