from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

import xli
from prompt_toolkit.application.current import get_app
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import BufferControl, UIContent, UIControl
from prompt_toolkit.layout.margins import Margin
from prompt_toolkit.layout.processors import Processor, Transformation
from prompt_toolkit.output.color_depth import ColorDepth
from prompt_toolkit.styles.style import Style as PtStyle
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

#: Oscura Midnight. Canvas is near-black; purple is the brand, teal is success.
BASE = "#030304"
SURFACE = "#040507"
ELEVATED = "#0F1216"
TEXT = "#E4E4E4"
MUTED = "#81868F"
SUBTLE = "#5E646C"
PURPLE = "#9B7ECE"
PURPLE_BRIGHT = "#C4A7E7"
TEAL = "#50B48C"
RED = "#DC5A64"
GOLD = "#EBD96E"
AMBER = "#F1BD00"
CYAN = "#7DCFDF"
BORDER = "#242034"
BORDER_ACTIVE = "#343048"

#: Names the rest of the CLI already imports. They now point at Oscura hues.
ACCENT = PURPLE
ORANGE = AMBER
BLUE = CYAN
YELLOW = GOLD
GREY = SUBTLE
GREEN = TEAL

#: Shown inside the composer until the first character. Not the Grok slogan.
PLACEHOLDER = "Cut the day…"

