"""Real FFmpeg smoke checks and MIDI/path-boundary regression checks; no models."""
from __future__ import annotations

import array
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
import wave

from tools.common import artifact_path, input_path, output_path, run
from tools.media import audio_timing, media_inspect, media_render, score_read


def vlq(value):
    result = [value & 127]
    while value := value >> 7:
        result.insert(0, 128 | (value & 127))
    return bytes(result)


def midi(tracks, division=480):
    header = b"MThd" + struct.pack(">IHHH", 6, int(len(tracks) > 1), len(tracks), division)
    return header + b"".join(b"MTrk" + struct.pack(">I", len(track)) + track for track in tracks)


class MediaToolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="edittude-media-test-")
        cls.root = Path(cls.temporary.name).resolve()
        cls.ffmpeg = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
        if cls.ffmpeg:
            run(["ffmpeg", "-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i",
                 "testsrc2=size=320x180:rate=25:duration=5", "-f", "lavfi", "-i",
                 "sine=frequency=440:sample_rate=48000:duration=5", "-ac", "2", "-c:v",
                 "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", cls.root / "source.mov"])
            run(["ffmpeg", "-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i",
                 "sine=frequency=220:sample_rate=48000:duration=2", "-ac", "2", "-c:a", "pcm_s16le", cls.root / "bed.wav"])
            run(["ffmpeg", "-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i",
                 "color=blue:size=160x160:rate=25:duration=1", "-c:v", "libx264", cls.root / "silent.mp4"])
        signal = array.array("h", [int(3000 * math.sin(2*math.pi*440*i/16000))
                                  if .5 <= i/16000 < 1.5 else 0 for i in range(32000)])
        with wave.open(str(cls.root / "signal.wav"), "wb") as output:
            output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            output.writeframes(signal.tobytes())

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def require_ffmpeg(self):
        if not self.ffmpeg:
            self.skipTest("FFmpeg/ffprobe unavailable")

    def render(self, operation, output, **options):
        return media_render(self.root, {"op": operation, "output": output, **options})

    def test_audio_pipeline_and_picture_preservation(self):
        self.require_ffmpeg()
        source = self.root / "source.mov"
        hashes = {path: hashlib.sha256(path.read_bytes()).digest() for path in (source, self.root / "bed.wav")}
        extracted = self.render("extract_audio", "/extracted.wav", path="/source.mov")
        self.assertEqual(extracted["output_path"], "/extracted.wav")
        self.assertAlmostEqual(extracted["duration"], 5, places=5)
        model = self.render("resample", "/model.wav", path="/extracted.wav", sample_rate=16000, channels=1)
        stream = model["probe"]["streams"][0]
        self.assertEqual((stream["sample_rate"], stream["channels"]), ("16000", 1))
        self.assertAlmostEqual(model["duration"], 5, places=5)
        mixed = self.render("mix", "/mixed.wav", path="/extracted.wav", music="/bed.wav")
        self.assertAlmostEqual(mixed["duration"], 5, places=5)
        normalized = self.render("normalize", "/normalized.wav", path="/mixed.wav", integrated_lufs=-16, true_peak_dbtp=-1.5)
        self.assertLessEqual(abs(normalized["loudness"]["integrated_lufs"] + 16), .5)
        self.assertLessEqual(normalized["loudness"]["true_peak_dbtp"], -1.5)
        muxed = self.render("mux", "/final.mp4", path="/source.mov", audio="/normalized.wav")
        self.assertAlmostEqual(muxed["duration"], 5, places=5)
        short_mux = self.render("mux", "/short-audio.mp4", path="/source.mov", audio="/bed.wav")
        self.assertAlmostEqual(short_mux["duration"], 5, places=5)
        frames = []
        for path in (source, self.root / "final.mp4"):
            output = run(["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-map", "0:v:0", "-f", "framemd5", "-"]).stdout
            frames.append([line for line in output.splitlines() if not line.startswith("#")])
        self.assertEqual(frames[0], frames[1])
        self.assertEqual(len(frames[0]), 125)
        self.assertEqual(hashes, {path: hashlib.sha256(path.read_bytes()).digest() for path in hashes})

    def test_inspection_previews_and_decode(self):
        self.require_ffmpeg()
        result = media_inspect(self.root, {"path": "/source.mov", "modes": ["probe", "frames", "loudness", "decode"],
                                         "timestamps": [.55, 4.92], "output_dir": "/previews",
                                         "audio_preview": {"output": "/preview.wav", "start": 1, "duration": 1.25}})
        self.assertEqual(result["probe"]["format"]["filename"], "/source.mov")
        self.assertEqual(result["decode"]["status"], "passed")
        self.assertEqual(len(result["frames"]), 2)
        for frame in result["frames"]:
            self.assertTrue(input_path(self.root, frame["path"]).is_file())
            self.assertLessEqual(abs(frame["timestamp"]-frame["requested_timestamp"]), 1/25 + 1e-6)
        self.assertAlmostEqual(result["audio_preview"]["duration"], 1.25, places=5)

    def test_trim_concat_and_explicit_timeline(self):
        self.require_ffmpeg()
        trimmed = self.render("trim", "/trim.wav", path="/signal.wav", start=.5, end=1.5)
        self.assertAlmostEqual(trimmed["duration"], 1, places=5)
        joined = self.render("concat", "/joined.wav", paths=["/trim.wav", "/bed.wav"], sample_rate=48000, channels=2)
        self.assertAlmostEqual(joined["duration"], 3, places=5)
        shots = [{"id": "one", "path": "/source.mov", "source_start": 1, "source_end": 2, "start": 0, "end": 1},
                 {"id": "two", "path": "/silent.mp4", "source_start": 0, "source_end": 1, "start": 1, "end": 2}]
        timeline = self.render("timeline", "/timeline.mp4", shots=shots, width=160, height=160, fps=25, fit="pad", audio_policy="keep")
        self.assertAlmostEqual(timeline["duration"], 2, places=4)
        video = next(stream for stream in timeline["probe"]["streams"] if stream["codec_type"] == "video")
        self.assertEqual((video["width"], video["height"], int(video["nb_frames"])), (160, 160, 50))
        self.assertTrue(any(stream["codec_type"] == "audio" for stream in timeline["probe"]["streams"]))
        cropped = self.render("timeline", "/cropped.mp4", shots=shots[:1], width=160, height=160, fps=25, fit="crop", audio_policy="mute")
        self.assertFalse(any(stream["codec_type"] == "audio" for stream in cropped["probe"]["streams"]))
        with self.assertRaisesRegex(ValueError, "continuous"):
            self.render("timeline", "/gap.mp4", shots=[{**shots[0], "start": 1, "end": 2}])
        self.assertFalse((self.root / "gap.mp4").exists())

    def test_measured_timing_is_not_a_fake_beat_grid(self):
        self.require_ffmpeg()
        result = audio_timing(self.root, {"path": "/signal.wav", "method": "silence", "minimum_silence": .2, "output": "/silences.json"})
        self.assertEqual(len(result["silences"]), 2)
        self.assertAlmostEqual(result["silences"][0]["end"], .5, delta=.001)
        self.assertAlmostEqual(result["silences"][1]["start"], 1.5, delta=.001)
        onsets = audio_timing(self.root, {"path": "/signal.wav", "method": "onsets", "window_ms": 50})
        self.assertTrue(onsets["events"])
        self.assertTrue(all(event["kind"] == "energy_onset" for event in onsets["events"]))
        self.assertAlmostEqual(onsets["events"][0]["time"], .525, delta=.05)
        self.assertEqual(json.loads((self.root / "silences.json").read_text())["method"], "silencedetect")

    def test_midi_tempo_crossing_and_later_note(self):
        conductor = b"\0\xff\x51\x03\x07\xa1\x20" + vlq(480) + b"\xff\x51\x03\x0f\x42\x40" + vlq(960) + b"\xff\x2f\0"
        vocal = b"\0\xff\x03\x05Voice" + vlq(240) + b"\x90\x3c\x40" + vlq(480) + b"\x80\x3c\0" + vlq(240) + b"\x90\x3e\x40" + vlq(480) + b"\x3e\0" + b"\0\xff\x2f\0"
        (self.root / "score.mid").write_bytes(midi([conductor, vocal]))
        result = score_read(self.root, {"path": "/score.mid", "track": 1, "output": "/score.json"})
        first, second = result["tracks"][0]["notes"]
        self.assertEqual(first["pitch"], "C4")
        self.assertEqual((first["start"], first["end"], first["duration"]), (.25, 1, .75))
        self.assertEqual((second["start"], second["end"], second["duration"]), (1.5, 2.5, 1))
        self.assertEqual(result["duration"], 2.5)
        self.assertEqual(result["tracks"][0]["rests"], [{"start": 0, "end": .25}, {"start": 1, "end": 1.5}])
        conflict = b"\0\xff\x51\x03\x07\xa1\x20\0\xff\x51\x03\x0f\x42\x40\0\xff\x2f\0"
        (self.root / "conflict.mid").write_bytes(midi([conflict]))
        with self.assertRaisesRegex(ValueError, "Conflicting tempo"):
            score_read(self.root, {"path": "/conflict.mid"})
        smpte = vlq(100) + b"\x90\x3c\x40" + vlq(500) + b"\x80\x3c\0\0\xff\x2f\0"
        (self.root / "smpte.mid").write_bytes(midi([smpte], division=(231 << 8) | 40))
        note = score_read(self.root, {"path": "/smpte.mid"})["tracks"][0]["notes"][0]
        self.assertAlmostEqual(note["start"], .1)
        self.assertAlmostEqual(note["end"], .6)

    def test_path_guards_and_invalid_requests(self):
        self.assertEqual(input_path(self.root, "/signal.wav"), self.root / "signal.wav")
        self.assertEqual(input_path(self.root, str(self.root / "signal.wav")), self.root / "signal.wav")
        self.assertEqual(artifact_path(self.root, self.root / "signal.wav"), "/signal.wav")
        with self.assertRaises(ValueError):
            input_path(self.root, "../signal.wav")
        with self.assertRaises(FileExistsError):
            output_path(self.root, "/signal.wav")
        with tempfile.TemporaryDirectory() as outside:
            (self.root / "escape").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                output_path(self.root, "/escape/out.wav")
            with self.assertRaises(ValueError):
                input_path(self.root, "/escape/missing.wav")
        for function in (media_inspect, media_render, audio_timing, score_read):
            with self.assertRaises(ValueError):
                function(self.root, {})
            with self.assertRaises(ValueError):
                function(self.root, [])
        self.assertEqual(list(self.root.glob(".media-*")), [])


if __name__ == "__main__":
    unittest.main()
