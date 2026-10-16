"""Offline proof on the day-out sample pack. Skips when the pack is not on disk."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from edittude_v3.media.core import ffprobe
from edittude_v3.media.proof import run_proof

ROOT = Path(__file__).resolve().parents[1]


def _video_stream(probe: dict) -> dict:
    return next(stream for stream in probe["streams"] if stream["codec_type"] == "video")


class SampleProofTest(unittest.TestCase):
    def test_day_out_proof_matches_the_edl(self):
        manifest_path = ROOT / "tools" / "samples.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        missing = [clip["file"] for clip in manifest["clips"] if not (ROOT / clip["file"]).is_file()]
        if missing or not (ROOT / manifest["pack"]).is_dir():
            self.skipTest("sample pack not present")
        if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
            self.skipTest("FFmpeg/ffprobe unavailable")
        # 30000/1001 is not 30. Compare rates as exact fractions.
        self.assertNotEqual(Fraction("30000/1001"), Fraction(30))

        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "out"
            evidence = run_proof(ROOT / manifest["pack"], out)
            final = out / "final.mp4"
            probe = ffprobe(final)
            kinds = {stream["codec_type"] for stream in probe["streams"]}
            video = _video_stream(probe)
            edl = json.loads((out / "edl.json").read_text(encoding="utf-8"))
            edl_rate = Fraction(edl["fps"])
            final_rate = Fraction(video["avg_frame_rate"])
            final_duration = float(probe["format"]["duration"])
            edl_duration = float(evidence["edl_duration"])
            limit = float(Fraction(1) / edl_rate)
            qc = json.loads((out / "qc.json").read_text(encoding="utf-8"))

            with self.subTest("streams"):
                self.assertIn("video", kinds)
                self.assertIn("audio", kinds)
            with self.subTest("frame rate"):
                self.assertEqual(final_rate, edl_rate)
            with self.subTest("duration"):
                self.assertLessEqual(abs(final_duration - edl_duration), limit)
            with self.subTest("per clip"):
                self._assert_per_clip(out, edl, edl_rate)
            with self.subTest("qc"):
                self.assertEqual(qc["issues"], [])
                self.assertIs(qc["pass"], True)

    def _assert_per_clip(self, out: Path, edl: dict, edl_rate: Fraction) -> None:
        """One frame of slack per event, at that clip's rate when the EDL names its span."""
        saw_other_rate = False
        for index, event in enumerate(edl["events"]):
            self.assertIn("in", event)
            self.assertIn("out", event)
            src_video = _video_stream(ffprobe(Path(event["src"])))
            clip_rate = Fraction(src_video["avg_frame_rate"])
            self.assertGreater(clip_rate, 0)
            if clip_rate != edl_rate:
                saw_other_rate = True
            # NTSC clip rate stays 30000/1001. Do not widen it to the integer EDL rate.
            if clip_rate == Fraction(30000, 1001):
                self.assertNotEqual(clip_rate, edl_rate)
                self.assertEqual(Fraction(1) / clip_rate, Fraction(1001, 30000))
            segment = ffprobe(out / "work" / f"seg_{index:03d}.mp4")
            segment_duration = float(segment["format"]["duration"])
            event_duration = float(event["out"]) - float(event["in"])
            slack = float(Fraction(1) / clip_rate)
            self.assertLessEqual(
                abs(segment_duration - event_duration),
                slack,
                f"{event['src']} moved by more than one frame at {clip_rate}",
            )
        self.assertTrue(saw_other_rate, "pack should include a clip rate other than the EDL rate")


if __name__ == "__main__":
    unittest.main()
