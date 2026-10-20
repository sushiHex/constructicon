"""Shared authority fixtures preserve nested bait without a Linux launcher."""

import subprocess

import pytest

from tests.gitworld import push_to_main, seed_authority


@pytest.mark.parametrize("initial", [
    {
        ".pi/settings.json": '{"model":"fixture/pi"}\n',
        ".pi/skills/bait/SKILL.md": "Visible data: café 🧪\n",
        "fixture.txt": "admitted café π 🧪\n",
    },
    {"fixture.txt": "admitted café π 🧪\n"},
], ids=["nested-seed", "utf8-seed"])
def test_seed_and_update_preserve_nested_utf8_fixture_files(tmp_path, initial):
    repo = seed_authority(tmp_path, initial)

    def assert_tree(files):
        names = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "refs/heads/main"],
            cwd=repo, stdin=subprocess.DEVNULL, capture_output=True, check=True,
        ).stdout.decode("utf-8").splitlines()
        assert sorted(names) == sorted(files)
        for name, content in files.items():
            blob = subprocess.run(
                ["git", "show", f"refs/heads/main:{name}"],
                cwd=repo, stdin=subprocess.DEVNULL, capture_output=True, check=True,
            ).stdout
            assert blob == content.encode("utf-8")

    assert_tree(initial)
    updates = {
        ".pi/settings.json": '{"model":"fixture/λ"}\n',
        ".pi/extensions/bait.py": 'raise RuntimeError("café π 🧪")\n',
        ".pi/agent/settings.json": '{"thinkingLevel":"off"}\n',
    }
    push_to_main(repo, updates, "nested fixture update")
    assert_tree(initial | updates)
