from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace
from fractions import Fraction
from math import isnan
from pathlib import Path
from typing import Any

from edittude_v3.media.core import ASPECTS, LOOKS, MediaError, ffmpeg, ffprobe, read_json, write_json
from edittude_v3.media.qc import BLACK_DETECT, FREEZE_DETECT, SILENCE_DETECT, detector_spans

HANDLE_IN = 0.12
HANDLE_OUT = 0.08
MAX_HOLD = 5.2
MIN_HOLD = 1.05
SCREENY_CAP = 4.0
# Interior detector hits shorter than this stay in the window. Leading hits do not.
INTERIOR_MIN = 0.5
SKIPPED_NO_CLEAN = "skipped: no clean window"
# Detector ends sometimes land a hair past a frame (AAC silence pad). Snap those back.
_SNAP_SLACK = 0.0002


@dataclass
class Event:
    src: str
    in_point: float
    out_point: float
    reason: str = ""
    zoom: float = 1.0
    cx: float = 0.5
    cy: float = 0.5
    audio: str = ""

    def __post_init__(self) -> None:
        for name, default, lower, upper in (
            ("zoom", 1.0, 1.0, 4.0),
            ("cx", 0.5, 0.0, 1.0),
            ("cy", 0.5, 0.0, 1.0),
        ):
            try:
                value = float(getattr(self, name))
            except (OverflowError, TypeError, ValueError):
                value = default
            setattr(self, name, default if isnan(value) else min(upper, max(lower, value)))

    def duration(self) -> float:
        return max(0.0, self.out_point - self.in_point)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "src": self.src,
            "in": round(self.in_point, 3),
            "out": round(self.out_point, 3),
            "reason": self.reason,
        }
        for name, default in (("zoom", 1.0), ("cx", 0.5), ("cy", 0.5)):
            if getattr(self, name) != default:
                data[name] = getattr(self, name)
        if self.audio:
            data["audio"] = self.audio
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Event:
        return cls(
            src=str(data["src"]),
            in_point=float(data.get("in") or data.get("in_point") or 0),
            out_point=float(data.get("out") or data.get("out_point") or 0),
            reason=str(data.get("reason") or ""),
            zoom=data.get("zoom", 1.0),
            cx=data.get("cx", 0.5),
            cy=data.get("cy", 0.5),
            audio=str(data.get("audio") or ""),
        )


def source_canvas(events: list[Event]) -> tuple[int, int]:
    """Use display size by greatest total event duration, ties first; round down even."""
    from edittude_v3.media.inventory import describe_clip

    durations: dict[str, float] = {}
    for event in events:
        durations[event.src] = durations.get(event.src, 0.0) + event.duration()
    for src in sorted(durations, key=lambda src: durations[src], reverse=True):
        try:
            clip = describe_clip(Path(src))
            width = int(clip.get("display_width") or 0) // 2 * 2
            height = int(clip.get("display_height") or 0) // 2 * 2
        except (MediaError, OSError, TypeError, ValueError):
            continue
        if clip.get("has_video", True) and width > 0 and height > 0:
            return width, height
    return 1920, 1080


