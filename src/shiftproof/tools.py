"""Exactly six allowlisted agent tools, without approval or external effects."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Callable
from typing import Any

from strands import tool

from shiftproof.config import MAX_SOLVES, MAX_TOOL_CALLS
from shiftproof.diagnostics import diagnose_case
from shiftproof.evidence import diagnosis_facts, sanitized_case, verified_facts
from shiftproof.models import Assignment, Case, InputError, Proposal, SolverResult
from shiftproof.proposals import apply_to_copy, make_proposal
from shiftproof.solver import solve_case
from shiftproof.verify import verify_assignments

TOOL_NAMES = frozenset({"inspect_case", "solve_schedule", "diagnose_infeasibility",
                        "propose_change", "simulate_change", "prepare_review"})


def safe_arguments(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: safe_arguments(v) for k, v in value.items()
                if isinstance(k, str) and re.fullmatch(r"[a-z_]{1,40}", k)}
    if isinstance(value, (list, tuple)):
        return [safe_arguments(v) for v in value[:40]]
    if type(value) in (int, bool) or value is None:
        return value
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_:.-]{0,160}", value):
        return value
    return "[invalid argument omitted]"


class ToolContext:
    def __init__(self, case: Case, baseline: tuple[Assignment, ...],
                 emit: Callable[[dict], None], prior: dict | None = None):
        self.case = case
        self.baseline = baseline
        self.emit = emit
        self.results: dict[str, dict] = {}
        self.proposals: dict[str, Proposal] = {}
        self.review_result_id: str | None = None
        self.current_result_id: str | None = None
        self.solves = 0
        self.calls = 0
        self.invalid_calls = 0
        self.abort_reason: str | None = None
        self.new_result_ids: set[str] = set()
        self.new_proposal_ids: set[str] = set()
        if prior:
            for row in prior.get("proposals", []):
                proposal = Proposal.model_validate(row)
                if proposal.base_case_hash == case.case_hash:
                    self.proposals[proposal.proposal_id] = proposal
            for row in prior.get("results", []):
                if row.get("base_case_hash") == case.case_hash:
                    self.results[row["result_id"]] = row
                    if not row.get("hypothetical"):
                        self.current_result_id = row["result_id"]

    def call(self, name: str, arguments: dict, action: Callable[[], dict]) -> dict:
        self.calls += 1
        if self.calls > MAX_TOOL_CALLS or self.abort_reason:
            raise InputError("The local action limit was reached.")
        started = time.monotonic()
        self.emit({"type": "tool_start", "tool": name, "arguments": safe_arguments(arguments),
                   "status": "running"})
        try:
            result = action()
        except (InputError, ValueError, KeyError) as exc:
            self.invalid_calls += 1
            if self.invalid_calls > 1:
                self.abort_reason = "Too many invalid tool actions."
            self.emit({"type": "tool_end", "tool": name, "status": "rejected",
                       "duration": round(time.monotonic() - started, 3),
                       "detail": "The requested action failed validation."})
            raise InputError("The action was rejected. Use current registered IDs and the tool schema.") from exc
        self.emit({"type": "tool_end", "tool": name, "status": "complete",
                   "result_id": result.get("result_id") or result.get("proposal_id"),
                   "duration": round(time.monotonic() - started, 3)})
        return result

    def _check_solve_budget(self) -> None:
        self.solves += 1
        if self.solves > MAX_SOLVES:
            raise InputError("The solve/simulation budget was reached.")

    def _register(self, case: Case, solved: SolverResult, proposal: Proposal | None = None) -> dict:
        result_id = "R_" + uuid.uuid4().hex[:16]
        verification = None
        diagnosis = None
        evidence = []
        if solved.status in ("OPTIMAL", "FEASIBLE"):
            checked = verify_assignments(case, solved.assignments, self.baseline)
            verification = checked.model_dump(mode="json")
            if not checked.valid:
                raise InputError("Independent verification rejected the solver candidate.")
            evidence = [fact.model_dump(mode="json") for fact in verified_facts(case, result_id, checked)]
        if solved.status == "INFEASIBLE" and proposal is not None:
            diagnosed = diagnose_case(case)
            diagnosis = diagnosed.model_dump(mode="json")
            evidence = [fact.model_dump(mode="json") for fact in diagnosis_facts(result_id, diagnosed)]
        record = {"result_id": result_id, "case_hash": case.case_hash,
                  "base_case_hash": self.case.case_hash, "hypothetical": proposal is not None,
                  "proposal_id": proposal.proposal_id if proposal else None,
                  "solver": solved.model_dump(mode="json"), "verification": verification,
                  "diagnosis": diagnosis, "evidence": evidence}
        self.results[result_id] = record
        self.new_result_ids.add(result_id)
        if proposal is None:
            self.current_result_id = result_id
        return self.summary(record)

    @staticmethod
    def summary(record: dict) -> dict:
        checked = record.get("verification")
        summary = {"result_id": record["result_id"], "case_hash": record["case_hash"],
                   "status": record["solver"]["status"], "hypothetical": record["hypothetical"],
                   "evidence": record.get("evidence", []),
                   "evidence_ids": [f["fact_id"] for f in record.get("evidence", [])]}
        if checked:
            summary["verified"] = {key: checked[key] for key in
                                   ("valid", "preferred", "non_preferred", "replacements", "dispersion")}
        if record.get("diagnosis"):
            summary["diagnosis"] = record["diagnosis"]
        return summary

    def inspect(self) -> dict:
        return sanitized_case(self.case)

    def solve(self) -> dict:
        self._check_solve_budget()
        return self._register(self.case, solve_case(self.case, self.baseline))

    def diagnose(self) -> dict:
        if self.current_result_id is None:
            raise InputError("First solve the current case.")
        record = self.results[self.current_result_id]
        if record["solver"]["status"] != "INFEASIBLE":
            raise InputError("Only a proven-infeasible current case can be diagnosed.")
        if not record.get("diagnosis"):
            report = diagnose_case(self.case)
            record["diagnosis"] = report.model_dump(mode="json")
            record["evidence"] = [f.model_dump(mode="json")
                                  for f in diagnosis_facts(record["result_id"], report)]
            self.new_result_ids.add(record["result_id"])
        return self.summary(record)

    def propose(self, operations: list[dict]) -> dict:
        proposal = make_proposal(self.case, operations)
        for old in self.proposals.values():
            if old.proposal_hash == proposal.proposal_hash:
                return old.model_dump(mode="json")
        self.proposals[proposal.proposal_id] = proposal
        self.new_proposal_ids.add(proposal.proposal_id)
        return {**proposal.model_dump(mode="json"), "applied": False}

    def simulate(self, proposal_id: str) -> dict:
        if proposal_id not in self.proposals:
            raise InputError("Unknown proposal.")
        for record in self.results.values():
            if record.get("proposal_id") == proposal_id:
                return self.summary(record)
        self._check_solve_budget()
        proposal = self.proposals[proposal_id]
        scenario = apply_to_copy(self.case, proposal)
        return self._register(scenario, solve_case(scenario, self.baseline), proposal)

    def review(self, result_id: str, evidence_ids: list[str]) -> dict:
        if result_id not in self.results:
            raise InputError("Unknown result.")
        record = self.results[result_id]
        allowed = {f["fact_id"] for f in record.get("evidence", [])}
        if len(evidence_ids) > 40 or any(key not in allowed for key in evidence_ids):
            raise InputError("Unknown evidence reference.")
        if allowed and not evidence_ids:
            raise InputError("Select at least one returned evidence ID.")
        self.review_result_id = result_id
        return {"result_id": result_id, "review_ready": True,
                "hypothetical": record["hypothetical"], "approved": False,
                "evidence_ids": evidence_ids}

    def payload(self) -> dict:
        return {"results": [r for k, r in self.results.items() if k in self.new_result_ids],
                "proposals": [p.model_dump(mode="json") for k, p in self.proposals.items()
                              if k in self.new_proposal_ids],
                "review_result_id": self.review_result_id, "error": self.abort_reason}


def make_tools(context: ToolContext) -> list:
    @tool
    def inspect_case() -> dict:
        """Read the current confirmed case as IDs, qualifications, availability and limits."""
        return context.call("inspect_case", {}, context.inspect)

    @tool
    def solve_schedule() -> dict:
        """Solve the current case and independently verify it. Returns result and evidence IDs."""
        return context.call("solve_schedule", {}, context.solve)

    @tool
    def diagnose_infeasibility() -> dict:
        """Explain a current case after solve_schedule returns INFEASIBLE. Never edit its constraints."""
        return context.call("diagnose_infeasibility", {}, context.diagnose)

    @tool
    def propose_change(operations: list[dict]) -> dict:
        """Propose 1-4 typed changes, never apply them. Operations: set_availability with volunteer_id,
        shift_id,status; set_limits with volunteer_id,max_total_minutes,max_shifts; remove_lock with
        lock_id. Each operation includes an op field. Do not change coverage or qualifications.
        """
        return context.call("propose_change", {"operations": operations},
                            lambda: context.propose(operations))

    @tool
    def simulate_change(proposal_id: str) -> dict:
        """Test a registered proposal on an isolated copy. Results stay hypothetical, not approved."""
        return context.call("simulate_change", {"proposal_id": proposal_id},
                            lambda: context.simulate(proposal_id))

    @tool
    def prepare_review(result_id: str, evidence_ids: list[str]) -> dict:
        """Prepare a review using a returned result_id and its exact evidence_ids. Cannot approve/export."""
        return context.call("prepare_review", {"result_id": result_id, "evidence_ids": evidence_ids},
                            lambda: context.review(result_id, evidence_ids))

    return [inspect_case, solve_schedule, diagnose_infeasibility, propose_change,
            simulate_change, prepare_review]
