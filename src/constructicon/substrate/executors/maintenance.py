"""Read the owner's separate maintenance authority through root file custody."""

from pathlib import Path

from pydantic import ValidationError

from constructicon.core.errors import ContractViolation
from constructicon.core.identity import canonical_json, parse_json_value
from constructicon.core.maintenance import (
    ChannelReplyAttemptAuthorization,
    MaintenanceAttemptAuthorization,
    MaintenanceAuthorization,
)
from constructicon.substrate.executors.qualification import _read_authorization_bytes

_UNAVAILABLE = "the maintenance authorization is unavailable"


def read_maintenance_authorization(path: Path) -> MaintenanceAuthorization:
    """Bounded root-owned operator configuration, never caller request data.

    The purpose literal selects one of exactly two closed types. Any other value,
    including none, is read as the plan-manifest type, whose literal refuses it.
    """
    try:
        record = parse_json_value(_read_authorization_bytes(path).decode("utf-8"))
        if isinstance(record, dict) and record.get("purpose") == "channel-stored-reply":
            return ChannelReplyAttemptAuthorization.model_validate_json(canonical_json(record))
        return MaintenanceAttemptAuthorization.model_validate_json(canonical_json(record))
    except (ContractViolation, OSError, ValidationError, ValueError, RecursionError) as exc:
        raise ContractViolation(_UNAVAILABLE) from exc
