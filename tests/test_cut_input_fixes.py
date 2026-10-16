"""Regression checks for the five cut-input fixes."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from edittude_v3.media.core import ffmpeg, ffprobe
from edittude_v3.media.edl import (
    EditDecision,
    Event,
    first_cut,
    pick_music,
    pick_voiceover,
)
from edittude_v3.media.inventory import build_inventory, extract_thumbs, iter_media
from edittude_v3.media.render import assemble
from edittude_v3.paths import state_dir
from tools.media import media_render


def _clip(name: str, kind: str, duration: float) -> dict:
    return {"path": f"/footage/{name}", "name": name, "kind": kind, "duration": duration}


class CutInputFixesTest(unittest.TestCase):
    def require_ffmpeg(self):
        if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
            self.skipTest("FFmpeg/ffprobe unavailable")

    def test_ogv_counts_as_video_in_the_inventory(self):
        self.require_ffmpeg()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clip = root / "clip.ogv"
            bed = root / "bed.ogg"
            ffmpeg([
                "-f", "lavfi", "-i", "testsrc=size=160x90:rate=24:duration=0.6",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=0.6",
                "-c:v", "libtheora", "-c:a", "libvorbis", "-shortest", str(clip),
            ])
            ffmpeg([
                "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000:duration=0.6",
                "-c:a", "libvorbis", str(bed),
            ])
            inventory = build_inventory(root)
            kinds = {item["name"]: item for item in inventory["clips"]}
            self.assertEqual(set(kinds), {"clip.ogv", "bed.ogg"})
            self.assertEqual(kinds["clip.ogv"]["kind"], "video")
            self.assertTrue(kinds["clip.ogv"]["has_video"])
            self.assertTrue(kinds["clip.ogv"]["has_audio"])
            self.assertEqual(kinds["bed.ogg"]["kind"], "audio")
            self.assertFalse(kinds["bed.ogg"]["has_video"])

    def test_inventory_skips_the_harness_state_dir(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "shot.mp4").write_bytes(b"")
            offloaded = state_dir(root) / "media"
            offloaded.mkdir(parents=True, exist_ok=True)
            (offloaded / "render.mp4").write_bytes(b"")
            self.assertEqual([path.name for path in iter_media(root)], ["shot.mp4"])

    def test_thumbs_clear_stale_output(self):
        self.require_ffmpeg()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "shot.mp4"
            ffmpeg(["-v", "error", "-f", "lavfi", "-i",
                    "testsrc=size=160x90:rate=30:duration=2", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(source)])
            inventory = {"clips": [{"path": str(source), "name": "shot.mp4",
                                    "kind": "video", "duration": 2.0}]}
            out_dir = root / "thumbs"
            extract_thumbs(inventory, out_dir, count=5, width=64)
            clip_dir = out_dir / "000_shot"
            self.assertEqual(len(list(clip_dir.glob("*.jpg"))), 5)
            stale = out_dir / "009_gone"
            stale.mkdir()
            (stale / "00.jpg").write_bytes(b"")
            keep = out_dir / "notes"
            keep.mkdir()
            extract_thumbs(inventory, out_dir, count=2, width=64)
            self.assertEqual(sorted(path.name for path in clip_dir.glob("*.jpg")),
                             ["00.jpg", "01.jpg"])
            self.assertFalse(stale.exists())
            self.assertTrue(keep.is_dir())

    def test_unnamed_audio_is_music_not_the_narrator(self):
        videos = [_clip(f"clip{index}.mov", "video", 6.0) for index in range(6)]
        anonymous = {"clips": [*videos, _clip("track01.mp3", "audio", 95.0)]}
        self.assertIsNone(pick_voiceover(anonymous))
        self.assertEqual(pick_music(anonymous, None)["name"], "track01.mp3")
        cut = first_cut(anonymous)
        self.assertIsNone(cut.voiceover)
        self.assertEqual(cut.music, "/footage/track01.mp3")
        self.assertLess(cut.duration(), 61)
        narrated = {"clips": [*videos, _clip("narration.mp3", "audio", 95.0),
                              _clip("track01.mp3", "audio", 40.0)]}
        self.assertEqual(pick_voiceover(narrated)["name"], "narration.mp3")
        self.assertIsNone(pick_music(narrated, pick_voiceover(narrated)))

    def test_resample_requires_its_documented_settings(self):
        self.require_ffmpeg()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            ffmpeg(["-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=48000:duration=1", "-ac", "2",
                    "-c:a", "pcm_s16le", str(root / "voice.wav")])
            for request, message in (
                ({"channels": 1}, "sample_rate"),
                ({"sample_rate": 16000}, "channels"),
                ({"samplerate": 16000, "channels": 1}, "sample_rate"),
            ):
                with self.subTest(request=request), self.assertRaisesRegex(ValueError, message):
                    media_render(root, {"op": "resample", "output": "/out.wav",
                                        "path": "/voice.wav", **request})
            result = media_render(root, {"op": "resample", "output": "/asr.wav",
                                         "path": "/voice.wav", "sample_rate": 16000, "channels": 1})
            self.assertEqual(result["probe"]["streams"][0]["sample_rate"], "16000")

    def test_assemble_holds_the_edl_frame_rate(self):
        self.require_ffmpeg()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "shot.mp4"
            ffmpeg(["-v", "error", "-f", "lavfi", "-i",
                    "testsrc=size=160x90:rate=30:duration=6", "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=48000:duration=6", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)])
            for fps in (24, 30):
                with self.subTest(fps=fps):
                    out = root / f"picture{fps}.mp4"
                    events = [Event(src=str(source), in_point=.12 + index * .01,
                                    out_point=.12 + index * .01 + .977) for index in range(8)]
                    assemble(EditDecision(events=events, fps=fps, aspect="16:9"),
                             out, root / f"work{fps}")
                    video = next(stream for stream in ffprobe(out)["streams"]
                                 if stream["codec_type"] == "video")
                    self.assertEqual(video["avg_frame_rate"], f"{fps}/1")
                    self.assertEqual(video["r_frame_rate"], f"{fps}/1")


if __name__ == "__main__":
    unittest.main()
