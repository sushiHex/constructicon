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

    PERMIT_RUN = "permit.run"
    PERMIT_INVOCATION = "permit.invocation"
    PERMIT_BINDING = "permit.binding"
    PERMIT_SOURCE_GRAPH = "permit.source_graph"
    PERMIT_CAPABILITY = "permit.capability"
    PERMIT_REVISION = "permit.revision"
    PERMIT_OPERATOR_BINDING = "permit.operator_binding"
    PERMIT_GRANTS = "permit.grants"
    PERMIT_EPOCH = "permit.epoch"
    PERMIT_EXPIRED = "permit.expired"

    CALLBACK_ORDER = "callback.order"
    CALLBACK_NOT_OPEN = "callback.not_open"
    CALLBACK_MALFORMED = "callback.malformed"
    CALLBACK_REPEATED_ID = "callback.repeated_id"
    CALLBACK_CALL_CEILING = "callback.call_ceiling"
    CALLBACK_DEADLINE = "callback.deadline"
    CALLBACK_UNANSWERED = "callback.unanswered"
    CALLBACK_PROGRAM_BOUND = "callback.program_bound"
    CALLBACK_TOOL_OUTPUT_BOUND = "callback.tool_output_bound"
    CALLBACK_WORKER_NONZERO = "callback.worker.nonzero"
    CALLBACK_WORKER_TIMEOUT = "callback.worker.timeout"
    CALLBACK_WORKER_OUTPUT_BOUND = "callback.worker.output_bound"
    CALLBACK_WORKER_INCOMPLETE = "callback.worker.incomplete"
    CALLBACK_WORKER_INVALID_UTF8 = "callback.worker.invalid_utf8"

    # The change-review advice route's own guards (ADR 0025, section 7).
    ADVICE_SUMMARY = "advice.summary"
    ADVICE_INSTRUCTION = "advice.instruction"
    ADVICE_INSTRUCTION_BOUND = "advice.instruction_bound"
    ADVICE_NOT_POSITIVE = "advice.not_positive"
    ADVICE_REPLY_BOUND = "advice.reply_bound"
    ADVICE_PERMIT = "advice.permit"
    ADVICE_PROVIDER = "advice.provider"
    ADVICE_JOURNAL = "advice.journal"
    ADVICE_ADMISSION = "advice.admission"
    ADVICE_SOURCE = "advice.source"
