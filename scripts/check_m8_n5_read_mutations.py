"""M8 N5 Stage 3, the read stage: one mutant per check; each must fail an assertion.

Portable: every target runs over the adapter suite's scripted native client.
"""

from _mutations import run

AUTH = "constructicon.core.qualification:QualificationAuthorization."
CODEX = "constructicon.substrate.executors.codex:"
HANDLE = CODEX + "CodexOperatorHandle."
RECORD = "constructicon.substrate.executors.attempt_record:AttemptRecord."
ENTRY = "constructicon.api.qualification:"
CORE_TEST = "tests/core/test_qualification.py::"
READ_TEST = "tests/substrate/test_codex_read_stage.py::"
ENTRY_TEST = "tests/api/test_qualification_entry.py::"
EXPIRED = READ_TEST + "test_an_authorization_expired_before_the_turn_dispatches_nothing"
COMPLETED = READ_TEST + "test_one_read_turn_completes_and_its_record_says_so"
SENT = 'self.turn_sent = self.turn_sent or value.get("method") == "turn/start"'

MUTANTS = (
    ("a read authorization pins its grants, record and one epoch",
     AUTH + "_stage_shape",
     "if self.grants is None or not self.attempt_record or self.max_epoch != 1:", "if False:",
     CORE_TEST + "test_a_read_authorization_missing_any_pin_is_refused"),
    ("a no-dispatch authorization pins neither",
     AUTH + "_stage_shape",
     "elif self.grants is not None or self.attempt_record is not None:", "elif False:",
     CORE_TEST + "test_a_no_dispatch_authorization_pins_neither"),
    ("a read acquisition runs under the pinned grants",
     AUTH + "acquisition_faults",
     '(pinned, "other grants"),', '(True, "other grants"),',
     CORE_TEST + "test_a_read_acquisition_under_other_grants_is_refused"),
    ("a read acquisition reserves the one attempt",
     CODEX + "CodexOperatorProvider.acquire",
     "if qualification is not None and qualification.attempt_record is not None:", "if False:",
     READ_TEST + "test_the_spent_attempt_refuses_every_later_acquisition"),
    ("a read acquisition may dispatch",
     CODEX + "CodexOperatorProvider.acquire",
     "dispatch=qualification is None or qualification.dispatches,",
     "dispatch=qualification is None,",
     READ_TEST + "test_a_read_acquisition_dispatches_and_holds_its_reserved_record"),
    ("the record's create is exclusive",
     RECORD + "_write", "os.O_CREAT | os.O_EXCL |", "os.O_CREAT |",
     READ_TEST + "test_the_record_moves_through_its_three_phases_and_reserves_once"),
    ("a short write is completed before it is synced",
     RECORD + "_write", "pending = pending[written:]", "pending = pending[len(pending):]",
     READ_TEST + "test_a_short_write_is_completed_never_published_truncated"),
    ("a write without progress refuses",
     RECORD + "_write", "if written <= 0:", "if False:",
     READ_TEST + "test_a_write_without_progress_refuses_rather_than_retrying"),
    ("an intent that cannot be recorded refuses rather than raising",
     RECORD + "intend", "except OSError as exc:", "except ZeroDivisionError as exc:",
     READ_TEST + "test_an_intent_that_cannot_be_recorded_is_a_refusal_not_a_raise"),
    ("the turn's last word is asked before turn/start",
     CODEX + "CodexConversation._request",
     'if method == "turn/start" and self._before_turn is not None and (', "if False and (",
     EXPIRED),
    ("a read turn is gated by its intent",
     HANDLE + "_converse",
     "before_turn=self._intend if self.attempt is not None else None,", "before_turn=None,",
     EXPIRED),
    ("an authorization expired before the turn refuses it",
     HANDLE + "_expired",
     "if qualification is not None and datetime.now(UTC) >= qualification.not_after:",
     "if False:", EXPIRED),
    ("expiry is checked again after the intent is durable",
     HANDLE + "_intend",
     "return self._expired() or self.attempt.intend() or self._expired()",
     "return self._expired() or self.attempt.intend()",
     READ_TEST
     + "test_an_authorization_that_expires_while_its_intent_is_written_dispatches_nothing"),
    ("a turn whose write began counts as sent",
     CODEX + "CodexConversation._send", SENT, "pass", COMPLETED),
    ("a turn refused before its write began is not sent",
     CODEX + "CodexConversation._send",
     "if self._spent + len(raw) > self._input_limit:",
     SENT + "\n    if self._spent + len(raw) > self._input_limit:",
     READ_TEST + "test_a_turn_refused_after_its_intent_is_proven_not_dispatched"),
    ("a turn counts as sent as its write begins, not when it returns",
     CODEX + "CodexConversation._send",
     SENT + "\n    try:\n        await io.write(raw)\n",
     "try:\n        await io.write(raw)\n        " + SENT + "\n",
     READ_TEST + "test_a_turn_whose_write_began_and_then_failed_is_possibly_dispatched"),
    ("only an accepted answer is completed",
     HANDLE + "_settle_attempt",
     'else "completed" if isinstance(outcome, ExecutorSuccess)', 'else "completed" if True',
     READ_TEST + "test_a_failure_after_the_turn_was_written_is_possibly_dispatched"),
    ("the answer's length is the decoded answer's",
     HANDLE + "_attempt_facts",
     "answer = outcome.output if isinstance(outcome, ExecutorSuccess) else None",
     "answer = outcome.raw_reply if isinstance(outcome, ExecutorSuccess) else None",
     COMPLETED),
    ("a refused turn keeps its readbacks",
     HANDLE + "_attempt_facts",
     "readbacks = None if conversation is None else rate_limit_of(",
     "readbacks = None if True else rate_limit_of(",
     READ_TEST + "test_a_refused_turn_keeps_what_the_conversation_observed"),
    ("a refused turn keeps its reason",
     HANDLE + "_attempt_facts",
     "if isinstance(outcome, ExecutorFailure) else None", "if False else None",
     READ_TEST + "test_a_refused_turn_keeps_what_the_conversation_observed"),
    ("a clean result from a failed exchange is no answer",
     HANDLE + "_converse",
     "if exchange_failed and isinstance(outcome, ExecutorSuccess):", "if False:",
     READ_TEST + "test_a_clean_result_salvaged_from_a_failed_exchange_is_refused"),
    ("the read node reports only an accepted text answer",
     ENTRY + "qualification_read_node",
     "if not isinstance(outcome, ExecutorSuccess) or not isinstance(answer, str) or not answer:",
     "if False:",
     ENTRY_TEST + "test_the_read_node_reports_only_an_accepted_text_answer[salvaged-failure]"),
    ("the entry requires an absolute attempt record",
     ENTRY + "_require_coherent",
     'or (authorization.dispatches and not Path(authorization.attempt_record or "").is_absolute())',
     "",
     ENTRY_TEST + "test_a_read_authorization_with_a_relative_record_is_not_this_qualification"),
    ("mint requires the record exactly for the read stage",
     ENTRY + "main",
     'if (arguments.stage == "qualification-read") != (arguments.attempt_record is not None):',
     "if False:",
     ENTRY_TEST + "test_mint_requires_the_record_exactly_for_the_read_stage"),
)

if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
