"""Load-bearing placement instrument checks; never edits source files."""

from _mutations import run

PEER = "tests.native_provider:"
TRANSPORT = "tests.substrate._provider_transport:"
UNIT = "tests/test_native_provider.py::"
RECIPE = "tests/test_provider_placement.py::"

MUTANTS = (
    ("third connection admitted", TRANSPORT + "Budget.admit",
     "self.connections > CONNECTIONS", "False",
     UNIT + "test_third_connection_is_refused_before_reading_headers[tcp]"),
    ("peer permits concurrent incomplete requests", PEER + "Peer.serve",
     'raise ValueError("concurrent connection")', "pass",
     UNIT + "test_concurrent_incomplete_connection_closes_the_listener[tcp]"),
    ("host aggregate bound omitted", TRANSPORT + "Budget.charge",
     "self.total > TOTAL", "False",
     UNIT + "test_header_and_aggregate_bounds_are_endpoint_owned[tcp]"),
    ("peer cleanup interruptible", PEER + "provider_peer.__wrapped__",
     "await finish_owned(asyncio.create_task(join()))", "await join()",
     UNIT + "test_repeated_cancellation_joins_every_accepted_handler[tcp]"),
    ("trailing requests discarded", PEER + "Peer.respond",
     "if await read(sock, self.budget):", "if False:",
     UNIT + "test_pipelined_bytes_after_a_large_body_are_not_dropped[tcp]"),
    ("workspace silently accepted", "tests.provider_placement:PlacementLauncher.argv",
     "if workspace is not None:", "if False:",
     RECIPE + "test_fixture_refuses_a_workspace_or_changed_endpoint"),
    ("endpoint identity ignored", "tests.provider_placement:PlacementLauncher.argv",
     "or (endpoint.st_dev, endpoint.st_ino) != self.endpoint_identity", "or False",
     RECIPE + "test_fixture_refuses_a_workspace_or_changed_endpoint"),
    ("bridge double-charges bytes", TRANSPORT + "read",
     "budget.charge(len(raw))", "budget.charge(2 * len(raw))",
     RECIPE + "test_bridge_half_close_drains_and_preserves_reverse_direction"),
    ("model match replaces scenario validation", PEER + "Peer.respond",
     "self.check_scenario(request)", "pass",
     UNIT + "test_model_match_does_not_substitute_for_the_controlled_scenario[tcp-wrong]"),
    ("unexpected mount admitted", "tests.substrate._provider_bootstrap:topology",
     'raise ValueError("unexpected mount inventory: " + json.dumps(mounts))', "pass",
     RECIPE + "test_actual_namespace_preflight_checks_named_mounts_flags_and_fds[extra]"),
    ("writable root admitted", "tests.substrate._provider_bootstrap:topology",
     'raise ValueError("runtime root is not read-only")', "pass",
     RECIPE + "test_actual_namespace_preflight_checks_named_mounts_flags_and_fds[root-rw]"),
    ("endpoint identity omitted from evidence", "tests.substrate._provider_bootstrap:topology",
     '"identity": expected', '"identity": None',
     RECIPE + "test_actual_namespace_preflight_checks_named_mounts_flags_and_fds[none]"),
    ("failed native outcome discarded", "tests.substrate.test_provider_placement:observe",
     "result = exc.result", "result = None",
     RECIPE + "test_failed_conversation_keeps_its_owned_result"),
)


if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
