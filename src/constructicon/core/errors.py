"""One error taxonomy, deliberately small.

A red gate is NOT an error — it is a CheckResult the loop consumes.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from constructicon.core.refusal import MAX_REFUSAL_CODES, RefusalCode

if TYPE_CHECKING:
    from constructicon.core.admission import AdmissionFault


class ConstructiconError(Exception):
    """Base for every framework error."""


class ContractViolation(ConstructiconError):
    """A payload failed validation at a boundary — a bug; fail fast.

    ``refusal`` is the guard's own closed reasons, most general first. It is
    never a causal claim, and the walker seals it beside the message.
    """

    refusal: tuple[RefusalCode, ...] = ()

    def __init__(self, *args: object, refusal: Sequence[RefusalCode] = ()) -> None:
        codes = tuple(refusal)
        if len(codes) > MAX_REFUSAL_CODES or not all(
            type(code) is RefusalCode for code in codes
        ):
            raise TypeError("refusal is at most twelve RefusalCode members")
        super().__init__(*args)
        self.refusal = codes


class AdmissionError(ConstructiconError):
    """Validation rejected a graph or authority transition.

    M5 makes graph faults typed and machine-repairable. Historical non-graph
    callers may still provide strings; they cross one explicit compatibility
    bridge into ``system.admission.legacy`` rather than maintaining a second
    error representation.
    """

    def __init__(self, faults: Sequence[AdmissionFault | str]) -> None:
        from constructicon.core.admission import AdmissionCode, AdmissionFault

        normalized: list[AdmissionFault] = []
        for fault in faults:
            if isinstance(fault, AdmissionFault):
                normalized.append(fault)
            else:
                normalized.append(
                    AdmissionFault(
                        code=AdmissionCode.LEGACY_ADMISSION,
                        message=fault,
                        repair=(
                            "inspect the message and resubmit through the relevant "
                            "authority or admission API"
                        ),
                    )
                )
        self.faults = tuple(normalized)
        super().__init__("; ".join(fault.message for fault in self.faults))


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
