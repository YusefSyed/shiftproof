from itertools import product

from shiftproof.models import Assignment
from shiftproof.solver import solve_case
from shiftproof.verify import verify_assignments

from .domain_helpers import fixture


def test_solver_feasibility_matches_small_exhaustive_assignment_oracle():
    case = fixture()
    slots = [(c.shift_id, c.role) for c in case.coverage]
    choices = []
    for sid, role in slots:
        choices.append(
            [
                v.volunteer_id
                for v in case.volunteers
                if role in v.roles
                and any(
                    a.volunteer_id == v.volunteer_id
                    and a.shift_id == sid
                    and a.status != "unavailable"
                    for a in case.availability
                )
            ]
        )
    brute = any(
        verify_assignments(
            case,
            tuple(Assignment(volunteer_id=v, shift_id=s, role=r) for (s, r), v in zip(slots, pick)),
        ).valid
        for pick in product(*choices)
    )
    assert (solve_case(case, optimize=False).status in {"OPTIMAL", "FEASIBLE"}) == brute


def test_fixed_seed_tiny_oracle_matches_lexicographic_objective():
    base = fixture()
    volunteers = tuple(
        volunteer.model_copy(update={"max_total_minutes": 360, "max_shifts": 3})
        for volunteer in base.volunteers[:2]
    )
    shifts = base.shifts[:3]
    coverage = tuple(
        item
        for item in base.coverage
        if item.shift_id in {"S1", "S2", "S3"} and item.role == "lead"
    )
    availability = tuple(
        item
        for item in base.availability
        if item.volunteer_id in {"V01", "V02"} and item.shift_id in {"S1", "S2", "S3"}
    )
    case = base.model_copy(
        update={
            "roles": ("lead",),
            "volunteers": volunteers,
            "shifts": shifts,
            "coverage": coverage,
            "availability": availability,
        }
    )
    slots = [(item.shift_id, item.role) for item in coverage]
    candidates = []
    for picked in product(("V01", "V02"), repeat=len(slots)):
        assignments = tuple(
            Assignment(volunteer_id=vid, shift_id=sid, role=role)
            for (sid, role), vid in zip(slots, picked)
        )
        verification = verify_assignments(case, assignments)
        if verification.valid:
            candidates.append(
                (verification.replacements, verification.non_preferred, verification.dispersion)
            )
    result = solve_case(case)
    values = tuple(phase.value for phase in result.phases if phase.name != "feasibility")
    assert result.status == "OPTIMAL"
    assert values == min(candidates)
