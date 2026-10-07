"""Optional local model adapters. No model downloads or implicit voice substitution."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

from .common import (CapabilityUnavailable, artifact_path, input_path, model_python, models_root,
                     output_path as resolve_output, probe, publish, run)
from .media import _integer

INSTALL_HINT = "run: edittude-media models install (seed-vc and diffsinger need --models seed-vc,diffsinger)"
# Weights installed by tools/install_models.py, relative to models_root().
DEFAULTS = {
    "EDITTUDE_ASR_MODEL_DIR": "asr/faster-whisper-base",
    "EDITTUDE_DEMUCS_REPO": "demucs",
    "EDITTUDE_SEED_VC_DIR": "seed-vc",
    # The installer drops Plachta/Seed-VC's pinned f0 44k pair here under its published names.
    "EDITTUDE_SEED_VC_CHECKPOINT":
        "seed-vc/ckpt/DiT_seed_v2_uvit_whisper_base_f0_44k_bigvgan_pruned_ft_ema_v2.pth",
    "EDITTUDE_SEED_VC_CONFIG": "seed-vc/ckpt/config_dit_mel_seed_uvit_whisper_base_f0_44k.yml",
    "EDITTUDE_DIFFSINGER_DIR": "DiffSinger",
}
DIFFSINGER_EXP = "0228_opencpop_ds100_rel"  # The checkpoint the installer fetches.


_OFFLINE_ENV = {
    "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1", "PYTHONDONTWRITEBYTECODE": "1",
}
_OFFLINE = """
import socket
def _network_disabled(*args, **kwargs):
    raise OSError('Network is disabled for local model tools; provide cached model assets')
