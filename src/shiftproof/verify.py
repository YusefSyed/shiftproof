"""Independent, pure assignment verifier.  Deliberately has no solver dependency."""

from __future__ import annotations

from itertools import combinations

from .models import Assignment, Case, Verification, Violation, assignment_hash


def verify_assignments(
    case: Case, assignments: tuple[Assignment, ...], baseline: tuple[Assignment, ...] = ()
) -> Verification:
    violations: list[Violation] = []
    volunteers = {v.volunteer_id: v for v in case.volunteers}
    shifts = {s.shift_id: s for s in case.shifts}
    demand = {(c.shift_id, c.role): c.required_count for c in case.coverage}
    coverage_refs = {(c.shift_id, c.role): c.source_ref for c in case.coverage}
    availability = {(a.volunteer_id, a.shift_id): a.status for a in case.availability}
    seen: set[tuple[str, str, str]] = set()
    coverage = {f"{s}:{r}": 0 for s, r in demand}
    work = {v: {"minutes": 0, "shifts": 0} for v in volunteers}
    per_vs: set[tuple[str, str]] = set()
    for a in assignments:
        if a.key in seen:
            violations.append(
                Violation(
                    code="duplicate_assignment",
                    entity_ids=a.key,
                    source_refs=(
                        coverage_refs.get((a.shift_id, a.role), "policy:unique_assignment"),
                    ),
                )
            )
            continue
        seen.add(a.key)
        if (
            a.volunteer_id not in volunteers
            or a.shift_id not in shifts
            or (a.shift_id, a.role) not in demand
        ):
            refs = tuple(
                source.source_ref
                for source in (volunteers.get(a.volunteer_id), shifts.get(a.shift_id))
                if source is not None
            )
            if not refs:
                refs = ("policy:known_ids",)
            violations.append(
                Violation(
                    code="unknown_or_undemanded_assignment", entity_ids=a.key, source_refs=refs
                )
            )
            continue
        v = volunteers[a.volunteer_id]
        if a.role not in v.roles:
            violations.append(
                Violation(code="unqualified", entity_ids=a.key, source_refs=(v.source_ref,))
            )
        if (
            availability.get((a.volunteer_id, a.shift_id)) == "unavailable"
            or (a.volunteer_id, a.shift_id) not in availability
        ):
            record = next(
                (
                    item
                    for item in case.availability
                    if (item.volunteer_id, item.shift_id) == (a.volunteer_id, a.shift_id)
                ),
                None,
            )
            refs = (record.source_ref,) if record else ("policy:missing_availability_unavailable",)
            violations.append(Violation(code="unavailable", entity_ids=a.key, source_refs=refs))
        coverage[f"{a.shift_id}:{a.role}"] += 1
        if (a.volunteer_id, a.shift_id) in per_vs:
            violations.append(
                Violation(
                    code="multiple_roles",
                    entity_ids=(a.volunteer_id, a.shift_id),
                    source_refs=(shifts[a.shift_id].source_ref,),
                )
            )
        per_vs.add((a.volunteer_id, a.shift_id))
        work[a.volunteer_id]["minutes"] += shifts[a.shift_id].duration_minutes
        work[a.volunteer_id]["shifts"] += 1
    for key, required in demand.items():
        actual = coverage[f"{key[0]}:{key[1]}"]
        if actual != required:
            violations.append(
                Violation(
                    code="coverage",
                    entity_ids=key,
                    source_refs=(coverage_refs[key],),
                    details={"required": required, "actual": actual},
                )
            )
    for vid, vals in work.items():
        v = volunteers[vid]
        if vals["minutes"] > v.max_total_minutes or vals["shifts"] > v.max_shifts:
            violations.append(
                Violation(
                    code="workload_cap",
                    entity_ids=(vid,),
                    source_refs=(v.source_ref,),
                    details=vals,
                )
            )
    for vid in volunteers:
        chosen = [a for a in assignments if a.volunteer_id == vid and a.shift_id in shifts]
        for first, second in combinations(chosen, 2):
            if (
                first.shift_id != second.shift_id
                and shifts[first.shift_id].start < shifts[second.shift_id].end
                and shifts[second.shift_id].start < shifts[first.shift_id].end
            ):
                violations.append(
                    Violation(
                        code="overlap",
                        entity_ids=(vid, first.shift_id, second.shift_id),
                        source_refs=(
                            shifts[first.shift_id].source_ref,
                            shifts[second.shift_id].source_ref,
                        ),
                    )
                )
    keys = {a.key for a in assignments}
    for lock in case.locks:
        if lock.key not in keys:
            violations.append(
                Violation(
                    code="missing_lock",
                    entity_ids=(lock.lock_id, *lock.key),
                    source_refs=(lock.source_ref,),
                )
            )
    preferred = sum(
        availability.get((a.volunteer_id, a.shift_id)) == "preferred" for a in assignments
    )
    nonpreferred = sum(
        availability.get((a.volunteer_id, a.shift_id)) == "available" for a in assignments
    )
    replacement = len(set(a.key for a in baseline) - keys)
    minutes = [vals["minutes"] for vals in work.values()]
    dispersion = sum(abs(a - b) for a, b in combinations(minutes, 2))
    return Verification(
        case_hash=case.case_hash,
        candidate_hash=assignment_hash(case, assignments),
        valid=not violations,
        violations=tuple(violations),
        coverage=coverage,
        workload=work,
        preferred=preferred,
        non_preferred=nonpreferred,
        replacements=replacement,
        dispersion=dispersion,
    )
