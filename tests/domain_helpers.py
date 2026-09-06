from pathlib import Path

from shiftproof.ingest import ingest_bundle

ROOT = Path(__file__).parents[1] / "fixtures"


def fixture(name="baseline"):
    base = {p.name: p.read_bytes() for p in (ROOT / "baseline").iterdir()}
    variant = ROOT / name
    if name != "baseline":
        base.update({p.name: p.read_bytes() for p in variant.iterdir()})
    return ingest_bundle(base)
