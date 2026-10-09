"""N2's subscription-mode gate, framing, request builders, decoder and adapter.

Run with ``uv run python scripts/check_m8_n2_mutations.py``. The shared runner
mutates only child-process code objects and requires an assertion failure: a
mutant that merely errors is NOT PROVEN, never a kill.

Every fault of the gate has a mutant here, and so does the pre-acceptance
discard — the behaviour ADR 0021 calls "refuses ... result acceptance", which
is the single most important thing in this slice.

One mechanical note that costs an hour to rediscover: the shared runner calls
``textwrap.dedent`` on the target's source before mutating it, so a replacement
spanning lines must be written at the *dedented* indentation — four spaces for a
method body, not eight. Getting it wrong raises ``IndentationError`` in the
child, which the runner scores as NOT PROVEN rather than a kill. That is the
runner behaving correctly; it is not a failing mutant.

A few mutants live in the handle's binding to the launcher, which only runs
where the physical acquisition guard does. Those are listed in ``LINUX_ONLY``
and are **filtered out entirely off Linux**, where they are reported as
UNMEASURED rather than counted as kills: the shared runner scores a skipped
test as no assertion, so leaving them in would silently turn a real gap into a
green line.

That list is currently empty. It held six entries until the adapter tests were
restructured to substitute only the acquisition guard, which made the handle's
own behaviour measurable everywhere; see ``LINUX_ONLY`` below.
"""

import sys

from _mutations import run

GATE = "constructicon.substrate.executors.codex_protocol:account_faults"
CHANGE = "constructicon.substrate.executors.codex_protocol:account_change_faults"
STREAM = "constructicon.substrate.executors.codex_protocol:RecordStream.feed"
SEALED = "constructicon.substrate.executors.codex_protocol:_sealed"
INITIALIZE = "constructicon.substrate.executors.codex_protocol:initialize_request"
ACCOUNT_READ = "constructicon.substrate.executors.codex_protocol:account_read_request"
TURN = "constructicon.substrate.executors.codex_protocol:turn_request"
THREAD_START = "constructicon.substrate.executors.codex_protocol:thread_start_request"
OBSERVE = "constructicon.substrate.executors.codex_protocol:observe_turn"
DECODE = "constructicon.substrate.executors.codex_protocol:decode_turn"
REFUSAL = "constructicon.substrate.executors.codex_protocol:unavailable_outcome"
CALL = "constructicon.substrate.executors.codex:CodexConversation.__call__"
CONVERSE = "constructicon.substrate.executors.codex:CodexConversation._converse"
PARSE = "constructicon.substrate.executors.codex_protocol:parse_record"
FINISH = "constructicon.substrate.executors.codex:CodexConversation._finish"
RATE_LIMIT = "constructicon.substrate.executors.codex_protocol:rate_limit_of"
ACCOUNT_RECORD = "constructicon.substrate.executors.codex_protocol:account_notice_faults"
SPEND = "constructicon.substrate.executors.codex_protocol:spend_faults"
READBACK = "constructicon.substrate.executors.codex_protocol:readback_faults"
NOTICE_STOP = "constructicon.substrate.executors.codex_protocol:notice_stop_faults"
IDENTITY = "constructicon.substrate.executors.codex_protocol:account_identity"
SEAL = "constructicon.substrate.executors.codex_protocol:ExpectedAccount.seal"

PROVIDER_INIT = "constructicon.substrate.executors.codex:CodexOperatorProvider.__init__"
READING = "constructicon.substrate.executors.codex_protocol:spend_reading"
BALANCE = "constructicon.substrate.executors.codex_protocol:_balance_zero"
CONVERSATION = "constructicon.substrate.executors.codex:CodexConversation.__init__"
TRANSCRIPT = "constructicon.substrate.executors.codex_protocol:_bounded_transcript"
EVIDENCE = "constructicon.substrate.executors.codex_protocol:_evidence"
EVIDENCE_ALLOWLIST = "constructicon.substrate.executors.codex_protocol:is_turn_evidence"
PREAMBLE = "constructicon.substrate.executors.codex:CodexConversation._drain_preamble"
COLLECT = "constructicon.substrate.executors.codex:CodexConversation._collect"
BINDING = "constructicon.substrate.executors.codex:CodexOperatorHandle._converse"
CORRELATE = "constructicon.substrate.executors.codex:CodexConversation._request"
EXECUTE = "constructicon.substrate.executors.codex:CodexOperatorHandle.execute"
CLOSE = "constructicon.substrate.executors.codex:CodexOperatorProvider.close"
DRAIN_BEFORE = "constructicon.substrate.executors.codex:CodexConversation._drain_before"
ABSORB = "constructicon.substrate.executors.codex:CodexConversation._absorb"
ONCE = "constructicon.substrate.executors.codex:CodexConversation._once"
AUDIT = "constructicon.substrate.executors.codex:CodexConversation._audit"
OWNED = "constructicon.substrate.executors.codex:CodexConversation._owned"
JUDGE = "constructicon.substrate.executors.codex:CodexConversation._judge_identified"
NOTICES = "constructicon.substrate.executors.codex:CodexConversation._notice_faults"
SETTINGS = "constructicon.substrate.executors.codex_protocol:settings_notice_faults"
CONFIGURED_PROVIDER = "constructicon.substrate.executors.codex:configured_provider"
TURN_OF = "constructicon.substrate.executors.codex_protocol:_turn_of"
USAGE = "constructicon.substrate.executors.codex_protocol:_usage"
NUMBER = "constructicon.substrate.executors.codex_protocol:_number"
NAMEABLE = "constructicon.substrate.executors.codex_protocol:_nameable"
PROVIDER = "constructicon.substrate.executors.codex:CodexOperatorProvider.unavailable_reasons"
CONSTRUCTOR = "constructicon.substrate.executors.codex:CodexOperatorProvider.__init__"

PROTOCOL = "tests/substrate/test_codex_protocol.py::"
ADAPTER = "tests/substrate/test_codex_adapter.py::"
STORE_ADAPTER = "tests/substrate/test_codex_store.py::"
SPEND_TEST = "tests/substrate/test_codex_spend.py::"
STARTUP_TEST = "tests/substrate/test_codex_startup.py::"
MATRIX_TEST = "tests/substrate/test_codex_matrix.py::"
WRITE_TEST = "tests/substrate/test_codex_write.py::"

