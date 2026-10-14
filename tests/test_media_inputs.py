"""Regression checks for media input handling: thumb paths, counts, titles, filter paths."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from edittude_v3.media.core import MediaError, ffmpeg
from edittude_v3.media.inventory import _thumb_positions, build_inventory, extract_thumbs
from edittude_v3.media.render import _escape_filter_path
from edittude_v3.media.titlecard import write_title_png


class MediaInputsTest(unittest.TestCase):
    def test_missing_footage_folder_exits_with_one_line(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            missing = root / "no-such-footage"
            out = root / "inventory.json"
            with self.assertRaises(MediaError) as raised:
                build_inventory(missing)
            message = f"{missing.resolve()}: no such footage folder"
            self.assertEqual(str(raised.exception), message)
            done = subprocess.run(
                [sys.executable, "-m", "edittude_v3", "media", "inventory", str(missing), "--out", str(out)],
                capture_output=True,
                text=True,
                cwd=root,
            )
            self.assertEqual(done.returncode, 1, done.stderr)
            self.assertEqual(done.stdout, "")
            self.assertEqual(done.stderr.splitlines(), [message])
            self.assertNotIn("Traceback", done.stderr)
            self.assertFalse(out.exists())

    def test_thumbs_keep_clips_with_the_same_stem_apart(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clips = []
            for folder in ("a", "b"):
                source = root / folder / "clip.mov"
                source.parent.mkdir()
                source.write_text(folder, encoding="utf-8")
                clips.append(
                    {"kind": "video", "name": source.name, "path": str(source), "duration": 1.0}
                )
            def copy(args):
                source = Path(args[args.index("-i") + 1]).read_text(encoding="utf-8")
                Path(args[-1]).write_text(source, encoding="utf-8")

            with patch("edittude_v3.media.inventory.ffmpeg", side_effect=copy):
                report = extract_thumbs({"clips": clips}, root / "thumbs")
            frames = [Path(frame) for item in report for frame in item["frames"]]
            self.assertEqual(len(frames), 6)
            self.assertEqual(len(set(frames)), 6)
            self.assertEqual({frame.read_text(encoding="utf-8") for frame in frames}, {"a", "b"})

    def test_thumb_positions_return_one_fraction_per_count(self):
        for count in (1, 2, 3, 10):
            with self.subTest(count=count):
                positions = _thumb_positions(count)
                self.assertEqual(len(positions), count)
                self.assertEqual(positions, sorted(positions))
                self.assertTrue(all(0 < value < 1 for value in positions))
        self.assertEqual(_thumb_positions(1), [0.5])
        self.assertEqual([round(value, 2) for value in _thumb_positions(3)], [0.12, 0.5, 0.88])
        with self.assertRaises(MediaError):
            _thumb_positions(0)

    def test_title_card_rejects_characters_it_cannot_draw(self):
        with tempfile.TemporaryDirectory() as temporary:
            card = Path(temporary) / "title.png"
            with self.assertRaises(MediaError) as raised:
                write_title_png(card, "DAY 1: THE END!", width=160, height=90)
            self.assertIn("!", str(raised.exception))
            self.assertIn("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -'./", str(raised.exception))
            self.assertFalse(card.exists())
            # The default flows pass lowercase text and punctuation that does have glyphs.
            write_title_png(card, "a day out", width=160, height=90, subtitle="city / date - '26.")
            self.assertTrue(card.is_file())

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg unavailable")
    def test_filter_path_escaping_survives_a_real_filtergraph(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "a,b[c];d'e f=g:h.ppm"
            source.write_bytes(b"P6\n1 1\n255\n\xff\x00\x00")
            out = Path(temporary) / "out.png"
            # movie= takes a filename option like subtitles= does, and needs no libass.
            def grab(escaped: str, dest: Path) -> None:
                ffmpeg(["-v", "error", "-f", "lavfi", "-i", f"movie={escaped}:loop=1",
                        "-frames:v", "1", str(dest)], capture=True)

            grab(_escape_filter_path(source), out)
            self.assertTrue(out.is_file())
            naive = str(source.resolve()).replace(":", "\\:").replace("'", "\\'")
            with self.assertRaises(MediaError):
                grab(naive, Path(temporary) / "naive.png")


if __name__ == "__main__":
    unittest.main()
