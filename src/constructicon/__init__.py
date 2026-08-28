"""Constructicon — an OS for agentic software-engineering pipelines.

One authored graph IR, one sealed ExecutionManifest per run, scoped capability
leases, journal-minted attestations, idempotent effects with receipts, and
component versions that propagate only through explicit promotion.

Layers (imports flow strictly toward ``core``):

- ``constructicon.core`` — every contract in the system, defined once.
- ``constructicon.substrate`` — services implementing core contracts.
- ``constructicon.runtime`` — registry, validator, walker; depends on core only.
- ``constructicon.sdk`` — authoring sugar compiling to the IR (arrives with M5).
- ``constructicon.api`` — the system object; assembles substrate into runtime.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("constructicon")
except PackageNotFoundError:
    __version__ = "0+unknown"
