"""Reproduce M7.1 compatibility evidence from its committed validator versions.

Requires local history at 8262d4f and b5ff31f; deliberately not a CI dependency.
Only the historical validator module is loaded: its core contracts and other
runtime dependencies are unchanged by PR B. Temporary journals stay outside the
checkout. Run with ``uv run python scripts/check_m71_fixture_provenance.py``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path
from tempfile import TemporaryDirectory

from constructicon.api.system import Constructicon
from constructicon.core.identity import canonical_json
from constructicon.substrate.journal.sqlite import SqliteJournal


def historical_manifest(commit, system, graph, inputs):
    source = subprocess.run(
        ["git", "show", f"{commit}:src/constructicon/runtime/validator.py"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    module = types.ModuleType(f"constructicon.runtime._fixture_{commit}")
    sys.modules[module.__name__] = module
    exec(compile(source, f"{commit}/validator.py", "exec"), module.__dict__)
    return module.admit(
        graph,
        snapshot=system._registry.snapshot(),
        catalog=system._catalog,
        capabilities=system._capabilities,
        root_grants=system._root_grants,
        inputs=inputs,
    )


def main() -> None:
    # Direct script execution puts scripts/, not the repository, on sys.path.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tests.conftest import TRIAGE_SCRIPT, FakeAnnounceEffect, FakeExecutor, build_system, world
    from tests.runtime.test_connection_endpoints import INPUTS, WRAPPERS, endpoint_graph
    from tests.runtime.test_membership_compatibility import INPUTS as EMPTY_INPUTS
    from tests.runtime.test_membership_compatibility import (
        empty_node_graph,
        test_empty_node_selector_preserves_the_base_manifest,
    )

    fixture = json.loads(
        (
            Path(__file__).resolve().parents[1] / "tests/fixtures/m71/ghost-endpoint-manifests.json"
        ).read_text()
    )
    assert fixture["writer_commit"] == "b5ff31f362ded8d486e8473a9cb23c2cffba661b"
    assert set(fixture["manifests"]) == set(WRAPPERS)
    with TemporaryDirectory(prefix="constructicon-provenance-") as scratch:
        for wrapper in WRAPPERS:
            system = Constructicon(journal=SqliteJournal(Path(scratch) / f"{wrapper}.db"))
            graph = endpoint_graph(system, wrapper=wrapper)
            old = historical_manifest(fixture["writer_commit"], system, graph, INPUTS)
            assert canonical_json(old.model_dump(mode="json")) == canonical_json(
                fixture["manifests"][wrapper]
            )
            print(f"b5ff31f / {wrapper}: exact manifest bytes reproduced", flush=True)

        system = build_system(
            SqliteJournal(Path(scratch) / "empty.db"),
            FakeExecutor(dict(TRIAGE_SCRIPT)),
            FakeAnnounceEffect(),
            owner_id="provenance",
        )
        world.__wrapped__(system)
        graph = empty_node_graph()
        old = historical_manifest(
            "8262d4fd614028ebb0b41b77ef124ff47afcc5dc", system, graph, EMPTY_INPUTS
        )
        current = system.validate(graph, EMPTY_INPUTS)
        assert canonical_json(old.model_dump(mode="json")) == canonical_json(
            current.model_dump(mode="json")
        )
        test_empty_node_selector_preserves_the_base_manifest(system)
        print("8262d4f / empty node: exact manifest bytes and golden reproduced")


if __name__ == "__main__":
    main()
