"""M8 N5 Stage 3, the read stage: one mutant per check; each must fail an assertion.

Portable: every target runs over the adapter suite's scripted native client.
Two checks have none, because removing either changes only how a refusal fails,
which the harness counts as an error rather than a kill:
- without the catch in `AttemptRecord.intend`, an unrecordable intent raises
  instead of refusing; its test proves it refuses;
- without the read node's success check, a failed turn has no reply to measure,
  so the node still fails.
"""

from _mutations import run

AUTH = "constructicon.core.qualification:QualificationAuthorization."
CODEX = "constructicon.substrate.executors.codex:"
HANDLE = CODEX + "CodexOperatorHandle."
ENTRY = "constructicon.api.qualification:"
CORE_TEST = "tests/core/test_qualification.py::"
READ_TEST = "tests/substrate/test_codex_read_stage.py::"
ENTRY_TEST = "tests/api/test_qualification_entry.py::"
EXPIRED = READ_TEST + "test_an_authorization_expired_before_the_turn_dispatches_nothing"

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
     "constructicon.substrate.executors.attempt_record:AttemptRecord._write",
     "os.O_CREAT | os.O_EXCL |", "os.O_CREAT |",
     READ_TEST + "test_the_record_moves_through_its_three_phases_and_reserves_once"),
    ("the turn's last word is asked before turn/start",
     CODEX + "CodexConversation._request",
     'if method == "turn/start" and self._before_turn is not None and (', "if False and (",
     EXPIRED),
    ("a read turn is gated by its intent",
     HANDLE + "_converse",
     "before_turn=self._intend if self.attempt is not None else None,", "before_turn=None,",
     EXPIRED),
    ("an authorization expired before the turn refuses it",
     HANDLE + "_intend",
     "if qualification is not None and datetime.now(UTC) >= qualification.not_after:",
     "if False:", EXPIRED),
    ("the turn counts as written only once it was",
     CODEX + "CodexConversation._request",
     'self._turn_requested = self._turn_requested or method == "turn/start"',
     'self._turn_requested = self._turn_requested or method == "turn/start"; '
     "self.turn_written = self._turn_requested",
     READ_TEST + "test_a_turn_refused_after_its_intent_is_proven_not_dispatched"),
    ("only an accepted answer is completed",
     HANDLE + "_settle_attempt",
     'else "completed" if isinstance(outcome, ExecutorSuccess)', 'else "completed" if True',
     READ_TEST + "test_a_failure_after_the_turn_was_written_is_possibly_dispatched"),
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
