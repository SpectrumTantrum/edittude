from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from edittude_v3.media.core import ffmpeg, write_json
from edittude_v3.media.edl import first_cut, save_edl
from edittude_v3.media.inventory import extract_thumbs, write_inventory
from edittude_v3.media.qc import write_review
from edittude_v3.media.render import assemble, finish, grab_frames


def run_proof(
    folder: Path,
    out_dir: Path,
    *,
    title: str = "A DAY OUT",
    subtitle: str = "",
    aspect: str = "source",
    fit: str = "pad",
    look: str = "warm",
    thumbs: bool = True,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg_version = _ffmpeg_version()
    print(ffmpeg_version, flush=True)
    inventory_path = out_dir / "inventory.json"
    inventory = write_inventory(folder, inventory_path)
    thumb_report: list[dict[str, Any]] = []
    if thumbs:
        thumb_report = extract_thumbs(inventory, out_dir / "thumbs")
    edl = first_cut(inventory, title=title, aspect=aspect, fit=fit, look=look)
    if subtitle:
        edl.subtitle = subtitle
    edl_path = out_dir / "edl.json"
    save_edl(edl, edl_path)
    work = out_dir / "work"
    picture = assemble(edl, out_dir / "picture.mp4", work)
    final = finish(picture, out_dir / "final.mp4", edl=edl)
    qc = write_review(final, out_dir / "qc.json")
    frames = grab_frames(final, out_dir / "frames")
    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ffmpeg": ffmpeg_version,
        "folder": str(folder.resolve()),
        "out_dir": str(out_dir.resolve()),
        "inventory": str(inventory_path),
        "edl": str(edl_path),
        "picture": str(picture),
        "final": str(final),
        "qc": str(out_dir / "qc.json"),
        "thumbs": thumb_report,
        "frames": [str(path) for path in frames],
        "title": edl.title,
        "duration": qc.get("duration"),
        "edl_duration": edl.duration(),
        "voiceover": edl.voiceover,
        "clip_count": len(edl.events),
        "pass": qc.get("pass"),
        "issues": qc.get("issues"),
    }
    write_json(out_dir / "evidence.json", evidence)
    (out_dir / "evidence.md").write_text(_evidence_md(evidence, qc), encoding="utf-8")
    return evidence


def _ffmpeg_version() -> str:
    result = ffmpeg(["-version"], capture=True)
    lines = (result.stdout or result.stderr or "").splitlines()
    return lines[0] if lines else "ffmpeg version unknown"


def _evidence_md(evidence: dict[str, Any], qc: dict[str, Any]) -> str:
    issues = evidence.get("issues") or []
    issue_line = ", ".join(issues) if issues else "none"
    frames = "\n".join(f"- {path}" for path in evidence.get("frames") or [])
    return (
        f"# Proof render\n\n"
        f"FFmpeg: {evidence.get('ffmpeg')}\n\n"
        f"Final file: `{evidence['final']}`\n\n"
        f"Duration: {evidence.get('duration')}s. "
        f"EDL: {evidence.get('edl_duration')}s. "
        f"Events: {evidence.get('clip_count')}.\n\n"
        f"Voiceover: `{evidence.get('voiceover')}`\n\n"
        f"QC pass: {evidence.get('pass')}. Issues: {issue_line}.\n\n"
        f"Loudness I: {qc.get('loudness', {}).get('I')} LUFS. "
        f"TP: {qc.get('loudness', {}).get('TP')} dBTP. "
        f"Size: {qc.get('width')}x{qc.get('height')} @ {qc.get('fps')} fps.\n\n"
        f"Frame grabs:\n{frames}\n"
    )
