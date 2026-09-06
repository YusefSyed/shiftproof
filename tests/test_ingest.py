import pytest

from shiftproof.models import InputError

from .domain_helpers import fixture


def test_baseline_is_canonical():
    case = fixture()
    assert case.case_id == "PANTRY_DEMO" and len(case.availability) == 15


def test_rejects_extra_slot_and_missing_availability():
    from pathlib import Path

    from shiftproof.ingest import ingest_bundle

    p = Path(__file__).parents[1] / "fixtures/baseline"
    files = {x.name: x.read_bytes() for x in p.iterdir()}
    files["x"] = b""
    with pytest.raises(InputError):
        ingest_bundle(files)


@pytest.mark.parametrize(
    ("slot", "old", "new"),
    [
        ("volunteers.csv", b"volunteer_id,display_name", b"volunteer_id,volunteer_id"),
        ("coverage.csv", b"S1,lead,1", b"S1,lead,true"),
        ("coverage.csv", b"S1,lead,1", b"S1,lead,1.0"),
        ("case.json", b'"schema_version":1', b'"schema_version":true'),
    ],
)
def test_rejects_duplicate_headers_and_non_integer_data(slot, old, new):
    from pathlib import Path

    from shiftproof.ingest import ingest_bundle

    root = Path(__file__).parents[1] / "fixtures/baseline"
    files = {path.name: path.read_bytes() for path in root.iterdir()}
    files[slot] = files[slot].replace(old, new, 1)
    with pytest.raises(InputError):
        ingest_bundle(files)


def test_rejects_duplicate_json_key_and_dst_gap():
    from pathlib import Path
    from zoneinfo import ZoneInfo

    from shiftproof.ingest import _local_datetime, ingest_bundle

    root = Path(__file__).parents[1] / "fixtures/baseline"
    files = {path.name: path.read_bytes() for path in root.iterdir()}
    files["case.json"] = files["case.json"].replace(
        b'"case_id":"PANTRY_DEMO",', b'"case_id":"PANTRY_DEMO","case_id":"SECOND",'
    )
    with pytest.raises(InputError):
        ingest_bundle(files)
    with pytest.raises(InputError):
        _local_datetime("2026-03-08T02:30:00-05:00", ZoneInfo("America/Toronto"), "start")
    with pytest.raises(InputError):
        _local_datetime("2026-09-12T09:00:00-05:00", ZoneInfo("America/Toronto"), "start")
