"""The investigation instrument must detect its own missing checks.

These are portable assertion mutants, never proof of native completeness.
"""

from _mutations import run

MODULE = "tests.native_codex_probe:"
TEST = "tests/test_native_codex_probe.py::"

MUTANTS = (
    *((name, MODULE + "Dispatch.answer", check, "False",
       TEST + "test_dispatch_never_accepts_authority_or_identity_from_peer")
      for name, check in (
          ("thread fence", 'params.get("threadId") != self.thread_id'),
          ("turn fence", 'params.get("turnId") != self.turn_id'),
          ("tool allowlist", 'params.get("tool") != TOOL["name"]'),
          ("namespace refusal", 'params.get("namespace") is not None'),
          ("argument closure", 'set(arguments) != {"program"}'),
          ("input bound", 'len(arguments["program"].encode()) > RECORD_BYTES'),
      )),
    ("spend before response", MODULE + "Dispatch.answer", "self.seen.add(call_id)", "pass",
     TEST + "test_response_loss_cannot_repeat_work_and_sessions_do_not_share_calls"),
    ("worker output bound", MODULE + "Dispatch.answer", "len(output.encode()) > RECORD_BYTES",
     "False", TEST + "test_worker_output_is_bounded"),
    ("total receive bound", MODULE + "Wire.read", "self.received > TOTAL_BYTES", "False",
     TEST + "test_valid_frames_still_obey_total_budget"),
)

if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
