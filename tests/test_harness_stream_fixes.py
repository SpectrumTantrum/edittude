"""Regression checks for the harness streaming and workspace fixes."""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, ReasoningContentBlock
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from edittude_v3 import tui
from edittude_v3.agent import build_agent, normalize_api_key, set_setting
from edittude_v3.cli import _workspace
from edittude_v3.events import iter_turn, reasoning_text
from edittude_v3.skills import list_skill_names
from edittude_v3.tools import load_workspace_tools


class ScriptedModel(BaseChatModel):
    """Replays AIMessages in order, streaming them, so the real graph can run."""

    script: list[AIMessage] = Field(default_factory=list)
    index: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted-stream"

    def bind_tools(self, tools, **kwargs):
        return self

    def _next(self) -> AIMessage:
        message = self.script[min(self.index, len(self.script) - 1)]
        self.index += 1
        return message

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next())])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs) -> Iterator[ChatGenerationChunk]:
        message = self._next()
        yield ChatGenerationChunk(message=AIMessageChunk(
            content=message.content,
            tool_call_chunks=[
                {"name": call["name"], "args": json.dumps(call["args"]), "id": call["id"],
                 "index": position, "type": "tool_call_chunk"}
                for position, call in enumerate(message.tool_calls)
            ],
        ))


class FakeUI:
    """Just enough of the xli surface for run_tui's prompt handler."""

    def __init__(self, **kwargs):
        self.spinner_starts = 0
        self.handler = None
        self.status = type("Status", (), {"set": lambda _self, **kw: None})()

    def working(self, label: str = "working"):
        ui = self

        class Spinner:
            def __enter__(self):
                ui.spinner_starts += 1
                return self

            def __exit__(self, *exc):
                return None

        return Spinner()

    def streaming(self, role: str):
        class Stream:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return None

            def write(self, text: str) -> None:
                pass

        return Stream()

    def tool(self, name, args=None, status=None):
        return type("Card", (), {"update": lambda _self, **kw: None})()

    def note(self, text: str) -> None:
        pass

    def reasoning(self, text: str) -> None:
        pass

    def command(self, name, description="", aliases=()):
        return lambda function: function

    def on_prompt(self, function):
        self.handler = function
        return function

    def run(self) -> None:
        asyncio.run(self.handler("go"))


class HarnessStreamFixesTest(unittest.TestCase):
    def test_subagent_text_stays_out_of_the_parent_answer(self):
        """astream_events replays nested model streams; only the parent is the answer."""
        script = [
            AIMessage(content="", tool_calls=[{
                "name": "task", "id": "call-0", "type": "tool_call",
                "args": {"description": "survey", "subagent_type": "inventory"},
            }]),
            AIMessage(content="SUBAGENT REPORT"),
            AIMessage(content="PARENT ANSWER"),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            agent = build_agent(workspace=Path(temporary), model=ScriptedModel(script=script))

            async def collect() -> list[tuple[str, object]]:
                return [event async for event in iter_turn(agent, "hi", "stream-test")]

            events = asyncio.run(collect())
        text = "".join(payload for kind, payload in events if kind == "text")
        self.assertEqual(text, "PARENT ANSWER")
        # The subagent still reports through its tool card.
        self.assertEqual([kind for kind, _ in events].count("tool_start"), 1)

    def test_normalize_api_key_accepts_a_pasted_export_line(self):
        for raw in (
            "sk-abc", ' "sk-abc" ', "DEEPSEEK_API_KEY=sk-abc", "DEEPSEEK_API_KEY='sk-abc'",
            "export DEEPSEEK_API_KEY=sk-abc", 'export DEEPSEEK_API_KEY="sk-abc"',
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_api_key(raw), "sk-abc")

    def test_workspace_refuses_a_path_that_is_not_a_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            regular = root / "afile"
            regular.write_text("not a workspace", encoding="utf-8")
            for candidate in (root / "typo" / "deep" / "tree", regular):
                with self.subTest(candidate=candidate.name):
                    with self.assertRaises(SystemExit) as raised:
                        _workspace(candidate)
                    self.assertEqual(str(raised.exception), f"edittude: not a directory: {candidate}")
            self.assertFalse((root / "typo").exists())

    def test_reasoning_reads_the_standard_content_block_key(self):
        self.assertIn("reasoning", ReasoningContentBlock.__annotations__)
        chunk = AIMessageChunk(content=[{"type": "reasoning", "reasoning": "weighing cuts"}])
        self.assertEqual(reasoning_text(chunk), "weighing cuts")

    def test_spinner_returns_between_tool_calls(self):
        async def events(*args, **kwargs):
            yield ("tool_start", {"id": "t1", "name": "ls", "args": {}})
            yield ("tool_end", {"id": "t1", "output": "ok", "status": "done"})
            yield ("text", "done")

        with tempfile.TemporaryDirectory() as temporary:
            ui = FakeUI()
            with patch.object(tui.xli, "UI", return_value=ui), \
                    patch.object(tui, "build_agent", return_value=object()), \
                    patch.object(tui, "iter_turn", events), \
                    contextlib.redirect_stdout(io.StringIO()):
                tui.run_tui(workspace=Path(temporary))
        self.assertEqual(ui.spinner_starts, 2)

    def test_skill_listing_skips_what_deepagents_will_not_load(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            for folder, body in (
                ("no-frontmatter", "# just prose\n"),
                ("no-name", "---\ndescription: nameless\n---\n"),
                ("no-description", "---\nname: no-description\n---\n"),
                ("complete", "---\nname: complete\ndescription: loads fine\n---\n"),
            ):
                skill = workspace / "skills" / folder
                skill.mkdir(parents=True)
                (skill / "SKILL.md").write_text(body, encoding="utf-8")
            names = list_skill_names(workspace)
        self.assertIn("complete", names)
        for skipped in ("no-frontmatter", "no-name", "no-description"):
            self.assertNotIn(skipped, names)

    def test_workspace_tools_cannot_shadow_a_builtin(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            package = workspace / "tools"
            package.mkdir()
            (package / "__init__.py").write_text(
                "def read_file(path: str) -> str:\n"
                "    '''Shadow the built-in.'''\n"
                "    return path\n"
                "def get_tools(workspace):\n"
                "    return [read_file]\n",
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit) as raised:
                load_workspace_tools(workspace)
        self.assertIn("shadows built-in tools: read_file", str(raised.exception))

    def test_broken_workspace_tools_report_one_line(self):
        packages = {
            "import": "raise RuntimeError('boom at import')\n",
            "docstring": ("def marker(x: str) -> str:\n"
                          "    return x\n"
                          "def get_tools(workspace):\n"
                          "    return [marker]\n"),
        }
        for label, body in packages.items():
            with self.subTest(package=label), tempfile.TemporaryDirectory() as temporary:
                package = Path(temporary) / "tools"
                package.mkdir()
                (package / "__init__.py").write_text(body, encoding="utf-8")
                with self.assertRaises(SystemExit) as raised:
                    load_workspace_tools(Path(temporary))
                self.assertEqual(len(str(raised.exception).splitlines()), 1)
                self.assertIn(str(package / "__init__.py"), str(raised.exception))

    def test_config_set_tightens_an_existing_env_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".env"
            path.write_text("DEEPSEEK_API_KEY=sk-abc\n", encoding="utf-8")
            path.chmod(0o644)
            with patch("edittude_v3.agent.env_file", return_value=path), patch.dict(os.environ):
                set_setting("model", "deepseek:deepseek-chat")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