UPDATED = "constructicon.substrate.executors.codex_protocol:updated_plan"
EXACT_UPDATED = "constructicon.substrate.executors.codex_protocol:_exact_updated_plan"
ACCEPT_REPLY = "constructicon.substrate.executors.codex:CodexConversation._accept_reply"
JUDGE_ACCOUNT = "constructicon.substrate.executors.codex:CodexConversation._judge_account"
EFFORT = "constructicon.substrate.executors.codex:configured_effort"
ROUTING = "constructicon.substrate.executors.codex_protocol:routing_faults"
COMPLETED_ITEM = "constructicon.substrate.executors.codex_protocol:_completed_item"
UNSEALED = PROTOCOL + "test_a_reading_routed_anywhere_else_stops_the_session"
EXCHANGE = "constructicon.substrate.executors.codex:CodexOperatorHandle._exchange"
RELAY_FAULTS = "constructicon.substrate.executors.codex:relay_faults"
EGRESS_REFUSED = (
    "tests/substrate/test_codex_egress.py::test_no_private_locator_reaches_the_outcome[refused]"
)
ANSWER = "constructicon.substrate.executors.codex_protocol:_answer"
ATTRIBUTED = "constructicon.substrate.executors.codex_protocol:_attributed"
REROUTED = "constructicon.substrate.executors.codex_protocol:_rerouted_to"
EVIDENCE_DAMAGE = PROTOCOL + "test_evidence_that_is_not_this_turns_or_is_malformed_is_damage"
CONTRADICTION = ADAPTER + "test_a_contradicting_account_update_refuses"
N5_PROTOCOL = (
    # --- N5 Stage 0: account/updated on an exact match only (decision 1) ---
    ("N5-1 account/updated is admitted when exact", ACCOUNT_RECORD,
     "if updated_plan(record, expected) is not None:", "if False:",
     SPEND_TEST + "test_an_exact_account_update_naming_an_accepted_plan_passes"),
    ("N5-2 account/updated has exactly two keys", EXACT_UPDATED,
     'set(params) != {"authMode", PLAN_TYPE_KEY}',
     'not {"authMode", PLAN_TYPE_KEY} <= set(params)',
     SPEND_TEST + "test_any_other_account_update_refuses"),
    ("N5-3 account/updated names the chatgpt mode", EXACT_UPDATED,
     'or params["authMode"] != "chatgpt" ', "",
     SPEND_TEST + "test_any_other_account_update_refuses"),
    ("N5-4 account/updated carries no reply or error", EXACT_UPDATED,
     'or "result" in record or "error" in record', "",
     SPEND_TEST + "test_any_other_account_update_refuses"),
    ("N5-5 account/updated names an accepted plan", UPDATED,
     "return plan if expected.accepts(plan) else None", "return plan",
     SPEND_TEST + "test_any_other_account_update_refuses"),
    ("N5-6 notices agree with each other", NOTICES,
     "if self._noticed_plan not in (None, plan):", "if False:",
     CONTRADICTION + "[between-notices]"),
    ("N5-7 the first reading agrees with the notices", JUDGE_ACCOUNT,
     "if not faults and self._noticed_plan not in (None, account_plan(reply)):", "if False:",
     CONTRADICTION + "[before-reading]"),
    # --- N5 Stage 0: the decoder reads the pinned events ---
    ("N5-8 the old turn fields stay unread", ANSWER,
     '    view, items = turn.get("itemsView"), turn.get("items")',
     '    if "output" in turn:\n        return turn["output"], True\n'
     '    view, items = turn.get("itemsView"), turn.get("items")',
     PROTOCOL + "test_the_old_turn_fields_are_never_read"),
    ("N5-9 the summary holds exactly one item", ANSWER,
     "len(items) == 1", "len(items) >= 1",
     PROTOCOL + "test_terminal_items_that_are_not_the_pinned_summary_are_damage"),
    ("N5-10 an empty answer is no answer", ANSWER,
     "return text or None, True", "return text, True",
     PROTOCOL + "test_a_completed_turn_without_an_answer_is_damage_only_where_one_is_required"),
    ("N5-11 a READ turn requires an answer", OBSERVE,
     "elif answer_required and completed and answer is None:", "elif False:",
     PROTOCOL + "test_a_completed_turn_without_an_answer_is_damage_only_where_one_is_required"),
    ("N5-12 the READ rule is the conversation's without a catalog", CALL,
     "answer_required=not self._catalog,", "answer_required=False,",
     ADAPTER + "test_a_read_turn_that_completes_without_an_answer_is_damage"),
    ("N5-13 a WRITE turn may complete without prose", CALL,
     "answer_required=not self._catalog,", "answer_required=True,",
     WRITE_TEST + "test_a_write_turn_may_complete_without_prose"),
    ("N5-14 another turn's evidence is damage", ATTRIBUTED,
     ' or params.get("turnId") != turn_id', "", EVIDENCE_DAMAGE),
    ("N5-15 another thread's evidence is damage", ATTRIBUTED,
     'or params.get("threadId") != thread_id ', "", EVIDENCE_DAMAGE),
    ("N5-16 malformed evidence never rewrites a fact", OBSERVE,
     "if fact is None:", "if False:", EVIDENCE_DAMAGE),
    ("N5-17 a usage count is non-negative", USAGE,
     "count >= 0 and ", "", EVIDENCE_DAMAGE),
    ("N5-18 a usage count is an integer, never a boolean", USAGE,
     "type(count) is int", "isinstance(count, int)", EVIDENCE_DAMAGE),
    ("N5-19 a reroute target is a bounded model name", REROUTED,
     "set(model) <= MODEL_CHARS", "True", EVIDENCE_DAMAGE),
    ("N5-20 the served model is never inferred", DECODE,
     '"served_model": observation.served_model,',
     '"served_model": observation.served_model or requested_model,',
     PROTOCOL + "test_no_reroute_means_the_served_model_is_unknown_never_the_requested_one"),
    ("N5-21 a turn that never completes keeps its partial text", OBSERVE,
     "output=answer if answer is not None else partial,", "output=answer,",
     PROTOCOL + "test_a_turn_that_never_completes_keeps_its_completed_messages_as_partial_text"),
    ("N5-22 the terminal answer is the output", OBSERVE,
     "output=answer if answer is not None else partial,", "output=partial or answer,",
     PROTOCOL + "test_a_terminal_answer_replaces_the_partial_text"),
    ("N5-29 an empty last message leaves no stale partial text", OBSERVE,
     "partial = fact or None", "partial = fact or partial",
     PROTOCOL + "test_an_empty_last_message_leaves_no_partial_text"),
    ("N5-28 a failed turn keeps the text it showed", OBSERVE,
     "output=answer if answer is not None else partial,",
     "output=answer if terminal else partial,",
     PROTOCOL + "test_a_failed_turn_keeps_its_partial_text_only_as_the_output_of_a_partial"),
    ("N5-23 only the two admitted item types are evidence", EVIDENCE_ALLOWLIST,
     "return isinstance(item, Mapping) and item.get(\"type\") in EVIDENCE_ITEMS", "return True",
     PROTOCOL + "test_only_agent_message_items_are_evidence"),
    # --- N5 Stage 0: the turn's evidence, held and drained ---
    ("N5-24 evidence before the turn/start reply is held", ABSORB,
     "self._held.append(line)", "pass",
     ADAPTER + "test_turn_evidence_before_the_turn_start_reply_is_held_for_the_turn"),
    ("N5-25 bytes framed before turn/start was written are never held", ABSORB,
     "self._turn_requested and not pre_send and", "self._turn_requested and",
     ADAPTER + "test_evidence_read_before_turn_start_was_written_is_never_the_turns"
     "[straddling]"),
    ("N5-26 held evidence joins the transcript before any callback", CONVERSE,
     "    self._transcript.extend(self._held)\n    self._held.clear()\n"
     "    if self._deferred_request is not None and self._deferred is not None:\n"
     '        self._refuse("the turn completed before its deferred callback was answered")\n'
     "        return\n"
     "    if not await self._claim_deferred_request(io):\n        return\n",
     "    if self._deferred_request is not None and self._deferred is not None:\n"
     '        self._refuse("the turn completed before its deferred callback was answered")\n'
     "        return\n"
     "    if not await self._claim_deferred_request(io):\n        return\n"
     "    self._transcript.extend(self._held)\n    self._held.clear()\n",
     WRITE_TEST + "test_held_evidence_keeps_its_order_across_a_buffered_callback"),
    ("N5-27 the drain transcribes the turn's evidence", AUDIT,
     "self._absorb(line, record)", "pass",
     ADAPTER + "test_turn_evidence_in_the_drain_is_folded_too"),
    # --- N5 Stage 0b: the sealed effort, and relay denials in the provider ---
    ("N5-30 the sealed configuration must name an effort", EFFORT,
     'return _configured(configuration, "model_reasoning_effort")', 'return "low"',
     ADAPTER + "test_an_unusable_configuration_is_refused_at_construction[no-effort]"),
    ("N5-31 the sealed effort is one the profile accepts", CONSTRUCTOR,
     "if self.configured_effort not in profile.accepted_efforts:", "if False:",
     ADAPTER + "test_an_unusable_configuration_is_refused_at_construction[effort-not-accepted]"),
    ("N5-32 a grant's effort must be the sealed one", EXECUTE,
     "if grants.effort != self.provider.configured_effort:", "if False:",
     ADAPTER + "test_a_grant_that_disagrees_with_the_configuration_is_refused[effort]"),
    ("N5-33 a relay denial refuses the turn", BINDING,
     "faults = conversation.faults + relay_faults(self.relay_denied)",
     "faults = conversation.faults", EGRESS_REFUSED),
    ("N5-34 the relay's denials are read however the exchange ends", EXCHANGE,
     "self.relay_denied = relay.denied", "pass", EGRESS_REFUSED),
    ("N5-35 any denial is a refusal", RELAY_FAULTS,
     "return (RELAY_DENIAL_FAULT,) if denied else ()", "return ()", EGRESS_REFUSED),
    # --- N5 Stage 0b: an unsealed backend stops the session (decision 2) ---
    ("N5-36 every reading's routing is judged", GATE,
     "return tuple(faults) + routing_faults(result)", "return tuple(faults)", UNSEALED),
    ("N5-37 the routed origin must be the sealed one", ROUTING,
     'routing.get("backendOrigin") == SEALED_BACKEND', "True",
     UNSEALED + "[other-origin]"),
    # The override's ``isinstance`` guard is not mutated: without it an
    # unhashable override raises instead of refusing, a crash, not a pass.
    ("N5-38 the residency override must be a known literal", ROUTING,
     " and isinstance(override, str) and override in ROUTING_OVERRIDES", "",
     UNSEALED + "[unknown-override]"),
    # --- N5 Stage 0b: a total with no input is no measurement; compaction ---
    ("N5-39 a filled total makes the usage unknown", USAGE,
     "if counts[0] == 0:", "if False:",
     PROTOCOL + "test_a_synthesized_total_makes_the_usage_unknown_not_zero"),
    ("N5-40 an initialized zero total is no measurement", USAGE,
     "if counts[0] == 0:", "if counts[0] == 0 and counts[2]:",
     PROTOCOL + "test_an_initialized_zero_total_is_no_measurement"),
    ("N5-41 a compaction makes the turn's usage unknown", OBSERVE,
     "usage=None if compacted else usage,", "usage=usage,",
     PROTOCOL + "test_a_compaction_makes_the_turns_usage_unknown"),
    ("N5-43 only a compaction in its pinned shape is one", COMPLETED_ITEM,
     "COMPACTED if isinstance(identifier, str) and identifier else None", "COMPACTED",
     PROTOCOL + "test_a_malformed_compaction_is_damage_and_clears_nothing"),
    ("N5-42 a compaction item is evidence", EVIDENCE_ALLOWLIST,
     "EVIDENCE_ITEMS", "{AGENT_MESSAGE}",
     PROTOCOL + "test_a_compaction_makes_the_turns_usage_unknown"),
    # The sealed account identity (M8-N5-account-identity.md).
    ("N5-A1 an account the wire does not name refuses", GATE,
     "faults.append(NO_IDENTITY_FAULT)", "pass",
     PROTOCOL + "test_an_account_the_wire_does_not_name_refuses"),
    ("N5-A2 another account than the sealed one refuses", GATE,
     "elif expected.identity is not None and identity != expected.identity:", "elif False:",
     PROTOCOL + "test_another_account_than_the_sealed_one_refuses"),
    ("N5-A3 the identity needs the workspace", IDENTITY,
     "and isinstance(workspace, str) and workspace", "",
     PROTOCOL + "test_an_account_the_wire_does_not_name_refuses"),
    ("N5-A4 the identity needs the login", IDENTITY,
     "isinstance(email, str) and email and ", "",
     PROTOCOL + "test_an_account_the_wire_does_not_name_refuses"),
    ("N5-A6 only a sealed account has a seal", SEAL,
     "if self.identity is None or self.alternatives:", "if False:",
     PROTOCOL + "test_only_a_sealed_account_has_a_seal[qualifying]"),
    ("N5-A7 the run seals the first reading's account", CONVERSE,
     "identity=self.observed_account,", "",
     ADAPTER + "test_another_login_after_the_turn_is_refused_whoever_sealed_the_first"),
    ("N5-A8 a refused reading's account is still recorded", JUDGE_ACCOUNT,
     "self.observed_account = account_identity(reply)", "self.observed_account = None",
     ADAPTER + "test_a_sealed_account_refuses_another_login_before_any_turn"),
    ("N5-A9 a provider requires the sealed account", PROVIDER_INIT,
     "if expected_account.identity is None or expected_account.alternatives:", "if False:",
     ADAPTER + "test_an_operator_provider_requires_the_account_its_binding_sealed"),
)  # fmt: skip

