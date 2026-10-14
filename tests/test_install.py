"""Installer checks. Run: python -m unittest tests.test_install -v."""
from __future__ import annotations

import contextlib
import io
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from edittude_v3 import __version__
from edittude_v3.cli import _parser, main

ROOT = Path(__file__).resolve().parents[1]
MINIMAL_PYPROJECT = """[project]
name = "edittude-v3"
version = "0.0.0"
requires-python = ">=3.13"
dependencies = []
"""


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_TEMPLATE_DIR"] = ""
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def _git(cwd: Path, *args: str) -> None:
    subprocess.check_call(["git", "-C", str(cwd), *args], env=_git_env())


def _git_output(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(cwd), *args], env=_git_env(), text=True)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.check_call(
        ["git", "-c", "init.templateDir=", "init", "-b", "main", str(path)],
        env=_git_env(),
    )
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")


def _write_checkout(path: Path, marker: str) -> None:
    shutil.copy(ROOT / "install.sh", path / "install.sh")
    (path / "pyproject.toml").write_text(MINIMAL_PYPROJECT, encoding="utf-8")
    (path / "marker.txt").write_text(marker, encoding="utf-8")


def _commit(path: Path, message: str) -> None:
    _git(path, "add", "-A")
    _git(path, "commit", "-m", message)


