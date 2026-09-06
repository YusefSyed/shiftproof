"""Exercise genuine local agent runs through the app API using synthetic operator actions.

Cookies, CSRF values and one-use approval tokens stay only in process memory.
The written receipt contains computed results, safe tool events and measured times.
"""

from __future__ import annotations

import io
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

import httpx

ROOT = Path(__file__).resolve().parents[1]


def summarized(state: dict) -> dict:
    candidate = state.get("candidate")
    return {
        "status": state["status"], "case_hash": state["case_hash"], "revision": state["revision"],
        "candidate": ({key: candidate.get(key) for key in
                       ("case_hash", "candidate_hash", "hypothetical", "solver", "verification")}
                      if candidate else None),
        "diagnosis": state.get("diagnosis"),
        "proposals": [{"operations": p["operations"], "base_case_hash": p["base_case_hash"],
                       "simulation": ({k: p["simulation"].get(k) for k in
                                       ("case_hash", "hypothetical", "solver", "verification", "diagnosis")}
                                      if p.get("simulation") else None)}
                      for p in state.get("proposals", [])],
        "approved": state.get("approval") is not None,
        "error": state.get("last_error"),
    }


class Harness:
    def __init__(self):
        self.client = httpx.Client(base_url="http://127.0.0.1:8000", trust_env=False, timeout=10)
        self.state = self.client.get("/api/state").json()
        self.started = time.monotonic()
        self.records: list[dict] = []
        self.timeline: list[dict] = []
        self.folder = ROOT / "workspace" / ("evaluation-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
        self.folder.mkdir(parents=True)

    def emit(self, text: str) -> None:
        elapsed = round(time.monotonic() - self.started, 3)
        self.timeline.append({"at_seconds": elapsed, "text": text})
        print(f"[{elapsed:7.2f}s] {text}", flush=True)

    def refresh(self) -> dict:
        response = self.client.get("/api/state")
        response.raise_for_status()
        self.state = response.json()
        return self.state

    def post(self, path: str, body: dict, *, expected: int = 200):
        response = self.client.post(path, json=body, headers={
            "Origin": "http://127.0.0.1:8000", "X-CSRF-Token": self.state["csrf"]})
        assert response.status_code == expected, f"{path}: HTTP {response.status_code}"
        result = response.json()
        self.refresh()
        return result

    def run(self, label: str, prompt: str) -> dict:
        self.emit(f"{label}: starting genuine local Strands run")
        started = time.monotonic()
        self.post("/api/run", {"request": prompt})
        last_seq = 0
        while True:
            state = self.refresh()
            for event in state["trace"]:
                if event["seq"] > last_seq:
                    last_seq = event["seq"]
                    if event["type"] in ("tool_end", "model_end"):
                        self.emit(f"{event.get('tool') or event.get('detail')}: {event['status']} ({event.get('duration',0)}s)")
            if not state["running"]:
                break
            if time.monotonic() - started > 195:
                self.post("/api/cancel", {})
                raise AssertionError("Parent worker deadline failed")
            time.sleep(0.5)
        record = {"label": label, "elapsed_seconds": round(time.monotonic() - started, 3),
                  "trace": state["trace"], "result": summarized(state)}
        self.records.append(record)
        self.emit(f"{label}: {state['status']}")
        assert not state.get("last_error"), state.get("last_error")
        return state

    def approve_export(self, label: str) -> None:
        candidate = self.state["candidate"]
        self.post("/api/approve", {"result_id": candidate["result_id"],
            "case_hash": self.state["case_hash"], "candidate_hash": candidate["candidate_hash"],
            "approval_token": candidate["approve_token"]})
        artifact = self.post("/api/export", {"approval_id": self.state["approval"]["approval_id"],
            "case_hash": self.state["case_hash"], "candidate_hash": candidate["candidate_hash"]})
        response = self.client.get("/api/artifacts/" + artifact["artifact_id"])
        response.raise_for_status()
        with ZipFile(io.BytesIO(response.content)) as archive:
            assert "calendar_all.ics" in archive.namelist()
            assert archive.read("calendar_all.ics").count(b"BEGIN:VEVENT") == 8
        (self.folder / f"{label}.zip").write_bytes(response.content)
        self.emit(f"Synthetic operator approved {label}; actual bundle contains 8 calendar events")

    def proposal(self, op: dict) -> dict:
        matches = [p for p in self.state["proposals"] if p["operations"] == [op]]
        assert len(matches) == 1, "Model did not propose the exact requested change"
        return matches[0]

    def apply(self, proposal: dict) -> None:
        self.post(f"/api/proposals/{proposal['proposal_id']}/apply", {
            "case_hash": self.state["case_hash"], "proposal_hash": proposal["proposal_hash"],
            "approval_token": proposal["apply_token"], "confirm": True})
        assert self.state["approval"] is None
        assert self.state["candidate"] is None
        self.emit("Synthetic operator applied the reviewed change; previous schedule approval revoked")

    def main(self) -> None:
        self.post("/api/demo", {"variant": "baseline"})
        self.post("/api/confirm", {"case_hash": self.state["case_hash"]})
        state = self.run("Baseline", "Inspect this case, find a schedule, and prepare a review using evidence from your tools.")
        check = state["candidate"]["verification"]
        assert check["valid"] and check["preferred"] == 8 and check["replacements"] == 0
        assert any(t.get("tool") == "solve_schedule" for t in state["trace"])
        self.approve_export("baseline")
        old_hash = self.state["case_hash"]
        old_approval = self.state["approval"]["approval_id"]

        self.run("Cancellation proposal", "Propose exactly one change: mark V02 unavailable for S2. Simulate it and prepare a review. Do not apply the change.")
        proposal = self.proposal({"op": "set_availability", "volunteer_id": "V02", "shift_id": "S2", "status": "unavailable"})
        assert self.state["case_hash"] == old_hash
        assert self.state["approval"]["approval_id"] == old_approval
        assert proposal["simulation"]["verification"]["replacements"] == 2
        self.apply(proposal)
        state = self.run("Cancellation repair", "Solve the current confirmed case, preserving the previous approved assignments where possible. Prepare a review using the returned evidence.")
        check = state["candidate"]["verification"]
        assert check["valid"] and check["replacements"] == 2 and check["preferred"] == 6
        expected = {("V01", "S1", "lead"), ("V01", "S2", "lead"),
                    ("V02", "S3", "lead"), ("V02", "S4", "lead"),
                    ("V03", "S1", "helper"), ("V04", "S2", "helper"),
                    ("V05", "S3", "helper"), ("V06", "S4", "helper")}
        assert {(a["volunteer_id"], a["shift_id"], a["role"])
                for a in state["candidate"]["solver"]["assignments"]} == expected
        self.approve_export("repair")
        old_candidate = self.state["candidate"]["candidate_hash"]
        old_approval = self.state["approval"]["approval_id"]
        self.run("Second cancellation proposal", "Propose exactly one change: mark V02 unavailable for S3. Simulate this proposal and prepare its review. Do not apply it.")
        proposal = self.proposal({"op": "set_availability", "volunteer_id": "V02", "shift_id": "S3", "status": "unavailable"})
        assert proposal["simulation"]["solver"]["status"] == "INFEASIBLE"
        self.apply(proposal)
        state = self.run("Infeasible case", "Find a schedule for the confirmed case. If infeasible, diagnose it with tool evidence, then prepare a review.")
        assert state["status"] == "INFEASIBLE"
        facts = state["diagnosis"]["facts"]
        witness = next(f for f in facts if f["code"] == "sole_eligible_capacity")
        assert witness["details"]["required_shifts"] == 3
        assert witness["details"]["required_minutes"] == 360
        assert witness["details"]["max_shifts"] == 2
        self.post("/api/export", {"approval_id": old_approval, "case_hash": state["case_hash"],
                                 "candidate_hash": old_candidate}, expected=409)
        self.emit("Rejected stale schedule export after the second cancellation")
        before = self.state["case_hash"]
        state = self.run("Hypothetical repairs", "Compare two separate hypothetical repairs. First restore V02's S3 availability to available. Second raise both V01's limits to 360 minutes and 3 shifts. Create one proposal for each alternative, simulate each, and prepare their reviews. Do not apply either change.")
        for op in ({"op":"set_availability","volunteer_id":"V02","shift_id":"S3","status":"available"},
                   {"op":"set_limits","volunteer_id":"V01","max_total_minutes":360,"max_shifts":3}):
            proposal = self.proposal(op)
            assert proposal["simulation"]["verification"]["valid"]
            assert proposal["simulation"]["hypothetical"]
        assert state["case_hash"] == before and state["approval"] is None
        assert state["status"] == "INFEASIBLE"
        assert state["candidate"]["solver"]["status"] == "INFEASIBLE"
        assert state["candidate"]["verification"] is None
        self.emit("Both alternatives verified feasible; neither changed the confirmed case")


if __name__ == "__main__":
    harness = Harness()
    result = {"synthetic_data_only": True, "real_model": True,
              "operator_actions": "Automated test harness exercising the explicit human UI routes",
              "runtime_model": json.loads((ROOT / "runtime-model.json").read_text()),
              "started_at": datetime.now(UTC).isoformat(), "passed": False}
    try:
        harness.main()
        result["passed"] = True
    except Exception as exc:
        result["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        harness.emit("Evaluation stopped: " + type(exc).__name__)
    finally:
        result["scenarios"] = harness.records
        result["timeline"] = harness.timeline
        result["elapsed_seconds"] = round(time.monotonic() - harness.started, 3)
        receipt = harness.folder / "receipt.json"
        receipt.write_text(json.dumps(result, indent=2) + "\n")
        print("Receipt:", receipt, flush=True)
        harness.client.close()
    raise SystemExit(0 if result["passed"] else 1)
