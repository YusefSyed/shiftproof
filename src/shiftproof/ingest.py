"""Strict, side-effect-free parsing for the five ShiftProof input slots."""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import cast
from zoneinfo import ZoneInfo

from .models import (
    Availability,
    AvailabilityStatus,
    Case,
    Coverage,
    InputError,
    Lock,
    Shift,
    Violation,
    Volunteer,
    hash_json,
)

_SLOTS = {"case.json", "volunteers.csv", "shifts.csv", "coverage.csv", "availability.csv"}
_HEADERS = {
    "volunteers.csv": ("volunteer_id", "display_name", "roles", "max_total_minutes", "max_shifts"),
    "shifts.csv": ("shift_id", "title", "start", "end"),
    "coverage.csv": ("shift_id", "role", "required_count"),
    "availability.csv": ("volunteer_id", "shift_id", "status", "note"),
}
_BAD_TEXT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def _fail(message: str, code: str = "input_invalid", *ids: str) -> None:
    raise InputError(message, (Violation(code=code, entity_ids=tuple(ids)),))


def _text(data: bytes, name: str) -> str:
    if len(data) > 256 * 1024:
        _fail(f"{name} exceeds 256KiB", "file_too_large")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        _fail(f"{name} is not UTF-8", "invalid_utf8")
    if _BAD_TEXT.search(text):
        _fail(f"{name} contains prohibited control characters", "unsafe_text")
    return text


def _csv(data: bytes, name: str) -> list[dict[str, str]]:
    text = _text(data, name)
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as exc:
        _fail(f"invalid {name}: {exc}", "invalid_csv")
    if not rows or tuple(rows[0]) != _HEADERS[name] or len(set(rows[0])) != len(rows[0]):
        _fail(f"{name} headers must exactly match the contract", "headers")
    width = len(rows[0])
    if any(len(row) != width for row in rows[1:]):
        _fail(f"{name} has an unexpected number of cells", "cell_count")
    return [dict(zip(rows[0], row, strict=True)) for row in rows[1:]]


def _integer(value: str, field: str) -> int:
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        _fail(f"{field} must be an integer", "integer")
    if (
        not parsed.is_finite()
        or parsed != parsed.to_integral_value()
        or "." in value
        or "e" in value.lower()
    ):
        _fail(f"{field} must be an integer", "integer")
    return int(parsed)


def _unique(rows: list[object], keys: list[object], what: str) -> None:
    if len(set(keys)) != len(keys):
        _fail(f"duplicate {what}", "duplicate")


def _local_datetime(value: str, zone: ZoneInfo, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        _fail(f"invalid {field}", "time")
    if result.tzinfo is None or result.second or result.microsecond:
        _fail(f"{field} requires a whole-minute offset-aware timestamp", "time")
    # A UTC round trip proves the supplied offset describes an actual local instant.
    local = result.astimezone(zone)
    if (
        local.replace(tzinfo=None) != result.replace(tzinfo=None)
        or local.utcoffset() != result.utcoffset()
    ):
        _fail(f"{field} has a wrong offset or is in a time gap", "time")
    return result.astimezone(ZoneInfo("UTC"))


def ingest_bundle(files: Mapping[str, bytes]) -> Case:
    if (
        not isinstance(files, Mapping)
        or set(files) != _SLOTS
        or not all(isinstance(v, bytes) for v in files.values())
    ):
        _fail("bundle must contain exactly the five required byte slots", "slots")
    if sum(len(value) for value in files.values()) > 1024 * 1024:
        _fail("bundle exceeds 1MiB", "bundle_too_large")
    raw_case = _text(files["case.json"], "case.json")
    try:
        obj = json.loads(raw_case, object_pairs_hook=lambda pairs: _json_object(pairs))
    except (json.JSONDecodeError, ValueError) as exc:
        _fail(f"invalid case.json: {exc}", "invalid_json")
    expected = {"schema_version", "case_id", "timezone", "week_start", "roles", "locks"}
    if not isinstance(obj, dict) or set(obj) != expected:
        _fail("case.json fields must exactly match the contract", "case_fields")
    if type(obj["schema_version"]) is not int or obj["schema_version"] != 1:
        _fail("schema_version must be integer 1", "case_type")
    try:
        zone = ZoneInfo(obj["timezone"])
        week_start = date.fromisoformat(obj["week_start"])
    except (ValueError, TypeError):
        _fail("invalid timezone or week_start", "case_time")
    if week_start.weekday() != 0:
        _fail("week_start must be Monday", "week_start")
    if not isinstance(obj["roles"], list) or not isinstance(obj["locks"], list):
        _fail("roles and locks must be arrays", "case_type")
    volunteers_rows, shifts_rows, coverage_rows, availability_rows = (
        _csv(files[name], name) for name in _HEADERS
    )
    try:
        volunteers = tuple(
            Volunteer(
                volunteer_id=row["volunteer_id"],
                display_name=row["display_name"],
                roles=tuple(row["roles"].split("|")),
                max_total_minutes=_integer(row["max_total_minutes"], "max_total_minutes"),
                max_shifts=_integer(row["max_shifts"], "max_shifts"),
                source_ref=f"volunteers.csv:{i + 2}",
            )
            for i, row in enumerate(volunteers_rows)
        )
        shifts = tuple(
            Shift(
                shift_id=row["shift_id"],
                title=row["title"],
                start=_local_datetime(row["start"], zone, "start"),
                end=_local_datetime(row["end"], zone, "end"),
                source_ref=f"shifts.csv:{i + 2}",
            )
            for i, row in enumerate(shifts_rows)
        )
        coverage = tuple(
            Coverage(
                shift_id=row["shift_id"],
                role=row["role"],
                required_count=_integer(row["required_count"], "required_count"),
                source_ref=f"coverage.csv:{i + 2}",
            )
            for i, row in enumerate(coverage_rows)
        )
        availability = tuple(
            Availability(
                volunteer_id=row["volunteer_id"],
                shift_id=row["shift_id"],
                status=cast("AvailabilityStatus", row["status"]),
                note=row["note"],
                source_ref=f"availability.csv:{i + 2}",
            )
            for i, row in enumerate(availability_rows)
        )
        locks = tuple(
            Lock(**lock, source_ref=f"case.json:locks[{i}]") for i, lock in enumerate(obj["locks"])
        )
        case = Case(
            schema_version=obj["schema_version"],
            case_id=obj["case_id"],
            timezone=obj["timezone"],
            week_start=week_start,
            roles=tuple(obj["roles"]),
            locks=locks,
            volunteers=volunteers,
            shifts=shifts,
            coverage=coverage,
            availability=availability,
            input_bundle_hash=hash_json({name: files[name].hex() for name in sorted(files)}),
        )
    except (TypeError, ValueError) as exc:
        _fail(str(exc), "schema")
    return validate_case(case)


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key}")
        result[key] = value
    return result


