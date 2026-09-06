"""Immutable contracts shared by the solver, independent verifier, and application."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints

Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,31}$")]
Role = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,23}$")]
AvailabilityStatus = Literal["preferred", "available", "unavailable"]
SolverStatus = Literal["OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNKNOWN", "MODEL_INVALID"]
POLICY_VERSION = "1"
VERIFIER_VERSION = "1"


def hash_json(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Volunteer(FrozenModel):
    volunteer_id: Identifier
    display_name: str = Field(min_length=1, max_length=80)
    roles: tuple[Role, ...] = Field(min_length=1, max_length=3)
    max_total_minutes: StrictInt = Field(ge=0, le=10080)
    max_shifts: StrictInt = Field(ge=0, le=12)
    source_ref: str = ""


class Shift(FrozenModel):
    shift_id: Identifier
    title: str = Field(min_length=1, max_length=80)
    start: datetime
    end: datetime
    source_ref: str = ""

    @property
    def duration_minutes(self) -> int:
        return int((self.end.timestamp() - self.start.timestamp()) / 60)


class Coverage(FrozenModel):
    shift_id: Identifier
    role: Role
    required_count: StrictInt = Field(ge=0, le=20)
    source_ref: str = ""


class Availability(FrozenModel):
    volunteer_id: Identifier
    shift_id: Identifier
    status: AvailabilityStatus
    note: str = Field(default="", max_length=500)
    source_ref: str = ""


class Assignment(FrozenModel):
    volunteer_id: Identifier
    shift_id: Identifier
    role: Role

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.volunteer_id, self.shift_id, self.role)


class Lock(Assignment):
    lock_id: Identifier
    source_ref: str = ""


class Case(FrozenModel):
    schema_version: Literal[1] = 1
    case_id: Identifier
    timezone: str
    week_start: date
    roles: tuple[Role, ...] = Field(min_length=1, max_length=3)
    locks: tuple[Lock, ...] = ()
    volunteers: tuple[Volunteer, ...] = Field(min_length=1, max_length=20)
    shifts: tuple[Shift, ...] = Field(min_length=1, max_length=12)
    coverage: tuple[Coverage, ...]
    availability: tuple[Availability, ...]
    input_bundle_hash: str

    @property
    def case_hash(self) -> str:
        return hash_json(self.model_dump(mode="json"))


class Violation(FrozenModel):
    code: str
    entity_ids: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    details: dict[str, Any] = Field(default_factory=dict)


class InputError(ValueError):
    def __init__(self, message: str, issues: tuple[Violation, ...] = ()):
        super().__init__(message)
        self.issues = issues


class Phase(FrozenModel):
    name: str
    status: SolverStatus
    value: int | None = None
    proven_optimal: bool = False


class SolverResult(FrozenModel):
    case_hash: str
    status: SolverStatus
    assignments: tuple[Assignment, ...] = ()
    phases: tuple[Phase, ...] = ()
    elapsed_seconds: float = 0
    error: str | None = None


def assignment_hash(case: Case, assignments: tuple[Assignment, ...]) -> str:
    return hash_json({"case_hash": case.case_hash,
                      "assignments": [a.model_dump() for a in sorted(assignments, key=lambda a: a.key)],
                      "policy_version": POLICY_VERSION})


class Verification(FrozenModel):
    case_hash: str
    candidate_hash: str
    verifier_version: str = VERIFIER_VERSION
    valid: bool
    violations: tuple[Violation, ...] = ()
    coverage: dict[str, int] = Field(default_factory=dict)
    workload: dict[str, dict[str, int]] = Field(default_factory=dict)
    preferred: int = 0
    non_preferred: int = 0
    replacements: int = 0
    dispersion: int = 0


class Fact(FrozenModel):
    fact_id: str
    code: str
    entity_ids: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    details: dict[str, Any] = Field(default_factory=dict)


class Diagnosis(FrozenModel):
    case_hash: str
    status: str
    proof_kind: str
    facts: tuple[Fact, ...] = ()
    conflict_demands: tuple[str, ...] = ()
    subset_minimal: bool = False
    solver_calls: int = 0
    elapsed_seconds: float = 0
    limitation: str = ""


class SetAvailability(FrozenModel):
    op: Literal["set_availability"]
    volunteer_id: Identifier
    shift_id: Identifier
    status: AvailabilityStatus


class SetLimits(FrozenModel):
    op: Literal["set_limits"]
    volunteer_id: Identifier
    max_total_minutes: StrictInt = Field(ge=0, le=10080)
    max_shifts: StrictInt = Field(ge=0, le=12)


class RemoveLock(FrozenModel):
    op: Literal["remove_lock"]
    lock_id: Identifier


Operation = Annotated[SetAvailability | SetLimits | RemoveLock, Field(discriminator="op")]


class Proposal(FrozenModel):
    proposal_id: str
    base_case_hash: str
    operations: tuple[Operation, ...] = Field(min_length=1, max_length=4)
    proposal_hash: str
    confirmations: tuple[str, ...] = ()


class Approval(FrozenModel):
    approval_id: str
    case_hash: str
    candidate_hash: str
    verification_hash: str
    session_id: str
    approved_at: datetime
