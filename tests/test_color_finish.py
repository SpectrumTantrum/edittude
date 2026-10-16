"""Mixed colour tags must not stall finish on ffmpeg 7."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from edittude_v3.media.core import ffmpeg, ffprobe, run, which
from edittude_v3.media.edl import EditDecision, Event
from edittude_v3.media.inventory import describe_clip
from edittude_v3.media.qc import _parse_loudness
from edittude_v3.media.render import (
    LOUDNESS_I,
    LOUDNESS_TP,
    assemble,
    bt709_colorspace,
    finish,
    input_colorspace,
)


def _video(path: Path) -> dict:
    probe = ffprobe(path)
    return next(stream for stream in probe["streams"] if stream["codec_type"] == "video")


class ColorNormalizeTests(unittest.TestCase):
    def test_untagged_sd_converts_from_smpte170m_and_hd_from_bt709(self):
        sd = bt709_colorspace({"height": 480, "pix_fmt": "yuv420p", "color_space": "unknown"})
        self.assertIn("iall=smpte170m", sd)
        self.assertIn("all=bt709", sd)
        self.assertIn("range=tv", sd)
        self.assertIn("format=yuv420p", sd)
        self.assertEqual(input_colorspace({"height": 1080, "color_range": "tv"})[0], "bt709")
        tagged = bt709_colorspace({
            "height": 270,
            "color_space": "smpte170m",
            "color_primaries": "smpte170m",
            "color_transfer": "smpte170m",
            "color_range": "tv",
            "pix_fmt": "yuv420p",
        })
        self.assertIn("iall=smpte170m", tagged)
        self.assertNotIn("reinit_filter", sd)
        self.assertNotIn("reinit_filter", tagged)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/ffprobe unavailable")
    def test_mixed_color_segments_finish_matches_the_edl(self):
        with tempfile.TemporaryDirectory(prefix="edittude-color-") as folder:
            root = Path(folder)
            untagged = self._clip(root / "untagged.mp4", "160x90", [])
            bt709 = self._clip(root / "bt709.mp4", "320x180", [
                "colorprim=bt709:transfer=bt709:colormatrix=bt709",
            ])
            smpte = self._clip(root / "smpte.mp4", "160x90", [
                "colorprim=smpte170m:transfer=smpte170m:colormatrix=smpte170m",
            ])
            # The title card lasts 4s. The colour change has to land after that,
            # which is where ffmpeg 7 rebuilds the overlay and waits.
            edl = EditDecision(
                events=[
                    Event(str(untagged), 0, 5),
                    Event(str(bt709), 0, 1),
                    Event(str(smpte), 0, 1),
                ],
                title="A DAY OUT",
                fps=30,
                canvas_width=160,
                canvas_height=90,
            )
            self.assertGreater(edl.events[0].duration(), 4)
            self._assert_conversion_changes_pixels(smpte)
            with self._timeout(45):
                picture = assemble(edl, root / "picture.mp4", root / "work")
                final = finish(picture, root / "final.mp4", edl=edl)
            tags = []
            for segment in sorted((root / "work").glob("seg_*.mp4")):
                stream = _video(segment)
                tags.append((
                    stream.get("pix_fmt"),
                    stream.get("color_range"),
                    stream.get("color_space"),
                    stream.get("color_primaries"),
                    stream.get("color_transfer"),
                ))
            self.assertEqual(len(tags), 3)
            self.assertEqual(len(set(tags)), 1, tags)
            pix_fmt, color_range, space, primaries, transfer = tags[0]
            self.assertEqual(
                (pix_fmt, color_range, space, primaries, transfer),
                ("yuv420p", "tv", "bt709", "bt709", "bt709"),
            )
            expected = sum(max(1, round(event.duration() * edl.fps)) for event in edl.events)
            self.assertEqual(int(_video(final).get("nb_frames") or 0), expected)
            self.assertEqual(int(_video(picture).get("nb_frames") or 0), expected)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/ffprobe unavailable")
    def test_finish_true_peak_stays_under_the_ceiling(self):
        with tempfile.TemporaryDirectory(prefix="edittude-peak-") as folder:
            root = Path(folder)
            source = root / "hot.mp4"
            # Crest is high enough that a gain to -16 LUFS would pass -1.5 dBTP.
            tone = "0.25*sin(2*PI*440*t)+0.99*lt(mod(t\\,0.5)\\,0.003)"
            ffmpeg([
                "-f", "lavfi", "-i", "testsrc=size=160x90:rate=30:duration=4",
                "-f", "lavfi", "-i", f"aevalsrc={tone}:s=48000:d=4",
                "-shortest",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-x264-params", "colorprim=bt709:transfer=bt709:colormatrix=bt709",
                "-c:a", "aac", "-ar", "48000",
                str(source),
            ], capture=True)
            edl = EditDecision(
                events=[Event(str(source), 0, 4)],
                title="A DAY OUT",
                fps=30,
                canvas_width=160,
                canvas_height=90,
            )
            with self._timeout(45):
                final = finish(source, root / "final.mp4", edl=edl)
            meter = ffmpeg([
                "-i", str(final), "-af", "ebur128=peak=true", "-f", "null", "-",
            ], capture=True)
            stats = _parse_loudness((meter.stderr or "") + (meter.stdout or ""))
            self.assertIsNotNone(stats["TP"])
            self.assertLessEqual(stats["TP"], LOUDNESS_TP)
            self.assertLessEqual(abs(stats["I"] - LOUDNESS_I), 1.5)

    def _clip(self, dest: Path, size: str, x264_color: list[str]) -> Path:
        color = ["-x264-params", x264_color[0]] if x264_color else []
        ffmpeg([
            "-f", "lavfi", "-i", f"testsrc=size={size}:rate=30:duration=6",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=6",
            "-shortest",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            *color,
            "-c:a", "aac",
            str(dest),
        ], capture=True)
        return dest

    def _assert_conversion_changes_pixels(self, source: Path) -> None:
        clip = describe_clip(source)
        converted = source.with_name("converted.yuv")
        retagged = source.with_name("retagged.yuv")
        ffmpeg([
            "-i", str(source), "-frames:v", "1",
            "-vf", "scale=32:18," + bt709_colorspace(clip).replace("format=yuv420p", "format=yuv444p"),
            "-f", "rawvideo", str(converted),
        ], capture=True)
        ffmpeg([
            "-i", str(source), "-frames:v", "1",
            "-vf", "scale=32:18,format=yuv444p",
            "-f", "rawvideo", str(retagged),
        ], capture=True)
        self.assertNotEqual(converted.read_bytes(), retagged.read_bytes())

    def _timeout(self, seconds: float):
        original = __import__("edittude_v3.media.render", fromlist=["ffmpeg"]).ffmpeg

        def limited(args, *, capture=False):
            blob = " ".join(str(arg) for arg in args)
            if "reinit_filter" in blob:
                raise AssertionError(blob)
            return run([which("ffmpeg"), "-hide_banner", "-y", *args], capture=capture, timeout=seconds)

        return _Patch("edittude_v3.media.render.ffmpeg", limited, original)


class _Patch:
    def __init__(self, target: str, wrapped, original):
        self.target = target
        self.wrapped = wrapped
        self.original = original

    def __enter__(self):
        module_name, name = self.target.rsplit(".", 1)
        module = __import__(module_name, fromlist=[name])
        setattr(module, name, self.wrapped)
        return self.wrapped

    def __exit__(self, *exc):
        module_name, name = self.target.rsplit(".", 1)
        module = __import__(module_name, fromlist=[name])
        setattr(module, name, self.original)


if __name__ == "__main__":
    unittest.main()
