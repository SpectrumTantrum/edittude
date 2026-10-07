# Portable video tools

This folder contains executable Python tools. `get_tools(workspace)` in `__init__.py` returns eleven ordinary callables; edittude loads and registers them with DeepAgents. The implementation imports no Edittude or HKU modules. Copy this folder and the sibling [skills folder](../skills/README.md) into another repository, then register the returned callables in that host.

## Run without a harness

Use Python 3.11 or later and install FFmpeg/ffprobe for media work. The skill validator additionally needs PyYAML from [requirements.txt](requirements.txt). Model libraries are optional and loaded only by the selected operation.

```sh
python tools/__main__.py list
python tools/__main__.py get_capabilities
python tools/__main__.py media_inspect '{"path":"/clips/input.mp4","modes":["probe","decode"]}'
python tools/__main__.py media_render '{"request":{"op":"extract_audio","path":"/clips/input.mp4","output":"/artifacts/audio.wav"}}'
```

Pass `--workspace PATH` when the process is running elsewhere. Media-tool paths are relative to that workspace; `/clips/input.mp4` means its `clips/input.mp4`. Real absolute paths inside the workspace also work. Traversal, symlink escapes, and overwriting existing outputs are rejected. The harness filesystem and shell use host paths, so prefix returned media artifact paths with the workspace before reading them through those tools. Copy outside source media into the workspace when using these portable tools.

## Registered operations

| Tool | Actual operation |
| --- | --- |
| `get_capabilities` | Inspect executables and optional backend configuration without downloading models. |
| `media_inspect` | Probe streams, extract timestamped frames/audio previews, measure loudness, or fully decode media. |
| `media_render` | Extract, resample, normalize, trim, concatenate, mix, mux, or render a shot timeline using FFmpeg. |
| `audio_timing` | Measure silence, RMS energy, and onset candidates. These are not guaranteed musical beats. |
| `score_read` | Read MIDI tracks, notes, tempo changes and timing. The agent selects the melody track. |
| `speech_transcribe` | Run cached faster-whisper and save source-linked timed JSON. |
| `image_describe` | Ask a local OpenAI-compatible vision model (LM Studio, Ollama) about 1 to 8 images. Set `EDITTUDE_VISION_URL` and `EDITTUDE_VISION_MODEL`, or use `edittude config`. |
| `speech_synthesize` | Render a local stock voice using macOS `say` or `espeak`; return decoded WAV and measured duration. |
| `audio_separate` | Invoke Demucs with a supplied local checkpoint repository and return actual stems. |
| `singing_synthesize` | Invoke a compatible local DiffSinger backend with validated Mandarin timed lyric/note units. |
| `voice_convert` | Invoke a configured local Seed-VC backend using supplied checkpoint/config and cached helper weights. |

Tool calls return `status: ok`, `error`, or `unavailable`. Missing models are explicit failures, never invented outputs. Backend discovery distinguishes configuration from successful inference. Generated audio/video is probed and decoded before publishing. Listening, factual relevance, and artistic quality still require agent/user review.

Writing narration, adapting scripts, choosing shots, assigning voices, and grouping timed phrases remain the agent's work. A [skill](../skills/README.md) names a registered tool call only where it needs a specific one. The [manifest](../skills/manifest.json) records the complete mapping.

## Render request fields

Pass the following fields inside `media_render(request={...})`. Every operation needs a fresh `output` path. Audio outputs use WAV or FLAC; video outputs use MP4, MOV, or MKV. Times are seconds.

| `op` | Required inputs and optional controls |
| --- | --- |
| `extract_audio` | `path`; optional `stream_index`, `sample_rate`, `channels`. |
| `resample` | `path`, `sample_rate`, `channels`. |
| `normalize` | `path`; `integrated_lufs=-16`, `true_peak_dbtp=-1.5`, `loudness_range=11`, `tolerance_lu=0.5`. Uses measured two-pass normalization and verifies the result. |
| `trim` | `path`, `start`, `end`. Video is re-encoded for precise cuts. |
| `concat` | `paths`, an ordered list of audio files or video files. Video also accepts the timeline size, fit, and audio settings below. |
| `mix` | `path` for foreground and `music`; `foreground_gain=1`, `music_gain=0.16`, `loop_music=true`, optional `duration`, `foreground_offset`, `music_offset`, `fade_in`, `fade_out`. Clipping fails before publication. |
| `mux` | `path` for picture and `audio`; optional `audio_offset`. Preserves the whole picture and pads or trims replacement audio. Other tracks are omitted. |
| `timeline` | `shots`, each with `id`, `path`, `source_start`, `source_end`, output `start`, output `end`, and optional `source_audio` of `keep` or `mute`. Uses contiguous hard cuts at original speed. |

