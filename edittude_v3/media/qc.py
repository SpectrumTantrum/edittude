from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from edittude_v3.media.core import ffmpeg, write_json
from edittude_v3.media.inventory import describe_clip

# One copy of the detector settings. first_cut imports these; do not duplicate them.
SILENCE_DETECT = "silencedetect=n=-38dB:d=1.2"
BLACK_DETECT = "blackdetect=d=0.2:pix_th=0.10"
FREEZE_DETECT = "freezedetect=n=-55dB:d=1.4"


def review(video: Path) -> dict[str, Any]:
    if not video.is_file():
        raise FileNotFoundError(video)
    meta = describe_clip(video)
    result = ffmpeg(
        [
            "-i",
            str(video),
            "-af",
            f"{SILENCE_DETECT},ebur128=peak=true:framelog=verbose",
            "-vf",
            f"{BLACK_DETECT},{FREEZE_DETECT}",
            "-f",
            "null",
            "-",
        ],
        capture=True,
    )
    log = (result.stderr or "") + "\n" + (result.stdout or "")
    spans = detector_spans(log)
    black = spans["black"]
    silence = spans["silence"]
    freeze = spans["freeze"]
    loudness = _parse_loudness(log)
    duration = float(meta.get("duration") or 0)
    issues: list[str] = []
    if duration < 3:
        issues.append("shorter than 3 seconds")
    if not meta.get("has_audio"):
        issues.append("no audio stream")
    if not meta.get("has_video"):
        issues.append("no video stream")
    if black:
        issues.append(f"{len(black)} black span(s)")
    if silence:
        issues.append(f"{len(silence)} long silence(s)")
    if freeze:
        issues.append(f"{len(freeze)} freeze(s)")
    if loudness.get("I") is not None and abs(loudness["I"] + 16) > 3.5:
        issues.append(f"integrated loudness {loudness['I']} LUFS, want about -16")
    report = {
        "path": str(video.resolve()),
        "duration": duration,
        "width": meta.get("width"),
        "height": meta.get("height"),
        "fps": meta.get("fps"),
        "video_codec": meta.get("video_codec"),
        "audio_codec": meta.get("audio_codec"),
        "size_bytes": meta.get("size_bytes"),
        "has_video": meta.get("has_video"),
        "has_audio": meta.get("has_audio"),
        "black": black,
        "silence": silence,
        "freeze": freeze,
        "loudness": loudness,
        "issues": issues,
        "pass": not issues,
    }
    return report


def write_review(video: Path, out: Path) -> dict[str, Any]:
    report = review(video)
    write_json(out, report)
    return report


def detector_spans(log: str) -> dict[str, list[dict[str, float]]]:
    """Black, freeze, and silence spans from one ffmpeg detector log."""
    return {
        "black": _paired_spans(log, "black_start:", "black_end:"),
        "silence": _paired_spans(log, "silence_start:", "silence_end:"),
        "freeze": _paired_spans(log, "freeze_start:", "freeze_end:"),
    }


def _paired_spans(log: str, start_key: str, end_key: str) -> list[dict[str, float]]:
    starts = [float(m.group(1)) for m in re.finditer(rf"{re.escape(start_key)}\s*([0-9.]+)", log)]
    ends = [float(m.group(1)) for m in re.finditer(rf"{re.escape(end_key)}\s*([0-9.]+)", log)]
    spans: list[dict[str, float]] = []
    for index, start in enumerate(starts):
        end = ends[index] if index < len(ends) else start
        spans.append({"start": start, "end": end})
    return spans


def _parse_loudness(log: str) -> dict[str, float | None]:
    def grab(label: str) -> float | None:
        match = re.search(rf"{label}:\s+(-?[0-9.]+)", summary)
        return float(match.group(1)) if match else None

    # ebur128 summary uses "I:", "LRA:", and "Peak:" under "True peak:".
    summary = log
    if "Summary:" in log:
        summary = log[log.rfind("Summary:") :]
    return {
        "I": grab("I"),
        "LRA": grab("LRA"),
        "TP": grab(r"True peak:\s+Peak"),
        "thresh": grab("Threshold"),
        "summary": bool("Summary:" in log),
    }
