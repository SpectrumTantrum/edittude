from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

VIDEO_EXTS = {".mov", ".mp4", ".m4v", ".mkv", ".avi", ".webm", ".ogv"}
AUDIO_EXTS = {".m4a", ".aac", ".wav", ".mp3", ".aiff", ".aif", ".flac", ".ogg"}
SKIP_DIRS = {
    ".edittude",
    ".edittude-v3",
    ".git",
    ".venv",
    "__pycache__",
    "artifacts",
    "cache",
    "dataset",
}

ASPECTS: dict[str, tuple[int, int]] = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
}

LOOKS: dict[str, str] = {
    "neutral": "eq=contrast=1.03:saturation=1.05:gamma=1.0",
    "warm": (
        "eq=contrast=1.06:saturation=1.10:gamma=1.02,"
        "colorbalance=rs=0.06:gs=-0.01:bs=-0.05:rm=0.03:bm=-0.03"
    ),
    "cool": (
        "eq=contrast=1.05:saturation=1.06:gamma=1.0,"
        "colorbalance=rs=-0.04:bs=0.06:rm=-0.02:bm=0.03"
    ),
    "teal-orange": (
        "eq=contrast=1.08:saturation=1.12:gamma=1.01,"
        "colorbalance=rs=0.08:gs=-0.02:bs=-0.06:rm=0.04:bm=-0.02"
    ),
}

FONT_CANDIDATES = [
    Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    Path("/Library/Fonts/Arial Bold.ttf"),
    Path("/Library/Fonts/Arial.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
]


class MediaError(RuntimeError):
    pass


def which(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise MediaError(f"{name} is not on PATH. Install ffmpeg.")
    return path


def parse_fps(rate: str | None) -> float:
    if not rate or rate in {"0/0", "0"}:
        return 0.0
    if "/" in rate:
        num, den = rate.split("/", 1)
        try:
            denom = float(den)
        except ValueError:
            return 0.0
        return float(num) / denom if denom else 0.0
    try:
        return float(rate)
    except ValueError:
        return 0.0


def write_json(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MediaError(f"{path}: not valid JSON: {exc}") from exc
    except OSError as exc:
        raise MediaError(f"{path}: {exc.strerror}") from exc


def find_font() -> Path:
    for candidate in FONT_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise MediaError("No drawtext font found. Install Arial or DejaVu.")


def escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace(":", "\\:")
        .replace("%", "%%")
    )


def run(
    cmd: list[str],
    *,
    check: bool = True,
    capture: bool = False,
    timeout: float | None = 3600,
) -> subprocess.CompletedProcess[str]:
    printable = " ".join(cmd)
    print(f"+ {printable}", file=sys.stderr)
    try:
        result = subprocess.run(
            cmd,
            check=False,
            text=True,
            capture_output=capture,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"command timed out after {timeout}s: {printable}") from exc
    if check and result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip() or "(see ffmpeg output above)"
        raise MediaError(f"command failed ({result.returncode}): {printable}\n{err}")
    return result


def ffprobe(path: Path) -> dict[str, Any]:
    cmd = [
        which("ffprobe"),
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-show_entries",
        "stream_tags=rotate:format_tags=creation_time,com.apple.quicktime.creationdate",
        "-of",
        "json",
        str(path),
    ]
    result = run(cmd, capture=True)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaError(f"ffprobe returned invalid JSON for {path}") from exc


def ffmpeg(args: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return run([which("ffmpeg"), "-hide_banner", "-y", *args], capture=capture)
