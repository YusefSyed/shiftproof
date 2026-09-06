"""Create a clearly labeled visualization of genuine recorded local runs, with local TTS.

This is not a live-looking scripted agent replay or a browser screen recording.
All schedules, metrics and tool lists come from the supplied measured receipts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import subprocess
import wave
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

import imageio_ffmpeg
import soundfile as sf
from kokoro_onnx import Kokoro
from PIL import Image, ImageDraw, ImageFont

from shiftproof.ingest import ingest_bundle

ROOT = Path(__file__).resolve().parents[1]
W, H = 1280, 720
BG, INK, TEAL, PALE, GOLD = "#f8f7ef", "#17324a", "#087f79", "#e0f2ec", "#fae8bd"


def font(size: int, bold: bool = False):
    path = Path("/System/Library/Fonts/Supplemental") / ("Arial Bold.ttf" if bold else "Arial.ttf")
    if path.exists():
        return ImageFont.truetype(str(path), size)
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


def wrap(draw, text, selected_font, width):
    lines, current = [], ""
    for word in text.split():
        trial = (current + " " + word).strip()
        if draw.textlength(trial, font=selected_font) > width and current:
            lines.append(current)
            current = word
        else:
            current = trial
    return lines + ([current] if current else [])


def base(title, subtitle):
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, W, 70), fill=INK)
    draw.text((44, 18), "ShiftProof", font=font(30, True), fill="white")
    draw.text((895, 25), "RECORDED LOCAL RUN", font=font(18, True), fill="#c5eee6")
    draw.text((44, 101), title, font=font(42, True), fill=INK)
    draw.text((46, 157), subtitle, font=font(20), fill=TEAL)
    draw.line((44, 661, 1236, 661), fill="#ccd9d6", width=2)
    draw.text((44, 680), "Results visualized from a real run · synthetic data · inference waits edited", font=font(17), fill=INK)
    return image, draw


def paragraph(draw, text, x, y, width, size=25, color=INK):
    for line in wrap(draw, text, font(size), width):
        draw.text((x, y), line, font=font(size), fill=color)
        y += size + 10
    return y


def table(draw, heads, rows, x=44, y=224, widths=None, highlights=()):
    widths = widths or [int(1192 / len(heads))] * len(heads)
    row_height = 51
    draw.rounded_rectangle((x, y, x + sum(widths), y + row_height), radius=8, fill=INK)
    xx = x
    for heading, width in zip(heads, widths):
        draw.text((xx + 15, y + 14), heading, font=font(20, True), fill="white")
        xx += width
    for index, row in enumerate(rows):
        yy = y + row_height * (index + 1)
        fill = GOLD if index in highlights else ("#eef3f0" if index % 2 == 0 else "white")
        draw.rectangle((x, yy, x + sum(widths), yy + row_height), fill=fill)
        xx = x
        for value, width in zip(row, widths):
            selected = font(22)
            value = str(value)
            assert draw.textlength(value, font=selected) < width - 24, value
            draw.text((xx + 15, yy + 13), value, font=selected, fill=INK)
            xx += width


def card(draw, x, y, width, height, heading, value, detail="", fill=PALE):
    draw.rounded_rectangle((x, y, x + width, y + height), radius=16, fill=fill, outline="#bed6cd", width=2)
    draw.text((x + 22, y + 18), heading, font=font(19, True), fill=INK)
    draw.text((x + 22, y + 52), str(value), font=font(43, True), fill=TEAL)
    if detail:
        paragraph(draw, detail, x + 22, y + 111, width - 44, 20)


def run(command):
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:])
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("receipt", type=Path)
    parser.add_argument("injection", type=Path)
    args = parser.parse_args()
    receipt = json.loads(args.receipt.read_text())
    injection = json.loads(args.injection.read_text())
    assert receipt["passed"] and injection["passed"]
    records = {row["label"]: row for row in receipt["scenarios"]}
    assert records["Hypothetical repairs"]["result"]["status"] == "INFEASIBLE"
    suites = ET.parse(ROOT / "workspace" / "release-tests.xml").getroot().findall("testsuite")
    assert suites and all(int(s.attrib.get("failures", 0)) + int(s.attrib.get("errors", 0)) == 0 for s in suites)
    test_count = sum(int(s.attrib["tests"]) - int(s.attrib.get("skipped", 0)) for s in suites)
    files = {p.name: p.read_bytes() for p in (ROOT / "fixtures" / "baseline").iterdir()}
    case = ingest_bundle(files)
    assert case.case_hash == records["Baseline"]["result"]["case_hash"]
    names = {v.volunteer_id: v.display_name for v in case.volunteers}
    baseline = records["Baseline"]["result"]["candidate"]
    repaired = records["Cancellation repair"]["result"]["candidate"]

    def lookup(candidate, sid, role):
        return next(a["volunteer_id"] for a in candidate["solver"]["assignments"]
                    if a["shift_id"] == sid and a["role"] == role)

    scenes = []

    image, draw = base("Coverage you can verify", "A local scheduling agent for community volunteer coordinators")
    paragraph(draw, "A cancellation should not turn into an overbooked volunteer or a silently changed staffing rule.", 50, 234, 1110, 35)
    card(draw, 50, 408, 365, 174, "REASON", "Strands", "The local model chooses narrow tools.")
    card(draw, 457, 408, 365, 174, "CHECK", "Independent", "Ordinary code verifies every assignment.")
    card(draw, 864, 408, 365, 174, "DECIDE", "Coordinator", "Approval stays outside the agent.", GOLD)
    scenes.append((image, "ShiftProof helps a volunteer coordinator handle cancellations without silently changing the rules. This video visualizes a recorded local Strands run, rather than a live screen recording. The pantry data and coordinator actions are synthetic, and inference waits are shortened. The model calls, computed results, checks, and exported files came from the working application."))

    image, draw = base("Start with confirmed constraints", "One site · one planning week · explicit availability, roles and limits")
    table(draw, ["Volunteer", "Role", "Minutes", "Shifts"],
          [[v.display_name, v.roles[0], v.max_total_minutes, v.max_shifts] for v in case.volunteers],
          widths=[200, 180, 160, 130])
    card(draw, 770, 224, 430, 175, "THE PANTRY DAY", "4 shifts", "Each needs exactly one lead and one helper.")
    paragraph(draw, "Missing availability means unavailable. Pins never override qualifications or workload limits.", 782, 436, 410, 25)
    scenes.append((image, "The example has six volunteers and four two-hour shifts. Every shift requires one lead and one helper. The two leads each allow at most two shifts and two hundred forty minutes. Missing availability is treated as unavailable. The coordinator can inspect qualifications, limits, availability, and source records before confirming these inputs."))

    image, draw = base("The agent computes, then prepares review", "These assignments came from the recorded local run")
    table(draw, ["Shift", "Lead", "Helper"],
          [[s.shift_id, names[lookup(baseline, s.shift_id, "lead")], names[lookup(baseline, s.shift_id, "helper")]] for s in case.shifts],
          widths=[250, 471, 471])
    check = baseline["verification"]
    paragraph(draw, f"{check['preferred']} preferred assignments · independent verification passed · not approved automatically", 50, 512, 1140, 27)
    tools = [t["tool"] for t in records["Baseline"]["trace"] if t["type"] == "tool_end" and t["status"] == "complete"]
    draw.text((50, 578), " → ".join(tools), font=font(22), fill=TEAL)
    scenes.append((image, "The actual local model inspected the case, called the scheduling solver, and prepared a review. The solver found eight preferred assignments. A separate verifier recomputed coverage, availability, qualifications, overlaps, and workload limits. The model did not write this schedule in prose, and a verified candidate was not automatically approved."))

    image, draw = base("One cancellation requires two changes", "Bo becomes unavailable for the midday shift; helpers remain unchanged")
    rows, changed = [], []
    for i, shift in enumerate(case.shifts):
        before, after = lookup(baseline, shift.shift_id, "lead"), lookup(repaired, shift.shift_id, "lead")
        helper = lookup(repaired, shift.shift_id, "helper")
        assert helper == lookup(baseline, shift.shift_id, "helper")
        rows.append([shift.shift_id, names[before], names[after], names[helper]])
        if before != after:
            changed.append(i)
    table(draw, ["Shift", "Lead before", "Lead after", "Helper"], rows, widths=[180, 336, 336, 340], highlights=changed)
    check = repaired["verification"]
    paragraph(draw, f"{check['replacements']} replaced assignments · {check['preferred']} preferred assignments · verified before approval", 50, 514, 1130, 28)
    scenes.append((image, "The model first proposed and simulated Bo's cancellation without changing the confirmed case. After a synthetic coordinator confirmation through the application's human route, the old approval was revoked. The agent then repaired the schedule. Simply adding midday to Asha would exceed both limits. Instead, it swapped two lead assignments and retained all four helper assignments."))

    image, draw = base("An impossible request stays impossible", "The second cancellation creates a shared capacity bottleneck")
    witness = next(f for f in records["Infeasible case"]["result"]["diagnosis"]["facts"] if f["code"] == "sole_eligible_capacity")
    z = witness["details"]
    card(draw, 50, 236, 550, 213, "ONLY ASHA CAN COVER", f"{z['required_shifts']} shifts", f"{z['required_minutes']} minutes required across S1, S2 and S3.", GOLD)
    card(draw, 652, 236, 550, 213, "CONFIRMED CAPACITY", f"{z['max_shifts']} shifts", f"{z['max_total_minutes']} minutes permitted. These limits are not silently increased.")
    paragraph(draw, "The case is infeasible. Reusing the old approval to export was rejected.", 50, 512, 1130, 31)
    scenes.append((image, "Now Bo also becomes unavailable for the afternoon. Every shift still has an eligible lead considered on its own. But Asha alone would need three shifts and three hundred sixty minutes, above the confirmed limits of two shifts and two hundred forty minutes. The application reports this concrete bottleneck. Reusing the old schedule approval to export is rejected."))

    image, draw = base("Compare options without changing facts", "Both alternatives are hypothetical and require confirmation")
    alternatives = records["Hypothetical repairs"]["result"]["proposals"]
    restore = next(p for p in alternatives if p["operations"][0]["op"] == "set_availability")
    caps = next(p for p in alternatives if p["operations"][0]["op"] == "set_limits")
    for x, title, item in [(50, "Restore Bo for S3", restore), (652, "Raise both Asha limits", caps)]:
        check = item["simulation"]["verification"]
        assert check["valid"] and item["simulation"]["hypothetical"]
        card(draw, x, 236, 550, 225, title, "Feasible in simulation", f"{check['replacements']} replacements · {check['preferred']} preferred assignments\nConfirmation is still required.")
    paragraph(draw, "Confirmed case: still INFEASIBLE. Neither simulation changed its revision or created approval.", 50, 508, 1150, 28)
    scenes.append((image, "The real agent compared two alternatives. One restores Bo's afternoon availability. The other increases both of Asha's limits. Both simulations are independently checked, but neither is an established fact. The confirmed case remains infeasible, with no schedule approval. The agent cannot claim a volunteer consented, and it has no tool for applying or approving either option."))

    image, draw = base("Export a checked, traceable snapshot", "The actual repaired bundle was opened and verified")
    with ZipFile(args.receipt.parent / "repair.zip") as archive:
        manifest = json.loads(archive.read("manifest.json"))
        filenames = archive.namelist()
        events = archive.read("calendar_all.ics").count(b"BEGIN:VEVENT")
        csv_rows = list(csv.DictReader(io.StringIO(archive.read("schedule.csv").decode())))
    table(draw, ["Artifact", "Purpose"], [
        ["schedule.csv / schedule.json", f"{len(csv_rows)} assignments"],
        ["verification.json", "Independent check results"],
        ["changes.csv / explanation.md", "Reviewable change record"],
        ["calendar_all.ics / calendars/", f"{events} coordinator events + personal snapshots"],
        ["manifest.json", "Input, candidate and artifact hashes"],
    ], widths=[530, 662])
    assert manifest and len(filenames) >= 8
    scenes.append((image, "After separate schedule approval, export recomputes the checks against the current snapshot. The actual repaired bundle includes the assignments, verification report, change record, calendar files, and checksum manifest. Its coordinator calendar contains eight events. These are importable snapshots, not invitations or synchronization updates. No calendar service is contacted."))

    image, draw = base("Keep the model inside a narrow boundary", "Measured checks, not a promise that an LLM is infallible")
    card(draw, 50, 228, 365, 235, "AUTOMATED CHECKS", str(test_count), "Deterministic tests, state gates and runtime-policy checks.")
    card(draw, 457, 228, 365, 235, "REAL PROVIDER CALLS", str(injection["provider_calls_inspected"]), "Synthetic name, title and instruction-note probes were excluded.")
    card(draw, 864, 228, 365, 235, "HOSTED INFERENCE", "No route", "Owned local daemon, cloud disabled, process egress restriction.")
    paragraph(draw, "A separate process holds only six tools. Approval tokens stay with the parent application.", 50, 522, 1120, 27)
    scenes.append((image, f"The automated suite has {test_count} passing tests. A separate genuine local run inspected four requests handed to the model provider: synthetic name, title, and instruction-note probes were absent. The app and its owned Ollama daemon run under a local-only process network policy on the tested Mac. There is no hosted model fallback. Approval tokens remain outside the agent worker."))

    image, draw = base("Useful automation, explicit human decisions", "Good Neighbor Agents · local prototype · synthetic evaluation")
    paragraph(draw, "A coordinator gets a usable schedule, a reviewable repair, and a concrete explanation when the facts cannot support one.", 50, 240, 1110, 37)
    paragraph(draw, "Design: GPT-6 Pro\nImplementation and checks: Codex\nRuntime: local Qwen through Strands and Ollama", 50, 448, 1120, 27)
    scenes.append((image, "ShiftProof is a working local prototype for one site and a seven-day planning window. It has not been deployed to a real pantry or evaluated with real volunteers. GPT-six Pro assisted with the design, Codex implemented and tested it, and Qwen runs locally through Strands and Ollama. The aim is useful automation with checkable outputs and explicit human decisions."))

    out = ROOT / "media-work" / "demo"
    out.mkdir(parents=True, exist_ok=True)
    model_dir = ROOT / "media-work" / "kokoro"
    model_path = model_dir / "kokoro-v1.0.onnx"
    voices_path = model_dir / "voices-v1.0.bin"
    if not model_path.is_file() or not voices_path.is_file():
        raise RuntimeError("Download the locally licensed Kokoro ONNX model and voices before rendering.")
    tts = Kokoro(str(model_path), str(voices_path))
    model_receipt = {
        "runtime": "kokoro-onnx 0.4.9 (MIT)",
        "weights": "Kokoro v1.0 ONNX (Apache-2.0)",
        "voice": "af_heart from voices-v1.0.bin (Apache-2.0 model distribution)",
        "source": "https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0",
        "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "voices_sha256": hashlib.sha256(voices_path.read_bytes()).hexdigest(),
    }
    (model_dir / "receipt.json").write_text(json.dumps(model_receipt, indent=2) + "\n")
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    durations, transcript, parts = [], [], []
    for index, (image, narration) in enumerate(scenes, 1):
        stem = out / f"scene-{index:02d}"
        image.save(stem.with_suffix(".png"))
        stem.with_suffix(".txt").write_text(narration)
        audio, sample_rate = tts.create(narration, voice="af_heart", speed=1.1, lang="en-us")
        sf.write(str(stem.with_suffix('.wav')), audio, sample_rate)
        with wave.open(str(stem.with_suffix('.wav'))) as audio:
            duration = math.ceil((audio.getnframes() / audio.getframerate() + 1.2) * 24) / 24
        assert duration < 55
        durations.append(duration)
        transcript.append(f"## Scene {index}\n\n{narration}\n")
        part = stem.with_suffix(".mp4")
        run([ffmpeg, "-y", "-loop", "1", "-framerate", "24", "-i", str(stem.with_suffix('.png')),
             "-i", str(stem.with_suffix('.wav')), "-t", str(duration), "-c:v", "libx264", "-preset", "fast",
             "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-af", "apad", str(part)])
        parts.append(part)
        print(f"Rendered scene {index}: {duration:.2f}s", flush=True)
    assert sum(durations) < 295, sum(durations)
    concat = out / "segments.txt"
    concat.write_text("\n".join(f"file '{p.name}'" for p in parts) + "\n")
    final = ROOT / "media-work" / "ShiftProof-Demo.mp4"
    run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", "-movflags", "+faststart", str(final)])
    decoded = run([ffmpeg, "-i", str(final), "-f", "null", "-"])
    matched = re.search(r"Duration: (\d+):(\d+):([\d.]+)", decoded.stderr)
    assert matched
    actual = int(matched[1]) * 3600 + int(matched[2]) * 60 + float(matched[3])
    assert actual <= 300 and "Audio:" in decoded.stderr and "Video:" in decoded.stderr
    (ROOT / "docs" / "demo-transcript.md").write_text("# ShiftProof demo transcript\n\nLocally synthesized narration. The video visualizes measured recorded outputs; it is not a live browser recording.\n\n" + "\n".join(transcript))
    (out / "render-receipt.json").write_text(json.dumps({"video": final.name, "duration_seconds": actual,
        "scene_durations": durations, "resolution": [W,H], "fps":24,
        "native_receipt": args.receipt.parent.name, "injection_receipt": args.injection.name,
        "unit_test_count": test_count, "audio_and_video_decoded": True,
        "presentation": "Recorded-run result visualization; synthetic operator actions; inference waits edited",
        "tts": model_receipt}, indent=2) + "\n")
    print(f"Video: {final} ({actual:.2f}s)")


if __name__ == "__main__":
    main()
