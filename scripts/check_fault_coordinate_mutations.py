"""Assertion mutants for exact admission-fault coordinates and repairs (#69)."""

from __future__ import annotations

from _mutations import run

MUTANTS = (
    (
        "structured scope segments",
        "constructicon.runtime.validator:_located_fault",
        '"scope": list(scope.segments),',
        '"scope": [scope.render()],',
        "tests/runtime/test_fault_coordinates.py::test_missing_node_source_keeps_its_exact_destination",
    ),
    (
        "feedback seed classification",
        "constructicon.runtime.validator:_bind_node_inputs",
        '"missing_feedback_seed",',
        '"missing_port_source",',
        "tests/runtime/test_fault_coordinates.py::test_feedback_seed_keeps_its_exact_loop_destination",
    ),
    (
        "map repair coordinate",
        "constructicon.runtime.validator:_map_fault",
        'entry.location.child("connections", entry.connection_index, '
        '"map", entry.destination_port)',
        "entry.location",
        "tests/runtime/test_fault_coordinates.py::test_ambiguous_node_input_keeps_the_exact_map_repair",
    ),
    (
        "level-local composite selector",
        "constructicon.runtime.validator:_applicable_selectors",
        'candidates.append(f"{node_name}.{output_name}")',
        'candidates.append(_describe(source).rsplit("/", 1)[-1])',
        "tests/runtime/test_fault_coordinates.py::test_ambiguity_advertises_only_applicable_level_local_selectors",
    ),
    (
        "only scalar selectors are advertised",
        "constructicon.runtime.validator:_applicable_selectors",
        'any(source is candidate for candidate in sources)\n'
        '                and source.port.cardinality == "one"\n'
        '                and _source_matches(source, port)\n'
        '            ):\n'
        '                candidates.append(f"{node_name}.{output_name}")',
        'any(source is candidate for candidate in sources)\n'
        '                and True\n'
        '                and _source_matches(source, port)\n'
        '            ):\n'
        '                candidates.append(f"{node_name}.{output_name}")',
        "tests/runtime/test_fault_coordinates.py::test_ambiguity_advertises_only_applicable_level_local_selectors",
    ),
    (
        "candidate publication bound",
        "constructicon.runtime.authoring:_classify_fault",
        "published = candidates[: limits.max_fault_detail_items]",
        "published = candidates",
        "tests/runtime/test_fault_coordinates.py::test_ambiguity_advertises_only_applicable_level_local_selectors",
    ),
)


if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