socket.socket.connect = _network_disabled
socket.socket.connect_ex = _network_disabled
socket.create_connection = _network_disabled
"""


def _runtime(backend: str) -> str:
    installed = model_python()
    value = (os.environ.get(f"EDITTUDE_{backend}_PYTHON") or os.environ.get("EDITTUDE_MODEL_PYTHON")
             or (str(installed) if installed.is_file() else sys.executable))
    executable = shutil.which(value) or str(Path(value).expanduser())
    if not Path(executable).is_file() or not os.access(executable, os.X_OK):
        raise CapabilityUnavailable(f"Python runtime unavailable: {value}; {INSTALL_HINT}, or set EDITTUDE_{backend}_PYTHON")
    return executable


def _configured_path(name: str, *, directory: bool = True) -> Path:
    """Resolve an env override, else the installed default under models_root()."""
    value = os.environ.get(name)
    kind = "directory" if directory else "file"
    default = DEFAULTS.get(name)
    if not value and default is None:
        raise CapabilityUnavailable(f"Set {name} to an existing local {kind}; downloads are disabled")
    path = Path(value).expanduser().resolve() if value else models_root() / default
    if not (path.is_dir() if directory else path.is_file()):
        raise CapabilityUnavailable(f"{name} does not identify an existing {kind}: {path}" if value
                                    else f"No installed model {kind} at {path}; {INSTALL_HINT}, or set {name}")
    return path


def _model_run(backend: str, code: str, args: list[str | Path], *, cwd: Path | None = None) -> None:
    try:
        run([_runtime(backend), "-c", _OFFLINE + code, *args], timeout=3600, cwd=cwd, env=_OFFLINE_ENV)
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or str(error))[-2000:].strip()
        missing = ("ModuleNotFoundError", "ImportError", "FileNotFoundError", "LocalEntryNotFoundError",
                   "Network is disabled", "Cannot find", "not found in the cached", "No such file",
                   "offline mode", "outgoing traffic", "appropriate cached snapshot")
        if any(term in detail for term in missing):
            raise CapabilityUnavailable(f"{backend} local backend unavailable: {detail}") from error
        raise RuntimeError(f"{backend} execution failed: {detail}") from error


def _audio(path: Path, *, decode: bool = True) -> dict:
    info = probe(path)
    stream = next((item for item in info.get("streams", []) if item.get("codec_type") == "audio"), None)
    if stream is None:
        raise ValueError(f"No audio stream: {path.name}")
    duration = float(stream.get("duration") or info.get("format", {}).get("duration", 0))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f"Audio has no finite positive duration: {path.name}")
    if decode:
        run(["ffmpeg", "-v", "error", "-xerror", "-nostdin", "-i", path, "-map", "0:a:0", "-f", "null", "-"], timeout=3600)
    return {"duration": duration, "sample_rate": int(stream["sample_rate"]), "channels": int(stream["channels"])}


def _wav_destination(workspace: Path, value: str) -> Path:
    destination = resolve_output(workspace, value)
    if destination.suffix.lower() != ".wav":
        raise ValueError("Model audio output must use a .wav destination")
    return destination


def _publish_audio(workspace: Path, generated: Path, destination: Path, backend: str) -> dict:
    metadata = _audio(generated)
    publish(generated, destination)
    return {"status": "ok", "audio_path": artifact_path(workspace, destination), "backend": backend,
            **metadata, "verification": {"decoded": True, "listening": False}}


def speech_transcribe(workspace: Path, audio_path: str, output_path: str, language: str | None = None,
                      model: str = "base", source_id: str | None = None) -> dict:
    """Transcribe with cached faster-whisper weights and retain measured word/segment times."""
    source = input_path(workspace, audio_path)
    destination = resolve_output(workspace, output_path)
    if destination.suffix.lower() != ".json":
        raise ValueError("Transcript output must use .json")
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)?", model):
        raise ValueError("model must be a cached faster-whisper model name or 'local' with EDITTUDE_ASR_MODEL_DIR configured")
    # The default 'base' resolves to installed local weights when they exist, so transcription
    # works straight after the installer with no environment and no downloads.
    installed_asr = os.environ.get("EDITTUDE_ASR_MODEL_DIR") or (models_root() / DEFAULTS["EDITTUDE_ASR_MODEL_DIR"]).is_dir()
    model_location = (str(_configured_path("EDITTUDE_ASR_MODEL_DIR"))
                      if model == "local" or (model == "base" and installed_asr) else model)
    if language is not None and (not isinstance(language, str) or not re.fullmatch(r"[a-z]{2,3}", language)):
        raise ValueError("language must be a supported two- or three-letter language code")
    if source_id is not None and (not isinstance(source_id, str) or not source_id.strip()):
        raise ValueError("source_id must be a nonempty string")
    identity = source_id or "source-" + hashlib.sha256(artifact_path(workspace, source).encode()).hexdigest()[:12]
    metadata = _audio(source)
    with tempfile.TemporaryDirectory(dir=workspace, prefix=".asr-") as directory:
        staged = Path(directory) / "transcript.json"
        _model_run("ASR", """
import json, sys
from faster_whisper import WhisperModel
source, output, model_name, language, identity = sys.argv[1:]
model = WhisperModel(model_name, device='cpu', compute_type='int8', cpu_threads=4, local_files_only=True)
segments, info = model.transcribe(source, language=language or None, word_timestamps=True,
    beam_size=1, temperature=0, condition_on_previous_text=False, vad_filter=True)
rows = []
for index, segment in enumerate(segments, 1):
    rows.append({'id': f'{identity}-{index:04d}', 'start': float(segment.start), 'end': float(segment.end),
        'text': segment.text.strip(), 'words': [{'start': float(word.start), 'end': float(word.end),
        'text': word.word.strip(), 'probability': float(word.probability)} for word in (segment.words or [])]})
with open(output, 'w', encoding='utf-8') as stream:
    json.dump({'language': info.language, 'segments': rows}, stream, ensure_ascii=False, allow_nan=False)
