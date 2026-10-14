"""Closed data contracts for the fixed plan-manifest maintenance application."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from constructicon.core.address import GitSha, RunId
from constructicon.core.envelope import GitRef
from constructicon.core.gates import MergeEvaluation
from constructicon.core.identity import Digest

VECTOR_PATH = "tests/vectors/plan_manifest.json"
TARGET_PATH = "scripts/regen_plan_manifest.py"


class PlanManifestRequest(BaseModel):
    """Trusted assembly data, never a caller-selected instruction or exam."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    repository: str = Field(min_length=1, max_length=4096)
    target_ref: str = Field(pattern=r"^refs/heads/[A-Za-z0-9/_-]+$", max_length=256)
    base_commit: GitSha = Field(pattern=r"^[0-9a-f]{40}([0-9a-f]{24})?$")
    target_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    check_set_hash: Digest
    vector_path: Literal["tests/vectors/plan_manifest.json"] = "tests/vectors/plan_manifest.json"


class PlanManifestResult(BaseModel):
    """Application acceptance proves one base parent plus the gated data tree.

    This does not claim installation, merge, or durable rendered-artifact storage.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId
    candidate: GitRef
    evaluation: MergeEvaluation
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    render_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
