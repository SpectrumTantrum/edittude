"""First launch with no DeepSeek key. Guidance once, and no paid client."""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from edittude_v3.agent import API_KEY_ENV, build_agent
from edittude_v3.cli import _NO_KEY_LINE, guide_offline, main

SENTINEL = "sk-doctor-sentinel-9f3c2a7b1e"


class FirstLaunchGuideTest(unittest.TestCase):
    def _home(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        home = Path(temporary.name)
        return temporary, home

    def test_first_launch_prints_doctor_key_page_and_media_once(self):
        temporary, home = self._home()
        with temporary:
            env = {API_KEY_ENV: "", "EDITTUDE_CONFIG_HOME": str(home)}
            with patch.dict(os.environ, env, clear=False):
                first = io.StringIO()
                with contextlib.redirect_stdout(first):
                    guide_offline()
                text = first.getvalue()
                self.assertIn("edittude doctor", text)
                self.assertIn("https://platform.deepseek.com/api_keys", text)
                self.assertIn("edittude media inventory", text)
                self.assertIn("edittude media proof", text)
                self.assertTrue((home / "offline-guide").is_file())
                self.assertNotIn(SENTINEL, (home / "offline-guide").read_text(encoding="utf-8"))
                second = io.StringIO()
                with contextlib.redirect_stdout(second):
                    guide_offline()
                self.assertEqual(second.getvalue(), "")

    def test_unwritable_config_and_cache_do_not_crash(self):
        temporary, home = self._home()
        with temporary:
            blocked_config = home / "config-file"
            blocked_cache = home / "cache-file"
            blocked_config.write_text("x", encoding="utf-8")
            blocked_cache.write_text("x", encoding="utf-8")
            env = {
                API_KEY_ENV: "",
                "EDITTUDE_CONFIG_HOME": str(blocked_config),
                "EDITTUDE_CACHE_DIR": str(blocked_cache),
            }
            with patch.dict(os.environ, env, clear=False):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    guide_offline()
                    guide_offline()
            self.assertIn("edittude doctor", out.getvalue())
            self.assertIn("https://platform.deepseek.com/api_keys", out.getvalue())

            cache = home / "cache"
            cache.mkdir()
            env["EDITTUDE_CACHE_DIR"] = str(cache)
            with patch.dict(os.environ, env, clear=False):
                first = io.StringIO()
                second = io.StringIO()
                with contextlib.redirect_stdout(first):
                    guide_offline()
                with contextlib.redirect_stdout(second):
                    guide_offline()
            self.assertIn("edittude doctor", first.getvalue())
            self.assertEqual(second.getvalue(), "")
            self.assertTrue((cache / "offline-guide").is_file())

    def test_saved_key_skips_first_launch_and_does_not_print_it(self):
        temporary, home = self._home()
        with temporary:
            (home / ".env").write_text(f"{API_KEY_ENV}={SENTINEL}\n", encoding="utf-8")
            with patch.dict(os.environ, {"EDITTUDE_CONFIG_HOME": str(home)}, clear=False):
                os.environ.pop(API_KEY_ENV, None)
                out = io.StringIO()
                err = io.StringIO()
                with (
                    patch("edittude_v3.cli.run_tui") as tui,
                    contextlib.redirect_stdout(out),
                    contextlib.redirect_stderr(err),
                ):
                    main([])
                blob = out.getvalue() + err.getvalue()
                self.assertNotIn("No DeepSeek key yet.", blob)
                self.assertNotIn("edittude doctor", blob)
                self.assertNotIn(SENTINEL, blob)
                self.assertNotIn(SENTINEL, "".join(path.read_text(encoding="utf-8") for path in home.rglob("offline-guide")))
                self.assertFalse(list(home.rglob("offline-guide")))
                tui.assert_called_once()

    def test_dummy_key_skips_guidance_and_does_not_leak(self):
        temporary, home = self._home()
        with temporary:
            (home / ".env").write_text(f"{API_KEY_ENV}=\n", encoding="utf-8")
            env = {API_KEY_ENV: SENTINEL, "EDITTUDE_CONFIG_HOME": str(home)}
            with patch.dict(os.environ, env, clear=False):
                out = io.StringIO()
                err = io.StringIO()
                with (
                    patch("edittude_v3.cli.run_tui") as tui,
                    contextlib.redirect_stdout(out),
                    contextlib.redirect_stderr(err),
                ):
                    main([])
                blob = out.getvalue() + err.getvalue()
                self.assertNotIn("edittude doctor", blob)
                self.assertNotIn(SENTINEL, blob)
                self.assertFalse((home / "offline-guide").exists())
                tui.assert_called_once()

    def test_no_paid_client_without_a_key(self):
        temporary, home = self._home()
        with temporary:
            env = {API_KEY_ENV: "", "EDITTUDE_CONFIG_HOME": str(home)}
            with patch.dict(os.environ, env, clear=False):
                with patch("edittude_v3.agent.init_chat_model") as client:
                    with self.assertRaises(SystemExit):
                        build_agent(workspace=home)
                client.assert_not_called()
                with (
                    patch("edittude_v3.agent.init_chat_model") as client,
                    patch("edittude_v3.cli.run_tui") as tui,
                    patch("edittude_v3.cli.sys.stdin.isatty", return_value=False),
                ):
                    out = io.StringIO()
                    err = io.StringIO()
                    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                        with self.assertRaises(SystemExit):
                            main([])
                        with self.assertRaises(SystemExit):
                            main(["ask", "make a cut"])
                client.assert_not_called()
                tui.assert_not_called()
                blob = out.getvalue() + err.getvalue()
                self.assertNotIn(SENTINEL, blob)
                self.assertNotIn("DEEPSEEK_API_KEY is missing", blob)
                self.assertNotIn("Traceback", blob)
                self.assertEqual(err.getvalue().count(_NO_KEY_LINE), 2)
                self.assertEqual(out.getvalue().count("No DeepSeek key yet."), 1)

    def test_every_nokey_launch_prints_one_stderr_line(self):
        for command in (["chat"], ["ask", "make a cut"]):
            temporary, home = self._home()
            with temporary:
                env = {
                    API_KEY_ENV: "",
                    "EDITTUDE_CONFIG_HOME": str(home),
                    "EDITTUDE_CACHE_DIR": str(home / "cache"),
                }
                with patch.dict(os.environ, env, clear=False):
                    with patch("edittude_v3.cli.sys.stdin.isatty", return_value=False):
                        first_out, first_err, first_code = self._launch(command)
                        second_out, second_err, second_code = self._launch(command)
                self.assertEqual(first_code, 1)
                self.assertEqual(second_code, 1)
                self.assertIn("No DeepSeek key yet.", first_out)
                self.assertIn("https://platform.deepseek.com/api_keys", first_out)
                self.assertEqual(second_out, "")
                self.assertEqual(first_err, _NO_KEY_LINE + "\n")
                self.assertEqual(second_err, _NO_KEY_LINE + "\n")
                self.assertNotIn("Traceback", first_err + second_err)
                self.assertNotIn("DEEPSEEK_API_KEY is missing", first_err + second_err)
                self.assertTrue((home / "offline-guide").is_file())

    def test_media_without_a_key_exits_zero_and_skips_the_block(self):
        temporary, home = self._home()
        with temporary:
            cache = home / "cache"
            env = {
                API_KEY_ENV: "",
                "EDITTUDE_CONFIG_HOME": str(home),
                "EDITTUDE_CACHE_DIR": str(cache),
            }
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop(API_KEY_ENV, None)
                with patch("edittude_v3.cli.sys.stdin.isatty", return_value=False):
                    out, err, code = self._launch(["media", "inventory", "--help"])
            self.assertEqual(code, 0)
            blob = out + err
            self.assertIn("usage: edittude media", blob)
            self.assertNotIn("No DeepSeek key yet.", blob)
            self.assertNotIn(_NO_KEY_LINE, blob)
            self.assertNotIn("platform.deepseek.com/api_keys", blob)
            self.assertNotIn("edittude doctor", blob)
            self.assertFalse(list(home.rglob("offline-guide")))

    def _launch(self, argv: list[str]) -> tuple[str, str, int | None]:
        out = io.StringIO()
        err = io.StringIO()
        code: int | None = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                main(argv)
            except SystemExit as exc:
                if exc.code is None:
                    code = 0
                elif isinstance(exc.code, int):
                    code = exc.code
                else:
                    code = 1
        return out.getvalue(), err.getvalue(), code
