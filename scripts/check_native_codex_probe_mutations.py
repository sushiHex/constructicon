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
    ("client RPC separation", MODULE + "Dispatch.answer",
     'message.get("method") != "item/tool/call"', "False",
     TEST + "test_client_rpc_names_never_become_server_dispatch_authority"),
    ("model passed to thread", MODULE + "conversation", '"model": model',
     '"model": "probe-model"', TEST + "test_model_selection_reaches_configuration_and_thread"),
    ("model passed through driver", MODULE + "run_probe", "worker, model=model)", "worker)",
     TEST + "test_model_selection_reaches_configuration_and_thread"),
    ("model passed to config", "tests.substrate.test_native_codex_mediation:argv_for",
     'model = "{model}"', 'model = "probe-model"',
     TEST + "test_model_selection_reaches_configuration_and_thread"),
    *((name, "tests.substrate.test_native_codex_mediation:catalog_for", before, after,
       TEST + "test_catalog_changes_only_the_named_tool_selectors")
      for name, before, after in (
          ("catalog patch selector", "apply_patch_tool_type=None",
           'apply_patch_tool_type="freeform"'),
          ("catalog direct selector", 'tool_mode="direct"', 'tool_mode="code_mode_only"'),
          ("catalog collaboration selector", "multi_agent_version=None",
           'multi_agent_version="v2"'),
          ("catalog preserves other models", 'entry["slug"] in selected', "True"),
      )),
    ("catalog reaches config", "tests.substrate.test_native_codex_mediation:argv_for",
     "if catalog else ''", "if False else ''",
     TEST + "test_catalog_changes_only_the_named_tool_selectors"),
    ("native cleanup exit race", "tests.substrate.test_native_codex_mediation:stop_native",
     "suppress(ProcessLookupError)", "suppress()",
     TEST + "test_native_cleanup_uses_pinned_identity_despite_pid_reuse"),
    ("native cleanup uses stable process identity",
     "tests.substrate.test_native_codex_mediation:stop_native",
     "signal.pidfd_send_signal", "os.kill",
     TEST + "test_native_cleanup_uses_pinned_identity_despite_pid_reuse"),
    ("native enrollment refuses PID reuse",
     "tests.substrate.test_native_codex_mediation:pin_native",
     "state[1] == start", "True", TEST + "test_native_enrollment_refuses_a_reused_pid"),
    ("native activity requires heartbeat data",
     "tests.substrate._native_probe_owner:wait_for_heartbeat",
     " or not heartbeat.read_bytes()", "",
     TEST + "test_native_heartbeat_observes_data_not_file_creation"),
)

if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