class InstallScriptTest(unittest.TestCase):
    def test_install_sh_is_valid_bash(self):
        subprocess.check_call(["bash", "-n", str(ROOT / "install.sh")])

    def test_local_install_writes_working_launcher(self):
        with tempfile.TemporaryDirectory() as temporary:
            bindir = Path(temporary) / "bin"
            env = os.environ.copy()
            env["HOME"] = str(Path(temporary) / "userhome")
            Path(env["HOME"]).mkdir()
            env["EDITTUDE_BIN"] = str(bindir)
            config_home = Path(temporary) / "home"
            env["EDITTUDE_CONFIG_HOME"] = str(config_home)
            done = subprocess.run(
                ["bash", str(ROOT / "install.sh")],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            notice = (
                "Edittude's own code is MIT. See `LICENSE` and `THIRD_PARTY_LICENSES` "
                f"in {ROOT}."
            )
            self.assertRegex(done.stdout, rf"(?m)^{re.escape(notice)}$")
            self.assertLess(
                done.stdout.index(
                    "First launch asks for a DeepSeek key (https://platform.deepseek.com)."
                ),
                done.stdout.index(notice),
            )
            self.assertTrue((ROOT / "LICENSE").is_file())
            self.assertTrue((ROOT / "THIRD_PARTY_LICENSES").is_file())
            self.assertIn("DEEPSEEK_API_KEY", (config_home / ".env").read_text(encoding="utf-8"))
            launcher = bindir / "edittude"
            alias = bindir / "edittude-v3"
            self.assertTrue(os.access(launcher, os.X_OK))
            self.assertTrue(os.access(alias, os.X_OK))
            text = launcher.read_text(encoding="utf-8")
            self.assertIn(f'EDITTUDE_ROOT="{ROOT}"', text)
            version = subprocess.check_output([str(launcher), "--version"], text=True).strip()
            alias_version = subprocess.check_output([str(alias), "--version"], text=True).strip()
            self.assertEqual(version, alias_version)
            self.assertTrue(version.startswith("edittude "))
            self.assertNotIn("edittude-v3", version)
            skills = subprocess.check_output(
                [str(launcher), "skills", "-C", temporary],
                text=True,
            )
            self.assertIn("zero-shot-cut", skills)

    def test_update_pulls_new_commit_from_current_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            origin = temporary / "origin"
            home = temporary / "home"
            bindir = temporary / "bin"
            _init_repo(origin)
            _write_checkout(origin, "one")
            _commit(origin, "one")
            subprocess.check_call(["git", "clone", str(origin), str(home)], env=_git_env())
            _write_checkout(origin, "two")
            _commit(origin, "two")

            env = _git_env()
            env["HOME"] = str(temporary / "userhome")
            Path(env["HOME"]).mkdir()
            env["EDITTUDE_BIN"] = str(bindir)
            env["EDITTUDE_CONFIG_HOME"] = str(temporary / "config")
            env["EDITTUDE_SKIP_SYNC"] = "1"
            updated = subprocess.run(
                ["bash", str(home / "install.sh"), "update"],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertNotIn("Edittude's own code is MIT.", updated.stdout)
            self.assertNotIn("Installed.", updated.stdout)
            self.assertNotIn("Installed.", updated.stderr)

            self.assertEqual((home / "marker.txt").read_text(encoding="utf-8"), "two")
            self.assertIn("two", _git_output(home, "log", "-1", "--oneline"))
            launcher = (bindir / "edittude-v3").read_text(encoding="utf-8")
            root_line = next(line for line in launcher.splitlines() if "EDITTUDE_ROOT=" in line)
            self.assertRegex(root_line, r'^export EDITTUDE_ROOT="[^"]+"$')
            quoted = root_line.split("=", 1)[1].strip('"')
            self.assertEqual(Path(quoted).resolve(), home.resolve())

    def test_update_refuses_dirty_checkout_without_force(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            origin = temporary / "origin"
            home = temporary / "home"
            _init_repo(origin)
            _write_checkout(origin, "one")
            _commit(origin, "one")
            subprocess.check_call(["git", "clone", str(origin), str(home)], env=_git_env())
            (home / "marker.txt").write_text("dirty", encoding="utf-8")

            env = _git_env()
            env["HOME"] = str(temporary / "userhome")
            Path(env["HOME"]).mkdir()
            env["EDITTUDE_BIN"] = str(temporary / "bin")
            env["EDITTUDE_CONFIG_HOME"] = str(temporary / "config")
            env["EDITTUDE_SKIP_SYNC"] = "1"
            failed = subprocess.run(
                ["bash", str(home / "install.sh"), "update"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("local changes", failed.stderr)
            self.assertEqual((home / "marker.txt").read_text(encoding="utf-8"), "dirty")

            subprocess.check_call(
                ["bash", str(home / "install.sh"), "update", "--force"],
                env=env,
            )
            self.assertEqual((home / "marker.txt").read_text(encoding="utf-8"), "one")

    def _launcher_env(self, temporary: Path, bindir: Path) -> dict[str, str]:
        env = _git_env()
        home = temporary / "userhome"
        home.mkdir(exist_ok=True)
        env["HOME"] = str(home)
        env["EDITTUDE_BIN"] = str(bindir)
        env["EDITTUDE_CONFIG_HOME"] = str(temporary / "config")
        env["EDITTUDE_SKIP_SYNC"] = "1"
        return env

    def test_install_refuses_foreign_file_at_launcher_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            bindir = temporary / "bin"
            bindir.mkdir()
            (bindir / "edittude").write_text("unrelated tool", encoding="utf-8")
            failed = subprocess.run(
                ["bash", str(ROOT / "install.sh")],
                env=self._launcher_env(temporary, bindir),
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("not written by this installer", failed.stderr)
            self.assertEqual((bindir / "edittude").read_text(encoding="utf-8"), "unrelated tool")

    def test_install_does_not_write_through_a_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            bindir = temporary / "bin"
            bindir.mkdir()
            precious = temporary / "precious.txt"
            precious.write_text("precious", encoding="utf-8")
            (bindir / "edittude").symlink_to(precious)
            failed = subprocess.run(
                ["bash", str(ROOT / "install.sh")],
                env=self._launcher_env(temporary, bindir),
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual(precious.read_text(encoding="utf-8"), "precious")

    def test_install_replaces_its_own_launchers(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            bindir = temporary / "bin"
            env = self._launcher_env(temporary, bindir)
            for _ in range(2):
                subprocess.check_call(["bash", str(ROOT / "install.sh")], env=env)
            for name in ("edittude", "edittude-v3", "edittude-media"):
                self.assertIn(
                    "generated by edittude/install.sh",
                    (bindir / name).read_text(encoding="utf-8"),
                )

    def test_plain_rerun_refuses_dirty_managed_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            origin = temporary / "origin"
            home = temporary / "home"
            runner = temporary / "runner"
            _init_repo(origin)
            _write_checkout(origin, "one")
            _commit(origin, "one")
            subprocess.check_call(["git", "clone", str(origin), str(home)], env=_git_env())
            (home / "marker.txt").write_text("dirty", encoding="utf-8")
            # Not a checkout, so the installer manages EDITTUDE_HOME: the curl | bash path.
            runner.mkdir()
            shutil.copy(ROOT / "install.sh", runner / "install.sh")

            env = self._launcher_env(temporary, temporary / "bin")
            env["EDITTUDE_HOME"] = str(home)
            failed = subprocess.run(
                ["bash", str(runner / "install.sh")], env=env, capture_output=True, text=True
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("local changes", failed.stderr)
            self.assertEqual((home / "marker.txt").read_text(encoding="utf-8"), "dirty")

            subprocess.check_call(["bash", str(runner / "install.sh"), "--force"], env=env)
            self.assertEqual((home / "marker.txt").read_text(encoding="utf-8"), "one")

    def test_uv_installer_chatter_does_not_become_the_uv_path(self):
        # install_uv's stdout is the uv path. The upstream uv installer prints its
        # progress on stdout, so it has to be redirected or it is what we try to exec.
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            home = temporary / "home"
            stubs = temporary / "stubs"
            for directory in (home, stubs):
                directory.mkdir(parents=True)
            # Stands in for `curl -LsSf https://astral.sh/uv/install.sh`.
            (stubs / "curl").write_text(
                "#!/bin/sh\n"
                "cat <<'INSTALLER'\n"
                'echo "downloading uv 0.12.17 aarch64-apple-darwin"\n'
                'echo "installing to $HOME/.local/bin"\n'
                'mkdir -p "$HOME/.local/bin"\n'
                'printf \'#!/bin/sh\\necho "$@" >>"$HOME/uv-args"\\n\' >"$HOME/.local/bin/uv"\n'
                'chmod +x "$HOME/.local/bin/uv"\n'
                "echo \"everything's installed!\"\n"
                "INSTALLER\n",
                encoding="utf-8",
            )
            (stubs / "curl").chmod(0o755)

            env = os.environ.copy()
            env["HOME"] = str(home)
            env["PATH"] = f"{stubs}:/usr/bin:/bin"
            env["EDITTUDE_BIN"] = str(temporary / "bin")
            env["EDITTUDE_CONFIG_HOME"] = str(temporary / "config")
            env.pop("EDITTUDE_SKIP_SYNC", None)
            done = subprocess.run(
                ["bash", str(ROOT / "install.sh")], env=env, capture_output=True, text=True
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            # The path install_uv handed back was executable, and it was the uv we installed.
            self.assertIn("sync", (home / "uv-args").read_text(encoding="utf-8"))

    def test_install_replaces_legacy_marker_launchers(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            bindir = temporary / "bin"
            bindir.mkdir()
            legacy = bindir / "edittude"
            legacy.write_text(
                "#!/bin/sh\n# generated by edittude-v3/install.sh\nexit 0\n",
                encoding="utf-8",
            )
            legacy.chmod(0o755)
            subprocess.check_call(["bash", str(ROOT / "install.sh")], env=self._launcher_env(temporary, bindir))
            text = legacy.read_text(encoding="utf-8")
            self.assertIn("generated by edittude/install.sh", text)
            self.assertIn('edittude "$@"', text)

    def test_install_copies_legacy_config_and_leaves_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            home = temporary / "home"
            legacy = home / ".config" / "edittude-v3"
            legacy.mkdir(parents=True)
            (legacy / ".env").write_text("DEEPSEEK_API_KEY=sk-legacy\n", encoding="utf-8")
            env = os.environ.copy()
            env["HOME"] = str(home)
            env["EDITTUDE_BIN"] = str(temporary / "bin")
            env["EDITTUDE_SKIP_SYNC"] = "1"
            env.pop("EDITTUDE_CONFIG_HOME", None)
            subprocess.check_call(["bash", str(ROOT / "install.sh")], env=env)
            copied = home / ".config" / "edittude" / ".env"
            self.assertEqual(copied.read_text(encoding="utf-8"), "DEEPSEEK_API_KEY=sk-legacy\n")
            self.assertEqual((legacy / ".env").read_text(encoding="utf-8"), "DEEPSEEK_API_KEY=sk-legacy\n")

    def test_default_prefix_keeps_legacy_share_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            home = temporary / "home"
            origin = temporary / "origin"
            legacy = home / ".local" / "share" / "edittude-v3"
            runner = temporary / "runner"
            _init_repo(origin)
            _write_checkout(origin, "legacy-install")
            _commit(origin, "legacy")
            subprocess.check_call(["git", "clone", str(origin), str(legacy)], env=_git_env())
            runner.mkdir()
            shutil.copy(ROOT / "install.sh", runner / "install.sh")

            env = self._launcher_env(temporary, temporary / "bin")
            env["HOME"] = str(home)
            env.pop("EDITTUDE_HOME", None)
            subprocess.check_call(["bash", str(runner / "install.sh")], env=env)
            launcher = (temporary / "bin" / "edittude").read_text(encoding="utf-8")
            self.assertIn(f'export EDITTUDE_ROOT="{legacy}"', launcher)
            self.assertFalse((home / ".local" / "share" / "edittude").exists())

    def test_fresh_install_clones_into_edittude_share(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            home = temporary / "home"
            origin = temporary / "origin"
            runner = temporary / "runner"
            _init_repo(origin)
            _write_checkout(origin, "fresh")
            _commit(origin, "fresh")
            runner.mkdir()
            shutil.copy(ROOT / "install.sh", runner / "install.sh")

            env = self._launcher_env(temporary, temporary / "bin")
            env["HOME"] = str(home)
            env["EDITTUDE_REPO"] = str(origin)
            env.pop("EDITTUDE_HOME", None)
            subprocess.check_call(["bash", str(runner / "install.sh")], env=env)
            installed = home / ".local" / "share" / "edittude"
            self.assertEqual((installed / "marker.txt").read_text(encoding="utf-8"), "fresh")
            launcher = (temporary / "bin" / "edittude").read_text(encoding="utf-8")
            self.assertIn(f'export EDITTUDE_ROOT="{installed}"', launcher)

    def test_help_names_edittude(self):
        parser = _parser()
        self.assertEqual(parser.prog, "edittude")
        buf = io.StringIO()
        parser.print_help(file=buf)
        text = buf.getvalue()
        self.assertIn("usage: edittude", text)
        self.assertIn('edittude ask "cut /path/to/footage"', text)
        self.assertNotIn("edittude-v3", text)
        version = io.StringIO()
        with contextlib.redirect_stdout(version):
            with self.assertRaises(SystemExit) as raised:
                parser.parse_args(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(version.getvalue().strip(), f"edittude {__version__}")

    def test_media_help_reaches_the_footage_tools(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as raised:
                main(["media", "--help"])
        self.assertIn(raised.exception.code, (0, None))
        text = buf.getvalue()
        self.assertIn("usage: edittude media", text)
        self.assertIn("inventory", text)
        detail = io.StringIO()
        with contextlib.redirect_stdout(detail):
            with self.assertRaises(SystemExit):
                main(["media", "inventory", "-h"])
        self.assertIn("--out", detail.getvalue())

    @patch.dict(os.environ, {"EDITTUDE_ROOT": ""})
    def test_update_command_runs_installer(self):
        self.assertEqual(_parser().parse_args(["update"]).command, "update")
        self.assertTrue(_parser().parse_args(["update", "--force"]).force)
        with patch("edittude_v3.cli.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            main(["update"])
            args, kwargs = run.call_args
            self.assertEqual(args[0][:2], ["bash", str(ROOT / "install.sh")])
            self.assertIn("update", args[0])
            self.assertEqual(kwargs["env"]["EDITTUDE_UPDATE"], "1")

            run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            main(["update", "--force"])
            self.assertEqual(run.call_args.kwargs["env"]["EDITTUDE_FORCE"], "1")


def _path_line(bindir: Path) -> str:
    return f'export PATH="{bindir}:$PATH"  # added by edittude/install.sh'


def _path_notice(name: str) -> str:
    return (
        f"Added edittude to PATH in {name} "
        '(remove the line marked "added by edittude/install.sh" to undo).'
    )


def _ssh_line(bindir: Path) -> str:
    return (
        "Login shells (SSH) need the same export line in ~/.profile: "
        f'export PATH="{bindir}:$PATH"  # added by edittude/install.sh'
    )


_OLD_HINT = "Add this to your shell profile, then open a new terminal:"
_ALREADY_SET_UP = "edittude is already set up on PATH."

# Ubuntu's bashrc returns before any later lines when the shell is not interactive,
# so a login shell only sees an export that was written to .profile (or .bash_profile).
_BASHRC_RETURNS_UNLESS_INTERACTIVE = """# keep
case $- in
    *i*) ;;
      *) return;;
esac
"""

_PROFILE_SOURCES_BASHRC = """# keep
if [ -n "$BASH_VERSION" ]; then
    if [ -f "$HOME/.bashrc" ]; then
        . "$HOME/.bashrc"
    fi
fi
"""


class PathRcTest(unittest.TestCase):
    """BIN_DIR is recorded only in rc files that already exist, and only once."""

    def _install(self, home: Path, bindir: Path, *, path: str | None = None) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["EDITTUDE_BIN"] = str(bindir)
        env["EDITTUDE_CONFIG_HOME"] = str(home / "config")
        env["EDITTUDE_SKIP_SYNC"] = "1"
        env["PATH"] = path if path is not None else os.environ.get("PATH", "/usr/bin:/bin")
        return subprocess.run(
            ["bash", str(ROOT / "install.sh")],
            env=env,
            capture_output=True,
            text=True,
        )

    def _mit(self) -> str:
        return (
            "Edittude's own code is MIT. See `LICENSE` and `THIRD_PARTY_LICENSES` "
            f"in {ROOT}."
        )

    def _assert_mit_is_last(self, done: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip().splitlines()[-1], self._mit())

    def _assert_no_old_hint(self, done: subprocess.CompletedProcess[str]) -> None:
        self.assertNotIn(_OLD_HINT, done.stdout)

    def _assert_shell_resolves(self, home: Path, bindir: Path, flag: str) -> None:
        done = subprocess.run(
            ["bash", flag, "command -v edittude"],
            env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
        self.assertEqual(done.returncode, 0, f"{flag}\n{done.stdout}\n{done.stderr}")
        self.assertIn(str(bindir / "edittude"), done.stdout)

    def test_every_existing_rc_file_gets_one_line_and_no_old_hint(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            home = temporary / "home"
            bindir = temporary / "bin"
            home.mkdir()
            names = (".bashrc", ".bash_profile", ".profile", ".zshrc")
            for name in names:
                (home / name).write_text("# keep\n", encoding="utf-8")
            done = self._install(home, bindir)
            line = _path_line(bindir)
            self._assert_mit_is_last(done)
            self._assert_no_old_hint(done)
            self.assertNotIn(_ALREADY_SET_UP, done.stdout)
            self.assertNotIn("Login shells (SSH)", done.stdout)
            for name in names:
                text = (home / name).read_text(encoding="utf-8")
                self.assertEqual(text.count(line), 1)
                self.assertIn("# keep\n", text)
                self.assertIn(_path_notice(f"~/{name}"), done.stdout)
            self.assertEqual(done.stdout.count("Added edittude to PATH in "), 4)
            self.assertLess(done.stdout.index("Added edittude to PATH in "), done.stdout.index(self._mit()))

    def test_bashrc_and_profile_resolve_for_login_and_interactive(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            home = temporary / "home"
            bindir = temporary / "bin"
            home.mkdir()
            (home / ".bashrc").write_text(_BASHRC_RETURNS_UNLESS_INTERACTIVE, encoding="utf-8")
            (home / ".profile").write_text(_PROFILE_SOURCES_BASHRC, encoding="utf-8")
            done = self._install(home, bindir)
            line = _path_line(bindir)
            self._assert_mit_is_last(done)
            self._assert_no_old_hint(done)
            self.assertNotIn(_ALREADY_SET_UP, done.stdout)
            self.assertNotIn("Login shells (SSH)", done.stdout)
            for name in (".bashrc", ".profile"):
                text = (home / name).read_text(encoding="utf-8")
                self.assertEqual(text.count(line), 1)
                self.assertIn(_path_notice(f"~/{name}"), done.stdout)
            self.assertFalse((home / ".bash_profile").exists())
            self.assertFalse((home / ".zshrc").exists())
            self._assert_shell_resolves(home, bindir, "-ic")
            self._assert_shell_resolves(home, bindir, "-lc")

    def test_only_bashrc_prints_the_ssh_line(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            home = temporary / "home"
            bindir = temporary / "bin"
            home.mkdir()
            (home / ".bashrc").write_text("# keep\n", encoding="utf-8")
            done = self._install(home, bindir)
            line = _path_line(bindir)
            self._assert_mit_is_last(done)
            self._assert_no_old_hint(done)
            self.assertNotIn(_ALREADY_SET_UP, done.stdout)
            text = (home / ".bashrc").read_text(encoding="utf-8")
            self.assertEqual(text.count(line), 1)
            self.assertIn(_path_notice("~/.bashrc"), done.stdout)
            self.assertIn(_ssh_line(bindir), done.stdout)
            self.assertLess(done.stdout.index("Login shells (SSH)"), done.stdout.index(self._mit()))
            for name in (".bash_profile", ".profile", ".zshrc"):
                self.assertFalse((home / name).exists())

    def test_bash_profile_is_edited_and_login_shell_resolves(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            home = temporary / "home"
            bindir = temporary / "bin"
            home.mkdir()
            (home / ".bash_profile").write_text("# keep\n", encoding="utf-8")
            done = self._install(home, bindir)
            line = _path_line(bindir)
            self._assert_mit_is_last(done)
            self._assert_no_old_hint(done)
            self.assertNotIn(_ALREADY_SET_UP, done.stdout)
            self.assertNotIn("Login shells (SSH)", done.stdout)
            text = (home / ".bash_profile").read_text(encoding="utf-8")
            self.assertEqual(text.count(line), 1)
            self.assertIn("# keep\n", text)
            self.assertIn(_path_notice("~/.bash_profile"), done.stdout)
            for name in (".bashrc", ".profile", ".zshrc"):
                self.assertFalse((home / name).exists())
            self._assert_shell_resolves(home, bindir, "-lc")

    def test_rerun_does_not_duplicate_the_line_or_the_notice(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            home = temporary / "home"
            bindir = temporary / "bin"
            home.mkdir()
            (home / ".bashrc").write_text("# keep\n", encoding="utf-8")
            first = self._install(home, bindir)
            second = self._install(home, bindir)
            line = _path_line(bindir)
            text = (home / ".bashrc").read_text(encoding="utf-8")
            self._assert_mit_is_last(first)
            self._assert_mit_is_last(second)
            self.assertEqual(text.count(line), 1)
            self.assertIn(_path_notice("~/.bashrc"), first.stdout)
            self.assertIn(_ssh_line(bindir), first.stdout)
            self._assert_no_old_hint(first)
            self.assertNotIn("Added edittude to PATH in ", second.stdout)
            self.assertNotIn("Login shells (SSH)", second.stdout)
            self.assertNotIn(_OLD_HINT, second.stdout)
            self.assertNotIn(_ALREADY_SET_UP, first.stdout)
            self.assertIn(_ALREADY_SET_UP, second.stdout)
            self.assertLess(second.stdout.index(_ALREADY_SET_UP), second.stdout.index(self._mit()))

    def test_already_on_path_leaves_the_rc_file_alone(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            home = temporary / "home"
            bindir = temporary / "bin"
            home.mkdir()
            bindir.mkdir()
            original = "# keep\n"
            (home / ".bashrc").write_text(original, encoding="utf-8")
            done = self._install(home, bindir, path=f"{bindir}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}")
            self._assert_mit_is_last(done)
            self.assertEqual((home / ".bashrc").read_text(encoding="utf-8"), original)
            self.assertNotIn("Added edittude to PATH in ", done.stdout)
            self._assert_no_old_hint(done)
            self.assertNotIn("Login shells (SSH)", done.stdout)
            self.assertIn(_ALREADY_SET_UP, done.stdout)
            self.assertLess(done.stdout.index(_ALREADY_SET_UP), done.stdout.index(self._mit()))
            for name in (".bash_profile", ".zshrc", ".profile"):
                self.assertFalse((home / name).exists())

    def test_missing_rc_files_are_not_created(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            home = temporary / "home"
            bindir = temporary / "bin"
            home.mkdir()
            done = self._install(home, bindir)
            self._assert_mit_is_last(done)
            for name in (".bashrc", ".bash_profile", ".zshrc", ".profile"):
                self.assertFalse((home / name).exists())
            self.assertNotIn("Added edittude to PATH in ", done.stdout)
            self.assertNotIn("Login shells (SSH)", done.stdout)
            self.assertNotIn(_ALREADY_SET_UP, done.stdout)
            self.assertIn(_OLD_HINT, done.stdout)
            self.assertIn(f'  export PATH="{bindir}:$PATH"', done.stdout)

    def test_custom_edittude_bin_is_what_gets_written(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            home = temporary / "home"
            bindir = temporary / "custom" / "edittude-bin"
            home.mkdir()
            (home / ".bashrc").write_text("# keep\n", encoding="utf-8")
            done = self._install(home, bindir)
            line = _path_line(bindir)
            self._assert_mit_is_last(done)
            self._assert_no_old_hint(done)
            self.assertNotIn(_ALREADY_SET_UP, done.stdout)
            self.assertEqual((home / ".bashrc").read_text(encoding="utf-8").count(line), 1)
            self.assertIn(_path_notice("~/.bashrc"), done.stdout)
            self.assertIn(_ssh_line(bindir), done.stdout)
            self.assertNotIn(str(home / ".local" / "bin"), (home / ".bashrc").read_text(encoding="utf-8"))
            self.assertNotIn(str(home / ".local" / "bin"), done.stdout)


if __name__ == "__main__":
    unittest.main()
