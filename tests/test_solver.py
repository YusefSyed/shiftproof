from shiftproof.solver import solve_case
from shiftproof.verify import verify_assignments

from .domain_helpers import fixture


def test_baseline_is_optimal_and_verified():
    case = fixture()
    result = solve_case(case)
    assert result.status == "OPTIMAL" and len(result.assignments) == 8
    assert verify_assignments(case, result.assignments).valid


def test_cancellation_repairs_against_baseline():
    baseline = solve_case(fixture()).assignments
    result = solve_case(fixture("cancellation"), baseline)
    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert (
        verify_assignments(fixture("cancellation"), result.assignments, baseline).replacements == 2
    )


def test_infeasible_status_is_honest():
    assert solve_case(fixture("infeasible"), optimize=False).status == "INFEASIBLE"


def test_forced_unknown_and_model_invalid_are_not_infeasible(monkeypatch):
    import shiftproof.solver as solver_module

    monkeypatch.setattr(solver_module, "_status", lambda _: "UNKNOWN")
    assert solve_case(fixture()).status == "UNKNOWN"
    monkeypatch.setattr(solver_module, "_status", lambda _: "MODEL_INVALID")
    assert solve_case(fixture()).status == "MODEL_INVALID"


def test_later_objective_unknown_retains_verified_incumbent(monkeypatch):
    import shiftproof.solver as solver_module

    statuses = iter(("OPTIMAL", "UNKNOWN"))
    monkeypatch.setattr(solver_module, "_status", lambda _: next(statuses))
    result = solve_case(fixture())
    assert result.status == "FEASIBLE"
    assert result.phases[-1].status == "UNKNOWN"
    assert verify_assignments(fixture(), result.assignments).valid
