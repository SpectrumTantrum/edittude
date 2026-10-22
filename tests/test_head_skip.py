"""Messy-head windows, the silent-clip bed, and the E1a clean-cut regression."""
from __future__ import annotations

import contextlib
import inspect
import io
import math
import re
import shutil
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from edittude_v3.media.core import ffmpeg, ffprobe
from edittude_v3.media.edl import (
    SKIPPED_NO_CLEAN,
    EditDecision,
    Event,
    _reason,
    edl_from_dict,
    first_cut,
)
from edittude_v3.media.inventory import build_inventory, describe_clip
from edittude_v3.media.proof import run_proof
from edittude_v3.media.qc import BLACK_DETECT, FREEZE_DETECT, SILENCE_DETECT, _parse_loudness, review
from edittude_v3.media.render import (
    AUDIO_BED,
    BED_CLEARANCE,
    BED_LUFS,
    BED_MAX,
    BED_MIN,
    _AMB_LINEAR,
    _bed_target,
    assemble,
    finish,
)

ROOT = Path(__file__).resolve().parents[1]
NOTES = (
    "Chronology is the spine. Handles off iPhone starts. "
    "Long holds capped. Picture fitted to voiceover when one exists."
)


def _ffmpeg(*args: str) -> None:
    ffmpeg(["-v", "error", *args])


def _span_lufs(path: Path, start: float, end: float) -> float:
    result = ffmpeg([
        "-i", str(path),
        "-af", f"atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS,ebur128=peak=true",
        "-f", "null", "-",
    ], capture=True)
    stats = _parse_loudness((result.stderr or "") + (result.stdout or ""))
    if stats["I"] is None:
        raise AssertionError((result.stderr or "")[-500:])
    return float(stats["I"])


def _rate(path: Path) -> Fraction:
    stream = next(item for item in ffprobe(path)["streams"] if item["codec_type"] == "video")
    return Fraction(stream["avg_frame_rate"])


def _screeny(clip: dict) -> bool:
    name = clip.get("name", "").lower()
    if any(token in name for token in ("screen", "laptop", "ui", "capture")):
        return True
    return float(clip.get("duration") or 0) >= 8.5


def _e1a_head(origin: float, src_dur: float, screeny: bool) -> tuple[float, float]:
    """The pre-E1b head rule, shifted when the keep window no longer starts at 0."""
    handle_in, handle_out = 0.12, 0.08
    max_hold, min_hold, screeny_cap = 5.2, 1.05, 4.0
    if origin <= 0:
        start = handle_in if src_dur > handle_in + min_hold else 0.0
    else:
        remain = src_dur - origin
        start = origin + handle_in if remain > handle_in + min_hold else origin
    end = src_dur - handle_out if src_dur - handle_out > start + min_hold else src_dur
    cap = screeny_cap if screeny else max_hold
    if end - start > cap:
        end = start + cap
    return start, end


def _e1a_events(clips: list[dict]) -> list[dict]:
    """Copy of the E1a loop, including growth. Literals stay here so a helper drift fails."""
    handle_out = 0.08
    videos = [clip for clip in clips if clip.get("kind") == "video"]
    videos = sorted(videos, key=lambda clip: (clip.get("creation_time") or "", clip.get("name") or ""))
    total = sum(float(clip.get("duration") or 0) for clip in videos)
    target = min(60.0, max(12.0, total * 0.72))
    events = []
    count = len(videos)
    for index, clip in enumerate(videos):
        src_dur = float(clip.get("duration") or 0)
        if src_dur < 0.4:
            continue
        start, end = _e1a_head(0.0, src_dur, _screeny(clip))
        events.append({
            "src": clip["path"],
            "in": start,
            "out": end,
            "reason": _reason(index, count, clip),
        })
    current = sum(event["out"] - event["in"] for event in events)
    if events and abs(current - target) >= 0.15 and current < target:
        remaining = target - current
        for event in events:
            if remaining <= 0.05:
                break
            src = Path(event["src"])
            if not src.is_file():
                continue
            src_dur = float(describe_clip(src)["duration"])
            slack = src_dur - handle_out - event["out"]
            if slack <= 0.05:
                continue
            take = min(slack, remaining)
            event["out"] += take
            remaining -= take
    return events


