import pytest

from shiftproof.models import SolverResult
from shiftproof.store import Session
from shiftproof.tools import ToolContext

from .domain_helpers import fixture


def test_feasible_hypothesis_does_not_relabel_infeasible_current_case():
    case = fixture("infeasible")
    session = Session()
    session.load_case(case)
    session.confirm(case.case_hash)
    original = ToolContext(case, (), lambda event: None)
    original.solve()
    diagnosed = original.diagnose()
    original.review(diagnosed["result_id"], diagnosed["evidence_ids"])
    session.begin_run("initial")
    assert session.finish_run("initial", case.case_hash, original.payload(), ())
    assert session.status == "INFEASIBLE"

    hypothetical = ToolContext(case, (), lambda event: None, session.worker_context())
    proposal = hypothetical.propose([{"op": "set_limits", "volunteer_id": "V01",
                                     "max_total_minutes": 360, "max_shifts": 3}])
    simulated = hypothetical.simulate(proposal["proposal_id"])
    assert simulated["verified"]["valid"]
    hypothetical.review(simulated["result_id"], simulated["evidence_ids"])
    session.begin_run("simulation")
    assert session.finish_run("simulation", case.case_hash, hypothetical.payload(), ())
    state = session.public_state({})
    assert state["case_hash"] == case.case_hash
    assert state["status"] == "INFEASIBLE"
    assert state["candidate"]["solver"]["status"] == "INFEASIBLE"
    assert state["candidate"]["verification"] is None
    assert state["approval"] is None


@pytest.mark.parametrize("solver_status,expected", [("UNKNOWN", "UNDETERMINED"), ("MODEL_INVALID", "ERROR")])
def test_no_candidate_solver_status_is_reported_honestly(monkeypatch, solver_status, expected):
    case = fixture()
    monkeypatch.setattr("shiftproof.tools.solve_case", lambda *args: SolverResult(
        case_hash=case.case_hash, status=solver_status))
    context = ToolContext(case, (), lambda event: None)
    context.solve()
    session = Session()
    session.load_case(case)
    session.confirm(case.case_hash)
    session.begin_run("test-status")
    assert session.finish_run("test-status", case.case_hash, context.payload(), ())
    assert session.status == expected
    assert session.approval is None
