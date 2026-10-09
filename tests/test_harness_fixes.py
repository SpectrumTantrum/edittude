"""Regression checks for the five harness and portable-tool fixes."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import ToolMessage
from langgraph.types import Command

from edittude_v3.events import iter_turn, preview
from edittude_v3.tools import load_workspace_tools
from tools import install_models
from tools.common import model_python
from tools.validate import validate

ROOT = Path(__file__).resolve().parents[1]


def _loaded_packages() -> set[str]:
    return {name for name in sys.modules if name.startswith("_edittude_tools_")}


class HarnessFixesTest(unittest.TestCase):
    def test_workspace_tools_are_loaded_once_per_package(self):
        """The TUI calls this twice at startup; each call used to leak a package."""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            (workspace / "tools").mkdir()
            (workspace / "tools" / "__init__.py").write_text(
                "def marker() -> str:\n"
                "    '''Identify this workspace.'''\n"
                "    return 'loaded'\n"
                "def get_tools(workspace):\n"
                "    return [marker]\n", encoding="utf-8",
            )
            first = load_workspace_tools(workspace)[0]
            after_first = _loaded_packages()
            second = load_workspace_tools(workspace)[0]
            self.assertEqual(first.func.__module__, second.func.__module__)
            self.assertEqual(after_first, _loaded_packages())

    def test_preview_unwraps_a_command_carrying_a_tool_message(self):
        message = ToolMessage(content=[{"type": "text", "text": " actual result "}],
                              tool_call_id="call")
        self.assertEqual(preview(message), "actual result")
        self.assertEqual(preview(Command(update={"messages": [message]})), "actual result")

    def test_iter_turn_flags_failed_tool_calls(self):
        """Failures used to render as done: no status, and nothing at all on a raise."""
        class FakeAgent:
            async def astream_events(self, _payload, config=None, version=None):
                for status in ("success", "error"):
                    message = ToolMessage(content=status, tool_call_id="call", status=status)
                    yield {"event": "on_tool_end", "run_id": "run", "data": {"output": message}}
                yield {"event": "on_tool_error", "run_id": "run",
                       "data": {"error": ValueError("boom"), "input": {}}}

        async def collect():
            return [payload async for _, payload in iter_turn(FakeAgent(), "prompt", "thread")]

        events = asyncio.run(collect())
        self.assertEqual([event["status"] for event in events], ["done", "error", "error"])
        self.assertEqual(preview(events[-1]["output"]), "boom")

    def test_installed_v2_skips_a_malformed_manifest(self):
        entry = {"rev": "revision", "files": ["model.bin"]}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, content in (("00-not-json", "{"), ("01-no-files", '{"revision": "revision"}'),
                                  ("02-good", json.dumps({"revision": entry["rev"],
                                                          "files": entry["files"]}))):
                (root / name).mkdir()
                (root / name / ".edittude-model.json").write_text(content, encoding="utf-8")
            with patch.object(install_models, "V2_MODELS", root):
                self.assertEqual(install_models._installed_v2(entry),
                                 (root / "02-good", entry["files"]))

    def test_the_model_python_override_is_installed_into_rather_than_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            override = root / "python"
            override.symlink_to(sys.executable)
            with patch.dict(os.environ, {"EDITTUDE_ROOT": str(root),
                                         "EDITTUDE_MODEL_PYTHON": str(override)}), \
                    patch.object(install_models, "_uv", return_value="uv"), \
                    patch.object(install_models, "_run") as run:
                self.assertEqual(model_python(), override)
                install_models._venv(["example-dependency"])
            run.assert_called_once_with(
                ["uv", "pip", "install", "--quiet", "--python", override, "example-dependency"])
            self.assertFalse((root / ".venv-models").exists())

    def test_validate_reports_a_broken_pack_even_under_O(self):
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary)
            manifest = json.loads((ROOT / "skills" / "manifest.json").read_text(encoding="utf-8"))
            manifest["skills"] = manifest["skills"][:1]
            name = manifest["skills"][0]["skill"]
            (pack / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            shutil.copytree(ROOT / "skills" / name, pack / name)
            self.assertEqual(validate(pack), 1)  # Count comes from the manifest, not a constant.
            (pack / name / "SKILL.md").unlink()
            with self.assertRaisesRegex(SystemExit, "Missing mapped skill"):
                validate(pack)
            result = subprocess.run([sys.executable, "-O", str(ROOT / "tools" / "validate.py"),
                                     "--skills-dir", str(pack)],
                                    capture_output=True, text=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Missing mapped skill", result.stderr)


if __name__ == "__main__":
    unittest.main()
