"""Three truths the registry and admission hold about a definition.

A definition is the same definition as another when its canonical bytes are;
an embedded schema is bound to its digest on a composite's boundary as on an
atomic's; and a fault's scope survives the spaces and colons a graph name or
node id may legally carry.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.address import ScopePath
from constructicon.core.admission import AdmissionRejected
from constructicon.core.component import ComponentDef, same_definition
from constructicon.core.errors import AdmissionError
from constructicon.core.graph import Graph, GraphNode, Ref
from constructicon.core.identity import digest
from constructicon.core.ports import Port
from constructicon.core.registry import StoredVersion
from constructicon.runtime.authoring import _scope_from_message
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import ISSUE, atomic


def _port(name: str, schema: dict[str, object]) -> Port:
    return Port(
        name=name,
        type_id="truths/T",
        schema_hash=str(digest("json-schema", 1, schema)),
        json_schema=schema,
    )


def _composite(name: str, *, declared: Port, exported: Port) -> ComponentDef:
    body = Graph(
        name=name,
        nodes=(GraphNode(id="inner", body=Ref(component="test/triage")),),
        inputs=(ISSUE,),
        outputs=(exported,),
    )
    return ComponentDef(
        name=name, role="component", body=body, inputs=(ISSUE,), outputs=(declared,)
    )


def test_two_definitions_are_one_definition_by_bytes_not_by_model_equality() -> None:
    """`1 == True` is a Python fact; a registry that deduplicated with `==` would merge them."""

    one = _port("out", {"const": 1})
    true = one.model_copy(update={"json_schema": {"const": True}})
    left = _composite("truths/pair", declared=one, exported=one)
    right = _composite("truths/pair", declared=true, exported=true)
    assert left == right
    assert not same_definition(left, right)
    assert same_definition(left, left.model_copy())


def test_a_composites_embedded_schema_is_bound_to_its_digest(
    system: Constructicon, journal: SqliteJournal
) -> None:
    """Registration refuses a composite boundary port whose schema is not its revision's;
    a store retained from before that rule is re-proved at admission."""

    definition, implementation = atomic(
        "test/triage", (ISSUE,), (_port("out", {"const": 1}),), _impl
    )
    version = system._register(definition, implementation)
    system._promote_initial(component=definition.name, version=version)

    honest = _port("out", {"const": 1})
    dishonest = honest.model_copy(
        update={"json_schema": {"const": 2}}
    )  # revision names another shape
    with pytest.raises(AdmissionError, match="for its embedded JSON Schema"):
        system._register(_composite("truths/lying-schema", declared=dishonest, exported=dishonest))

    retained = _composite("truths/retained-lie", declared=dishonest, exported=dishonest)
    journal.store_version(
        StoredVersion(
            definition=retained,
            content_hash=retained.content_hash(),
            registered_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    system._promote_initial(component=retained.name, version=retained.content_hash())
    seats = Graph(
        name="truths/seats-retained-lie",
        nodes=(GraphNode(id="member", body=Ref(component=retained.name)),),
        inputs=(ISSUE,),
        outputs=(dishonest,),
    )
    with pytest.raises(AdmissionError, match="for its embedded JSON Schema"):
        system.validate(seats, {"issue": {"title": "x"}})
    rejected = system.admit_graph(seats.model_dump(mode="json"), {"issue": {"title": "x"}})
    assert isinstance(rejected, AdmissionRejected)
    fault = next(item for item in rejected.faults if "retained composite" in item.message)
    assert fault.details == {"component": retained.name, "version": str(retained.content_hash())}
    # The fault says which truth failed: the schema's digest, not the boundary.
    assert "for its embedded JSON Schema" in fault.message
    assert "does not export" not in fault.message
    assert "embedded schemas are their declared revisions'" in fault.repair


async def _impl(ctx: object, inputs: dict[str, object]) -> dict[str, object]:
    return {"out": 1}


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        # The port form ends at the message's own separator: spaces and colons survive.
        ("a b/c:d input port 'x' has no upstream output", ("a b", "c:d")),
        ("a b/c:d output port 'y' ambiguity is an error", ("a b", "c:d")),
        # The colon form cannot tell a scope from prose, so it keeps the legacy
        # rule: a prefix with a space is not a scope, and prose gains none.
        ("root/node: unknown component 'q'", ("root", "node")),
        ("x y/z:w: unknown component 'q'", None),
        ("a b: c/node: unknown component 'q'", None),
        ("run inputs are missing declared inputs: ['x']", None),
        ("no separator at all", None),
    ],
)
def test_a_faults_scope_is_exact_or_absent(message: str, expected: tuple[str, ...] | None) -> None:
    scope = _scope_from_message(message)
    assert scope == (ScopePath(segments=expected) if expected else None)
