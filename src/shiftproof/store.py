"""Parent-only, in-memory session state and approval gates."""

from __future__ import annotations

import re
import secrets
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from .export import build_bundle, build_diagnosis_bundle
from .models import (
    Approval,
    Assignment,
    Case,
    Diagnosis,
    Fact,
    Proposal,
    SolverResult,
    Verification,
    hash_json,
)
from .proposals import apply_to_copy
from .verify import verify_assignments


class StoreError(ValueError):
    """A safe state-gate error suitable for displaying to a user."""


class Session:
    def __init__(self) -> None:
        self.session_id = "S_" + uuid.uuid4().hex
        self.csrf = secrets.token_urlsafe(24)
        self.lock = threading.RLock()
        self.case: Case | None = None
        self.source_kind = "none"
        self.baseline: tuple[Assignment, ...] = ()
        self.revision = 0
        self.confirmed = False
        self.status = "IMPORTED"
        self.active_run_id: str | None = None
        self.results: dict[str, dict[str, Any]] = {}
        self.proposals: dict[str, Proposal] = {}
        self._apply_tokens: dict[str, str] = {}
        self._approve_tokens: dict[str, str] = {}
        self.approval: Approval | None = None
        self.trace: list[dict[str, Any]] = []
        self.artifacts: dict[str, dict[str, Any]] = {}
        self.current_result_id: str | None = None
        self.diagnosis: Diagnosis | None = None
        self.last_error: str | None = None

    def load_case(self, case: Case) -> dict[str, Any]:
        with self.lock:
            self.case = case
            self.baseline = ()
            self.revision += 1
            self.confirmed = False
            self.status = "IMPORTED"
            self.active_run_id = None
            self.results.clear()
            self.proposals.clear()
            self._apply_tokens.clear()
            self._approve_tokens.clear()
            self.current_result_id = None
            self.approval = None
            self.diagnosis = None
            self.last_error = None
            self._mark_historical()
            return self.public_state({})

    def confirm(self, case_hash: str) -> dict[str, Any]:
        with self.lock:
            self._require_case(case_hash)
            assert self.case is not None
            self.confirmed = True
            self.status = "HUMAN_CONFIRMED"
            return self.public_state({})

    def begin_run(self, run_id: str) -> bool:
        with self.lock:
            if not self.case or not self.confirmed or self.active_run_id:
                return False
            self.active_run_id = run_id
            self.status = "PLANNING"
            self.last_error = None
            return True

    def cancel_run(self) -> None:
        with self.lock:
            if self.active_run_id:
                self.active_run_id = None
                self.status = "CANCELLED"

    def finish_run(
        self,
        run_id: str,
        expected_case_hash: str,
        payload: dict[str, Any],
        baseline: tuple[Assignment, ...],
    ) -> bool:
        with self.lock:
            if (
                not self.case
                or self.active_run_id != run_id
                or self.case.case_hash != expected_case_hash
            ):
                return False
            case = self.case
            assert case is not None
            try:
                if (
                    set(payload) != {"results", "proposals", "review_result_id", "error"}
                    or not isinstance(payload["results"], list)
                    or not isinstance(payload["proposals"], list)
                    or (
                        payload["review_result_id"] is not None
                        and not isinstance(payload["review_result_id"], str)
                    )
                    or (payload["error"] is not None and not isinstance(payload["error"], str))
                ):
                    raise StoreError("Worker envelope is invalid.")
                parsed_proposals = [
                    Proposal.model_validate(item) for item in payload.get("proposals", [])
                ]
                if len({proposal.proposal_id for proposal in parsed_proposals}) != len(
                    parsed_proposals
                ):
                    raise StoreError("Worker proposal IDs are duplicated.")
                all_proposals = {
                    **self.proposals,
                    **{proposal.proposal_id: proposal for proposal in parsed_proposals},
                }
                scenarios = {
                    proposal.proposal_id: apply_to_copy(self.case, proposal)
                    for proposal in all_proposals.values()
                }
                staged: list[dict[str, Any]] = []
                for raw in payload.get("results", []):
                    if not isinstance(raw, dict) or set(raw) != {
                        "result_id",
                        "case_hash",
                        "base_case_hash",
                        "hypothetical",
                        "proposal_id",
                        "solver",
                        "verification",
                        "diagnosis",
                        "evidence",
                    }:
                        raise StoreError("Worker result is invalid.")
                    result_id = raw["result_id"]
                    if (
                        not isinstance(result_id, str)
                        or not re.fullmatch(r"R_[0-9a-f]{16}", result_id)
                        or any(entry["result_id"] == result_id for entry in staged)
                    ):
                        raise StoreError("Worker result ID is invalid.")
                    hypothetical = raw["hypothetical"]
                    if type(hypothetical) is not bool:
                        raise StoreError("Worker result is invalid.")
                    proposal_id = raw.get("proposal_id")
                    if hypothetical and not isinstance(proposal_id, str):
                        raise StoreError("Worker result has an invalid scenario.")
                    if hypothetical:
                        assert isinstance(proposal_id, str)
                        scenario = scenarios.get(proposal_id)
                    else:
                        scenario = case
                    if scenario is None or (not hypothetical and proposal_id is not None):
                        raise StoreError("Worker result has an invalid scenario.")
                    if (
                        raw.get("case_hash") != scenario.case_hash
                        or raw.get("base_case_hash") != case.case_hash
                    ):
                        raise StoreError("Worker result has a stale case.")
                    solver = SolverResult.model_validate(raw["solver"])
                    if solver.case_hash != scenario.case_hash:
                        raise StoreError("Worker result has a stale case.")
                    verification = (
                        Verification.model_validate(raw["verification"])
                        if raw.get("verification")
                        else None
                    )
                    diagnosis = (
                        Diagnosis.model_validate(raw["diagnosis"]) if raw.get("diagnosis") else None
                    )
                    if diagnosis and diagnosis.case_hash != scenario.case_hash:
                        raise StoreError("Worker diagnosis has a stale case.")
                    if not isinstance(raw["evidence"], list):
                        raise StoreError("Worker evidence is invalid.")
                    evidence = tuple(Fact.model_validate(item) for item in raw["evidence"])
                    if len({fact.fact_id for fact in evidence}) != len(evidence) or any(
                        not fact.fact_id.startswith(result_id + ":") for fact in evidence
                    ):
                        raise StoreError("Worker evidence is out of scope.")
                    feasible = solver.status in {"OPTIMAL", "FEASIBLE"}
                    checked = (
                        verify_assignments(scenario, solver.assignments, baseline)
                        if feasible
                        else None
                    )
                    if feasible and (
                        not checked
                        or not checked.valid
                        or verification is None
                        or verification.model_dump() != checked.model_dump()
                    ):
                        raise StoreError("Worker schedule did not pass independent verification.")
                    if not feasible and solver.assignments:
                        raise StoreError("Non-feasible result contains assignments.")
                    staged.append(
                        {
                            "result_id": result_id,
                            "case": scenario,
                            "solver": solver,
                            "verification": checked,
                            "diagnosis": diagnosis,
                            "hypothetical": hypothetical,
                            "proposal_id": proposal_id,
                            "baseline": baseline,
                            "evidence": evidence,
                        }
                    )
            except (KeyError, TypeError, ValueError, StoreError):
                self.active_run_id = None
                self.status = "ERROR"
                self.last_error = "Worker output could not be verified."
                return False
            review_id = payload["review_result_id"]
            known_ids = set(self.results) | {entry["result_id"] for entry in staged}
            if review_id is not None and review_id not in known_ids:
                self.active_run_id = None
                self.status = "ERROR"
                self.last_error = "Worker output could not be verified."
                return False
            self.active_run_id = None
            for proposal in parsed_proposals:
                self.proposals[proposal.proposal_id] = proposal
                self._apply_tokens[proposal.proposal_id] = secrets.token_urlsafe(24)
            for entry in staged:
                self.results[entry["result_id"]] = entry
            if payload["error"]:
                self.last_error = "Local planning ended with an error."
                self.status = "ERROR"
                return True
            real = [entry for entry in staged if not entry["hypothetical"]]
            if real:
                current = next((entry for entry in real if entry["result_id"] == review_id), real[-1])
                self.current_result_id = current["result_id"]
                self.approval = None
                self._approve_tokens.clear()
                self.diagnosis = current["diagnosis"]
                if current["verification"]:
                    self._approve_tokens[current["result_id"]] = secrets.token_urlsafe(24)
            self.status = self._resting_status()
            return True

    def _resting_status(self) -> str:
        """Only the current real result, never existence of a hypothetical, sets case status."""
        if self.approval:
            return "HUMAN_APPROVED"
        current = self.results.get(self.current_result_id or "")
        if current is None:
            return "HUMAN_CONFIRMED" if self.confirmed else "IMPORTED"
        if current["verification"] is not None and current["verification"].valid:
            return "VERIFIED_FEASIBLE"
        if current["solver"].status == "INFEASIBLE":
            return "INFEASIBLE"
        if current["solver"].status == "MODEL_INVALID":
            self.last_error = "The local solver model was invalid. No schedule was approved."
            return "ERROR"
        return "UNDETERMINED"

    def apply_proposal(
        self,
        proposal_id: str,
        case_hash: str,
        proposal_hash: str,
        approval_token: str,
        confirm: bool,
    ) -> dict[str, Any]:
        with self.lock:
            self._require_case(case_hash)
            case = self.case
            assert case is not None
            assert self.case is not None
            if self.active_run_id or not self.confirmed or not confirm:
                raise StoreError("Confirm the current change before applying it.")
            proposal = self.proposals.get(proposal_id)
            stored_token = self._apply_tokens.get(proposal_id)
            if (
                not proposal
                or proposal.proposal_hash != proposal_hash
                or not stored_token
                or not secrets.compare_digest(stored_token, approval_token)
            ):
                raise StoreError("Proposal approval is invalid or already used.")
            self.case = apply_to_copy(self.case, proposal)
            self.revision += 1
            self._apply_tokens.pop(proposal_id, None)
            self.results.clear()
            self.proposals.clear()
            self._apply_tokens.clear()
            self._approve_tokens.clear()
            self.current_result_id = None
            self.approval = None
            self.diagnosis = None
            self._mark_historical()
            self.status = "HUMAN_CONFIRMED"
            return self.public_state({})

    def approve_schedule(
        self, result_id: str, case_hash: str, candidate_hash: str, approval_token: str
    ) -> dict[str, Any]:
        with self.lock:
            self._require_case(case_hash)
            assert self.case is not None
            entry = self.results.get(result_id)
            stored_token = self._approve_tokens.get(result_id)
            fresh = (
                verify_assignments(self.case, entry["solver"].assignments, entry["baseline"])
                if entry
                else None
            )
            if (
                self.active_run_id
                or not self.confirmed
                or not entry
                or entry["hypothetical"]
                or result_id != self.current_result_id
            ):
                raise StoreError("Schedule cannot be approved now.")
            verification = entry["verification"]
            if (
                not verification
                or not verification.valid
                or not fresh
                or not fresh.valid
                or fresh.model_dump() != verification.model_dump()
                or verification.candidate_hash != candidate_hash
                or not stored_token
                or not secrets.compare_digest(stored_token, approval_token)
            ):
                raise StoreError("Schedule approval is invalid or already used.")
            approval = Approval(
                approval_id="A_" + uuid.uuid4().hex,
                case_hash=self.case.case_hash,
                candidate_hash=candidate_hash,
                verification_hash=hash_json(verification.model_dump(mode="json")),
                session_id=self.session_id,
                approved_at=datetime.now(UTC),
            )
            self.approval = approval
            self.baseline = entry["solver"].assignments
            self._approve_tokens.pop(result_id, None)
            self.status = "HUMAN_APPROVED"
            return self.public_state({})

    def export_schedule(
        self, approval_id: str, case_hash: str, candidate_hash: str, runtime_lock: dict[str, str]
    ) -> dict[str, Any]:
        with self.lock:
            self._require_case(case_hash)
            case = self.case
            assert case is not None
            if (
                self.active_run_id
                or not self.approval
                or self.approval.approval_id != approval_id
                or self.approval.candidate_hash != candidate_hash
            ):
                raise StoreError("Approved schedule export is unavailable.")
            entry = self.results.get(self.current_result_id or "")
            if not entry or entry["hypothetical"]:
                raise StoreError("Approved schedule export is unavailable.")
            try:
                data = build_bundle(
                    case,
                    entry["solver"].assignments,
                    entry["baseline"],
                    self.approval,
                    runtime_lock,
                    entry["solver"].phases,
                )
            except ValueError as exc:
                raise StoreError("Schedule no longer passes export checks.") from exc
            artifact_id = "X_" + uuid.uuid4().hex
            name = "shiftproof_schedule.zip"
            self.artifacts[artifact_id] = {
                "name": name,
                "kind": "schedule",
                "case_hash": case_hash,
                "bytes": data,
                "historical": False,
            }
            self.status = "EXPORTED"
            return {"artifact_id": artifact_id, "name": name}

    def export_diagnosis(self, case_hash: str) -> dict[str, Any]:
        with self.lock:
            self._require_case(case_hash)
            case = self.case
            assert case is not None
            if (
                self.active_run_id
                or not self.diagnosis
                or self.diagnosis.case_hash != case.case_hash
            ):
                raise StoreError("No current diagnosis is available.")
            artifact_id = "X_" + uuid.uuid4().hex
            name = "shiftproof_diagnosis.zip"
            self.artifacts[artifact_id] = {
                "name": name,
                "kind": "diagnosis",
                "case_hash": case_hash,
                "bytes": build_diagnosis_bundle(case, self.diagnosis),
                "historical": False,
            }
            return {"artifact_id": artifact_id, "name": name}

    def get_artifact(self, artifact_id: str) -> tuple[str, bytes]:
        with self.lock:
            artifact = self.artifacts.get(artifact_id)
            if not artifact:
                raise StoreError("Artifact is unavailable.")
            return artifact["name"], artifact["bytes"]

    def worker_context(self) -> dict[str, Any]:
        with self.lock:
            return {
                "case": self.case.model_dump(mode="json") if self.case else None,
                "baseline": [item.model_dump() for item in self.baseline],
                "results": [
                    self._worker_result(item)
                    for item in self.results.values()
                    if item["case"].case_hash == (self.case.case_hash if self.case else "")
                ],
                "proposals": [
                    proposal.model_dump(mode="json") for proposal in self.proposals.values()
                ],
            }

    def public_state(self, model_status: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            candidate = self.results.get(self.current_result_id or "")

            def public(entry: dict[str, Any]) -> dict[str, Any]:
                value = {
                    "result_id": entry["result_id"],
                    "case_hash": entry["case"].case_hash,
                    "candidate_hash": entry["verification"].candidate_hash
                    if entry["verification"]
                    else None,
                    "hypothetical": entry["hypothetical"],
                    "baseline_assignments": [a.model_dump() for a in entry["baseline"]],
                    "solver": entry["solver"].model_dump(mode="json"),
                    "verification": entry["verification"].model_dump(mode="json")
                    if entry["verification"]
                    else None,
                    "diagnosis": entry["diagnosis"].model_dump(mode="json")
                    if entry["diagnosis"]
                    else None,
                }
                if not entry["hypothetical"] and entry["result_id"] in self._approve_tokens:
                    value["approve_token"] = self._approve_tokens[entry["result_id"]]
                return value

            proposals = []
            for proposal in self.proposals.values():
                row = proposal.model_dump(mode="json")
                row["apply_token"] = self._apply_tokens.get(proposal.proposal_id)
                row["simulation"] = next(
                    (
                        public(entry)
                        for entry in self.results.values()
                        if entry["proposal_id"] == proposal.proposal_id
                    ),
                    None,
                )
                proposals.append(row)
            return {
                "csrf": self.csrf,
                "session_id": self.session_id,
                "revision": self.revision,
                "case_hash": self.case.case_hash if self.case else None,
                "confirmed": self.confirmed,
                "status": self.status,
                "running": self.active_run_id is not None,
                "run_id": self.active_run_id,
                "last_error": self.last_error,
                "model": model_status,
                "case": self.case.model_dump(mode="json") if self.case else None,
                "missing_availability_pairs": self._missing_pairs(),
                "candidate": public(candidate) if candidate else None,
                "diagnosis": self.diagnosis.model_dump(mode="json") if self.diagnosis else None,
                "approval": self.approval.model_dump(mode="json") if self.approval else None,
                "proposals": proposals,
                "trace": self.trace,
                "artifacts": [
                    {key: value for key, value in artifact.items() if key != "bytes"}
                    | {"artifact_id": artifact_id}
                    for artifact_id, artifact in self.artifacts.items()
                ],
            }

    def _require_case(self, case_hash: str) -> None:
        if not self.case or self.case.case_hash != case_hash:
            raise StoreError("Case is stale or unavailable.")

    def _mark_historical(self) -> None:
        for artifact in self.artifacts.values():
            artifact["historical"] = True

    def _missing_pairs(self) -> int:
        if not self.case:
            return 0
        return len(self.case.volunteers) * len(self.case.shifts) - len(self.case.availability)

    def _worker_result(self, entry: dict[str, Any]) -> dict[str, Any]:
        return {
            "result_id": entry["result_id"],
            "case_hash": entry["case"].case_hash,
            "base_case_hash": self.case.case_hash if self.case else None,
            "hypothetical": entry["hypothetical"],
            "proposal_id": entry["proposal_id"],
            "solver": entry["solver"].model_dump(mode="json"),
            "verification": entry["verification"].model_dump(mode="json")
            if entry["verification"]
            else None,
            "diagnosis": entry["diagnosis"].model_dump(mode="json") if entry["diagnosis"] else None,
            "evidence": [fact.model_dump(mode="json") for fact in entry.get("evidence", ())],
        }