""", [source, staged, model_location, language or "", identity])
        payload = json.loads(staged.read_text(encoding="utf-8"))
        previous = 0.0
        for segment in payload["segments"]:
            start, end = segment["start"], segment["end"]
            if not all(math.isfinite(value) for value in (start, end)) or not previous <= start < end <= metadata["duration"] + .1:
                raise ValueError("ASR returned invalid or unordered segment timestamps")
            previous = end
            for word in segment["words"]:
                if not all(math.isfinite(word[key]) for key in ("start", "end", "probability")) or not start <= word["start"] <= word["end"] <= end + .01:
                    raise ValueError("ASR returned invalid word timestamps")
        payload.update({"source_id": identity, "audio_path": artifact_path(workspace, source),
                        "timebase": "seconds-from-audio-start", "model": model, **metadata,
                        "accuracy": "unreviewed", "coverage": {"start": 0.0, "end": metadata["duration"]}})
        staged.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        publish(staged, destination)
    return {"status": "ok", "transcript_path": artifact_path(workspace, destination),
            "speech_detected": bool(payload["segments"]), "segment_count": len(payload["segments"]), **payload}


def speech_synthesize(workspace: Path, text: str, output_path: str, voice: str | None = None,
                      rate: int = 180, reference_audio_path: str | None = None) -> dict:
    """Render plain text through an installed stock macOS say or eSpeak voice."""
    if not isinstance(text, str) or not text.strip() or "\x00" in text:
        raise ValueError("text must contain nonempty spoken text")
    rate = _integer(rate, "rate", 40, 600)
    if voice is not None and (not isinstance(voice, str) or not voice.strip() or "\x00" in voice):
        raise ValueError("voice must be a stock voice name")
    if reference_audio_path is not None:
        input_path(workspace, reference_audio_path)
        raise CapabilityUnavailable("Stock speech synthesis does not support reference voices; no voice substitution was performed")
    destination = _wav_destination(workspace, output_path)
    executable = shutil.which("say") or shutil.which("espeak-ng") or shutil.which("espeak")
    if executable is None:
        raise CapabilityUnavailable("Install a local stock speech engine: macOS say, espeak-ng, or espeak")
    backend = Path(executable).name
    with tempfile.TemporaryDirectory(dir=workspace, prefix=".speech-") as directory:
        temporary = Path(directory)
        script = temporary / "speech.txt"
        script.write_text(text, encoding="utf-8")
        staged = temporary / "speech.wav"
        if backend == "say":
            if "[[" in text:
                raise ValueError("macOS speech control markup is unsupported; provide plain spoken text")
            if voice:
                available = [line.split("#", 1)[0].strip().rsplit(None, 1)[0]
                             for line in run([executable, "-v", "?"]).stdout.splitlines() if line.strip()]
                if voice not in available:
                    raise CapabilityUnavailable(f"macOS stock voice is not installed: {voice}")
            intermediate = temporary / "speech.aiff"
            run([executable, "-f", script, "-o", intermediate, "--file-format=AIFF", "-r", str(rate),
                 *(["-v", voice] if voice else [])], timeout=3600)
            run(["ffmpeg", "-v", "error", "-nostdin", "-n", "-i", intermediate,
                 "-c:a", "pcm_s16le", staged], timeout=3600)
        else:
            run([executable, "-f", script, "-w", staged, "-s", str(rate), *(["-v", voice] if voice else [])], timeout=3600)
        try:
            result = _publish_audio(workspace, staged, destination, backend)
        except ValueError as error:
            if backend == "say" and "no finite positive duration" in str(error):
                raise CapabilityUnavailable("macOS say produced no audio frames; its native speech service may be inaccessible in this sandbox") from error
            raise
        return {**result, "voice": voice or "system-default", "rate": rate}


def audio_separate(workspace: Path, audio_path: str, output_dir: str, model: str = "htdemucs",
                   stem: str | None = "vocals") -> dict:
    """Run installed Demucs against an explicit local checkpoint repository."""
    source = input_path(workspace, audio_path)
    destination = resolve_output(workspace, output_dir)
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", model):
        raise ValueError("model must be a Demucs model name in the configured local repository")
    if stem not in (None, "vocals", "drums", "bass", "other", "guitar", "piano"):
        raise ValueError("stem must name a supported Demucs stem or be null for all stems")
    repository = _configured_path("EDITTUDE_DEMUCS_REPO")
    _audio(source)
    with tempfile.TemporaryDirectory(dir=workspace, prefix=".separate-") as directory:
        temporary = Path(directory)
        args = ["--repo", repository, "-n", model, "--float32", "-o", temporary]
        if stem:
            args += ["--two-stems", stem]
        _model_run("DEMUCS", """
