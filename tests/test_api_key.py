"""First-launch DeepSeek key prompt. Run: python -m unittest tests.test_api_key -v."""
from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from edittude_v3.agent import (
    API_KEY_ENV,
    configured_api_key,
    load_env,
    normalize_api_key,
    save_api_key,
)
from edittude_v3.cli import ensure_api_key
from edittude_v3.paths import env_file


class SaveApiKeyTest(unittest.TestCase):
    def test_creates_env_file_and_sets_permissions(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".env"
            with patch.dict(os.environ, {API_KEY_ENV: ""}, clear=False):
                saved = save_api_key("sk-test-create", path)
                self.assertEqual(os.environ[API_KEY_ENV], "sk-test-create")
            self.assertEqual(saved, path)
            self.assertEqual(path.read_text(encoding="utf-8"), "DEEPSEEK_API_KEY=sk-test-create\n")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_replaces_empty_key_and_keeps_other_lines(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".env"
            path.write_text("# keep\nDEEPSEEK_API_KEY=\nOTHER=1\n", encoding="utf-8")
            with patch.dict(os.environ, {API_KEY_ENV: ""}, clear=False):
                save_api_key("sk-test-replace", path)
            self.assertEqual(
                path.read_text(encoding="utf-8"),
                "# keep\nDEEPSEEK_API_KEY=sk-test-replace\nOTHER=1\n",
            )

    def test_appends_when_file_has_no_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".env"
            path.write_text("OTHER=1", encoding="utf-8")
            with patch.dict(os.environ, {API_KEY_ENV: ""}, clear=False):
                save_api_key("sk-test-append", path)
            self.assertEqual(
                path.read_text(encoding="utf-8"),
                "OTHER=1\nDEEPSEEK_API_KEY=sk-test-append\n",
            )

    def test_normalize_strips_assignment_and_quotes(self):
        self.assertEqual(normalize_api_key('  DEEPSEEK_API_KEY="sk-pasted"  '), "sk-pasted")
        self.assertEqual(normalize_api_key("sk-plain"), "sk-plain")

    def test_empty_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                save_api_key("   ", Path(temporary) / ".env")


class EnsureApiKeyTest(unittest.TestCase):
    def test_skips_prompt_when_key_is_already_set(self):
        with patch.dict(os.environ, {API_KEY_ENV: "sk-already"}):
            with patch("edittude_v3.cli.getpass.getpass") as prompt:
                ensure_api_key()
            prompt.assert_not_called()

    def test_noninteractive_missing_key_exits(self):
        with patch.dict(os.environ, {API_KEY_ENV: ""}, clear=False):
            with patch("edittude_v3.cli.sys.stdin.isatty", return_value=False):
                with self.assertRaises(SystemExit) as raised:
                    ensure_api_key()
        self.assertIn("DEEPSEEK_API_KEY is missing", str(raised.exception))

    def test_first_launch_prompts_and_saves(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".env"
            with patch.dict(os.environ, {API_KEY_ENV: ""}, clear=False):
                with (
                    patch("edittude_v3.cli.sys.stdin.isatty", return_value=True),
                    patch("edittude_v3.cli.getpass.getpass", side_effect=["", "sk-from-prompt"]),
                    patch("edittude_v3.cli.save_api_key", return_value=path) as save,
                    patch("edittude_v3.cli.console.print"),
                ):
                    ensure_api_key()
            save.assert_called_once_with("sk-from-prompt")

    def test_first_launch_writes_config_home_env(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / ".env").write_text("DEEPSEEK_API_KEY=\n", encoding="utf-8")
            with patch.dict(os.environ, {API_KEY_ENV: "", "EDITTUDE_CONFIG_HOME": str(home)}):
                with (
                    patch("edittude_v3.cli.sys.stdin.isatty", return_value=True),
                    patch("edittude_v3.cli.getpass.getpass", return_value="sk-written"),
                    patch("edittude_v3.cli.console.print"),
                ):
                    ensure_api_key()
                    self.assertEqual(os.environ[API_KEY_ENV], "sk-written")
            self.assertEqual((home / ".env").read_text(encoding="utf-8"), "DEEPSEEK_API_KEY=sk-written\n")

    def test_configured_api_key_treats_whitespace_as_missing(self):
        with patch.dict(os.environ, {API_KEY_ENV: "   "}):
            self.assertEqual(configured_api_key(), "")


class ConfigHomeTest(unittest.TestCase):
    def test_env_file_uses_config_home_not_install_root_or_cwd(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            home = temporary / "home"
            root = temporary / "root"
            with patch.dict(os.environ, {"EDITTUDE_CONFIG_HOME": str(home), "EDITTUDE_ROOT": str(root)}):
                self.assertEqual(env_file(), (home / ".env").resolve())

    def test_load_env_reads_config_home_not_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            home = temporary / "home"
            root = temporary / "root"
            work = temporary / "work"
            for path in (home, root, work):
                path.mkdir()
            (home / ".env").write_text(f"{API_KEY_ENV}=sk-home\n", encoding="utf-8")
            (root / ".env").write_text(f"{API_KEY_ENV}=sk-root\n", encoding="utf-8")
            (work / ".env").write_text(f"{API_KEY_ENV}=sk-work\n", encoding="utf-8")
            with patch.dict(os.environ, {"EDITTUDE_CONFIG_HOME": str(home), "EDITTUDE_ROOT": str(root)}):
                os.environ.pop(API_KEY_ENV, None)
                load_env()
                self.assertEqual(os.environ.get(API_KEY_ENV), "sk-home")

    def test_load_env_copies_legacy_config_dir(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            home = temporary / "home"
            root = temporary / "root"
            legacy = home / ".config" / "edittude-v3"
            root.mkdir()
            legacy.mkdir(parents=True)
            (legacy / ".env").write_text(
                f"{API_KEY_ENV}=sk-old\nEDITTUDE_MODEL=deepseek:other\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"EDITTUDE_ROOT": str(root)}, clear=False):
                os.environ.pop("EDITTUDE_CONFIG_HOME", None)
                os.environ.pop(API_KEY_ENV, None)
                with patch("edittude_v3.paths.Path.home", return_value=home):
                    load_env()
                    try:
                        self.assertEqual(os.environ.get(API_KEY_ENV), "sk-old")
                        copied = home / ".config" / "edittude" / ".env"
                        text = copied.read_text(encoding="utf-8")
                        self.assertIn("sk-old", text)
                        self.assertIn("EDITTUDE_MODEL=deepseek:other", text)
                        self.assertEqual(stat.S_IMODE(copied.stat().st_mode), 0o600)
                        self.assertIn("sk-old", (legacy / ".env").read_text(encoding="utf-8"))
                    finally:
                        os.environ.pop(API_KEY_ENV, None)

    def test_empty_new_config_is_replaced_by_legacy(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            home = temporary / "home"
            root = temporary / "root"
            root.mkdir()
            new = home / ".config" / "edittude"
            old = home / ".config" / "edittude-v3"
            new.mkdir(parents=True)
            old.mkdir(parents=True)
            (new / ".env").write_text("DEEPSEEK_API_KEY=\n", encoding="utf-8")
            (old / ".env").write_text(f"{API_KEY_ENV}=sk-from-old\n", encoding="utf-8")
            with patch.dict(os.environ, {"EDITTUDE_ROOT": str(root)}, clear=False):
                os.environ.pop("EDITTUDE_CONFIG_HOME", None)
                os.environ.pop(API_KEY_ENV, None)
                with patch("edittude_v3.paths.Path.home", return_value=home):
                    load_env()
                    try:
                        self.assertEqual(os.environ.get(API_KEY_ENV), "sk-from-old")
                        self.assertEqual(
                            (new / ".env").read_text(encoding="utf-8"),
                            f"{API_KEY_ENV}=sk-from-old\n",
                        )
                    finally:
                        os.environ.pop(API_KEY_ENV, None)

    def test_existing_config_wins_and_keeps_a_missing_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            home = temporary / "home"
            root = temporary / "root"
            root.mkdir()
            new = home / ".config" / "edittude"
            old = home / ".config" / "edittude-v3"
            new.mkdir(parents=True)
            old.mkdir(parents=True)
            (new / ".env").write_text("EDITTUDE_MODEL=deepseek:custom\n", encoding="utf-8")
            (old / ".env").write_text(
                f"{API_KEY_ENV}=sk-old\nEDITTUDE_MODEL=deepseek:legacy\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"EDITTUDE_ROOT": str(root)}, clear=False):
                os.environ.pop("EDITTUDE_CONFIG_HOME", None)
                os.environ.pop(API_KEY_ENV, None)
                os.environ.pop("EDITTUDE_MODEL", None)
                with patch("edittude_v3.paths.Path.home", return_value=home):
                    load_env()
                    try:
                        self.assertEqual(os.environ.get(API_KEY_ENV), "sk-old")
                        text = (new / ".env").read_text(encoding="utf-8")
                        self.assertIn("deepseek:custom", text)
                        self.assertIn("sk-old", text)
                        self.assertNotIn("deepseek:legacy", text)
                    finally:
                        os.environ.pop(API_KEY_ENV, None)
                        os.environ.pop("EDITTUDE_MODEL", None)

    def test_config_home_override_ignores_legacy_config_dir(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            home = temporary / "home"
            override = temporary / "override"
            root = temporary / "root"
            for path in (override, root):
                path.mkdir()
            legacy = home / ".config" / "edittude-v3"
            legacy.mkdir(parents=True)
            (legacy / ".env").write_text(f"{API_KEY_ENV}=sk-legacy\n", encoding="utf-8")
            (override / ".env").write_text("OTHER=1\n", encoding="utf-8")
            with patch.dict(
                os.environ,
                {"EDITTUDE_CONFIG_HOME": str(override), "EDITTUDE_ROOT": str(root)},
            ):
                os.environ.pop(API_KEY_ENV, None)
                with patch("edittude_v3.paths.Path.home", return_value=home):
                    load_env()
                    self.assertNotEqual(os.environ.get(API_KEY_ENV), "sk-legacy")
                    self.assertFalse((home / ".config" / "edittude" / ".env").exists())

    def test_load_env_adopts_legacy_install_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            home = temporary / "home"
            root = temporary / "root"
            home.mkdir()
            root.mkdir()
            (root / ".env").write_text(f"{API_KEY_ENV}=sk-legacy\n", encoding="utf-8")
            with patch.dict(os.environ, {"EDITTUDE_CONFIG_HOME": str(home), "EDITTUDE_ROOT": str(root)}):
                os.environ.pop(API_KEY_ENV, None)
                load_env()
                self.assertEqual(os.environ.get(API_KEY_ENV), "sk-legacy")
                self.assertEqual((home / ".env").read_text(encoding="utf-8"), f"{API_KEY_ENV}=sk-legacy\n")


if __name__ == "__main__":
    unittest.main()