ERROR_REPLY = PROTOCOL + "test_an_error_or_missing_result_refuses"
NULL_ACCOUNT = PROTOCOL + "test_a_null_account_refuses_without_naming_a_cause"
WRONG_TYPE = PROTOCOL + "test_an_api_or_cloud_credential_refuses"
OVERRIDE = PROTOCOL + "test_a_provider_override_refuses_independently_of_the_account"
NO_PLAN = PROTOCOL + "test_a_missing_plan_fact_refuses"
WRONG_PLAN = PROTOCOL + "test_a_different_plan_refuses"
CHANGED = PROTOCOL + "test_a_reading_that_differs_from_the_pre_turn_one_refuses"
DISCARD = ADAPTER + "test_a_pre_acceptance_gate_fault_discards_a_successful_turn"

MUTANTS = (
    (
        "fault 1: an error or a missing result refuses",
        GATE,
        "return (NO_RESULT_FAULT,)",
        "return ()",
        ERROR_REPLY,
    ),
    (
        "fault 2: no usable account refuses",
        GATE,
        "if known is None:",
        "if False:",
        NULL_ACCOUNT,
    ),
    (
        "fault 3: an api or cloud account type refuses",
        GATE,
        "if known is not None and known.get(ACCOUNT_TYPE_KEY) != expected.account_type:",
        "if False:",
        WRONG_TYPE,
    ),
    (
        "fault 4: a provider override refuses",
        GATE,
        "if result.get(PROVIDER_FLAG_KEY) is not True:",
        "if False:",
        OVERRIDE,
    ),
    (
        "fault 4: only an exact true clears the provider check",
        GATE,
        "if result.get(PROVIDER_FLAG_KEY) is not True:",
        "if result.get(PROVIDER_FLAG_KEY) is False:",
        OVERRIDE,
    ),
    (
        "fault 5: a missing plan fact refuses",
        GATE,
        "if known is not None and plan is None:",
        "if False:",
        NO_PLAN,
    ),
    (
        "fault 6: a plan other than the provisioned one refuses",
        GATE,
        "if plan is not None and not expected.accepts(plan):",
        "if False:",
        WRONG_PLAN,
    ),
    (
        "fault 7: the two readings must agree",
        CHANGE,
        "if old != new",
        "if False",
        CHANGED,
    ),
    (
        "the pre-acceptance reading is actually taken",
        CONVERSE,
        "after = await self._account(io)",
        "after = before",
        DISCARD,
    ),
    (
        "a faulting pre-acceptance reading discards the turn",
        CONVERSE,
        "self.faults += self._judge_account(after)",
        "self.faults += ()",
        DISCARD,
    ),
    (
        "a changed pre-acceptance reading discards the turn",
        CONVERSE,
        "self.faults += account_change_faults(before, after)",
        "self.faults += ()",
        ADAPTER + "test_a_pre_acceptance_reading_that_merely_changed_discards_the_turn",
    ),
    (
        "a refused pre-turn reading sends no turn",
        CONVERSE,
        "if faults:\n        # A refused pre-turn reading never sends a turn.",
        "if False:\n        # A refused pre-turn reading never sends a turn.",
        ADAPTER + "test_a_pre_turn_gate_fault_refuses_without_sending_a_turn",
    ),
    (
        "the gate's completion is recorded, never inferred from silence",
        CALL,
        "if not self.gate_completed and not self.faults:",
        "if False:",
        ADAPTER + "test_a_conversation_aborted_at_its_first_read_never_looks_clean",
    ),
    (
        "nothing before the pre-acceptance reading may record completion",
        CONVERSE,
        # The runner dedents the method source, so the body sits at four spaces.
        "after = await self._account(io)",
        "self.gate_completed = True\n    after = await self._account(io)",
        ADAPTER + "test_a_conversation_aborted_during_the_pre_acceptance_reading_refuses",
    ),
    (
        "a pathological record is damage, not an escape",
        PARSE,
        "raise RecordDamaged(DAMAGE_NESTING) from exc",
        "raise",
        ADAPTER + "test_a_pathological_record_is_damage_rather_than_an_escape",
    ),
    (
        "a reply must arrive after the request it answers",
        DRAIN_BEFORE,
        "while self._queue:",
        "while False:",
        ADAPTER + "test_a_reply_queued_before_its_request_cannot_answer_it",
    ),
    (
        "a queued id-bearing record is not a notification",
        DRAIN_BEFORE,
        'if "id" in record:',
        "if False:",
        ADAPTER + "test_a_reply_queued_before_its_request_cannot_answer_it",
    ),
    (
        "the decoder's own message never reaches a public field",
        PARSE,
        "raise RecordDamaged(_damage_reason(exc)) from exc",
        "raise RecordDamaged(str(exc)) from exc",
        PROTOCOL + "test_a_duplicated_key_is_classified_never_quoted",
    ),
    (
        "an account notification is refused wherever it arrives",
        ABSORB,
        "if notice:",
        "if False:",
        ADAPTER + "test_an_account_notification_mid_turn_discards_the_turn",
    ),
    (
        "a reply must correlate with the request that earned it",
        ACCEPT_REPLY,
        'if type(record["id"]) is not int:',
        "if False:",
        ADAPTER + "test_a_reply_whose_id_is_the_awaited_int_spelled_as_a_float_is_refused",
    ),
    (
        "an executor call must match its sealed grants",
        EXECUTE,
        "if canonical_json(grants) != canonical_json(self.context.binding.effective_grants):",
        "if False:",
        ADAPTER + "test_grants_differing_from_the_sealed_set_are_refused",
    ),
    (
        "READ initialize never requests the experimental capability",
        INITIALIZE,
        '"capabilities": {"experimentalApi": True} if experimental_api else {},',
        '"capabilities": {"experimentalApi": True},',
        PROTOCOL + "test_initialize_never_requests_the_experimental_capability",
    ),
    (
        "the mode reading never causes a refresh",
        ACCOUNT_READ,
        '"params": {"refreshToken": False},',
        '"params": {"refreshToken": True},',
        PROTOCOL + "test_account_read_observes_and_never_causes_a_refresh",
    ),
    (
        "a provider override field is refused structurally",
        SEALED,
        "if overrides:",
        "if False:",
        PROTOCOL + "test_a_provider_override_field_is_refused_structurally",
    ),
    (
        "a thread never opts into an approval policy",
        THREAD_START,
        '"sandbox": "read-only",',
        '"sandbox": "read-only", "approvalPolicy": "never",',
        PROTOCOL + "test_a_thread_never_opts_into_an_approval_policy",
    ),
    (
        "a composed byte scope's preamble is drained",
        PREAMBLE,
        "for _ in range(self._preamble):",
        "for _ in range(0):",
        ADAPTER + "test_a_composed_byte_scope_preamble_is_drained_and_never_transcribed",
    ),
    (
        "a scope ending inside its preamble refuses before initialize",
        CONVERSE,
        "if not await self._drain_preamble(io):",
        "if False:",
        ADAPTER + "test_a_byte_scope_that_ends_inside_its_preamble_refuses",
    ),
    (
        "a turn requires the explicit sealed model",
        TURN,
        'if selection.kind != "explicit" or not (selection.model or "").strip():',
        "if False:",
        PROTOCOL + "test_a_turn_requires_the_explicit_sealed_model_even_though_it_never_sends_it",
    ),
    (
        "an oversized record is damage",
        STREAM,
        "if len(self.pending) >= RECORD_BYTES:",
        "if False:",
        PROTOCOL + "test_an_oversized_record_is_damage_rather_than_an_exception",
    ),
    (
        "a stream ending inside a record is refused",
        STREAM,
        "if self.pending:",
        "if False:",
        PROTOCOL + "test_a_stream_ending_inside_a_record_is_refused_not_accepted",
    ),
    (
        "a reply never reaches the transcript",
        OBSERVE,
        'if not isinstance(record, dict) or "id" in record or "method" not in record:',
        'if not isinstance(record, dict) or "method" not in record:',
        PROTOCOL + "test_a_reply_or_a_native_request_never_reaches_the_transcript",
    ),
    (
        "two terminal records are contradictory, not last-wins",
        OBSERVE,
        "if terminal:",
        "if False:",
        PROTOCOL + "test_two_terminal_records_are_contradictory_rather_than_last_wins",
    ),
    (
        "a timeout salvages rather than succeeding",
        DECODE,
        "if process.timed_out:",
        "if False:",
        PROTOCOL + "test_a_timeout_salvages_the_output_it_did_see",
    ),
    (
        "an incomplete private exit report is infrastructure",
        DECODE,
        "process.payload_returncode is None or process.payload_returncode != process.returncode",
        "False",
        PROTOCOL + "test_an_incomplete_private_exit_report_is_never_a_success_or_an_exit",
    ),
    (
        "a nonzero exit without a bound breach is an exit failure",
        DECODE,
        "if process.returncode and not (process.bound_exceeded or incomplete):",
        "if False:",
        PROTOCOL + "test_a_nonzero_exit_without_a_bound_breach_is_an_exit_failure",
    ),
    (
        "a turn with no terminal record demotes",
        DECODE,
        'or (None if observation.terminal else "no terminal turn record")',
        "or None",
        PROTOCOL + "test_a_turn_with_no_terminal_record_demotes_to_partial",
    ),
    (
        "a refused gate names its faults",
        REFUSAL,
        'detail=_bounded("; ".join(faults), DETAIL_CHARS),',
        'detail="",',
        PROTOCOL + "test_a_refused_gate_discards_the_result_and_still_reports_that_a_turn_ran",
    ),
    (
        "no account method is attested turn evidence",
        EVIDENCE_ALLOWLIST,
        "return method in TURN_EVIDENCE_METHODS or method.startswith(TURN_EVIDENCE_PREFIXES)",
        "return not method.startswith('turn/completed-never')",
        PROTOCOL + "test_no_account_method_is_attested_turn_evidence",
    ),
    (
        "the adapter discards a refused turn",
        BINDING,
        # Dedented: the method body sits at four spaces.
        "    if faults:\n        return unavailable_outcome(",
        "    if False:\n        return unavailable_outcome(",
        ADAPTER + "test_execute_discards_a_turn_whose_pre_acceptance_reading_faults",
    ),
    (
        "the launcher receives this acquisition's guard",
        BINDING,
        "guard_fds=(guard, held.lock_fd),",
        "guard_fds=(held.lock_fd,),",
        STORE_ADAPTER
        + "test_materialization_retains_one_store_lock_and_records_three_checks",
    ),
    (
        "a drifted launch recipe refuses",
        BINDING,
        "if provider.launcher.revision != provider.identity.isolation_revision:",
        "if False:",
        ADAPTER + "test_a_launch_recipe_that_drifts_after_construction_refuses",
    ),
    (
        "a grouped cancellation stays a cancellation",
        BINDING,
        "if group.subgroup(asyncio.CancelledError) is not None:",
        "if False:",
        ADAPTER + "test_a_grouped_cleanup_failure_keeps_a_cancellation_a_cancellation",
    ),
    (
        "close cancels an exchange still in flight",
        CLOSE,
        'await self._own(acquisition, "close").cleanup(disposition)',
        'self._own(acquisition, "close").closed = True',
        STORE_ADAPTER
        + "test_materialization_retains_one_store_lock_and_records_three_checks",
    ),
    (
        "the published readback is a fixed vocabulary of present facts",
        RATE_LIMIT,
        "if (value := getattr(reading, name)) is not None",
        "if (value := getattr(reading, name)) is not None or True",
        SPEND_TEST + "test_only_the_fixed_vocabulary_is_published_and_no_identity_fact",
    ),
    (
        "a wire value reaches a public detail only when classified",
        GATE,
        "f\"account type {named_value(known.get(ACCOUNT_TYPE_KEY))} is not the \"",
        "f\"account type {known.get(ACCOUNT_TYPE_KEY)!r} is not the \"",
        PROTOCOL + "test_no_unbounded_wire_value_reaches_a_public_fault_detail",
    ),
    (
        "no unparseable byte is republished",
        OBSERVE,
        # The runner dedents, so the fold's body sits at eight spaces.
        "            continue\n        if not isinstance(record, dict)",
        "            kept.append(line.decode('utf-8', errors='replace'))\n"
        "            continue\n        if not isinstance(record, dict)",
        PROTOCOL + "test_no_unparseable_byte_is_ever_published",
    ),
    (
        "the transcript carries attested evidence only",
        OBSERVE,
        "if not is_turn_evidence(record):",
        "if False:",
        PROTOCOL + "test_an_unattested_method_is_excluded_without_being_called_damage",
    ),
    (
        "the account namespace is a prefix, not an exact name",
        ACCOUNT_RECORD,
        "if method.startswith((ACCOUNT_NAMESPACE, PROVIDER_NAMESPACE)):",
        "if method in (ACCOUNT_NAMESPACE, PROVIDER_NAMESPACE):",
        PROTOCOL + "test_the_whole_account_namespace_is_refused_not_a_list_of_known_methods",
    ),
    (
        "an exclusion is counted rather than silent",
        OBSERVE,
        "unclassified += 1",
        "unclassified += 0",
        PROTOCOL + "test_the_item_namespace_is_excluded_and_says_so_rather_than_going_silent",
    ),
    (
        "the item namespace is not attested evidence",
        EVIDENCE_ALLOWLIST,
        'TURN_EVIDENCE_PREFIXES',
        '("turn/", "item/")',
        PROTOCOL + "test_the_item_namespace_is_excluded_and_says_so_rather_than_going_silent",
    ),
    (
        "the transcript is bounded",
        TRANSCRIPT,
        "if size + len(item) > TRANSCRIPT_CHARS:",
        "if False:",
        PROTOCOL + "test_the_transcript_is_bounded_and_says_how_much_it_dropped",
    ),
    (
        "the stderr excerpt is bounded",
        EVIDENCE,
        "[:EVIDENCE_BYTES]",
        "[:]",
        PROTOCOL + "test_a_bound_breach_demotes_to_partial_with_bounded_stderr_evidence",
    ),
    (
        "framing damage reaches the observation",
        CALL,
        "transport_damage=self._stream.damage,",
        "transport_damage=None,",
        ADAPTER + "test_framing_damage_reaches_the_outcome_rather_than_vanishing",
    ),
    (
        "the drain runs to EOF",
        FINISH,
        "chunk = await io.read(self._stream.next_read())",
        "chunk = b''",
        ADAPTER + "test_the_conversation_drains_to_eof_after_closing_stdin",
    ),
    (
        "a notification before the turn is not its evidence",
        ABSORB,
        "if self._collecting:",
        "if True:",
        ADAPTER + "test_a_notification_before_the_turn_is_not_the_turns_evidence",
    ),
    (
        "the configured model must equal the granted one",
        EXECUTE,
        "if grants.model_selection.model != self.provider.configured_model:",
        "if False:",
        ADAPTER + "test_a_grant_that_disagrees_with_the_configuration_is_refused",
    ),
    (
        "the configuration's model must be in the inventory",
        CONSTRUCTOR,
        "if self.configured_model not in profile.grant_policy.model_ids:",
        "if False:",
        ADAPTER + "test_the_configuration_must_name_a_model_from_the_profiles_inventory",
    ),
    (
        "the turn status reaches a public field classified",
        OBSERVE,
        "f\"the turn reported status {named_value(turn.get('status'))}\"",
        "f\"the turn reported status {turn.get('status')!r}\"",
        PROTOCOL + "test_no_planted_wire_string_escapes_its_permitted_field_on_a_turn",
    ),
    (
        "the damage first error is bounded",
        DECODE,
        "first_error=_bounded(damage, FIRST_ERROR_CHARS),",
        "first_error=damage,",
        PROTOCOL + "test_a_long_transport_damage_string_is_bounded_in_the_outcome",
    ),
    (
        "the refusal detail is bounded",
        REFUSAL,
        'detail=_bounded("; ".join(faults), DETAIL_CHARS),',
        'detail="; ".join(faults),',
        PROTOCOL + "test_a_long_refusal_detail_is_bounded_in_the_outcome",
    ),
    (
        "a wire number's magnitude is bounded",
        NUMBER,
        "and len(repr(value)) <= NUMBER_CHARS",
        "",
        PROTOCOL + "test_no_published_number_is_larger_than_a_number"
    ),
    (
        "a usage number's magnitude is bounded",
        USAGE,
        "count >= 0 and len(repr(count)) <= NUMBER_CHARS",
        "count >= 0",
        PROTOCOL + "test_no_published_number_is_larger_than_a_number"
    ),
    (
        "the nameable alphabet is ascii, not unicode alphanumerics",
        NAMEABLE,
        "character in NAMEABLE_ALPHABET",
        "character.isalnum()",
        PROTOCOL + "test_a_non_ascii_value_is_not_nameable_despite_being_alphanumeric",
    ),
    (
        "the withheld record count is exact",
        TRANSCRIPT,
        "dropped = len(kept) - index",
        "dropped = 1",
        PROTOCOL + "test_the_withheld_record_count_is_exact_not_merely_present",
    ),
    (
        "the transcript bound counts its newlines",
        TRANSCRIPT,
        "size += len(item) + 1",
        "size += len(item)",
        PROTOCOL + "test_the_transcript_bound_counts_the_newlines_it_adds",
    ),
    (
        "the three attested names are load-bearing",
        EVIDENCE_ALLOWLIST,
        "return method in TURN_EVIDENCE_METHODS or method.startswith(TURN_EVIDENCE_PREFIXES)",
        "return method.startswith(TURN_EVIDENCE_PREFIXES)",
        PROTOCOL + "test_an_attested_turn_notification_is_kept_as_evidence",
    ),
    (
        "an unidentified invocation has no terminal record",
        TURN_OF,
        "if thread_id is None or turn_id is None:",
        "if False:",
        PROTOCOL + "test_an_unidentified_invocation_can_have_no_terminal_record",
    ),
    (
        "a nested configuration refuses as a contract violation",
        "constructicon.substrate.executors.codex:_configured",
        'raise ContractViolation(f"the sealed configuration is {DAMAGE_NESTING}") from exc',
        "raise",
        ADAPTER + "test_a_deeply_nested_configuration_refuses_as_a_contract_violation",
    ),
    (
        "nothing read before the turn is the turn's evidence",
        CONVERSE,
        "self._collecting = True",
        "",
        ADAPTER + "test_a_notification_between_the_thread_and_the_turn_is_not_turn_evidence",
    ),
    (
        "the drain accounts for the record still being framed",
        DRAIN_BEFORE,
        "self._pre_send_record = bool(self._stream.pending)",
        "self._pre_send_record = False",
        ADAPTER + "test_a_half_framed_forgery_is_refused_with_no_genuine_reply_behind_it",
    ),
    (
        "a pre-send record cannot answer the request",
        CORRELATE,
        "if pre_send:\n            # Its bytes were read before this request",
        "if False:\n            # Its bytes were read before this request",
        ADAPTER + "test_a_half_framed_forgery_is_refused_with_no_genuine_reply_behind_it",
    ),
    (
        "no id is answered twice",
        ONCE,
        "if identifier in self._correlated:",
        "if False:",
        ADAPTER + "test_a_duplicate_reply_id_is_refused_even_during_the_drain_to_eof",
    ),
    (
        "the drain to eof applies the duplicate rule",
        AUDIT,
        'if not self._judge_identified(\n'
        '        line, record, context="the drain to EOF", awaiting=awaiting,\n'
        '    ):',
        "if False:",
        ADAPTER + "test_a_duplicate_reply_id_is_refused_even_during_the_drain_to_eof",
    ),
    (
        "a correlated id is remembered",
        ACCEPT_REPLY,
        "self._correlated.add(record[\"id\"])",
        "pass",
        ADAPTER + "test_a_duplicate_reply_id_is_refused_even_during_the_drain_to_eof",
    ),
    (
        "an incomplete duplicate check is not a pass",
        FINISH,
        "if inconclusive:",
        "if False:",
        ADAPTER + "test_a_twice_answered_id_is_refused_whatever_sits_between_the_replies",
    ),
    (
        "damaged bytes leave the check inconclusive",
        AUDIT,
        "return True",
        "return False",
        ADAPTER + "test_a_twice_answered_id_is_refused_whatever_sits_between_the_replies",
    ),
    (
        "the drain audits records already framed",
        FINISH,
        "if self._queue:",
        "if False:",
        ADAPTER + "test_a_twice_answered_id_is_refused_whatever_sits_between_the_replies",
    ),
    (
        "an unhashable id never reaches a hash",
        OWNED,
        "return _hashable(identifier) and identifier in self._allocated",
        "return identifier in self._allocated",
        ADAPTER + "test_an_unhashable_id_in_the_drain_escapes_nothing",
    ),
    (
        "an id we allocated is judged, not merely matched",
        OWNED,
        "identifier in self._allocated",
        "False",
        ADAPTER + "test_a_reply_queued_before_its_request_cannot_answer_it",
    ),
    (
        "unavailability is published, not inferred",
        PROVIDER,
        "return self._unavailable",
        "return ()",
        ADAPTER + "test_the_provider_publishes_its_prerequisites_and_refuses_to_acquire",
    ),
    (
        "a published identity that drifts from actual content is refused",
        CONSTRUCTOR,
        "if getattr(identity, field) != expected:",
        "if False:",
        ADAPTER + "test_an_identity_that_drifts_from_the_actual_content_is_refused",
    ),
    (
        "READ refuses a mediated callback catalog",
        CONSTRUCTOR,
        "if not coherent:",
        "if False:",
        ADAPTER + "test_read_profile_refuses_a_write_callback_catalog",
    ),
    # --- N4: the spend readback and the notice allowlist ----------------------
    (
        "N4-1 every account notice but the plan-checked update refuses",
        ACCOUNT_RECORD,
        "if method.startswith((ACCOUNT_NAMESPACE, PROVIDER_NAMESPACE)):",
        "if False:",
        SPEND_TEST
        + "test_every_other_account_or_provider_notice_refuses_naming_only_the_method",
    ),
    (
        "N4-2 a rate-limit update carrying another plan refuses",
        ACCOUNT_RECORD,
        "or expected.accepts(snapshot[PLAN_TYPE_KEY])",
        "or True",
        SPEND_TEST + "test_any_other_rate_limit_update_refuses[other-plan]",
    ),
    (
        "N4-3 a rate-limit update with no plan change passes",
        ACCOUNT_RECORD,
        "            return ()\n        return refused",
        "            return refused\n        return refused",
        SPEND_TEST + "test_a_rate_limit_update_with_no_plan_change_passes",
    ),
    (
        "N4-4 a rate-limit update's params are exactly the pinned key",
        ACCOUNT_RECORD,
        'and set(params) == {"rateLimits"}',
        "",
        SPEND_TEST + "test_any_other_rate_limit_update_refuses[extra-key]",
    ),
    (
        "N4-5 the provider namespace refuses too",
        ACCOUNT_RECORD,
        "(ACCOUNT_NAMESPACE, PROVIDER_NAMESPACE)",
        "(ACCOUNT_NAMESPACE,)",
        STARTUP_TEST + "test_a_provider_auth_recovery_mid_turn_discards_it",
    ),
    # --- the owner's operator_authorized bound (#78, 2026-10-01) ---
    (
        "N4-6 a reached spend control starts no turn",
        SPEND,
        "if reading is not None and reading.spend_control_reached is True:",
        "if False:",
        SPEND_TEST + "test_a_reached_spend_control_starts_no_turn",
    ),
    (
        "N4-7 a malformed spend control is unreadable, never open",
        READING,
        "if stop is not None and type(stop) is not bool:",
        "if False:",
        SPEND_TEST + "test_a_malformed_spend_control_is_unreadable_never_open[string]",
    ),
    (
        "N4-8 no credit state refuses a turn",
        SPEND,
        "faults = readback_faults(reading, expected)",
        "faults = readback_faults(reading, expected) + (\n"
        "        (SPEND_CONTROL_FAULT,) if reading is not None and reading.has_credits else ()\n"
        "    )",
        SPEND_TEST + "test_no_credit_state_refuses_a_turn[purchased]",
    ),
    (
        "N4-9 only a zero decimal is published as zero",
        BALANCE,
        'return set(digits) == {"0"}',
        "return True",
        SPEND_TEST + "test_the_balance_is_published_as_measured_and_malformed_is_unknown[cents]",
    ),
    (
        "N4-9b a malformed balance is published as unknown, not nonzero",
        BALANCE,
        "        return None\n    whole",
        "        return False\n    whole",
        SPEND_TEST + "test_the_balance_is_published_as_measured_and_malformed_is_unknown"
        "[non-string]",
    ),
    (
        "N4-10 an unreadable readback refuses",
        READBACK,
        "        return (SPEND_UNREADABLE_FAULT,)",
        "        return ()",
        SPEND_TEST + "test_an_unreadable_or_unidentified_codex_bucket_refuses",
    ),
    (
        "N4-11 the readback plan is compared",
        READBACK,
        "if reading.plan is not None and not expected.accepts(reading.plan):",
        "if False:",
        SPEND_TEST + "test_another_readback_plan_refuses_and_names_only_a_short_literal",
    ),
    (
        "N4-12 only the bucket naming itself codex is judged",
        READING,
        'or bucket.get("limitId") != CODEX_LIMIT_ID',
        "",
        SPEND_TEST + "test_an_unreadable_or_unidentified_codex_bucket_refuses",
    ),
    (
        "N4-13 the headline bucket is never judged",
        READING,
        'buckets.get(CODEX_LIMIT_ID) if isinstance(buckets, Mapping) else None',
        'result.get("rateLimits") if result is not None else None',
        SPEND_TEST + "test_the_headline_bucket_is_never_the_one_judged",
    ),
    (
        "N4-14 a completed turn is never second-guessed on spend",
        CONVERSE,
        "readback_faults(self.after_spend, self._expected)",
        "spend_faults(self.after_spend, self._expected)",
        STARTUP_TEST + "test_a_turn_that_draws_credits_or_reaches_the_control_is_kept",
    ),
    (
        "N4-15 the pre-turn readback is sent",
        CONVERSE,
        "    readback = await self._request(\n"
        "        io, rate_limits_read_request(self._next_identifier()),\n"
        "    )\n    if readback is None:\n        return\n    self.before_spend",
        "    readback = None\n    self.before_spend",
        STARTUP_TEST + "test_the_startup_phase_sends_exactly_the_four_authorized_methods",
    ),
    (
        "N4-16 a refused pre-turn readback never reaches a thread",
        CONVERSE,
        "    faults = spend_faults(self.before_spend, self._expected)\n"
        "    if faults:\n        self.faults += faults\n        return",
        "    faults = spend_faults(self.before_spend, self._expected)\n"
        "    self.faults += faults",
        STARTUP_TEST + "test_a_refused_pre_turn_readback_never_sends_a_thread",
    ),
    (
        "N4-17 the startup phase stops after its readback",
        CONVERSE,
        "    if self._startup_only:",
        "    if False:",
        STARTUP_TEST + "test_the_startup_phase_sends_exactly_the_four_authorized_methods",
    ),
    (
        "N4-18 the post-turn readback is judged on its bucket and plan",
        CONVERSE,
        "    self.faults += readback_faults(self.after_spend, self._expected)",
        "    pass",
        STARTUP_TEST + "test_a_post_turn_plan_change_discards_the_turn",
    ),
    (
        "N4-19 the published rate limit carries the post-turn reading",
        CALL,
        "rate_limit=rate_limit_of(self.before_spend, self.after_spend)",
        "rate_limit=rate_limit_of(self.before_spend, None)",
        STARTUP_TEST + "test_the_accepting_turn_publishes_both_readbacks_and_no_identity",
    ),
    (
        "N4-20 a startup conversation offers no callbacks",
        CONVERSATION,
        "if startup_only and catalog:",
        "if False:",
        STARTUP_TEST + "test_a_startup_conversation_offers_no_callbacks",
    ),
    (
        "N4-21 only an accepted plan is recorded as observed",
        CONVERSE,
        "    faults = self._judge_account(before, first=True)\n    if faults:",
        "    self.observed_plan = account_plan(before)\n"
        "    faults = self._judge_account(before, first=True)\n    if faults:",
        STARTUP_TEST + "test_qualification_refuses_an_undeclared_plan_and_records_none",
    ),
    # --- the lane review's notice and plan findings (2026-09-24) ---
    (
        "N4-22 the drain to EOF judges id-less records (NOTICE-1, RL-5)",
        AUDIT,
        "self.faults += self._notice_faults(record)",
        "pass",
        STARTUP_TEST + "test_a_refused_notice_after_the_last_reply_is_audited_not_dropped"
        "[account-updated]",
    ),
    (
        "N4-23 a settings update is judged at every site (NOTICE-4)",
        NOTICES,
        "or settings_notice_faults(",
        "or (lambda *args, **kwargs: ())(",
        STARTUP_TEST + "test_a_refused_notice_before_the_readback_refuses_too[settings]",
    ),
    (
        "N4-24 a settings update names the sealed model",
        SETTINGS,
        'and values.get("model") == model and type(values.get("model")) is str',
        "",
        SPEND_TEST + "test_a_settings_update_changing_or_hiding_model_or_provider_refuses[model]",
    ),
    (
        "N4-25 a settings update names the sealed provider",
        SETTINGS,
        'and values.get("modelProvider") == provider',
        "",
        SPEND_TEST + "test_a_settings_update_changing_or_hiding_model_or_provider_refuses"
        "[provider]",
    ),
    (
        "N4-26 a rate-limit update's spend facts are never judged (#78)",
        ACCOUNT_RECORD,
        "expected.accepts(snapshot[PLAN_TYPE_KEY]))",
        "expected.accepts(snapshot[PLAN_TYPE_KEY]))\n"
        '            and snapshot.get("spendControlReached") is not True',
        SPEND_TEST + "test_a_rate_limit_updates_spend_facts_are_never_judged[spend-control]",
    ),
    (
        "N4-29 one run binds one plan literal (SPEND-2, NOTICE-3)",
        CONVERSE,
        "    if self.observed_plan is not None:",
        "    if False:",
        STARTUP_TEST + "test_one_run_binds_one_plan_literal_for_every_later_observation",
    ),
    (
        "N4-30 an id-bearing account record refuses at every site (NOTICE-2)",
        JUDGE,
        "refused = account_request_faults(record)",
        "refused = ()",
        STARTUP_TEST + "test_an_account_request_refuses_wherever_the_chunk_falls",
    ),
    (
        "N4-31 the startup phase refuses any other unowned request",
        JUDGE,
        "if self._startup_only:",
        "if False:",
        STARTUP_TEST + "test_the_startup_phase_refuses_any_other_unowned_request",
    ),
    (
        "N4-32 the startup pause runs before stdin closes (RL-3)",
        CONVERSE,
        "await self._pause()",
        "pass",
        STARTUP_TEST + "test_the_startup_pause_runs_while_the_zone_is_live",
    ),
    (
        "N4-33 only a startup conversation pauses",
        CONVERSATION,
        "if pause is not None and not startup_only:",
        "if False:",
        STARTUP_TEST + "test_only_a_startup_conversation_pauses",
    ),
    (
        "N4-34 the handle hands the conversation its sealed provider",
        BINDING,
        "provider=configured_provider(provider.configuration),",
        "",
        STARTUP_TEST + "test_the_handle_never_runs_the_startup_phase",
    ),
    (
        "N4-35 an absent provider is the pinned default",
        CONFIGURED_PROVIDER,
        '.get("model_provider", OPENAI_PROVIDER)',
        '.get("model_provider", "elsewhere")',
        STARTUP_TEST + "test_the_sealed_provider_is_the_configurations_or_the_pinned_default",
    ),
    (
        "N4-36 the notice fault names no turn (NOTICE-5)",
        ACCOUNT_RECORD,
        "refused = (ACCOUNT_NOTICE_FAULT.format(method=named_method(method)),)",
        'refused = (ACCOUNT_NOTICE_FAULT.format(method=named_method(method)) + " during'
        ' the turn",)',
        SPEND_TEST + "test_the_notice_fault_claims_no_turn",
    ),
    # --- the connector's P1 on #115: a stop report before turn/start ---
    (
        "N4-37 a stop notice before turn/start starts no turn",
        NOTICES,
        "or (() if self._turn_requested else notice_stop_faults(record))",
        "or ()",
        STARTUP_TEST + "test_a_stop_notice_before_turn_start_starts_no_turn"
        "[after_readback-reached]",
    ),
    (
        "N4-38 a started turn is never second-guessed on a stop notice",
        CORRELATE,
        'self._turn_requested = self._turn_requested or method == "turn/start"',
        "pass",
        STARTUP_TEST + "test_a_stop_notice_after_turn_start_is_not_judged",
    ),
    (
        "N4-39 the turn starts at turn/start, not thread/start",
        CORRELATE,
        'self._turn_requested or method == "turn/start"',
        'self._turn_requested or method == "thread/start"',
        STARTUP_TEST + "test_a_stop_notice_before_turn_start_starts_no_turn"
        "[after_thread-reached]",
    ),
    (
        "N4-40 a damaged stop flag in a notice is a report",
        NOTICE_STOP,
        "stop is None or stop is False",
        "stop is not True",
        SPEND_TEST + "test_a_notice_reports_the_spend_control_reached"
        "_unless_null_absent_or_false[string]",
    ),
    # H7: refusal is latched, but a sent reply remains evidence, not a forgery.
    (
        "H7-1 only a successfully sent pending request admits a cleanup reply",
        CORRELATE,
        "self._pending_reply = (identifier, method)",
        "pass",
        "tests/substrate/test_codex_refusal.py::"
        "test_exact_wrong_plan_notice_and_reading_are_affirmative[same-chunk-before]",
    ),
    (
        "H7-2 a pre-send fragment cannot answer during cleanup",
        AUDIT,
        "awaiting = None if pre_send or pending is None else pending[0]",
        "awaiting = None if pending is None else pending[0]",
        "tests/substrate/test_codex_refusal.py::"
        "test_cleanup_cannot_correlate_a_reply_started_before_its_request",
    ),
    (
        "H7-3 cleanup judges the pending account reading",
        AUDIT,
        'pending[1] == "account/read"',
        'pending[1] == "account/rateLimits/read"',
        "tests/substrate/test_codex_refusal.py::"
        "test_exact_wrong_plan_notice_and_reading_are_affirmative[same-chunk-before]",
    ),
    (
        "H7-4 cleanup cannot overwrite the first account identity",
        AUDIT,
        "first=not self._turn_requested",
        "first=True",
        "tests/substrate/test_codex_refusal.py::"
        "test_cleanup_never_overwrites_the_first_readings_identity",
    ),
    (
        "H7-5 only the approved notice vocabulary becomes plan evidence",
        ACCOUNT_RECORD,
        "if plan in QUALIFICATION_PLANS:",
        "if plan is not None:",
        "tests/substrate/test_codex_refusal.py::"
        "test_only_an_exact_approved_notice_can_supply_plan_evidence[unknown-plan]",
    ),
    (
        "H7-6 an exact account notice has no identifier",
        EXACT_UPDATED,
        ' or "id" in record',
        "",
        "tests/substrate/test_codex_refusal.py::"
        "test_an_id_bearing_notice_cannot_supply_exact_plan_evidence",
    ),
    (
        "H7-7 a cleanup reply still has a strictly integer identifier",
        ACCEPT_REPLY,
        'if type(record["id"]) is not int:',
        "if False:",
        "tests/substrate/test_codex_refusal.py::"
        "test_a_pending_reply_still_requires_the_exact_response_contract[float]",
    ),
    (
        "H7-8 a cleanup reply carries exactly one result or error",
        ACCEPT_REPLY,
        'if ("result" in record) == ("error" in record):',
        "if False:",
        "tests/substrate/test_codex_refusal.py::"
        "test_a_pending_reply_still_requires_the_exact_response_contract[neither]",
    ),
    (
        "H7-9 a cleanup reply never admits a native request",
        ACCEPT_REPLY,
        'if "method" in record:',
        "if False:",
        "tests/substrate/test_codex_refusal.py::"
        "test_a_pending_reply_still_requires_the_exact_response_contract[native-request]",
    ),
    (
        "H7-10 cleanup checks the account against every previously accepted notice",
        JUDGE_ACCOUNT,
        "if not faults and self._noticed_plan not in (None, account_plan(reply)):",
        "if False:",
        "tests/substrate/test_codex_refusal.py::"
        "test_cleanup_checks_the_plan_latched_before_the_pending_reading",
    ),
    (
        "H7-11 a pending cleanup reply cannot answer twice",
        ACCEPT_REPLY,
        'self._correlated.add(record["id"])',
        "pass",
        "tests/substrate/test_codex_refusal.py::test_a_pending_account_reply_cannot_answer_twice",
    ),
    *N5_PROTOCOL,
)

