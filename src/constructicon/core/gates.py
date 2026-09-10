"""One merge-evaluation value; an explicit async contract for contained gates."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from constructicon.core.address import GitSha
from constructicon.core.effect import CheckResult, MergeSubject


class MergeEvaluation(BaseModel):
    """The typed gate verdict a merge node needs — subject, authority id, and
    evidence. A conflict has no subject and can authorize nothing."""

    model_config = ConfigDict(frozen=True)

    subject: MergeSubject | None
    attestation_id: str | None
    checks: tuple[CheckResult, ...]

    @property
    def ok(self) -> bool:
        return (
            self.subject is not None
            and self.attestation_id is not None
            and bool(self.checks)
            and all(check.ok for check in self.checks)
        )


@runtime_checkable
class MergeGate(Protocol):
    """``gates.contained`` never uses the historical synchronous convention."""

    @property
    def target_ref(self) -> str: ...

    async def verify(self, candidate: GitSha) -> MergeEvaluation: ...
