"""Install the optional neural model runtime and its pinned weights. Needs network access.

This is the only part of tools/ that downloads anything. Inference itself stays offline:
everything lands in models_root() and a separate .venv-models interpreter, so the agent
virtualenv never gains torch.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.common import install_root, model_python, models_root
from tools.models import capabilities

# Shared with every backend; the pins come from edittude-v2's asr extra. TorchAudio 2.9
# removed APIs these backends still call.
SHARED = ["torch>=2.6,<2.9", "torchaudio>=2.6,<2.9", "numpy<3", "soundfile", "huggingface-hub>=0.34,<1"]

# edittude-v2 downloaded most of these weights already, pinned to the same revisions this table
# uses, and records the revision it fetched in each directory's .edittude-model.json. An exact
# revision match is therefore the whole reuse check: matching weights are linked, not re-fetched.
V2_MODELS = Path(os.environ.get("EDITTUDE_V2_MODELS") or Path.home() / ".edittude/models")

_DEMUCS = "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/"
_REMOTE = "https://raw.githubusercontent.com/facebookresearch/demucs/e976d93ecc3865e5757426930257e200846a520a/demucs/remote/"

# files entries are (destination under models_root(), url, sha256 or its demucs prefix).
# hf entries are {repo, rev, into (under models_root()), files, cache}; cache=True lays the
# repo out as an HF *cache* so upstream code that calls hf_hub_download finds it offline.
# git entries clone {url} at {sha} into {into} and apply tools/patches/<into>.patch.
BACKENDS = {
    "asr": {
        "tool": "speech_transcribe", "deps": ["faster-whisper>=1.2,<2"], "size_gb": 0.15,
        "hf": [{"repo": "Systran/faster-whisper-base", "into": "asr/faster-whisper-base",
                "rev": "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66",
                "files": ["model.bin", "config.json", "tokenizer.json", "vocabulary.txt"]}],
        "files": [],
    },
    "separation": {
        "tool": "audio_separate", "deps": ["demucs>=4.1,<5"], "size_gb": 0.1, "hf": [],
        # htdemucs.yaml is a bag of exactly one signature: 955717e8.
        "files": [
            ("demucs/htdemucs.yaml", _REMOTE + "htdemucs.yaml",
             "239c445d0b14454d541ad8bd9bb271c9e536d267e8a4625208744cbb2e7bb66c"),
            # ponytail: upstream publishes no full digest for the .th, so this verifies the
            # 8-hex sha256 prefix demucs itself checks. Swap in a full digest if one appears.
            ("demucs/955717e8-8726e21a.th", _DEMUCS + "955717e8-8726e21a.th", "8726e21a"),
        ],
    },
    # Seed-VC is GPL-3.0, so it is cloned at install time and never vendored into this MIT tree.
    # v3 always runs --f0-condition True, so only the 44k f0 model set is fetched. The aux repos
    # land in the HF cache layout upstream's own hf_hub_download/from_pretrained calls expect
    # (./checkpoints and ./checkpoints/hf_cache, relative to the clone), so no path patch is needed.
    "seed-vc": {
        "tool": "voice_convert", "size_gb": 2.5, "files": [],
        # descript-audio-codec is what the vendored dac/ package needs; argbind and
        # descript-audiotools come with it.
        "deps": ["einops>=0.8,<1", "munch>=4,<5", "librosa>=0.11,<0.12", "transformers>=4.45,<5",
                 "descript-audio-codec>=1,<2", "scipy>=1.15,<2", "PyYAML>=6,<7"],
        "git": {"url": "https://github.com/Plachtaa/seed-vc", "into": "seed-vc",
                "sha": "86959712a9d7971b691bc9919bed78306eca8f41"},
        "hf": [
            {"repo": "Plachta/Seed-VC", "rev": "257283f9f41585055e8f858fba4fd044e5caed6e",
             "into": "seed-vc/ckpt", "files": ["*_f0_44k_*_v2.pth", "*f0_44k.yml"]},
            {"repo": "funasr/campplus", "rev": "e4b6ede7ce16997aff4ae69fbca1f0175e2afede",
             "into": "seed-vc/checkpoints", "files": ["campplus_cn_common.bin"], "cache": True},
            {"repo": "lj1995/VoiceConversionWebUI", "rev": "e6d0c1a17da07c33557852f9dfa2bd44cc75737d",
             "into": "seed-vc/checkpoints", "files": ["rmvpe.pt"], "cache": True},
            {"repo": "openai/whisper-small", "rev": "973afd24965f72e36ca33b3055d56a652f456b4d",
             "into": "seed-vc/checkpoints/hf_cache", "cache": True,
             "files": ["config.json", "model.safetensors", "preprocessor_config.json"]},
            {"repo": "nvidia/bigvgan_v2_44khz_128band_512x", "cache": True,
             "rev": "95a9d1dcb12906c03edd938d77b9333d6ded7dfb",
             "into": "seed-vc/checkpoints/hf_cache", "files": ["bigvgan_generator.pt", "config.json"]},
        ],
    },
    # DiffSinger is MIT, but its opencpop checkpoint is not; see "notice".
    "diffsinger": {
        "tool": "singing_synthesize", "size_gb": 0.5, "files": [],
        # Trimmed to what the patched inference path actually imports: the patch keeps
        # DIFF_DECODERS out of usr.diffsinger_task, so the training stack never loads.
        "deps": ["pypinyin>=0.53,<1", "pycwt>=0.4.0b0,<0.5", "h5py>=3.12,<4", "pandas>=2.2,<3",
                 "matplotlib>=3.9,<4", "librosa>=0.11,<0.12", "scipy>=1.15,<2", "einops>=0.8,<1",
                 "PyYAML>=6,<7"],
        "git": {"url": "https://github.com/MoonInTheRiver/DiffSinger", "into": "DiffSinger",
                "sha": "4662c53a27a5ac662821eae23a7d71cfcff7356d"},
        # Upstream resolves checkpoints/<exp>, vocoder_ckpt and pe_ckpt relative to its own
        # directory, which is where singing_synthesize runs it, so these land ready to use.
        "hf": [{"repo": "PillowTa1k/DiffSinger", "rev": "87c4ccc78132ec624eca9a86c94cb6e2c607185d",
                "into": "DiffSinger/checkpoints",
                "files": ["0102_xiaoma_pe/*", "0109_hifigan_bigpopcs_hop128/*",
                          "0228_opencpop_ds100_rel/*"]}],
        "notice": "The 0228_opencpop_ds100_rel checkpoint is trained on Opencpop "
                  "(CC BY-NC-ND 4.0): non-commercial use only.",
    },
}


def _uv() -> str:
    found = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
    if not Path(found).is_file():
        raise SystemExit("uv is missing. Re-run the edittude installer.")
    return found


def _run(args: list[str | Path]) -> None:
    command = [str(arg) for arg in args]
    try:
        subprocess.run(command, check=True)
    except FileNotFoundError:
        raise SystemExit(f"{command[0]} is missing. Install it and run this again.") from None
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"{command[0]} failed with exit code {error.returncode}") from None


def _venv(deps: list[str]) -> None:
    python = model_python()
    # An override names an interpreter we do not own: install into it, never venv over it.
    if not os.environ.get("EDITTUDE_MODEL_PYTHON") and not python.is_file():
        print(f"creating {python.parent.parent}")
        _run([_uv(), "venv", "--python", "3.11", python.parent.parent])
    _run([_uv(), "pip", "install", "--quiet", "--python", python, *deps])


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _adopt(source: Path, destination: Path) -> None:
    """Take an already-downloaded file, without spending the bytes again."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:  # A separate filesystem, so pay for the copy.
        shutil.copy2(source, destination)


