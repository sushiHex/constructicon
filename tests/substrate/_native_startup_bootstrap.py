"""Immutable test-image entry point; replace this process, never supervise it.

The one initial line is trusted test setup, not model input. All allocated
files are under the existing launcher's private /tmp and die with its namespace.
"""

import json
import os
import sys
from pathlib import Path


def prepare(setup=None):
    if setup is None:
        setup = json.loads(sys.stdin.buffer.readline(256 * 1024))
    if set(setup) != {"files", "config", "arguments"}:
        raise ValueError("unexpected startup fixture fields")
    root = Path("/tmp/native-startup")
    root.mkdir()
    config = Path("/tmp/home/.codex")
    config.mkdir()
    (config / "config.toml").write_text(setup["config"])
    for name, content in setup["files"].items():
        path = Path(name)
        if not path.is_absolute() or ".." in path.parts or not (
            path.is_relative_to(root) or path.is_relative_to(config)
        ):
            raise ValueError("fixture file must belong to private startup storage")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return setup


def launch(setup):
    print(json.dumps({
        "bootstrap_environment": dict(os.environ),
        "absent": {name: not Path(name).exists() for name in (
            "/etc/codex", "/workspace/.codex", "/root", "/home",
        )},
    }), flush=True)
    os.chdir("/tmp/native-startup")
    os.execv("/opt/native-startup/native/bin/codex", [
        "codex", *setup["arguments"], "app-server", "--strict-config", "--stdio",
    ])


if __name__ == "__main__":
    launch(prepare())