LINUX_ONLY: frozenset[str] = frozenset()
"""Empty, and that is the point.

Every mutant here used to need Linux, because the tests that killed them entered
the physical acquisition guard. The adapter tests now substitute *only* the
guard — the handle, provider, conversation and both doubles are the real ones —
so the behaviour those mutants pin is measurable on every host. What stays
Linux-gated is one test of the guard's own physical properties, which pins no
mutant because it pins a property of the OS rather than a decision of ours.

The machinery is kept rather than deleted: it is the honest shape for any future
mutant that genuinely needs a platform, and an unmeasured mutant must never read
as a killed one.
"""

assert len({name for name, *_ in MUTANTS}) == len(MUTANTS), "mutant names must be unique"
assert {name for name, *_ in MUTANTS} >= LINUX_ONLY, "a stale LINUX_ONLY entry"
"""A renamed mutant would otherwise shrink the reported UNMEASURED count
silently, which is the one direction this script must never fail quietly."""
"""Names are the identity used for filtering and for reporting, so a duplicate
would silently drop one copy from the unmeasured list."""

# Built from the platform alone, so the parent and each child process agree on
# the indices the runner passes between them.
SELECTED = tuple(
    mutant for mutant in MUTANTS
    if sys.platform == "linux" or mutant[0] not in LINUX_ONLY
)
UNMEASURED = tuple(name for name, *_ in MUTANTS if name in LINUX_ONLY) if (
    sys.platform != "linux"
) else ()

if __name__ == "__main__":
    status = run(SELECTED)
    if len(sys.argv) == 1:
        for name in UNMEASURED:
            print(f"UNMEASURED (requires Linux): {name}", flush=True)
        if status == 0:
            print(
                f"{len(SELECTED)}/{len(SELECTED)} mutants KILLED by assertion; "
                f"{len(UNMEASURED)} UNMEASURED."
            )
    raise SystemExit(status)
