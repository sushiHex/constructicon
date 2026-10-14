"""Application identity shared by trusted assembly and operational admission."""

from __future__ import annotations

import hashlib
from pathlib import Path

from constructicon.core.identity import Digest, digest


def maintenance_application_revision() -> Digest:
    root = Path(__file__).parents[1]
    return digest("maintenance-application", 1, {
        "sources": {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                    for name in ("api/plan_manifest_application.py", "api/maintenance_entry.py",
                                 "api/_maintenance_source.py", "api/_maintenance_identity.py",
                                 "core/maintenance.py", "substrate/executors/maintenance.py",
                                 "substrate/executors/qualification.py",)},
    })
