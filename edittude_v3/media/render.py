from __future__ import annotations

import math
from pathlib import Path

from edittude_v3.media.core import (
    ASPECTS,
    LOOKS,
    MediaError,
    ffmpeg,
    run,
    which,
)
from edittude_v3.media.edl import EditDecision, Event
from edittude_v3.media.inventory import describe_clip
from edittude_v3.media.titlecard import write_title_png


def scale_filter(
    width: int,
    height: int,
    fit: str = "pad",
    zoom: float = 1.0,
    cx: float = 0.5,
    cy: float = 0.5,
    fps: int | None = 30,
    reset_pts: bool = True,
) -> str:
    if fit == "pad":
        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
    elif fit == "crop":
        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )
    else:
        raise MediaError(f"unknown fit {fit}. use pad or crop")
    if zoom > 1:
        vf = (
            f"crop=iw/{zoom:g}:ih/{zoom:g}:"
            f"min(max(iw*{cx:g}-iw/{zoom:g}/2\\,0)\\,iw-iw/{zoom:g}):"
            f"min(max(ih*{cy:g}-ih/{zoom:g}/2\\,0)\\,ih-ih/{zoom:g}),"
            + vf
        )
    if fps is not None:
        vf += f",fps={fps}"
    # Segments restart at 0 for concat. A whole-file filter must not: its audio is copied as is.
    pts = ",setpts=PTS-STARTPTS" if reset_pts else ""
    return vf + f",setsar=1{pts},format=yuv420p"


def assemble(edl: EditDecision, out: Path, work_dir: Path) -> Path:
    if not edl.events:
        raise MediaError("EDL has no events")
    work_dir.mkdir(parents=True, exist_ok=True)
    width, height = edl.width, edl.height
    segments: list[Path] = []
    for index, event in enumerate(edl.events):
        dest = work_dir / f"seg_{index:03d}.mp4"
        _encode_event(event, dest, width, height, edl.fit, fps=int(edl.fps or 30))
        segments.append(dest)
    listing = work_dir / "concat.txt"
    lines = ["file '" + str(seg.resolve()).replace("'", "'\\''") + "'" for seg in segments]
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(
        [
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-c:v",
            "copy",
            "-af",
            "aresample=async=1:first_pts=0,aformat=sample_rates=48000:channel_layouts=stereo",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(out),
        ]
    )
    return out


def _encode_event(event: Event, dest: Path, width: int, height: int, fit: str = "pad", fps: int = 30) -> None:
    src = Path(event.src)
    if not src.is_file():
        raise MediaError(f"missing source {src}")
    duration = event.duration()
    if duration <= 0.04:
        raise MediaError(f"event too short: {event}")
    # The concat demuxer offsets each segment by its container duration, so a segment whose
    # audio outruns its picture opens a gap per cut and drags the joined frame rate off fps.
    frames = max(1, round(duration * fps))
    duration = math.floor(frames / fps * 1e6) / 1e6
    clip = describe_clip(src)
    vf = scale_filter(width, height, fit=fit, zoom=event.zoom, cx=event.cx, cy=event.cy, fps=fps)
    args = [
        "-ss",
        f"{event.in_point:.3f}",
        "-i",
        str(src),
    ]
    if not clip.get("has_audio"):
        args += [
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
        ]
    args += [
        "-t",
        f"{duration:.6f}",
        "-map",
        "0:v:0",
        "-vf",
        vf,
        "-frames:v",
        str(frames),
        "-video_track_timescale",
        str(fps),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
    ]
    if clip.get("has_audio"):
        args += [
            "-map",
            "0:a:0",
            "-af",
            "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
        ]
    else:
        args += [
            "-map",
            "1:a:0",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
        ]
    args += ["-movflags", "+faststart", str(dest)]
    ffmpeg(args)


