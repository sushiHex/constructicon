"""Exercise the standing owner approval record, its two check points and custody."""

import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from scripts.ops import m9_owner_approval as approval
from scripts.ops.claude_read_commands import sha
from scripts.ops.claude_read_session import json_bytes
from scripts.ops.m9_owner_approval import StandingApproval

from constructicon.api import change_review_advice as route
from constructicon.substrate.executors.codex_host import READ_GRANTS

NOW = datetime(2026, 11, 17, 12, tzinfo=UTC)
NOT_AFTER = NOW + timedelta(days=7)
HOLDER = "f" * 32


def forbid_supervisor_sleep(monkeypatch):
    """No supervisor step may wait for a human.

    Only the supervisor modules' own ``time`` is replaced, never the global
    module: on POSIX ``subprocess`` polls with ``time.sleep``, and the adapter's
    own subprocesses must keep the real one.
    """
    import time
    import types

    from scripts.ops import m9_native_read, m9_read_window

    def no_human_wait(_seconds):
        pytest.fail("no window step waits for a human")

    proxy = types.SimpleNamespace(
        **{name: getattr(time, name) for name in dir(time) if not name.startswith("__")},
    )
    proxy.sleep = no_human_wait
    for module in (m9_read_window, m9_native_read):
        monkeypatch.setattr(module, "time", proxy)


def view(**overrides):
    """A ``selected_pins`` view, and the packet's shape for check point (b)."""
    instruction = "fixture instruction\n" * 4
    pins = {
        "source_graph": "sha256:" + "1" * 64,
        "component": "sha256:" + "2" * 64,
        "guard": "sha256:" + "3" * 64,
        "capability": route.CAPABILITY,
        "actor": route.ACTOR_ID,
        "scope": "/".join(route.SCOPE.segments),
        "grants": READ_GRANTS.model_dump(mode="json"),
        "instruction": instruction,
        "instruction_bytes": len(instruction.encode("utf-8")),
        "instruction_digest": "sha256:" + "4" * 64,
    }
    pins.update(overrides.pop("pins", {}))
    return {
        "consumer": "change-review-advice",
        "controller": "0" * 40,
        "runtime": "sha256:" + "5" * 64,
        "alias": "fixture",
        "pins": pins,
        **overrides,
    }


def record_bytes(selected=None, *, not_after=NOT_AFTER, max_runs=3, changes=None):
    raw = approval.issue(selected or view(), not_after=not_after, max_runs=max_runs)
    if not changes:
        return raw
    record = {**json.loads(raw), **changes}
    return json_bytes({key: value for key, value in record.items() if value is not None})


def placed(work, raw=None, name="standing-approval.json"):
    raw = record_bytes() if raw is None else raw
    (work / name).write_bytes(raw)
    return StandingApproval.load(work / name, sha(raw), work)


def admitted(work, standing):
    """Write the admission marker exactly as the window does."""
    standing.suspension(work).write_bytes(HOLDER.encode("ascii"))


class AnySelection(StandingApproval):
    """The real record, slots and suspension, admitting every selection.

    Only for supervisor and transport regressions whose subject is not the
    approval's field fit (for example the M9 transport, which can never hold
    a real standing record).
    """

    def _fit(self, consumer, packet):
        return None


def any_selection(work, *, not_after=None):
    """Placed in ``work`` like a real record: both check points re-read its file."""
    if not_after is None:  # the supervisor reads the real clock
        not_after = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)
    raw = record_bytes(not_after=not_after)
    path = work / "standing-approval.json"
    path.write_bytes(raw)
    return AnySelection(raw, sha(raw), json.loads(raw), not_after, path)


# --- the accepting path -----------------------------------------------------------


def test_an_issued_record_admits_its_selection_and_confirms_its_packet(tmp_path):
    standing = placed(tmp_path)
    assert standing.sha256 == sha((tmp_path / "standing-approval.json").read_bytes())
    assert standing.max_runs == 3 and standing.not_after == NOT_AFTER
    assert set(json.loads(standing.raw)) == approval.KEYS
    assert standing.admit(view(), tmp_path, NOW) is None
    admitted(tmp_path, standing)
    assert standing.confirm("change-review-advice", json_bytes(view()), tmp_path, NOW,
                            HOLDER) is None


def test_the_instruction_class_admits_any_instruction_within_its_bound(tmp_path):
    standing = placed(tmp_path)
    admitted(tmp_path, standing)
    for text in ("a", "\N{SNOWMAN}" * 100, "x" * route.INSTRUCTION_MAX_BYTES):
        packet = view(pins={"instruction": text, "instruction_bytes": len(text.encode()),
                            "instruction_digest": "sha256:" + "9" * 64})
        assert standing.confirm("change-review-advice", json_bytes(packet), tmp_path, NOW,
                                HOLDER) is None


# --- refusals, each naming its field ------------------------------------------------


@pytest.mark.parametrize("field", [
    "consumer", "controller", "runtime", "host_key_alias", *approval.PINNED,
    "instruction_max_bytes",
])
def test_each_fixed_field_mismatch_refuses_by_name_at_both_check_points(tmp_path, field):
    standing = placed(tmp_path)
    other = view()
    if field == "consumer":
        other["consumer"] = "m9"
    elif field == "host_key_alias":
        other["alias"] = "another-host-key"
    elif field in ("controller", "runtime"):
        other[field] = "1" * 40 if field == "controller" else "sha256:" + "6" * 64
    elif field == "grants":
        other["pins"]["grants"] = {**other["pins"]["grants"], "timeout_s": 121}
    elif field == "instruction_max_bytes":
        # The fixture instruction is 80 bytes: one byte over this class's bound.
        small = record_bytes(changes={"instruction_max_bytes": 79})
        standing = placed(tmp_path, small, "small.json")
    else:
        other["pins"][field] = "sha256:" + "7" * 64
    code = "approval-" + field
    assert standing.admit(other, tmp_path, NOW) == code
    admitted(tmp_path, standing)
    assert standing.confirm(other["consumer"], json_bytes(other), tmp_path, NOW, HOLDER) == code


