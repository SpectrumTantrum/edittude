"""Regression checks for the LLM-callable tool fixes; real FFmpeg, no network."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import get_tools, models
from tools.common import run
from tools.media import audio_timing, media_render


def black_columns(path: Path) -> tuple[int, int]:
    """Decoded frame size and how many of its columns are entirely black."""
    frame = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-frames:v", "1",
                            "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    width, height = (int(value) for value in run([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=width,height", "-of", "csv=p=0:s=,", path]).stdout.strip().split(","))
    return width, sum(1 for x in range(width) if all(frame[y*width+x] <= 16 for y in range(height)))


class Reply(io.BytesIO):
    """Stands in for urlopen's context-managed response."""
    def __enter__(self):
        return self

    def __exit__(self, *arguments):
        return False


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/ffprobe unavailable")
class LLMToolFixesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="edittude-llm-tools-test-")
        cls.root = Path(cls.temporary.name).resolve()
        for name, size, rate in (("source.mp4", "640x360", 25), ("f24.mp4", "320x180", 24), ("f60.mp4", "320x180", 60)):
            run(["ffmpeg", "-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i",
                 f"testsrc2=size={size}:rate={rate}:duration=3", "-f", "lavfi", "-i",
                 "sine=frequency=440:sample_rate=48000:duration=3", "-ac", "2", "-c:v", "libx264",
                 "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", cls.root / name])
        run(["ffmpeg", "-v", "error", "-nostdin", "-n", "-display_rotation", "90", "-i",
             cls.root / "source.mp4", "-c", "copy", cls.root / "rotated.mp4"])
        run(["ffmpeg", "-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i", "color=red:size=16x16",
             "-frames:v", "1", cls.root / "frame.png"])
        (cls.root / "broken.mp4").write_bytes(b"not a video" * 100)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.tools = {tool.__name__: tool for tool in get_tools(self.root)}

    def test_rotated_source_defaults_to_its_display_canvas(self):
        result = media_render(self.root, {"op": "timeline", "output": "/rotated-timeline.mp4",
                                          "shots": [{"path": "/rotated.mp4", "source_start": 0, "source_end": 1}]})
        self.assertEqual((result["width"], result["height"]), (360, 640))
        width, black = black_columns(self.root / "rotated-timeline.mp4")
        self.assertEqual((width, black), (360, 0))

    def test_timeline_renders_every_planned_frame_of_offbeat_cuts(self):
        spans = [("/source.mp4", .5, 2.0), ("/source.mp4", .1, 1.6), ("/source.mp4", .02, 1.52),
                 ("/source.mp4", .3, 1.0), ("/source.mp4", 0.0, 1.5), ("/source.mp4", 1.0, 2.5),
                 ("/f24.mp4", .5, 2.0), ("/f60.mp4", .3, 1.0)]
        for index, (source, start, end) in enumerate(spans):
            with self.subTest(source=source, span=(start, end)):
                result = media_render(self.root, {"op": "timeline", "output": f"/span-{index}.mp4",
                                                  "shots": [{"path": source, "source_start": start, "source_end": end}]})
                video = next(stream for stream in result["probe"]["streams"] if stream["codec_type"] == "video")
                self.assertEqual(int(video["nb_frames"]), result["expected_video_frames"])
        joined = media_render(self.root, {"op": "timeline", "output": "/two-shots.mp4", "shots": [
            {"path": "/source.mp4", "source_start": .5, "source_end": 2.0, "start": 0, "end": 1.5},
            {"path": "/source.mp4", "source_start": .1, "source_end": 1.6, "start": 1.5, "end": 3.0}]})
        streams = {stream["codec_type"]: stream for stream in joined["probe"]["streams"]}
        self.assertEqual(int(streams["video"]["nb_frames"]), joined["expected_video_frames"])
        self.assertAlmostEqual(float(streams["audio"]["duration"]), 3, places=3)

    def test_attribute_errors_are_reported_as_tool_errors(self):
        for directory in (None, 5):
            with self.subTest(output_dir=directory):
                result = self.tools["media_inspect"]("/source.mp4", ["audio_preview"], None, directory, None)
                self.assertEqual(result["status"], "error")
                self.assertIn("output_dir", result["error"])
        with patch("tools.models.urllib.request.urlopen",
                   return_value=Reply(json.dumps({"choices": [{"message": {"content": None}}]}).encode())):
            result = self.tools["image_describe"](["/frame.png"], "What is here?")
        self.assertEqual(result["status"], "error")
        self.assertIn("no message content", result["error"])

    def test_asr_capability_needs_installed_weights(self):
        real = models.run

        def stubbed(arguments, *args, **options):
            if len(arguments) > 2 and "find_spec" in str(arguments[2]):
                return subprocess.CompletedProcess(arguments, 0, json.dumps(
                    {"faster_whisper": True, "demucs": True, "torch": True}), "")
            return real(arguments, *args, **options)

        with patch.dict(os.environ, {"EDITTUDE_MODELS_DIR": str(self.root / "no-models")}), \
                patch.object(models, "run", stubbed):
            capability = models.capabilities()["speech_transcribe"]
        self.assertEqual(capability["status"], "unavailable")
        self.assertIn("EDITTUDE_ASR_MODEL_DIR", capability["reason"])

    def test_error_text_uses_virtual_workspace_paths(self):
        result = self.tools["media_render"]({"op": "trim", "path": "/broken.mp4",
                                             "output": "/broken.mp4.mov", "start": 0, "end": 1})
        self.assertEqual(result["status"], "error")
        self.assertNotIn(str(self.root), result["error"])
        self.assertIn("/broken.mp4", result["error"])

    def test_frames_of_different_sources_share_the_default_directory(self):
        first = self.tools["media_inspect"]("/source.mp4", ["frames"], [0.5])
        second = self.tools["media_inspect"]("/rotated.mp4", ["frames"], [0.5])
        self.assertEqual((first["status"], second["status"]), ("ok", "ok"))
        self.assertNotEqual(first["frames"][0]["path"], second["frames"][0]["path"])

    def test_rate_accepts_integral_numbers_and_ids_stay_off_errors(self):
        (self.root / "taken.wav").write_bytes(b"")
        for rate in (180.0, "180"):
            with self.subTest(rate=rate), self.assertRaises(FileExistsError):  # Past rate validation.
                models.speech_synthesize(self.root, "Hello.", "/taken.wav", rate=rate)
        with self.assertRaisesRegex(ValueError, "rate"):
            models.speech_synthesize(self.root, "Hello.", "/taken.wav", rate=180.5)
        result = self.tools["speech_synthesize"]("Hello.", "/spoken.wav", None, 9999, None, "utterance-1")
        self.assertEqual(result["status"], "error")
        self.assertNotIn("id", result)

    def test_vision_server_errors_are_reported_without_the_api_key(self):
        payload = {"error": {"message": "model not loaded"}}
        with patch.dict(os.environ, {"EDITTUDE_VISION_API_KEY": "secret-key-value"}), \
                patch("tools.models.urllib.request.urlopen", return_value=Reply(json.dumps(payload).encode())):
            url, model = models._vision()
            with self.assertRaises(RuntimeError) as raised:
                models.image_describe(self.root, ["/frame.png"], "What is here?")
        self.assertIn(model, str(raised.exception))
        self.assertIn(url, str(raised.exception))
        self.assertIn("model not loaded", str(raised.exception))
        self.assertNotIn("secret-key-value", str(raised.exception))

    def test_default_minimum_silence_fits_a_short_range(self):
        result = audio_timing(self.root, {"path": "/source.mp4", "method": "silence", "start": 0, "end": .1})
        self.assertAlmostEqual(result["settings"]["minimum_silence"], .1)
        with self.assertRaisesRegex(ValueError, "minimum_silence"):
            audio_timing(self.root, {"path": "/source.mp4", "method": "silence",
                                     "start": 0, "end": .1, "minimum_silence": .5})


if __name__ == "__main__":
    unittest.main()