def mix(
    video: Path,
    out: Path,
    *,
    voiceover: Path | None = None,
    music: Path | None = None,
    amb_db: float = -16.0,
    music_db: float = -22.0,
) -> Path:
    if not video.is_file():
        raise MediaError(f"missing video {video}")
    out.parent.mkdir(parents=True, exist_ok=True)
    if voiceover is None and music is None:
        ffmpeg(
            [
                "-i",
                str(video),
                "-af",
                "loudnorm=I=-16:TP=-1.5:LRA=11,aformat=sample_rates=48000:channel_layouts=stereo",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "48000",
                "-movflags",
                "+faststart",
                str(out),
            ]
        )
        return out

    inputs = ["-i", str(video)]
    filters: list[str] = []
    mix_labels: list[str] = []
    next_index = 1
    picture = describe_clip(video)
    if picture.get("has_audio"):
        filters.append(f"[0:a]volume={_db(amb_db)}[amb]")
        mix_labels.append("[amb]")
    if voiceover is not None:
        inputs += ["-i", str(voiceover)]
        filters.append(
            f"[{next_index}:a]loudnorm=I=-16:TP=-1.5:LRA=11,"
            "aformat=sample_rates=48000:channel_layouts=stereo[vo]"
        )
        mix_labels.append("[vo]")
        next_index += 1
    if music is not None:
        inputs += ["-i", str(music)]
        filters.append(f"[{next_index}:a]volume={_db(music_db)},aformat=channel_layouts=stereo[mus]")
        mix_labels.append("[mus]")
    n = len(mix_labels)
    if n == 0:
        raise MediaError("mix has no audio inputs")
    if n == 1:
        filters.append(
            f"{mix_labels[0]}loudnorm=I=-16:TP=-1.5:LRA=11,"
            "aformat=sample_rates=48000:channel_layouts=stereo[a]"
        )
    else:
        joined = "".join(mix_labels)
        filters.append(
            f"{joined}amix=inputs={n}:duration=first:dropout_transition=0.4,"
            "loudnorm=I=-16:TP=-1.5:LRA=11,aformat=sample_rates=48000:channel_layouts=stereo[a]"
        )
    ffmpeg(
        [
            *inputs,
            "-filter_complex",
            ";".join(filters),
            "-map",
            "0:v:0",
            "-map",
            "[a]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(out),
        ]
    )
    return out


def grade(video: Path, out: Path, look: str = "warm") -> Path:
    vf = LOOKS.get(look) or LOOKS["warm"]
    return _video_filter(video, out, vf)


def titles(
    video: Path,
    out: Path,
    *,
    title: str,
    subtitle: str = "",
    hold: float = 3.1,
) -> Path:
    if not title.strip():
        return _copy(video, out)
    if not video.is_file():
        raise MediaError(f"missing video {video}")
    meta = describe_clip(video)
    width = int(meta.get("display_width") or 1920)
    height = int(meta.get("display_height") or 1080)
    card = out.parent / "title-card.png"
    write_title_png(card, title, width=width, height=height, subtitle=subtitle)
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(
        [
            "-i",
            str(video),
            "-loop",
            "1",
            "-t",
            f"{hold + 1:.2f}",
            "-i",
            str(card),
            "-filter_complex",
            _title_overlay(hold),
            "-map",
            "[v]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(out),
        ]
    )
    return out


def _title_overlay(hold: float = 3.1, *, base: str = "[0:v]", card: str = "[1:v]") -> str:
    end = 0.35 + hold
    return (
        f"{card}format=rgba,fade=t=in:st=0.35:d=0.40:alpha=1,"
        f"fade=t=out:st={end - 0.40:.2f}:d=0.40:alpha=1[ttl];"
        f"{base}[ttl]overlay=0:0:eof_action=pass[v]"
    )


def burn_srt(video: Path, out: Path, srt: Path) -> Path:
    if not srt.is_file():
        raise MediaError(f"missing captions {srt}")
    # Homebrew ffmpeg is often built without libass. Fail clearly.
    probe = run([which("ffmpeg"), "-hide_banner", "-filters"], capture=True, check=False)
    listing = (probe.stdout or "") + (probe.stderr or "")
    if "subtitles" not in listing:
        raise MediaError(
            "this ffmpeg has no subtitles filter. burn a title card or install ffmpeg with libass."
        )
    vf = f"subtitles={_escape_filter_path(srt)}:force_style='Fontsize=22,Outline=1,Shadow=0'"
    return _video_filter(video, out, vf)


def reframe(video: Path, out: Path, aspect: str, fit: str = "crop") -> Path:
    if aspect not in ASPECTS:
        raise MediaError(f"unknown aspect {aspect}. use {', '.join(ASPECTS)}")
    width, height = ASPECTS[aspect]
    return _video_filter(video, out, scale_filter(width, height, fit=fit, fps=None, reset_pts=False))


