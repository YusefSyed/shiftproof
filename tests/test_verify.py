from shiftproof.models import Assignment
from shiftproof.solver import solve_case
from shiftproof.verify import verify_assignments

from .domain_helpers import fixture


def test_verifier_catches_mutated_assignment():
    case = fixture()
    valid = solve_case(case).assignments
    bad = valid + (Assignment(volunteer_id="V01", shift_id="S1", role="lead"),)
    result = verify_assignments(case, bad)
    assert not result.valid and any(v.code == "duplicate_assignment" for v in result.violations)


def test_adjacency_is_not_overlap():
    case = fixture()
    assignments = tuple(
        Assignment(volunteer_id="V01", shift_id="S2", role="lead")
        if assignment.key == ("V02", "S2", "lead")
        else assignment
        for assignment in solve_case(case).assignments
    )
    result = verify_assignments(case, assignments)
    assert "overlap" not in {violation.code for violation in result.violations}


def test_verifier_reports_assignment_mutation_classes():
    case = fixture()
    valid = solve_case(case).assignments
    changed_volunteers = tuple(
        volunteer.model_copy(update={"roles": ("lead", "helper")})
        if volunteer.volunteer_id == "V01"
        else volunteer
        for volunteer in case.volunteers
    )
    dual_case = case.model_copy(update={"volunteers": changed_volunteers})
    mutations = {
        "unknown_or_undemanded_assignment": valid
        + (Assignment(volunteer_id="V99", shift_id="S1", role="lead"),),
        "unqualified": valid[:-1] + (Assignment(volunteer_id="V03", shift_id="S4", role="lead"),),
        "unavailable": valid[:-1] + (Assignment(volunteer_id="V02", shift_id="S1", role="lead"),),
        "multiple_roles": valid + (Assignment(volunteer_id="V01", shift_id="S1", role="helper"),),
        "coverage": valid[:-1],
    }
    for code, assignments in mutations.items():
        tested_case = dual_case if code == "multiple_roles" else case
        assert code in {
            violation.code for violation in verify_assignments(tested_case, assignments).violations
        }


def test_verifier_detects_overcoverage_and_workload_cap():
    case = fixture()
    valid = solve_case(case).assignments
    over = valid + (Assignment(volunteer_id="V02", shift_id="S3", role="lead"),)
    assert "coverage" in {item.code for item in verify_assignments(case, over).violations}
    low_cap = tuple(
        volunteer.model_copy(update={"max_total_minutes": 0})
        if volunteer.volunteer_id == "V01"
        else volunteer
        for volunteer in case.volunteers
    )
    capped = case.model_copy(update={"volunteers": low_cap})
    assert "workload_cap" in {item.code for item in verify_assignments(capped, valid).violations}


def test_verifier_violations_include_provenance():
    case = fixture()
    valid = solve_case(case).assignments
    assignments = valid[:-1] + (Assignment(volunteer_id="V02", shift_id="S1", role="lead"),)
    result = verify_assignments(case, assignments)
    by_code = {violation.code: violation for violation in result.violations}
    assert by_code["unavailable"].source_refs == ("policy:missing_availability_unavailable",)
    assert by_code["coverage"].source_refs