import os, runpy, sys, torch
os.environ.setdefault('PYTORCH_ENABLE_MPS_FALLBACK', '1')  # Unsupported Metal ops fall back to CPU.
device = os.environ.get('EDITTUDE_DEVICE') or ('cuda' if torch.cuda.is_available()
    else 'mps' if torch.backends.mps.is_available() else 'cpu')
sys.argv = ['demucs.separate', '--device', device, *sys.argv[1:]]
runpy.run_module('demucs.separate', run_name='__main__')
""", [*args, source])
        generated = sorted(temporary.rglob("*.wav"))
        if not generated or len({path.name for path in generated}) != len(generated):
            raise RuntimeError("Demucs did not produce an unambiguous set of WAV stems")
        measurements = {path.name: _audio(path) for path in generated}
        destination.mkdir()  # Refuses a destination created while inference was running.
        for path in generated:
            publish(path, destination / path.name)
    return {"status": "ok", "source_path": artifact_path(workspace, source), "backend": "demucs", "model": model,
            "stems": [{"name": name.removesuffix(".wav"), "audio_path": artifact_path(workspace, destination / name), **meta}
                      for name, meta in measurements.items()], "verification": {"decoded": True, "listening": False}}


def _singing_input(analysis: dict) -> dict:
    """Convert a Mandarin syllable score for DiffSinger's documented word frontend."""
    if not isinstance(analysis, dict) or not str(analysis.get("language", "")).lower().startswith("zh"):
        raise ValueError("This DiffSinger adapter supports the Mandarin word frontend; analysis.language must be zh")
    duration = analysis.get("duration_seconds")
    if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
        raise ValueError("analysis.duration_seconds must be finite and positive")
    units = analysis.get("units")
    if not isinstance(units, list) or not units:
        raise ValueError("analysis.units must contain timed lyric/rest units")
    texts, pitches, durations, ids = [], [], [], set()
    cursor = 0.0
    for unit in units:
        if not isinstance(unit, dict) or type(unit.get("id")) not in (str, int) or unit["id"] == "" or unit["id"] in ids:
            raise ValueError("Each musical unit must have a unique stable id")
        ids.add(unit["id"])
        start, end = unit.get("start"), unit.get("end")
        if not all(type(t) in (int, float) and math.isfinite(t) for t in (start, end)) or not math.isclose(start, cursor, abs_tol=1e-6) or end <= start:
            raise ValueError("Musical units must be contiguous finite positive intervals")
        notes = unit.get("notes")
        if unit.get("kind") == "rest":
            if notes or unit.get("text"):
                raise ValueError("Rest units must have empty text and notes")
            texts.append("AP"); pitches.append("rest"); durations.append(str(end - start))
        elif unit.get("kind") == "lyric":
            if not isinstance(unit.get("text"), str) or not re.fullmatch(r"[\u3400-\u9fff]", unit["text"]):
                raise ValueError("Each Mandarin lyric unit must contain one sung Chinese character")
            if not isinstance(notes, list) or not notes:
                raise ValueError("Lyric units require sequential notes")
            pitch_group, duration_group, note_cursor = [], [], start
            for note in notes:
                if not isinstance(note, dict):
                    raise ValueError("Each note must contain pitch, start and end")
                left, right = note.get("start"), note.get("end")
                pitch = note.get("pitch")
                if type(pitch) is int and 0 <= pitch <= 127:
                    pitch = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"][pitch % 12] + str(pitch // 12 - 1)
                if not isinstance(pitch, str) or not re.fullmatch(r"[A-G](?:#|b)?-?\d(?:/[A-G](?:#|b)?-?\d)?", pitch):
                    raise ValueError("Notes need a valid pitch name or MIDI pitch number")
                if not all(type(t) in (int, float) and math.isfinite(t) for t in (left, right)) or not math.isclose(left, note_cursor, abs_tol=1e-6) or right <= left or right > end + 1e-6:
                    raise ValueError("Notes must sequentially cover their lyric unit")
                pitch_group.append(pitch); duration_group.append(str(right - left)); note_cursor = right
            if not math.isclose(note_cursor, end, abs_tol=1e-6):
                raise ValueError("Notes do not cover the complete lyric unit")
            texts.append(unit["text"]); pitches.append(" ".join(pitch_group)); durations.append(" ".join(duration_group))
        else:
            raise ValueError("Musical unit kind must be lyric or rest")
        cursor = end
    if not math.isclose(cursor, duration, abs_tol=1e-6):
        raise ValueError("Musical units do not cover duration_seconds")
    return {"text": " ".join(texts), "notes": " | ".join(pitches), "notes_duration": " | ".join(durations), "input_type": "word"}


