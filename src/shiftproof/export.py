"""Deterministic, in-memory exports for independently verified schedules."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from icalendar import Calendar, Event

from .models import (
    POLICY_VERSION,
    VERIFIER_VERSION,
    Approval,
    Assignment,
    Case,
    Diagnosis,
    Phase,
    Verification,
    hash_json,
)
from .verify import verify_assignments

_SAFE_RUNTIME_KEYS = frozenset(
    {"code_version", "policy_version", "verifier_version", "runtime_version", "model_tag", "model_digest"}
)


def _safe_csv(value: object) -> object:
    """Prevent spreadsheet formula evaluation without converting numbers to strings."""
    if not isinstance(value, str):
        return value
    if value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _csv_bytes(headers: tuple[str, ...], rows: Sequence[tuple[object, ...]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([_safe_csv(value) for value in row])
    return output.getvalue().encode("utf-8")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("approval timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _zip_timestamp(approved_at: datetime) -> tuple[int, int, int, int, int, int]:
    approved = _utc(approved_at)
    if approved.year < 1980:
        raise ValueError("approval timestamp cannot be represented by ZIP")
    return (approved.year, approved.month, approved.day, approved.hour, approved.minute, approved.second)


def _zip(files: list[tuple[str, bytes]], approved_at: datetime) -> bytes:
    buffer = io.BytesIO()
    timestamp = _zip_timestamp(approved_at)
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, contents in files:
            info = ZipInfo(name, date_time=timestamp)
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, contents)
    return buffer.getvalue()


def _calendar(
    case: Case, assignments: tuple[Assignment, ...], approval: Approval, volunteer_id: str | None = None
) -> bytes:
    approved_at = _utc(approval.approved_at)
    volunteers = {volunteer.volunteer_id: volunteer for volunteer in case.volunteers}
    shifts = {shift.shift_id: shift for shift in case.shifts}
    calendar = Calendar()
    calendar.add("prodid", "-//ShiftProof//Local volunteer schedule//EN")
    calendar.add("version", "2.0")
    for assignment in sorted(assignments, key=lambda item: item.key):
        if volunteer_id is not None and assignment.volunteer_id != volunteer_id:
            continue
        shift = shifts[assignment.shift_id]
        volunteer = volunteers[assignment.volunteer_id]
        event = Event()
        snapshot = f"{approval.case_hash}:{approval.candidate_hash}:{assignment.volunteer_id}:{assignment.shift_id}:{assignment.role}"
        event.add("uid", hashlib.sha256(snapshot.encode("utf-8")).hexdigest() + "@shiftproof.local")
        event.add("dtstamp", approved_at)
        event.add("dtstart", shift.start.astimezone(UTC))
        event.add("dtend", shift.end.astimezone(UTC))
        event.add("summary", f"Volunteer shift: {shift.title} ({assignment.role})")
        event.add("description", "Verified ShiftProof volunteer schedule.")
        event.add("categories", assignment.role)
        event.add("x-shiftproof-volunteer", volunteer.volunteer_id)
        calendar.add_component(event)
    return calendar.to_ical()


def _verification_or_raise(
    case: Case, assignments: tuple[Assignment, ...], baseline: tuple[Assignment, ...], approval: Approval
) -> Verification:
    verification = verify_assignments(case, assignments, baseline)
    verification_hash = hash_json(verification.model_dump(mode="json"))
    if not verification.valid:
        raise ValueError("cannot export an invalid schedule")
    if verification.case_hash != case.case_hash or approval.case_hash != case.case_hash:
        raise ValueError("case hash does not match the approved schedule")
    if verification.candidate_hash != approval.candidate_hash:
        raise ValueError("candidate hash does not match the approval")
    if approval.verification_hash != verification_hash:
        raise ValueError("verification hash does not match the approval")
    return verification


def _safe_runtime_lock(runtime_lock: dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in sorted(runtime_lock.items())
        if key in _SAFE_RUNTIME_KEYS and isinstance(value, str)
    }


def _explanation(case: Case, verification: Verification, approval: Approval) -> bytes:
    text = "\n".join(
        (
            "# ShiftProof verified schedule",
            "",
            "This bundle was generated from canonical case data after independent verification.",
            f"Case: {case.case_id}",
            f"Approved at: {_utc(approval.approved_at).isoformat()}",
            f"Assignments: {sum(verification.coverage.values())}",
            f"Preferred assignments: {verification.preferred}",
            f"Available assignments: {verification.non_preferred}",
            f"Replacements from baseline: {verification.replacements}",
        )
    )
    return (text + "\n").encode("utf-8")


def build_bundle(
    case: Case,
    assignments: tuple[Assignment, ...],
    baseline: tuple[Assignment, ...],
    approval: Approval,
    runtime_lock: dict[str, str],
    phases: tuple[Phase, ...] = (),
) -> bytes:
    """Build a stable ZIP for an already-approved snapshot without side effects."""
    verification = _verification_or_raise(case, assignments, baseline, approval)
    volunteers = {volunteer.volunteer_id: volunteer for volunteer in case.volunteers}
    shifts = {shift.shift_id: shift for shift in case.shifts}
    ordered = tuple(sorted(assignments, key=lambda item: item.key))
    schedule_rows = [
        (
            assignment.shift_id,
            shifts[assignment.shift_id].title,
            assignment.role,
            assignment.volunteer_id,
            volunteers[assignment.volunteer_id].display_name,
            shifts[assignment.shift_id].start.astimezone(UTC).isoformat(),
            shifts[assignment.shift_id].end.astimezone(UTC).isoformat(),
        )
        for assignment in ordered
    ]
    before = {item.key for item in baseline}
    after = {item.key for item in assignments}
    change_rows = [("removed", *key) for key in sorted(before - after)] + [
        ("added", *key) for key in sorted(after - before)
    ]
    schedule_json = {
        "case_hash": case.case_hash,
        "candidate_hash": verification.candidate_hash,
        "assignments": [item.model_dump(mode="json") for item in ordered],
    }
    files: list[tuple[str, bytes]] = [
        (
            "schedule.csv",
            _csv_bytes(
                ("shift_id", "shift_title", "role", "volunteer_id", "volunteer_name", "start_utc", "end_utc"),
                schedule_rows,
            ),
        ),
        ("schedule.json", json.dumps(schedule_json, sort_keys=True, separators=(",", ":")).encode("utf-8")),
        (
            "verification.json",
            json.dumps(verification.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode("utf-8"),
        ),
        ("explanation.md", _explanation(case, verification, approval)),
        (
            "changes.csv",
            _csv_bytes(("change", "volunteer_id", "shift_id", "role"), change_rows),
        ),
        ("calendar_all.ics", _calendar(case, ordered, approval)),
    ]
    for volunteer_id in sorted(volunteers):
        files.append((f"calendars/{volunteer_id}.ics", _calendar(case, ordered, approval, volunteer_id)))
    safe_runtime = _safe_runtime_lock(runtime_lock)
    manifest = {
        "case_hash": case.case_hash,
        "candidate_hash": verification.candidate_hash,
        "approval_id": approval.approval_id,
        "approved_at": _utc(approval.approved_at).isoformat(),
        "code_version": safe_runtime.get("code_version", "unknown"),
        "policy_version": POLICY_VERSION,
        "verifier_version": VERIFIER_VERSION,
        "runtime_version": safe_runtime.get("runtime_version", "unknown"),
        "model_tag": safe_runtime.get("model_tag", "unknown"),
        "model_digest": safe_runtime.get("model_digest", "unknown"),
        "phases": [phase.model_dump(mode="json") for phase in phases],
        "runtime_lock": safe_runtime,
        "files": {name: hashlib.sha256(contents).hexdigest() for name, contents in files},
    }
    files.append(("manifest.json", json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")))
    return _zip(files, approval.approved_at)


def build_diagnosis_bundle(case: Case, diagnosis: Diagnosis) -> bytes:
    """Build the limited diagnosis-only artifact; it intentionally has no calendar."""
    if diagnosis.case_hash != case.case_hash:
        raise ValueError("diagnosis case hash does not match the current case")
    diagnosis_json = json.dumps(diagnosis.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode("utf-8")
    fact_lines = [f"- {fact.code}: {', '.join(fact.entity_ids)}" for fact in diagnosis.facts]
    text = "\n".join(
        ["# ShiftProof diagnosis", "", f"Status: {diagnosis.status}", f"Evidence: {diagnosis.proof_kind}", "", *fact_lines]
    ) + "\n"
    # Diagnosis has no approval timestamp; its deterministic ZIP timestamp is the ZIP epoch.
    return _zip([("diagnosis.json", diagnosis_json), ("explanation.md", text.encode("utf-8"))], datetime(1980, 1, 1, tzinfo=UTC))
