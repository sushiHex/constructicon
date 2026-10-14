"""Read the owner's separate maintenance authority through root file custody."""

from pathlib import Path

from pydantic import ValidationError

from constructicon.core.errors import ContractViolation
from constructicon.core.identity import canonical_json, parse_json_value
from constructicon.core.maintenance import MaintenanceAttemptAuthorization
from constructicon.substrate.executors.qualification import _read_authorization_bytes

_UNAVAILABLE = "the maintenance authorization is unavailable"


def read_maintenance_authorization(path: Path) -> MaintenanceAttemptAuthorization:
    """Bounded root-owned operator configuration, never caller request data."""
    try:
        record = parse_json_value(_read_authorization_bytes(path).decode("utf-8"))
        return MaintenanceAttemptAuthorization.model_validate_json(canonical_json(record))
    except (ContractViolation, OSError, ValidationError, ValueError, RecursionError) as exc:
        raise ContractViolation(_UNAVAILABLE) from exc