def singing_synthesize(workspace: Path, analysis_path: str, output_path: str) -> dict:
    """Render a Mandarin timed score through an explicitly configured DiffSinger CLI."""
    source = input_path(workspace, analysis_path)
    destination = _wav_destination(workspace, output_path)
    analysis = json.loads(source.read_text(encoding="utf-8"))
    payload = _singing_input(analysis)
    backend = _configured_path("EDITTUDE_DIFFSINGER_DIR")
    experiment = os.environ.get("EDITTUDE_DIFFSINGER_EXP") or DIFFSINGER_EXP
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", experiment):
        raise CapabilityUnavailable("Set EDITTUDE_DIFFSINGER_EXP to the installed checkpoint experiment name")
    entry = backend / "inference/svs/ds_e2e.py"
    options = backend / "utils/hparams.py"
    if not entry.is_file() or not options.is_file() or "--output-dir" not in options.read_text(encoding="utf-8"):
        raise CapabilityUnavailable("DiffSinger needs inference/svs/ds_e2e.py with --inp, --exp_name, --save_name and --output-dir support")
    with tempfile.TemporaryDirectory(dir=workspace, prefix=".singing-") as directory:
        temporary = Path(directory)
        request = temporary / "score.json"
        request.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        _model_run("DIFFSINGER", """
import runpy, sys
from pathlib import Path
entry = Path(sys.argv[1])
sys.path.insert(0, str(entry.parents[2]))
sys.argv = [str(entry), *sys.argv[2:]]
runpy.run_path(str(entry), run_name='__main__')
""", [entry, "--exp_name", experiment, "--inp", request, "--save_name", "vocal", "--output-dir", temporary, "--infer"], cwd=backend)
        result = _publish_audio(workspace, temporary / "vocal.wav", destination, "diffsinger")
    difference = result["duration"] - analysis["duration_seconds"]
    return {**result, "analysis_path": artifact_path(workspace, source), "duration_difference": difference,
            "timing_matches_score": abs(difference) <= .1, "timing_tolerance": .1, "language": "zh"}


