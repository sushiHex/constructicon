"""One side-effect-free version choice for preflight and compilation."""

from collections.abc import Mapping

from constructicon.core.address import ScopePath
from constructicon.core.control import ResolutionPin
from constructicon.core.graph import Ref
from constructicon.core.registry import RegistrySnapshot, StoredVersion


def select_version(
    snapshot: RegistrySnapshot,
    ref: Ref,
    scope: ScopePath,
    lock: Mapping[tuple[str, ...], ResolutionPin] | None,
) -> StoredVersion | None:
    """A lock is exact authority, never a hint to fall back to current stable.

    Compilation owns pin accounting and all resolution faults. Preflight only
    inspects the definition that compilation would select at this exact scope.
    """

    if lock is not None:
        pin = lock.get(scope.segments)
        if pin is None or pin.component != ref.component:
            return None
        return snapshot.get(pin.component, pin.version)
    if ref.version is not None:
        return snapshot.versions.get(ref.component, {}).get(ref.version)
    stable = snapshot.stable_version(ref.component)
    return snapshot.get(ref.component, stable) if stable is not None else None
