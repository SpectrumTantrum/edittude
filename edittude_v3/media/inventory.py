from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from edittude_v3.media.core import (
    AUDIO_EXTS,
    SKIP_DIRS,
    VIDEO_EXTS,
    MediaError,
    ffmpeg,
    ffprobe,
    parse_fps,
    write_json,
)


def iter_media(folder: Path) -> list[Path]:
    root = folder.expanduser().resolve()
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if any(part in SKIP_DIRS for part in rel.parts[:-1]):
            continue
        if path.suffix.lower() in VIDEO_EXTS | AUDIO_EXTS:
            found.append(path)
    return found


def _stream(probe: dict[str, Any], kind: str) -> dict[str, Any]:
    for stream in probe.get("streams") or []:
        if stream.get("codec_type") == kind:
            return stream
    return {}


def _rotation(video: dict[str, Any], probe: dict[str, Any]) -> int:
    tags = video.get("tags") or {}
    if tags.get("rotate"):
        try:
            return int(float(tags["rotate"]))
        except ValueError:
            pass
    for side in video.get("side_data_list") or []:
        if "rotation" in side:
            try:
                return int(float(side["rotation"]))
            except (TypeError, ValueError):
                pass
    fmt_tags = (probe.get("format") or {}).get("tags") or {}
    if fmt_tags.get("rotate"):
        try:
            return int(float(fmt_tags["rotate"]))
        except ValueError:
            return 0
    return 0


def describe_clip(path: Path) -> dict[str, Any]:
    probe = ffprobe(path)
    fmt = probe.get("format") or {}
    video = _stream(probe, "video")
    audio = _stream(probe, "audio")
    suffix = path.suffix.lower()
    kind = "video" if suffix in VIDEO_EXTS else "audio"
    duration = float(fmt.get("duration") or video.get("duration") or audio.get("duration") or 0)
    rotation = _rotation(video, probe)
    display_width, display_height = video.get("width"), video.get("height")
    if abs(rotation) % 180 == 90:
        display_width, display_height = display_height, display_width
    return {
        "path": str(path.resolve()),
        "name": path.name,
        "kind": kind,
        "duration": duration,
        "width": video.get("width"),
        "height": video.get("height"),
        "display_width": display_width,
        "display_height": display_height,
        "fps": parse_fps(video.get("r_frame_rate")),
        "avg_fps": parse_fps(video.get("avg_frame_rate")),
        "video_codec": video.get("codec_name"),
        "pix_fmt": video.get("pix_fmt"),
        "color_space": video.get("color_space"),
        "color_transfer": video.get("color_transfer"),
        "color_primaries": video.get("color_primaries"),
        "color_range": video.get("color_range"),
        "audio_codec": audio.get("codec_name"),
        "sample_rate": int(audio["sample_rate"]) if audio.get("sample_rate") else None,
        "channels": audio.get("channels"),
        "size_bytes": int(fmt.get("size") or path.stat().st_size),
        "bit_rate": int(fmt["bit_rate"]) if fmt.get("bit_rate") else None,
        "rotation": rotation,
        "creation_time": (fmt.get("tags") or {}).get("creation_time")
        or (fmt.get("tags") or {}).get("com.apple.quicktime.creationdate"),
        "has_video": bool(video),
        "has_audio": bool(audio),
    }


def build_inventory(folder: Path) -> dict[str, Any]:
    folder = folder.expanduser().resolve()
    if not folder.is_dir():
        raise MediaError(f"{folder}: no such footage folder")
    clips = [describe_clip(path) for path in iter_media(folder)]
    videos = [c for c in clips if c["kind"] == "video"]
    audios = [c for c in clips if c["kind"] == "audio"]
    return {
        "folder": str(folder),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "clips": clips,
        "totals": {
            "files": len(clips),
            "video": len(videos),
            "audio": len(audios),
            "video_seconds": round(sum(c["duration"] for c in videos), 3),
            "audio_seconds": round(sum(c["duration"] for c in audios), 3),
        },
    }


def write_inventory(folder: Path, out: Path) -> dict[str, Any]:
    data = build_inventory(folder)
    write_json(out, data)
    return data


def extract_thumbs(
    inventory: dict[str, Any],
    out_dir: Path,
    *,
    count: int = 3,
    width: int = 480,
) -> list[dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    positions = _thumb_positions(count)
    written: list[dict[str, Any]] = []
    fresh: set[Path] = set()
    for clip_index, clip in enumerate(inventory.get("clips") or []):
        if clip.get("kind") != "video":
            continue
        src = Path(clip["path"])
        duration = float(clip.get("duration") or 0)
        if duration <= 0 or not src.is_file():
            continue
        clip_dir = out_dir / f"{clip_index:03d}_{src.stem}"
        shutil.rmtree(clip_dir, ignore_errors=True)
        clip_dir.mkdir(parents=True, exist_ok=True)
        fresh.add(clip_dir)
        frames: list[str] = []
        for index, frac in enumerate(positions):
            t = min(max(duration * frac, 0.04), max(duration - 0.04, 0.04))
            dest = clip_dir / f"{index:02d}.jpg"
            ffmpeg(
                [
                    "-ss",
                    f"{t:.3f}",
                    "-i",
                    str(src),
                    "-frames:v",
                    "1",
                    "-update",
                    "1",
                    "-vf",
                    f"scale={width}:-2",
                    "-q:v",
                    "3",
                    str(dest),
                ]
            )
            frames.append(str(dest))
        written.append({"clip": clip["name"], "path": clip["path"], "frames": frames})
    # Clip indices shift when the folder changes; drop our own dirs that this run did not write.
    for stale in out_dir.iterdir():
        if stale not in fresh and stale.is_dir() and re.match(r"\d{3}_", stale.name):
            shutil.rmtree(stale, ignore_errors=True)
    return written


def _thumb_positions(count: int) -> list[float]:
    if count < 1:
        raise MediaError(f"thumb count must be at least 1, got {count}")
    if count == 1:
        return [0.5]
    if count == 2:
        return [0.2, 0.8]
    return [0.12 + 0.76 * index / (count - 1) for index in range(count)]
