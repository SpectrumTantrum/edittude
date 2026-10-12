"""Run with python -m unittest discover -s tests -p test_model_paths.py."""
from __future__ import annotations

from contextlib import redirect_stdout
from fnmatch import fnmatch
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import install_models, models
from tools.common import model_python, models_root

# Every EDITTUDE_* knob these paths read, emptied so only EDITTUDE_ROOT decides.
UNSET = {key: "" for key in (
    "EDITTUDE_MODELS_DIR", "EDITTUDE_MODEL_PYTHON", "EDITTUDE_ASR_PYTHON", "EDITTUDE_DEMUCS_PYTHON",
    "EDITTUDE_ASR_MODEL_DIR", "EDITTUDE_DEMUCS_REPO", "EDITTUDE_SEED_VC_DIR",
    "EDITTUDE_SEED_VC_CHECKPOINT", "EDITTUDE_SEED_VC_CONFIG", "EDITTUDE_DIFFSINGER_DIR",
    "EDITTUDE_DIFFSINGER_EXP",
)}


class ModelPathDefaultsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        for relative in ("models/asr/faster-whisper-base", "models/demucs", "models/DiffSinger",
                         "models/seed-vc/ckpt", ".venv-models/bin"):
            (self.root / relative).mkdir(parents=True)
        for name in ("EDITTUDE_SEED_VC_CHECKPOINT", "EDITTUDE_SEED_VC_CONFIG"):
            (self.root / "models" / models.DEFAULTS[name]).write_bytes(b"")
        python = self.root / ".venv-models/bin/python"
        python.write_text("#!/bin/sh\n")
        python.chmod(0o755)
        self.environment = patch.dict(os.environ, {**UNSET, "EDITTUDE_ROOT": str(self.root)})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_all_four_backends_default_inside_the_install_root(self):
        expected = {
            "EDITTUDE_ASR_MODEL_DIR": "asr/faster-whisper-base",
            "EDITTUDE_DEMUCS_REPO": "demucs",
            "EDITTUDE_SEED_VC_DIR": "seed-vc",
            "EDITTUDE_DIFFSINGER_DIR": "DiffSinger",
        }
        self.assertEqual(models_root(), self.root / "models")
        for name, relative in expected.items():
            with self.subTest(variable=name):
                self.assertEqual(models._configured_path(name), self.root / "models" / relative)
        for name in ("EDITTUDE_SEED_VC_CHECKPOINT", "EDITTUDE_SEED_VC_CONFIG"):
            with self.subTest(variable=name):
                self.assertEqual(models._configured_path(name, directory=False),
                                 self.root / "models" / models.DEFAULTS[name])

    def test_the_diffsinger_experiment_defaults_to_a_checkpoint_the_installer_fetches(self):
        entry = install_models.BACKENDS["diffsinger"]["hf"][0]
        self.assertEqual(models.DEFAULTS["EDITTUDE_DIFFSINGER_DIR"] + "/checkpoints", entry["into"])
        self.assertIn(models.DIFFSINGER_EXP + "/*", entry["files"])

    def test_the_seed_vc_checkpoint_defaults_match_the_installed_filenames(self):
        entry = install_models.BACKENDS["seed-vc"]["hf"][0]
        for name in ("EDITTUDE_SEED_VC_CHECKPOINT", "EDITTUDE_SEED_VC_CONFIG"):
            relative = Path(models.DEFAULTS[name])
            self.assertEqual(relative.parent.as_posix(), entry["into"])
            self.assertTrue(any(fnmatch(relative.name, pattern) for pattern in entry["files"]), relative)

    def test_installed_model_python_is_preferred_over_the_harness_interpreter(self):
        self.assertEqual(model_python(), self.root / ".venv-models/bin/python")
        self.assertEqual(models._runtime("ASR"), str(self.root / ".venv-models/bin/python"))

    def test_environment_variables_still_override_the_defaults(self):
        elsewhere = self.root / "elsewhere"
        (elsewhere / "repo").mkdir(parents=True)
        with patch.dict(os.environ, {"EDITTUDE_DEMUCS_REPO": str(elsewhere / "repo")}):
            self.assertEqual(models._configured_path("EDITTUDE_DEMUCS_REPO"), elsewhere / "repo")
        with patch.dict(os.environ, {"EDITTUDE_MODELS_DIR": str(elsewhere)}):
            self.assertEqual(models_root(), elsewhere)
        with patch.dict(os.environ, {"EDITTUDE_MODEL_PYTHON": "python3"}):
            self.assertNotEqual(models._runtime("DEMUCS"), str(model_python()))

    def test_missing_default_names_the_install_command(self):
        (self.root / "models/demucs").rmdir()
        with self.assertRaisesRegex(models.CapabilityUnavailable, "models install"):
            models._configured_path("EDITTUDE_DEMUCS_REPO")


