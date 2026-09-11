"""Assertion mutants for scoped I/O and native duplex completion; no file edits."""

from _mutations import run

IO = "constructicon.substrate.executors.linux:_ProcessIO."
PUMP = "constructicon.substrate.executors.linux:LinuxLauncher._run"
UNIT = "tests/substrate/test_process_io.py::"
NATIVE = "tests/substrate/test_linux_duplex.py::"

MUTANTS = (
    (
        "input budget resets per write", IO + "write",
        "self.input_limit - self.spent", "self.input_limit",
        UNIT + "test_input_is_cumulative_and_refusal_delivers_no_prefix",
    ),
    (
        "input charge is discarded", IO + "write",
        "self.spent += len(data)", "self.spent = 0",
        UNIT + "test_input_is_cumulative_and_refusal_delivers_no_prefix",
    ),
    (
        "read waits to fill maximum", IO + "read",
        "self.offset == len(self._output)", "len(self._output) - self.offset < maximum",
        UNIT + "test_available_short_read_progresses_without_filling_or_inventing_eof",
    ),
    (
        "EOF does not wake the reader", IO + "read",
        " and not self.eof", "",
        UNIT + "test_available_short_read_progresses_without_filling_or_inventing_eof",
    ),
    (
        "read ignores its byte bound", IO + "read",
        "self.offset + maximum", "self.offset + 8192",
        UNIT + "test_fragment_reads_keep_one_capture_cursor",
    ),
    (
        "capture cursor does not advance", IO + "read",
        "self.offset = end", "self.offset = self.offset",
        UNIT + "test_fragment_reads_keep_one_capture_cursor",
    ),
    (
        "closed scope stays readable", IO + "require_active",
        "if not self.active:", "if False:",
        UNIT + "test_stdin_half_close_is_idempotent_but_scope_close_refuses_every_operation",
    ),
    (
        "owned pipe failure becomes independent", IO + "write",
        "if self.stopping:", "if False:",
        UNIT + "test_io_failure_is_subordinate_only_to_its_owned_shutdown[True]",
    ),
    (
        "ordinary pipe failure is treated as shutdown", IO + "write",
        "if self.stopping:", "if True:",
        UNIT + "test_io_failure_is_subordinate_only_to_its_owned_shutdown[False]",
    ),
    (
        "repeated stops interrupt callback cleanup", PUMP,
        "if initiating and protocol is not None", "if protocol is not None",
        NATIVE + "test_repeated_bound_notifications_do_not_cancel_callback_cleanup",
    ),
    (
        "private report failure hides the callback failure", PUMP,
        "raw_report = os.read(report_read, 5)",
        "\n                try: raw_report = os.read(report_read, 5)"
        "\n                except BaseException: errors.clear(); raise",
        NATIVE + "test_cleanup_failure_keeps_the_original_callback_error[report]",
    ),
    (
        "stdout ceiling never stops conversation", PUMP,
        'bound = bound or "stdout"', 'bound = bound',
        NATIVE + "test_output_bound_returns_salvage_with_a_stalled_reader[stdout]",
    ),
    (
        "record ceiling never stops conversation", PUMP,
        'bound = bound or "record"', 'bound = bound',
        NATIVE + "test_output_bound_returns_salvage_with_a_stalled_reader[record]",
    ),
)

if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
