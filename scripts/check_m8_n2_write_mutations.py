"""N2 WRITE's closed callback and lifecycle laws; assertion failures only."""

from _mutations import run

PROTOCOL = "constructicon.substrate.executors.codex_protocol:"
TEST = "tests/substrate/test_codex_write_protocol.py::"
PARSE = PROTOCOL + "parse_tool_call"
BOUND = TEST + "test_program_and_output_bounds_permit_the_exact_byte_limit_and_refuse_one_more"
SHAPE = TEST + "test_callback_envelope_has_one_exact_shape"
PARAMS = TEST + "test_callback_parameters_cannot_widen_the_fixed_exchange"
EXACT = TEST + "test_exact_callback_and_terminal_response_are_permitted"
BUILDERS = TEST + "test_write_opt_in_and_catalog_are_explicit_while_read_bytes_stay_narrow"
CONVERSATION = "constructicon.substrate.executors.codex:CodexConversation."
DISPATCH = CONVERSATION + "_dispatch_tool"
AWAIT = CONVERSATION + "_await_callback"
WRITE = "tests/substrate/test_codex_write.py::"
LIFECYCLE = "tests/substrate/test_codex_write_lifecycle.py::"
ACCEPT = WRITE + "test_conversation_dispatches_one_callback_and_completes_its_response"
WORKSPACE = "constructicon.substrate.executors.codex:CodexOperatorHandle._validated_workspace"
WORKER = "constructicon.substrate.executors.codex:CodexOperatorHandle._run_worker"
RESULT = WRITE + "test_public_write_handle_accepts_only_a_complete_contained_worker"
PENDING = WRITE + "test_active_callback_refuses_terminal_or_bounded_pending_flood"
RESERVED = WRITE + "test_active_callback_reserves_pending_request_and_call_ids"
FOREIGN = WRITE + "test_write_handle_refuses_foreign_workspace_identity_before_native_io"

