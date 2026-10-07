from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import dotenv_values, load_dotenv, set_key, unset_key
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, LocalShellBackend

from edittude_v3.deepseek_vision import DEEPSEEK_PROFILE, DeepSeekImageMiddleware
from edittude_v3.paths import PACKAGE_ROOT, env_file, install_root, legacy_env_file, state_dir
from edittude_v3.skills import skill_dirs
from edittude_v3.subagents import video_subagents
from edittude_v3.tools import load_workspace_tools

MODEL = "deepseek:deepseek-flash"
MODEL_LABEL = "DeepSeek Flash"
API_KEY_ENV = "DEEPSEEK_API_KEY"
API_KEY_URL = "https://platform.deepseek.com"
DEFAULT_RECURSION_LIMIT = 400
# `edittude config` names -> variables in env_file(). Defaults shown are what runs when unset.
SETTINGS = {
    "model": ("EDITTUDE_MODEL", MODEL),
    "vision-url": ("EDITTUDE_VISION_URL", "http://localhost:1234/v1"),
    "vision-model": ("EDITTUDE_VISION_MODEL", "qwen/qwen3.8-27b"),
    "vision-api-key": ("EDITTUDE_VISION_API_KEY", ""),
    "recursion-limit": ("EDITTUDE_RECURSION_LIMIT", str(DEFAULT_RECURSION_LIMIT)),
}
_API_KEY_LINE = re.compile(rf"^(?:export\s+)?{API_KEY_ENV}=.*$\n?", re.MULTILINE)

SYSTEM_PROMPT = """You are edittude, a local cutter.

The user gives you a footage folder and a brief, or just a folder. You make a cut.
You do not wait for an EDL. You do not ask twenty questions. Defaults:

- delivery matches the source frame, 30fps, hard cuts
- chronology is the spine unless the brief names a different structure
- if a voiceover file exists, picture fits that duration and ambient ducks under it
- warm grade, one opening title if you have a name, about -16 LUFS
- write outputs next to the source under artifacts/ or a path they name
- never copy huge media into the git repo

House style: cut the day, don't illustrate it. One idea per shot. Get in late,
get out early. Alternate wide, person, detail. Cap screen recordings and static
holds. Dissolves are for when you failed to find the cut.

Framing: `--aspect source` is the default, so the canvas is the display
resolution of the clip carrying the most screen time. Vertical footage
delivers vertical, horizontal delivers horizontal. The shooter already chose
the frame, and changing aspect throws picture away, so change it only when the
brief names a delivery format: 16:9, 9:16, 1:1. Off-aspect clips sit padded on
the canvas, `fit` is `"pad"`; `"crop"` fills and center-crops, and you pick it
when the brief wants edge-to-edge. In a mixed-orientation folder the canvas
follows the dominant footage and the minority pads, unless a crop of those
shots genuinely reads better. Read `display_width`/`display_height` from the
inventory, not the coded width/height, which are pre-rotation.

Crop is still an editor's tool, at the event level. A punch-in is `zoom` on
an event, 1.0 to 4.0, with `cx`/`cy` between 0 and 1 for the focus point
(default center). It earns its place when it does work: emphasis on a line or
a reaction, a second angle out of one take so a jump cut reads, reframing dead
space or a distraction out of a shot, a push on a detail, hitting a beat. It
is an upscale, so stay near 1.3-1.5x on 1080p sources and go harder only with
4K headroom. Look at a frame before choosing cx/cy so the subject is inside
the window you asked for.

Workflow:
1. Read the matching skill under ./skills/. Start with zero-shot-cut when they
   want an edit from a folder.
2. ls the folder they named. Absolute paths are real.
3. Inventory with `edittude media`. Do not invent ffmpeg
   graphs when a subcommand exists.
4. Plan an EDL, assemble, finish, QC, recut if QC fails.
5. A cut is not done until the output file exists on disk. Run the media CLI.
   Do not stop at a command list. Then reply with the path, duration, and what
   you chose. Short.

Delegate with the task tool when it helps: inventory, editor, mixer, qc.
The general-purpose subagent is for leftover work, not for hiding from a cut.

You can see images. read_file on a jpg or png attaches the real image. Each one
costs up to 1024 tokens, so extract a contact sheet and read that rather than every
frame. image_describe stays available for bulk local description. Look before you
write the EDL: reasons come from what is in the shot, matched to what the voiceover says.

You have a local shell. ffmpeg and ffprobe work. virtual_mode is off on purpose.

The registered portable media tools are also available. Call get_capabilities to
check dependencies before using them. Their paths are workspace-relative:
/clips/input.mp4 means clips/input.mp4 in this project. Built-in filesystem and
shell tools use host paths. Resolve returned media paths against the project
directory before opening them with filesystem tools. Use the existing media CLI
for footage outside the workspace. Keep originals intact and verify outputs.
"""


def model_name() -> str:
    return os.getenv("EDITTUDE_MODEL", "").strip() or MODEL


def model_label() -> str:
    return MODEL_LABEL if model_name() == MODEL else model_name()


def _env_has_values(path: Path) -> bool:
    if not path.is_file():
        return False
    return any(str(value or "").strip() for value in dotenv_values(path).values())


