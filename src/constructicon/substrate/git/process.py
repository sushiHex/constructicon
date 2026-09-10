"""Bounded async Git plumbing over trusted metadata, never a mutable stage.

Authority export and quarantine verification share this pump. Contained Git
uses LinuxLauncher instead. A trusted writer inherits the acquisition guard,
so recovery cannot remove its files while the OS process still owns them.
"""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from constructicon.core.errors import ContractViolation
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.executors.linux import ProcessLimits
from constructicon.substrate.git.authority import _PINNED_ENV

# Strict Git parses untrusted objects in the quarantine. Bound the parser
# itself, not just its eventual inventory: compressed bytes can expand first.
# This tiny exec trampoline owns no process protocol or mutable Git metadata.
_LIMITED_EXEC = """
import os, resource, sys
for kind, bound in ((resource.RLIMIT_AS, 512 * 1024 * 1024),
                    (resource.RLIMIT_FSIZE, 128 * 1024 * 1024),
                    (resource.RLIMIT_CPU, 30), (resource.RLIMIT_CORE, 0)):
    resource.setrlimit(kind, (bound, bound))
os.execv(sys.argv[1], sys.argv[1:])
"""


@dataclass(frozen=True)
class GitProcess:
    executable: str
    limits: ProcessLimits

    async def run(
        self, *args: str, cwd: Path | str, stdin: bytes = b"", guard: int | None = None,
    ) -> bytes:
        if len(stdin) > self.limits.artifact_bytes:
            raise ContractViolation("trusted Git input exceeds artifact bound")
        if guard is not None and sys.platform != "linux":
            raise ContractViolation("guarded Git work requires Linux")
        environment = {
            "PATH": os.environ.get("PATH", os.defpath), **_PINNED_ENV,
            "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0",
        }
        command = (
            self.executable, "-c", "core.hooksPath=" + os.devnull,
            "-c", "protocol.allow=never", "-c", "gc.auto=0",
            "-c", "maintenance.auto=false", *args,
        )
        if sys.platform == "linux":
            command = (sys.executable, "-I", "-c", _LIMITED_EXEC, *command)
        spawn = asyncio.create_task(asyncio.create_subprocess_exec(
            *command, cwd=cwd, env=environment,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, close_fds=True,
            pass_fds=(guard,) if guard is not None else (),
        ))
        process: asyncio.subprocess.Process | None = None
        tasks: list[asyncio.Task[None]] = []
        output, errors = bytearray(), bytearray()
        overflow = False

        async def feed() -> None:
            assert process is not None and process.stdin is not None
            try:
                for offset in range(0, len(stdin), 8192):
                    process.stdin.write(stdin[offset:offset + 8192])
                    await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                process.stdin.close()

        async def drain(stream: asyncio.StreamReader, target: bytearray, bound: int) -> None:
            nonlocal overflow
            while chunk := await stream.read(8192):
                room = max(0, bound - len(target))
                target.extend(chunk[:room])
                if len(chunk) > room:
                    overflow = True
                    assert process is not None
                    with suppress(ProcessLookupError):
                        process.kill()

        async def cleanup() -> None:
            nonlocal process
            process = process or await spawn
            if process.stdin is not None:
                process.stdin.close()
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()
            if not tasks:
                assert process.stdout is not None and process.stderr is not None
                tasks.extend((
                    asyncio.create_task(drain(process.stdout, output, self.limits.artifact_bytes)),
                    asyncio.create_task(drain(process.stderr, errors, self.limits.stderr_bytes)),
                ))
            try:
                await asyncio.gather(*tasks)
            finally:
                await process.wait()

        try:
            async with asyncio.timeout(30):
                process = await asyncio.shield(spawn)
                assert process.stdout is not None and process.stderr is not None
                tasks = [
                    asyncio.create_task(feed()),
                    asyncio.create_task(drain(process.stdout, output, self.limits.artifact_bytes)),
                    asyncio.create_task(drain(process.stderr, errors, self.limits.stderr_bytes)),
                ]
                await process.wait()
                await asyncio.shield(asyncio.gather(*tasks))
                if overflow:
                    raise ContractViolation(
                        "trusted Git output exceeds artifact materialization bound",
                    )
                if process.returncode:
                    detail = errors.decode("utf-8", errors="replace")[:500]
                    raise ContractViolation(f"trusted Git {args[0]} failed: {detail}")
        finally:
            await finish_owned(asyncio.create_task(cleanup()))
        return bytes(output)