#: Transcript grammar: ❯ on prompts, ◆ bullets on tools, ┃ rail on reasoning.
#: warning_color paints the braille spinner and the busy word; success_color
#: paints finished tools and the idle word.
THEME = xli.CODEX.with_overrides(
    user_label="❯",
    assistant_label="edittude",
    user_color=PURPLE_BRIGHT,
    assistant_color=PURPLE,
    system_color=MUTED,
    tool_glyph="◆",
    tool_done_glyph="◆",
    tool_error_glyph="✗",
    tool_color=PURPLE,
    reasoning_glyph="┃",
    reasoning_color=f"italic {MUTED}",
    plan_color=GOLD,
    error_color=RED,
    warning_color=PURPLE,
    success_color=TEAL,
    muted_color=MUTED,
    diff_add_color=TEAL,
    diff_del_color=RED,
    diff_hunk_color=SUBTLE,
    prompt_glyph="❯",
    prompt_color=f"bold {PURPLE_BRIGHT}",
    command_color=f"bold {CYAN}",
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
    title.append("◆ ", style=PURPLE)
    title.append(APP_NAME, style=f"bold {TEXT}")
    title.append(f"  v{__version__}", style=SUBTLE)

    meta = Table.grid(padding=(0, 1))
    meta.add_column(style=MUTED, min_width=8)
    meta.add_column()
    skill_word = "skill" if skills == 1 else "skills"
    tool_word = "tool" if tools == 1 else "tools"
    meta.add_row("model", Text(model_label(), style=TEAL))
    meta.add_row("folder", Text(_display_path(workspace), style=AMBER))
    meta.add_row("ready", Text(f"{skills} {skill_word} · {tools} {tool_word}", style=SUBTLE))
    welcome = Text("Name a footage folder, or describe the cut.", style=SUBTLE)

    return Panel(
        Group(title, meta, welcome),
        box=ROUNDED,
        border_style=BORDER,
        style=f"{TEXT} on {ELEVATED}",
        padding=(0, 2),
        expand=False,
    )


def _help_text(ui: xli.UI) -> Text:
    text = Text()
    text.append(f"{APP_NAME}\n", style="bold")
    text.append("commands\n", style=MUTED)
    for cmd in ui._slash.all():
        text.append(f"  /{cmd.name:<8}", style=f"bold {CYAN}")
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
        text.append(f"  {key:<22}", style=f"bold {TEXT}")
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


class _Rule(UIControl):
    """One row of a rounded frame: ╭───╮ or ╰───╯."""

    def __init__(self, left: str, right: str) -> None:
        self.left = left
        self.right = right

    def create_content(self, width: int, height: int) -> UIContent:
        if width <= 1:
            text = (self.left + self.right)[: max(width, 0)]
        else:
            text = self.left + "─" * (width - 2) + self.right

        def get_line(_i: int):
            return [("", text)]

        return UIContent(get_line=get_line, line_count=1, show_cursor=False)


class _Rail(Margin):
    """Vertical │ on the composer, colored with the frame."""

    def __init__(self, style_for) -> None:
        self._style_for = style_for

    def get_width(self, get_ui_content) -> int:
        return 1

    def create_margin(self, window_render_info, width: int, height: int):
        style = self._style_for()
        rows = window_render_info.window_height or height or 1
        out: list[tuple[str, str]] = []
        for _ in range(rows):
            out.append((style, "│"))
            out.append(("", "\n"))
        return out


class _Placeholder(Processor):
    """Ghost line while the buffer is empty. The cursor stays in front of it."""

    def apply_transformation(self, transformation_input) -> Transformation:
        document = transformation_input.document
        if document.text or transformation_input.lineno != 0:
            return Transformation(transformation_input.fragments)
        return Transformation(
            list(transformation_input.fragments) + [("class:placeholder", PLACEHOLDER)]
        )


class _QuietStatus(UIControl):
    """Idle / working plus the status fields. The intro already lists the keys."""

    def __init__(self, engine) -> None:
        self._engine = engine

    def create_content(self, width: int, height: int) -> UIContent:
        engine = self._engine
        state = "class:status.busy" if engine.busy else "class:status.idle"
        label = " working" if engine.busy else " idle"
        frags: list[tuple[str, str]] = [(state, label)]
        body = engine._status.render()
        if body:
            frags.append(("class:status", "  ·  "))
            frags.extend(("class:status", text) for _style, text in body)
        pet = engine._pet_fragment()
        if pet:
            used = sum(len(text) for _style, text in frags) + len(pet[1])
            frags.append(("class:status", " " * max(1, width - used)))
            frags.append(pet)
        return UIContent(get_line=lambda _i: frags, line_count=1, show_cursor=False)


def _border_class(engine, composer) -> str:
    try:
        focused = get_app().layout.has_focus(composer)
    except Exception:
        focused = True
    if focused and not engine.busy:
        return "class:composer.active"
    return "class:composer.idle"


def _install_oscura_composer(engine) -> None:
    """Turn xli's full-width rule into a rounded composer. The harness stays put.

    xli builds the dock inside ``Engine._build_app`` and does not theme the box,
    so this wraps that method and dresses the windows it returns.
    """
    original = engine._build_app

    def build():
        app = original()
        _dress_composer(app, engine)
        return app

    engine._build_app = build


def _dress_composer(app, engine) -> None:
    root = app.layout.container
    children = getattr(root, "children", None)
    if not isinstance(children, list) or len(children) < 5:
        return
    composer = children[2]
    control = getattr(composer, "content", None)
    if not isinstance(control, BufferControl):
        return

    def border() -> str:
        return _border_class(engine, composer)

    glyph = engine.theme.prompt_glyph or "❯"

    def prefix(line: int, wrap_count: int):
        if line == 0 and wrap_count == 0:
            return [("class:prompt", f" {glyph} ")]
        return [("", " " * (len(glyph) + 2))]

    composer.get_line_prefix = prefix
    composer.left_margins = [_Rail(border)]
    composer.right_margins = [_Rail(border)]
    processors = list(control.input_processors or [])
    processors.append(_Placeholder())
    control.input_processors = processors

    children[1] = Window(content=_Rule("╭", "╮"), height=1, style=border)
    children.insert(3, Window(content=_Rule("╰", "╯"), height=1, style=border))
    status = children[5] if len(children) > 5 else None
    if isinstance(status, Window):
        status.content = _QuietStatus(engine)

    app.style = PtStyle(
        list(app.style.style_rules)
        + [
            ("composer.idle", BORDER),
            ("composer.active", BORDER_ACTIVE),
            ("placeholder", SUBTLE),
        ]
    )
    # xli leaves prompt_toolkit on 256 colors, which muddies these hexes.
    # True color unless the user asked for no color.
    if not os.environ.get("NO_COLOR"):
        app._color_depth = ColorDepth.TRUE_COLOR


def _session_console() -> Console:
    """Banner colors stay on the Oscura hexes when the terminal can take them."""
    if sys.stdout.isatty() and not os.environ.get("NO_COLOR"):
        return Console(color_system="truecolor")
    return Console()


def _paint_canvas() -> None:
    """OSC 11 / OSC 10 — near-black canvas, Oscura text. Reset on the way out."""
    sys.stdout.write(f"\033]11;{BASE}\a\033]10;{TEXT}\a")
    sys.stdout.flush()


def _reset_canvas() -> None:
    sys.stdout.write("\033]111\a\033]110\a")
    sys.stdout.flush()


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
    tty = sys.stdout.isatty()
    if tty:
        _paint_canvas()
    engine = getattr(ui, "_engine", None)
    if engine is not None:
        _install_oscura_composer(engine)
    try:
        _session_console().print(
            _banner(workspace, len(skills), len(list_tool_names(workspace)))
        )
        ui.run()
    finally:
        if tty:
            _reset_canvas()
