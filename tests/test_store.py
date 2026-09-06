import pytest

from shiftproof.solver import solve_case
from shiftproof.store import Session, StoreError
from shiftproof.verify import verify_assignments

from .domain_helpers import fixture


def payload(case, baseline=()):
    solver = solve_case(case, baseline)
    verification = verify_assignments(case, solver.assignments, baseline)
    return {
        "results": [
            {
                "result_id": "R_0123456789abcdef",
                "case_hash": case.case_hash,
                "base_case_hash": case.case_hash,
                "hypothetical": False,
                "proposal_id": None,
                "solver": solver.model_dump(mode="json"),
                "verification": verification.model_dump(mode="json"),
                "diagnosis": None,
                "evidence": [],
            }
        ],
        "proposals": [],
        "review_result_id": None,
        "error": None,
    }


def ready():
    case = fixture()
    session = Session()
    session.load_case(case)
    session.confirm(case.case_hash)
    session.begin_run("run")
    assert session.finish_run("run", case.case_hash, payload(case), ())
    return session, case


def test_approval_replay_export_and_original_baseline_are_gated():
    session, case = ready()
    state = session.public_state({})
    candidate = state["candidate"]
    session.approve_schedule(
        candidate["result_id"],
        case.case_hash,
        candidate["candidate_hash"],
        candidate["approve_token"],
    )
    with pytest.raises(StoreError):
        session.approve_schedule(
            candidate["result_id"],
            case.case_hash,
            candidate["candidate_hash"],
            candidate["approve_token"],
        )
    exported = session.export_schedule(
        session.approval.approval_id, case.case_hash, candidate["candidate_hash"], {}
    )
    assert session.get_artifact(exported["artifact_id"])[0] == "shiftproof_schedule.zip"
    assert session.baseline == session.results[candidate["result_id"]]["solver"].assignments
    assert session.results[candidate["result_id"]]["baseline"] == ()


def test_forged_and_stale_worker_completion_cannot_commit():
    case = fixture()
    session = Session()
    session.load_case(case)
    session.confirm(case.case_hash)
    session.begin_run("run")
    forged = payload(case)
    forged["results"][0]["verification"]["valid"] = False
    assert not session.finish_run("run", case.case_hash, forged, ())
    assert not session.results
    session.begin_run("late")
    assert not session.finish_run("other", case.case_hash, payload(case), ())