def _wanted(names, patterns) -> list[str]:
    """The subset of names an hf entry asked for; [] means the source is no use to us."""
    names = [name for name in names
             if not patterns or any(fnmatch.fnmatch(name, pattern) for pattern in patterns)]
    # Every pattern has to land something, or we would install a partial model and call it done.
    return names if all(any(fnmatch.fnmatch(name, pattern) for name in names)
                        for pattern in patterns or []) else []


def _installed_v2(entry: dict) -> tuple[Path, list[str]] | None:
    """An edittude-v2 model directory at this exact revision that holds every file we want.

    One revision can cover several directories (Plachta/Seed-VC ships both the f0 and the
    non-f0 checkpoint), so matching the revision alone picks the wrong weights.
    """
    for manifest in sorted(V2_MODELS.glob("*/.edittude-model.json")):
        # Another app owns this directory, so one unreadable manifest must not stop the install.
        try:
            record = json.loads(manifest.read_text(encoding="utf-8"))
            if record["revision"] != entry["rev"]:
                continue
            names = _wanted(record["files"], entry.get("files"))
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if names:
            return manifest.parent, names
    return None


def _download(destination: Path, url: str, digest: str) -> None:
    if destination.is_file() and _digest(destination).startswith(digest):
        print(f"have   {destination.name}")
        return
    # Same file, same checksum, already paid for by edittude-v2.
    adopted = next((path for path in sorted(V2_MODELS.glob(f"*/{destination.name}"))
                    if _digest(path).startswith(digest)), None)
    if adopted is not None:
        print(f"link   {destination.name} from {adopted.parent.name}")
        _adopt(adopted, destination)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = destination.with_suffix(destination.suffix + ".part")
    print(f"fetch  {destination.name}")
    try:
        with urllib.request.urlopen(url, timeout=60) as response, staged.open("wb") as output:  # noqa: S310 - pinned https URLs above.
            shutil.copyfileobj(response, output)
        if not _digest(staged).startswith(digest):
            raise SystemExit(f"Checksum mismatch for {url}")
        staged.replace(destination)
    finally:
        staged.unlink(missing_ok=True)


