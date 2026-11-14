"""Which guard refused: one closed set, named at the guard (docs/designs/REFUSAL_CODE.md).

A code names the guard that fired. It never classifies behaviour and never
selects policy: no check result, attestation, subject or manifest holds one.
The walker seals the codes a ``ContractViolation`` carries beside its message,
and absence means "not recorded", for current writers as for old ones.
"""

from __future__ import annotations

from enum import StrEnum

MAX_REFUSAL_CODES = 12


class RefusalCode(StrEnum):
    WRITER_WORKSPACE = "writer.workspace"
    WRITER_BASE = "writer.base"
    WRITER_INSTRUCTION = "writer.instruction"
    WRITER_NOT_POSITIVE = "writer.not_positive"
    CAPTURE_RETURN = "capture.return"
    CAPTURE_UNCHANGED = "capture.unchanged"
    CAPTURE_REPOSITORY = "capture.repository"
    CAPTURE_PATHS = "capture.paths"
    CAPTURE_BASE = "capture.base"
    CHECKER_INPUT = "checker.input"
    GATE_NOT_POSITIVE = "gate.not_positive"
    GATE_SUBJECT = "gate.subject"
