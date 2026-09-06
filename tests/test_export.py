import csv
import hashlib
import io
import json
from datetime import UTC, datetime
from zipfile import ZipFile

import pytest
from icalendar import Calendar

from shiftproof.export import build_bundle, build_diagnosis_bundle
from shiftproof.models import Approval, Assignment, Diagnosis, hash_json
from shiftproof.solver import solve_case
from shiftproof.verify import verify_assignments

from .domain_helpers import fixture


def approval_for(case, assignments, baseline=()):
    verification = verify_assignments(case, assignments, baseline)
    return Approval(
        approval_id="APR1",
        case_hash=case.case_hash,
        candidate_hash=verification.candidate_hash,
        verification_hash=hash_json(verification.model_dump(mode="json")),
        session_id="SESSION1",
        approved_at=datetime(2026, 9, 6, 16, 0, tzinfo=UTC),
    )


def bundle_files(data):
    with ZipFile(io.BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_schedule_bundle_is_readable_and_deterministic():
    case = fixture()
    assignments = solve_case(case).assignments
    approval = approval_for(case, assignments)
    first = build_bundle(
        case, assignments, (), approval, {"model_tag": "local-qwen", "model_digest": "abc"}
    )
    second = build_bundle(
        case, assignments, (), approval, {"model_tag": "local-qwen", "model_digest": "abc"}
    )
    assert first == second
    files = bundle_files(first)
    assert {
        "schedule.csv",
        "schedule.json",
        "verification.json",
        "explanation.md",
        "changes.csv",
        "calendar_all.ics",
        "manifest.json",
    } <= files.keys()
    assert {f"calendars/V0{i}.ics" for i in range(1, 7)} <= files.keys()
    assert list(csv.reader(io.StringIO(files["schedule.csv"].decode())))[0] == [
        "shift_id",
        "shift_title",
        "role",
        "volunteer_id",
        "volunteer_name",
        "start_utc",
        "end_utc",
    ]
    calendar = Calendar.from_ical(files["calendar_all.ics"])
    events = [item for item in calendar.subcomponents if item.name == "VEVENT"]
    assert len(events) == len(assignments)
    assert all("ATTENDEE" not in event and "METHOD" not in event for event in events)
    manifest = json.loads(files["manifest.json"])
    assert manifest["files"]["schedule.csv"] == hashlib.sha256(files["schedule.csv"]).hexdigest()


def test_rejects_invalid_stale_and_verification_mismatch():
    case = fixture()
    assignments = solve_case(case).assignments
    approval = approval_for(case, assignments)
    bad = assignments + (Assignment(volunteer_id="V01", shift_id="S1", role="lead"),)
    with pytest.raises(ValueError, match="invalid"):
        build_bundle(case, bad, (), approval, {})
    with pytest.raises(ValueError, match="candidate"):
        build_bundle(
            case, assignments, (), approval.model_copy(update={"candidate_hash": "stale"}), {}
        )
    with pytest.raises(ValueError, match="verification"):
        build_bundle(
            case, assignments, (), approval.model_copy(update={"verification_hash": "stale"}), {}
        )


def test_csv_formula_text_is_neutralized():
    case = fixture()
    volunteer = case.volunteers[0].model_copy(update={"display_name": "  =SUM(1,1)"})
    case = case.model_copy(update={"volunteers": (volunteer, *case.volunteers[1:])})
    assignments = solve_case(case).assignments
    approval = approval_for(case, assignments)
    files = bundle_files(build_bundle(case, assignments, (), approval, {}))
    rows = list(csv.reader(io.StringIO(files["schedule.csv"].decode())))
    assert "'  =SUM(1,1)" in [row[4] for row in rows]


def test_diagnosis_bundle_has_no_schedule_or_calendar():
    case = fixture()
    diagnosis = Diagnosis(case_hash=case.case_hash, status="INFEASIBLE", proof_kind="sufficient")
    files = bundle_files(build_diagnosis_bundle(case, diagnosis))
    assert set(files) == {"diagnosis.json", "explanation.md"}
    with pytest.raises(ValueError, match="case hash"):
        build_diagnosis_bundle(case, diagnosis.model_copy(update={"case_hash": "stale"}))
