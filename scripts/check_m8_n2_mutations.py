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
SPEND_CHANGE = "constructicon.substrate.executors.codex_protocol:spend_change_faults"
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
TURN_OF = "constructicon.substrate.executors.codex_protocol:_turn_of"
CONFIGURED = "constructicon.substrate.executors.codex:configured_model"
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
        "self.faults += account_faults(after, self._expected)",
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
        CORRELATE,
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
        "if conversation.faults:",
        "if False:",
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
        "await handle.cleanup(disposition)",
        "handle.closed = True",
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
        "if type(item) is int and len(repr(item)) <= NUMBER_CHARS",
        "if type(item) is int",
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
        CONFIGURED,
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
        'self._judge_identified(line, record, context="the drain to EOF")',
        "pass",
        ADAPTER + "test_a_duplicate_reply_id_is_refused_even_during_the_drain_to_eof",
    ),
    (
        "a correlated id is remembered",
        CORRELATE,
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
    (
        "N4-6 purchased credits refuse",
        SPEND,
        "reading.has_credits is False and ",
        "",
        SPEND_TEST + "test_anything_but_proven_zero_credits_refuses[has-credits]",
    ),
    (
        "N4-7 unlimited credits refuse",
        SPEND,
        "reading.unlimited is False\n        and ",
        "",
        SPEND_TEST + "test_anything_but_proven_zero_credits_refuses[unlimited]",
    ),
    (
        "N4-8 a non-zero balance refuses",
        SPEND,
        "and reading.balance_zero is not False",
        "",
        SPEND_TEST + "test_anything_but_proven_zero_credits_refuses[cents]",
    ),
    (
        "N4-9 only a zero decimal is zero",
        BALANCE,
        'return set(digits) == {"0"}',
        "return True",
        SPEND_TEST + "test_anything_but_proven_zero_credits_refuses[negative]",
    ),
    (
        "N4-10 an unreadable readback refuses",
        SPEND,
        "        return (SPEND_UNREADABLE_FAULT,)",
        "        return ()",
        SPEND_TEST + "test_an_unreadable_or_unidentified_codex_bucket_refuses",
    ),
    (
        "N4-11 the readback plan is compared",
        SPEND,
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
        "N4-14 a moved overage field refuses",
        SPEND_CHANGE,
        "if getattr(before, name) != getattr(after, name)",
        "if False",
        SPEND_TEST + "test_each_overage_field_that_moves_across_the_turn_refuses",
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
        "N4-18 the post-turn readback is judged against its baseline",
        CONVERSE,
        "    self.faults += spend_change_faults(self.before_spend, self.after_spend)",
        "    pass",
        STARTUP_TEST + "test_a_post_turn_overage_change_discards_the_turn",
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
        "    faults = account_faults(before, self._expected)\n    if faults:",
        "    self.observed_plan = account_plan(before)\n"
        "    faults = account_faults(before, self._expected)\n    if faults:",
        STARTUP_TEST + "test_qualification_refuses_an_undeclared_plan_and_records_none",
    ),
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
