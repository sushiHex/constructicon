"""Trusted disposable-runner provisioning: curate, freeze, and identify userspace.

Never imported by Constructicon. Copies only installed Python and its dynamic
link closure, not the host /usr, home, project, package cache, or credentials.
The resulting content digest is the exact pin supplied to this job's assembly.
The closure rule is the private host's (``m8_host_artifacts.runtime_plan``), so
every lane runs on the runtime the host installer builds.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


def main() -> None:
    # CI only; the private host takes reviewed artifacts via scripts/ci/m8_host_artifacts.py (#94).
    if os.getuid() != 0 or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise SystemExit("provisioning requires the explicitly authorized disposable runner")
    destination = Path(sys.argv[1])
    if not destination.is_absolute() or destination.exists() or destination.is_symlink():
        raise SystemExit("runtime destination must be a fresh absolute path")
    from m8_host_artifacts import contents, materialize, runtime_plan

    from constructicon.substrate.executors import _egress_bridge, _supervisor
    from constructicon.substrate.executors.linux import runtime_digest, runtime_inventory

    # The supervisor and the native zone's proxy bridge are content in this
    # immutable closure, not checkout paths.
    plan = runtime_plan(
        Path("/"),
        Path(_supervisor.__file__).read_bytes(),
        Path(_egress_bridge.__file__).read_bytes(),
        _supervisor.NAMESPACE_SCRIPT,
        _egress_bridge.BRIDGE_SCRIPT,
    )
    materialize(plan, destination, contents())
    policy = Path("/etc/apparmor.d/constructicon-m8-launch")
    abi = Path("/etc/apparmor.d/abi/4.0")
    print(json.dumps({
        "runtime_digest": str(runtime_digest(destination)),
        "entries": runtime_inventory(destination),
        "bubblewrap_sha256": hashlib.sha256(
            (destination.parent / "bwrap").read_bytes(),
        ).hexdigest(),
        "apparmor_policy_sha256": hashlib.sha256(policy.read_bytes()).hexdigest(),
        "apparmor_abi_sha256": hashlib.sha256(abi.read_bytes()).hexdigest(),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
