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
    color_convert_filter,
    finish,
    input_colorspace,
    relabel_only,
)


def _yuv444_pixel(path: Path, width: int) -> tuple[int, int, int]:
    data = path.read_bytes()
    plane = width * width
    return data[0], data[plane], data[2 * plane]


def _video(path: Path) -> dict:
    probe = ffprobe(path)
    return next(stream for stream in probe["streams"] if stream["codec_type"] == "video")


# Limited-range red. smpte170m (BT.601) and bt709 put this patch on different pixels.
_RED_601 = (81, 90, 240)
_RED_709 = (73, 95, 229)


def _assert_bt709(testcase: unittest.TestCase, path: Path) -> None:
    stream = _video(path)
    testcase.assertEqual(
        (stream.get("color_space"), stream.get("color_primaries"), stream.get("color_transfer")),
        ("bt709", "bt709", "bt709"),
        path.name,
    )


class ColorNormalizeTests(unittest.TestCase):
    def test_untagged_sd_converts_from_smpte170m_and_hd_from_bt709(self):
        sd = bt709_colorspace({"height": 480, "pix_fmt": "yuv420p", "color_space": "unknown"})
        self.assertIn("iall=smpte170m", sd)
        self.assertIn("all=bt709", sd)
        self.assertIn("range=tv", sd)
        self.assertIn("format=yuv420p", sd)
        self.assertIn("iall=smpte170m", bt709_colorspace({"height": 719, "color_range": "unknown"}))
        self.assertEqual(input_colorspace({"height": 720, "color_range": "tv"})[0], "bt709")
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
        already = {
            "height": 1080,
            "color_space": "bt709",
            "color_primaries": "bt709",
            "color_transfer": "bt709",
            "color_range": "tv",
            "pix_fmt": "yuv420p",
        }
        self.assertTrue(relabel_only(already))
        self.assertIsNone(color_convert_filter(already))
        self.assertIsNotNone(color_convert_filter({"height": 480, "color_space": "unknown"}))
        for text in (sd, tagged):
            self.assertNotIn("reinit_filter", text)
            self.assertNotIn("h264_metadata", text)

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
            self._assert_red_patch_converts(root / "red.mp4")
            with self._timeout(45) as commands:
                picture = assemble(edl, root / "picture.mp4", root / "work")
                final = finish(picture, root / "final.mp4", edl=edl)
            blob = "\n".join(commands)
            self.assertNotIn("h264_metadata", blob)
            self.assertNotIn("reinit_filter", blob)
            segments = sorted((root / "work").glob("seg_*.mp4"))
            self.assertEqual(len(segments), 3)
            for segment in segments:
                stream = _video(segment)
                self.assertEqual(stream.get("pix_fmt"), "yuv420p")
                self.assertEqual(stream.get("color_range"), "tv")
                _assert_bt709(self, segment)
            _assert_bt709(self, final)
            expected = sum(max(1, round(event.duration() * edl.fps)) for event in edl.events)
            self.assertEqual(int(_video(final).get("nb_frames") or 0), expected)
            self.assertEqual(int(_video(picture).get("nb_frames") or 0), expected)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/ffprobe unavailable")
    def test_finish_true_peak_stays_under_the_ceiling(self):
        with tempfile.TemporaryDirectory(prefix="edittude-peak-") as folder:
            root = Path(folder)
            source = root / "hot.mp4"
            # Full-scale clicks every 40 ms. Loudnorm's dynamic fallback still
            # has to come back at or under the true-peak ceiling.
            tone = "0.99*lt(mod(t\\,0.04)\\,0.0015)+0.2*sin(2*PI*1000*t)"
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
            with self._timeout(45) as commands:
                final = finish(source, root / "final.mp4", edl=edl)
            encode = "\n".join(commands)
            self.assertIn("print_format=json", encode)
            self.assertRegex(
                encode,
                r"loudnorm=I=-16:TP=-1\.5:LRA=11,volume=-?[0-9.]+dB,alimiter=limit=",
            )
            self.assertIn("level=false", encode)
            self.assertIn("attack=0.1", encode)
            self.assertIn("release=5", encode)
            meter = ffmpeg([
                "-i", str(final), "-af", "ebur128=peak=true", "-f", "null", "-",
            ], capture=True)
            stats = _parse_loudness((meter.stderr or "") + (meter.stdout or ""))
            self.assertIsNotNone(stats["TP"])
            self.assertLessEqual(stats["TP"], LOUDNESS_TP, stats)
            # Peak-limited clicks. The trim has to land inside ±0.5 of -16
            # with the true-peak ceiling still held.
            self.assertLessEqual(abs(stats["I"] - LOUDNESS_I), 0.5, stats)

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

    def _assert_red_patch_converts(self, dest: Path) -> None:
        ffmpeg([
            "-f", "lavfi", "-i", "color=c=red:s=32x32:r=30:d=0.1",
            "-frames:v", "1",
            "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv420p",
            "-x264-params", "colorprim=smpte170m:transfer=smpte170m:colormatrix=smpte170m",
            str(dest),
        ], capture=True)
        clip = describe_clip(dest)
        convert = bt709_colorspace(clip).replace("format=yuv420p", "format=yuv444p")
        converted = dest.with_name("converted.yuv")
        retagged = dest.with_name("retagged.yuv")
        ffmpeg([
            "-i", str(dest), "-frames:v", "1", "-vf", convert, "-f", "rawvideo", str(converted),
        ], capture=True)
        ffmpeg([
            "-i", str(dest), "-frames:v", "1", "-vf", "format=yuv444p", "-f", "rawvideo", str(retagged),
        ], capture=True)
        self.assertEqual(_yuv444_pixel(converted, 32), _RED_709)
        self.assertEqual(_yuv444_pixel(retagged, 32), _RED_601)
        self.assertNotEqual(_yuv444_pixel(converted, 32), _yuv444_pixel(retagged, 32))

    def _timeout(self, seconds: float):
        original = __import__("edittude_v3.media.render", fromlist=["ffmpeg"]).ffmpeg
        commands: list[str] = []

        def limited(args, *, capture=False):
            blob = " ".join(str(arg) for arg in args)
            commands.append(blob)
            if "reinit_filter" in blob or "h264_metadata" in blob:
                raise AssertionError(blob)
            return run([which("ffmpeg"), "-hide_banner", "-nostdin", "-y", *args], capture=capture, timeout=seconds)

        return _Patch("edittude_v3.media.render.ffmpeg", limited, original, commands)


class _Patch:
    def __init__(self, target: str, wrapped, original, commands: list[str]):
        self.target = target
        self.wrapped = wrapped
        self.original = original
        self.commands = commands

    def __enter__(self):
        module_name, name = self.target.rsplit(".", 1)
        module = __import__(module_name, fromlist=[name])
        setattr(module, name, self.wrapped)
        return self.commands

    def __exit__(self, *exc):
        module_name, name = self.target.rsplit(".", 1)
        module = __import__(module_name, fromlist=[name])
        setattr(module, name, self.original)


if __name__ == "__main__":
    unittest.main()
