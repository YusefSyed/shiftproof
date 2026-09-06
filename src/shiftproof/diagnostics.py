"""Bounded, conservative infeasibility explanations."""

from __future__ import annotations

import time

from .models import Case, Diagnosis, Fact
from .solver import solve_case


def diagnose_case(case: Case, *, max_calls: int = 24, time_limit: float = 30.0) -> Diagnosis:
    started = time.monotonic()
    if max_calls <= 0 or time_limit <= 0:
        return Diagnosis(
            case_hash=case.case_hash,
            status="UNKNOWN",
            proof_kind="bounded",
            limitation="No solver budget was available for diagnosis.",
        )
    demands = {(c.shift_id, c.role): c for c in case.coverage if c.required_count}
    av = {
        (a.volunteer_id, a.shift_id): a.status
        for a in case.availability
        if a.status != "unavailable"
    }
    volunteers = {v.volunteer_id: v for v in case.volunteers}
    facts = []
    for (sid, role), cov in demands.items():
        eligible = [
            v for v in volunteers.values() if role in v.roles and (v.volunteer_id, sid) in av
        ]
        if len(eligible) < cov.required_count:
            facts.append(
                Fact(
                    fact_id=f"eligible:{sid}:{role}",
                    code="insufficient_eligible",
                    entity_ids=(sid, role),
                    source_refs=(cov.source_ref,),
                    details={"eligible": len(eligible), "required": cov.required_count},
                )
            )
    for volunteer in volunteers.values():
        for role in case.roles:
            sole = []
            for (shift_id, demand_role), coverage in demands.items():
                if demand_role != role:
                    continue
                eligible = [
                    candidate
                    for candidate in volunteers.values()
                    if role in candidate.roles and (candidate.volunteer_id, shift_id) in av
                ]
                if len(eligible) == 1 and eligible[0].volunteer_id == volunteer.volunteer_id:
                    sole.append(coverage)
            required_shifts = sum(coverage.required_count for coverage in sole)
            required_minutes = sum(
                coverage.required_count
                * next(
                    shift.duration_minutes
                    for shift in case.shifts
                    if shift.shift_id == coverage.shift_id
                )
                for coverage in sole
            )
            if sole and (
                required_shifts > volunteer.max_shifts
                or required_minutes > volunteer.max_total_minutes
            ):
                involved_shifts = tuple(coverage.shift_id for coverage in sole)
                availability_refs = tuple(
                    availability.source_ref
                    for availability in case.availability
                    if availability.shift_id in involved_shifts
                    and role in volunteers[availability.volunteer_id].roles
                )
                facts.append(
                    Fact(
                        fact_id=f"sole-capacity:{volunteer.volunteer_id}:{role}",
                        code="sole_eligible_capacity",
                        entity_ids=(volunteer.volunteer_id, *involved_shifts, role),
                        source_refs=tuple(coverage.source_ref for coverage in sole)
                        + (volunteer.source_ref,)
                        + availability_refs
                        + ("policy:missing_availability_unavailable",),
                        details={
                            "required_shifts": required_shifts,
                            "max_shifts": volunteer.max_shifts,
                            "required_minutes": required_minutes,
                            "max_total_minutes": volunteer.max_total_minutes,
                        },
                    )
                )
    if facts:
        return Diagnosis(
            case_hash=case.case_hash,
            status="INFEASIBLE",
            proof_kind="direct",
            facts=tuple(facts),
            elapsed_seconds=time.monotonic() - started,
        )
    remaining_time = time_limit - (time.monotonic() - started)
    if remaining_time <= 0:
        return Diagnosis(
            case_hash=case.case_hash,
            status="UNKNOWN",
            proof_kind="bounded",
            limitation="Diagnosis time budget expired before a solver call.",
        )
    full = solve_case(case, time_limit=min(remaining_time, 10), optimize=False)
    calls = 1
    if full.status != "INFEASIBLE":
        return Diagnosis(
            case_hash=case.case_hash,
            status=full.status,
            proof_kind="none",
            solver_calls=calls,
            elapsed_seconds=time.monotonic() - started,
            limitation="Original feasibility was not proved infeasible.",
        )
    if calls >= max_calls or time.monotonic() - started >= time_limit:
        return Diagnosis(
            case_hash=case.case_hash,
            status="INFEASIBLE",
            proof_kind="bounded",
            solver_calls=calls,
            elapsed_seconds=time.monotonic() - started,
            limitation="Solver budget expired before conflict attribution.",
        )
    all_bounds = frozenset(demands)
    remaining_time = time_limit - (time.monotonic() - started)
    if remaining_time <= 0:
        return Diagnosis(
            case_hash=case.case_hash,
            status="INFEASIBLE",
            proof_kind="bounded",
            solver_calls=calls,
            elapsed_seconds=time.monotonic() - started,
            limitation="Diagnosis time budget expired before conflict attribution.",
        )
    empty = solve_case(
        case,
        lower_bounds=frozenset(),
        optimize=False,
        time_limit=remaining_time,
    )
    calls += 1
    if empty.status == "INFEASIBLE":
        return Diagnosis(
            case_hash=case.case_hash,
            status="INFEASIBLE",
            proof_kind="fixed_conflict",
            solver_calls=calls,
            elapsed_seconds=time.monotonic() - started,
            limitation="Fixed constraints are infeasible without coverage lower bounds.",
        )
    if empty.status != "OPTIMAL" and empty.status != "FEASIBLE":
        return Diagnosis(
            case_hash=case.case_hash,
            status="UNKNOWN",
            proof_kind="bounded",
            solver_calls=calls,
            elapsed_seconds=time.monotonic() - started,
            limitation="Could not establish fixed-constraint feasibility.",
        )
    remaining = set(all_bounds)
    definitive = True
    for demand in sorted(all_bounds):
        remaining_time = time_limit - (time.monotonic() - started)
        if calls >= max_calls or remaining_time <= 0:
            definitive = False
            break
        trial = frozenset(remaining - {demand})
        result = solve_case(
            case,
            lower_bounds=trial,
            optimize=False,
            time_limit=remaining_time,
        )
        calls += 1
        if result.status == "INFEASIBLE":
            remaining.remove(demand)
        elif result.status not in {"OPTIMAL", "FEASIBLE"}:
            definitive = False
    return Diagnosis(
        case_hash=case.case_hash,
        status="INFEASIBLE",
        proof_kind="demand_conflict",
        conflict_demands=tuple(f"{s}:{r}" for s, r in sorted(remaining)),
        subset_minimal=False,
        solver_calls=calls,
        elapsed_seconds=time.monotonic() - started,
        limitation="Sufficient bounded deletion diagnosis."
        if definitive
        else "Bounded diagnosis retained unknown deletion tests.",
    )
