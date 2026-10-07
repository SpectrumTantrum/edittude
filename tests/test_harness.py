"""Offline integration checks. Run: python -m unittest discover -s tests -v."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field

from deepagents.middleware.summarization import create_summarization_middleware

import xli
from rich.console import Console

from edittude_v3.agent import MODEL, build_agent, build_backend
from edittude_v3.cli import _parser, main
from edittude_v3.paths import state_dir
from edittude_v3.skills import list_skill_names, list_skills
from edittude_v3.tools import list_tool_names, load_workspace_tools
from edittude_v3.tui import (
    BORDER,
    BORDER_ACTIVE,
    PLACEHOLDER,
    PURPLE,
    PURPLE_BRIGHT,
    TEXT,
    THEME,
    _banner,
    _dress_composer,
    _help_text,
    fmt_duration,
)
from tools import get_tools

ROOT = Path(__file__).resolve().parents[1]
MEDIA_TOOLS = {
    "get_capabilities", "media_inspect", "media_render", "audio_timing",
    "score_read", "speech_transcribe", "speech_synthesize", "audio_separate",
    "singing_synthesize", "voice_convert", "image_describe",
}


class ScriptedModel(BaseChatModel):
    """Exercise real middleware and tool dispatch without making model requests."""

    system_prompts: list[str] = Field(default_factory=list)
    registered_names: set[str] = Field(default_factory=set)
    delegated_messages: list[ToolMessage] = Field(default_factory=list)
    skill_path: str

    @property
    def _llm_type(self) -> str:
        return "offline-harness-test"

    def bind_tools(self, tools, **kwargs):
        self.registered_names.update(item.name for item in tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.system_prompts.append(str(messages[0].content))
        completed = [message for message in messages if isinstance(message, ToolMessage)]
        steps = [
            ("read_file", {"file_path": self.skill_path}),
            ("get_capabilities", {}),
            ("media_inspect", {"path": "/fixture.wav", "modes": ["probe"]}),
            ("media_render", {"request": {
                "op": "resample", "path": "/fixture.wav", "output": "/resampled.wav",
                "sample_rate": 8000, "channels": 1,
            }}),
            ("media_inspect", {"path": "/resampled.wav", "modes": ["probe"]}),
            ("task", {"subagent_type": "inventory",
                      "description": "Read video-extract-audio and check media capabilities."}),
        ]
        if "You inventory footage." in str(messages[0].content):
            self.delegated_messages = completed
            steps = steps[:2]
        if len(completed) < len(steps):
            name, args = steps[len(completed)]
            reply = AIMessage(content="", tool_calls=[{
                "name": name, "args": args, "id": f"call-{len(completed)}",
                "type": "tool_call",
            }])
        else:
            reply = AIMessage(content="Inspected the workspace fixture.")
        return ChatResult(generations=[ChatGeneration(message=reply)])


class HarnessTest(unittest.TestCase):
    def test_tool_packages_are_isolated_and_support_relative_imports(self):
        cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            workspaces = [Path(temporary) / name for name in ("first", "second")]
            loaded = []
            for index, workspace in enumerate(workspaces):
                package = workspace / "tools"
                package.mkdir(parents=True)
                (package / "values.py").write_text(f"VALUE = {index}\n")
                (package / "__init__.py").write_text(
                    "from .values import VALUE\n"
                    "def get_tools(workspace):\n"
                    "    def marker() -> dict:\n"
                    "        '''Identify this workspace.'''\n"
                    "        return {'value': VALUE, 'workspace': str(workspace)}\n"
                    "    return [marker]\n"
                )
                loaded.append(load_workspace_tools(workspace)[0])
            for index, registered in enumerate(loaded):
                self.assertEqual(registered.invoke({}), {
                    "value": index, "workspace": str(workspaces[index].resolve()),
                })
        self.assertEqual(Path.cwd(), cwd)

    @unittest.skipUnless(shutil.which("ffprobe") and shutil.which("ffmpeg"),
                         "ffmpeg and ffprobe are required for the media check")
    def test_relocated_pack_runs_through_actual_agent_graph(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            for folder in ("skills", "tools"):
                shutil.copytree(ROOT / folder, workspace / folder,
                                ignore=shutil.ignore_patterns("__pycache__"))
            (workspace / "AGENTS.md").write_text("Local memory sentinel for the test.\n")
            source = workspace / "fixture.wav"
            with wave.open(str(source), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(b"\x00\x00" * 16000)
            original = hashlib.sha256(source.read_bytes()).hexdigest()
            names = list_skill_names(workspace)
            manifest = json.loads((workspace / "skills/manifest.json").read_text())
            portable_names = {entry["skill"] for entry in manifest["skills"]}
            self.assertEqual(len(portable_names), 33)
            self.assertTrue(portable_names.issubset(names))
            self.assertEqual(set(list_tool_names(workspace)), MEDIA_TOOLS)
            model = ScriptedModel(skill_path=str(workspace / "skills/video-extract-audio/SKILL.md"))
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
                agent = build_agent(workspace=workspace, model=model)
                result = agent.invoke(
                    {"messages": [{"role": "user", "content": "Inspect fixture.wav."}]},
                    config={"configurable": {"thread_id": "offline-test"}},
                )
            self.assertTrue(MEDIA_TOOLS.issubset(model.registered_names))
            self.assertIn("execute", model.registered_names)
            prompt = model.system_prompts[0]
            for name in names:
                self.assertIn(f"**{name}**", prompt)
            self.assertIn("Local memory sentinel for the test.", prompt)
            delegated_prompt = next(prompt for prompt in model.system_prompts
                                    if "You inventory footage." in prompt)
            for name in names:
                self.assertIn(f"**{name}**", delegated_prompt)
            self.assertEqual({message.name for message in model.delegated_messages},
                             {"read_file", "get_capabilities"})
            for message in model.delegated_messages:
                self.assertEqual(message.status, "success", message.content)
            tool_messages = [
                message for message in result["messages"] if isinstance(message, ToolMessage)
            ]
            outputs = {
                message.name: message
                for message in tool_messages
            }
            self.assertEqual(set(outputs), {
                "read_file", "get_capabilities", "media_inspect", "media_render", "task",
            })
            for message in tool_messages:
                self.assertEqual(message.status, "success", message.content)
            self.assertIn("video-extract-audio", outputs["read_file"].content)
            capabilities = json.loads(outputs["get_capabilities"].content)
            self.assertIsInstance(capabilities, dict)
            render = json.loads(outputs["media_render"].content)
            self.assertEqual(render["status"], "ok", render)
            inspections = [json.loads(message.content) for message in tool_messages
                           if message.name == "media_inspect"]
            self.assertEqual(len(inspections), 2)
            for inspection, sample_rate in zip(inspections, (16000, 8000)):
                self.assertEqual(inspection["status"], "ok", inspection)
                self.assertAlmostEqual(inspection["duration"], 1, places=3)
                audio_stream = inspection["probe"]["streams"][0]
                self.assertEqual(audio_stream["codec_type"], "audio")
                self.assertEqual(int(audio_stream["sample_rate"]), sample_rate)
                self.assertEqual(audio_stream["channels"], 1)
            with wave.open(str(workspace / "resampled.wav"), "rb") as rendered:
                self.assertEqual(rendered.getframerate(), 8000)
                self.assertEqual(rendered.getnframes(), 8000)
                self.assertEqual(rendered.getnchannels(), 1)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original)

    def test_empty_workspace_uses_bundled_skills_and_tools(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            names = list_skill_names(workspace)
            self.assertIn("zero-shot-cut", names)
            self.assertGreaterEqual(len(names), 33)
            self.assertEqual(set(list_tool_names(workspace)), MEDIA_TOOLS)

    def test_offloaded_history_lands_in_the_project_state_dir(self):
        """Regression: artifacts_root of "/" wrote to the read-only macOS root."""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary).resolve()
            backend = build_backend(workspace)
            middleware = create_summarization_middleware(
                init_chat_model(MODEL, api_key="dummy"), backend
            )
            path = middleware._get_history_path("session_test")
            self.assertIn(f"{workspace}/.edittude/", path)
            self.assertNotIn(f"{workspace}/.edittude-v3", path)
            # Real file tools still work on absolute host paths.
            probe = workspace / "probe.txt"
            self.assertIsNone(backend.write(str(probe), "hi").error)
            self.assertEqual(probe.read_text(), "hi")

    def test_workspace_skills_override_bundled_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            skill = workspace / "skills" / "zero-shot-cut"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: zero-shot-cut\ndescription: local override\n---\n",
                encoding="utf-8",
            )
            rows = dict(list_skills(workspace))
            self.assertEqual(rows["zero-shot-cut"], "local override")

    def test_cli_lists_tools_without_a_key(self):
        for arguments in (["-C", str(ROOT), "tools"], ["tools", "-C", str(ROOT)]):
            self.assertEqual(_parser().parse_args(arguments).directory, ROOT)
        output = io.StringIO()
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}), contextlib.redirect_stdout(output):
            main(["tools", "-C", str(ROOT)])
        lines = output.getvalue().splitlines()
        self.assertEqual(lines[0], "11 tools")
        self.assertEqual({line.strip() for line in lines[1:]}, MEDIA_TOOLS)

    def test_state_dir_keeps_an_existing_legacy_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            legacy = workspace / ".edittude-v3"
            legacy.mkdir()
            self.assertEqual(state_dir(workspace), legacy.resolve())
            self.assertFalse((workspace / ".edittude").exists())

    def test_banner_and_help_use_the_edittude_name(self):
        buf = io.StringIO()
        Console(file=buf, force_terminal=False, width=80).print(_banner(Path("/tmp/saturday"), 2, 1))
        text = buf.getvalue()
        self.assertIn("edittude", text)
        self.assertNotIn("edittude-v3", text)
        self.assertIn("folder", text)
        self.assertIn("2 skills · 1 tool", text)
        help_text = _help_text(xli.UI(title="edittude")).plain
        for token in ("/help", "/quit", "/clear", "enter", "esc", "ctrl+d", "ctrl+c"):
            self.assertIn(token, help_text)
        self.assertNotIn("edittude-v3", help_text)

    def test_oscura_composer_is_a_rounded_box(self):
        ui = xli.UI(title="edittude", intro="Chronology is the spine.", theme=THEME)
        app = ui._engine._build_app()
        _dress_composer(app, ui._engine)
        children = app.layout.container.children
        top = "".join(piece for _style, piece in children[1].content.create_content(24, 1).get_line(0))
        bottom = "".join(piece for _style, piece in children[3].content.create_content(24, 1).get_line(0))
        self.assertEqual(top, "╭" + "─" * 22 + "╮")
        self.assertEqual(bottom, "╰" + "─" * 22 + "╯")
        composer = children[2]
        self.assertEqual(len(composer.left_margins), 1)
        self.assertEqual(len(composer.right_margins), 1)
        rules = dict(app.style.style_rules)
        self.assertEqual(rules["composer.idle"], BORDER)
        self.assertEqual(rules["composer.active"], BORDER_ACTIVE)
        self.assertEqual(rules["placeholder"], "#5E646C")
        placeholder = composer.content.input_processors[-1]
        from prompt_toolkit.document import Document
        from prompt_toolkit.layout.processors import TransformationInput

        empty = TransformationInput(
            composer.content, Document(), 0, lambda i: i, [], 20, 1, None
        )
        shown = "".join(piece for _style, piece in placeholder.apply_transformation(empty).fragments)
        self.assertEqual(shown, PLACEHOLDER)
        self.assertEqual(PURPLE, "#9B7ECE")
        self.assertEqual(PURPLE_BRIGHT, "#C4A7E7")
        self.assertEqual(TEXT, "#E4E4E4")

    def test_durations_read_like_grok(self):
        for seconds, expected in (
            (7.13, "7.1s"), (21.4, "21s"), (59.9, "59s"), (65, "1m5s"), (3720, "1h2m")
        ):
            self.assertEqual(fmt_duration(seconds), expected)

    def test_portable_tools_return_an_error_dict(self):
        """tools/ stays harness-free: plain callables, plain dicts, no raising."""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            registered = {item.__name__: item for item in get_tools(workspace)}
            for arguments in ({}, {"op": "resample", "path": "../source.wav", "output": "/out.wav"}):
                result = registered["media_render"](arguments)
                self.assertEqual(result["status"], "error", result)
                self.assertTrue(result["error"])
            self.assertFalse((workspace / "out.wav").exists())

    def test_tool_errors_are_returned_to_the_agent(self):
        """The adapter turns those dicts into ToolMessage(status="error") for the UI."""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            shutil.copytree(ROOT / "tools", workspace / "tools",
                            ignore=shutil.ignore_patterns("__pycache__"))
            registered = {item.name: item for item in load_workspace_tools(workspace)}
            message = registered["media_render"].invoke(
                {"name": "media_render", "args": {"request": {}},
                 "id": "call_1", "type": "tool_call"}
            )
            self.assertIsInstance(message, ToolMessage)
            self.assertEqual(message.status, "error")
            self.assertEqual(message.tool_call_id, "call_1")
            self.assertEqual(json.loads(message.content)["status"], "error")
            self.assertFalse((workspace / "out.wav").exists())

    def test_adapter_flags_unavailable_and_leaves_success_alone(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            (workspace / "tools").mkdir()
            (workspace / "tools" / "__init__.py").write_text(
                "def missing() -> dict:\n"
                "    '''Report a missing runtime.'''\n"
                "    return {'status': 'unavailable', 'error': 'no demucs'}\n"
                "def fine() -> dict:\n"
                "    '''Succeed.'''\n"
                "    return {'status': 'ok', 'path': '/out.wav'}\n"
                "def get_tools(workspace):\n"
                "    return [missing, fine]\n", encoding="utf-8",
            )
            registered = {item.name: item for item in load_workspace_tools(workspace)}
            call = {"args": {}, "id": "call_1", "type": "tool_call"}
            unavailable = registered["missing"].invoke({**call, "name": "missing"})
            self.assertEqual(unavailable.status, "error")
            self.assertEqual(json.loads(unavailable.content),
                             {"status": "unavailable", "error": "no demucs"})
            ok = registered["fine"].invoke({**call, "name": "fine"})
            self.assertEqual(ok.status, "success")
            self.assertEqual(json.loads(ok.content), {"status": "ok", "path": "/out.wav"})

    def test_skill_manifest_maps_to_model_compatible_tools(self):
        registered = load_workspace_tools(ROOT)
        names = {item.name for item in registered}
        manifest = json.loads((ROOT / "skills/manifest.json").read_text())
        self.assertEqual(len(manifest["skills"]), 33)
        self.assertTrue({entry["skill"] for entry in manifest["skills"]}.issubset(
            list_skill_names(ROOT)))
        for entry in manifest["skills"]:
            self.assertTrue(set(entry["tools"]).issubset(names), entry["skill"])
        for item in registered:
            schema = convert_to_openai_tool(item)
            self.assertEqual(schema["function"]["name"], item.name)
            self.assertEqual(schema["function"]["parameters"]["type"], "object")
            json.dumps(schema)
        # Binding exercises the installed provider's schema conversion, with no request.
        bound = init_chat_model(MODEL, api_key="unused-offline-test").bind_tools(registered)
        self.assertEqual({item["function"]["name"] for item in bound.kwargs["tools"]}, names)


if __name__ == "__main__":
    unittest.main()
