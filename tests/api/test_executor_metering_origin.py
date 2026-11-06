"""A counterfactual run can contain actual executor observations."""

from __future__ import annotations

import json

from constructicon.api.control import ControlPlane
from constructicon.api.qualification import (
    FIXED,
    REQUEST,
    qualification_definition,
    qualification_graph,
)
from constructicon.api.system import Constructicon
from constructicon.core.control import RunResultPreviewV3, RunSubmission
from tests.api.test_counterfactual import ACTOR, _source_run
from tests.conftest import await_attempt_terminal
from tests.substrate import test_codex_adapter as adapter
from tests.substrate.test_codex_adapter import (
    CAPABILITY,
    GRANTS,
    bare_launcher,
    clean_native,
    descriptor_of,
    provider_for,
)
from tests.substrate.test_codex_protocol import completed, usage_update

portable_binding = adapter.portable_binding
substituted_guard = adapter.substituted_guard


async def test_counterfactual_actual_calls_and_simulated_effects_have_distinct_metering(
    journal, world, announce_effect, tmp_path, portable_binding, substituted_guard,
):
    def peer(tokens):
        return clean_native(records=[usage_update(input_tokens=tokens, output_tokens=1),
                                     completed(answer="ready")])

    launch = bare_launcher(peer(5))
    provider = provider_for(
        launch, unavailable_reasons=(), binding=portable_binding[1:], root=tmp_path,
    )
    native = Constructicon(
        journal=journal, capabilities={CAPABILITY: provider},
        catalog={CAPABILITY: descriptor_of(provider)}, root_grants=GRANTS,
    )
    stage = "qualification-read"
    native._register(qualification_definition(stage), FIXED[stage].body)
    control = ControlPlane(system=native, store=journal)
    fake_control = ControlPlane(system=world, store=journal)
    try:
        source = await control.runs_start(
            ACTOR, proposal=qualification_graph(CAPABILITY, stage),
            inputs={REQUEST.name: {"authorization": "metering-origin-fixture"}},
            idempotency_key="native-metering-source",
        )
        assert isinstance(source, RunSubmission), source
        assert (await await_attempt_terminal(
            journal, source.run_id, baseline_event_seq=0,
        )).kind == "RunSucceeded"
        original = control.runs_result(ACTOR, source.run_id)
        assert isinstance(original, RunResultPreviewV3)
        assert original.metering.groups[0].known_input_tokens == 5

        provider.launcher = bare_launcher(peer(11))
        child = await control.runs_counterfactual(
            ACTOR, source_run_id=source.run_id, overrides={},
            idempotency_key="native-metering-counterfactual",
        )
        assert isinstance(child, RunSubmission), child
        assert (await await_attempt_terminal(
            journal, child.run_id, baseline_event_seq=0,
        )).kind == "RunSucceeded"
        origin = journal.run_origin(child.run_id)
        assert origin is not None and origin.effects == "simulated"
        assert journal.capability_leases(child.run_id)[0].disposition == "discarded"
        actual = control.runs_result(ACTOR, child.run_id)
        assert isinstance(actual, RunResultPreviewV3)
        assert actual.metering.attempt_count == 1
        assert actual.metering.groups[0].known_input_tokens == 11
        detail = control.details_read(ACTOR, actual.metering.detail, max_bytes=64_000)
        (attempt,) = json.loads(detail.text)["attempts"]
        assert attempt["intent"]["origin"] == "actual"
        assert attempt["intent"]["run_id"] == child.run_id
        assert control.runs_result(ACTOR, source.run_id) == original

        fake_source = await _source_run(fake_control, journal, key="fake-metering-source")
        fake_child = await fake_control.runs_counterfactual(
            ACTOR, source_run_id=fake_source.run_id, overrides={},
            idempotency_key="fake-metering-counterfactual",
        )
        assert isinstance(fake_child, RunSubmission), fake_child
        assert (await await_attempt_terminal(
            journal, fake_child.run_id, baseline_event_seq=0,
        )).kind == "RunSucceeded"
        assert len(announce_effect.simulations) == 1
        simulated = fake_control.runs_result(ACTOR, fake_child.run_id)
        assert isinstance(simulated, RunResultPreviewV3)
        assert simulated.metering.coverage == "unmeasured"
        assert simulated.metering.attempt_count == 0
        assert simulated.metering.groups == ()
    finally:
        await control.shutdown()
        await fake_control.shutdown()
