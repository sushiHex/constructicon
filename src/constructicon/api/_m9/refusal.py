"""Bounded local-application refusals; no backend text crosses the CLI boundary."""

from __future__ import annotations

import re
from typing import Literal

from constructicon.core.address import RunId
from constructicon.core.admission import AdmissionCode, AdmissionRejected
from constructicon.core.control import ControlCode, ControlRejected
from constructicon.core.identity import canonical_json


class TrialRefused(ValueError):
    def __init__(
        self, stage: str,
        code: Literal["M9_CONTROL_INVALID_REFUSAL", "M9_CONTROL_REJECTED",
                      "M9_UNEXPECTED_CONTROL_RESULT"],
        *, codes: tuple[ControlCode | AdmissionCode, ...] = (),
    ) -> None:
        if any(not isinstance(item, (ControlCode, AdmissionCode)) for item in codes):
            raise ValueError("M9_INVALID_REFUSAL_PROJECTION")
        self.stage = stage if re.fullmatch(r"[a-z][a-z0-9-]{0,47}", stage) else "invalid-stage"
        self.code = code
        self.codes = tuple(str(item) for item in codes[:10])
        self.partial = len(codes) > 10
        super().__init__(canonical_json(self.projection()))

    def projection(self) -> dict[str, object]:
        return {"status": "refused", "stage": self.stage, "code": self.code,
                "control_codes": self.codes, "partial": self.partial}


def check_control(result: object, stage: str) -> None:
    if isinstance(result, (ControlRejected, AdmissionRejected)):
        if not result.faults or any(
            not isinstance(fault.code, (ControlCode, AdmissionCode)) for fault in result.faults
        ):
            raise TrialRefused(stage, "M9_CONTROL_INVALID_REFUSAL")
        codes = tuple(sorted({fault.code for fault in result.faults}))
        raise TrialRefused(stage, "M9_CONTROL_REJECTED", codes=codes)


class TrialWaitTimeout(TimeoutError):
    def __init__(self, stage: str, run: RunId, status: str, liveness: str) -> None:
        self.stage, self.run, self.status, self.liveness = stage, run, status, liveness
        super().__init__(
            f"M9_WAIT_TIMEOUT stage={stage} run={run} status={status} "
            f"liveness={liveness}; preserve the store, inspect recorded owner liveness, "
            "and retry the same command only when its run/command lease permits recovery"
        )

    def projection(self) -> dict[str, object]:
        return {
            "status": "refused", "code": "M9_WAIT_TIMEOUT",
            "stage": self.stage if re.fullmatch(r"[a-z][a-z0-9-]{0,47}", self.stage) else None,
            "run": self.run if re.fullmatch(r"[a-z0-9-]{1,128}", self.run) else None,
            "run_status": self.status if self.status in {
                "missing", "pending", "running", "succeeded", "failed", "cancelled", "parked",
            } else None,
            "liveness": self.liveness if self.liveness in {
                "live", "lost", "not_applicable", "unknown",
            } else None,
        }
