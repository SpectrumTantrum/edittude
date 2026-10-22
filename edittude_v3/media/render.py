from __future__ import annotations

import json
import math
import re
from pathlib import Path

from edittude_v3.media.core import (
    ASPECTS,
    MediaError,
    ffmpeg,
    ffprobe,
    look_chain,
    run,
    which,
)
from edittude_v3.media.edl import EditDecision, Event
from edittude_v3.media.inventory import describe_clip
from edittude_v3.media.qc import _parse_loudness
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


# colorspace=iall names. ffprobe uses a few aliases for the same primaries.
_COLORSPACE_IALL = {
    "bt470m": "bt470m",
    "bt470bg": "bt470bg",
    "bt601-6-525": "bt601-6-525",
    "bt601-6-625": "bt601-6-625",
    "bt709": "bt709",
    "smpte170m": "smpte170m",
    "smpte240m": "smpte240m",
    "bt2020": "bt2020",
    "bt2020nc": "bt2020",
    "bt2020ncl": "bt2020",
    "bt2020c": "bt2020",
}
_UNTAGGED = {"", "unknown", "unspecified", "none"}
# Untagged frames below this height are SD (smpte170m). 720 and above are HD (bt709).
_SD_HEIGHT = 720
# Delivered loudness. alimiter catches sample peaks, so the ceiling sits at -3.5 dBFS
# and the limiter runs at 4x sample rate. Encoded true peak is measured after AAC.
LOUDNESS_I = -16.0
LOUDNESS_TP = -1.5
LOUDNESS_LRA = 11.0
LOUDNESS_LIMIT_DB = -3.5
# Picture bed under neighbouring audio, after the one program gain. A file that is
# only the bed keeps the program target instead. The aim is -35, pulled down when
# a neighbour would otherwise sit under 12 LU above the bed, and clamped so the
# one post-encode trim still leaves the bed inside -40 to -30.
BED_LUFS = -35.0
BED_CLEARANCE = 12.0
BED_MIN = -37.5
BED_MAX = -33.0
# Existing amb duck ahead of a voiceover. The linear gain is measured after it.
_AMB_LINEAR = 0.16


def _colorspace_name(value: object) -> str | None:
    key = str(value or "").strip().lower()
    if key in _UNTAGGED:
        return None
    return _COLORSPACE_IALL.get(key)


def _full_range(clip: dict) -> bool:
    pix = str(clip.get("pix_fmt") or "")
    raw_range = str(clip.get("color_range") or "").strip().lower()
    return raw_range in {"pc", "jpeg", "full"} or pix.startswith("yuvj")


def input_colorspace(clip: dict) -> tuple[str, str]:
    """Input space for a real conversion. Untagged SD is smpte170m; untagged HD is bt709."""
    named = None
    for key in ("color_space", "color_primaries", "color_transfer"):
        tag = _colorspace_name(clip.get(key))
        if tag is None:
            continue
        if tag != "bt709":
            named = tag
            break
        if named is None:
            named = tag
    if named is None:
        height = int(clip.get("height") or clip.get("display_height") or 0)
        named = "smpte170m" if 0 < height < _SD_HEIGHT else "bt709"
    irange = "pc" if _full_range(clip) else "tv"
    return named, irange


def relabel_only(clip: dict) -> bool:
    """Already bt709 and tv range: the encoder writes the labels, pixels stay put."""
    tags = [
        _colorspace_name(clip.get(key))
        for key in ("color_space", "color_primaries", "color_transfer")
    ]
    return all(tag == "bt709" for tag in tags) and not _full_range(clip)


def bt709_colorspace(clip: dict) -> str:
    """Convert into bt709, tv range, yuv420p. iall/all runs the matrix, primaries, and transfer."""
    iall, irange = input_colorspace(clip)
    return (
        f"colorspace=iall={iall}:all=bt709:irange={irange}:range=tv:format=yuv420p"
    )


def color_convert_filter(clip: dict) -> str | None:
    """colorspace conversion for a re-encode. None when the clip is already bt709."""
    if relabel_only(clip):
        return None
    return bt709_colorspace(clip)


