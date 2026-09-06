"""Deterministic facts exposed to the model and rendered to the coordinator."""

from __future__ import annotations

from shiftproof.models import Case, Diagnosis, Fact, Verification


def verified_facts(case: Case, result_id: str, verification: Verification) -> tuple[Fact, ...]:
    facts = [Fact(fact_id=f"{result_id}:verification", code="independent_verification",
                  details={"valid": verification.valid, "preferred": verification.preferred,
                           "non_preferred": verification.non_preferred,
                           "replacements": verification.replacements,
                           "dispersion": verification.dispersion},
                  source_refs=("policy:independent_verifier",))]
    for demand in case.coverage:
        key = f"{demand.shift_id}:{demand.role}"
        facts.append(Fact(fact_id=f"{result_id}:coverage:{key}", code="coverage",
                          entity_ids=(demand.shift_id, demand.role),
                          source_refs=(demand.source_ref,),
                          details={"required": demand.required_count,
                                   "assigned": verification.coverage.get(key, 0)}))
    return tuple(facts)


def diagnosis_facts(result_id: str, diagnosis: Diagnosis) -> tuple[Fact, ...]:
    facts = [fact.model_copy(update={"fact_id": f"{result_id}:{fact.fact_id}"})
             for fact in diagnosis.facts]
    if not facts:
        facts.append(Fact(fact_id=f"{result_id}:diagnosis", code="bounded_diagnosis",
                          entity_ids=diagnosis.conflict_demands,
                          details={"status": diagnosis.status, "proof_kind": diagnosis.proof_kind,
                                   "subset_minimal": diagnosis.subset_minimal,
                                   "solver_calls": diagnosis.solver_calls},
                          source_refs=("policy:bounded_diagnosis",)))
    return tuple(facts)


def sanitized_case(case: Case) -> dict:
    availability = {}
    for volunteer in case.volunteers:
        availability[volunteer.volunteer_id] = {
            status: [a.shift_id for a in case.availability
                     if a.volunteer_id == volunteer.volunteer_id and a.status == status]
            for status in ("preferred", "available")
        }
    return {
        "case_hash": case.case_hash, "timezone": case.timezone,
        "missing_availability": "unavailable", "coverage_interpretation": "exact",
        "volunteers": [{"id": v.volunteer_id, "roles": v.roles,
                         "max_total_minutes": v.max_total_minutes, "max_shifts": v.max_shifts}
                        for v in case.volunteers],
        "shifts": [{"id": s.shift_id, "start": s.start.isoformat(), "end": s.end.isoformat(),
                    "minutes": s.duration_minutes} for s in case.shifts],
        "coverage": [{"shift_id": d.shift_id, "role": d.role, "required": d.required_count}
                     for d in case.coverage],
        "availability": availability,
        "locks": [{"lock_id": lock.lock_id, "volunteer_id": lock.volunteer_id,
                   "shift_id": lock.shift_id, "role": lock.role} for lock in case.locks],
    }
