"""The shared law accepts only the existing closed leaves and integer epochs."""

from types import SimpleNamespace

import pytest

from constructicon.core import permit
from constructicon.core.maintenance import _AttemptAuthorization
from constructicon.core.qualification import QualificationAuthorization
from constructicon.core.refusal import MAX_REFUSAL_CODES, RefusalCode
from tests.core.test_qualification import authorization
from tests.core.test_run_permit_goldens import PURPOSES, exact, wrong


@pytest.mark.parametrize("purpose", PURPOSES)
def test_each_closed_purpose_uses_the_same_ordered_law(purpose):
    make, sentences = PURPOSES[purpose]
    value = make()
    assert permit.run_id(value) == value.run_id
    assert permit.admits(
        value, source_graph_hash=value.source_graph_hash,
        capability_id=value.capability_id, revision=value.revision,
    )
    assert permit.faults(value, **exact(value)) == ()
    assert permit.faults(value, **wrong(value)) == tuple(
        fault for fault, sentence in zip(permit.PermitFault, sentences, strict=True) if sentence
    )
    assert value.purpose in (
        "qualification-no-dispatch", "qualification-read", "qualification-write",
        "plan-manifest-maintenance", "channel-stored-reply",
    )
    assert "purpose" not in QualificationAuthorization.model_fields


class UnlistedQualification(QualificationAuthorization):
    """A subclass is not a sixth purpose in the closed law."""


@pytest.mark.parametrize("unlisted", [
    object(), SimpleNamespace(**authorization().__dict__),
    UnlistedQualification.model_construct(**authorization().__dict__),
    _AttemptAuthorization.model_construct(),
])
@pytest.mark.parametrize("operation", ["run_id", "admits", "faults", "fault_sentences"])
def test_unlisted_objects_are_refused_at_each_law_entry(unlisted, operation):
    args = exact(authorization()) if operation == "faults" else {}
    if operation == "fault_sentences":
        args = {"found": ()}
    if operation == "admits":
        args = {key: args_value for key, args_value in exact(authorization()).items()
                if key in ("source_graph_hash", "capability_id", "revision")}
    with pytest.raises(TypeError, match="the permit law requires a closed authorization type"):
        getattr(permit, operation)(unlisted, **args)


@pytest.mark.parametrize("epoch", [0, -1, False, True, 0.5, 1.0, 4])
def test_a_multi_epoch_permit_refuses_noninteger_or_out_of_range_epochs(epoch):
    value = authorization(max_epoch=3)
    assert permit.faults(value, **{**exact(value), "epoch": epoch}) == (permit.PermitFault.EPOCH,)


@pytest.mark.parametrize("epoch", [1, 2, 3])
def test_a_multi_epoch_permit_accepts_every_integer_inside_its_budget(epoch):
    value = authorization(max_epoch=3)
    assert permit.faults(value, **{**exact(value), "epoch": epoch}) == ()


def test_the_permit_code_family_names_exactly_the_ten_actual_law_checks():
    expected = (
        RefusalCode.PERMIT_RUN, RefusalCode.PERMIT_INVOCATION, RefusalCode.PERMIT_BINDING,
        RefusalCode.PERMIT_SOURCE_GRAPH, RefusalCode.PERMIT_CAPABILITY, RefusalCode.PERMIT_REVISION,
        RefusalCode.PERMIT_OPERATOR_BINDING, RefusalCode.PERMIT_GRANTS,
        RefusalCode.PERMIT_EPOCH, RefusalCode.PERMIT_EXPIRED,
    )
    assert tuple(fault.refusal for fault in permit.PermitFault) == expected
    assert set(expected) == {code for code in RefusalCode if code.value.startswith("permit.")}
    assert len(expected) <= MAX_REFUSAL_CODES


@pytest.mark.parametrize("purpose", PURPOSES)
def test_every_individual_failed_check_records_its_code_without_using_the_sentence(purpose):
    make, sentences = PURPOSES[purpose]
    value = make()
    for index, (key, wrong_value) in enumerate(wrong(value).items()):
        found = permit.faults(value, **{**exact(value), key: wrong_value})
        expected = (tuple(permit.PermitFault)[index],) if sentences[index] else ()
        assert found == expected
        assert tuple(fault.refusal.value for fault in found) == tuple(
            f"permit.{fault.value}" for fault in expected
        )
        assert permit.fault_sentences(value, found) == (
            (sentences[index],) if sentences[index] else ()
        )