def _snapshot(entry: dict, destination: Path) -> None:
    """Install one pinned HF repo, preferring bytes already on disk over the network."""
    label = f"{entry['repo']}@{entry['rev'][:8]}"
    slug = f"models--{entry['repo'].replace('/', '--')}"
    # cache=True lays the repo out the way upstream's own hf_hub_download reads it back offline.
    root = destination / slug / "snapshots" / entry["rev"] if entry.get("cache") else destination
    adopted = _installed_v2(entry)
    present = _wanted([str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()],
                      entry.get("files")) if root.is_dir() else []
    if present:
        print(f"have   {label}")
    elif adopted is not None:
        source, names = adopted
        print(f"link   {label} from {source.name}")
        for name in names:
            _adopt(source / name, root / name)
    else:
        # Downloads run inside the model venv, not the agent venv, which never gains torch.
        print(f"fetch  {label}")
        _run([model_python(), "-c", "import json, sys; from huggingface_hub import snapshot_download;"
              " snapshot_download(**json.loads(sys.argv[1]))",
              json.dumps({"repo_id": entry["repo"], "revision": entry["rev"],
                          "allow_patterns": entry.get("files") or None,
                          ("cache_dir" if entry.get("cache") else "local_dir"): str(destination)})])
    if entry.get("cache"):
        # Downloading by sha leaves no refs/main, and the upstream code we call resolves these
        # repos by their default revision. Point main at the revision we pinned.
        reference = destination / slug / "refs" / "main"
        reference.parent.mkdir(parents=True, exist_ok=True)
        reference.write_text(entry["rev"], encoding="utf-8")


def _clone(spec: dict, destination: Path) -> None:
    """Clone an upstream at its pinned sha and apply our patch, idempotently."""
    patch = Path(__file__).resolve().parent / "patches" / f"{spec['into']}.patch"
    if not patch.is_file():  # Before the clone: a clone we cannot patch is wasted bytes.
        raise SystemExit(f"Missing patch {patch}")
    if not (destination / ".git").is_dir():
        print(f"clone  {spec['url']}")
        _run(["git", "clone", "--quiet", spec["url"], destination])
    git = ["git", "-C", str(destination)]
    if subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip() != spec["sha"]:
        _run([*git, "checkout", "--force", "--quiet", spec["sha"]])
    if subprocess.run([*git, "apply", "--reverse", "--check", str(patch)], capture_output=True).returncode:
        print(f"patch  {patch.name}")
        _run([*git, "apply", str(patch)])


def install(names: list[str]) -> None:
    total = sum(BACKENDS[name]["size_gb"] for name in names)
    print(f"Installing {', '.join(names)}: about {total:.2f} GB of weights "
          f"plus about 2.5 GB of torch runtime into {install_root()}")
    for name in names:
        if BACKENDS[name].get("notice"):
            print(f"note:  {BACKENDS[name]['notice']}")
    _venv(SHARED + [dep for name in names for dep in BACKENDS[name]["deps"]])
    for name in names:
        backend = BACKENDS[name]
        if backend.get("git"):
            _clone(backend["git"], models_root() / backend["git"]["into"])
        for relative, url, digest in backend["files"]:
            _download(models_root() / relative, url, digest)
        for entry in backend["hf"]:
            _snapshot(entry, models_root() / entry["into"])


def check(names: list[str]) -> int:
    reported = capabilities()
    failed = 0
    for name in names:
        status = reported[BACKENDS[name]["tool"]]
        print(f"{name:12} {status['status']:12} {status['reason']}")
        failed += status["status"] != "configured"
    return int(bool(failed))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="edittude-media models install", description=__doc__)
    parser.add_argument("--models", default="asr,separation",
                        help="comma-separated backends (default: asr,separation)")
    parser.add_argument("--check", action="store_true",
                        help="report backend status without downloading anything")
    args = parser.parse_args(argv)
    names = [name for name in args.models.split(",") if name]
    unknown = [name for name in names if name not in BACKENDS]
    if unknown:
        parser.error(f"Unknown model backend: {', '.join(unknown)}. Valid: {', '.join(BACKENDS)}")
    if args.check:
        return check(names)
    install(names)
    return check(names)


if __name__ == "__main__":
    raise SystemExit(main())