@pytest.mark.parametrize("key", approval.FORBIDDEN)
def test_a_fresh_per_window_key_is_forbidden_by_name(tmp_path, key):
    raw = record_bytes(changes={key: "sha256:" + "8" * 64})
    with pytest.raises(ValueError, match=f"^approval-forbidden-{key}$"):
        placed(tmp_path, raw)


@pytest.mark.parametrize(("change", "code"), [
    ({"note": "extra"}, "approval-unknown-key"),
    ({"max_runs": None}, "approval-missing-max_runs"),
    ({"exposure": "no cost"}, "approval-exposure"),
    ({"max_runs": 0}, "approval-max_runs"),
    ({"max_runs": True}, "approval-max_runs"),
    ({"instruction_max_bytes": route.INSTRUCTION_MAX_BYTES + 1}, "approval-instruction_max_bytes"),
    ({"not_after": "2026-11-24T12:00:00"}, "approval-not_after"),
    ({"not_after": "2026-11-24T13:00:00+01:00"}, "approval-not_after"),
    ({"consumer": "m9"}, "approval-consumer"),
    ({"schema_version": 2}, "approval-schema_version"),
    ({"host_key_alias": "192.0.2.1 extra"}, "approval-host_key_alias"),
])
def test_record_shape_refusals_name_their_field(tmp_path, change, code):
    with pytest.raises(ValueError, match=f"^{code}$"):
        placed(tmp_path, record_bytes(changes=change))


def test_digest_canonical_bytes_and_location_refuse_by_name(tmp_path):
    raw = record_bytes()
    (tmp_path / "standing-approval.json").write_bytes(raw)
    with pytest.raises(ValueError, match=r"^approval-digest$"):
        StandingApproval.load(tmp_path / "standing-approval.json", "0" * 64, tmp_path)
    with pytest.raises(ValueError, match=r"^approval-canonical$"):
        placed(tmp_path, raw.replace(b"\n", b"\r\n"), "crlf.json")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "standing-approval.json").write_bytes(raw)
    with pytest.raises(ValueError, match=r"^approval-location$"):
        StandingApproval.load(elsewhere / "standing-approval.json", sha(raw), tmp_path)
    with pytest.raises(ValueError, match=r"^approval-unreadable$"):
        StandingApproval.load(tmp_path / "deleted.json", sha(raw), tmp_path)


def test_expiry_suspension_revocation_and_exhaustion_refuse_at_both_check_points(tmp_path):
    standing = placed(tmp_path, record_bytes(max_runs=2))
    packet = json_bytes(view())
    assert standing.admit(view(), tmp_path, NOT_AFTER) == "approval-expired"
    assert standing.confirm("change-review-advice", packet, tmp_path, NOT_AFTER,
                            HOLDER) == "approval-expired"
    # The window's own admission marker is the only one check point (b) accepts.
    assert standing.confirm("change-review-advice", packet, tmp_path, NOW,
                            HOLDER) == "approval-suspended"
    standing.suspension(tmp_path).write_bytes(b"another-window")
    assert standing.admit(view(), tmp_path, NOW) == "approval-suspended"
    assert standing.confirm("change-review-advice", packet, tmp_path, NOW,
                            HOLDER) == "approval-suspended"
    standing.suspension(tmp_path).unlink()
    standing.revocation(tmp_path).write_bytes(b"")
    assert standing.admit(view(), tmp_path, NOW) == "approval-revoked"
    standing.revocation(tmp_path).unlink()
    for slot in (1, 2):
        assert standing.free_slot(tmp_path) == slot
        (tmp_path / ("selection-" + standing.decision(slot))).write_bytes(b"spent")
    assert standing.free_slot(tmp_path) is None
    assert standing.admit(view(), tmp_path, NOW) == "approval-exhausted"


def test_slot_decisions_are_distinct_and_bound_to_the_record(tmp_path):
    first = StandingApproval.from_bytes(record_bytes())
    other = StandingApproval.from_bytes(record_bytes(max_runs=4))
    decisions = {first.decision(slot) for slot in (1, 2, 3)}
    assert len(decisions) == 3 and other.decision(1) not in decisions
    assert first.decision(1) == sha(json_bytes({"approval_sha256": first.sha256, "slot": 1}))


def test_m9_cannot_be_issued_a_standing_record():
    with pytest.raises(ValueError, match=r"^approval-consumer$"):
        approval.issue(view(consumer="m9"), not_after=NOT_AFTER)


# --- custody ------------------------------------------------------------------------


def test_verifier_custody_refuses_shared_writes():
    with tempfile.TemporaryDirectory(dir=Path.home().resolve(strict=True)) as tmp:
        private = Path(tmp)
        approval.private_directory(private)
        if os.name == "nt":
            import ntsecuritycon as rights
            import win32security as security

            mask = security.DACL_SECURITY_INFORMATION
            acl = security.GetNamedSecurityInfo(
                tmp, security.SE_FILE_OBJECT, mask
            ).GetSecurityDescriptorDacl()
            everyone = security.ConvertStringSidToSid("S-1-1-0")
            acl.AddAccessAllowedAce(security.ACL_REVISION, rights.FILE_ADD_FILE, everyone)
            security.SetNamedSecurityInfo(tmp, security.SE_FILE_OBJECT, mask, None, None, acl, None)
        else:
            private.chmod(0o770)
        with pytest.raises(ValueError, match="UNSAFE_CUSTODY"):
            approval.private_directory(private)