@dataclass
class EditDecision:
    events: list[Event] = field(default_factory=list)
    title: str = ""
    subtitle: str = ""
    aspect: str = "source"
    look: str = "warm"
    fps: int = 30
    voiceover: str | None = None
    music: str | None = None
    notes: str = ""
    canvas_width: int | None = None
    canvas_height: int | None = None
    fit: str = "pad"
    skipped: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.fit not in ("pad", "crop"):
            raise MediaError("fit must be pad or crop")
        if self.aspect != "source" and self.aspect not in ASPECTS:
            raise MediaError(f"unknown aspect {self.aspect}. use source or {', '.join(ASPECTS)}")
        if self.fps and not 0 < self.fps <= 240:
            raise MediaError(f"fps must be between 1 and 240, or 0 for the default 30. got {self.fps}")
        if self.aspect == "source":
            for size in (self.canvas_width, self.canvas_height):
                if size is not None and size <= 0:
                    raise MediaError("source canvas dimensions must be positive")

    def _canvas(self) -> tuple[int, int]:
        if self.aspect != "source":
            return ASPECTS.get(self.aspect, ASPECTS["16:9"])
        if self.canvas_width is None or self.canvas_height is None:
            width, height = source_canvas(self.events)
            if self.canvas_width is None:
                self.canvas_width = width
            if self.canvas_height is None:
                self.canvas_height = height
        # libx264 needs even dimensions; source_canvas rounds, explicit values did not.
        self.canvas_width = max(2, self.canvas_width // 2 * 2)
        self.canvas_height = max(2, self.canvas_height // 2 * 2)
        return self.canvas_width, self.canvas_height

    @property
    def width(self) -> int:
        return self._canvas()[0]

    @property
    def height(self) -> int:
        return self._canvas()[1]

    def duration(self) -> float:
        return sum(event.duration() for event in self.events)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "version": 1,
            "title": self.title,
            "subtitle": self.subtitle,
            "aspect": self.aspect,
            "fit": self.fit,
            "look": self.look,
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "voiceover": self.voiceover,
            "music": self.music,
            "duration": round(self.duration(), 3),
            "notes": self.notes,
            "events": [event.to_dict() for event in self.events],
        }
        if self.skipped:
            data["skipped"] = self.skipped
        return data


def load_edl(path: Path) -> EditDecision:
    data = read_json(path)
    return edl_from_dict(data)


def _skipped_from(raw: Any) -> list[dict[str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise MediaError("EDL skipped must be a list")
    skipped = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise MediaError(f"EDL skipped {index}: must be an object")
        skipped.append({"src": str(item.get("src") or ""), "reason": str(item.get("reason") or "")})
    return skipped


def edl_from_dict(data: dict[str, Any]) -> EditDecision:
    if not isinstance(data, dict):
        raise MediaError("EDL must be an object")
    items = data.get("events", [])
    if not isinstance(items, list):
        raise MediaError("EDL events must be a list")
    events = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise MediaError(f"EDL event {index}: must be an object")
        for name in ("src", "in", "out"):
            if name not in item and (name == "src" or f"{name}_point" not in item):
                raise MediaError(f"EDL event {index}: missing {name}")
        event = Event.from_dict(item)
        if event.in_point >= event.out_point:
            raise MediaError(f"EDL event {index}: in must be less than out")
        events.append(event)
    aspect = str(data.get("aspect") or "source")
    return EditDecision(
        events=events,
        title=str(data.get("title") or ""),
        subtitle=str(data.get("subtitle") or ""),
        aspect=aspect,
        canvas_width=int(data["width"]) if aspect == "source" and data.get("width") is not None else None,
        canvas_height=int(data["height"]) if aspect == "source" and data.get("height") is not None else None,
        fit=str(data.get("fit") or "pad"),
        look=str(data.get("look") or "warm"),
        fps=int(data.get("fps") or 30),
        voiceover=data.get("voiceover"),
        music=data.get("music"),
        notes=str(data.get("notes") or ""),
        skipped=_skipped_from(data.get("skipped")),
    )


def save_edl(edl: EditDecision, path: Path) -> Path:
    return write_json(path, edl.to_dict())


def pick_voiceover(inventory: dict[str, Any]) -> dict[str, Any] | None:
    audios = [c for c in inventory.get("clips") or [] if c.get("kind") == "audio"]
    if not audios:
        return None
    ranked = sorted(audios, key=lambda c: (_vo_score(c), c.get("duration") or 0), reverse=True)
    # Length alone does not make a narrator; an unnamed track belongs to pick_music.
    return ranked[0] if _vo_score(ranked[0]) else None


def pick_music(inventory: dict[str, Any], voiceover: dict[str, Any] | None) -> dict[str, Any] | None:
    audios = [c for c in inventory.get("clips") or [] if c.get("kind") == "audio"]
    vo_path = voiceover.get("path") if voiceover else None
    candidates = []
    for clip in audios:
        if clip.get("path") == vo_path:
            continue
        name = clip.get("name", "").lower()
        if any(token in name for token in ("music", "bed", "underscore", "song", "score")):
            candidates.append(clip)
    if not candidates and voiceover is None:
        # Nothing claimed the narration slot, so unnamed audio is a bed.
        candidates = audios
    if not candidates:
        return None
    return max(candidates, key=lambda c: c.get("duration") or 0)


def _vo_score(clip: dict[str, Any]) -> int:
    name = clip.get("name", "").lower()
    score = 0
    for token in ("voiceover", "voice-over", "narration", "vo "):
        if token in name:
            score += 10
    if name.endswith(".m4a") or name.endswith(".wav"):
        score += 1
    return score


def first_cut(
    inventory: dict[str, Any],
    *,
    title: str = "",
    aspect: str = "source",
    fit: str = "pad",
    look: str = "warm",
    target: float | None = None,
) -> EditDecision:
    videos = [c for c in inventory.get("clips") or [] if c.get("kind") == "video"]
    videos = sorted(videos, key=lambda c: (c.get("creation_time") or "", c.get("name") or ""))
    voiceover = pick_voiceover(inventory)
    music = pick_music(inventory, voiceover)
    if target is None:
        if voiceover:
            target = float(voiceover["duration"])
        else:
            total = sum(float(c.get("duration") or 0) for c in videos)
            target = min(60.0, max(12.0, total * 0.72))

    kept: list[tuple[dict[str, Any], float, float, float | None]] = []
    skipped: list[dict[str, str]] = []
    for clip in videos:
        src_dur = float(clip.get("duration") or 0)
        if src_dur < 0.4:
            continue
        chosen = _keep_window(clip)
        if chosen is None:
            skipped.append({"src": str(clip.get("path") or ""), "reason": SKIPPED_NO_CLEAN})
            continue
        start, end, ceiling = chosen
        if end <= start:
            skipped.append({"src": str(clip.get("path") or ""), "reason": SKIPPED_NO_CLEAN})
            continue
        kept.append((clip, start, end, ceiling))

    events: list[Event] = []
    ceilings: list[float | None] = []
    for index, (clip, start, end, ceiling) in enumerate(kept):
        events.append(
            Event(
                src=clip["path"],
                in_point=start,
                out_point=end,
                reason=_reason(index, len(kept), clip),
                audio="bed" if clip.get("has_audio") is False else "",
            )
        )
        ceilings.append(ceiling)

    # No ceiling on a clean cut, so growth stays on the previous path.
    bounded = ceilings if any(item is not None for item in ceilings) else None
    fit_to_duration(events, target, bounded)
    notes = (
        "Chronology is the spine. Handles off iPhone starts. "
        "Long holds capped. Picture fitted to voiceover when one exists."
    )
    return EditDecision(
        events=events,
        title=title,
        aspect=aspect,
        fit=fit,
        look=look if look in LOOKS else "warm",
        voiceover=voiceover["path"] if voiceover else None,
        music=music["path"] if music else None,
        notes=notes,
        skipped=skipped,
    )


def fit_to_duration(
    events: list[Event],
    target: float,
    ceilings: list[float | None] | None = None,
) -> list[Event]:
    if not events or target <= 0:
        return events
    current = sum(event.duration() for event in events)
    if abs(current - target) < 0.15:
        return events
    if current > target:
        _shrink(events, current - target)
    else:
        _grow(events, target - current, ceilings)
    return events


def tighten(edl: EditDecision, *, drop_longest: bool = False) -> EditDecision:
    # Pin the canvas before durations move, or a source EDL re-derives it from the new holds.
    edl.canvas_width, edl.canvas_height = edl.width, edl.height
    events = [replace(event) for event in edl.events]
    if drop_longest and len(events) > 4:
        longest = max(range(len(events)), key=lambda i: events[i].duration())
        if events[longest].duration() > 3.5 and 0 < longest < len(events) - 1:
            events.pop(longest)
    for event in events:
        hold = event.duration()
        if hold > 3.4:
            event.out_point = event.in_point + max(MIN_HOLD, hold * 0.82)
    target = None
    if edl.voiceover:
        vo = Path(edl.voiceover)
        if vo.is_file():
            from edittude_v3.media.inventory import describe_clip

            target = float(describe_clip(vo)["duration"])
    if target:
        fit_to_duration(events, target)
    edl.events = events
    return edl


def _shrink(events: list[Event], excess: float) -> None:
    remaining = excess
    # Prefer trimming the longest interior holds first.
    order = sorted(range(len(events)), key=lambda i: events[i].duration(), reverse=True)
    for _ in range(12):
        if remaining <= 0.05:
            return
        progressed = False
        for index in order:
            event = events[index]
            slack = event.duration() - MIN_HOLD
            if slack <= 0.05:
                continue
            take = min(slack, remaining, max(0.12, slack * 0.35))
            event.out_point -= take
            remaining -= take
            progressed = True
            if remaining <= 0.05:
                return
        if not progressed:
            break
    # Last resort: drop a middle short insert if still long.
    while remaining > 0.8 and len(events) > 6:
        middles = list(range(1, len(events) - 1))
        victim = max(middles, key=lambda i: events[i].duration())
        remaining -= events[victim].duration()
        events.pop(victim)


def _grow(
    events: list[Event],
    need: float,
    ceilings: list[float | None] | None = None,
) -> None:
    remaining = need
    for index, event in enumerate(events):
        if remaining <= 0.05:
            return
        src = Path(event.src)
        if not src.is_file():
            continue
        from edittude_v3.media.inventory import describe_clip

        src_dur = float(describe_clip(src)["duration"])
        slack = src_dur - HANDLE_OUT - event.out_point
        if ceilings is not None and index < len(ceilings) and ceilings[index] is not None:
            slack = min(slack, ceilings[index] - event.out_point)
        if slack <= 0.05:
            continue
        take = min(slack, remaining)
        event.out_point += take
        remaining -= take


@dataclass
class _Span:
    start: float
    end: float


def _keep_window(clip: dict[str, Any]) -> tuple[float, float, float | None] | None:
    """In/out/ceiling for one clip. None drops it: no clean window of MIN_HOLD."""
    src_dur = float(clip.get("duration") or 0)
    screeny = _looks_like_screen(clip)
    path = Path(str(clip.get("path") or ""))
    if not path.is_file():
        start, end = _legacy_window(src_dur, screeny)
        return start, end, None
    spans, rate = _probe_spans(path, clip.get("has_audio") is True)
    spans = _merge_spans(_close_spans(spans, src_dur), rate)
    if not spans:
        start, end = _legacy_window(src_dur, screeny)
        return start, end, None
    origin = _advance_origin(spans, rate, src_dur)
    blocking = [
        span
        for span in spans
        if span.end > origin + _SNAP_SLACK + 1e-4 and span.end - span.start >= INTERIOR_MIN
    ]
    return _choose_window(origin, blocking, rate, src_dur, screeny)


def _choose_window(
    origin: float,
    blocking: list[_Span],
    rate: Fraction,
    src_dur: float,
    screeny: bool,
) -> tuple[float, float, float | None] | None:
    if src_dur - origin <= 1e-3:
        return None
    start, end = _head_window(origin, src_dur, screeny)
    if end <= start:
        return None
    hit = next(
        (span for span in blocking if span.start < end - 1e-4 and span.end > start + 1e-4),
        None,
    )
    if hit is None:
        if origin > 1e-6 and end - start < MIN_HOLD:
            return None
        return start, end, _ceiling_after(end, blocking, rate, src_dur)
    hit_end = _frame_at_or_after(hit.end, rate)
    for gap_start, gap_end in _gaps(origin, blocking, rate, src_dur):
        if gap_start + 1e-4 < hit_end:
            continue
        placed = _place_in_gap(gap_start, gap_end, src_dur, screeny)
        if placed is not None:
            return placed
    cut_end = _frame_at_or_before(hit.start, rate)
    if cut_end > start + 1e-4 and cut_end - start >= MIN_HOLD:
        return start, cut_end, cut_end
    return None


def _place_in_gap(
    gap_start: float,
    gap_end: float,
    src_dur: float,
    screeny: bool,
) -> tuple[float, float, float | None] | None:
    start, end = _head_window(gap_start, src_dur, screeny)
    limit = gap_end if gap_end < src_dur - 1e-4 else None
    if limit is not None and end > limit:
        end = limit
    if end <= start or end - start < MIN_HOLD:
        return None
    ceiling = limit if limit is not None and limit < src_dur - HANDLE_OUT - 1e-9 else None
    return start, end, ceiling


def _gaps(
    origin: float,
    blocking: list[_Span],
    rate: Fraction,
    src_dur: float,
) -> list[tuple[float, float]]:
    gaps: list[tuple[float, float]] = []
    cursor = origin
    for span in blocking:
        if span.start > cursor + 1e-4:
            wall = _frame_at_or_before(span.start, rate)
            if wall > cursor:
                gaps.append((cursor, wall))
        nxt = _frame_at_or_after(span.end, rate)
        if nxt > cursor:
            cursor = nxt
    if cursor < src_dur - 1e-4:
        gaps.append((cursor, src_dur))
    return gaps


def _ceiling_after(
    end: float,
    blocking: list[_Span],
    rate: Fraction,
    src_dur: float,
) -> float | None:
    """Stop growth at the next interior defect, before the handle already would."""
    for span in blocking:
        if span.end <= end + 1e-6:
            continue
        wall = _frame_at_or_before(span.start, rate)
        if wall <= end + 1e-6:
            return end
        if wall < src_dur - HANDLE_OUT - 1e-9:
            return wall
        return None
    return None


def _legacy_window(src_dur: float, screeny: bool) -> tuple[float, float]:
    start = HANDLE_IN if src_dur > HANDLE_IN + MIN_HOLD else 0.0
    end = src_dur - HANDLE_OUT if src_dur - HANDLE_OUT > start + MIN_HOLD else src_dur
    cap = SCREENY_CAP if screeny else MAX_HOLD
    if end - start > cap:
        end = start + cap
    return start, end


def _head_window(origin: float, src_dur: float, screeny: bool) -> tuple[float, float]:
    if origin <= 1e-9:
        return _legacy_window(src_dur, screeny)
    remain = src_dur - origin
    start = origin + HANDLE_IN if remain > HANDLE_IN + MIN_HOLD else origin
    end = src_dur - HANDLE_OUT if src_dur - HANDLE_OUT > start + MIN_HOLD else src_dur
    cap = SCREENY_CAP if screeny else MAX_HOLD
    if end - start > cap:
        end = start + cap
    return start, end


def _advance_origin(spans: list[_Span], rate: Fraction, src_dur: float) -> float:
    origin = 0.0
    frame = _frame(rate)
    for span in spans:
        if span.end <= origin + _SNAP_SLACK:
            continue
        if span.start <= origin + frame + 1e-4:
            origin = min(src_dur, _frame_at_or_after(span.end, rate))
            continue
        break
    return origin


def _probe_spans(path: Path, has_audio: bool) -> tuple[list[_Span], Fraction]:
    rate = _video_rate(ffprobe(path))
    args = ["-i", str(path)]
    if has_audio:
        args += ["-af", SILENCE_DETECT]
    args += ["-vf", f"{BLACK_DETECT},{FREEZE_DETECT}", "-f", "null", "-"]
    result = ffmpeg(args, capture=True)
    log = (result.stderr or "") + "\n" + (result.stdout or "")
    found = detector_spans(log)
    spans = [_Span(item["start"], item["end"]) for item in found["black"]]
    spans += [_Span(item["start"], item["end"]) for item in found["freeze"]]
    if has_audio:
        spans += [_Span(item["start"], item["end"]) for item in found["silence"]]
    return spans, rate


def _close_spans(spans: list[_Span], src_dur: float) -> list[_Span]:
    closed: list[_Span] = []
    for span in spans:
        if span.start >= src_dur:
            continue
        # A missing end is the open-ended form (freeze through EOF), not a zero-length hit.
        end = src_dur if span.end <= span.start else span.end
        closed.append(_Span(span.start, min(end, src_dur)))
    return closed


def _merge_spans(spans: list[_Span], rate: Fraction) -> list[_Span]:
    if not spans:
        return []
    frame = _frame(rate)
    ordered = sorted(spans, key=lambda span: (span.start, span.end))
    merged = [_Span(ordered[0].start, ordered[0].end)]
    for span in ordered[1:]:
        if span.start <= merged[-1].end + frame + 1e-4:
            merged[-1].end = max(merged[-1].end, span.end)
            merged[-1].start = min(merged[-1].start, span.start)
        else:
            merged.append(_Span(span.start, span.end))
    return merged


def _video_rate(probed: dict[str, Any]) -> Fraction:
    for stream in probed.get("streams") or []:
        if stream.get("codec_type") != "video":
            continue
        for key in ("avg_frame_rate", "r_frame_rate"):
            rate = _parse_rate(stream.get(key))
            if rate > 0:
                return rate
    return Fraction(0)


def _parse_rate(value: object) -> Fraction:
    text = str(value or "")
    if not text or text in {"0/0", "0"}:
        return Fraction(0)
    try:
        rate = Fraction(text)
    except (ValueError, ZeroDivisionError):
        return Fraction(0)
    return rate if rate > 0 else Fraction(0)


def _frame(rate: Fraction) -> float:
    if rate <= 0:
        return 0.0
    return float(Fraction(1) / rate)


def _frame_at_or_after(t: float, rate: Fraction) -> float:
    if rate <= 0:
        return t
    n = math.ceil((t - _SNAP_SLACK) * float(rate) - 1e-9)
    return float(Fraction(max(n, 0)) / rate)


def _frame_at_or_before(t: float, rate: Fraction) -> float:
    if rate <= 0:
        return t
    n = math.floor(t * float(rate) + 1e-6)
    return float(Fraction(max(n, 0)) / rate)


def _looks_like_screen(clip: dict[str, Any]) -> bool:
    name = clip.get("name", "").lower()
    if any(token in name for token in ("screen", "laptop", "ui", "capture")):
        return True
    # Long static-ish clips in this set are usually screens.
    return float(clip.get("duration") or 0) >= 8.5


def _reason(index: int, count: int, clip: dict[str, Any]) -> str:
    name = clip.get("name", "")
    if index == 0:
        return f"open on {name}"
    if index == count - 1:
        return f"button / close {name}"
    if index == 1:
        return f"establish place {name}"
    if _looks_like_screen(clip):
        return f"detail, keep short {name}"
    if index < count * 0.35:
        return f"arrive {name}"
    if index < count * 0.7:
        return f"move {name}"
    return f"work / land {name}"


def as_plain(edl: EditDecision) -> dict[str, Any]:
    return asdict(edl)
