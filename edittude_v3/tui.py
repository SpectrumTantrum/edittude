from __future__ import annotations

import time
import uuid
from pathlib import Path

import xli
from rich.box import ROUNDED
from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from edittude_v3 import APP_NAME, __version__
from edittude_v3.agent import build_agent, model_label
from edittude_v3.events import iter_turn, preview
from edittude_v3.paths import state_dir
from edittude_v3.skills import list_skill_names
from edittude_v3.tools import list_tool_names

#: The accent knob for the whole CLI — magenta marks active/running state.
ACCENT = "#bb9af7"
#: The rest of the palette. Chromatic hues and mid-greys only: body text keeps
#: the terminal's own foreground, so the UI reads on dark and light terminals.
TEAL = "#1abc9c"
ORANGE = "#ff9e64"
BLUE = "#7aa2f7"
YELLOW = "#e0af68"
GREY = "#787878"
MUTED = "#6c6c6c"
RED = "#f7768e"
GREEN = "#9ece6a"
BORDER = "#505058"

#: Transcript grammar: ❯ on prompts, ◆ bullets on tools, ┃ rail on reasoning.
#: Two knobs are named for their xli role, not their colour: the spinner and the
#: busy toolbar use warning_color (hence magenta), finished tool cards use
#: success_color (hence grey) — running cards stay magenta via tool_color.
THEME = xli.CODEX.with_overrides(
    user_label="❯",
    assistant_label="edittude",
    user_color="default",
    assistant_color=ACCENT,
    system_color=BLUE,
    tool_glyph="◆",
    tool_done_glyph="◆",
    tool_error_glyph="✗",
    tool_color=ACCENT,
    reasoning_glyph="┃",
    reasoning_color=f"italic {MUTED}",
    plan_color="#FFDB8D",
    error_color=RED,
    warning_color=ACCENT,
    success_color=GREY,
    muted_color=MUTED,
    diff_add_color=GREEN,
    diff_del_color=RED,
    diff_hunk_color=MUTED,
    prompt_glyph="❯",
    prompt_color=f"bold {ACCENT}",
    command_color=f"bold {YELLOW}",
    code_theme="ansi_dark",
    status_separator=" │ ",
    status_color=MUTED,
)


def fmt_duration(seconds: float) -> str:
    """Elapsed time, Grok-style: 7.1s · 21s · 1m5s · 1h2m."""
    if seconds < 10:
        return f"{seconds:.1f}s"
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m{int(seconds % 60)}s"
    return f"{int(seconds // 3600)}h{int(seconds % 3600) // 60}m"


def _history_file(workspace: Path) -> str:
    return str(state_dir(workspace) / "history")


def _display_path(path: Path) -> str:
    return str(path).replace(str(Path.home()), "~", 1)


def _banner(workspace: Path, skills: int, tools: int) -> RenderableType:
    title = Text()
    title.append("◆ ", style=ACCENT)
    title.append(APP_NAME, style="bold")
    title.append(f"  v{__version__}", style="dim")

    meta = Table.grid(padding=(0, 1))
    meta.add_column(style=MUTED, min_width=8)
    meta.add_column()
    skill_word = "skill" if skills == 1 else "skills"
    tool_word = "tool" if tools == 1 else "tools"
    meta.add_row("model", Text(model_label(), style=TEAL))
    meta.add_row("folder", Text(_display_path(workspace), style=ORANGE))
    meta.add_row("ready", Text(f"{skills} {skill_word} · {tools} {tool_word}", style="dim"))
    welcome = Text("Name a footage folder, or describe the cut.", style="dim")

    panel = Panel(
        Group(title, Text(""), meta, Text(""), welcome),
        box=ROUNDED,
        border_style=BORDER,
        padding=(1, 2),
        expand=False,
    )
    return panel


def _help_text(ui: xli.UI) -> Text:
    text = Text()
    text.append(f"{APP_NAME}\n", style="bold")
    text.append("commands\n", style=MUTED)
    for cmd in ui._slash.all():
        text.append(f"  /{cmd.name:<8}", style=f"bold {YELLOW}")
        text.append(cmd.description or "")
        if cmd.aliases:
            shown = "  " + "  ".join(f"/{alias}" for alias in cmd.aliases)
            text.append(shown, style="dim")
        text.append("\n")
    text.append("\nkeys\n", style=MUTED)
    for key, label in (
        ("enter", "send"),
        ("alt+enter, ctrl+j", "newline"),
        ("/", "slash commands"),
        ("@", "mention a file"),
        ("esc", "interrupt the turn"),
        ("ctrl+c", "interrupt"),
        ("ctrl+d", "quit"),
        ("up, down", "history"),
        ("y, a, n", "accept, always, deny"),
    ):
        text.append(f"  {key:<22}", style="bold")
        text.append(label + "\n", style="dim")
    return text