def validate_case(case: Case) -> Case:
    volunteer_ids = {v.volunteer_id for v in case.volunteers}
    shift_ids = {s.shift_id for s in case.shifts}
    _unique(list(case.volunteers), [v.volunteer_id for v in case.volunteers], "volunteer")
    _unique(list(case.shifts), [s.shift_id for s in case.shifts], "shift")
    _unique(list(case.coverage), [(c.shift_id, c.role) for c in case.coverage], "coverage")
    _unique(
        list(case.availability),
        [(a.volunteer_id, a.shift_id) for a in case.availability],
        "availability",
    )
    _unique(list(case.locks), [lock.lock_id for lock in case.locks], "lock")
    if len(case.coverage) > 36 or len(case.availability) > 240 or len(case.locks) > 40:
        _fail("record bound exceeded", "bound")
    if len(set(case.roles)) != len(case.roles):
        _fail("duplicate role", "duplicate")
    for shift in case.shifts:
        if shift.end <= shift.start:
            _fail("shift end must follow start", "shift_time", shift.shift_id)
        local = shift.start.astimezone(ZoneInfo(case.timezone))
        end_local = shift.end.astimezone(ZoneInfo(case.timezone))
        horizon = datetime.combine(
            case.week_start, datetime.min.time(), tzinfo=ZoneInfo(case.timezone)
        )
        if not (
            horizon <= local < horizon + timedelta(days=7)
            and end_local <= horizon + timedelta(days=7)
        ):
            _fail("shift lies outside weekly horizon", "horizon", shift.shift_id)
    positive = 0
    by_shift: dict[str, int] = {sid: 0 for sid in shift_ids}
    for cov in case.coverage:
        if cov.shift_id not in shift_ids or cov.role not in case.roles:
            _fail("unknown coverage reference", "reference")
        positive += cov.required_count
        by_shift[cov.shift_id] += cov.required_count
    if not 1 <= positive <= 40 or any(count == 0 for count in by_shift.values()):
        _fail("invalid demand", "demand")
    for av in case.availability:
        if av.volunteer_id not in volunteer_ids or av.shift_id not in shift_ids:
            _fail("unknown availability reference", "reference")
    for lock in case.locks:
        if (
            lock.volunteer_id not in volunteer_ids
            or lock.shift_id not in shift_ids
            or lock.role not in case.roles
        ):
            _fail("unknown lock reference", "reference")
    return case.model_copy(
        update={
            "volunteers": tuple(sorted(case.volunteers, key=lambda x: x.volunteer_id)),
            "shifts": tuple(sorted(case.shifts, key=lambda x: x.shift_id)),
            "coverage": tuple(sorted(case.coverage, key=lambda x: (x.shift_id, x.role))),
            "availability": tuple(
                sorted(case.availability, key=lambda x: (x.volunteer_id, x.shift_id))
            ),
            "locks": tuple(sorted(case.locks, key=lambda x: x.lock_id)),
        }
    )
