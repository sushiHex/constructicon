"""FakeExecutor — the CI backbone (I7) and the executor seam's second consumer (I6).

Scripted: instruction -> structured output. Runs everywhere with zero
credentials; its isolation profile trivially satisfies READ because it touches
nothing at all.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from constructicon.core.executor import (
    ExecutorError,
    ExecutorFailure,
    ExecutorOutcome,
    ExecutorProfile,
    ExecutorSuccess,
    TaskSpec,
)
from constructicon.core.grants import EffectiveGrants, IsolationProfile, Posture
from constructicon.core.identity import canonical_json


class FakeExecutor:
    def __init__(self, script: Mapping[str, Any], *, name: str = "fake") -> None:
        self._script = dict(script)
        self._profile = ExecutorProfile(
            name=name,
            structured_output=True,
            postures=frozenset({Posture.READ}),
            isolation=IsolationProfile(
                filesystem="none",
                process_tree_owned=True,
                environment_allowlisted=True,
                network_enforced=True,
            ),
        )
        self.calls: list[TaskSpec] = []

    @property
    def profile(self) -> ExecutorProfile:
        return self._profile

    def validate_grants(self, grants: EffectiveGrants) -> tuple[str, ...]:
        if grants.posture not in self._profile.postures:
            return (f"fake executor offers no {grants.posture.value!r} posture",)
        return ()

    async def execute(
        self,
        task: TaskSpec,
        *,
        workspace: object | None,
        grants: EffectiveGrants,
    ) -> ExecutorOutcome:
        started = time.monotonic()
        self.calls.append(task)
        problems = self.validate_grants(grants)
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
                        f"fake executor has no scripted reply for {task.instruction!r}; "
                        f"scripted: {sorted(self._script)}"
                    ),
                    exit_code=1,
                ),
                elapsed_s=time.monotonic() - started,
            )
        output = self._script[task.instruction]
        return ExecutorSuccess(
            raw_reply=canonical_json(output),
            output=output,
            requested_model=(
                grants.model_selection.model
                if grants.model_selection.kind == "explicit"
                else None
            ),
            served_model=None,  # I4: the fake does not pretend a backend spoke
            elapsed_s=time.monotonic() - started,
        )