MUTANTS = (
    ("opt-in selector is exact rather than truthy", PROTOCOL + "initialize_request",
     'if type(experimental_api) is not bool:', 'if False:',
     TEST + "test_opt_in_selector_is_not_truthiness"),
    ("READ cannot inherit WRITE opt-in", PROTOCOL + "initialize_request",
     'if experimental_api else {}', 'if True else {}', BUILDERS),
    ("WRITE explicitly opts into its carrier", PROTOCOL + "initialize_request",
     'if experimental_api else {}', 'if False else {}', BUILDERS),
    ("thread registration has one closed catalog", PROTOCOL + "thread_start_request",
     'if dynamic_tools and tuple(dynamic_tools) != (CONTAINED_PYTHON_TOOL,):',
     'if False:', BUILDERS),
    ("WRITE actually registers its callback", PROTOCOL + "thread_start_request",
     'if dynamic_tools:', 'if False:', BUILDERS),
    ("callback envelope is exact", PARSE,
     'if set(record) != {"id", "method", "params"}:', 'if False:', SHAPE),
    ("booleans are not callback request ids", PARSE,
     'type(request_id) is int', 'isinstance(request_id, int)', SHAPE),
    ("only the admitted callback method is dispatchable", PARSE,
     'if record["method"] != "item/tool/call":', 'if False:', SHAPE),
    ("callback namespace cannot name another route", PARSE,
     'or params.get("namespace") is not None', 'or False', PARAMS),
    ("callback is bound to its thread", PARSE,
     'if params["threadId"] != thread_id:', 'if False:', PARAMS),
    ("callback is bound to its turn", PARSE,
     'if turn_id is not None and params["turnId"] != turn_id:', 'if False:', PARAMS),
    ("callback has a bounded call id", PARSE,
     'if not _bounded_wire_name(call_id):', 'if False:', PARAMS),
    ("callback cannot name a different tool", PARSE,
     'if params["tool"] != CONTAINED_PYTHON:', 'if False:', PARAMS),
    ("callback argument object cannot grow authority fields", PARSE,
     'set(arguments) != {"program"}', '"program" not in arguments', PARAMS),
    ("callback program byte bound binds", PARSE,
     'len(program.encode("utf-8")) > TOOL_PROGRAM_BYTES', 'False', BOUND),
    ("callback result byte bound binds", PROTOCOL + "tool_call_response",
     'len(output.encode("utf-8")) > TOOL_OUTPUT_BYTES', 'False', BOUND),
    ("wire name byte bound binds before turn identity", PROTOCOL + "_bounded_wire_name",
     'len(value.encode("utf-8")) <= TOOL_IDENTIFIER_BYTES', 'True',
     TEST + "test_wire_identifier_limit_binds_before_turn_identity_is_known"),
    ("response preserves inbound request identity", PROTOCOL + "tool_call_response",
     '"id": call.request_id', '"id": "another-request"', EXACT),
    ("joined successful worker gets a successful response", PROTOCOL + "tool_call_response",
     '"success": True', '"success": False', EXACT),
    ("callback receives the validated program", CONVERSATION + "_await_callback",
     'self._worker(program)', 'self._worker("")', ACCEPT),
    ("inbound callback request ids cannot repeat", DISPATCH,
     'if request_key in self._server_requests:', 'if False:',
     WRITE + "test_duplicate_inbound_request_id_refuses_without_a_second_effect"),
    ("inbound callback request ids are recorded", DISPATCH,
     'self._server_requests.add(request_key)', 'pass',
     WRITE + "test_duplicate_inbound_request_id_refuses_without_a_second_effect"),
    ("callback call ids cannot repeat", DISPATCH,
     'if call.call_id in self._tool_calls:', 'if False:',
     WRITE + "test_duplicate_call_id_refuses_without_a_second_effect"),
    ("callback call ids are spent", DISPATCH,
     'self._tool_calls.add(call.call_id)', 'pass',
     WRITE + "test_duplicate_call_id_refuses_without_a_second_effect"),
    ("callback count ceiling binds", DISPATCH,
     'if len(self._tool_calls) >= MAX_TOOL_CALLS:', 'if False:',
     WRITE + "test_callback_ceiling_binds_on_the_first_excess_call"),
    ("callback start is a recorded fact", DISPATCH,
     'self._callbacks_started += 1', 'self._callbacks_started += 0', ACCEPT),
    ("callback completion is a recorded fact", DISPATCH,
     'self._callbacks_completed += 1', 'self._callbacks_completed += 0', ACCEPT),
    ("pre-identity completion closes callback authority", CONVERSATION + "_defer_tool_request",
     'if self._deferred is not None:', 'if False:',
     WRITE + "test_callback_after_a_buffered_completion_is_never_dispatched"),
    ("native EOF interrupts the owned effect", AWAIT,
     '(worker, current), return_when=asyncio.FIRST_COMPLETED',
     '(worker,), return_when=asyncio.FIRST_COMPLETED',
     LIFECYCLE + "test_native_eof_cancels_a_callback_that_is_still_running"),
    ("joined cleanup errors remain observable", AWAIT,
     'if not isinstance(result, BaseException):', 'if True:',
     LIFECYCLE + "test_native_eof_preserves_a_callback_cleanup_failure"),
    ("cleanup failure preserves outer cancellation", AWAIT,
     'if primary is not None:', 'if False:',
     LIFECYCLE + "test_callback_cleanup_failure_keeps_outer_cancellation"),
    ("pending notifications have a record ceiling", AWAIT,
     'if records > CALLBACK_PENDING_RECORDS:', 'if False:',
     PENDING + "[notification-flood]"),
    ("pending callbacks have an aggregate byte ceiling", AWAIT,
     'if held_bytes + len(line) > CALLBACK_PENDING_BYTES:', 'if False:',
     PENDING + "[byte-flood]"),
    ("terminal completion cannot precede the callback response", AWAIT,
     'elif pending.get("method") == "turn/completed":', 'elif False:',
     PENDING + "[terminal]"),
    ("pending callbacks survive the completed response", DISPATCH,
     'self._queue = held + self._queue', 'self._queue = self._queue',
     WRITE + "test_parallel_exact_requests_are_held_and_effects_stay_sequential"),
    ("active request identity cannot be queued again", AWAIT,
     'request_key in self._server_requests', 'False', RESERVED + "[active-request]"),
    ("held request identity cannot be queued twice", AWAIT,
     'or request_key in held_requests', 'or False', RESERVED + "[held-request]"),
    ("active call identity cannot be queued again", AWAIT,
     'deferred.call_id in self._tool_calls', 'False', RESERVED + "[active-call]"),
    ("held call identity cannot be queued twice", AWAIT,
     'or deferred.call_id in held_calls', 'or False', RESERVED + "[held-call]"),
    ("pending calls share the invocation ceiling", AWAIT,
     'if len(self._tool_calls) + len(held) >= MAX_TOOL_CALLS:', 'if False:',
     WRITE + "test_active_callback_pending_count_ceiling_binds_before_an_excess_effect"),
    ("worker supervisor exit is checked independently", WORKER,
     'result.returncode != 0', 'False', RESULT + "[supervisor-exit]"),
    ("worker payload exit is checked independently", WORKER,
     'result.payload_returncode != 0', 'False', RESULT + "[payload-exit]"),
    ("worker timeout is checked independently", WORKER,
     'or result.timed_out', 'or False', RESULT + "[timed-out]"),
    ("worker output bound is checked independently", WORKER,
     'or result.bound_exceeded is not None', 'or False', RESULT + "[output-bound]"),
    ("missing worker exit is not a success fact", WORKER,
     'result.payload_returncode != 0',
     'result.payload_returncode is not None and result.payload_returncode != 0',
     RESULT + "[missing-payload]"),
    ("workspace ownership law is reused", WORKSPACE,
     'owned = provider.owned_view(workspace, self.context)', 'owned = workspace',
     FOREIGN + "[epoch]"),
    ("workspace shares the lease owner", WORKSPACE,
     'if actual.run_lease.owner_id != self.context.run_lease.owner_id:', 'if False:',
     FOREIGN + "[owner]"),
    ("workspace revision is current", WORKSPACE,
     'if actual.binding.revision != provider.revision:', 'if False:',
     FOREIGN + "[revision]"),
    ("workspace carries the exact grants", WORKSPACE,
     'canonical_json(actual.binding.effective_grants) != canonical_json(grants)', 'False',
     FOREIGN + "[grants]"),
)

assert len({name for name, *_ in MUTANTS}) == len(MUTANTS)

if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
