"""Installed local M9 catalog selection and scripted evaluation; never prompt-quality proof."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
from datetime import timedelta
from pathlib import Path

from pydantic import ValidationError

from constructicon.api._m9 import proposer
from constructicon.api._m9.evaluator import REGISTRAR, Evaluator, wait_deadline
from constructicon.api._m9.evidence import TrialIdentity
from constructicon.api._m9.refusal import TrialRefused, TrialWaitTimeout, check_control
from constructicon.api._m9.safety import before_startup, selector_run
from constructicon.api._m9.trial import _open, run
from constructicon.api.control import ControlPlane
from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.control import RegistrationCommandResult, RunSubmission
from constructicon.core.envelope import utc_now
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.core.identity import digest, json_value
from constructicon.core.manifest import source_graph_hash_for
from constructicon.core.qualification import QualificationAuthorization
from constructicon.core.run import RunStatus
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.sdk.types import DefinitionBundle
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.executors.codex import CodexOperatorProvider
from constructicon.substrate.executors.codex_host import READ_GRANTS, HostSession, operator_provider
from constructicon.substrate.executors.qualification import read_authorization
from constructicon.substrate.journal.sqlite import SqliteJournal


async def seed(root: Path, trial: TrialIdentity) -> dict[str, object]:
    journal = _open(root, trial, initialize=True)
    evaluator = Evaluator.assemble(journal, initialize=True)
    await evaluator.prepare(trial, retained=False, seed_only=True)
    return {"status": "seeded", "source": proposer.SOURCE,
            "input": digest("inputs", 1, {"training": proposer.training()}),
            "task": digest("m9-selector-task", 1, proposer.task().model_dump(mode="json"))}


def check_authorization(
    journal: SqliteJournal, root: Path, trial: TrialIdentity,
    authorization: QualificationAuthorization, provider: CodexOperatorProvider,
) -> None:
    expected_journal = root / "journal.sqlite"
    if (authorization.stage != "qualification-read"
            or authorization.actor_id != proposer.ACTOR.actor_id
            or authorization.idempotency_key != trial.key("select")
            or authorization.run_id != selector_run(trial)
            or authorization.scope != proposer.PATH.scope or authorization.binding != "executor"
            or authorization.capability_id != proposer.CAPABILITY
            or authorization.source_graph_hash != source_graph_hash_for(proposer.graph())
            or authorization.revision != provider.identity.revision
            or authorization.operator_binding_digest
            != provider.identity.store.operator_binding_digest
            or authorization.grants != READ_GRANTS or authorization.max_epoch != 1
            or provider.qualification != authorization
            or not expected_journal.is_absolute()
            or str(expected_journal.resolve()) != authorization.journal
            or not authorization.attempt_record
            or not Path(authorization.attempt_record).is_absolute()
            or Path(authorization.attempt_record).resolve() != Path(authorization.attempt_record)):
        raise ValueError("M9_SELECTOR_AUTHORIZATION_MISMATCH")
    before_startup(journal, trial, role="select")
    # Affirm the seed through committed commands and all existing evidence
    # predicates before an executor can be acquired, without starting workers.
    if journal.snapshot().stable_version("test/m9-diagnostic") is None:
        raise ValueError("M9_SELECTOR_MISSING_SEED")


async def execute_selection(
    root: Path, trial: TrialIdentity, provider: CodexOperatorProvider,
) -> dict[str, object]:
    """Trusted composition seam; the CLI constructs only the existing host provider."""
    journal = _open(root, trial, initialize=False)
    run_id = RunId(selector_run(trial))
    if journal.run_record(run_id) is not None:
        return selection_result(journal, run_id, replayed=True)
    authorization = provider.qualification
    if authorization is None:
        raise ValueError("M9_SELECTOR_REQUIRES_OWNER_AUTHORIZATION")
    check_authorization(journal, root, trial, authorization, provider)
    if os.path.lexists(authorization.attempt_record or ""):
        raise ValueError("M9_SELECTOR_SPENT_ATTEMPT_NO_RETRY")
    evaluator = Evaluator.assemble(journal)
    await evaluator.prepare(trial, retained=True, seed_only=True)
    system = Constructicon(
        journal=journal, root_grants=READ_GRANTS,
        capabilities={proposer.CAPABILITY: provider},
        catalog={proposer.CAPABILITY: CapabilityDescriptor(
            capability_id=proposer.CAPABILITY, kind="executor", leased=True,
            revision=provider.identity.revision, executor_profile=provider.profile,
        )},
    )
    definition = proposer.definition()
    control = ControlPlane(system=system, store=journal)
    before_startup(journal, trial, role="select")
    try:
        await control.startup()
        registered = await control.registry_register(
            REGISTRAR, definition=DefinitionBundle(definition, proposer.select),
            idempotency_key=trial.key("selector-register"),
        )
        check_control(registered, "selector-register")
        if (not isinstance(registered, RegistrationCommandResult)
                or registered.version != definition.content_hash()):
            raise TrialRefused("selector-register", "M9_UNEXPECTED_CONTROL_RESULT")
        submission = await control.runs_start(
            proposer.ACTOR, proposal=proposer.graph(),
            inputs={"training": proposer.training()}, idempotency_key=trial.key("select"),
        )
        check_control(submission, "select")
        if not isinstance(submission, RunSubmission) or submission.run_id != run_id:
            raise TrialRefused("select", "M9_UNEXPECTED_CONTROL_RESULT")
        async with wait_deadline(
            journal, run_id, "select", timeout_s=READ_GRANTS.timeout_s + 60,
        ):
            while True:
                record = journal.run_record(run_id)
                if record is None:
                    raise ValueError("M9_SELECTOR_MISSING_RUN")
                if record.status not in (RunStatus.PENDING, RunStatus.RUNNING):
                    break
                await asyncio.sleep(0.01)
    finally:
        await finish_owned(asyncio.create_task(control.shutdown()))
    return selection_result(journal, run_id, replayed=False)


def selection_result(journal: SqliteJournal, run: RunId, *, replayed: bool) -> dict[str, object]:
    observed = proposer.retained(journal, run)
    return {"status": "baseline-no-promotion" if observed.choice == "baseline" else "selected",
            "run": run, "observation": observed.model_dump(mode="json"), "replayed": replayed,
            "evaluation": "scripted-diagnostic-exam"}


def _provider(options: argparse.Namespace,
              authorization: QualificationAuthorization | None = None) -> CodexOperatorProvider:
    if any(getattr(options, name, None) is None for name in (
        "session", "store_key", "sealed", "qualification", "state",
    )):
        raise ValueError("M9_SELECTOR_HOST_METADATA_ARGUMENTS_REQUIRED")
    return operator_provider(HostSession(
        session=options.session, store_key=options.store_key, sealed=options.sealed,
        qualification=options.qualification, state=options.state,
    ), authorization)


def pins(options: argparse.Namespace, trial: TrialIdentity) -> dict[str, object]:
    journal = _open(options.store, trial, initialize=False)
    before_startup(journal, trial, role="select")
    provider = _provider(options)
    return {"source": proposer.SOURCE,
            "task": digest("m9-selector-task", 1, proposer.task().model_dump(mode="json")),
            "input": digest("inputs", 1, {"training": proposer.training()}),
            "source_graph": source_graph_hash_for(proposer.graph()),
            "component": proposer.definition().content_hash(),
            "provider_revision": provider.identity.revision,
            "operator_binding_digest": provider.identity.store.operator_binding_digest,
            "grants": READ_GRANTS.model_dump(mode="json"),
            "run": selector_run(trial), "actor": proposer.ACTOR.actor_id,
            "key": trial.key("select"), "evaluation": "scripted-diagnostic-exam"}


def mint(options: argparse.Namespace, trial: TrialIdentity) -> QualificationAuthorization:
    """Print a candidate; only existing root-custody read_authorization grants authority."""
    if (not isinstance(options.authorization_id, str)
            or not 0 < len(options.authorization_id) <= 128
            or not isinstance(options.attempt_record, Path)
            or not options.attempt_record.is_absolute()
            or options.attempt_record.resolve() != options.attempt_record
            or os.path.lexists(options.attempt_record)):
        raise ValueError("M9_SELECTOR_AUTHORIZATION_INPUT_INVALID")
    metadata = pins(options, trial)
    return QualificationAuthorization(
        authorization_id=options.authorization_id, stage="qualification-read",
        actor_id=proposer.ACTOR.actor_id, idempotency_key=trial.key("select"),
        scope=proposer.PATH.scope, binding="executor",
        source_graph_hash=source_graph_hash_for(proposer.graph()),
        capability_id=proposer.CAPABILITY,
        revision=str(metadata["provider_revision"]),
        operator_binding_digest=metadata["operator_binding_digest"],
        journal=str((options.store / "journal.sqlite").resolve()), max_epoch=1,
        not_after=utc_now() + timedelta(hours=1), grants=READ_GRANTS,
        attempt_record=str(options.attempt_record),
    )


async def dispatch(options: argparse.Namespace) -> dict[str, object]:
    trial = TrialIdentity(options.trial)
    if options.stage == "seed":
        return await seed(options.store, trial)
    if options.stage == "rehearse":
        return await run(options.store, trial, "prepare")
    journal = _open(options.store, trial, initialize=False)
    if options.stage == "pins":
        return pins(options, trial)
    if options.stage == "mint":
        return mint(options, trial).model_dump(mode="json")
    run_id = RunId(selector_run(trial))
    if options.stage == "propose":
        # This branch deliberately precedes host-provider construction and
        # authorization-file reading. Replay cannot reacquire model authority.
        if journal.run_record(run_id) is not None:
            return selection_result(journal, run_id, replayed=True)
        if options.authorization is None:
            raise ValueError("M9_SELECTOR_REQUIRES_OWNER_AUTHORIZATION")
        authorization = read_authorization(options.authorization)
        return await execute_selection(options.store, trial, _provider(options, authorization))
    selected = journal.run_record(run_id)
    if selected is not None:
        observed = proposer.retained(journal, run_id)
        if observed.choice == "baseline":
            return selection_result(journal, run_id, replayed=True)
    if options.stage == "prepare" and selected is None:
        raise ValueError("M9_SELECTOR_REQUIRES_COMPLETED_SELECTION")
    return await run(options.store, trial, options.stage,
                     selection=run_id if selected is not None else None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("stage", choices=(
        "rehearse", "seed", "pins", "mint", "propose", "prepare", "approve", "reject",
        "promote", "rollback",
    ))
    parser.add_argument("--trial", required=True)
    parser.add_argument("--store", required=True, type=Path)
    for name in ("session", "sealed", "qualification", "state", "authorization", "attempt-record"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--store-key")
    parser.add_argument("--authorization-id")
    options = parser.parse_args(argv)
    def stopped(code: str, details: dict[str, object] | None = None) -> None:
        body = {"status": "refused", "stage": options.stage, "code": code}
        if details is not None:
            body.update(details)
        body["operation"] = options.stage
        parser.exit(1, "M9 trial stopped: " + json.dumps(json_value(body), sort_keys=True) + "\n")

    try:
        result = asyncio.run(dispatch(options))
    except TrialRefused as error:
        stopped(error.code, error.projection())
    except TrialWaitTimeout as error:
        stopped("M9_WAIT_TIMEOUT", error.projection())
    except JournalDamaged:
        stopped("M9_JOURNAL_DAMAGED")
    except sqlite3.DatabaseError:
        stopped("M9_JOURNAL_UNAVAILABLE")
    except ValidationError:
        stopped("M9_TRIAL_INVALID_RETAINED_DATA")
    except TypeError:
        stopped("M9_TRIAL_INVALID_TYPE")
    except TimeoutError:
        stopped("M9_WAIT_BODY_TIMEOUT")
    except OSError:
        stopped("M9_TRIAL_LOCAL_IO_UNAVAILABLE")
    except (ValueError, ContractViolation) as error:
        stopped(refusal_code(error))
    print(json.dumps(json_value(result), sort_keys=True))
    return 0


_REFUSALS = frozenset({
    "M9_SELECTOR_AUTHORIZATION_INPUT_INVALID", "M9_SELECTOR_AUTHORIZATION_MISMATCH",
    "M9_SELECTOR_MISSING_SEED", "M9_SELECTOR_REQUIRES_OWNER_AUTHORIZATION",
    "M9_SELECTOR_SPENT_ATTEMPT_NO_RETRY", "M9_SELECTOR_ADMISSION_REFUSED",
    "M9_SELECTOR_REGISTRATION_REFUSED",
    "M9_SELECTOR_MISSING_RUN", "M9_SELECTOR_HOST_METADATA_ARGUMENTS_REQUIRED",
    "M9_SELECTOR_REQUIRES_COMPLETED_SELECTION", "M9_SELECTOR_BASELINE_NO_PROMOTION",
    "M9_SELECTOR_INCOMPLETE_PRESERVE_STORE_NO_RETRY", "M9_SELECTOR_SOURCE_UNAVAILABLE",
    "M9_SELECTOR_INVALID_OBSERVATION", "M9_SELECTOR_OBSERVATION_TYPE",
    "M9_SELECTOR_SOURCE_INVENTORY_INVALID", "M9_OWNER_REJECTION_TERMINATION_MISMATCH",
    "M9_SELECTOR_SOURCE_OR_PROVIDER_UNAVAILABLE", "M9_SELECTOR_INVALID_CHOICE",
    "M9_SELECTOR_CONTRACT_REFUSED",
    "M9_SELECTOR_INPUT_OR_SOURCE_DRIFT", "M9_SELECTOR_REQUIRES_CODEX_READ",
    "M9_SELECTOR_PROVIDER_OR_GRANT_DRIFT", "M9_SELECTOR_INVALID_OUTCOME",
    "M9_SELECTOR_COMPLETION_DRIFT", "M9_SELECTOR_TRAINING_SEAL_MISMATCH",
    "M9_SELECTOR_RETAINED_IDENTITY_MISMATCH", "M9_SELECTOR_RETAINED_IMPLEMENTATION_MISMATCH",
    "M9_SELECTOR_RETAINED_ENVELOPE_MISMATCH", "M9_SELECTOR_RETAINED_OBSERVATION_MISMATCH",
    "M9_SELECTOR_LINEAGE_MANIFEST_MISMATCH", "M9_SELECTOR_RUN_IDENTITY_MISMATCH",
    "M9_STARTUP_RUN_INVENTORY_EXCEEDED", "M9_STARTUP_UNALLOWLISTED_RUN",
    "M9_STARTUP_ISSUANCE_ASSEMBLY_REQUIRED", "M9_STARTUP_UNKNOWN_ASSEMBLY",
    "M9_SELECTOR_NONPREPARATION_RUN",
    "M9_STARTUP_RUN_GRAPH_DRIFT", "M9_SELECTOR_REQUIRES_COMPLETED_PREPARATION",
})


def refusal_code(error: Exception) -> str:
    """One closed public refusal boundary; exception text is never a transcript."""
    message = str(error)
    if message in _REFUSALS:
        return message
    if message.startswith("M9_STORE_SOURCE_OR_IDENTITY_DRIFT:"):
        return "M9_STORE_SOURCE_OR_IDENTITY_DRIFT"
    return "M9_TRIAL_REFUSED"


if __name__ == "__main__":
    raise SystemExit(main())