class HeadSkipPlanTest(unittest.TestCase):
    def setUp(self) -> None:
        if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
            self.skipTest("FFmpeg/ffprobe unavailable")

    def _cut(self, path: Path):
        clip = describe_clip(path)
        return first_cut({"clips": [clip]}), clip

    def _assert_fraction(self, actual: float, expected: Fraction, rate: Fraction) -> None:
        limit = float(Fraction(1) / rate)
        self.assertLessEqual(
            abs(actual - float(expected)),
            limit,
            f"{actual} is more than one frame ({limit}) from {expected} at {rate}",
        )

    def test_black_head_starts_after_three_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "black-head.mp4"
            _ffmpeg(
                "-f", "lavfi", "-i", "color=c=black:s=160x90:r=24:d=3",
                "-f", "lavfi", "-i", "testsrc=s=160x90:r=24:d=5",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=8",
                "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
                "-map", "[v]", "-map", "2:a",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(path),
            )
            cut, clip = self._cut(path)
            rate = _rate(path)
            self.assertEqual(rate, Fraction(24))
            self.assertEqual(cut.skipped, [])
            event = cut.events[0]
            self._assert_fraction(event.in_point, Fraction(3) + Fraction(12, 100), rate)
            start, end = _e1a_head(3.0, float(clip["duration"]), False)
            self._assert_fraction(event.out_point, Fraction(end).limit_denominator(100000), rate)
            self.assertEqual(event.to_dict()["in"], round(start, 3))
            self.assertEqual(event.to_dict()["out"], round(end, 3))
            self.assertNotIn("audio", event.to_dict())

    def test_freeze_head_starts_after_two_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "freeze-head.mp4"
            _ffmpeg(
                "-f", "lavfi", "-i", "color=c=gray:s=160x90:r=24:d=2",
                "-f", "lavfi", "-i", "testsrc=s=160x90:r=24:d=4",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=6",
                "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
                "-map", "[v]", "-map", "2:a",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(path),
            )
            cut, clip = self._cut(path)
            rate = _rate(path)
            event = cut.events[0]
            self._assert_fraction(event.in_point, Fraction(2) + Fraction(12, 100), rate)
            _start, end = _e1a_head(2.0, float(clip["duration"]), False)
            self._assert_fraction(event.out_point, Fraction(end).limit_denominator(100000), rate)
            self.assertEqual(cut.skipped, [])

    def test_silent_head_starts_after_two_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "silent-head.mp4"
            _ffmpeg(
                "-f", "lavfi", "-i", "testsrc=s=160x90:r=25:d=6",
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=2",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4",
                "-filter_complex", "[1:a][2:a]concat=n=2:v=0:a=1[a]",
                "-map", "0:v", "-map", "[a]",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(path),
            )
            cut, clip = self._cut(path)
            rate = _rate(path)
            self.assertEqual(rate, Fraction(25))
            event = cut.events[0]
            # silence_end lands at 2.00008; the keep window snaps back onto frame 50.
            self._assert_fraction(event.in_point, Fraction(2) + Fraction(12, 100), rate)
            _start, end = _e1a_head(2.0, float(clip["duration"]), False)
            self._assert_fraction(event.out_point, Fraction(end).limit_denominator(100000), rate)

    def test_black_in_the_middle_moves_past_the_span(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "black-mid.mp4"
            _ffmpeg(
                "-f", "lavfi", "-i", "testsrc=s=160x90:r=30:d=2",
                "-f", "lavfi", "-i", "color=c=black:s=160x90:r=30:d=1.5",
                "-f", "lavfi", "-i", "testsrc=s=160x90:r=30:d=3",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=6.5",
                "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
                "-map", "[v]", "-map", "3:a",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(path),
            )
            cut, clip = self._cut(path)
            rate = _rate(path)
            self.assertEqual(rate, Fraction(30))
            event = cut.events[0]
            self._assert_fraction(event.in_point, Fraction("3.5") + Fraction(12, 100), rate)
            _start, end = _e1a_head(3.5, float(clip["duration"]), False)
            self._assert_fraction(event.out_point, Fraction(end).limit_denominator(100000), rate)
            self.assertGreater(event.in_point, 2.0)

    def test_black_tail_too_short_cuts_before_the_span(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "cut-short.mp4"
            _ffmpeg(
                "-f", "lavfi", "-i", "testsrc=s=160x90:r=24:d=2",
                "-f", "lavfi", "-i", "color=c=black:s=160x90:r=24:d=1.2",
                "-f", "lavfi", "-i", "testsrc=s=160x90:r=24:d=0.8",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4",
                "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
                "-map", "[v]", "-map", "3:a",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(path),
            )
            cut, _clip = self._cut(path)
            rate = _rate(path)
            event = cut.events[0]
            self._assert_fraction(event.in_point, Fraction(12, 100), rate)
            self._assert_fraction(event.out_point, Fraction(2), rate)
            self.assertLess(event.out_point, 2.0 + float(Fraction(1) / rate))

    def test_later_black_stops_growth(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ceiling.mp4"
            _ffmpeg(
                "-f", "lavfi", "-i", "testsrc=s=160x90:r=24:d=7",
                "-f", "lavfi", "-i", "color=c=black:s=160x90:r=24:d=1.5",
                "-f", "lavfi", "-i", "testsrc=s=160x90:r=24:d=3.5",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=12",
                "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
                "-map", "[v]", "-map", "3:a",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(path),
            )
            cut, _clip = self._cut(path)
            rate = _rate(path)
            event = cut.events[0]
            self._assert_fraction(event.in_point, Fraction(12, 100), rate)
            self._assert_fraction(event.out_point, Fraction(7), rate)
            self.assertLess(event.out_point, 8.5)

    def test_all_black_is_dropped_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "all-black.mp4"
            _ffmpeg(
                "-f", "lavfi", "-i", "color=c=black:s=160x90:r=24:d=3",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(path),
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                cut, _clip = self._cut(path)
            self.assertIn(f"{SKIPPED_NO_CLEAN}: all-black.mp4", buf.getvalue())
            self.assertEqual(cut.events, [])
            self.assertEqual(cut.skipped, [{"src": str(path.resolve()), "reason": SKIPPED_NO_CLEAN}])
            self.assertEqual(SKIPPED_NO_CLEAN, "skipped: no clean window")
            data = cut.to_dict()
            self.assertEqual(data["skipped"], cut.skipped)
            self.assertEqual(edl_from_dict(data).skipped, cut.skipped)

    def test_all_black_beside_a_clean_clip_completes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            black = root / "a-black.mp4"
            clean = root / "b-clean.mp4"
            _ffmpeg(
                "-f", "lavfi", "-i", "color=c=black:s=160x90:r=24:d=3",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(black),
            )
            _ffmpeg(
                "-f", "lavfi", "-i", "testsrc=s=160x90:r=24:d=6",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=6",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(clean),
            )
            out = root / "proof"
            evidence = run_proof(root, out, title="", thumbs=False)
            edl = __import__("json").loads((out / "edl.json").read_text(encoding="utf-8"))
            self.assertEqual(len(edl["events"]), 1)
            self.assertTrue(edl["events"][0]["src"].endswith("b-clean.mp4"))
            self.assertEqual(edl["events"][0]["reason"][:4], "open")
            self.assertEqual(edl["skipped"], [{"src": str(black.resolve()), "reason": SKIPPED_NO_CLEAN}])
            self.assertEqual(evidence["issues"], [])
            self.assertTrue(evidence["pass"])
            self.assertTrue((out / "final.mp4").is_file())

    def test_video_only_clip_gets_a_bed_and_finishes_near_minus_16(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "video-only.mp4"
            _ffmpeg(
                "-f", "lavfi", "-i", "testsrc=s=160x90:r=30:d=4",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-an", str(path),
            )
            cut, clip = self._cut(path)
            self.assertIs(clip["has_audio"], False)
            event = cut.events[0]
            self.assertEqual(event.audio, "bed")
            self.assertEqual(event.to_dict()["audio"], "bed")
            start, end = _e1a_head(0.0, float(clip["duration"]), False)
            self.assertEqual(event.in_point, start)
            self.assertEqual(event.out_point, end)
            picture = root / "picture.mp4"
            assemble(cut, picture, root / "work")
            segment = review(root / "work" / "seg_000.mp4")
            self.assertEqual(segment["silence"], [])
            self.assertIsNotNone(segment["loudness"]["I"])
            self.assertLessEqual(abs(segment["loudness"]["I"] + 45), 1.5)
            final = finish(picture, root / "final.mp4", edl=cut)
            report = review(final)
            self.assertEqual(report["issues"], [])
            self.assertIsNotNone(report["loudness"]["I"])
            self.assertLessEqual(abs(report["loudness"]["I"] + 16), 0.5)
            probed = ffprobe(final)
            durations = {
                stream["codec_type"]: float(stream.get("duration") or 0)
                for stream in probed["streams"]
            }
            self.assertLessEqual(abs(durations["audio"] - durations["video"]), 0.05)

    def test_warm_grade_black_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "graded-dark.mp4"
            _ffmpeg(
                "-f", "lavfi", "-i",
                "color=c=black:s=160x90:r=24:d=3,format=yuv420p,geq=lum=40:cb=128:cr=128",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
                "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(path),
            )
            raw = ffmpeg(["-i", str(path), "-vf", BLACK_DETECT, "-f", "null", "-"], capture=True)
            self.assertNotIn("black_start", (raw.stderr or "") + (raw.stdout or ""))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                cut, _clip = self._cut(path)
            self.assertEqual(cut.events, [])
            self.assertEqual(cut.skipped, [{"src": str(path.resolve()), "reason": SKIPPED_NO_CLEAN}])
            self.assertIn(f"{SKIPPED_NO_CLEAN}: graded-dark.mp4", buf.getvalue())

    def test_bed_target_clears_a_quiet_neighbour(self) -> None:
        amb = 20.0 * math.log10(_AMB_LINEAR)
        gain = 21.34
        quietest = -30.5
        target = _bed_target(quietest, gain)
        predicted = quietest + amb + gain
        self.assertAlmostEqual(target, min(BED_LUFS, predicted - BED_CLEARANCE), places=2)
        self.assertAlmostEqual(predicted - target, BED_CLEARANCE, places=6)
        self.assertGreaterEqual(target, BED_MIN)
        self.assertLessEqual(target, BED_MAX)
        self.assertAlmostEqual(_bed_target(-5.0, 0.0), BED_LUFS, places=2)
        self.assertEqual(_bed_target(-80.0, 0.0), BED_MIN)

    def test_bed_under_a_neighbour_lands_between_minus_40_and_minus_30(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bed = root / "a-bed.mp4"
            tone = root / "b-tone.mp4"
            _ffmpeg(
                "-f", "lavfi", "-i", "testsrc=s=160x90:r=30:d=4",
                "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                str(bed),
            )
            _ffmpeg(
                "-f", "lavfi", "-i", "testsrc=s=160x90:r=30:d=4",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(tone),
            )
            cut = first_cut(build_inventory(root), title="")
            self.assertEqual([event.audio for event in cut.events], ["bed", ""])
            picture = root / "picture.mp4"
            assemble(cut, picture, root / "work")
            final = finish(picture, root / "final.mp4", edl=cut)
            fps = int(cut.fps or 30)
            bed_frames = max(1, round(cut.events[0].duration() * fps))
            bed_end = bed_frames / fps
            neighbour_frames = max(1, round(cut.events[1].duration() * fps))
            neighbour_end = bed_end + neighbour_frames / fps
            bed_i = _span_lufs(final, 0.05, bed_end - 0.05)
            neighbour_i = _span_lufs(final, bed_end + 0.05, neighbour_end - 0.05)
            self.assertGreaterEqual(bed_i, -40.0, bed_i)
            self.assertLessEqual(bed_i, -30.0, bed_i)
            self.assertGreaterEqual(neighbour_i - bed_i, 10.0, (neighbour_i, bed_i))
            silence = ffmpeg([
                "-i", str(final),
                "-af", f"atrim=start=0:end={bed_end:.6f},silencedetect=n=-60dB:d=0.3",
                "-f", "null", "-",
            ], capture=True)
            self.assertNotIn("silence_start", (silence.stderr or "") + (silence.stdout or ""))
            report = review(final)
            self.assertIsNotNone(report["loudness"]["TP"])
            self.assertLessEqual(report["loudness"]["TP"], -1.5)
            self.assertLessEqual(abs(report["loudness"]["I"] + 16), 1.5, report["loudness"])

    def test_clean_clip_matches_the_e1a_window(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "clean.mp4"
            _ffmpeg(
                "-f", "lavfi", "-i", "testsrc=s=160x90:r=24:d=6",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=6",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(path),
            )
            clip = describe_clip(path)
            cut = first_cut({"clips": [clip]})
            expected = _e1a_events([clip])[0]
            event = cut.events[0]
            self.assertEqual(event.in_point, expected["in"])
            self.assertEqual(event.out_point, expected["out"])
            self.assertEqual(event.to_dict()["in"], round(expected["in"], 3))
            self.assertEqual(event.to_dict()["out"], round(expected["out"], 3))
            self.assertEqual(event.reason, expected["reason"])
            self.assertEqual(cut.skipped, [])
            self.assertNotIn("skipped", cut.to_dict())
            self.assertNotIn("audio", event.to_dict())
            self.assertEqual(cut.notes, NOTES)

    def test_two_clean_clips_match_e1a(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, tone in (("a-clean.mp4", 440), ("b-clean.mp4", 550)):
                _ffmpeg(
                    "-f", "lavfi", "-i", "testsrc=s=160x90:r=24:d=6",
                    "-f", "lavfi", "-i", f"sine=frequency={tone}:sample_rate=48000:duration=6",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(root / name),
                )
            inventory = build_inventory(root)
            cut = first_cut(inventory)
            expected = _e1a_events(inventory["clips"])
            self.assertEqual(len(cut.events), len(expected))
            for event, oracle in zip(cut.events, expected, strict=True):
                self.assertEqual(event.in_point, oracle["in"])
                self.assertEqual(event.out_point, oracle["out"])
                self.assertEqual(event.reason, oracle["reason"])
                self.assertNotIn("audio", event.to_dict())
            self.assertNotIn("skipped", cut.to_dict())
            self.assertEqual(cut.notes, NOTES)

    def test_ntsc_black_head_uses_the_clip_rate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ntsc.mp4"
            _ffmpeg(
                "-f", "lavfi", "-i", "color=c=black:s=160x90:r=30000/1001:d=2",
                "-f", "lavfi", "-i", "testsrc=s=160x90:r=30000/1001:d=3",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=5",
                "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
                "-map", "[v]", "-map", "2:a",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(path),
            )
            cut, clip = self._cut(path)
            rate = _rate(path)
            self.assertEqual(rate, Fraction(30000, 1001))
            origin = Fraction(60) * Fraction(1001, 30000)
            self.assertEqual(origin, Fraction("2.002"))
            event = cut.events[0]
            self._assert_fraction(event.in_point, origin + Fraction(12, 100), rate)
            _start, end = _e1a_head(float(origin), float(clip["duration"]), False)
            self._assert_fraction(event.out_point, Fraction(end).limit_denominator(100000), rate)

    def test_short_interior_black_does_not_move_the_window(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "speck.mp4"
            _ffmpeg(
                "-f", "lavfi", "-i", "testsrc=s=160x90:r=24:d=2",
                "-f", "lavfi", "-i", "color=c=black:s=160x90:r=24:d=0.25",
                "-f", "lavfi", "-i", "testsrc=s=160x90:r=24:d=3.75",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=6",
                "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
                "-map", "[v]", "-map", "3:a",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(path),
            )
            clip = describe_clip(path)
            cut = first_cut({"clips": [clip]})
            expected = _e1a_events([clip])[0]
            event = cut.events[0]
            self.assertEqual(event.in_point, expected["in"])
            self.assertEqual(event.out_point, expected["out"])
            self.assertEqual(cut.skipped, [])


class HeadSkipContractTest(unittest.TestCase):
    def test_missing_files_match_e1a_and_do_not_crash(self) -> None:
        clips = [
            {"path": "/footage/a.mov", "name": "a.mov", "kind": "video", "duration": 6.0},
            {"path": "/footage/b.mov", "name": "b.mov", "kind": "video", "duration": 6.0},
        ]
        cut = first_cut({"clips": clips})
        expected = _e1a_events(clips)
        self.assertEqual(
            [(event.in_point, event.out_point, event.reason) for event in cut.events],
            [(event["in"], event["out"], event["reason"]) for event in expected],
        )
        self.assertEqual(cut.skipped, [])
        self.assertNotIn("skipped", cut.to_dict())
        self.assertTrue(all(event.audio == "" for event in cut.events))

    def test_a_short_clip_is_omitted_without_a_skipped_reason(self) -> None:
        cut = first_cut({"clips": [
            {"path": "/footage/tiny.mov", "name": "tiny.mov", "kind": "video", "duration": 0.3},
            {"path": "/footage/keep.mov", "name": "keep.mov", "kind": "video", "duration": 6.0},
        ]})
        self.assertEqual(len(cut.events), 1)
        self.assertEqual(cut.skipped, [])
        self.assertTrue(cut.events[0].reason.startswith("open"))

    def test_skipped_and_bed_round_trip(self) -> None:
        edl = EditDecision(
            events=[Event("clip.mov", 0.12, 2.0, audio="bed")],
            skipped=[{"src": "black.mov", "reason": SKIPPED_NO_CLEAN}],
        )
        data = edl.to_dict()
        self.assertEqual(data["events"][0]["audio"], "bed")
        self.assertEqual(data["skipped"][0]["reason"], "skipped: no clean window")
        self.assertEqual(edl_from_dict(data).to_dict(), data)
        self.assertNotIn("audio", Event("clip.mov", 0, 1).to_dict())
        self.assertNotIn("skipped", EditDecision().to_dict())

    def test_detector_thresholds_are_not_copied_into_the_cutter(self) -> None:
        from edittude_v3.media import edl, qc

        source = inspect.getsource(edl)
        for token in ("silencedetect", "blackdetect", "freezedetect", "-38dB", "-55dB", "pix_th"):
            self.assertNotIn(token, source)
        review_source = inspect.getsource(qc.review)
        self.assertNotIn("-38dB", review_source)
        self.assertIn("SILENCE_DETECT", review_source)
        self.assertEqual(SILENCE_DETECT, "silencedetect=n=-38dB:d=1.2")
        self.assertEqual(BLACK_DETECT, "blackdetect=d=0.2:pix_th=0.10")
        self.assertEqual(FREEZE_DETECT, "freezedetect=n=-55dB:d=1.4")
        self.assertEqual(
            f"{SILENCE_DETECT},ebur128=peak=true:framelog=verbose",
            "silencedetect=n=-38dB:d=1.2,ebur128=peak=true:framelog=verbose",
        )
        self.assertEqual(
            f"{BLACK_DETECT},{FREEZE_DETECT}",
            "blackdetect=d=0.2:pix_th=0.10,freezedetect=n=-55dB:d=1.4",
        )
        probe = inspect.getsource(edl._probe_spans)
        self.assertIn("look_chain(look)", probe)
        self.assertIn("color_convert_filter", probe)
        self.assertIn("BLACK_DETECT", probe)
        self.assertIn("FREEZE_DETECT", probe)
        self.assertNotIn("colorbalance", source)
        self.assertNotIn("eq=contrast", source)

    def test_audio_bed_is_one_pink_noise_constant(self) -> None:
        from edittude_v3.media import render

        self.assertEqual(AUDIO_BED, "anoisesrc=color=pink:r=48000:a=1:s=1,loudnorm=I=-45")
        source = inspect.getsource(render)
        self.assertEqual(source.count("color=pink"), 1)
        self.assertEqual(source.count("loudnorm=I=-45"), 1)
        self.assertNotIn("anullsrc", source)

    def test_every_ffmpeg_invocation_passes_nostdin(self) -> None:
        pattern = re.compile(
            r"""(?:run|subprocess\.run)\(\s*\[(?:\s*which\(\s*["']ffmpeg["']\s*\)|["']ffmpeg["'])"""
        )
        skip = {".venv", "venv", ".git", "site-packages", "__pycache__", "node_modules"}
        offenders = []
        for path in ROOT.rglob("*.py"):
            if skip.intersection(path.parts):
                continue
            text = path.read_text(encoding="utf-8")
            for match in pattern.finditer(text):
                window = text[match.start():match.start() + 500]
                if "-nostdin" not in window:
                    line = text[:match.start()].count("\n") + 1
                    offenders.append(f"{path.relative_to(ROOT)}:{line}")
        self.assertEqual(offenders, [])
        helper = inspect.getsource(
            __import__("edittude_v3.media.core", fromlist=["ffmpeg"]).ffmpeg
        )
        self.assertIn("-nostdin", helper)

    def test_day_out_pack_stays_edl_identical_for_clean_clips(self) -> None:
        manifest_path = ROOT / "tools" / "samples.json"
        pack = ROOT / "samples" / "day-out"
        if not manifest_path.is_file() or not pack.is_dir():
            self.skipTest("day-out pack not present")
        if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
            self.skipTest("FFmpeg/ffprobe unavailable")
        inventory = build_inventory(pack)
        if len([clip for clip in inventory["clips"] if clip.get("kind") == "video"]) < 2:
            self.skipTest("day-out pack not present")
        cut = first_cut(inventory)
        expected = _e1a_events(inventory["clips"])
        got = [
            (event.src, event.in_point, event.out_point, event.reason, event.audio)
            for event in cut.events
        ]
        oracle = [
            (event["src"], event["in"], event["out"], event["reason"], "")
            for event in expected
        ]
        self.assertEqual(got, oracle)
        self.assertEqual(cut.skipped, [])
        self.assertNotIn("skipped", cut.to_dict())


if __name__ == "__main__":
    unittest.main()