class InstallerSchemaTest(unittest.TestCase):
    """BACKENDS is data install() unpacks; drift here is what broke `models install --models asr`."""

    def test_every_hf_entry_carries_exactly_the_keys_install_consumes(self):
        for name, backend in install_models.BACKENDS.items():
            for entry in backend["hf"]:
                with self.subTest(backend=name, repo=entry.get("repo")):
                    self.assertIsInstance(entry, dict)
                    self.assertLessEqual({"repo", "rev", "into"}, entry.keys())
                    self.assertLessEqual(entry.keys(), {"repo", "rev", "into", "files", "cache"})
                    self.assertRegex(entry["rev"], r"^[0-9a-f]{40}$")

    def test_asr_downloads_the_pinned_revision_into_the_directory_models_py_reads(self):
        entry = install_models.BACKENDS["asr"]["hf"][0]
        destination = Path("/nowhere/models") / entry["into"]
        # No V2_MODELS to adopt from and nothing on disk, so this takes the download branch.
        with patch.object(install_models, "_run") as run, \
                patch.object(install_models, "V2_MODELS", Path("/nonexistent")):
            install_models._snapshot(entry, destination)
        payload = json.loads(run.call_args[0][0][-1])
        self.assertEqual(payload["revision"], entry["rev"])
        self.assertEqual(payload["local_dir"], str(destination))
        self.assertEqual(entry["into"], models.DEFAULTS["EDITTUDE_ASR_MODEL_DIR"])

    def test_v2_reuse_skips_a_same_revision_directory_holding_different_files(self):
        """Plachta/Seed-VC ships both checkpoints at one revision; only the f0 one will do."""
        entry = next(item for item in install_models.BACKENDS["seed-vc"]["hf"]
                     if item["repo"] == "Plachta/Seed-VC")
        v2 = Path(tempfile.mkdtemp()) / "v2-models"
        for name, files in (("seed-vc", ["DiT_seed_v2_uvit_whisper_small_wavenet.pth"]),
                            ("seed-vc-f0", [pattern.replace("*", "x") for pattern in entry["files"]])):
            (v2 / name).mkdir(parents=True)
            (v2 / name / ".edittude-model.json").write_text(
                json.dumps({"revision": entry["rev"], "files": files}), encoding="utf-8")
            for file in files:
                (v2 / name / file).write_bytes(b"")
        with patch.object(install_models, "V2_MODELS", v2):
            source, names = install_models._installed_v2(entry)
        self.assertEqual(source.name, "seed-vc-f0")
        self.assertEqual(len(names), len(entry["files"]))


class InstallFailureTest(unittest.TestCase):
    """Missing tools and missing patches exit with a message, not a traceback."""

    def test_missing_executable_exits_cleanly(self):
        with self.assertRaises(SystemExit) as raised:
            install_models._run(["definitely-not-a-command-xyz"])
        self.assertIn("definitely-not-a-command-xyz is missing", str(raised.exception))

    def test_failing_command_exits_cleanly(self):
        with self.assertRaises(SystemExit) as raised:
            install_models._run(["sh", "-c", "exit 3"])
        self.assertIn("exit code 3", str(raised.exception))

    def test_clone_checks_the_patch_before_cloning(self):
        spec = {"url": "https://example.invalid/repo", "into": "no-such-backend", "sha": "0" * 40}
        with patch.object(install_models, "_run") as run, \
                self.assertRaises(SystemExit) as raised:
            install_models._clone(spec, Path("/nowhere/clone"))
        self.assertIn("no-such-backend.patch", str(raised.exception))
        run.assert_not_called()


