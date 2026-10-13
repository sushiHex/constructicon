"""WRITE qualification pins and the trusted fixed request (L0, no host I/O).

Fixture identity binds reviewed seed bytes and the canonical authority
relationship. It is not a custody proof: trusted assembly checks the actual
artifacts before registration, admission or recovery. Locators stay private.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, TypeAlias

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from constructicon.core.address import GitSha
from constructicon.core.effect import CheckStatus
from constructicon.core.identity import Digest
from constructicon.core.run import RunStatus


def _git_object(value: GitSha) -> GitSha:
    if len(value) not in (40, 64) or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("qualification requires an exact lowercase Git object identity")
    return value


_GitObject: TypeAlias = Annotated[GitSha, AfterValidator(_git_object)]


class QualificationCapabilityPin(BaseModel):
    """An exact capability descriptor, checked against its assembled provider."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_id: str = Field(min_length=1)
    revision: Digest


class QualificationFixturePin(BaseModel):
    """One disposable authority's reviewed seed and unchanged target."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    identity: Digest
    base_commit: _GitObject
    target_ref: str

    @field_validator("target_ref")
    @classmethod
    def _full_ref(cls, value: str) -> str:
        if not value.startswith("refs/") or len(value) == len("refs/"):
            raise ValueError("qualification requires a full target ref")
        return value


class WriteQualificationPins(BaseModel):
    """WRITE-only assembly pins; a gate revision already names its check set."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace: QualificationCapabilityPin
    gate: QualificationCapabilityPin
    fixture: QualificationFixturePin
    report_definition: Digest


class WriteQualificationRequest(BaseModel):
    """Trusted entry data; the model sees only the writer's fixed task literal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    authorization_id: str = Field(min_length=1)
    fixture_identity: Digest
    base_commit: _GitObject


# Arrays obey the L4 whole-report byte ceiling, not an invented acquisition cap.
# Number/model bounds mirror the frozen protocol's NUMBER_CHARS/NAMEABLE_METHOD.
_Count: TypeAlias = Annotated[int, Field(strict=True, ge=0, le=10**32 - 1)]
_ModelName: TypeAlias = Annotated[
    str, Field(strict=True, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
]
_RunIdentity: TypeAlias = Annotated[str, Field(pattern=r"^run-[0-9a-f]{32}$")]
_LeaseIdentity: TypeAlias = Annotated[str, Field(pattern=r"^lease-[0-9a-f]{32}$")]
_AcquisitionIdentity: TypeAlias = Annotated[str, Field(pattern=r"^acq-[0-9a-f]{32}$")]
_AttestationIdentity: TypeAlias = Annotated[str, Field(pattern=r"^att-[0-9a-f]{64}$")]
_Seconds: TypeAlias = Annotated[float, Field(ge=0, allow_inf_nan=False)]
WriteObservation: TypeAlias = Literal["terminal", "timeout", "error"]


def _wire_integer(value: int) -> int:
    if len(repr(value)) > 32:
        raise ValueError("a protocol number has at most 32 characters")
    return value


_WireInteger: TypeAlias = Annotated[int, Field(strict=True), AfterValidator(_wire_integer)]


class WriteReportIssue(StrEnum):
    AUTHORIZATION_MISMATCH = "authorization_mismatch"
    ASSEMBLY_MISMATCH = "assembly_mismatch"
    RUN_MISSING = "run_missing"
    RUN_NOT_SUCCEEDED = "run_not_succeeded"
    CHECKPOINT_CHAIN = "checkpoint_chain"
    ATTEMPT_MISSING = "attempt_missing"
    ATTEMPT_INVALID = "attempt_invalid"
    ATTEMPT_MISMATCH = "attempt_mismatch"
    ATTEMPT_NOT_COMPLETED = "attempt_not_completed"
    CANDIDATE_MISMATCH = "candidate_mismatch"
    ATTESTATION_MISSING = "attestation_missing"
    ATTESTATION_MISMATCH = "attestation_mismatch"
    GATE_FAILED = "gate_failed"
    OBLIGATIONS_MISSING = "obligations_missing"
    OBLIGATIONS_UNSETTLED = "obligations_unsettled"
    OBLIGATION_MISMATCH = "obligation_mismatch"
    TARGET_DRIFT = "target_drift"
    EVIDENCE_UNAVAILABLE = "evidence_unavailable"
    REPORT_OVERFLOW = "report_overflow"
    TELEMETRY_INVALID = "telemetry_invalid"
    OBSERVATION_TIMEOUT = "observation_timeout"
    OBSERVATION_ERROR = "observation_error"


class WriteReportLimits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    exchange_s: _Count
    capture_s: _Count
    gate_s: _Count
    check_s: _Seconds
    observation_s: _Count
    callback_limit: _Count
    program_bytes: _Count
    callback_output_bytes: _Count
    cumulative_input_bytes: _Count
    artifact_bytes: _Count
    stdout_bytes: _Count
    record_bytes: _Count
    stderr_bytes: _Count


class WriteReportSpendReading(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    has_credits: bool | None = None
    unlimited: bool | None = None
    balance_zero: bool | None = None
    spend_control_reached: bool | None = None
    rate_limit_reached: bool | None = None
    primary_used_percent: _WireInteger | None = None
    secondary_used_percent: _WireInteger | None = None


WorkerResultCategory: TypeAlias = Literal[
    "success", "nonzero", "timeout", "output_bound", "incomplete", "invalid_utf8"
]


class CallbackObservation(BaseModel):
    """A bounded prefix of admitted callbacks, never a count of inbound requests.

    Eight is the closed mediated-callback ceiling, not a new execution budget.
    Null means no worker result was observed, not that no worker ran.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1]
    admitted_started: Annotated[int, Field(strict=True, ge=0, le=8)]
    admitted_completed: Annotated[int, Field(strict=True, ge=0, le=8)]
    worker_results: tuple[WorkerResultCategory | None, ...] = Field(max_length=8)

    @model_validator(mode="before")
    @classmethod
    def _version(cls, value: object) -> object:
        if isinstance(value, dict) and "schema_version" in value and (
            type(value["schema_version"]) is not int or value["schema_version"] != 1
        ):
            raise ValueError("callback observation requires exact schema 1")
        return value

    @model_validator(mode="after")
    def _prefix(self) -> CallbackObservation:
        if self.admitted_started != len(self.worker_results) or (
            self.admitted_completed > self.admitted_started
            or any(result != "success" for result in self.worker_results[:self.admitted_completed])
        ):
            raise ValueError("callback observations contradict the admitted prefix")
        return self

    @property
    def responses_complete(self) -> bool:
        """All admitted responses completed; zero is valid and not mandatory usage."""
        return self.admitted_completed == self.admitted_started


