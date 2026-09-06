from shiftproof.diagnostics import diagnose_case
from shiftproof.models import Lock
from shiftproof.solver import solve_case

from .domain_helpers import fixture


def test_diagnosis_is_bounded_and_sound():
    d = diagnose_case(fixture("infeasible"), max_calls=4, time_limit=3)
    assert d.status == "INFEASIBLE" and d.solver_calls <= 4
    witness = next(fact for fact in d.facts if fact.code == "sole_eligible_capacity")
    assert witness.entity_ids[:4] == ("V01", "S1", "S2", "S3")
    assert witness.details == {
        "required_shifts": 3,
        "max_shifts": 2,
        "required_minutes": 360,
        "max_total_minutes": 240,
    }
    assert "coverage.csv:2" in witness.source_refs
    assert "volunteers.csv:2" in witness.source_refs
    assert "policy:missing_availability_unavailable" in witness.source_refs
    assert all(fact.code != "insufficient_eligible" for fact in d.facts)


def test_removed_lower_bounds_preserve_contradictory_pins():
    case = fixture()
    locks = tuple(
        Lock(lock_id=f"L0{i}", volunteer_id="V01", shift_id=shift, role="lead")
        for i, shift in enumerate(("S1", "S2", "S3"), 1)
    )
    pinned = case.model_copy(update={"locks": locks})
    assert solve_case(pinned, lower_bounds=frozenset(), optimize=False).status == "INFEASIBLE"
    diagnosis = diagnose_case(pinned, max_calls=4, time_limit=3)
    assert diagnosis.proof_kind == "fixed_conflict" and not diagnosis.subset_minimal


def test_unknown_deletion_does_not_claim_minimality(monkeypatch):
    import shiftproof.diagnostics as diagnostics
    from shiftproof.models import SolverResult

    statuses = iter(("INFEASIBLE", "FEASIBLE", "UNKNOWN"))

    def fake_solve(case, **_kwargs):
        return SolverResult(case_hash=case.case_hash, status=next(statuses))

    monkeypatch.setattr(diagnostics, "solve_case", fake_solve)
    result = diagnostics.diagnose_case(fixture(), max_calls=3)
    assert result.status == "INFEASIBLE"
    assert result.subset_minimal is False
    assert "unknown" in result.limitation.lower()


def test_diagnosis_honors_call_and_empty_time_budgets(monkeypatch):
    import shiftproof.diagnostics as diagnostics
    from shiftproof.models import SolverResult

    calls = []

    def fake_solve(case, **_kwargs):
        calls.append(case.case_id)
        return SolverResult(case_hash=case.case_hash, status="INFEASIBLE")

    monkeypatch.setattr(diagnostics, "solve_case", fake_solve)
    limited = diagnostics.diagnose_case(fixture(), max_calls=1, time_limit=10)
    assert limited.status == "INFEASIBLE"
    assert limited.proof_kind == "bounded"
    assert limited.solver_calls == len(calls) == 1
    calls.clear()
    empty = diagnostics.diagnose_case(fixture(), max_calls=0, time_limit=10)
    assert empty.status == "UNKNOWN" and empty.solver_calls == len(calls) == 0