def finish(
    picture: Path,
    out: Path,
    *,
    edl: EditDecision,
    voiceover: Path | None = None,
    music: Path | None = None,
) -> Path:
    """One encode: grade, title, mix. Avoids stacking generations."""
    if not picture.is_file():
        raise MediaError(f"missing picture {picture}")
    look = LOOKS.get(edl.look) or LOOKS["warm"]
    vo = Path(voiceover) if voiceover else (Path(edl.voiceover) if edl.voiceover else None)
    mus = Path(music) if music else (Path(edl.music) if edl.music else None)
    inputs = ["-i", str(picture)]
    next_index = 1
    filters = [f"[0:v]{look}[base]"]
    video_out = "[base]"
    if edl.title.strip():
        card = out.parent / "title-card.png"
        write_title_png(
            card,
            edl.title,
            width=edl.width,
            height=edl.height,
            subtitle=edl.subtitle,
        )
        inputs += ["-loop", "1", "-t", "4", "-i", str(card)]
        filters.append(
            f"[{next_index}:v]format=rgba,fade=t=in:st=0.35:d=0.40:alpha=1,"
            "fade=t=out:st=3.05:d=0.40:alpha=1[ttl]"
        )
        filters.append("[base][ttl]overlay=0:0:eof_action=pass[v]")
        video_out = "[v]"
        next_index += 1
    else:
        video_out = "[base]"

    mix_labels: list[str] = []
    picture_meta = describe_clip(picture)
    if picture_meta.get("has_audio"):
        filters.append("[0:a]volume=0.16[amb]")
        mix_labels.append("[amb]")
    if vo and vo.is_file():
        inputs += ["-i", str(vo)]
        filters.append(
            f"[{next_index}:a]loudnorm=I=-16:TP=-1.5:LRA=11,"
            "aformat=sample_rates=48000:channel_layouts=stereo[vo]"
        )
        mix_labels.append("[vo]")
        next_index += 1
    if mus and mus.is_file():
        inputs += ["-i", str(mus)]
        filters.append(f"[{next_index}:a]volume=0.08,aformat=channel_layouts=stereo[mus]")
        mix_labels.append("[mus]")
    if mix_labels:
        if len(mix_labels) == 1:
            filters.append(
                f"{mix_labels[0]}loudnorm=I=-16:TP=-1.5:LRA=11,"
                "aformat=sample_rates=48000:channel_layouts=stereo[a]"
            )
        else:
            filters.append(
                f"{''.join(mix_labels)}amix=inputs={len(mix_labels)}:duration=first:"
                "dropout_transition=0.4,loudnorm=I=-16:TP=-1.5:LRA=11,"
                "aformat=sample_rates=48000:channel_layouts=stereo[a]"
            )
        map_audio = ["-map", "[a]"]
    else:
        map_audio = []
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(
        [
            *inputs,
            "-filter_complex",
            ";".join(filters),
            "-map",
            video_out,
            *map_audio,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(out),
        ]
    )
    return out


def grab_frames(video: Path, out_dir: Path, fractions: tuple[float, ...] = (0.05, 0.25, 0.5, 0.75, 0.95)) -> list[Path]:
    meta = describe_clip(video)
    duration = float(meta.get("duration") or 0)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []
    for frac in fractions:
        t = min(max(duration * frac, 0.05), max(duration - 0.05, 0.05))
        dest = out_dir / f"t{int(frac * 100):02d}.jpg"
        ffmpeg(
            [
                "-ss",
                f"{t:.3f}",
                "-i",
                str(video),
        "-frames:v",
        "1",
        "-update",
        "1",
        "-q:v",
        "3",
        str(dest),
            ]
        )
        frames.append(dest)
    return frames


def _video_filter(video: Path, out: Path, vf: str) -> Path:
    if not video.is_file():
        raise MediaError(f"missing video {video}")
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(
        [
            "-i",
            str(video),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(out),
        ]
    )
    return out


def _copy(video: Path, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    if video.resolve() == out.resolve():
        return out
    ffmpeg(["-i", str(video), "-c", "copy", "-movflags", "+faststart", str(out)])
    return out


def _db(db: float) -> str:
    return f"{10 ** (db / 20):.4f}"


def _escape_filter_path(path: Path) -> str:
    text = str(path.resolve())
    # ffmpeg unescapes the filtergraph first, then the filter option, so escape
    # for the option level first and for the filtergraph around it second.
    for special in ("\\':=", "\\'[],;"):
        text = "".join("\\" + char if char in special else char for char in text)
    return text
