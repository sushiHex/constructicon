"""One error taxonomy, deliberately small.

A red gate is NOT an error — it is a CheckResult the loop consumes.
"""

from __future__ import annotations


class ConstructiconError(Exception):
    """Base for every framework error."""


class ContractViolation(ConstructiconError):
    """A payload failed validation at a boundary — a bug; fail fast."""


class AdmissionError(ConstructiconError):
    """Validation rejected a graph. Itemized, per-fault, repair-naming (I9)."""

    def __init__(self, faults: list[str]) -> None:
        self.faults = faults
        super().__init__("; ".join(faults))


class ExecutorFailed(ConstructiconError):
    """Process-level executor failure; salvage lives on the outcome (I4)."""


class TransportDamaged(ConstructiconError):
    """A stream parsed incompletely; the result was demoted, never dropped."""


class BudgetExhausted(ConstructiconError):
    """A loop or budget policy ran out; carries the attempt history."""


class Cancelled(ConstructiconError):
    """Cooperative cancellation; children are kill-tree'd."""


class JournalDamaged(ConstructiconError):
    """The journal itself could not be fully read — distinct from stream damage."""
