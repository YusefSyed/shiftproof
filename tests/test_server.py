import io
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from shiftproof.solver import solve_case
from shiftproof.verify import verify_assignments

server = pytest.importorskip("shiftproof.server")

ORIGIN = "http://127.0.0.1:8000"


class FakeJob:
    """A local worker stand-in that returns a real solver/verifier envelope once."""

    def __init__(self, case, baseline, request, prior):
        self.run_id = "RUN_TEST"
        self.case_hash = case.case_hash
        self.baseline = baseline
        self.done = False
        solved = solve_case(case, baseline)
        verified = verify_assignments(case, solved.assignments, baseline)
        self.messages = [
            {"kind": "event", "event": {"type": "tool_start", "tool": "solve_schedule", "status": "running"}},
            {
                "kind": "complete",
                "payload": {
                    "results": [
                        {
                            "result_id": "R_aaaaaaaaaaaaaaaa",
                            "case_hash": case.case_hash,
                            "base_case_hash": case.case_hash,
                            "hypothetical": False,
                            "proposal_id": None,
                            "solver": solved.model_dump(mode="json"),
                            "verification": verified.model_dump(mode="json"),
                            "diagnosis": None,
                            "evidence": [],
                        }
                    ],
                    "proposals": [],
                    "review_result_id": None,
                    "error": None,
                },
            },
        ]

    def poll(self):
        if self.done:
            return []
        self.done = True
        return self.messages

    def cancel(self):
        self.done = True


class PendingJob:
    def __init__(self, case, baseline, request, prior):
        self.run_id = "RUN_PENDING"
        self.case_hash = case.case_hash
        self.baseline = baseline
        self.done = False

    def poll(self):
        return []

    def cancel(self):
        self.done = True


def client(job_factory=FakeJob):
    return TestClient(server.create_app(job_factory=job_factory, runtime_probe=lambda: {"ready": True, "tag": "test", "detail": "local"}), base_url=ORIGIN)


def state_and_headers(web):
    response = web.get("/api/state")
    assert response.status_code == 200
    assert "httponly" in response.headers["set-cookie"].lower()
    return response.json(), {"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf"]}


def load_and_confirm(web):
    _, headers = state_and_headers(web)
    loaded = web.post("/api/demo", json={"variant": "baseline"}, headers=headers)
    assert loaded.status_code == 200
    case_hash = loaded.json()["case_hash"]
    confirmed = web.post("/api/confirm", json={"case_hash": case_hash}, headers=headers)
    assert confirmed.status_code == 200
    return headers, confirmed.json()


def test_mutations_require_origin_and_csrf_and_planning_requires_confirmation():
    with client() as web:
        state, headers = state_and_headers(web)
        assert web.post("/api/demo", json={"variant": "baseline"}).status_code >= 400
        assert web.post("/api/demo", json={"variant": "baseline"}, headers={"Origin": "http://example.invalid", "X-CSRF-Token": state["csrf"]}).status_code >= 400
        assert web.post("/api/demo", json={"variant": "baseline"}, headers={"Origin": ORIGIN, "X-CSRF-Token": "wrong"}).status_code >= 400
        loaded = web.post("/api/demo", json={"variant": "baseline"}, headers=headers)
        assert loaded.status_code == 200
        assert web.post("/api/run", json={"request": "find a schedule"}, headers=headers).status_code >= 400


def test_import_rejects_missing_slots_and_bad_host():
    with client() as web:
        _, headers = state_and_headers(web)
        response = web.post("/api/import", files={"case.json": ("ignored.json", b"{}", "application/json")}, headers=headers)
        assert response.status_code >= 400
        hostile = dict(headers)
        hostile["Host"] = "example.invalid"
        assert web.post("/api/demo", json={"variant": "baseline"}, headers=hostile).status_code >= 400
        too_large = web.post("/api/run", json={"request": "x" * 1_100_000}, headers=headers)
        assert too_large.status_code == 413


def test_confirmed_mocked_run_can_be_approved_and_exported_with_session_isolation():
    with client() as web:
        headers, _ = load_and_confirm(web)
        started = web.post("/api/run", json={"request": "Find a schedule."}, headers=headers)
        assert started.status_code == 200
        completed = web.get("/api/state").json()
        assert completed["status"] == "VERIFIED_FEASIBLE"
        candidate = completed["candidate"]
        foreign_result = web.post("/api/approve", json={"result_id": "R_bbbbbbbbbbbbbbbb", "case_hash": completed["case_hash"], "candidate_hash": candidate["candidate_hash"], "approval_token": candidate["approve_token"]}, headers=headers)
        assert foreign_result.status_code >= 400
        with client() as stranger:
            _, stranger_headers = state_and_headers(stranger)
            foreign_session_result = stranger.post("/api/approve", json={"result_id": candidate["result_id"], "case_hash": completed["case_hash"], "candidate_hash": candidate["candidate_hash"], "approval_token": candidate["approve_token"]}, headers=stranger_headers)
            assert foreign_session_result.status_code >= 400
        approved = web.post("/api/approve", json={"result_id": candidate["result_id"], "case_hash": completed["case_hash"], "candidate_hash": candidate["candidate_hash"], "approval_token": candidate["approve_token"]}, headers=headers)
        assert approved.status_code == 200
        approval = approved.json()["approval"]
        foreign_approval = web.post("/api/export", json={"approval_id": "A_foreign", "case_hash": approved.json()["case_hash"], "candidate_hash": candidate["candidate_hash"]}, headers=headers)
        assert foreign_approval.status_code >= 400
        exported = web.post("/api/export", json={"approval_id": approval["approval_id"], "case_hash": approved.json()["case_hash"], "candidate_hash": candidate["candidate_hash"]}, headers=headers)
        assert exported.status_code == 200
        artifact_id = exported.json()["artifact_id"]
        download = web.get(f"/api/artifacts/{artifact_id}")
        assert download.status_code == 200
        with ZipFile(io.BytesIO(download.content)) as archive:
            assert "manifest.json" in archive.namelist()
        with client() as stranger:
            _, stranger_headers = state_and_headers(stranger)
            foreign_session_approval = stranger.post("/api/export", json={"approval_id": approval["approval_id"], "case_hash": approved.json()["case_hash"], "candidate_hash": candidate["candidate_hash"]}, headers=stranger_headers)
            assert foreign_session_approval.status_code >= 400
            assert stranger.get(f"/api/artifacts/{artifact_id}").status_code >= 400


def test_cancelled_run_rejects_late_completion():
    with client(PendingJob) as web:
        headers, _ = load_and_confirm(web)
        assert web.post("/api/run", json={"request": "Find a schedule."}, headers=headers).status_code == 200
        assert web.get("/api/state").json()["running"] is True
        cancelled = web.post("/api/cancel", json={}, headers=headers)
        assert cancelled.status_code == 200
        state = web.get("/api/state").json()
        assert state["status"] == "CANCELLED"
        assert state["running"] is False
