"""Doctor checks, with subprocess and the filesystem mocked."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from edittude_v3.cli import main
from edittude_v3.doctor import Check, collect_checks, exit_code, format_json, format_text


def _completed(args: list[str], stdout: str = "", stderr: str = "", code: int = 0):
    return subprocess.CompletedProcess(args, code, stdout, stderr)


_ENCODERS = """
 V..... libx264              libx264 H.264
 A..... aac                  AAC
 A..... libopus              libopus Opus
 V..... libtheora            libtheora Theora
"""


class DoctorChecksTest(unittest.TestCase):
    def _run(self, versions: dict[str, str], encoders: str = _ENCODERS, uv: str = "uv 0.9.0"):
        def run(args, timeout=15):
            del timeout
            tool = Path(args[0]).name
            if tool in {"ffmpeg", "ffprobe"} and args[1] == "-version":
                return _completed(args, stdout=versions[tool])
            if tool == "ffmpeg" and args[-1] == "-encoders":
                return _completed(args, stdout=encoders)
            if tool == "uv":
                return _completed(args, stdout=uv + "\n")
            if tool == "nvidia-smi":
                return _completed(args, stdout="GPU 0: Test (UUID: GPU-test)\n")
            raise AssertionError(args)

        return run

    def _which(self, present: set[str]):
        def which(name: str) -> str | None:
            if name in present:
                return f"/usr/bin/{name}"
            return None

        return which

    def _checks(self, **kwargs):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            return collect_checks(
                which=kwargs.get("which", self._which({"ffmpeg", "ffprobe", "uv"})),
                run=kwargs.get("run", self._run({
                    "ffmpeg": "ffmpeg version 7.1.5 Copyright\n",
                    "ffprobe": "ffprobe version 7.1.5 Copyright\n",
                })),
                temp_dir=kwargs.get("temp_dir", root / "tmp"),
                cache=kwargs.get("cache", root / "cache"),
                disk_usage=kwargs.get("disk_usage", lambda path: type("Usage", (), {"free": 5 * 1024**3})()),
                model_items=kwargs.get("model_items", (("ASR", True), ("Demucs", True), ("Seed-VC", True), ("DiffSinger", True))),
                python_version=kwargs.get("python_version", (3, 13)),
                cuda_message=kwargs.get("cuda_message", "no CUDA device"),
            )

    def test_pass_path_has_no_failures(self):
        checks = self._checks()
        self.assertEqual(exit_code(checks), 0)
        by_name = {check.name: check for check in checks}
        self.assertEqual(by_name["ffmpeg"].status, "pass")
        self.assertEqual(by_name["ffprobe"].status, "pass")
        self.assertEqual(by_name["encoder-libx264"].status, "pass")
        self.assertEqual(by_name["encoder-aac"].status, "pass")
        self.assertEqual(by_name["encoder-libopus"].status, "pass")
        self.assertEqual(by_name["encoder-libtheora"].status, "pass")
        self.assertEqual(by_name["python"].status, "pass")
        self.assertEqual(by_name["uv"].status, "pass")
        self.assertEqual(by_name["temp"].status, "pass")
        self.assertEqual(by_name["cache"].status, "pass")
        self.assertEqual(by_name["disk"].status, "pass")
        self.assertEqual(by_name["models"].status, "pass")
        self.assertEqual(by_name["cuda"].status, "info")
        self.assertIsNone(by_name["ffmpeg"].hint)
        text = format_text(checks)
        self.assertNotIn("hint:", text)
        payload = json.loads(format_json(checks))
        self.assertTrue(payload["ok"])

    def test_old_ffmpeg_and_missing_optional_pieces_warn(self):
        encoders = "\n".join(line for line in _ENCODERS.splitlines() if "libtheora" not in line)
        checks = self._checks(
            run=self._run({
                "ffmpeg": "ffmpeg version 6.1.1-3ubuntu5 Copyright\n",
                "ffprobe": "ffprobe version 6.1.1-3ubuntu5 Copyright\n",
            }, encoders=encoders),
            which=self._which({"ffmpeg", "ffprobe"}),
            model_items=(("ASR", False), ("Demucs", False), ("Seed-VC", False), ("DiffSinger", True)),
            disk_usage=lambda path: type("Usage", (), {"free": 200 * 1024**2})(),
            python_version=(3, 12),
        )
        self.assertEqual(exit_code(checks), 0)
        by_name = {check.name: check for check in checks}
        self.assertEqual(by_name["ffmpeg"].status, "warn")
        self.assertIn("older than 7.1", by_name["ffmpeg"].message)
        self.assertIn("7.1", by_name["ffmpeg"].hint or "")
        self.assertEqual(by_name["ffprobe"].status, "warn")
        self.assertEqual(by_name["encoder-libtheora"].status, "warn")
        self.assertIn("libtheora", by_name["encoder-libtheora"].hint or "")
        self.assertEqual(by_name["encoder-libx264"].status, "pass")
        self.assertEqual(by_name["uv"].status, "warn")
        self.assertIn("uv", by_name["uv"].hint or "")
        self.assertEqual(by_name["python"].status, "warn")
        self.assertEqual(by_name["disk"].status, "warn")
        self.assertEqual(by_name["models"].status, "warn")
        self.assertIn("Seed-VC", by_name["models"].message)
        self.assertNotIn("DiffSinger", by_name["models"].message)
        self.assertIn("models install", by_name["models"].hint or "")
        text = format_text(checks)
        for line in text.splitlines():
            if line.startswith(("warn", "fail")):
                self.assertIn("hint:", line)

    def test_missing_ffmpeg_fails_and_exits_nonzero(self):
        def refuse_spawn(*args, **kwargs):
            raise AssertionError(f"should not spawn {args}")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            not_dir = root / "file"
            not_dir.write_text("x", encoding="utf-8")
            checks = collect_checks(
                which=lambda name: None,
                run=refuse_spawn,
                temp_dir=not_dir,
                cache=root / "cache",
                disk_usage=lambda path: type("Usage", (), {"free": 5 * 1024**3})(),
                model_items=(("ASR", False),),
                python_version=(3, 13),
                cuda_message="no CUDA device",
            )
        self.assertEqual(exit_code(checks), 1)
        by_name = {check.name: check for check in checks}
        self.assertEqual(by_name["ffmpeg"].status, "fail")
        self.assertIn("PATH", by_name["ffmpeg"].hint or "")
        self.assertEqual(by_name["ffprobe"].status, "fail")
        self.assertEqual(by_name["encoder-libx264"].status, "fail")
        self.assertEqual(by_name["encoder-aac"].status, "fail")
        self.assertEqual(by_name["encoder-libopus"].status, "fail")
        self.assertEqual(by_name["encoder-libtheora"].status, "warn")
        self.assertEqual(by_name["temp"].status, "fail")
        self.assertIn("TMPDIR", by_name["temp"].hint or "")
        payload = json.loads(format_json(checks))
        self.assertFalse(payload["ok"])
        failed = [item["name"] for item in payload["checks"] if item["status"] == "fail"]
        self.assertIn("ffmpeg", failed)

    def test_cli_prints_text_and_json_and_exits_on_fail(self):
        failed = [Check("ffmpeg", "fail", "not on PATH", "install ffmpeg and put ffmpeg on PATH")]
        warned = [Check("ffmpeg", "warn", "6.1.1 is older than 7.1", "install ffmpeg 7.1 or newer")]
        with patch("edittude_v3.doctor.collect_checks", return_value=failed):
            output = io.StringIO()
            with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
                main(["doctor"])
            self.assertEqual(raised.exception.code, 1)
            self.assertIn("fail  ffmpeg", output.getvalue())
            self.assertIn("hint: install ffmpeg", output.getvalue())
            json_out = io.StringIO()
            with contextlib.redirect_stdout(json_out), self.assertRaises(SystemExit):
                main(["doctor", "--json"])
            payload = json.loads(json_out.getvalue())
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["checks"][0]["hint"], failed[0].hint)
        with patch("edittude_v3.doctor.collect_checks", return_value=warned):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                main(["doctor"])
            self.assertIn("warn  ffmpeg", output.getvalue())
            self.assertIn("hint:", output.getvalue())


if __name__ == "__main__":
    unittest.main()
