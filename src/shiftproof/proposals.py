"""Typed hypothetical edits. This module has no approval or session capability."""

from __future__ import annotations

import uuid

from pydantic import TypeAdapter

from shiftproof.ingest import validate_case
from shiftproof.models import (
    Availability,
    Case,
    InputError,
    Operation,
    Proposal,
    RemoveLock,
    SetAvailability,
    SetLimits,
    hash_json,
)

OPERATIONS = TypeAdapter(tuple[Operation, ...])


def make_proposal(case: Case, operations: list[dict]) -> Proposal:
    try:
        parsed = OPERATIONS.validate_python(operations)
    except ValueError:
        raise InputError("Invalid change operation. Use the documented IDs, fields and limits.") from None
    if not 1 <= len(parsed) <= 4:
        raise InputError("A proposal must contain one to four operations.")
    volunteers = {v.volunteer_id: v for v in case.volunteers}
    shifts = {s.shift_id for s in case.shifts}
    locks = {lock.lock_id for lock in case.locks}
    seen: set[tuple[str, ...]] = set()
    confirmations: list[str] = []
    for operation in parsed:
        key: tuple[str, ...]
        if isinstance(operation, SetAvailability):
            key = ("availability", operation.volunteer_id, operation.shift_id)
            if operation.volunteer_id not in volunteers or operation.shift_id not in shifts:
                raise InputError("The proposal refers to an unknown volunteer or shift.")
            confirmations.append("Confirm the volunteer's availability change.")
        elif isinstance(operation, SetLimits):
            key = ("limits", operation.volunteer_id)
            if operation.volunteer_id not in volunteers:
                raise InputError("The proposal refers to an unknown volunteer.")
            confirmations.append("Confirm both workload limits with the volunteer.")
        else:
            key = ("lock", operation.lock_id)
            if operation.lock_id not in locks:
                raise InputError("The proposal refers to an unknown pinned assignment.")
            confirmations.append("Confirm release of the pinned assignment.")
        if key in seen:
            raise InputError("Repeated writes to one target are not permitted in a proposal.")
        seen.add(key)
    payload = {"base_case_hash": case.case_hash,
               "operations": [op.model_dump() for op in parsed]}
    return Proposal(proposal_id="P_" + uuid.uuid4().hex[:16], base_case_hash=case.case_hash,
                    operations=parsed, proposal_hash=hash_json(payload),
                    confirmations=tuple(dict.fromkeys(confirmations)))


def apply_to_copy(case: Case, proposal: Proposal) -> Case:
    if proposal.base_case_hash != case.case_hash:
        raise InputError("The proposal is stale. Review the current case first.")
    expected = hash_json({"base_case_hash": case.case_hash,
                          "operations": [op.model_dump() for op in proposal.operations]})
    if expected != proposal.proposal_hash:
        raise InputError("Proposal hash mismatch.")
    availability = {(a.volunteer_id, a.shift_id): a for a in case.availability}
    volunteers = {v.volunteer_id: v for v in case.volunteers}
    locks = {lock.lock_id: lock for lock in case.locks}
    for op in proposal.operations:
        ref = f"proposal:{proposal.proposal_id}"
        if isinstance(op, SetAvailability):
            old = availability.get((op.volunteer_id, op.shift_id))
            availability[(op.volunteer_id, op.shift_id)] = Availability(
                volunteer_id=op.volunteer_id, shift_id=op.shift_id, status=op.status,
                note=old.note if old else "", source_ref=ref)
        elif isinstance(op, SetLimits):
            volunteers[op.volunteer_id] = volunteers[op.volunteer_id].model_copy(update={
                "max_total_minutes": op.max_total_minutes, "max_shifts": op.max_shifts,
                "source_ref": ref})
        elif isinstance(op, RemoveLock):
            del locks[op.lock_id]
    scenario = case.model_copy(update={
        "availability": tuple(availability[k] for k in sorted(availability)),
        "volunteers": tuple(volunteers[k] for k in sorted(volunteers)),
        "locks": tuple(locks[k] for k in sorted(locks)),
    })
    return validate_case(scenario)