# One bed for a clip with no audio stream: pink noise at -45 LUFS.
# Golden tests pin this string. Do not add another noise or level.
AUDIO_BED = "anoisesrc=color=pink:r=48000:a=1:s=1,loudnorm=I=-45"


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
    # Convert before the stream copy. Identical tags keep ffmpeg 7 from rebuilding
    # finish's filter graph after the title card has already ended. A clip that is
    # already bt709 is only relabeled by the encoder flags below.
    convert = color_convert_filter(clip)
    if convert:
        suffix = ",format=yuv420p"
        if vf.endswith(suffix):
            vf = vf[: -len(suffix)]
        vf += "," + convert
    args = [
        "-ss",
        f"{event.in_point:.3f}",
        "-i",
        str(src),
    ]
    if not clip.get("has_audio"):
        # loudnorm oversamples, so the delivery rate and layout are set after AUDIO_BED.
        args += [
            "-f",
            "lavfi",
            "-t",
            f"{duration:.6f}",
            "-i",
            f"{AUDIO_BED},aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo",
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
        "-colorspace",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-color_range",
        "tv",
        "-x264-params",
        "colorprim=bt709:transfer=bt709:colormatrix=bt709",
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
    return _video_filter(video, out, look_chain(look))


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
    probe = run([which("ffmpeg"), "-hide_banner", "-nostdin", "-filters"], capture=True, check=False)
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
    look = look_chain(edl.look)
    vo = Path(voiceover) if voiceover else (Path(edl.voiceover) if edl.voiceover else None)
    mus = Path(music) if music else (Path(edl.music) if edl.music else None)
    inputs = ["-i", str(picture)]
    next_index = 1
    picture_meta = describe_clip(picture)
    # Grade stays in the picture's space. Convert only when that space is not
    # already bt709; otherwise the encoder flags relabel the finished file.
    convert = color_convert_filter(picture_meta)
    chain = f"{look},{convert}" if convert else look
    filters = [f"[0:v]{chain}[base]"]
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
    audio_filters: list[str] = []
    if picture_meta.get("has_audio"):
        audio_filters.append(f"[0:a]volume={_AMB_LINEAR:g}[amb]")
        mix_labels.append("[amb]")
    if vo and vo.is_file():
        inputs += ["-i", str(vo)]
        audio_filters.append(
            f"[{next_index}:a]loudnorm=I={LOUDNESS_I:g}:TP={LOUDNESS_TP:g}:LRA={LOUDNESS_LRA:g},"
            "aformat=sample_rates=48000:channel_layouts=stereo[vo]"
        )
        mix_labels.append("[vo]")
        next_index += 1
    if mus and mus.is_file():
        inputs += ["-i", str(mus)]
        audio_filters.append(f"[{next_index}:a]volume=0.08,aformat=channel_layouts=stereo[mus]")
        mix_labels.append("[mus]")
    out.parent.mkdir(parents=True, exist_ok=True)
    fps = int(edl.fps or 30) or 30
    frames = _video_frame_count(picture, fps)
    seconds = frames / fps
    if mix_labels:
        if len(mix_labels) == 1:
            pre_filters = audio_filters
            pre_label = mix_labels[0]
        else:
            pre_filters = [
                *audio_filters,
                f"{''.join(mix_labels)}amix=inputs={len(mix_labels)}:duration=first:"
                "dropout_transition=0.4[pre]",
            ]
            pre_label = "[pre]"
        stats = _measure_program(
            _audio_inputs(picture, vo, mus),
            _measure_filters(picture_meta.get("has_audio"), vo, mus),
        )
        gain = None if stats is None else LOUDNESS_I - stats["input_i"]
        if gain is None or not picture_meta.get("has_audio"):
            bed_extra, bed_spans, bed_target = 0.0, [], None
        else:
            bed_extra, bed_spans, bed_target = _bed_makeup(picture, edl, gain)
        if gain is not None:
            line = f"finish gain {gain:.2f} dB"
            if bed_spans and bed_target is not None:
                line += f"; bed {bed_extra:.2f} dB at {bed_target:.1f} LUFS"
            print(line, flush=True)
        trim = 0.0
        for attempt in range(2):
            # The corrective trim is another volume on the whole program. Take it
            # back off the bed so that trim does not walk the bed out of its window
            # or close the gap to a quiet neighbour.
            delivered = _with_bed(pre_filters, bed_extra - trim, bed_spans)
            chain = _linear_chain(gain, trim, seconds)
            _encode_finish(
                inputs,
                [
                    *filters,
                    *delivered,
                    f"{pre_label}{chain},aformat=sample_rates=48000:channel_layouts=stereo[a]",
                ],
                video_out,
                ["-map", "[a]"],
                frames,
                out,
            )
            if attempt == 1:
                break
            reading = _encoded_loudness(out)
            trim = _corrective_trim(reading.get("I"), reading.get("TP"))
            if trim is None:
                break
            peak = reading.get("TP")
            integrated = reading.get("I")
            if trim < 0:
                print(
                    f"true peak {peak:.2f} dBTP over {LOUDNESS_TP:g}; retry {trim:.2f} dB",
                    flush=True,
                )
            else:
                print(
                    f"integrated {integrated:.2f} LUFS; retry {trim:.2f} dB",
                    flush=True,
                )
    else:
        _encode_finish(inputs, filters, video_out, [], frames, out)
    return out


def _audio_inputs(picture: Path, vo: Path | None, mus: Path | None) -> list[str]:
    inputs = ["-i", str(picture)]
    if vo and vo.is_file():
        inputs += ["-i", str(vo)]
    if mus and mus.is_file():
        inputs += ["-i", str(mus)]
    return inputs


def _measure_filters(has_picture_audio: bool, vo: Path | None, mus: Path | None) -> tuple[list[str], str]:
    """Same program the encode loudnorm sees, with audio inputs packed from index 0."""
    filters: list[str] = []
    labels: list[str] = []
    index = 1
    if has_picture_audio:
        filters.append(f"[0:a]volume={_AMB_LINEAR:g}[amb]")
        labels.append("[amb]")
    if vo and vo.is_file():
        filters.append(
            f"[{index}:a]loudnorm=I={LOUDNESS_I:g}:TP={LOUDNESS_TP:g}:LRA={LOUDNESS_LRA:g},"
            "aformat=sample_rates=48000:channel_layouts=stereo[vo]"
        )
        labels.append("[vo]")
        index += 1
    if mus and mus.is_file():
        filters.append(f"[{index}:a]volume=0.08,aformat=channel_layouts=stereo[mus]")
        labels.append("[mus]")
    if len(labels) == 1:
        return filters, labels[0]
    return [
        *filters,
        f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:dropout_transition=0.4[pre]",
    ], "[pre]"


def _measure_program(inputs: list[str], measured: tuple[list[str], str]) -> dict[str, float] | None:
    """Pass 1: integrated loudness of the program the encode gain will see."""
    pre_filters, pre_label = measured
    measure = (
        f"loudnorm=I={LOUDNESS_I:g}:TP={LOUDNESS_TP:g}:LRA={LOUDNESS_LRA:g}:print_format=json"
    )
    result = ffmpeg(
        [
            *inputs,
            "-filter_complex",
            ";".join([*pre_filters, f"{pre_label}{measure}[a]"]),
            "-map",
            "[a]",
            "-f",
            "null",
            "-",
        ],
        capture=True,
    )
    return _loudnorm_stats(result.stderr or "")


def _linear_chain(gain: float | None, trim: float, seconds: float) -> str:
    """One fixed gain, then the true-peak limiter, then pad to the picture length.

    loudnorm linear mode silently falls back to dynamic when the range or the
    peak will not fit, and that fallback lifts a quiet bed. The gain here is
    volume only. trim is one corrective pass after the encoded file is measured:
    negative when true peak is over the ceiling, positive when the limiter held
    the program down and the encoded peak still has room.
    """
    decibels = 0.0 if gain is None else gain
    parts = [f"volume={decibels:.2f}dB", _true_peak_limiter()]
    if abs(trim) >= 0.05:
        parts.append(f"volume={trim:.2f}dB")
    parts.append(
        "asetpts=PTS-STARTPTS,"
        f"apad=whole_dur={seconds:.6f},atrim=end={seconds:.6f},asetpts=PTS-STARTPTS"
    )
    return ",".join(parts)


def _corrective_trim(integrated: float | None, peak: float | None) -> float | None:
    """One adjustment after the encoded measure. None leaves the file as encoded."""
    if peak is not None and math.isfinite(peak) and peak > LOUDNESS_TP:
        # A trim under about 1 dB can raise the AAC true peak. Step by at
        # least 1.5 dB and aim at -3 so the re-encode stays under the ceiling.
        return min(-1.5, -3.0 - peak)
    if (
        integrated is not None
        and peak is not None
        and math.isfinite(integrated)
        and math.isfinite(peak)
        and integrated < LOUDNESS_I - 0.4
        and peak <= -3.0
    ):
        boost = min(LOUDNESS_I - integrated, -2.5 - peak, 4.0)
        if boost >= 0.05:
            return boost
    return None


def _true_peak_limiter() -> str:
    """Sample-peak ceiling at 4x rate. alimiter does not see inter-sample peaks."""
    limit = 10 ** (LOUDNESS_LIMIT_DB / 20)
    return (
        "aresample=192000,"
        f"alimiter=limit={limit:.6f}:level=false:attack=5:release=50:latency=true,"
        "aresample=48000"
    )


def _with_bed(
    filters: list[str],
    extra: float,
    spans: list[tuple[float, float]],
) -> list[str]:
    if not spans or abs(extra) < 0.05:
        return list(filters)
    enable = "+".join(f"between(t\\,{start:.6f}\\,{end:.6f})" for start, end in spans)
    needle = f"volume={_AMB_LINEAR:g}[amb]"
    insert = f"volume={_AMB_LINEAR:g},volume={extra:.2f}dB:enable='{enable}'[amb]"
    return [item.replace(needle, insert) if needle in item else item for item in filters]


def _bed_makeup(
    picture: Path,
    edl: EditDecision,
    gain: float,
) -> tuple[float, list[tuple[float, float]], float | None]:
    """Extra gain so a bed lands on its target. Omitted when the file is only a bed."""
    spans, neighbours = _timeline_ranges(edl)
    if not spans or not neighbours:
        return 0.0, [], None
    weighted: list[tuple[float, float]] = []
    for start, end in spans:
        measured = _span_integrated(picture, start, end)
        if measured is None:
            measured = -45.0
        weighted.append((end - start, measured))
    total = sum(weight for weight, _level in weighted)
    if total <= 0:
        return 0.0, [], None
    bed_i = sum(weight * level for weight, level in weighted) / total
    quietest: float | None = None
    for start, end in neighbours:
        measured = _span_integrated(picture, start, end)
        if measured is None:
            continue
        quietest = measured if quietest is None else min(quietest, measured)
    target = _bed_target(quietest, gain)
    amb = 20.0 * math.log10(_AMB_LINEAR)
    extra = target - bed_i - amb - gain
    if abs(extra) < 0.05:
        extra = 0.0
    return extra, spans, target


def _bed_target(quietest: float | None, gain: float) -> float:
    """Bed level after the program gain. -35, or lower so the quiet neighbour stays 12 LU up."""
    target = BED_LUFS
    if quietest is not None and math.isfinite(quietest) and math.isfinite(gain):
        amb = 20.0 * math.log10(_AMB_LINEAR)
        predicted = quietest + amb + gain
        target = min(target, predicted - BED_CLEARANCE)
    if not math.isfinite(target):
        target = BED_LUFS
    return min(BED_MAX, max(BED_MIN, target))


def _timeline_ranges(
    edl: EditDecision,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Bed spans and neighbour spans on the assembled frame grid."""
    fps = int(edl.fps or 30) or 30
    spans: list[tuple[float, float]] = []
    neighbours: list[tuple[float, float]] = []
    cursor = 0.0
    for event in edl.events:
        frames = max(1, round(event.duration() * fps))
        dur = frames / fps
        if event.audio == "bed":
            spans.append((cursor, cursor + dur))
        else:
            neighbours.append((cursor, cursor + dur))
        cursor += dur
    return spans, neighbours


def _span_integrated(path: Path, start: float, end: float) -> float | None:
    if end - start < 0.4:
        return None
    result = ffmpeg(
        [
            "-i",
            str(path),
            "-af",
            (
                f"atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS,"
                f"loudnorm=I={LOUDNESS_I:g}:TP={LOUDNESS_TP:g}:LRA={LOUDNESS_LRA:g}:print_format=json"
            ),
            "-f",
            "null",
            "-",
        ],
        capture=True,
    )
    stats = _loudnorm_stats(result.stderr or "")
    if stats is None:
        return None
    return stats["input_i"]


def _encoded_loudness(path: Path) -> dict[str, float | None]:
    result = ffmpeg(
        ["-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture=True,
    )
    return _parse_loudness((result.stderr or "") + (result.stdout or ""))


def _encode_finish(
    inputs: list[str],
    filters: list[str],
    video_out: str,
    map_audio: list[str],
    frames: int,
    out: Path,
) -> None:
    ffmpeg(
        [
            *inputs,
            "-filter_complex",
            ";".join(filters),
            "-map",
            video_out,
            *map_audio,
            "-frames:v",
            str(frames),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-color_range",
            "tv",
            "-x264-params",
            "colorprim=bt709:transfer=bt709:colormatrix=bt709",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(out),
        ]
    )


def _loudnorm_stats(stderr: str) -> dict[str, float] | None:
    matches = re.findall(r'\{\s*"input_i".*?\}', stderr, re.S)
    if not matches:
        return None
    try:
        data = json.loads(matches[-1])
        values = {key: float(data[key]) for key in (
            "input_i", "input_tp", "input_lra", "input_thresh", "target_offset",
        )}
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not all(math.isfinite(value) for value in values.values()):
        return None
    return values


def _video_frame_count(path: Path, fps: int) -> int:
    probe = ffprobe(path)
    stream = next(
        (item for item in probe.get("streams") or [] if item.get("codec_type") == "video"),
        {},
    )
    try:
        count = int(stream.get("nb_frames") or 0)
    except (TypeError, ValueError):
        count = 0
    if count > 0:
        return count
    duration = float((probe.get("format") or {}).get("duration") or stream.get("duration") or 0)
    return max(1, round(duration * max(fps, 1)))


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
