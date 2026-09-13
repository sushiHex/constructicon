"""FakeNativeOperatorExecutor — the schema-3 seam's genuine second consumer (I6, I7).

Scripted: instruction -> structured output. It runs everywhere with zero
credentials and spawns no native process, opens no vendor session and mounts no
store. Rate-limit and overage facts stay ``None`` because this double observes
nothing (I4); a fake proves its own behavior, never a real launcher's safety.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from constructicon.core.executor import (
    ExecutorError,
    ExecutorFailure,
    ExecutorOutcome,
    ExecutorSuccess,
    TaskSpec,
)
from constructicon.core.grants import EffectiveGrants
from constructicon.core.identity import canonical_json
from constructicon.core.native_operator import NativeOperatorExecutorProfileV3
from constructicon.core.workspace import WorkspaceView
from constructicon.substrate.external.fake import FakeExternalLedger


class FakeNativeOperatorExecutor:
    def __init__(
        self,
        script: Mapping[str, Any],
        *,
        profile: NativeOperatorExecutorProfileV3,
        ledger: FakeExternalLedger | None = None,
    ) -> None:
        self._script = dict(script)
        self._profile = profile
        self.ledger = ledger if ledger is not None else FakeExternalLedger()

    @property
    def calls(self) -> list[TaskSpec]:
        """Every invocation ever made against this executor's ledger, in call order."""
        return [
            TaskSpec.model_validate_json(task_json)
            for task_json in self.ledger.executor_calls()
        ]

    @property
    def profile(self) -> NativeOperatorExecutorProfileV3:
        return self._profile

    def validate_grants(self, grants: EffectiveGrants) -> tuple[str, ...]:
        return self._profile.grant_faults(grants)

    async def execute(
        self,
        task: TaskSpec,
        *,
        workspace: WorkspaceView | None,
        grants: EffectiveGrants,
    ) -> ExecutorOutcome:
        started = time.monotonic()
        self.ledger.record_executor_call(self._profile.name, task.model_dump_json())
        problems = self.validate_grants(grants)
        if self._profile.grant_policy.workspace_required and not isinstance(
            workspace, WorkspaceView
        ):
            problems += ("executor requires a WorkspaceView",)
        if problems:
            return ExecutorFailure(
                error=ExecutorError(kind="unavailable", detail="; ".join(problems)),
                elapsed_s=time.monotonic() - started,
            )
        if task.instruction not in self._script:
            return ExecutorFailure(
                error=ExecutorError(
                    kind="exit",
                    detail=(
                        f"fake native operator executor has no scripted reply for "
                        f"{task.instruction!r}; scripted: {sorted(self._script)}"
                    ),
                    exit_code=1,
                ),
                elapsed_s=time.monotonic() - started,
            )
        output = self._script[task.instruction]
        return ExecutorSuccess(
            raw_reply=canonical_json(output),
            output=output,
            requested_model=grants.model_selection.model,
            served_model=None,  # I4: the double does not pretend a vendor spoke
            rate_limit=None,  # I4: it observes no quota or overage fact
            elapsed_s=time.monotonic() - started,
        )
