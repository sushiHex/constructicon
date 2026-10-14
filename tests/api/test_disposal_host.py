"""Disposal advances accounting, never process-local execution intent."""

from __future__ import annotations

from constructicon.core.control import RunSubmission
from constructicon.core.run import RunStatus
from tests.api.test_capability_disposal import ADMIN, disposal_world, dispose


async def test_disposal_keeps_cleanup_deferred_host_without_scheduling(tmp_path):
    async with disposal_world(tmp_path) as world:
        deferred = set(world.host._deferred)
        response = await dispose(world)
        assert response.status == "disposed"
        assert world.host._deferred == deferred
        assert world.host._requested == {}
        assert world.host._tasks == {}
        assert world.executions == []


async def test_disposal_drops_queued_resume_fence_without_rejecting_committed_submission(
    tmp_path, monkeypatch,
):
    async with disposal_world(tmp_path) as world:
        submission = await world.control.runs_resume(
            ADMIN, run_id=world.run_id, idempotency_key="queued-before-disposal",
        )
        assert isinstance(submission, RunSubmission)
        assert world.run_id in world.host._requested
        assert world.run_id not in world.host._deferred
        baseline = world.journal.max_event_seq(world.run_id)
        response = await dispose(world)
        assert response.status == "disposed"
        assert world.journal.max_event_seq(world.run_id) == baseline + 3
        # Observe the pump's decision synchronously before a worker can claim:
        # stale explicit intent is dropped and ordinary recovery is selected.
        selected = []
        monkeypatch.setattr(world.host, "_start", lambda run_id, **kwargs:
                            selected.append((run_id, kwargs)))
        world.host._fill_capacity()
        assert world.run_id not in world.host._requested
        assert len(selected) == 1 and selected[0][0] == world.run_id
        assert selected[0][1]["explicit"] is False
        assert selected[0][1]["intent"].cause is None
        assert selected[0][1]["intent"].expected_event_seq == baseline + 3
        assert world.executions == []
        command = world.journal.command(submission.command.command_id)
        assert command.state == "committed"
        replay = await world.control.runs_resume(
            ADMIN, run_id=world.run_id, idempotency_key="queued-before-disposal",
        )
        assert isinstance(replay, RunSubmission) and replay.command.replayed
        assert world.run_id not in world.host._requested
        assert world.journal.run_head(world.run_id).record.status is RunStatus.RUNNING
        # Keep automatic recovery deferred while this fixture shuts down. The
        # explicit resume deliberately cleared it before disposal, not disposal.
        world.host._deferred.add(world.run_id)
