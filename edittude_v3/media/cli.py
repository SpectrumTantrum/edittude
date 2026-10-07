from __future__ import annotations

import argparse
import sys
from pathlib import Path

from edittude_v3.media.core import ASPECTS, LOOKS, MediaError, write_json
from edittude_v3.media.edl import first_cut, load_edl, save_edl, tighten
from edittude_v3.media.inventory import extract_thumbs, write_inventory
from edittude_v3.media.proof import run_proof
from edittude_v3.media.qc import write_review
from edittude_v3.media.render import (
    assemble,
    burn_srt,
    finish,
    grade,
    grab_frames,
    mix,
    reframe,
    titles,
)


def main(argv: list[str] | None = None) -> None:
    parser = _parser()
    argv = sys.argv[1:] if argv is None else list(argv)
    # --force is a global flag; hoist it so it also works after the subcommand.
    if "--force" in argv:
        argv = ["--force", *(arg for arg in argv if arg != "--force")]
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except MediaError as exc:
        raise SystemExit(str(exc)) from exc


def _prog() -> str:
    invoked = Path(sys.argv[0]).name
    if invoked == "edittude-media":
        return "edittude-media"
    if invoked == "edittude-v3":
        return "edittude-v3 media"
    return "edittude media"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=_prog(),
        description="Local footage tools. Inventory, cut, mix, grade, titles, QC.",
    )
    parser.add_argument("--force", action="store_true", help="overwrite existing output files")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("inventory", help="ffprobe a footage folder")
    p.add_argument("folder", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=_cmd_inventory)

    p = sub.add_parser("thumbs", help="extract stills from an inventory")
    p.add_argument("inventory", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--count", type=int, default=3)
    p.set_defaults(func=_cmd_thumbs)

    p = sub.add_parser("plan", help="write a first-cut EDL from inventory")
    p.add_argument("inventory", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--title", default="")
    p.add_argument("--aspect", default="source", choices=("source", *ASPECTS),
                   help="canvas size; source keeps the dominant clip's display resolution")
    p.add_argument("--fit", default="pad", choices=("pad", "crop"),
                   help="pad off-aspect shots or crop them to fill the canvas")
    p.add_argument("--look", default="warm", choices=sorted(LOOKS))
    p.add_argument("--target", type=float)
    p.set_defaults(func=_cmd_plan)

    p = sub.add_parser("assemble", help="render an EDL to a picture cut")
    p.add_argument("edl", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--work", type=Path)
    p.set_defaults(func=_cmd_assemble)

    p = sub.add_parser("mix", help="duck voiceover / music under picture")
    p.add_argument("video", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--vo", type=Path)
    p.add_argument("--music", type=Path)
    p.add_argument("--amb-db", type=float, default=-16)
    p.add_argument("--music-db", type=float, default=-22)
    p.set_defaults(func=_cmd_mix)

    p = sub.add_parser("grade", help="apply a still look")
    p.add_argument("video", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--look", default="warm", choices=sorted(LOOKS))
    p.set_defaults(func=_cmd_grade)

    p = sub.add_parser("titles", help="burn an opening title")
    p.add_argument("video", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--subtitle", default="")
    p.set_defaults(func=_cmd_titles)

    p = sub.add_parser(
        "captions",
        help="burn an SRT if ffmpeg has libass. this Homebrew build usually does not",
    )
    p.add_argument("video", type=Path)
    p.add_argument("--srt", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=_cmd_captions)

    p = sub.add_parser("reframe", help="reframe to 16:9, 9:16, or 1:1")
    p.add_argument("video", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--aspect", required=True, choices=("16:9", "9:16", "1:1"))
    p.add_argument("--fit", default="crop", choices=("pad", "crop"))
    p.set_defaults(func=_cmd_reframe)

    p = sub.add_parser("finish", help="grade + title + mix in one encode")
    p.add_argument("picture", type=Path)
    p.add_argument("edl", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=_cmd_finish)

    p = sub.add_parser("qc", help="black / silence / loudness / duration")
    p.add_argument("video", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=_cmd_qc)

    p = sub.add_parser("frames", help="grab stills from a render")
    p.add_argument("video", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=_cmd_frames)

    p = sub.add_parser("recut", help="tighten an EDL after QC")
    p.add_argument("edl", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--drop-longest", action="store_true")
    p.set_defaults(func=_cmd_recut)

    p = sub.add_parser("proof", help="inventory, plan, assemble, finish, QC")
    p.add_argument("folder", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--title", default="A DAY OUT")
    p.add_argument("--subtitle", default="")
    p.add_argument("--aspect", default="source", choices=("source", *ASPECTS),
                   help="canvas size; source keeps the dominant clip's display resolution")
    p.add_argument("--fit", default="pad", choices=("pad", "crop"),
                   help="pad off-aspect shots or crop them to fill the canvas")
    p.add_argument("--look", default="warm")
    p.add_argument("--no-thumbs", action="store_true")
    p.set_defaults(func=_cmd_proof)

    p = sub.add_parser("models", help="install the optional neural model runtime and weights")
    p.add_argument("action", choices=("install",))
    p.add_argument("--models", default="asr,separation")
    p.add_argument("--check", action="store_true")
    p.set_defaults(func=_cmd_models)

    return parser


def _cmd_inventory(args: argparse.Namespace) -> None:
    data = write_inventory(args.folder, args.out)
    totals = data["totals"]
    print(
        f"wrote {args.out}  {totals['video']} clips, "
        f"{totals['video_seconds']}s picture, {totals['audio']} audio"
    )


def _cmd_thumbs(args: argparse.Namespace) -> None:
    from edittude_v3.media.core import read_json

    inventory = read_json(args.inventory)
    frames = extract_thumbs(inventory, args.out, count=args.count)
    print(f"wrote thumbs for {len(frames)} clips under {args.out}")


def _cmd_plan(args: argparse.Namespace) -> None:
    from edittude_v3.media.core import read_json

    _guard_output(args.out, args.force)
    if args.target is not None and args.target <= 0:
        raise MediaError("--target must be greater than 0 seconds")
    inventory = read_json(args.inventory)
    edl = first_cut(
        inventory,
        title=args.title,
        aspect=args.aspect,
        fit=args.fit,
        look=args.look,
        target=args.target,
    )
    save_edl(edl, args.out)
    print(f"wrote {args.out}  {len(edl.events)} events, {edl.duration():.2f}s")


def _guard_output(out: Path, force: bool) -> None:
    if out.exists() and not force:
        raise MediaError(f"{out} exists; pass --force to overwrite")


def _cmd_assemble(args: argparse.Namespace) -> None:
    _guard_output(args.out, args.force)
    edl = load_edl(args.edl)
    work = args.work or args.out.parent / "work"
    assemble(edl, args.out, work)
    print(f"wrote {args.out}")


def _cmd_mix(args: argparse.Namespace) -> None:
    _guard_output(args.out, args.force)
    mix(
        args.video,
        args.out,
        voiceover=args.vo,
        music=args.music,
        amb_db=args.amb_db,
        music_db=args.music_db,
    )
    print(f"wrote {args.out}")


def _cmd_grade(args: argparse.Namespace) -> None:
    _guard_output(args.out, args.force)
    grade(args.video, args.out, args.look)
    print(f"wrote {args.out}")


def _cmd_titles(args: argparse.Namespace) -> None:
    _guard_output(args.out, args.force)
    titles(args.video, args.out, title=args.title, subtitle=args.subtitle)
    print(f"wrote {args.out}")


def _cmd_captions(args: argparse.Namespace) -> None:
    _guard_output(args.out, args.force)
    burn_srt(args.video, args.out, args.srt)
    print(f"wrote {args.out}")


def _cmd_reframe(args: argparse.Namespace) -> None:
    _guard_output(args.out, args.force)
    reframe(args.video, args.out, args.aspect, fit=args.fit)
    print(f"wrote {args.out}")


def _cmd_finish(args: argparse.Namespace) -> None:
    _guard_output(args.out, args.force)
    finish(args.picture, args.out, edl=load_edl(args.edl))
    print(f"wrote {args.out}")


def _cmd_qc(args: argparse.Namespace) -> None:
    report = write_review(args.video, args.out)
    status = "pass" if report["pass"] else "issues"
    print(f"wrote {args.out}  {status}  {report['duration']:.2f}s  {report['issues']}")


def _cmd_frames(args: argparse.Namespace) -> None:
    frames = grab_frames(args.video, args.out)
    print(f"wrote {len(frames)} frames under {args.out}")


def _cmd_recut(args: argparse.Namespace) -> None:
    _guard_output(args.out, args.force)
    edl = tighten(load_edl(args.edl), drop_longest=args.drop_longest)
    save_edl(edl, args.out)
    print(f"wrote {args.out}  {len(edl.events)} events, {edl.duration():.2f}s")


def _cmd_models(args: argparse.Namespace) -> None:
    # tools/ is portable and must not import the harness, so run it as its own script.
    import subprocess
    import sys

    from edittude_v3.paths import PACKAGE_ROOT, install_root

    # EDITTUDE_ROOT may point at a models-only root, so fall back to the shipped copy.
    script = next((root / "tools/install_models.py" for root in (install_root(), PACKAGE_ROOT)
                   if (root / "tools/install_models.py").is_file()), None)
    if script is None:
        raise SystemExit(f"tools/install_models.py is missing from {install_root()}")
    forwarded = ["--models", args.models] + (["--check"] if args.check else [])
    raise SystemExit(subprocess.run([sys.executable, str(script), *forwarded]).returncode)


def _cmd_proof(args: argparse.Namespace) -> None:
    for name in ("final.mp4", "edl.json"):
        _guard_output(args.out / name, args.force)
    evidence = run_proof(
        args.folder,
        args.out,
        title=args.title,
        subtitle=args.subtitle,
        aspect=args.aspect,
        fit=args.fit,
        look=args.look,
        thumbs=not args.no_thumbs,
    )
    write_json(args.out / "evidence.json", evidence)
    print(f"final {evidence['final']}  {evidence['duration']}s  pass={evidence['pass']}")