def adopt_legacy_config() -> None:
    """Copy ~/.config/edittude-v3/.env into ~/.config/edittude/ when the new file is empty.

    The old file is left in place. Once the new file has any setting, it wins.
    A new file that already has other settings still receives a missing API key.
    EDITTUDE_CONFIG_HOME disables the lookup.
    """
    legacy = legacy_env_file()
    if legacy is None or not legacy.is_file():
        return
    dest = env_file()
    if dest.is_file() and _env_has_values(dest):
        if not _key_from_file(dest) and (key := _key_from_file(legacy)):
            save_api_key(key, dest)
        return
    text = legacy.read_text(encoding="utf-8")
    if not text.strip():
        return
    if not text.endswith("\n"):
        text += "\n"
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        dest.chmod(0o600)
    except OSError:
        return


def get_settings() -> dict[str, str]:
    adopt_legacy_config()
    saved = dotenv_values(env_file()) if env_file().is_file() else {}
    return {name: os.getenv(var) or saved.get(var) or default for name, (var, default) in SETTINGS.items()}


def set_setting(name: str, value: str | None) -> None:
    """Persist to env_file(); value None restores the default."""
    adopt_legacy_config()
    var = SETTINGS[name][0]
    if name == "recursion-limit" and value is not None:
        try:
            if int(value) <= 0:
                raise ValueError
        except ValueError:
            raise ValueError("recursion-limit must be a positive integer") from None
    path = env_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600)
    if value is None:
        unset_key(path, var)
        os.environ.pop(var, None)
    else:
        set_key(path, var, value)
        os.environ[var] = value
    path.chmod(0o600)  # touch() is a no-op on an existing file and set_key keeps its mode.


def default_workspace() -> Path:
    return Path.cwd().resolve()


def _key_from_file(path: Path) -> str:
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("export "):
            stripped = stripped[7:].strip()
        if stripped.startswith(f"{API_KEY_ENV}="):
            return normalize_api_key(stripped)
    return ""


def _legacy_env_files() -> list[Path]:
    home = env_file().resolve()
    found: list[Path] = []
    seen: set[Path] = {home}
    for path in (install_root() / ".env", PACKAGE_ROOT / ".env"):
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        found.append(path)
    return found


def load_env() -> None:
    adopt_legacy_config()
    path = env_file()
    load_dotenv(path)
    if configured_api_key():
        return
    candidates: list[Path] = []
    legacy = legacy_env_file()
    if legacy is not None:
        candidates.append(legacy)
    candidates.extend(_legacy_env_files())
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        key = _key_from_file(candidate)
        if not key:
            continue
        try:
            save_api_key(key, path)
        except OSError:
            os.environ[API_KEY_ENV] = key
        return


def configured_api_key() -> str:
    return os.getenv(API_KEY_ENV, "").strip()


def normalize_api_key(raw: str) -> str:
    """Accept sk-…, KEY=sk-…, export KEY=sk-…, and any of those quoted."""
    key = raw.strip()
    if key.startswith("export "):
        key = key[len("export "):].strip()
    prefix = f"{API_KEY_ENV}="
    if key.startswith(prefix):
        key = key[len(prefix):].strip()
    return key.strip("'\"")


def save_api_key(key: str, path: Path | None = None) -> Path:
    key = normalize_api_key(key)
    if not key:
        raise ValueError("API key is empty")
    path = path or env_file()
    line = f"{API_KEY_ENV}={key}"
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        if match := _API_KEY_LINE.search(text):
            text = text[:match.start()] + line + "\n" + _API_KEY_LINE.sub("", text[match.end():])
        else:
            text = text.rstrip("\n")
            text = f"{text}\n{line}" if text else line
        if not text.endswith("\n"):
            text += "\n"
        path.write_text(text, encoding="utf-8")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(line + "\n", encoding="utf-8")
    path.chmod(0o600)
    os.environ[API_KEY_ENV] = key
    return path


def require_api_key() -> None:
    if configured_api_key():
        return
    raise SystemExit(
        f"{API_KEY_ENV} is missing. Run edittude in a terminal to paste a key, "
        f"or add it to {env_file()}."
    )


def build_backend(workspace: Path) -> CompositeBackend:
    """Real host paths for the agent, project-local scratch for offloaded history.

    virtual_mode is off so /Users/... paths are real, which also makes deepagents'
    default artifacts_root of "/" a literal write to the read-only macOS root.
    """
    return CompositeBackend(
        default=LocalShellBackend(
            root_dir=workspace,
            virtual_mode=False,
            inherit_env=True,
            timeout=600,
        ),
        routes={},
        artifacts_root=str(state_dir(workspace)),
    )


def build_agent(*, workspace: Path | None = None, model: BaseChatModel | None = None):
    workspace = (workspace or default_workspace()).expanduser().resolve()
    if model is None:
        deepseek = model_name().startswith("deepseek:")
        if deepseek:
            require_api_key()
        model = init_chat_model(model_name(), **({"profile": DEEPSEEK_PROFILE} if deepseek else {}))
    backend = build_backend(workspace)

    memory_files: list[str] = []
    for path in (install_root() / "AGENTS.md", workspace / "AGENTS.md"):
        if not path.is_file():
            continue
        resolved = str(path.resolve())
        if resolved not in memory_files:
            memory_files.append(resolved)
    memory = memory_files or None
    skills = [str(path) for path in skill_dirs(workspace)] or None
    subagents = [{**spec, "skills": skills or []} for spec in video_subagents()]

    return create_deep_agent(
        model=model,
        tools=load_workspace_tools(workspace),
        system_prompt=SYSTEM_PROMPT + f"\nProject directory: {workspace}\n",
        memory=memory,
        skills=skills,
        backend=backend,
        subagents=subagents,
        middleware=[DeepSeekImageMiddleware()],
        checkpointer=InMemorySaver(),
        name="edittude",
    )
