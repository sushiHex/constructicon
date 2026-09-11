"""Startup instrument mutants; no source edits or native-authentication claim."""

from _mutations import run

FRAME = "tests.native_startup:DuplexWire._readline"
WIRE = "tests.native_codex_probe:Wire."
UNIT = "tests/test_native_startup.py::"

MUTANTS = (
    ("frame consumption omitted", FRAME, "del self.pending[:end]", "pass",
     UNIT + "test_duplex_framing_preserves_short_reads_and_coalesced_suffix[8192]"),
    ("coalesced suffix discarded", FRAME, "del self.pending[:end]", "self.pending.clear()",
     UNIT + "test_duplex_framing_preserves_short_reads_and_coalesced_suffix[8192]"),
    ("short chunk is treated as a complete frame", FRAME,
     'while b"\\n" not in self.pending:', 'if b"\\n" not in self.pending:',
     UNIT + "test_duplex_framing_preserves_short_reads_and_coalesced_suffix[1]"),
    ("duplicate JSON key accepted through duplex", WIRE + "read",
     'parse_json_value(raw.decode("utf-8"))', 'json.loads(raw.decode("utf-8"))',
     UNIT + "test_duplex_uses_existing_strict_record_law[duplicate]"),
    ("duplex cumulative receive bound removed", WIRE + "read",
     "self.received > TOTAL_BYTES", "False",
     UNIT + "test_duplex_retains_cumulative_receive_and_send_bounds"),
    ("duplex cumulative send bound removed", WIRE + "send",
     "self.sent > TOTAL_BYTES", "False",
     UNIT + "test_duplex_retains_cumulative_receive_and_send_bounds"),
    ("startup accepts an unpinned model", "tests.native_startup:configuration",
     "if model not in MODELS:", "if False:",
     UNIT + "test_startup_configuration_keeps_pins_and_has_no_authentication"),
    ("startup gains a workspace mount", "tests.substrate.test_linux_duplex:exchange",
     "workspace=None", 'workspace=Path("/workspace")',
     UNIT + "test_startup_uses_the_exact_owned_launch_interface"),
    ("session control is not delivered", "tests.substrate.test_native_startup:observe",
     '"arguments": list(arguments)', '"arguments": []',
     "tests/substrate/test_native_startup.py::"
     "test_explicit_session_configuration_is_a_positive_control"),
    ("native network failures are discarded", "tests.substrate.test_native_startup:"
     "test_provider_failure_retries_until_the_owned_deadline",
     'observations["turn_events"].append(message)', "pass",
     "tests/substrate/test_native_startup.py::"
     "test_provider_failure_retries_until_the_owned_deadline"),
)

if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