Timeline settings are `width`, `height`, `fps`, `fit` of `pad` or `crop`, and `audio_policy` of `keep`, `mute`, or `replace`. Replacement requires `audio`. Gaps, overlaps, unsupported retiming, and missing media fail explicitly. This renderer does not add transitions or subtitles; use the host's shell/editor for those operations.

```json
{"request":{"op":"timeline","output":"/artifacts/edit.mp4","width":1280,"height":720,"fps":30,"fit":"pad","audio_policy":"keep","shots":[{"id":"shot-01","path":"/clips/input.mp4","source_start":1,"source_end":3,"start":0,"end":2}]}}
```

`audio_timing` accepts `request` with `path`, `method`, optional `start`, `end`, and JSON `output`. Silence options are `threshold_db=-35` and `minimum_silence=0.2`. RMS/onset options are `window_ms=50`, `threshold_ratio=0.35`, `minimum_interval=0.25`, and optional `include_envelope=true`. RMS/onset analysis always decodes a mono 16 kHz copy, and options belonging to the other method, or to a library this tool does not use, are ignored without an error; the returned `settings` report what was actually applied. Times refer to the original input, including when only a range is analyzed.

`score_read` accepts `request` with MIDI `path`, optional numeric `track`, and optional JSON `output`. It returns notes, rests, and integrated tempo timing. Lyric alignment and melody selection remain the agent's decisions.

## Optional model configuration

`EDITTUDE_MODEL_PYTHON` selects a Python interpreter for optional engines. Per-engine overrides are `EDITTUDE_ASR_PYTHON`, `EDITTUDE_DEMUCS_PYTHON`, `EDITTUDE_DIFFSINGER_PYTHON`, and `EDITTUDE_SEED_VC_PYTHON`. This lets a model use its own compatible environment without putting its dependencies into the harness. No developer-specific paths are built into these tools.

- ASR needs `faster_whisper` in its interpreter and a cached model name. For a local weight directory, set `EDITTUDE_ASR_MODEL_DIR` and call with `model="local"`. It uses `local_files_only=True`. Word timestamps are recognition estimates, not forced alignment.
- Stock speech needs an installed system voice. Requested reference-voice cloning returns `unavailable`; it never silently substitutes a stock voice.
- Demucs needs its package plus `EDITTUDE_DEMUCS_REPO`, a local checkpoint directory.
- DiffSinger needs `EDITTUDE_DIFFSINGER_DIR`, `EDITTUDE_DIFFSINGER_EXP` (default `0228_opencpop_ds100_rel`), compatible weights and the CLI contract checked in [models.py](models.py). The adapter supports Mandarin lyric/note units and explicit rests; unsupported inputs fail before inference.
- Seed-VC needs `EDITTUDE_SEED_VC_DIR`, `EDITTUDE_SEED_VC_CHECKPOINT`, `EDITTUDE_SEED_VC_CONFIG`, and cached auxiliary weights.

`edittude-media models install --models seed-vc,diffsinger` supplies all four variables' defaults. See the README for the GPL-3.0 and non-commercial-checkpoint terms those two carry.

Neural model subprocesses run offline. Supply missing dependencies/weights explicitly, then inspect capabilities again. A configured backend is not an inference-quality guarantee.

`singing_synthesize` reads `analysis_path` in the [shared score format](../skills/video-transcribe-melody/SKILL.md). For this adapter, use `language: "zh"` and one Chinese character per lyric unit. Notes may use pitch names such as `C4` or MIDI numbers. Explicit rests and all notes must cover the complete duration without gaps. Split phrases in the agent when the model's context limit requires it.

## Validation

```sh
python tools/validate.py
python tools/smoke_media.py
```

The first checks the 33 skills and provenance manifest. Optional `--source PATH` verifies the original HKU source snapshot. The smoke check uses synthetic media and writes its results in a fresh temporary directory. Harness and tool integration tests live in the host repository's `tests/` directory.

In edittude, run the host integration checks with `python -m unittest discover -s tests -v`. To include cached ASR, set `EDITTUDE_TEST_ASR_PYTHON` to an interpreter with faster-whisper and a cached base model. The stock-speech test needs access to the operating system's speech service.

Those checks passed locally, including actual rendering, source preservation, model failure paths, stock speech, cached speech recognition, and skill/tool use by the main agent and an inventory subagent. A live DeepSeek run also read a skill and called inspection/rendering tools successfully. Demucs, DiffSinger, and Seed-VC inference were not run; those adapters need the configured model assets above.
