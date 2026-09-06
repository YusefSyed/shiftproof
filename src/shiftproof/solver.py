"""Deterministic CP-SAT scheduler with explicit lexicographic phases."""

from __future__ import annotations

import time
from itertools import combinations

from ortools.sat.python import cp_model

from .models import Assignment, Case, Phase, SolverResult, SolverStatus


def _status(code: cp_model.CpSolverStatus) -> SolverStatus:
    statuses: dict[cp_model.CpSolverStatus, SolverStatus] = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
    }
    return statuses.get(code, "UNKNOWN")


def solve_case(
    case: Case,
    baseline: tuple[Assignment, ...] = (),
    *,
    time_limit: float = 10.0,
    lower_bounds: frozenset[tuple[str, str]] | None = None,
    optimize: bool = True,
) -> SolverResult:
    started = time.monotonic()
    model = cp_model.CpModel()
    demands = {(c.shift_id, c.role): c.required_count for c in case.coverage}
    volunteers = {v.volunteer_id: v for v in case.volunteers}
    shifts = {s.shift_id: s for s in case.shifts}
    available = {
        (a.volunteer_id, a.shift_id): a.status
        for a in case.availability
        if a.status != "unavailable"
    }
    keys = [
        (vid, sid, role)
        for (sid, role), required in demands.items()
        if required
        for vid, v in volunteers.items()
        if role in v.roles and (vid, sid) in available
    ]
    variables = {key: model.new_bool_var("x_" + "_".join(key)) for key in keys}
    for (sid, role), required in demands.items():
        values = [var for (vid, s, r), var in variables.items() if s == sid and r == role]
        model.add(sum(values) <= required)
        if lower_bounds is None or (sid, role) in lower_bounds:
            model.add(sum(values) >= required)
    for vid, sid in {(v, s) for v, s, _ in keys}:
        model.add(sum(var for (v, s, _), var in variables.items() if (v, s) == (vid, sid)) <= 1)
    for vid, volunteer in volunteers.items():
        model.add(
            sum(
                shifts[sid].duration_minutes * var
                for (v, sid, _), var in variables.items()
                if v == vid
            )
            <= volunteer.max_total_minutes
        )
        model.add(
            sum(var for (v, _, _), var in variables.items() if v == vid) <= volunteer.max_shifts
        )
        these = [(sid, var) for (v, sid, _), var in variables.items() if v == vid]
        for (s1, _), (s2, _) in combinations(these, 2):
            if s1 != s2 and shifts[s1].start < shifts[s2].end and shifts[s2].start < shifts[s1].end:
                model.add(
                    sum(
                        var
                        for (v, sid, _), var in variables.items()
                        if v == vid and sid in (s1, s2)
                    )
                    <= 1
                )
    for lock in case.locks:
        variable = variables.get(lock.key)
        if variable is None:
            return SolverResult(
                case_hash=case.case_hash,
                status="INFEASIBLE",
                elapsed_seconds=time.monotonic() - started,
            )
        model.add(variable == 1)
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 1

    def run() -> cp_model.CpSolverStatus:
        remain = max(0.001, time_limit - (time.monotonic() - started))
        solver.parameters.max_time_in_seconds = remain
        return solver.Solve(model)

    code = run()
    status = _status(code)
    phases = [Phase(name="feasibility", status=status, proven_optimal=status == "OPTIMAL")]
    if status in {"INFEASIBLE", "UNKNOWN", "MODEL_INVALID"} or not optimize:
        return SolverResult(
            case_hash=case.case_hash,
            status=status,
            phases=tuple(phases),
            elapsed_seconds=time.monotonic() - started,
        )

    def incumbent() -> tuple[Assignment, ...]:
        return tuple(
            sorted(
                (
                    Assignment(volunteer_id=v, shift_id=s, role=r)
                    for (v, s, r), x in variables.items()
                    if solver.Value(x)
                ),
                key=lambda assignment: assignment.key,
            )
        )

    assigned = incumbent()
    old = {a.key for a in baseline}
    objectives = [
        ("replacements", sum((1 - variables[k]) if k in variables else 1 for k in old)),
        (
            "non_preferred",
            sum(x for (v, s, _), x in variables.items() if available[(v, s)] == "available"),
        ),
        ("dispersion", None),
    ]
    # Linearize pairwise absolute workload differences for the final phase.
    loads = {
        v: sum(shifts[s].duration_minutes * x for (vv, s, _), x in variables.items() if vv == v)
        for v in volunteers
    }
    diffs = []
    for a, b in combinations(volunteers, 2):
        d = model.new_int_var(0, 10080, "diff_" + a + "_" + b)
        model.add_abs_equality(d, loads[a] - loads[b])
        diffs.append(d)
    objectives[-1] = ("dispersion", sum(diffs))
    for name, objective in objectives:
        if objective is None:
            continue
        model.minimize(objective)
        code = run()
        phase_status = _status(code)
        if phase_status in {"OPTIMAL", "FEASIBLE"}:
            value = int(solver.ObjectiveValue())
            assigned = incumbent()
            phases.append(
                Phase(
                    name=name,
                    status=phase_status,
                    value=value,
                    proven_optimal=phase_status == "OPTIMAL",
                )
            )
            if phase_status == "OPTIMAL":
                model.add(objective == value)
            else:
                break
        else:
            phases.append(Phase(name=name, status=phase_status))
            break
    return SolverResult(
        case_hash=case.case_hash,
        status="OPTIMAL" if all(p.proven_optimal for p in phases) else "FEASIBLE",
        assignments=assigned,
        phases=tuple(phases),
        elapsed_seconds=time.monotonic() - started,
    )
