"""Controls for the M7.1 shadow measurement.

Not collected by the suite from here. These controls belong only to the
three-row liveness artifact: copy this file to
``tests/sdk/test_m71_controls.py``, apply ``shadow_liveness.py``, run the suite,
then revert both. The 16-row provenance artifact is corpus-only; apply
``shadow_gather_provenance.py`` to a clean checkout without copying this file.

Three graphs:

* ``sdk/control-panel``  — positive control for gather liveness. A member whose
  stable version carries a drifted output contract. Admission succeeds and the
  gather holds one member where two were connected: the defect itself.
* ``sdk/control-intact`` — negative control. The same panel undrifted. A
  detector that fires here is broken, and "no corpus findings" would mean
  nothing.
* ``sdk/control-ghost``  — positive control for endpoint validation. Two
  connections naming nodes that do not exist.
"""

from __future__ import annotations

from constructicon.api.system import Constructicon
from constructicon.core.graph import Connection
from constructicon.core.identity import digest
from constructicon.core.ports import Port
from constructicon.sdk import panel

from tests.sdk.test_combinators import (  # noqa: F401
    _promote_all,
    panel_no,
    panel_tally,
    panel_yes,
)


def test_drifted_member_is_silently_absent_today(system: Constructicon) -> None:
    """Positive control, gather: the defect, reproduced."""

    _promote_all(system, panel_no, panel_tally)

    outputs = (
        Port(
            name="vote",
            type_id="sdk/Verdict",
            schema_hash=panel_yes.definition.outputs[0].schema_hash,
        ),
    )
    # The registry binds PythonRef.contract_hash to the declared ports, so a
    # drifted boundary has to carry its own recomputed contract hash — which is
    # exactly what an honest re-registration from new source would do.
    body = panel_yes.definition.body.model_copy(
        update={
            "contract_hash": digest(
                "component-contract",
                1,
                {
                    "inputs": [
                        port.model_dump(mode="json") for port in panel_yes.definition.inputs
                    ],
                    "outputs": [port.model_dump(mode="json") for port in outputs],
                },
            )
        }
    )
    drifted = panel_yes.definition.model_copy(update={"outputs": outputs, "body": body})
    version = system._register(drifted, panel_yes.implementation)
    system._promote_initial(component="sdk/panel-yes", version=version)

    authored = panel("sdk/control-panel", panel_yes, panel_no, aggregator=panel_tally)
    inputs = {"request": {"question": "ship?"}, "quorum": {"required": 1}}

    manifest = system.validate(authored.definition.body, inputs)
    assert _gathered(manifest) == ["panel_no"]


def test_the_intact_panel_gathers_both_members(system: Constructicon) -> None:
    """Negative control: a detector that fires here is broken."""

    _promote_all(system, panel_yes, panel_no, panel_tally)
    authored = panel("sdk/control-intact", panel_yes, panel_no, aggregator=panel_tally)
    inputs = {"request": {"question": "ship?"}, "quorum": {"required": 1}}
    manifest = system.validate(authored.definition.body, inputs)
    assert _gathered(manifest) == ["panel_no", "panel_yes"]


def test_a_connection_naming_no_node_is_discarded_in_silence(
    system: Constructicon,
) -> None:
    """Positive control, endpoint: a typo is not a fault, it is nothing."""

    _promote_all(system, panel_yes, panel_no, panel_tally)
    authored = panel("sdk/control-ghost", panel_yes, panel_no, aggregator=panel_tally)
    graph = authored.definition.body
    haunted = graph.model_copy(
        update={
            "connections": (
                *graph.connections,
                Connection(src="ghost", dst="panel_tally"),
                Connection(src="panel_yes", dst="phantom"),
            )
        }
    )
    inputs = {"request": {"question": "ship?"}, "quorum": {"required": 1}}

    manifest = system.validate(haunted, inputs)
    clean = system.validate(graph, inputs)
    # Inert in the bindings it resolves...
    assert manifest.resolved_connections == clean.resolved_connections
    # ...and not inert in identity, which every effect key derives from.
    assert manifest.manifest_hash != clean.manifest_hash


def _gathered(manifest: object) -> list[str]:
    return sorted(
        getattr(source, "node", "$input")
        for binding in manifest.resolved_connections  # type: ignore[attr-defined]
        if binding.destination.kind == "node_port"
        and binding.destination.node == "panel_tally"
        and binding.destination.port == "votes"
        for source in binding.sources
    )