class SeedVcFetchNoticeTest(unittest.TestCase):
    """The GPL line is one print, immediately before a real Seed-VC fetch, and nowhere else."""

    NOTICE = ("Downloading Seed-VC (GPL-3.0, separate from Edittude's MIT code). "
              "See THIRD_PARTY_LICENSES.")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.environment = patch.dict(os.environ, {**UNSET, "EDITTUDE_ROOT": str(self.root)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.stdout = io.StringIO()
        # A previous install() in this process must not swallow a later real fetch.
        install_models._seed_vc_notice_sent = True

    def _git(self, command, **kwargs):
        parts = [str(part) for part in command]
        stdout = ""
        if "rev-parse" in parts:
            into = Path(parts[parts.index("-C") + 1]).name
            sha = next(backend["git"]["sha"] for backend in install_models.BACKENDS.values()
                       if backend.get("git", {}).get("into") == into)
            stdout = sha + "\n"
        # returncode 0 on `git apply --reverse --check` means the patch is already applied.
        return subprocess.CompletedProcess(parts, 0, stdout, "")

    def _install(self, names, side_effect=None):
        with redirect_stdout(self.stdout), \
                patch.object(install_models, "_venv"), \
                patch.object(install_models, "V2_MODELS", self.root / "no-v2-models"), \
                patch.object(install_models.subprocess, "run", self._git), \
                patch.object(install_models, "_run", side_effect=side_effect) as run:
            install_models.install(names)
        return run

    def _seed_weights(self, *, skip_repo=None):
        for entry in install_models.BACKENDS["seed-vc"]["hf"]:
            if entry["repo"] == skip_repo:
                continue
            destination = self.root / "models" / entry["into"]
            if entry.get("cache"):
                slug = "models--" + entry["repo"].replace("/", "--")
                folder = destination / slug / "snapshots" / entry["rev"]
            else:
                folder = destination
            folder.mkdir(parents=True, exist_ok=True)
            for pattern in entry["files"]:
                (folder / pattern.replace("*", "x")).write_bytes(b"x")

    def _seed_clone(self, into):
        (self.root / "models" / into / ".git").mkdir(parents=True)

    def test_fetch_prints_the_notice_once_before_the_clone(self):
        calls = []

        def record(command):
            calls.append(([str(part) for part in command], self.stdout.getvalue()))

        self._install(["seed-vc"], record)
        output = self.stdout.getvalue()
        clones = [item for item in calls if item[0][:2] == ["git", "clone"]]
        snapshots = [item for item in calls if any("snapshot_download" in part for part in item[0])]
        self.assertEqual(len(clones), 1)
        self.assertEqual(clones[0][1].count(self.NOTICE), 1)
        self.assertEqual(output.count(self.NOTICE), 1)
        self.assertEqual(len(snapshots), 5)
        for snapshot in snapshots:
            self.assertEqual(snapshot[1].count(self.NOTICE), 1)

    def test_cached_install_is_silent_and_does_not_fetch(self):
        self._seed_clone("seed-vc")
        self._seed_weights()
        run = self._install(["seed-vc"])
        run.assert_not_called()
        self.assertNotIn(self.NOTICE, self.stdout.getvalue())

    def test_partial_cache_prints_the_notice_once_before_the_missing_weight(self):
        missing = "nvidia/bigvgan_v2_44khz_128band_512x"
        self._seed_clone("seed-vc")
        self._seed_weights(skip_repo=missing)
        calls = []

        def record(command):
            self.assertEqual(self.stdout.getvalue().splitlines()[-1], self.NOTICE)
            calls.append([str(part) for part in command])

        self._install(["seed-vc"], record)
        self.assertEqual(len(calls), 1)
        self.assertIn("snapshot_download", calls[0][2])
        self.assertEqual(json.loads(calls[0][-1])["repo_id"], missing)
        self.assertEqual(self.stdout.getvalue().count(self.NOTICE), 1)

    def test_diffsinger_install_does_not_print_the_seed_vc_notice(self):
        run = self._install(["diffsinger"])
        self.assertGreaterEqual(run.call_count, 1)
        self.assertNotIn(self.NOTICE, self.stdout.getvalue())
        self.assertIn("non-commercial use only", self.stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
