"""Application identity shared by trusted assembly and operational admission."""

from __future__ import annotations

import hashlib
from pathlib import Path

from constructicon.core.identity import Digest, digest


def maintenance_application_revision() -> Digest:
    root = Path(__file__).parent
    return digest("maintenance-application", 1, {
        "sources": {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                    for name in ("plan_manifest_application.py", "maintenance_entry.py",
                                 "_maintenance_source.py", "_maintenance_identity.py")},
    })
