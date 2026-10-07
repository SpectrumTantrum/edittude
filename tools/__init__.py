"""Portable video tools. No harness imports; get_tools returns ordinary callables."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from . import media, models
from .common import CapabilityUnavailable


def get_tools(workspace: str | Path) -> list:
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Workspace is not a directory: {root}")

    def virtual(text: str) -> str:
        """Report host paths under the workspace as the virtual paths tools accept."""
        return text.replace(str(root), "")

    def invoke(function, *args, **kwargs):
        try:
            result = function(root, *args, **kwargs)
            result.setdefault("status", "ok")
            return result
        except CapabilityUnavailable as exc:
            return {"status": "unavailable", "error": virtual(str(exc))}
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            return {"status": "error", "error": virtual(exc.stderr or str(exc))[-2000:]}
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, ImportError) as exc:
            return {"status": "error", "error": virtual(str(exc))}

    def get_capabilities() -> dict:
        """Inspect installed media executables and optional model backends without downloads.

        Read this before model-dependent work. Registered tools can report unavailable
        when a runtime, checkpoint, or supported feature is missing. Package presence
        does not prove model readiness. Media paths are relative to this workspace;
        /clip.mp4 means the workspace's clip.mp4, not the host filesystem root.
        """
        executables = {name: shutil.which(name) for name in ("ffmpeg", "ffprobe")}
        return {
            "status": "ok", "executables": executables,
            "media_ready": all(executables.values()),
            "models": models.capabilities(),
            "tools": [function.__name__ for function in registered],
            "path_mode": "workspace-relative or virtual absolute; outputs never overwrite",
        }

    def media_inspect(path: str, modes: list[str] | None = None,
                      timestamps: list[float] | None = None,
                      output_dir: str = "artifacts/previews",
                      audio_preview: dict | None = None) -> dict:
        """Probe media or create timestamped previews and measure/decode actual content.

        modes defaults to ['probe']; supported modes are probe, frames, loudness,
        decode, audio_preview. For frames supply timestamps in source seconds and
        an output_dir. audio_preview uses {output, start, duration} in seconds.
        Example: path='/clips/source.mp4', modes=['probe','frames'],
        timestamps=[0.5,2.0]. Returned artifact paths use this workspace's virtual
        root. Decode/measurement success does not establish perceptual quality.
        """
        request = {"path": path, "modes": modes or ["probe"],
                   "timestamps": timestamps or [], "output_dir": output_dir}
        if audio_preview is not None:
            request["audio_preview"] = audio_preview
        return invoke(media.media_inspect, request)

    def media_render(request: dict) -> dict:
        """Render a bounded audio operation or explicit video timeline to a NEW file.

        request requires op and output. Supported ops: extract_audio, resample,
        normalize, trim, concat, mix, mux, timeline. Single sources use path;
        concat uses paths; mix uses path plus music; mux uses path plus audio;
        timeline uses shots. Times are seconds. Examples:
        {'op':'extract_audio','path':'/clip.mp4','output':'/audio.wav'};
        {'op':'resample','path':'/audio.wav','sample_rate':16000,'channels':1,
        'output':'/model-input.wav'}. Read the workspace's tools/README.md for fields.
        Originals and existing outputs are preserved. Inspect returned properties.
        """
        return invoke(media.media_render, request)

    def audio_timing(request: dict) -> dict:
        """Measure silence, RMS energy, or onsets with source-relative timestamps.

        request contains path and method ('silence', 'rms', or 'onsets'), with
        optional analysis settings and output JSON path. Energy peaks are not a
        guaranteed musical beat grid. Example: {'path':'/music.wav','method':'onsets'}.
        Choose editorial cut points from the returned evidence using the rhythm skill.
        """
        return invoke(media.audio_timing, request)

    def score_read(request: dict) -> dict:
        """Read MIDI tracks, tempo changes, and notes with correctly integrated seconds.

        request contains path, optional melody track index and output JSON path.
        Example: {'path':'/song.mid'}. Inspect track candidates before selecting
        the vocal melody; lyric character count does not identify the correct track.
        This parses MIDI, not a recording of music.
        """
        return invoke(media.score_read, request)

    def speech_transcribe(audio_path: str, output_path: str,
                          language: str | None = None, model: str = "base",
                          source_id: str | None = None) -> dict:
        """Transcribe audio to source-linked timed JSON with cached faster-whisper.

        Requires an installed optional ASR runtime and already cached model.
        For local weights use model='local' with EDITTUDE_ASR_MODEL_DIR configured.
        No downloads. Use language when known and preserve an upstream source_id.
        Times are relative to this input audio; retain slice offsets separately.
        output_path is a fresh JSON file. Forced alignment is not provided.
        """
        return invoke(models.speech_transcribe, audio_path, output_path, language,
                      model, source_id)

    def speech_synthesize(text: str, output_path: str, voice: str | None = None,
                          rate: int = 180, reference_audio_path: str | None = None,
                          utterance_id: str | None = None) -> dict:
        """Synthesize text with an installed system voice and return measured WAV audio.

        Uses macOS say or espeak. rate is words per minute. Stock voices do not
        clone references; a requested reference voice returns unavailable rather
        than silently substituting a stock voice. Preserve scene/utterance identity
        through utterance_id. Stage directions should not be included in text.
        """
        result = invoke(models.speech_synthesize, text, output_path, voice, rate,
                        reference_audio_path)
        if utterance_id is not None and result.get("status") == "ok":
            result["id"] = utterance_id
        return result

    def audio_separate(audio_path: str, output_dir: str, model: str = "htdemucs",
                       stem: str | None = "vocals") -> dict:
        """Separate supported stems using Demucs and an explicit LOCAL checkpoint repo.

        Requires EDITTUDE_DEMUCS_REPO and an installed Demucs runtime; no downloads.
        Set stem to null for all stems.
        Returns actual stem paths and measurements. A decoded stem still needs
        listening review for old words, leakage, and processing artifacts.
        """
        return invoke(models.audio_separate, audio_path, output_dir, model, stem)

    def singing_synthesize(analysis_path: str, output_path: str) -> dict:
        """Render a validated DiffSinger score through an explicitly configured backend.

        Requires EDITTUDE_DIFFSINGER_DIR and its runtime/checkpoints. Read
        the workspace's tools/README.md for score format and backend requirements.
        No model downloads. Returns a real decoded vocal or a precise error;
        prepared lyrics are not a substitute for generated singing.
        """
        return invoke(models.singing_synthesize, analysis_path, output_path)

    def voice_convert(audio_path: str, reference_audio_path: str, output_path: str,
                       diffusion_steps: int = 30) -> dict:
        """Convert vocal timbre with an explicitly configured local Seed-VC backend.

        Requires local backend, checkpoint/config and cached auxiliary weights.
        Use an authorized target voice reference. This preserves source words;
        it does not generate new text. No downloads; recheck sync and diction.
        """
        return invoke(models.voice_convert, audio_path, reference_audio_path,
                      output_path, diffusion_steps)

    def image_describe(image_paths: list[str], question: str) -> dict:
        """LOOK at images. You cannot see images yourself; read_file on a jpg or png shows you nothing.

        Sends 1 to 8 jpg/png/webp files to the local vision model and returns its answer
        as text. Extract frames or a contact sheet first (edittude media thumbs, or
        media_inspect mode 'frames'), then ask a concrete question: 'For each image:
        location, subject, shot scale, camera motion, anything unusable.' The answer is
        a model's reading, not ground truth; ask again when a cut depends on a detail.
        """
        return invoke(models.image_describe, image_paths, question)

    registered = [get_capabilities, media_inspect, media_render, audio_timing,
                  score_read, speech_transcribe, speech_synthesize, audio_separate,
                  singing_synthesize, voice_convert, image_describe]
    return registered