def _skill_list(names: list[str]) -> Text:
    text = Text()
    word = "skill" if len(names) == 1 else "skills"
    text.append(f"{len(names)} {word}\n", style="bold")
    width = 0
    for name in names:
        piece = f"{name}  "
        if width and width + len(piece) > 72:
            text.append("\n")
            width = 0
        text.append(piece, style=TEAL)
        width += len(piece)
    return text


def run_tui(*, workspace: Path, thread: str | None = None) -> None:
    agent = build_agent(workspace=workspace)
    thread_id = thread or uuid.uuid4().hex
    skills = list_skill_names(workspace)

    ui = xli.UI(
        title=APP_NAME,
        intro="Chronology is the spine. One idea per shot.",
        theme=THEME,
        status_fields=("cwd", "model", "thread", "skills"),
        history_file=_history_file(workspace),
        notify_after=20,
    )
    ui.status.set(
        cwd=workspace.name,
        model=model_label(),
        thread=f"thread {thread_id[:8]}",
        skills=f"{len(skills)} skills",
    )

    @ui.command("new", description="fresh thread")
    async def cmd_new(ui: xli.UI, args: str) -> None:
        nonlocal thread_id
        thread_id = uuid.uuid4().hex
        ui.status.set(thread=f"thread {thread_id[:8]}")
        ui.note(f"New thread {thread_id[:8]}")

    @ui.command("skills", description="list skill folders")
    async def cmd_skills(ui: xli.UI, args: str) -> None:
        names = list_skill_names(workspace)
        if not names:
            ui.note("No skills yet. Add folders under skills/<name>/SKILL.md")
            return
        ui.print(_skill_list(names))

    @ui.command("status", description="model, thread, workspace")
    async def cmd_status(ui: xli.UI, args: str) -> None:
        count = len(list_skill_names(workspace))
        ui.note(
            f"{APP_NAME} · {model_label()} · thread {thread_id[:8]} · "
            f"{_display_path(workspace)} · {count} skills"
        )

    @ui.command("help", description="commands and keys", aliases=("?",))
    async def cmd_help(ui: xli.UI, args: str) -> None:
        ui.print(_help_text(ui))

    @ui.on_prompt
    async def handle(prompt: str) -> None:
        cards: dict[str, object] = {}
        stream = None
        reasoning_buf: list[str] = []
        reasoning_started: float | None = None
        turn_started = time.monotonic()
        spinner = None

        def start_spinner() -> None:
            nonlocal spinner
            if spinner is None:
                spinner = ui.working("Thinking…")
                spinner.__enter__()

        def stop_spinner() -> None:
            nonlocal spinner
            if spinner is not None:
                spinner.__exit__(None, None, None)
                spinner = None

        start_spinner()

        def close_stream() -> None:
            nonlocal stream
            if stream is not None:
                stream.__exit__(None, None, None)
                stream = None

        def flush_reasoning() -> None:
            nonlocal reasoning_started
            if not reasoning_buf:
                return
            thought = "".join(reasoning_buf).strip()
            reasoning_buf.clear()
            elapsed = time.monotonic() - reasoning_started if reasoning_started else 0.0
            reasoning_started = None
            if thought:
                # No title param on the reasoning cell, so the header is the first railed line.
                ui.reasoning(f"◆ Thought for {fmt_duration(elapsed)}\n{preview(thought, limit=800)}")

        def write_text(text: str) -> None:
            nonlocal stream
            if stream is None:
                flush_reasoning()
                stream = ui.streaming("assistant")
                stream.__enter__()
            stream.write(text)

        try:
            async for kind, payload in iter_turn(agent, prompt, thread_id):
                if kind == "reasoning":
                    if reasoning_started is None:
                        reasoning_started = time.monotonic()
                    reasoning_buf.append(payload)
                    continue

                stop_spinner()

                if kind == "text":
                    write_text(payload)
                    continue

                if kind == "tool_start":
                    close_stream()
                    flush_reasoning()
                    cards[payload["id"]] = ui.tool(
                        payload["name"],
                        args=payload["args"],
                        status="running",
                    )
                    continue

                if kind == "tool_end":
                    card = cards.get(payload["id"])
                    if card is None:
                        continue
                    card.update(
                        status=payload.get("status", "done"),
                        output=preview(payload.get("output")),
                    )
                    # The next model call can be long; show activity again.
                    if stream is None:
                        start_spinner()
        finally:
            stop_spinner()
            close_stream()
            flush_reasoning()
            ui.note(f"Worked for {fmt_duration(time.monotonic() - turn_started)}")

    # ui.print() before run() has no printer attached, so banner goes out directly.
    Console().print(_banner(workspace, len(skills), len(list_tool_names(workspace))))
    ui.run()
