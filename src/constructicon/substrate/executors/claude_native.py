"""The finite Claude native recipe, separate from Codex's catalog/store law.

This is a credential-free composition candidate, never vendor qualification.
Only the opaque credential file persists. Its refresh staging and lock siblings
live in disposable writable directories; immutable policy lives elsewhere.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from constructicon.core.errors import ContractViolation
from constructicon.core.identity import Digest, digest
from constructicon.substrate.executors._supervisor import CLAUDE_NATIVE_LABEL
from constructicon.substrate.executors.claude_startup import fixed_environment, fixed_policy
from constructicon.substrate.executors.egress import EgressSocket
from constructicon.substrate.executors.operator_store import BindingCheck

VENDOR_MOUNT = "/opt/claude"
EXECUTABLE = f"{VENDOR_MOUNT}/claude"
CONFIG_ROOT = "/tmp/claude-config"
STORAGE_PARENT = "/tmp/claude-storage"
SECURE_ROOT = f"{STORAGE_PARENT}/secure"
ANTHROPIC_ROOT = "/tmp/anthropic-config"
CREDENTIAL_MOUNT = f"{SECURE_ROOT}/.credentials.json"
ADMIN_ROOT = "/etc/claude-code"
POLICY_MOUNT = f"{ADMIN_ROOT}/managed-settings.json"
MCP_MOUNT = f"{ADMIN_ROOT}/managed-mcp.json"
MANAGED_MCP = b'{"mcpServers":{}}\n'
CLAUDE_PROFILE = CLAUDE_NATIVE_LABEL
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})


def native_environment() -> dict[str, str]:
    """Source-reviewed successor: initially protect the bridge's exact proxy."""
    return {**fixed_environment(), "HTTPS_PROXY": "http://127.0.0.1:18080",
            "HOME": "/tmp/home", "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
            "CLAUDE_CONFIG_DIR": CONFIG_ROOT, "CLAUDE_SECURESTORAGE_CONFIG_DIR": SECURE_ROOT,
            "ANTHROPIC_CONFIG_DIR": ANTHROPIC_ROOT, "CLAUDE_CODE_ENTRYPOINT": "sdk-cli"}


@dataclass(frozen=True)
class ClaudeNativeVendor:
    """One fixed native tree and explicit sealed session selection."""

    tree: Path
    model: str
    effort: str
    expected_tree: Digest

    def __post_init__(self) -> None:
        if (type(self.model) is not str or _MODEL.fullmatch(self.model) is None
                or type(self.effort) is not str or self.effort not in _EFFORTS):
            raise ContractViolation("invalid sealed Claude model or effort")

    @property
    def command(self) -> tuple[str, ...]:
        return (EXECUTABLE, "--print", "--input-format", "stream-json", "--output-format",
                "stream-json", "--verbose", "--safe-mode", "--tools", "",
                "--model", self.model, "--effort", self.effort)

    def check(self) -> None:
        """Admit fixed regular content, never a helper/link/device or mutable tree."""
        if not self.tree.is_absolute():
            raise ContractViolation("the Claude vendor tree needs an absolute path")
        for parent in self.tree.parents:
            info = os.lstat(parent)
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                    or info.st_mode & 0o022):
                raise ContractViolation("Claude vendor ancestors must be fixed root directories")
        pending = [self.tree]
        while pending:
            current = pending.pop()
            info = os.lstat(current)
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                    or info.st_mode & 0o6022):
                raise ContractViolation("Claude vendor directories must be fixed and root-owned")
            with os.scandir(current) as entries:
                for entry in entries:
                    info = os.lstat(entry.path)
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(Path(entry.path))
                    elif (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                          or info.st_mode & 0o6022):
                        raise ContractViolation("Claude vendor files must be fixed and root-owned")
        executable = os.lstat(self.tree / "claude")
        if not stat.S_ISREG(executable.st_mode) or not executable.st_mode & 0o111:
            raise ContractViolation("the fixed Claude executable is missing or not executable")

    @property
    def revision(self) -> Digest:
        return digest("claude-native-recipe", 1, {
            "implementation": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "tree": str(self.tree), "expected_tree": self.expected_tree, "command": self.command,
            "environment": native_environment(), "policy": fixed_policy(),
            "managed_mcp": MANAGED_MCP.decode(), "final_label": CLAUDE_PROFILE,
        })


@dataclass(frozen=True)
class ClaudeNativeStoreMount:
    """The one persistent native object, plus its separate retained guard."""

    lock_fd: int
    credential_fd: int
    before_spawn: Callable[[], BindingCheck]
    egress: EgressSocket | None = None

    def __post_init__(self) -> None:
        fds = (self.lock_fd, self.credential_fd)
        if any(type(fd) is not int or fd < 0 for fd in fds) or len(set(fds)) != len(fds):
            raise ContractViolation("the Claude store requires two distinct descriptors")

    @property
    def mount_fds(self) -> tuple[int, ...]:
        return (self.credential_fd,)


@dataclass(frozen=True)
class ClaudeNativeLayout:
    """Fixed sealed admin inputs; no writable native ancestor can replace them."""

    policy_fd: int
    mcp_fd: int

    def __post_init__(self) -> None:
        fds = (self.policy_fd, self.mcp_fd)
        if any(type(fd) is not int or fd < 0 for fd in fds) or len(set(fds)) != len(fds):
            raise ContractViolation("the Claude layout requires two distinct descriptors")

    @classmethod
    def seal(cls) -> ClaudeNativeLayout:
        # Local import keeps the shared sealed-data primitive single-defined.
        from constructicon.substrate.executors.linux import sealed_data_fd

        policy = sealed_data_fd(json.dumps(fixed_policy(), sort_keys=True).encode() + b"\n")
        try:
            return cls(policy, sealed_data_fd(MANAGED_MCP))
        except BaseException:
            os.close(policy)
            raise

    @property
    def mount_fds(self) -> tuple[int, ...]:
        return (self.policy_fd, self.mcp_fd)

    def close(self) -> None:
        for fd in self.mount_fds:
            os.close(fd)
