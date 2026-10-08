"""The Linux twin of the qualification entry (M8 N5 Stage 1).

Run as the unprivileged service in the provisioned foundation lane: the real
launcher, the real credential-free operator store, the real flock guard and a
real closure authority. The authorization is read by the production reader
from a file root wrote; nothing here can write one.

Commands:
- ``mint``: print the pins of each scenario's authorization, one JSON object
  per line, for root to install. Minting is computation, not authority.
- ``die PATH``: run the authorization at PATH, and die as a process does the
  moment its acquisition is materialized, holding the guard and store lock.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from constructicon.api.qualification import EXECUTOR, SCOPE, qualification_graph, qualify
from constructicon.core.manifest import source_graph_hash_for
from constructicon.core.native_operator import NativeOperatorStoreIdentityV1
from constructicon.core.qualification import QualificationAuthorization
from constructicon.substrate.executors.codex import CodexOperatorProvider
from constructicon.substrate.executors.operator_store import BindingStore
from constructicon.substrate.executors.qualification import read_authorization
from constructicon.substrate.git.acquisition import AcquisitionClosure
from constructicon.substrate.git.authority import GitAuthority
from tests.gitworld import seed_authority
from tests.substrate._gate_owner import installed_launcher
from tests.substrate.test_codex_adapter import (
    BINARY,
    CONFIGURATION,
    EXPECTED,
    GRANTS,
    codex_profile,
    identity_for,
)
from tests.substrate.test_operator_store_containment import KEY as STORE_KEY

CAPABILITY = "codex-qualification"
SCENARIOS = ("accepted", "recovered")
DEATH = 9


def state() -> Path:
    return Path(os.environ["M8_QUALIFICATION_STATE"])


def assemble(qualification: QualificationAuthorization | None = None) -> CodexOperatorProvider:
    store_root = Path(os.environ["M8_OPERATOR_STORE_ROOT"])
    sealed = NativeOperatorStoreIdentityV1.model_validate_json(
        (store_root.parent / "operator-store-fixture.json").read_text(),
    )
    authority = state() / "authority"
    if not (authority / "authority.git").exists():
        authority.mkdir(mode=0o700, exist_ok=True)
        seed_authority(authority)
    launcher = installed_launcher()
    return CodexOperatorProvider(
        launcher=launcher, profile=codex_profile(),
        identity=identity_for(launcher, store_identity=sealed),
        expected_account=EXPECTED, binary=BINARY, configuration=CONFIGURATION, catalog=(),
        acquisition_root=state() / "acquisitions",
        binding_store=BindingStore(store_root, STORE_KEY, sealed),
        closure=AcquisitionClosure(
            GitAuthority(authority / "authority.git", authority / "legacy"),
        ),
        qualification=qualification,
    )


def mint() -> None:
    plain = assemble()
    for scenario in SCENARIOS:
        print(scenario, QualificationAuthorization(
            authorization_id=f"ci-twin-{scenario}",
            stage="qualification-no-dispatch",
            actor_id="operator:qualification-twin",
            idempotency_key=scenario,
            scope=SCOPE,
            binding=EXECUTOR,
            source_graph_hash=source_graph_hash_for(qualification_graph(CAPABILITY)),
            capability_id=CAPABILITY,
            revision=plain.identity.revision,
            operator_binding_digest=plain.identity.store.operator_binding_digest,
            journal=str(state() / f"{scenario}.sqlite"),
            max_epoch=1,
            not_after=datetime.now(UTC) + timedelta(hours=1),
        ).model_dump_json())


async def die(path: Path) -> None:
    qualified = assemble(read_authorization(path))
    acquire = qualified.acquire

    async def acquire_then_die(context):
        acquisition = await acquire(context)
        real = acquisition.materialize
        assert real is not None

        async def materialize_then_die():
            await real()
            sys.stdout.write(json.dumps({"materialized": acquisition.resource_ref}) + "\n")
            sys.stdout.flush()
            os._exit(DEATH)

        return replace(acquisition, materialize=materialize_then_die)

    qualified.acquire = acquire_then_die
    await qualify(provider=qualified, grants=GRANTS, timeout_s=60)


if __name__ == "__main__":
    command = sys.argv[1]
    if command == "mint":
        mint()
    elif command == "die":
        asyncio.run(die(Path(sys.argv[2])))
    else:
        raise SystemExit(f"unknown command {command!r}")
