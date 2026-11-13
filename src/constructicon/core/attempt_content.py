"""Digests and lengths of one attempt's callback content and reply (L0, no host I/O).

Kept apart from ``qualification_write``: the WRITE report definition hashes that
whole module, and this block belongs to maintenance attempts alone.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from constructicon.core.qualification_write import CallbackObservation

# Restated, not imported (L0 imports no substrate): the decoder's program ceiling
# (codex_protocol.TOOL_PROGRAM_BYTES) and the default launcher stdout ceiling
# (linux.ProcessLimits.stdout_bytes). test_codex_callback_observations.py pins both.
CALLBACK_PROGRAM_BYTES = 128 * 1024
CONTENT_DIGEST_BYTES = 32 * 1024 * 1024


class ContentDigest(BaseModel):
    """The sha256 and exact length of some bytes, never the bytes themselves.

    A digest of short or guessable bytes confirms a guess; it is a fingerprint
    for comparison, not a confidentiality boundary.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    sha256: Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
    bytes: Annotated[int, Field(strict=True, ge=0, le=CONTENT_DIGEST_BYTES)]


class CallbackContent(BaseModel):
    """One admitted callback's content, by digest.

    ``program`` is the stdin handed to the worker launcher; null means that
    callback never reached the launcher. ``output`` is the worker's retained
    stdout, whatever its category; null means no worker result was observed.
    A worker that never received a program has no output.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    program: ContentDigest | None
    output: ContentDigest | None

    @model_validator(mode="after")
    def _coherent(self) -> CallbackContent:
        if self.program is not None and self.program.bytes > CALLBACK_PROGRAM_BYTES:
            raise ValueError("a callback program exceeds the decoder's ceiling")
        if self.output is not None and self.program is None:
            raise ValueError("a worker output requires the program that produced it")
        return self


class ContentDigests(BaseModel):
    """Digests and lengths of one attempt's callback content and final reply.

    ``callbacks`` aligns index for index with ``CallbackObservation``'s admitted
    prefix. ``reply`` is the outcome's output text: the terminal answer on
    success, the last completed message otherwise; null means it carried none.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    callbacks: tuple[CallbackContent, ...] = Field(max_length=8)
    reply: ContentDigest | None

    def contradicts(self, observation: CallbackObservation) -> bool:
        """Whether these digests disagree with the admitted prefix they describe."""
        return len(self.callbacks) != observation.admitted_started or any(
            (content.output is None) != (result is None)
            for content, result in zip(self.callbacks, observation.worker_results, strict=True)
        )
