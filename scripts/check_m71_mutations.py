"""Run the M7.1 law mutations in isolated interpreters; never edit the checkout.

Each replacement is confined to one function's code object. Imported aliases
therefore see it too. A pytest assertion failure kills a mutant; collection or
setup errors are not credited as proof. Run with ``uv run python scripts/check_m71_mutations.py``.
"""

from __future__ import annotations

import importlib
import inspect
import subprocess
import sys
import textwrap

MUTANTS = (
    (
        "endpoint validation is mandatory",
        "constructicon.runtime.validator:_compile_graph",
        "if not _validate_connection_endpoints(comp, graph, scope=scope, location=location):",
        "if False:",
        "tests/runtime/test_connection_endpoints.py::test_unknown_endpoints_have_one_exact_fault_per_connection",
    ),
    (
        "endpoint-invalid graph stops before compilation",
        "constructicon.runtime.validator:_compile_graph",
        "raise AdmissionError(comp.faults)",
        "pass",
        "tests/runtime/test_connection_endpoints.py::test_bad_endpoints_stop_before_reachability_and_node_compilation",
    ),
    (
        "failed boundary is not an empty output set",
        "constructicon.runtime.validator:_compile_graph",
        "raise AdmissionError(comp.faults)",
        "return {}",
        "tests/runtime/test_connection_endpoints.py::test_endpoint_failure_unwinds_parent_compilation",
    ),
    (
        "retained inner Loop keeps its body coordinate at admission",
        "constructicon.runtime.validator:_compile_loop",
        'location=location.child("body"),\n        )\n    member_order',
        "location=location,\n        )\n    member_order",
        "tests/runtime/test_connection_endpoints.py::test_unknown_endpoints_have_one_exact_fault_per_connection[False-missing_roles2-retained-with-loop]",
    ),
    (
        "retained inner Loop keeps its body coordinate in counterfactual refusal",
        "constructicon.runtime.validator:_compile_loop",
        'location=location.child("body"),\n        )\n    member_order',
        "location=location,\n        )\n    member_order",
        "tests/api/test_endpoint_admission.py::test_historical_endpoint_fault_is_baseline_invalid_and_reproduce_stays_exact[False-retained-with-loop]",
    ),
    (
        "source endpoint is accounted for",
        "constructicon.runtime.validator:_validate_connection_endpoints",
        "if name not in declared",
        'if role == "dst" and name not in declared',
        "tests/runtime/test_connection_endpoints.py::test_unknown_endpoints_have_one_exact_fault_per_connection",
    ),
    (
        "destination endpoint is accounted for",
        "constructicon.runtime.validator:_validate_connection_endpoints",
        "if name not in declared",
        'if role == "src" and name not in declared',
        "tests/runtime/test_connection_endpoints.py::test_unknown_endpoints_have_one_exact_fault_per_connection",
    ),
    (
        "missing endpoint roles retain their order",
        "constructicon.runtime.validator:_validate_connection_endpoints",
        '(("src", connection.src), ("dst", connection.dst))',
        '(("dst", connection.dst), ("src", connection.src))',
        "tests/runtime/test_connection_endpoints.py::test_unknown_endpoints_have_one_exact_fault_per_connection",
    ),
    (
        "endpoint coordinate names the connection",
        "constructicon.runtime.validator:_validate_connection_endpoints",
        'location.child("connections", index)',
        "location",
        "tests/runtime/test_connection_endpoints.py::test_unknown_endpoints_have_one_exact_fault_per_connection",
    ),
    (
        "historical endpoints are baseline failures",
        "constructicon.api._control_commands:_CommandExecutor._admit_counterfactual",
        "manifest = self._system.validate(source.source_graph, inputs, resolution_lock=lock)",
        "manifest = source",
        "tests/api/test_endpoint_admission.py::test_historical_endpoint_fault_is_baseline_invalid_and_reproduce_stays_exact",
    ),
    (
        "empty node remains a representable selector",
        "constructicon.runtime.validator:_resolve_selector",
        "if not port_name:",
        "if not node_name or not port_name:",
        "tests/runtime/test_membership_compatibility.py::test_empty_node_selector_preserves_the_base_manifest",
    ),
    (
        "duplicate destination coordinate frame",
        "constructicon.runtime.validator:_located_fault",
        "details = {",
        'if defect == "duplicate_map_destination":\n'
        '        comp.faults.append(f"{scope.render()}: {message}")\n'
        "        return\n"
        "    details = {",
        "tests/runtime/test_explicit_membership.py::test_distinct_scalar_maps_still_refuse_a_non_many_destination",
    ),
    (
        "first conflicting distinct selector",
        "constructicon.runtime.validator:_bind_node_inputs",
        'comp, conflict, scope, "duplicate_map_destination",',
        'comp, first, scope, "duplicate_map_destination",',
        "tests/runtime/test_explicit_membership.py::test_map_coordinates_follow_the_bytes_that_own_them",
    ),
    (
        "selector grammar refusal",
        "constructicon.runtime.validator:_resolve_selector",
        "if not port_name:",
        "if False:",
        "tests/runtime/test_explicit_membership.py::test_malformed_selector_gets_a_grammar_repair",
    ),
    (
        "unused destination",
        "constructicon.runtime.validator:_bind_node_inputs",
        "if entry.destination_port not in declared:",
        "if False:",
        "tests/runtime/test_explicit_membership.py::test_an_unused_map_destination_is_never_discarded",
    ),
    (
        "scalar source",
        "constructicon.runtime.validator:_resolve_selector",
        'if source.port.cardinality != "one":',
        "if False:",
        "tests/runtime/test_explicit_membership.py::test_a_selector_is_not_a_collection_or_an_optional_seat",
    ),
    (
        "connection order",
        "constructicon.runtime.validator:_explicit_maps",
        "enumerate(graph.connections)",
        "enumerate(sorted(graph.connections, key=lambda item: item.src))",
        "tests/runtime/test_explicit_membership.py::test_ordered_scalar_union_replaces_the_pool",
    ),
    (
        "map object order",
        "constructicon.runtime.validator:_explicit_maps",
        "sorted(connection.map.items())",
        "connection.map.items()",
        "tests/runtime/test_explicit_membership.py::test_map_object_order_is_not_fault_order",
    ),
    (
        "panel maps",
        "constructicon.sdk.combinators:panel",
        'map={gathers.name: f"{member_id}.{result.name}"}',
        "map={}",
        "tests/sdk/test_combinators.py::test_a_second_compatible_producer_is_gathered_by_many_and_ambiguous_for_one",
    ),
    (
        "plural panel",
        "constructicon.sdk.combinators:panel",
        "if len(members) < 2:",
        "if len(members) < 1:",
        "tests/sdk/test_combinators.py::test_panel_refuses_what_would_be_gathered_wrongly_or_not_at_all",
    ),
    (
        "selector node delimiter",
        "constructicon.sdk.combinators:panel",
        'if any("." in member_id for member_id in member_ids):',
        "if False:",
        "tests/sdk/test_panel_membership.py::test_panel_selectors_are_representable_before_constructing_a_graph",
    ),
    (
        "selector output name",
        "constructicon.sdk.combinators:panel",
        "if not result.name:",
        "if False:",
        "tests/sdk/test_panel_membership.py::test_panel_selectors_are_representable_before_constructing_a_graph",
    ),
    (
        "distinct request",
        "constructicon.sdk.combinators:panel",
        "if _same_contract(request, result):",
        "if False:",
        "tests/sdk/test_combinators.py::test_panel_refuses_what_would_be_gathered_wrongly_or_not_at_all",
    ),
    (
        "unique gather role",
        "constructicon.sdk.combinators:panel",
        "if _same_contract(port, result):",
        "if False:",
        "tests/sdk/test_combinators.py::test_panel_refuses_what_would_be_gathered_wrongly_or_not_at_all",
    ),
    (
        "lock-aware preflight",
        "constructicon.runtime.authoring:_preflight_ref",
        "select_version(state.snapshot, ref, scope, state.resolution_lock)",
        "select_version(state.snapshot, ref, scope, None)",
        "tests/api/test_membership_admission.py::test_preflight_inspects_the_exact_pin_not_current_stable",
    ),
    (
        "baseline-first",
        "constructicon.api._control_commands:_CommandExecutor._admit_counterfactual",
        "manifest = self._system.validate(source.source_graph, inputs, resolution_lock=lock)",
        "manifest = source",
        "tests/api/test_membership_admission.py::test_retained_non_scalar_map_is_baseline_invalid_not_an_override_mismatch",
    ),
    (
        "whole override boundary",
        "constructicon.api._control_commands:_CommandExecutor._admit_counterfactual",
        "if before.contract_hash != after.contract_hash:",
        "if False:",
        "tests/api/test_membership_admission.py::test_counterfactual_preserves_the_whole_boundary_at_every_affected_scope",
    ),
    (
        "scalar vocabulary",
        "constructicon.api.introspection:build_system_description",
        '"authoring": authoring.model_dump(mode="json"),',
        '"authoring": authoring.model_dump(mode="json", '
        'exclude={"bindings": {"explicit_map_source_cardinality"}}),',
        "tests/api/test_membership_admission.py::test_description_publishes_both_laws_in_schema_two",
    ),
    (
        "fan-in vocabulary",
        "constructicon.api.introspection:build_system_description",
        '"authoring": authoring.model_dump(mode="json"),',
        '"authoring": authoring.model_dump(mode="json", '
        'exclude={"bindings": {"mapped_many_policy"}}),',
        "tests/api/test_membership_admission.py::test_description_publishes_both_laws_in_schema_two",
    ),
)


def child(index: int) -> int:
    import pytest

    _, target, before, after, test = MUTANTS[index]
    module_name, attribute = target.split(":")
    module = importlib.import_module(module_name)
    function = module
    for part in attribute.split("."):
        function = getattr(function, part)
    source = textwrap.dedent(inspect.getsource(function))
    if before not in source:
        raise RuntimeError(f"mutation no longer matches {target}")
    namespace = dict(function.__globals__)
    exec(
        compile(source.replace(before, after, 1), function.__code__.co_filename, "exec"), namespace
    )
    function.__code__ = namespace[function.__name__].__code__
    return int(pytest.main(["-q", "--tb=short", test]))


def main() -> int:
    if len(sys.argv) == 2:
        return child(int(sys.argv[1]))
    failed = False
    for index, (name, *_) in enumerate(MUTANTS):
        result = subprocess.run(
            [sys.executable, __file__, str(index)],
            capture_output=True,
            text=True,
        )
        killed = (
            result.returncode == 1 and "FAILED " in result.stdout and "ERROR " not in result.stdout
        )
        print(f"{name}: {'KILLED' if killed else 'NOT PROVEN'}", flush=True)
        if not killed:
            print(result.stdout[-3000:], result.stderr[-3000:])
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
