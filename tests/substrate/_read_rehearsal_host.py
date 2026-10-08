"""Stage 2's session directory, synthesized as the service for the Stage 3 rehearsal.

Run as m8-service on the provisioned foundation lane:
``python -m tests.substrate._read_rehearsal_host W``. It writes what Stage 2
leaves in ``W`` (M8-N5-host-session.md): the production configuration, a
startup policy of routable literals, a passing S6a record naming this host's
launch facts, and g4's sealed identity, which is the CI fixture's with both
revisions replaced by that record's digest ``Q``. The store never reads ``Q``
(ADR 0021:160-163), so this generation is synthetic and says so; no real g4
exists in CI. It prints ``Q`` and the fixture's binding digest.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from constructicon.core.native_operator import NativeOperatorStoreIdentityV1
from constructicon.substrate.executors import codex_lane
from constructicon.substrate.executors.codex_host import LAUNCH_ROOT
from tests.substrate.test_codex_host import evidence, sealed_by

# Real, routable addresses: with no login the client opens no connection (L2),
# and a nonzero relay count in the record would be a real one, reported loudly.
POLICY = {
    "destinations": [["auth.openai.com", 443, "8.8.8.8"], ["chatgpt.com", 443, "8.8.4.4"]],
    "connections": 8,
}


def write(path: Path, content: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(content)


def main(session: Path) -> None:
    session.mkdir(mode=0o700)
    configuration = codex_lane.production_configuration()
    write(session / "config.toml", configuration)
    write(session / "startup-policy.json", json.dumps(POLICY))
    launcher = codex_lane._launcher(LAUNCH_ROOT)
    record = evidence(codex_lane.launch_facts(
        launcher, codex_lane._policy(session / "startup-policy.json"),
        codex_lane.vendor_executable(launcher), configuration,
    ))
    write(session / "s6a-qualification.json", json.dumps(record))
    fixture = NativeOperatorStoreIdentityV1.model_validate_json(
        (LAUNCH_ROOT / "operator-store-fixture.json").read_text(encoding="utf-8"),
    )
    sealed = sealed_by(record, fixture)
    write(session / "g4.sealed.json", sealed.model_dump_json())
    print(json.dumps({
        "qualification": str(sealed.subscription_mode_adapter_revision),
        "operator_binding_digest": str(sealed.operator_binding_digest),
    }))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