def voice_convert(workspace: Path, audio_path: str, reference_audio_path: str, output_path: str,
                  diffusion_steps: int = 30) -> dict:
    """Convert singing timbre with pitch-conditioned local Seed-VC, preserving pitch by request."""
    source = input_path(workspace, audio_path)
    reference = input_path(workspace, reference_audio_path)
    destination = _wav_destination(workspace, output_path)
    if type(diffusion_steps) is not int or not 1 <= diffusion_steps <= 200:
        raise ValueError("diffusion_steps must be an integer from 1 to 200")
    backend = _configured_path("EDITTUDE_SEED_VC_DIR")
    checkpoint = _configured_path("EDITTUDE_SEED_VC_CHECKPOINT", directory=False)
    config = _configured_path("EDITTUDE_SEED_VC_CONFIG", directory=False)
    entry = backend / "inference.py"
    if not entry.is_file():
        raise CapabilityUnavailable(f"Seed-VC inference.py missing in {backend}")
    source_metadata = _audio(source)
    _audio(reference)
    with tempfile.TemporaryDirectory(dir=workspace, prefix=".voice-") as directory:
        temporary = Path(directory)
        _model_run("SEED_VC", """
import runpy, sys
from pathlib import Path
entry = Path(sys.argv[1])
sys.path.insert(0, str(entry.parent))
sys.argv = [str(entry), *sys.argv[2:]]
runpy.run_path(str(entry), run_name='__main__')
""", [entry, "--source", source, "--target", reference, "--output", temporary, "--checkpoint", checkpoint,
        "--config", config, "--diffusion-steps", str(diffusion_steps), "--length-adjust", "1.0",
        "--inference-cfg-rate", "0.7", "--f0-condition", "True", "--auto-f0-adjust", "False",
        "--semi-tone-shift", "0", "--fp16", "False"], cwd=backend)
        generated = list(temporary.glob("*.wav"))
        if len(generated) != 1:
            raise RuntimeError("Seed-VC did not produce exactly one WAV output")
        result = _publish_audio(workspace, generated[0], destination, "seed-vc")
    return {**result, "source_path": artifact_path(workspace, source), "reference_audio_path": artifact_path(workspace, reference),
            "duration_difference": result["duration"] - source_metadata["duration"],
            "settings": {"f0_condition": True, "auto_f0_adjust": False, "semitone_shift": 0, "length_adjust": 1.0,
                         "diffusion_steps": diffusion_steps}, "pitch_and_identity_review": "unverified"}


VISION_URL = "http://localhost:1234/v1"  # LM Studio. Ollama: http://localhost:11434/v1
VISION_MODEL = "qwen/qwen3.8-27b"


def _vision() -> tuple[str, str]:
    return ((os.environ.get("EDITTUDE_VISION_URL") or VISION_URL).rstrip("/"),
            os.environ.get("EDITTUDE_VISION_MODEL") or VISION_MODEL)


def image_describe(workspace: Path, image_paths: list[str], question: str) -> dict:
    """Ask a local OpenAI-compatible vision model about up to 8 images."""
    if not image_paths or len(image_paths) > 8:
        raise ValueError("Supply 1 to 8 image paths")
    url, model = _vision()
    content: list[dict] = [{"type": "text", "text": question}]
    for value in image_paths:
        path = input_path(workspace, value)
        kind = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".webp": "webp"}.get(path.suffix.lower())
        if kind is None:
            raise ValueError(f"Not a jpg, png or webp image: {value}")
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:image/{kind};base64,{data}"}})
    body = json.dumps({"model": model, "temperature": 0.2,
                       "messages": [{"role": "user", "content": content}]}).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 - user-configured local endpoint.
        f"{url}/chat/completions", data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ.get('EDITTUDE_VISION_API_KEY') or 'local'}"})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310
            reply = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"{model} at {url}: {error.read().decode('utf-8', 'replace')[-500:]}") from error
    except OSError as error:
        raise CapabilityUnavailable(
            f"No vision model at {url} ({error}). Start it, or run: edittude config set vision-url URL") from error
    description = ((reply.get("choices") or [{}])[0].get("message") or {}).get("content")
    if not isinstance(description, str):
        raise RuntimeError(f"{model} at {url} returned no message content: {json.dumps(reply)[:500]}")
    return {"model": model, "images": len(image_paths), "description": description.strip()}


