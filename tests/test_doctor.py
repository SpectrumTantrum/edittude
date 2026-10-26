"""Doctor checks, with subprocess and the filesystem mocked."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from edittude_v3.cli import main
from edittude_v3.doctor import Check, collect_checks, exit_code, format_json, format_text

SENTINEL = "sk-doctor-sentinel-9f3c2a7b1e"


def _completed(args: list[str], stdout: str = "", stderr: str = "", code: int = 0):
    return subprocess.CompletedProcess(args, code, stdout, stderr)


_ENCODERS = """
 V..... libx264              libx264 H.264
 A..... aac                  AAC
 A..... libopus              libopus Opus
 V..... libtheora            libtheora Theora
"""

_FILTERS = """
 T.. = Timeline support
 ... loudnorm          A->A       EBU R128 loudness normalization
 T.C alimiter          A->A       Audio lookahead limiter.
"""

_MODELS_OK = (
    ("asr", "configured", "ok"),
    ("separation", "configured", "ok"),
    ("seed-vc", "configured", "ok"),
    ("diffsinger", "configured", "ok"),
)


class DoctorChecksTest(unittest.TestCase):
    def _run(
        self,
        versions: dict[str, str],
        encoders: str = _ENCODERS,
        filters: str = _FILTERS,
        uv: str = "uv 0.9.0",
    ):
        def run(args, timeout=15):
            del timeout
            tool = Path(args[0]).name
            if tool in {"ffmpeg", "ffprobe"} and args[1] == "-version":
                return _completed(args, stdout=versions[tool])
            if tool == "ffmpeg" and args[-1] == "-encoders":
                return _completed(args, stdout=encoders)
            if tool == "ffmpeg" and args[-1] == "-filters":
                return _completed(args, stdout=filters)
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
                cache=kwargs.get("cache", root / "cache"),
                footage=kwargs.get("footage", root / "footage"),
                footage_note=kwargs.get("footage_note"),
                disk_usage=kwargs.get("disk_usage", lambda path: type("Usage", (), {"free": 5 * 1024**3})()),
                model_rows=kwargs.get("model_rows", _MODELS_OK),
                key_present=kwargs.get("key_present", True),
                python_version=kwargs.get("python_version", (3, 13, 17)),
                cuda_message=kwargs.get("cuda_message", "no CUDA device"),
            )

    def test_pass_path_is_ok_and_prints_the_version(self):
        checks = self._checks()
        self.assertEqual(exit_code(checks), 0)
        by_name = {check.name: check for check in checks}
        self.assertEqual(by_name["ffmpeg"].status, "pass")
        self.assertEqual(by_name["ffmpeg"].message, "7.1.5")
        self.assertEqual(by_name["ffprobe"].status, "pass")
        self.assertEqual(by_name["encoder-libx264"].status, "pass")
        self.assertEqual(by_name["encoder-aac"].status, "pass")
        self.assertEqual(by_name["encoder-libopus"].status, "pass")
        self.assertEqual(by_name["encoder-libtheora"].status, "pass")
        self.assertEqual(by_name["filter-loudnorm"].status, "pass")
        self.assertEqual(by_name["filter-alimiter"].status, "pass")
        self.assertEqual(by_name["key"].status, "info")
        self.assertEqual(by_name["key"].message, "present")
        self.assertEqual(by_name["models"].status, "pass")
        self.assertEqual(by_name["python"].status, "info")
        self.assertEqual(by_name["uv"].status, "info")
        self.assertEqual(by_name["cuda"].status, "info")
        self.assertEqual(by_name["disk-cache"].status, "pass")
        self.assertEqual(by_name["disk-footage"].status, "pass")
        text = format_text(checks)
        self.assertIn("ffmpeg              OK  7.1.5", text)
        self.assertNotIn("hint:", text)
        payload = json.loads(format_json(checks))
        self.assertTrue(payload["ok"])
        self.assertNotIn(SENTINEL, text)
        self.assertNotIn(SENTINEL, format_json(checks))

    def test_old_ffmpeg_and_optional_gaps_do_not_fail(self):
        encoders = "\n".join(
            line for line in _ENCODERS.splitlines() if "libopus" not in line and "libtheora" not in line
        )
        checks = self._checks(
            run=self._run({
                "ffmpeg": "ffmpeg version 6.1.1-3ubuntu5 Copyright\n",
                "ffprobe": "ffprobe version 6.1.1-3ubuntu5 Copyright\n",
            }, encoders=encoders),
            which=self._which({"ffmpeg", "ffprobe"}),
            model_rows=(("asr", "unavailable", "missing"), ("separation", "configured", "ok")),
            disk_usage=lambda path: type("Usage", (), {"free": 200 * 1024**2})(),
            python_version=(3, 12, 3),
            footage_note="cwd; no footage directory configured",
        )
        self.assertEqual(exit_code(checks), 0)
        by_name = {check.name: check for check in checks}
        self.assertEqual(by_name["ffmpeg"].status, "warn")
        self.assertIn("6.1.1", by_name["ffmpeg"].hint or "")
        self.assertIn("7.1", by_name["ffmpeg"].hint or "")
        self.assertEqual(by_name["ffprobe"].status, "pass")
        self.assertEqual(by_name["ffprobe"].message, "6.1.1")
        self.assertEqual(by_name["encoder-libx264"].status, "pass")
        self.assertEqual(by_name["encoder-aac"].status, "pass")
        self.assertEqual(by_name["encoder-libopus"].status, "warn")
        self.assertIn("libopus", by_name["encoder-libopus"].hint or "")
        self.assertEqual(by_name["encoder-libtheora"].status, "warn")
        self.assertEqual(by_name["models"].status, "warn")
        self.assertIn("asr", by_name["models"].hint or "")
        self.assertNotIn("separation", by_name["models"].hint or "")
        self.assertEqual(by_name["disk-footage"].status, "warn")
        self.assertIn("cwd; no footage directory configured", by_name["disk-footage"].hint or "")
        self.assertEqual(by_name["python"].status, "info")
        self.assertEqual(by_name["uv"].status, "info")
        self.assertEqual(by_name["uv"].message, "not on PATH")
        text = format_text(checks)
        for line in text.splitlines():
            if "OK" not in line.split("  ", 1)[-1]:
                self.assertNotIn("hint:", line)
                self.assertTrue(line.strip().endswith("."))

    def test_missing_filter_fails_with_one_sentence(self):
        filters = "\n".join(line for line in _FILTERS.splitlines() if "loudnorm" not in line)
        checks = self._checks(run=self._run({
            "ffmpeg": "ffmpeg version 7.1.5 Copyright\n",
            "ffprobe": "ffprobe version 7.1.5 Copyright\n",
        }, filters=filters))
        self.assertEqual(exit_code(checks), 1)
        by_name = {check.name: check for check in checks}
        self.assertEqual(by_name["filter-loudnorm"].status, "fail")
        self.assertIn("loudnorm", by_name["filter-loudnorm"].hint or "")
        self.assertEqual(by_name["filter-alimiter"].status, "pass")
        payload = json.loads(format_json(checks))
        self.assertFalse(payload["ok"])
        text = format_text(checks)
        self.assertIn("Install an ffmpeg build that provides the loudnorm filter.", text)
        self.assertNotIn("\nhint:", text)

    def test_missing_encoder_fails_with_one_sentence(self):
        encoders = "\n".join(line for line in _ENCODERS.splitlines() if "libx264" not in line)
        checks = self._checks(run=self._run({
            "ffmpeg": "ffmpeg version 7.1.5 Copyright\n",
            "ffprobe": "ffprobe version 7.1.5 Copyright\n",
        }, encoders=encoders))
        self.assertEqual(exit_code(checks), 1)
        failed = next(check for check in checks if check.name == "encoder-libx264")
        self.assertEqual(failed.status, "fail")
        self.assertIn("libx264", failed.hint or "")
        self.assertIn("Install an ffmpeg build with libx264.", format_text(checks))

    def test_missing_ffmpeg_fails_required_tools_only(self):
        def refuse_spawn(*args, **kwargs):
            raise AssertionError(f"should not spawn {args}")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checks = collect_checks(
                which=lambda name: None,
                run=refuse_spawn,
                cache=root / "cache",
                footage=root / "footage",
                disk_usage=lambda path: type("Usage", (), {"free": 5 * 1024**3})(),
                model_rows=_MODELS_OK,
                key_present=True,
                python_version=(3, 13, 17),
                cuda_message="no CUDA device",
            )
        self.assertEqual(exit_code(checks), 1)
        by_name = {check.name: check for check in checks}
        self.assertEqual(by_name["ffmpeg"].status, "fail")
        self.assertIn("PATH", by_name["ffmpeg"].hint or "")
        self.assertEqual(by_name["ffprobe"].status, "fail")
        self.assertEqual(by_name["encoder-libx264"].status, "fail")
        self.assertEqual(by_name["encoder-aac"].status, "fail")
        self.assertEqual(by_name["filter-loudnorm"].status, "fail")
        self.assertEqual(by_name["filter-alimiter"].status, "fail")
        self.assertEqual(by_name["encoder-libopus"].status, "warn")
        self.assertEqual(by_name["encoder-libtheora"].status, "warn")
        payload = json.loads(format_json(checks))
        self.assertFalse(payload["ok"])

    def test_no_key_warns_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / ".env").write_text("OTHER=1\n", encoding="utf-8")
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "", "EDITTUDE_CONFIG_HOME": str(home)}):
                checks = self._checks(key_present=None)
        self.assertEqual(exit_code(checks), 0)
        key = next(check for check in checks if check.name == "key")
        self.assertEqual(key.status, "warn")
        self.assertIn("DEEPSEEK_API_KEY", key.hint or "")
        self.assertNotIn("=", key.hint or "")

    def test_missing_models_warn_and_exit_zero(self):
        checks = self._checks(model_rows=(
            ("asr", "unavailable", "missing weights"),
            ("seed-vc", "unavailable", "missing checkpoint"),
            ("separation", "configured", "ok"),
        ))
        self.assertEqual(exit_code(checks), 0)
        models = next(check for check in checks if check.name == "models")
        self.assertEqual(models.status, "warn")
        self.assertIn("asr", models.hint or "")
        self.assertIn("seed-vc", models.hint or "")
        self.assertNotIn("separation", models.hint or "")
        self.assertIn("models install", models.hint or "")

    def test_models_use_install_check_offline(self):
        with tempfile.TemporaryDirectory() as temporary, patch(
            "tools.install_models.model_status",
            return_value=[("asr", "configured", "ok")],
        ) as status:
            root = Path(temporary)
            checks = collect_checks(
                which=self._which({"ffmpeg", "ffprobe", "uv"}),
                run=self._run({
                    "ffmpeg": "ffmpeg version 7.1.5 Copyright\n",
                    "ffprobe": "ffprobe version 7.1.5 Copyright\n",
                }),
                cache=root / "cache",
                footage=root / "footage",
                disk_usage=lambda path: type("Usage", (), {"free": 5 * 1024**3})(),
                key_present=True,
                python_version=(3, 13,),
                cuda_message="no CUDA device",
            )
        status.assert_called_once_with(probe_vision=False)
        self.assertEqual(next(check for check in checks if check.name == "models").status, "pass")

    def test_model_status_offline_does_not_open_a_url(self):
        def fake_run(arguments, *args, **kwargs):
            del args, kwargs
            payload = json.dumps({"faster_whisper": False, "demucs": False, "torch": False})
            return subprocess.CompletedProcess(arguments, 0, payload, "")

        with tempfile.TemporaryDirectory() as temporary, patch("tools.models.run", fake_run), patch(
            "tools.models.urllib.request.urlopen",
            side_effect=AssertionError("network"),
        ), patch.dict(os.environ, {"EDITTUDE_MODELS_DIR": temporary}):
            from tools.install_models import model_status

            rows = model_status(probe_vision=False)
        self.assertTrue(rows)
        self.assertTrue(all(status != "configured" for _name, status, _reason in rows))

    def test_sentinel_key_never_appears_in_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / ".env").write_text(f"DEEPSEEK_API_KEY={SENTINEL}\n", encoding="utf-8")
            versions = {
                "ffmpeg": "ffmpeg version 7.1.5 Copyright\n",
                "ffprobe": "ffprobe version 7.1.5 Copyright\n",
            }
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "", "EDITTUDE_CONFIG_HOME": str(home)}):
                checks = self._checks(key_present=None)
                rendered = format_text(checks) + format_json(checks)
                self.assertNotIn(SENTINEL, rendered)
                self.assertEqual(next(check for check in checks if check.name == "key").message, "present")
                self.assertEqual(exit_code(checks), 0)
            (home / ".env").write_text("DEEPSEEK_API_KEY=\n", encoding="utf-8")
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": SENTINEL, "EDITTUDE_CONFIG_HOME": str(home)}):
                out = io.StringIO()
                err = io.StringIO()
                with patch("edittude_v3.doctor._spawn", self._run(versions)), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    main(["doctor"])
                    main(["doctor", "--json"])
                blob = out.getvalue() + err.getvalue()
                self.assertNotIn(SENTINEL, blob)
                self.assertIn('"message": "present"', blob)
                self.assertIn("OK  present", blob)

    def test_cli_prints_ok_or_one_sentence_and_exits_on_fail(self):
        sentence = "Install an ffmpeg build that provides the loudnorm filter."
        failed = [Check("filter-loudnorm", "fail", sentence, sentence)]
        warned = [Check(
            "ffmpeg",
            "warn",
            "ffmpeg 6.1.1 is older than 7.1; install ffmpeg 7.1 or newer.",
            "ffmpeg 6.1.1 is older than 7.1; install ffmpeg 7.1 or newer.",
        )]
        with patch("edittude_v3.doctor.collect_checks", return_value=failed):
            output = io.StringIO()
            with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
                main(["doctor"])
            self.assertEqual(raised.exception.code, 1)
            self.assertIn(sentence, output.getvalue())
            self.assertNotIn("fail  ", output.getvalue())
            json_out = io.StringIO()
            with contextlib.redirect_stdout(json_out), self.assertRaises(SystemExit):
                main(["doctor", "--json"])
            payload = json.loads(json_out.getvalue())
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["checks"][0]["hint"], sentence)
        with patch("edittude_v3.doctor.collect_checks", return_value=warned):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                main(["doctor"])
            self.assertIn("ffmpeg 6.1.1 is older than 7.1; install ffmpeg 7.1 or newer.", output.getvalue())
            self.assertNotIn("OK", output.getvalue())

    def test_cli_passes_workspace_as_footage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch("edittude_v3.doctor.collect_checks", return_value=[]) as collect:
                with contextlib.redirect_stdout(io.StringIO()):
                    main(["-C", str(root), "doctor"])
                self.assertEqual(collect.call_args.kwargs["footage"], root.resolve())
                self.assertIsNone(collect.call_args.kwargs["footage_note"])
                with contextlib.redirect_stdout(io.StringIO()):
                    main(["doctor"])
                self.assertEqual(
                    collect.call_args.kwargs["footage_note"],
                    "cwd; no footage directory configured",
                )


if __name__ == "__main__":
    unittest.main()