class WriteReportTelemetry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    requested_model: _ModelName | None = None
    effort: _ModelName | None = None
    served_model: _ModelName | None = None
    input_tokens: _Count | None = None
    output_tokens: _Count | None = None
    before: WriteReportSpendReading | None = None
    after: WriteReportSpendReading | None = None
    callbacks: CallbackObservation | None = None
    # An observed final outcome snapshot, not fsync acknowledgement or all responses completed.
    callbacks_final_snapshot: Annotated[bool, Field(strict=True)] | None = None
    backend_request_count: None = None
    vendor_retry_count: None = None

    @model_validator(mode="after")
    def _callback_provenance(self) -> WriteReportTelemetry:
        if (self.callbacks is None) != (self.callbacks_final_snapshot is None):
            raise ValueError("callback observations require explicit snapshot provenance")
        return self


class WriteReportObligation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Literal["executor", "workspace", "gate", "unexpected"]
    lease_id: _LeaseIdentity
    acquisition_id: _AcquisitionIdentity
    epoch: _Count
    state: Literal["active", "closed", "lost"]
    disposition: Literal["released", "discarded"] | None


class WriteReportCheck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    identity: Digest
    status: CheckStatus


class WriteReportInstalledIdentities(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_revision: Digest
    executable_digest: Digest
    runtime_digest: Digest
    adapter_revision: Digest
    decoder_revision: Digest
    isolation_revision: Digest
    configuration_digest: Digest
    limits_digest: Digest
    callback_protocol_revision: Digest
    callback_catalog_digest: Digest
    authenticated_startup_conformance_revision: Digest
    subscription_mode_conformance_revision: Digest


class CaptureQualificationReport(BaseModel):
    """An allowlisted projection, not authority to merge or dispatch again."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1, 2] = 1
    verdict: Literal["passed", "not-qualified", "incomplete"]
    observation: WriteObservation
    issues: tuple[WriteReportIssue, ...] = Field(max_length=len(WriteReportIssue))
    details_complete: bool
    run_id: _RunIdentity
    report_definition: Digest
    fixture_identity: Digest | None = None
    manifest_hash: Digest | None = None
    run_status: RunStatus | None = None
    checkpoint_chain_validated: bool = False
    workspace_revision: Digest | None = None
    gate_revision: Digest | None = None
    base_commit: _GitObject | None = None
    candidate: _GitObject | None = None
    candidate_tree: _GitObject | None = None
    target_unchanged: bool | None = None
    attestation_id: _AttestationIdentity | None = None
    gate_subject_identity: Digest | None = None
    check_set_hash: Digest | None = None
    obligation_count: _Count | None = None
    check_count: _Count | None = None
    obligations: tuple[WriteReportObligation, ...] = ()
    checks: tuple[WriteReportCheck, ...] = ()

    def _capture_complete(self, roles: set[str]) -> bool:
        return (
            not self.issues
            and self.details_complete
            and self.observation == "terminal"
            and self.run_status == RunStatus.SUCCEEDED
            and self.checkpoint_chain_validated
            and self.target_unchanged is True
            and all(
                value is not None
                for value in (
                    self.fixture_identity,
                    self.manifest_hash,
                    self.workspace_revision,
                    self.gate_revision,
                    self.base_commit,
                    self.candidate,
                    self.candidate_tree,
                    self.attestation_id,
                    self.gate_subject_identity,
                    self.check_set_hash,
                )
            )
            and self.obligation_count == len(self.obligations)
            and {row.role for row in self.obligations} == roles
            and all(
                row.state == "closed" and row.disposition is not None and row.epoch > 0
                for row in self.obligations
            )
            and all(
                max(
                    (row for row in self.obligations if row.role == role), key=lambda row: row.epoch
                ).disposition
                == "released"
                for role in roles
            )
            and self.check_count == len(self.checks)
            and bool(self.checks)
            and all(check.status == "passed" for check in self.checks)
        )


class SmokeQualificationReport(CaptureQualificationReport):
    """The contained capture proof, with no fabricated executor or turn facts."""

    schema_version: Literal[1] = 1

    @model_validator(mode="after")
    def _passing_facts(self) -> SmokeQualificationReport:
        if len(set(self.issues)) != len(self.issues):
            raise ValueError("report issues are a finite set")
        if self.verdict == "passed" and not self._capture_complete({"workspace", "gate"}):
            raise ValueError("a passing smoke report requires complete affirmative facts")
        return self


class WriteQualificationReport(CaptureQualificationReport):
    schema_version: Literal[2] = 2
    authorization_identity: Digest
    attempt_identity: Digest | None = None
    attempt_epoch: _Count | None = None
    turn_dispatch: Literal[
        "unknown", "acquired-only", "not dispatched", "possibly dispatched", "completed"
    ] = "unknown"
    turn_status: Literal["success", "partial", "failure"] | None = None
    writer_lease_id: _LeaseIdentity | None = None
    writer_acquisition_id: _AcquisitionIdentity | None = None
    limits: WriteReportLimits | None = None
    installed: WriteReportInstalledIdentities | None = None
    telemetry: WriteReportTelemetry | None = None

    @model_validator(mode="after")
    def _passing_facts(self) -> WriteQualificationReport:
        if len(set(self.issues)) != len(self.issues):
            raise ValueError("report issues are a finite set")
        if self.verdict == "passed" and not (
            self._capture_complete({"executor", "workspace", "gate"})
            and self.turn_dispatch == "completed"
            and self.turn_status == "success"
            and (
                self.telemetry is None
                or self.telemetry.callbacks is None
                or (
                    self.telemetry.callbacks_final_snapshot is True
                    and self.telemetry.callbacks.responses_complete
                )
            )
            and self.target_unchanged is True
            and self.limits is not None
            and self.installed is not None
            and all(
                value is not None
                for value in (
                    self.attempt_identity,
                    self.attempt_epoch,
                    self.writer_lease_id,
                    self.writer_acquisition_id,
                )
            )
        ):
            raise ValueError("a passing report requires complete affirmative facts")
        return self