def capabilities() -> dict:
    """Discover executables/configuration without importing models or downloading weights."""
    result = {}
    modules = {"ASR": "faster_whisper", "DEMUCS": "demucs", "DIFFSINGER": "torch", "SEED_VC": "torch"}
    runtimes, errors = {}, {}
    for backend in modules:
        try:
            runtimes[backend] = _runtime(backend)
        except CapabilityUnavailable as error:
            errors[backend] = str(error)
    found = {}
    for runtime in set(runtimes.values()):
        try:
            response = run([runtime, "-c", "import importlib.util,json; print(json.dumps({name: importlib.util.find_spec(name) is not None for name in ['faster_whisper','demucs','torch']}))"], timeout=30)
            found[runtime] = json.loads(response.stdout)
        except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
            found[runtime] = {"error": str(error)}
    for backend, tool in (("ASR", "speech_transcribe"), ("DEMUCS", "audio_separate"),
                          ("DIFFSINGER", "singing_synthesize"), ("SEED_VC", "voice_convert")):
        runtime = runtimes.get(backend)
        reason = errors.get(backend) or found.get(runtime, {}).get("error")
        if not reason and not found.get(runtime, {}).get(modules[backend]):
            reason = f"{modules[backend]} is not installed in the configured Python runtime; {INSTALL_HINT}"
        try:
            if backend == "ASR":
                _configured_path("EDITTUDE_ASR_MODEL_DIR")  # What model='base'/'local' resolves to; no downloads.
            elif backend == "DEMUCS":
                _configured_path("EDITTUDE_DEMUCS_REPO")
            elif backend == "DIFFSINGER":
                directory = _configured_path("EDITTUDE_DIFFSINGER_DIR")
                if not (directory / "inference/svs/ds_e2e.py").is_file():
                    raise CapabilityUnavailable("Configure a compatible DiffSinger CLI")
                if not (directory / "checkpoints" / (os.environ.get("EDITTUDE_DIFFSINGER_EXP") or DIFFSINGER_EXP)).is_dir():
                    raise CapabilityUnavailable(f"No DiffSinger checkpoint experiment installed; {INSTALL_HINT}, or set EDITTUDE_DIFFSINGER_EXP")
            elif backend == "SEED_VC":
                directory = _configured_path("EDITTUDE_SEED_VC_DIR")
                if not (directory / "inference.py").is_file():
                    raise CapabilityUnavailable("Configured Seed-VC directory lacks inference.py")
                _configured_path("EDITTUDE_SEED_VC_CHECKPOINT", directory=False)
                _configured_path("EDITTUDE_SEED_VC_CONFIG", directory=False)
        except CapabilityUnavailable as error:
            reason = reason or str(error)
        result[tool] = {"status": "unavailable" if reason else "configured", "runtime": runtime,
                        "reason": reason or "Package/configuration found; required cached model assets are checked at invocation",
                        "model_weights": "unverified", "downloads": False}
    url, model = _vision()
    try:
        with urllib.request.urlopen(f"{url}/models", timeout=2) as response:  # noqa: S310
            served = [item["id"] for item in json.load(response)["data"]]
        reason = None if model in served else f"{model} is not served at {url}; it serves {served}"
    except (OSError, ValueError, KeyError) as error:
        reason = f"No vision model at {url} ({error})"
    result["image_describe"] = {"status": "unavailable" if reason else "configured", "url": url,
                                "model": model, "reason": reason or "Endpoint serves the model"}
    engine = shutil.which("say") or shutil.which("espeak-ng") or shutil.which("espeak")
    result["speech_synthesize"] = {"status": "configured" if engine else "unavailable", "backend": engine,
                                    "reference_voice": False, "reason": "Stock executable found; voice/service availability is verified on render" if engine else "No say/espeak executable found"}
    return result
